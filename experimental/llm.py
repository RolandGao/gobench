"""Direct, durable LLM sessions (Python 3.12+, Linux; no agent runtime).

    from experimental.llm import LLM
    with LLM(name="gpt-5.6-sol", mode="multi_turn", auth="api_key",
             session_dir="sessions/demo") as model:
        answer = model.input("Explain ko in Go.", turn_id="question-1")
    with LLM(session_dir="sessions/demo") as model:
        assert model.get_turn("question-1").response.text == answer.text

Initial registry: OpenAI and Anthropic models already used by this repository.
API keys come from OPENAI_API_KEY / ANTHROPIC_API_KEY (or api_key_env).
OAuth reads an existing login via credential_file, OPENAI_OAUTH_FILE or
ANTHROPIC_OAUTH_FILE, falling back to the providers' local login files. It does
not launch a CLI. Credential refresh is serialized and durably guarded against
replaying a refresh token after an interrupted exchange.

Requests are stateless and never enable tools. Native output (including opaque
reasoning) is replayed locally. These endpoints cannot retrieve store=False
requests after a lost response: RecoveryRequired requires explicit abandon().
No credentials or HTTP headers are written to the session database.

Run offline tests: python -m unittest experimental.test_llm
"""
from __future__ import annotations

import base64
import contextlib
import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
from typing import Any
import uuid

import httpx


SCHEMA_VERSION = 1
_UNSET = object()
_BLOCKING = {"prepared", "running", "uncertain"}
_SECRET_KEYS = {"authorization", "x-api-key", "api_key", "access_token",
                "refresh_token", "id_token", "accesstoken", "refreshtoken"}


class LLMError(RuntimeError):
    """Public errors carry stable codes and optionally a durable turn identity."""

    code = "llm_error"

    def __init__(self, message: str, *, turn_id: str | None = None):
        super().__init__(message)
        self.turn_id = turn_id


class ConfigurationError(LLMError):
    code = "configuration"


class AuthenticationError(LLMError):
    code = "authentication"


class SessionBusy(LLMError):
    code = "session_busy"


class SessionError(LLMError):
    code = "session"


class TurnConflict(LLMError):
    code = "turn_conflict"


class ContextLimitError(LLMError):
    code = "context_limit"


class RequestFailed(LLMError):
    code = "request_failed"


class TurnCancelled(LLMError):
    code = "cancelled"


class RecoveryRequired(LLMError):
    code = "recovery_required"
    actions = ("get_turn", "reconcile", "abandon")


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    efforts: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    auth_methods: tuple[str, ...] = ("api_key", "oauth")
    max_output_tokens: int = 128_000


# Explicit entries, not prefix guessing. Update this registry as adapters are verified.
MODEL_REGISTRY = (
    ModelSpec("openai", "gpt-5.4", ("none", "low", "medium", "high", "xhigh")),
    ModelSpec("openai", "gpt-5.5", ("none", "low", "medium", "high", "xhigh")),
    ModelSpec("openai", "gpt-5.6-sol", ("none", "low", "medium", "high", "xhigh", "max"),
              ("gpt5.6-sol",)),
    ModelSpec("openai", "gpt-5.6-luna", ("none", "low", "medium", "high", "xhigh", "max"),
              ("gpt5.6-luna",)),
    ModelSpec("openai", "gpt-6-astra", ("low", "medium", "high", "xhigh", "max"),
              ("gpt6-astra",)),
    ModelSpec("anthropic", "claude-opus-5", ("low", "medium", "high", "xhigh", "max"),
              ("opus-5",)),
    ModelSpec("anthropic", "claude-fable-5-1", ("low", "medium", "high", "xhigh", "max"),
              ("fable-5.1",)),
)


def resolve_model(name: str) -> ModelSpec:
    matches = [m for m in MODEL_REGISTRY if name == m.model or name in m.aliases]
    if len(matches) != 1:
        raise ConfigurationError(f"Unknown or ambiguous model: {name!r}")
    return matches[0]


@dataclass(frozen=True)
class Response:
    text: str
    turn_id: str
    response_id: str | None
    usage: dict[str, Any] | None
    elapsed_seconds: float
    status: str
    finish_reason: str | None
    inference_seconds: float | None = None


