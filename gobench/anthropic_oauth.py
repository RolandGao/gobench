"""Direct Claude subscription transport, without a Claude Code agent runtime.

Based on Prime Agent 9c8230df67b378aaedc032f90e1ae8ba687cfe4a:
packages/ai/src/{utils/oauth/anthropic,providers/anthropic}.ts.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
HEADERS = {
    "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
    "user-agent": "claude-cli/2.1.261",
    "x-app": "cli",
}


class ClaudeOAuthError(RuntimeError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.body = {"retryable": retryable}


@contextlib.contextmanager
def _auth_lock(path):
    # Serialize arena workers independently of the Claude Code credential writer.
    # Recheck the file after refreshing to avoid replacing a renewed CLI login.
    lock = Path(f"{path}.arena-oauth.lock")
    deadline = time.monotonic() + 30
    while True:
        try:
            lock.mkdir(mode=0o700)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ClaudeOAuthError(
                    f"Timed out waiting for Claude credential lock: {lock}",
                    retryable=True,
                ) from None
            time.sleep(0.1)
    inode = lock.stat().st_ino
    stopped = threading.Event()
    compromised = threading.Event()

    def check():
        try:
            owned = lock.stat().st_ino == inode
        except OSError:
            owned = False
        if not owned or compromised.is_set():
            raise ClaudeOAuthError("Claude credential lock was lost")

    def heartbeat():
        while not stopped.wait(2):
            try:
                check()
                os.utime(lock, None)
            except (OSError, ClaudeOAuthError):
                compromised.set()
                return

    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    try:
        yield check
    finally:
        stopped.set()
        worker.join()
        with contextlib.suppress(OSError, ClaudeOAuthError):
            check()
            lock.rmdir()


def _read_auth(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cred = data["claudeAiOauth"]
        if not _valid_token(cred["accessToken"]):
            raise ValueError
        expires = cred["expiresAt"]
        if (isinstance(expires, bool) or not isinstance(expires, (int, float))
                or not math.isfinite(expires)):
            raise ValueError
        return data, cred
    except (OSError, KeyError, TypeError, ValueError):
        raise ClaudeOAuthError(
            f"A Claude subscription OAuth login is required at {path}; "
            "sign in with Claude Code, or set ARENA_ANTHROPIC_AUTH_PATH "
            "to your Claude Code .credentials.json"
        ) from None


def _valid_token(token):
    return isinstance(token, str) and token.startswith("sk-ant-oat")


def _refresh(refresh_token):
    request = urllib.request.Request(
        TOKEN_URL,
        data=json.dumps({
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        }).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # Never surface the response body: token endpoints may echo credentials.
        status = exc.code
        exc.close()
        raise ClaudeOAuthError(
            f"Claude OAuth refresh failed (HTTP {status}); sign in again if expired",
            retryable=status == 429 or status >= 500,
        ) from None
    except (OSError, ValueError):
        raise ClaudeOAuthError("Claude OAuth refresh failed", retryable=True) from None
    try:
        lifetime = result["expires_in"]
        if (not _valid_token(result["access_token"])
                or not isinstance(result["refresh_token"], str)
                or not result["refresh_token"]
                or isinstance(lifetime, bool)
                or not isinstance(lifetime, (int, float))
                or not math.isfinite(lifetime) or lifetime <= 0):
            raise ValueError
        return {
            "accessToken": result["access_token"],
            "refreshToken": result["refresh_token"],
            "expiresAt": time.time() * 1000 + lifetime * 1000,
        }
    except (KeyError, TypeError, ValueError):
        raise ClaudeOAuthError("Claude OAuth refresh returned invalid credentials") from None


def _fresh(cred):
    return time.time() * 1000 + 300_000 < cred["expiresAt"]


def access_token():
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if token is not None:
        if not _valid_token(token):
            raise ClaudeOAuthError("CLAUDE_CODE_OAUTH_TOKEN is not a Claude OAuth token")
        return token
    config_dir = Path(os.environ.get(
        "CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")
    )).expanduser()
    path = Path(os.environ.get(
        "ARENA_ANTHROPIC_AUTH_PATH", str(config_dir / ".credentials.json")
    )).expanduser().resolve()
    _, cred = _read_auth(path)
    if _fresh(cred):
        return cred["accessToken"]
    with _auth_lock(path) as check_lock:
        # Another game or Claude Code may have refreshed while we waited.
        data, cred = _read_auth(path)
        if _fresh(cred):
            return cred["accessToken"]
        refresh = cred.get("refreshToken")
        if not isinstance(refresh, str) or not refresh:
            raise ClaudeOAuthError("Claude OAuth login has expired; sign in with Claude Code again")
        try:
            updated = _refresh(refresh)
        except ClaudeOAuthError:
            # A concurrent CLI refresh may have consumed the old refresh token.
            _, latest = _read_auth(path)
            if _fresh(latest):
                return latest["accessToken"]
            raise
        data, latest = _read_auth(path)
        if (latest["accessToken"] != cred["accessToken"]
                or latest.get("refreshToken") != refresh):
            if _fresh(latest):
                return latest["accessToken"]
            raise ClaudeOAuthError("Claude credentials changed during refresh", retryable=True)
        data["claudeAiOauth"] = latest | updated
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", delete=False,
            ) as out:
                temporary = Path(out.name)
                os.fchmod(out.fileno(), 0o600)
                json.dump(data, out)
                out.flush()
                os.fsync(out.fileno())
            check_lock()
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return updated["accessToken"]


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    number = _number(value)
    if number is not None:
        try:
            datetime.fromtimestamp(number, timezone.utc)
            return number
        except (ValueError, OverflowError, OSError):
            return None
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.timestamp() if date.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _quota_wait(exc):
    """Attach retry timing without sleeping or discarding SDK error diagnostics.

    Subscription reset headers are best effort: use only exhausted windows,
    since successful requests also carry the next five-hour and weekly resets.
    Unknown timing is polled every five minutes, never sent to a paid API key.
    """
    headers = getattr(getattr(exc, "response", None), "headers", {})
    body = getattr(exc, "body", {})
    body = body if isinstance(body, dict) else {}
    detail = body.get("error", body)
    detail = detail if isinstance(detail, dict) else {}
    now = time.time()
    deadlines = []
    retry_after = headers.get("retry-after")
    seconds = _number(retry_after)
    if seconds is None and isinstance(retry_after, str):
        try:
            seconds = max(0, parsedate_to_datetime(retry_after).timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            pass
    for delay in (seconds, _number(body.get("retry_after")), _number(detail.get("retry_after"))):
        if delay is not None and _timestamp(now + delay) is not None:
            deadlines.append((now + delay, "rate_limit"))
    milliseconds = _number(headers.get("retry-after-ms"))
    if milliseconds is not None and _timestamp(now + milliseconds / 1000) is not None:
        deadlines.append((now + milliseconds / 1000, "rate_limit"))

    prefix = "anthropic-ratelimit-unified"
    claim = headers.get(f"{prefix}-representative-claim")
    windows = {"five_hour": "5h", "seven_day": "7d",
               "seven_day_sonnet": "7d-sonnet", "seven_day_opus": "7d-opus"}
    status = headers.get(f"{prefix}-status")
    if status not in {"allowed", "allowed_warning"}:
        reset = _timestamp(headers.get(f"{prefix}-reset"))
        if reset is not None and reset >= now:
            deadlines.append((reset, claim if claim in windows else "subscription"))
    for window, short in windows.items():
        utilization = _number(headers.get(f"{prefix}-{short}-utilization"))
        exhausted = (
            headers.get(f"{prefix}-{short}-status") in {"rejected", "rate_limited"}
            or utilization is not None and utilization >= 1
            or claim == window and status not in {"allowed", "allowed_warning"}
        )
        reset = _timestamp(headers.get(f"{prefix}-{short}-reset"))
        if exhausted and reset is not None and reset >= now:
            deadlines.append((reset, window))
    for field in ("reset_at", "resets_at"):
        reset = _timestamp(detail.get(field))
        if reset is not None and reset >= now:
            deadlines.append((reset, "subscription"))

    if deadlines:
        reset, window = max(deadlines, key=lambda item: item[0])
        exc.arena_quota_retry_after = max(0, reset - now) + 5
        exc.arena_quota = {"quota_window": window, "quota_reset_at": reset}
    else:
        exc.arena_quota_retry_after = 300
        exc.arena_quota = {"quota_window": "unknown"}


class AnthropicClient:
    """Subscription-only Messages transport; the arena owns waiting and retries."""

    auth_mode = "oauth"

    def __init__(self, client_cls, api):
        # Explicitly suppress environment API keys, including SDK fallback.
        self._client = client_cls(
            api_key="", auth_token=access_token(), base_url=api.base_url,
            default_headers=HEADERS, **dict(api.client_options),
        )
        self._client.api_key = None
        self.messages = self

    def close(self):
        self._client.close()

    def create(self, **request):
        self._client.auth_token = access_token()
        request["system"] = [{"type": "text", "text": IDENTITY}]
        try:
            return self._create_response(**request)
        except Exception as exc:
            exc.arena_auth_mode = "oauth"
            if getattr(exc, "status_code", None) == 429:
                _quota_wait(exc)
            raise

    def _create_response(self, **request):
        # Use the Anthropic SDK's streaming accumulator to retain thinking
        # signatures and cache usage for per-game conversation recovery.
        import anthropic
        import httpx2

        request.pop("stream", None)
        usage = {}
        try:
            with self._client.messages.stream(**request) as stream:
                completed = False
                for event in stream:
                    if event.type in {"message_start", "message_delta"}:
                        usage = stream.current_message_snapshot.usage.model_dump(mode="json")
                    if event.type == "message_stop":
                        completed = True
                if not completed:
                    raise ClaudeOAuthError(
                        "Claude OAuth stream ended without message_stop", retryable=True
                    )
                response = stream.get_final_message()
        except (httpx2.TransportError, ClaudeOAuthError) as exc:
            error = exc if isinstance(exc, ClaudeOAuthError) else ClaudeOAuthError(
                "Claude OAuth stream transport failed", retryable=True
            )
            error.arena_usage = usage
            raise error from None
        except anthropic.APIStatusError as exc:
            exc.arena_usage = usage
            # SSE errors arrive after HTTP 200; status-based retry alone misses
            # overloads and rate limits. Keep normal HTTP diagnostics intact.
            if exc.status_code == 200 and isinstance(exc.body, dict):
                detail = exc.body.get("error", exc.body)
                if isinstance(detail, dict) and detail.get("type") in {
                    "overloaded_error", "rate_limit_error", "api_error",
                }:
                    error = ClaudeOAuthError("Claude OAuth stream service error", retryable=True)
                    if detail.get("type") == "rate_limit_error":
                        error.status_code = 429
                    error.body.update(exc.body)
                    error.response = exc.response
                    error.arena_usage = usage
                    raise error from None
            raise
        if response.stop_reason not in {"end_turn", "stop_sequence"}:
            error = ClaudeOAuthError(f"Claude OAuth response stopped: {response.stop_reason}")
            error.arena_usage = response.usage.model_dump(mode="json")
            raise error
        return response