@dataclass(frozen=True)
class Turn:
    turn_id: str
    state: str
    prompt: str
    response: Response | None
    error: dict[str, Any] | None
    attempts: tuple[dict[str, Any], ...]
    retry_of: str | None = None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def _redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if key.lower() in _SECRET_KEYS else _redact(item, secrets))
                for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_json(path: Path, value: Any) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(_json(value) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


@contextlib.contextmanager
def _file_lock(path: Path, *, blocking: bool = False):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise SessionBusy("Another process owns this session or credential store") from None
        yield
    finally:
        os.close(fd)  # Never unlink a lock file: other waiters may own its inode.


def _number(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _jwt_expiry(token: str) -> float | None:
    try:
        payload = token.split(".")[1]
        value = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"]
        return float(value) if _number(value) else None
    except (ValueError, KeyError, IndexError, TypeError):
        return None


class _Credentials:
    """Credentials never enter session state. Only non-secret source paths do."""

    def __init__(self, config: dict, transport=None):
        self.config = config
        self.transport = transport

    def get(self, rejected: str | None = None) -> tuple[str, dict[str, str]]:
        c = self.config
        if c["auth"] == "api_key":
            token = os.environ.get(c["api_key_env"], "").strip()
            if not token:
                raise AuthenticationError(f"Set {c['api_key_env']} to an API key")
            return token, {}
        path = Path(c["credential_file"])
        try:
            # For Anthropic also cooperate with the existing CLI-compatible locks.
            with contextlib.ExitStack() as stack:
                stack.enter_context(_file_lock(path.with_name(path.name + ".llm.lock"), blocking=True))
                check = lambda: None
                if c["provider"] == "anthropic":
                    from gobench.anthropic_oauth import _auth_lock
                    check = stack.enter_context(_auth_lock(path))
                data = self._read(path)
                token, expiry, refresh, headers = self._extract(data)
                if token != rejected and (expiry is None or expiry > time.time() + 60):
                    return token, headers
                if not refresh:
                    raise AuthenticationError("OAuth login expired or was rejected; sign in again")
                guard = path.with_name(path.name + ".llm-refresh.json")
                fingerprint = hashlib.sha256(refresh.encode()).hexdigest()
                if guard.exists():
                    prior = self._read(guard)
                    if prior.get("refresh_sha256") == fingerprint:
                        raise AuthenticationError(
                            "OAuth refresh was interrupted or rejected; renew the login before retrying")
                check()
                _atomic_json(guard, {"refresh_sha256": fingerprint, "state": "pending"})
                updated = self._refresh(refresh)
                check()
                # A different login may have replaced this file while HTTP was in flight.
                latest = self._read(path)
                if latest != data:
                    latest_token, latest_expiry, _, latest_headers = self._extract(latest)
                    if latest_token != rejected and (latest_expiry is None or latest_expiry > time.time()):
                        return latest_token, latest_headers
                    raise AuthenticationError("OAuth credentials changed during refresh; retry with the new login")
                if c["provider"] == "openai":
                    data["tokens"].update({k: updated[k] for k in
                                           ("access_token", "refresh_token", "id_token") if k in updated})
                    if "expires_in" in updated:
                        data["tokens"]["expires_at"] = time.time() + updated["expires_in"]
                    else:
                        # A new JWT's expiry replaces an old explicit expiry.
                        data["tokens"].pop("expires_at", None)
                    data["last_refresh"] = datetime.now(timezone.utc).isoformat()
                else:
                    data["claudeAiOauth"].update(
                        accessToken=updated["access_token"], refreshToken=updated.get("refresh_token", refresh),
                        expiresAt=(time.time() + updated["expires_in"]) * 1000)
                check()
                _atomic_json(path, data)
                guard.unlink()
                _fsync_dir(path.parent)
                token, _, _, headers = self._extract(data)
                return token, headers
        except (AuthenticationError, SessionBusy):
            raise
        except Exception:
            # Neither transport exception text nor token endpoint bodies are safe to log.
            raise AuthenticationError("Cannot read or renew OAuth credentials; check the login file") from None

    @staticmethod
    def _read(path: Path) -> dict:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("credential document must be an object")
        return data

    def _extract(self, data: dict):
        if self.config["provider"] == "openai":
            if data.get("auth_mode") != "chatgpt":
                raise AuthenticationError("The selected file is not an OpenAI OAuth login")
            cred = data["tokens"]
            token = cred["access_token"]
            account = cred["account_id"]
            if not isinstance(account, str) or not account:
                raise ValueError("missing account")
            expiry = cred.get("expires_at") or _jwt_expiry(token)
            headers = {"ChatGPT-Account-Id": account, "originator": "codex_cli_rs",
                       "OpenAI-Beta": "responses=experimental"}
            refresh = cred.get("refresh_token")
        else:
            cred = data["claudeAiOauth"]
            token = cred["accessToken"]
            expiry = cred["expiresAt"] / 1000
            refresh = cred.get("refreshToken")
            from gobench.anthropic_oauth import HEADERS
            headers = dict(HEADERS)
        if not isinstance(token, str) or not token or (expiry is not None and not _number(expiry)):
            raise ValueError("invalid token")
        if refresh is not None and (not isinstance(refresh, str) or not refresh):
            raise ValueError("invalid refresh token")
        return token, expiry, refresh, headers

    def _refresh(self, refresh: str) -> dict:
        if self.config["provider"] == "openai":
            url = "https://auth.openai.com/oauth/token"
            client_id = "app_EMoamEEZ73f0CkXaXp7hrann"
        else:
            from gobench.anthropic_oauth import TOKEN_URL, CLIENT_ID
            url, client_id = TOKEN_URL, CLIENT_ID
        with httpx.Client(transport=self.transport, timeout=30, follow_redirects=False) as client:
            response = client.post(url, json={"grant_type": "refresh_token",
                                              "refresh_token": refresh, "client_id": client_id},
                                   headers={"User-Agent": "gobench-experimental/1"})
            if response.status_code != 200:
                raise AuthenticationError("OAuth refresh rejected; renew the login")
            result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("access_token"), str) or not result["access_token"]:
            raise AuthenticationError("OAuth refresh returned invalid credentials; renew the login")
        if "refresh_token" in result and (not isinstance(result["refresh_token"], str) or not result["refresh_token"]):
            raise AuthenticationError("OAuth refresh returned an invalid refresh token")
        lifetime = result.get("expires_in")
        if lifetime is not None and (not _number(lifetime) or lifetime <= 0):
            raise AuthenticationError("OAuth refresh returned an invalid expiry")
        if self.config["provider"] == "anthropic" and lifetime is None:
            raise AuthenticationError("OAuth refresh omitted the token expiry")
        return result


class _WireError(Exception):
    def __init__(self, code: str, *, known: bool = False, status: int | None = None,
                 retryable: bool = False, partial: dict | None = None,
                 retry_after: float = 0.25):
        self.code, self.known, self.status = code, known, status
        self.retryable, self.partial = retryable, partial
        self.retry_after = retry_after


def _retry_after(value: str | None) -> float:
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            delay = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return 0.25
    return max(0.25, delay) if math.isfinite(delay) else 0.25


class _Adapter:
    def __init__(self, config: dict, transport=None):
        self.config = config
        self.transport = transport
        self.credentials = _Credentials(config, transport)

    def request(self, prompt: str, history: list) -> dict:
        c = self.config
        messages = copy.deepcopy(history) + [{"role": "user", "content": prompt}]
        request = {"model": c["model"], "stream": True}
        if c["provider"] == "openai":
            request.update(input=messages, store=False, include=["reasoning.encrypted_content"])
            if c["auth"] == "api_key":
                request["truncation"] = "disabled"
            if c["reasoning_effort"] is not None:
                request["reasoning"] = {"effort": c["reasoning_effort"]}
                if c["mode"] == "multi_turn" and c["model"].startswith(("gpt-5.6", "gpt-6-")):
                    request["reasoning"]["context"] = "all_turns"
            if c["max_output_tokens"] is not None:
                request["max_output_tokens"] = c["max_output_tokens"]
        else:
            request.update(messages=messages, max_tokens=c["max_output_tokens"])
            if c["reasoning_effort"] is not None:
                request.update(thinking={"type": "adaptive"},
                               output_config={"effort": c["reasoning_effort"]})
            if c["auth"] == "oauth":
                from gobench.anthropic_oauth import IDENTITY
                request["system"] = [{"type": "text", "text": IDENTITY}]
        return request

    def send(self, request: dict, token: str, extra_headers: dict, turn_id: str, observe,
             bind_client) -> dict:
        c = self.config
        headers = {"Accept": "text/event-stream", **extra_headers}
        if c["provider"] == "openai":
            url = ("https://api.openai.com/v1/responses" if c["auth"] == "api_key"
                   else "https://chatgpt.com/backend-api/codex/responses")
            headers.update(Authorization=f"Bearer {token}", **{"x-client-request-id": turn_id})
        else:
            url = "https://api.anthropic.com/v1/messages"
            headers["anthropic-version"] = "2023-06-01"
            headers["x-api-key" if c["auth"] == "api_key" else "Authorization"] = (
                token if c["auth"] == "api_key" else f"Bearer {token}")
        partial = {}
        try:
            with httpx.Client(transport=self.transport, timeout=c["timeout"], follow_redirects=False) as client:
                if not bind_client(client):
                    raise _WireError("cancelled_before_send", known=True)
                with client.stream("POST", url, json=request, headers=headers) as response:
                    observe("request_id", {"request_id": response.headers.get("x-request-id"),
                                           "http_status": response.status_code})
                    if response.status_code != 200:
                        body = response.read()
                        try:
                            error_body = json.loads(body)
                        except ValueError:
                            error_body = {"body": body.decode("utf-8", errors="replace")}
                        if not isinstance(error_body, dict):
                            error_body = {"body": error_body}
                        code = "provider_rejected"
                        if response.status_code in {400, 413, 422} and any(s in body.lower() for s in
                                (b"context_length", b"context window", b"prompt is too long", b"too many input tokens")):
                            code = "context_limit"
                        if response.status_code in {401, 403}:
                            code = "authentication"
                        raise _WireError(code, known=response.status_code in {400, 401, 403, 404, 413, 422, 429},
                                         status=response.status_code, retryable=response.status_code == 429,
                                         partial=error_body,
                                         retry_after=_retry_after(response.headers.get("retry-after")))
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        result = json.loads(response.read())
                    elif c["provider"] == "openai":
                        result = self._openai_stream(response, observe, partial)
                    else:
                        result = self._anthropic_stream(response, observe, partial)
                    self.parse(result)  # Reject malformed envelopes before treating them as complete.
                    return result
        except _WireError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise _WireError("connection_failed", known=True, retryable=True) from None
        except Exception:
            raise _WireError("transport_or_protocol", partial=partial or None) from None

    @staticmethod
    def _events(response):
        data = []
        for line in response.iter_lines():
            if not line:
                if data:
                    raw = "\n".join(data)
                    data = []
                    if raw != "[DONE]":
                        yield json.loads(raw)
            elif line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
        if data and "\n".join(data) != "[DONE]":
            yield json.loads("\n".join(data))

    def _openai_stream(self, response, observe, partial):
        items = {}
        for event in self._events(response):
            kind = event.get("type")
            if kind == "response.created":
                partial.update(event["response"])
                observe("response_id", {"response_id": partial.get("id")})
            elif kind == "response.output_text.delta":
                partial["partial_text"] = partial.get("partial_text", "") + event["delta"]
            elif kind == "response.output_item.done":
                items[event["output_index"]] = event["item"]
                partial["output"] = [items[i] for i in sorted(items)]
            elif kind in {"response.completed", "response.incomplete", "response.failed", "response.cancelled"}:
                result = event["response"]
                if items and not result.get("output"):
                    result["output"] = [items[i] for i in sorted(items)]
                return result
            elif kind == "error":
                raise _WireError("stream_error", partial=partial or None)
        raise _WireError("incomplete_stream", partial=partial or None)

    def _anthropic_stream(self, response, observe, partial):
        blocks = {}
        for event in self._events(response):
            kind = event.get("type")
            if kind == "message_start":
                partial.update(event["message"])
                observe("response_id", {"response_id": partial.get("id")})
            elif kind == "content_block_start":
                blocks[event["index"]] = copy.deepcopy(event["content_block"])
            elif kind == "content_block_delta":
                block, delta = blocks[event["index"]], event["delta"]
                key = {"text_delta": "text", "thinking_delta": "thinking",
                       "signature_delta": "signature"}.get(delta.get("type"))
                if key is None:
                    raise _WireError("unsupported_content", partial=partial or None)
                block[key] = block.get(key, "") + delta[key]
            elif kind == "message_delta":
                partial.update(event["delta"])
                if "usage" in event:
                    partial["usage"] = {**(partial.get("usage") or {}), **event["usage"]}
            elif kind == "message_stop":
                partial["content"] = [blocks[i] for i in sorted(blocks)]
                return partial
            elif kind == "error":
                raise _WireError("stream_error", partial=partial or None)
            partial["content"] = [blocks[i] for i in sorted(blocks)]
        raise _WireError("incomplete_stream", partial=partial or None)

    def parse(self, raw: dict) -> tuple[str, str, str | None, list]:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise ValueError("missing response identity")
        if self.config["provider"] == "openai":
            status = raw.get("status")
            if status not in {"completed", "incomplete", "failed", "cancelled"}:
                raise ValueError("missing terminal status")
            items = raw.get("output", [])
            text, refusal = [], False
            for item in items:
                if item.get("type") not in {"message", "reasoning"}:
                    raise ValueError("unexpected tool or output item")
                for block in item.get("content", []):
                    if block.get("type") == "output_text":
                        text.append(block["text"])
                    elif block.get("type") == "refusal":
                        text.append(block.get("refusal", ""))
                        refusal = True
            reason = ((raw.get("incomplete_details") or {}).get("reason") or
                      (raw.get("error") or {}).get("code") or ("refusal" if refusal else status))
            return "".join(text), status, reason, items
        blocks = raw["content"]
        if not isinstance(blocks, list) or not raw.get("stop_reason"):
            raise ValueError("incomplete message")
        if any(b.get("type") not in {"text", "thinking", "redacted_thinking"} for b in blocks):
            raise ValueError("unexpected tool or output block")
        text = "".join(b["text"] for b in blocks if b["type"] == "text")
        reason = raw["stop_reason"]
        return text, "incomplete" if reason == "max_tokens" else "completed", reason, [
            {"role": "assistant", "content": blocks}]


@dataclass
class _Flight:
    turn_id: str
    done: threading.Event = field(default_factory=threading.Event)
    started: float = field(default_factory=time.monotonic)
    error: BaseException | None = None
    result: Response | None = None
    client: httpx.Client | None = None


class LLM:
    """One exclusive owner per session. Different sessions may run concurrently.

    New sessions require name and auth; mode defaults to single_turn. Omitted
    settings on reopen use saved values. `None` explicitly disables a reasoning
    override. `timeout` bounds a whole input (including authentication/retries).
    API output defaults to 8192 tokens; OpenAI OAuth uses its endpoint's default
    and rejects an explicit output limit because that endpoint does not support it.
    `transport` is an httpx transport for offline tests, never persisted.
    """

    def __init__(self, *, session_dir, name=_UNSET, mode=_UNSET, auth=_UNSET,
                 reasoning_effort=_UNSET, credential_file=_UNSET, api_key_env=_UNSET,
                 timeout=_UNSET, max_output_tokens=_UNSET, max_attempts=_UNSET,
                 transport=None):
        self.path = Path(session_dir).expanduser().resolve()
        self._owner_pid = os.getpid()
        self._mutex = threading.RLock()
        self._db = None
        self._closed = False
        self._active = None
        self._lock_context = None
        supplied = dict(name=name, mode=mode, auth=auth, reasoning_effort=reasoning_effort,
                        credential_file=credential_file, api_key_env=api_key_env, timeout=timeout,
                        max_output_tokens=max_output_tokens, max_attempts=max_attempts)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_context = _file_lock(self.path.with_name(f".{self.path.name}.llm.lock"))
            self._lock_context.__enter__()
            self._open(supplied)
            self._adapter = _Adapter(self.config, transport)
            self.reconcile()
        except BaseException:
            if self._db is not None:
                self._db.close()
            if self._lock_context is not None:
                self._lock_context.__exit__(None, None, None)
            self._closed = True
            raise

    @property
    def config(self) -> dict:
        """A snapshot; modifying it never changes the durable session contract."""
        return copy.deepcopy(self._config)

    @staticmethod
    def _new_config(supplied):
        if supplied["name"] is _UNSET or supplied["auth"] is _UNSET:
            raise ConfigurationError("New sessions require name and explicit auth")
        spec = resolve_model(supplied["name"])
        auth = supplied["auth"]
        defaults = dict(mode="single_turn", reasoning_effort=None, credential_file=None,
                        api_key_env=None, timeout=300.0, max_attempts=2,
                        max_output_tokens=None if auth == "oauth" and spec.provider == "openai" else 8192)
        c = {k: defaults.get(k) if v is _UNSET else v for k, v in supplied.items()}
        c.update(provider=spec.provider, model=spec.model)
        c.pop("name")
        if c["mode"] not in {"single_turn", "multi_turn"}:
            raise ConfigurationError("mode must be single_turn or multi_turn")
        if auth not in spec.auth_methods:
            raise ConfigurationError("Unsupported authentication method for this model")
        if c["reasoning_effort"] is not None and c["reasoning_effort"] not in spec.efforts:
            raise ConfigurationError("Unsupported reasoning_effort for this model")
        if not _number(c["timeout"]) or c["timeout"] <= 0:
            raise ConfigurationError("timeout must be a positive finite number")
        if type(c["max_attempts"]) is not int or not 1 <= c["max_attempts"] <= 10:
            raise ConfigurationError("max_attempts must be an integer from 1 to 10")
        limit = c["max_output_tokens"]
        if auth == "oauth" and spec.provider == "openai":
            if limit is not None:
                raise ConfigurationError("OpenAI OAuth does not support max_output_tokens")
        elif type(limit) is not int or not 1 <= limit <= spec.max_output_tokens:
            raise ConfigurationError(f"max_output_tokens must be from 1 to {spec.max_output_tokens}")
        if auth == "api_key":
            if c["credential_file"] is not None:
                raise ConfigurationError("credential_file is only for OAuth")
            c["api_key_env"] = c["api_key_env"] or f"{spec.provider.upper()}_API_KEY"
            if not isinstance(c["api_key_env"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", c["api_key_env"]):
                raise ConfigurationError("api_key_env must be an environment-variable name")
        else:
            if c["api_key_env"] is not None:
                raise ConfigurationError("api_key_env is only for API-key authentication")
            if spec.provider == "openai":
                default = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
            else:
                default = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / ".credentials.json"
            c["credential_file"] = str(Path(c["credential_file"] or os.environ.get(
                f"{spec.provider.upper()}_OAUTH_FILE", default)).expanduser().resolve())
        c["context_policy"] = "error"
        return c

    def _check_config(self, supplied):
        for key, value in supplied.items():
            if value is _UNSET:
                continue
            if key == "name":
                # Saved canonical names do not depend on alias registry changes.
                if value == self.config["model"]:
                    continue
                spec = resolve_model(value)
                if (spec.provider, spec.model) != (self.config["provider"], self.config["model"]):
                    raise ConfigurationError("Conflicting model on resume")
            else:
                if key == "credential_file" and value is not None:
                    value = str(Path(value).expanduser().resolve())
                if value != self.config[key]:
                    raise ConfigurationError(f"Conflicting {key} on resume")
        # Reject adapters removed by a later version; never silently reinterpret saved settings.
        spec = next((m for m in MODEL_REGISTRY if m.model == self.config["model"] and
                     m.provider == self.config["provider"]), None)
        if spec is None:
            raise ConfigurationError("Saved model has no supported adapter")
        if (self.config["auth"] not in spec.auth_methods
                or self.config["mode"] not in {"single_turn", "multi_turn"}
                or self.config["reasoning_effort"] is not None
                and self.config["reasoning_effort"] not in spec.efforts):
            raise ConfigurationError("Saved configuration is no longer supported by this adapter")

    def _open(self, supplied):
        marker = self.path / "initializing.json"
        db_path = self.path / "session.sqlite3"
        if not self.path.exists():
            config = self._new_config(supplied)
            # Publish an initialization marker before the directory becomes visible.
            stage = Path(tempfile.mkdtemp(prefix=f".{self.path.name}.init-", dir=self.path.parent))
            try:
                _atomic_json(stage / marker.name, dict(schema=SCHEMA_VERSION, session_id=str(uuid.uuid4()),
                                                       config=config))
                os.rename(stage, self.path)
                _fsync_dir(self.path.parent)
            finally:
                if stage.exists():
                    for item in stage.iterdir():
                        item.unlink()
                    stage.rmdir()
        if not self.path.is_dir() or (not marker.exists() and not db_path.is_file()):
            raise SessionError("Unrecognized session directory; no files were overwritten")
        if marker.exists():
            try:
                initial = json.loads(marker.read_text())
                if initial["schema"] != SCHEMA_VERSION or not isinstance(initial["session_id"], str):
                    raise ValueError
                allowed = {marker.name, db_path.name, db_path.name + "-journal"}
                if any(p.name not in allowed for p in self.path.iterdir()):
                    raise ValueError
                self._config, self.session_id = initial["config"], initial["session_id"]
                self._check_config(supplied)
            except (KeyError, TypeError, ValueError, OSError):
                raise SessionError("Unrecognized initialization record") from None
        try:
            if db_path.is_symlink():
                raise SessionError("Session database must not be a symlink")
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA synchronous=FULL")
            if marker.exists():
                os.chmod(db_path, 0o600)
                with self._db:
                    self._db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                    self._db.execute("CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
                    self._db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, turn_id TEXT, data TEXT NOT NULL)")
                    for k, v in dict(schema=SCHEMA_VERSION, config=self.config, session_id=self.session_id,
                                     history=[]).items():
                        self._db.execute("INSERT OR IGNORE INTO meta VALUES (?, ?)", (k, _json(v)))
                marker.unlink()
                _fsync_dir(self.path)
            if self._meta("schema") != SCHEMA_VERSION:
                raise SessionError("Unsupported session schema")
            self._config, self.session_id = self._meta("config"), self._meta("session_id")
            self._check_config(supplied)
        except (sqlite3.Error, ValueError, KeyError, TypeError):
            raise SessionError("Invalid or corrupt session database") from None

    def _meta(self, key):
        row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if row is None:
            raise SessionError("Incomplete session metadata")
        return json.loads(row[0])

    def _ensure_open(self):
        if os.getpid() != self._owner_pid:
            raise SessionError("Session handles cannot be shared across fork; open a new session handle")
        if self._closed:
            raise SessionError("Session is closed")

    def _load(self, turn_id):
        row = self._db.execute("SELECT data FROM turns WHERE id=?", (turn_id,)).fetchone()
        if row is None:
            raise KeyError(turn_id)
        return json.loads(row[0])

    def _save(self, data):
        self._db.execute("INSERT INTO turns VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                         (data["turn_id"], _json(data)))

    def _event(self, kind, turn_id=None, **data):
        self._db.execute("INSERT INTO events(kind, turn_id, data) VALUES (?, ?, ?)",
                         (kind, turn_id, _json({"at": time.time(), **data})))

    @staticmethod
    def _turn(data):
        return Turn(data["turn_id"], data["state"], data["prompt"],
                    Response(**data["response"]) if data.get("response") else None,
                    data.get("error"), tuple(data["attempts"]), data.get("retry_of"))

    def get_turn(self, turn_id: str) -> Turn:
        with self._mutex:
            self._ensure_open()
            return self._turn(self._load(turn_id))

    def list_turns(self) -> list[Turn]:
        with self._mutex:
            self._ensure_open()
            return [self._turn(json.loads(r[0])) for r in self._db.execute("SELECT data FROM turns ORDER BY rowid")]

    def events(self) -> list[dict]:
        """Return the audit journal without exposing mutable internal state."""
        with self._mutex:
            self._ensure_open()
            return [dict(seq=r[0], kind=r[1], turn_id=r[2], **json.loads(r[3]))
                    for r in self._db.execute("SELECT seq, kind, turn_id, data FROM events ORDER BY seq")]

    def reconcile(self, turn_id: str | None = None) -> list[Turn]:
        with self._mutex:
            self._ensure_open()
            turns = [self.get_turn(turn_id)] if turn_id is not None else self.list_turns()
            for turn in turns:
                if turn.state not in {"running", "uncertain"}:
                    continue
                if self._active is not None and self._active.turn_id == turn.turn_id:
                    continue
                data = self._load(turn.turn_id)
                receipt = next((a for a in reversed(data["attempts"]) if a.get("receipt")), None)
                if receipt is not None:
                    self._complete(data, receipt["receipt"], receipt.get("turn_elapsed_seconds", 0.0))
                elif data["state"] == "running":
                    with self._db:
                        data.update(state="uncertain", error={"code": "recovery_required", "reason": "interrupted_request"})
                        self._save(data)
                        self._event("uncertain", turn.turn_id, reason="interrupted_request")
            return [self.get_turn(t.turn_id) for t in turns]

    def _raise_outcome(self, data):
        state = data["state"]
        if state == "completed":
            return Response(**data["response"])
        if state in {"running", "uncertain"}:
            raise RecoveryRequired("Request outcome is uncertain; reconcile or explicitly abandon it",
                                   turn_id=data["turn_id"])
        code = (data.get("error") or {}).get("code", "request_failed")
        cls = {"authentication": AuthenticationError, "context_limit": ContextLimitError,
               "cancelled": TurnCancelled}.get(code, RequestFailed)
        raise cls(f"Turn is {state}: {code}", turn_id=data["turn_id"])

    def input(self, prompt: str, *, turn_id: str | None = None, retry_of: str | None = None) -> Response:
        if not isinstance(prompt, str):
            raise ConfigurationError("prompt must be a string")
        if turn_id is None:
            turn_id = str(uuid.uuid4())
        if not isinstance(turn_id, str) or not turn_id or len(turn_id) > 200:
            raise ConfigurationError("turn_id must be a nonempty string of at most 200 characters")
        with self._mutex:
            self._ensure_open()
            try:
                data = self._load(turn_id)
            except KeyError:
                data = None
            if data and (data["prompt"] != prompt or data.get("retry_of") != retry_of):
                raise TurnConflict("turn_id already belongs to a different input", turn_id=turn_id)
            if self._active is not None:
                if self._active.turn_id != turn_id:
                    raise SessionBusy("Another input is in progress", turn_id=self._active.turn_id)
                flight = self._active
            else:
                if data and data["state"] != "prepared":
                    self.reconcile(turn_id)
                    return self._raise_outcome(self._load(turn_id))
                blocked = next((t for t in self.list_turns() if t.state in _BLOCKING and t.turn_id != turn_id), None)
                if blocked:
                    raise RecoveryRequired("Resolve the unfinished turn before submitting another input", turn_id=blocked.turn_id)
                if retry_of is not None and self._load(retry_of)["state"] not in {"abandoned", "failed", "cancelled"}:
                    raise TurnConflict("retry_of must identify an abandoned, failed, or cancelled turn")
                if data is None:
                    history = self._meta("history") if self.config["mode"] == "multi_turn" else []
                    data = dict(turn_id=turn_id, prompt=prompt, retry_of=retry_of, state="prepared",
                                request=self._adapter.request(prompt, history), attempts=[], response=None, error=None)
                    with self._db:
                        self._save(data)
                        self._event("prepared", turn_id)
                flight = self._active = _Flight(turn_id)
                worker = threading.Thread(target=self._perform, args=(flight,), daemon=True,
                                          name=f"llm-{turn_id[:24]}")
                worker.start()
        if not flight.done.wait(max(0, self.config["timeout"] - (time.monotonic() - flight.started))):
            with self._mutex:
                if not flight.done.is_set():
                    self._interrupt(flight, "timeout")
        if flight.error is not None:
            raise flight.error
        if flight.result is None:
            raise SessionError("Request ended without a recorded outcome", turn_id=turn_id)
        return flight.result

    def _live(self, flight):
        return not self._closed and self._active is flight and not flight.done.is_set()

    def _perform(self, flight):
        rejected = None
        try:
            for attempt_no in range(self.config["max_attempts"]):
                try:
                    token, headers = self._adapter.credentials.get(rejected)
                except Exception:
                    with self._mutex:
                        if self._live(flight):
                            self._fail(flight, "authentication", known=True)
                    return
                secrets = (token,)
                with self._mutex:
                    if not self._live(flight):
                        return
                    data = self._load(flight.turn_id)
                    data["attempts"].append({"number": attempt_no + 1, "request": data["request"],
                                             "started_at": time.time(), "usage": None})
                    data["state"] = "running"
                    with self._db:
                        self._save(data)
                        self._event("running", flight.turn_id, attempt=attempt_no + 1)
                    request = data["request"]
                attempt_started = time.monotonic()
                def observe(kind, value):
                    with self._mutex:
                        if self._live(flight):
                            current = self._load(flight.turn_id)
                            current["attempts"][-1].update(_redact(value, secrets))
                            with self._db:
                                self._save(current)
                                self._event(kind, flight.turn_id, **_redact(value, secrets))
                def bind_client(client):
                    with self._mutex:
                        if not self._live(flight):
                            return False
                        flight.client = client
                        return True
                try:
                    raw = self._adapter.send(request, token, headers, flight.turn_id, observe, bind_client)
                except _WireError as exc:
                    with self._mutex:
                        if not self._live(flight):
                            return
                        data = self._load(flight.turn_id)
                        attempt = data["attempts"][-1]
                        attempt.update(error={"code": exc.code, "http_status": exc.status},
                                       elapsed_seconds=time.monotonic() - attempt_started)
                        if exc.partial:
                            attempt["partial"] = _redact(exc.partial, secrets)
                            attempt["usage"] = _redact(exc.partial.get("usage"), secrets)
                        retry = exc.known and attempt_no + 1 < self.config["max_attempts"] and (
                            exc.retryable or (exc.status == 401 and self.config["auth"] == "oauth" and rejected is None))
                        with self._db:
                            data["state"] = "prepared" if retry else data["state"]
                            self._save(data)
                            self._event("attempt_failed", flight.turn_id, **attempt["error"], retry=retry)
                        if not retry:
                            self._fail(flight, exc.code, known=exc.known)
                            return
                        if exc.status == 401:
                            rejected = token
                        retry_delay = exc.retry_after
                    if flight.done.wait(retry_delay):
                        return
                    continue
                raw = _redact(raw, secrets)
                elapsed = time.monotonic() - flight.started
                with self._mutex:
                    if self._closed:
                        return  # Released owners must never mutate the session.
                    data = self._load(flight.turn_id)
                    data["attempts"][-1].update(receipt=raw, usage=raw.get("usage"),
                                                 elapsed_seconds=time.monotonic() - attempt_started,
                                                 turn_elapsed_seconds=elapsed)
                    with self._db:
                        self._save(data)
                        self._event("received" if self._live(flight) else "late_response", flight.turn_id)
                    if not self._live(flight):
                        return
                    result = self._complete(data, raw, elapsed)
                    flight.result = result
                    if result.status in {"failed", "cancelled"}:
                        cls = TurnCancelled if result.status == "cancelled" else RequestFailed
                        flight.error = cls("Provider returned a terminal failure", turn_id=flight.turn_id)
                    self._active = None
                    flight.done.set()
                    return
        except BaseException:
            # A failed durable commit is not a provider failure. Leave the running
            # record/receipt recoverable and never return an uncommitted response.
            with self._mutex:
                if self._live(flight):
                    flight.error = SessionError("Could not commit request state; close and reopen to recover",
                                                turn_id=flight.turn_id)
                    self._active = None
                    flight.done.set()

    def _complete(self, data, raw, elapsed):
        text, status, reason, items = self._adapter.parse(raw)
        result = Response(text, data["turn_id"], raw.get("id"), raw.get("usage"), elapsed, status, reason)
        state = {"failed": "failed", "cancelled": "cancelled"}.get(status, "completed")
        data.update(state=state, response=asdict(result), error=None if state == "completed" else {"code": state})
        with self._db:
            if state == "completed" and self.config["mode"] == "multi_turn":
                history = self._meta("history") + [{"role": "user", "content": data["prompt"]}] + items
                self._db.execute("UPDATE meta SET value=? WHERE key='history'", (_json(history),))
            self._save(data)
            self._event(state, data["turn_id"], response_id=result.response_id)
        return result

    def _fail(self, flight, code, *, known):
        data = self._load(flight.turn_id)
        data.update(state="failed" if known else "uncertain", error={"code": code})
        with self._db:
            self._save(data)
            self._event(data["state"], flight.turn_id, code=code)
        cls = ({"authentication": AuthenticationError, "context_limit": ContextLimitError}.get(code, RequestFailed)
               if known else RecoveryRequired)
        flight.error = cls(f"Request failed: {code}" if known else f"Request outcome is uncertain: {code}", turn_id=flight.turn_id)
        self._active = None
        flight.done.set()

    def _interrupt(self, flight, reason):
        if not self._live(flight):
            return
        data = self._load(flight.turn_id)
        known = data["state"] == "prepared"
        data.update(state="cancelled" if known else "uncertain", error={"code": "cancelled" if known else "recovery_required",
                                                                         "reason": reason})
        with self._db:
            self._save(data)
            self._event(data["state"], flight.turn_id, reason=reason)
        cls = TurnCancelled if known else RecoveryRequired
        flight.error = cls("Cancelled before dispatch" if known else "Stopped waiting; remote outcome remains uncertain", turn_id=flight.turn_id)
        self._active = None
        flight.done.set()
        if flight.client is not None:
            # Closing an HTTP socket may wait for an OS read. Do not hold the
            # session lock or prevent cancellation of input while it unwinds.
            def close_transport():
                with contextlib.suppress(Exception):
                    flight.client.close()
            threading.Thread(target=close_transport, daemon=True).start()

    def cancel(self, turn_id: str | None = None) -> Turn | None:
        """Stop waiting immediately. Stateless endpoints cannot confirm remote cancellation."""
        with self._mutex:
            self._ensure_open()
            flight = self._active
            if flight is not None and (turn_id is None or turn_id == flight.turn_id):
                self._interrupt(flight, "cancelled")
                return self.get_turn(flight.turn_id)
            if turn_id is not None:
                data = self._load(turn_id)
                if data["state"] == "prepared":
                    with self._db:
                        data.update(state="cancelled", error={"code": "cancelled"})
                        self._save(data)
                        self._event("cancelled", turn_id)
                return self.get_turn(turn_id)
            return None

    def abandon(self, turn_id: str) -> Turn:
        with self._mutex:
            self._ensure_open()
            if self._active is not None and self._active.turn_id == turn_id:
                self._interrupt(self._active, "abandoned")
            data = self._load(turn_id)
            if data["state"] == "abandoned":
                return self._turn(data)
            if data["state"] != "uncertain":
                raise TurnConflict("Only an uncertain turn can be abandoned", turn_id=turn_id)
            with self._db:
                data["state"] = "abandoned"
                self._save(data)
                self._event("abandoned", turn_id)
            return self._turn(data)

    def reset(self, *, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ConfigurationError("reset requires a nonempty reason")
        with self._mutex:
            self._ensure_open()
            if any(t.state in _BLOCKING for t in self.list_turns()):
                raise SessionBusy("Resolve unfinished turns before resetting context")
            with self._db:
                self._db.execute("UPDATE meta SET value='[]' WHERE key='history'")
                self._event("reset", reason=reason)

    def close(self):
        with self._mutex:
            if os.getpid() != self._owner_pid:
                raise SessionError("A forked process cannot close the original owner's session")
            if self._closed:
                return
            if self._active is not None:
                self._interrupt(self._active, "closed")
            self._closed = True
            self._db.close()
            self._lock_context.__exit__(None, None, None)

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *exc):
        self.close()
