"""Claude subscription transport, refresh, and recovery without live requests."""

import concurrent.futures
import contextlib
import io
import json
import multiprocessing
import os
import socket
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import anthropic
import httpx2 as httpx

from gobench import anthropic_oauth as oauth
import arena


def message_events(*, stop_reason="end_turn", input_tokens=100):
    return [
        {"type": "message_start", "message": {
            "id": "msg_test", "type": "message", "role": "assistant",
            "model": "claude-opus-5", "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": 1,
                      "cache_read_input_tokens": 40, "cache_creation_input_tokens": 20},
        }},
        {"type": "content_block_start", "index": 0, "content_block": {
            "type": "thinking", "thinking": "", "signature": "",
        }},
        {"type": "content_block_delta", "index": 0, "delta": {
            "type": "thinking_delta", "thinking": "Consider D4.",
        }},
        {"type": "content_block_delta", "index": 0, "delta": {
            "type": "signature_delta", "signature": "opaque-signature",
        }},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {
            "type": "redacted_thinking", "data": "opaque-thinking",
        }},
        {"type": "content_block_stop", "index": 1},
        {"type": "content_block_start", "index": 2, "content_block": {
            "type": "text", "text": "",
        }},
        {"type": "content_block_delta", "index": 2, "delta": {
            "type": "text_delta", "text": "D4",
        }},
        {"type": "content_block_stop", "index": 2},
        {"type": "message_delta", "delta": {
            "stop_reason": stop_reason, "stop_sequence": None,
        }, "usage": {"output_tokens": 30}},
        {"type": "message_stop"},
    ]


def sse(events):
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          content="".join(
                              f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                              for event in events))


def refresh_in_process(auth_path, outcome):
    """Real process coordination with a fake token endpoint."""
    path = Path(auth_path)

    def refresh(_token):
        with (path.parent / "refresh-attempts").open("a") as out:
            out.write("attempt\n")
        if outcome == "crash":
            os._exit(17)
        if outcome == "rejected":
            raise oauth.ClaudeOAuthError("refresh rejected")
        time.sleep(.05)
        return {"accessToken": "sk-ant-oat-worker", "refreshToken": "worker-refresh",
                "expiresAt": time.time() * 1000 + 3600000}

    with (mock.patch.dict(os.environ, {"ARENA_ANTHROPIC_AUTH_PATH": auth_path}),
          mock.patch.object(oauth, "_refresh", side_effect=refresh)):
        try:
            return oauth.access_token()
        except oauth.ClaudeOAuthError:
            return "waiting"


class ClaudeOAuthTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.auth = self.root / ".credentials.json"
        self.stack.enter_context(mock.patch.object(
            oauth.urllib.request, "urlopen", side_effect=AssertionError("Live token request")
        ))
        self.write_auth()
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "ARENA_ANTHROPIC_AUTH_PATH": str(self.auth),
            "ANTHROPIC_API_KEY": "unused-paid-api-key",
            "ANTHROPIC_AUTH_TOKEN": "unused-environment-token",
        }))
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        self.stack.enter_context(mock.patch.object(
            arena, "_llm_api_key", side_effect=AssertionError("API key used")
        ))
        self.stack.enter_context(mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 1))
        self.stack.enter_context(mock.patch.object(
            arena.subprocess, "Popen", side_effect=AssertionError("Agent process launched")
        ))
        self.requests = []
        self.reply = lambda: sse(message_events())
        sdk_class = anthropic.Anthropic

        def handle(request):
            self.requests.append(request)
            return self.reply()

        def create_sdk(**kwargs):
            return sdk_class(**kwargs, http_client=httpx.Client(
                transport=httpx.MockTransport(handle)
            ))

        self.stack.enter_context(mock.patch.object(anthropic, "Anthropic", create_sdk))

    def write_auth(self, token="sk-ant-oat-test", *, expires=None):
        self.auth.write_text(json.dumps({
            "claudeAiOauth": {"accessToken": token, "refreshToken": "private-refresh",
                          "expiresAt": expires if expires is not None else time.time() * 1000 + 3600000,
                          "subscriptionType": "max", "scopes": ["user:inference"]},
            "organizationUuid": "organization-id",
        }))

    def client(self, name="opus-5-high-api"):
        client = arena._llm_client(name, work_dir=self.root, game_number=1)
        self.stack.callback(client.close)
        return client

    def call(self, client, name="opus-5-high-api", move=1):
        return arena._call_llm_move(
            client, f"Move {move}: legal moves D4, pass", player_name=name,
            log_path=self.root / "raw.jsonl", compact_log_path=self.root / "compact.jsonl",
            game_number=1, move_number=move, attempt=1,
        )

    def test_oauth_wire_request_usage_and_manifest(self):
        output, _, cost = self.call(self.client())
        self.assertEqual(output, "D4")
        self.assertAlmostEqual(cost, (100 * 5 + 40 * .5 + 20 * 6.25 + 30 * 25) / 1e6)
        request = self.requests[-1]
        self.assertEqual(str(request.url), "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.headers["authorization"], "Bearer sk-ant-oat-test")
        self.assertNotIn("x-api-key", request.headers)
        for key, value in oauth.HEADERS.items():
            self.assertEqual(request.headers[key], value)
        body = json.loads(request.content)
        self.assertEqual(body["system"], [{"type": "text", "text": oauth.IDENTITY}])
        self.assertEqual(body["model"], "claude-opus-5")
        self.assertEqual(body["thinking"], {"type": "adaptive"})
        self.assertEqual(body["cache_control"], {"type": "ephemeral"})
        self.assertEqual(body["output_config"], {"effort": "high"})
        self.assertEqual(body["max_tokens"], 128000)
        self.assertTrue(body["stream"])
        self.assertNotIn("tools", body)
        manifest = arena._llm_player_manifest("opus-5-high-api")
        self.assertEqual(manifest["auth_mode"], "oauth")
        self.assertIn("api_equivalent", manifest["cost_basis"])
        self.assertEqual(manifest["oauth_system_prompt"], oauth.IDENTITY)
        self.assertEqual(manifest["cache_control"], body["cache_control"])
        entry = json.loads((self.root / "raw.jsonl").read_text())
        self.assertEqual(entry["request"]["system"], body["system"])
        self.assertEqual(entry["usage"]["cache_read_input_tokens"], 40)
        compact = json.loads((self.root / "compact.jsonl").read_text())
        self.assertEqual(compact["cached_input_tokens"], 40)
        self.assertEqual(compact["cache_write_tokens"], 20)
        self.assertEqual(compact["auth_mode"], "oauth")

    def test_only_api_names_are_advertised_and_old_names_remain_readable(self):
        self.assertFalse(any("-oauth" in name for name in arena._Arena.ACTIVE_LLM_PLAYERS))
        self.assertEqual(arena._llm_player_config("opus-5-high-oauth-multi2"),
                         arena._llm_player_config("opus-5-high-api-multi2"))
        self.assertEqual(arena._llm_api_config("anthropic_oauth").name, "anthropic")

    def test_existing_api_run_accepts_auth_policy_but_rejects_model_change(self):
        manifest = arena._llm_player_manifest("opus-5-high-api-multi")
        previous = {k: v for k, v in manifest.items()
                    if k not in {"auth_mode", "cost_basis", "oauth_system_prompt"}}
        arena._validate_named_extension({"bots": [previous]}, {"bots": [manifest]})
        with self.assertRaisesRegex(arena.ArenaError, "different game/player settings"):
            arena._validate_named_extension({"bots": [previous]}, {"bots": [manifest | {"model": "different-model"}]})

    def test_renamed_history_uses_new_directory_without_duplicate_games(self):
        old, new = "opus-5-high-oauth-multi2", "opus-5-high-api-multi2"
        (self.root / new).mkdir()
        with mock.patch.object(arena._Arena, "LOG_ROOT", self.root):
            self.assertEqual(arena._historical_run_name(old), new)
            # An unrelated legacy directory must never be silently replaced.
            (self.root / old).mkdir()
            self.assertEqual(arena._historical_run_name(old), old)

    def test_quota_wait_preserves_history_and_never_uses_api_key(self):
        name = "opus-5-high-api-multi2"
        client = self.client(name)
        self.call(client, name)
        replies = iter([
            httpx.Response(429, headers={"retry-after": "14400"},
                           json={"error": {"type": "rate_limit_error", "message": "limit"}}),
            sse(message_events()),
        ])
        self.reply = lambda: next(replies)
        with (mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 0),
              mock.patch.object(arena.time, "sleep") as sleep):
            self.assertEqual(self.call(client, name, move=3)[0], "D4")
        sleep.assert_called_once_with(14405)
        for request in self.requests:
            self.assertEqual(request.headers["authorization"], "Bearer sk-ant-oat-test")
            self.assertNotIn("x-api-key", request.headers)
        self.assertEqual(json.loads(self.requests[1].content)["messages"],
                         json.loads(self.requests[2].content)["messages"])
        for filename in ("raw.jsonl", "compact.jsonl"):
            entries = [json.loads(line) for line in (self.root / filename).read_text().splitlines()]
            self.assertEqual([e["auth_mode"] for e in entries], ["oauth"] * 3)
            self.assertEqual(entries[1]["recovery_action"], "wait_for_quota_reset")
            self.assertEqual(entries[1]["retry_in_seconds"], 14405)
            self.assertIn("quota_reset_at", entries[1])
            self.assertNotIn("quota_reset_at", entries[2])
        recovered = self.client(name)
        self.assertEqual(self.call(recovered, name, move=3), ("D4", 0, 0))
        self.assertEqual(len(self.requests), 3)

    def test_quota_reset_timing(self):
        prefix = "anthropic-ratelimit-unified"
        now = 1800000000
        self.write_auth(expires=(now + 3600) * 1000)
        cases = [
            ({f"{prefix}-status": "rejected", f"{prefix}-representative-claim": "five_hour",
              f"{prefix}-5h-reset": str(now + 7200), f"{prefix}-7d-reset": str(now + 86400),
              f"{prefix}-7d-utilization": "0.2"}, {}, 7205, "five_hour"),
            ({f"{prefix}-5h-utilization": "1", f"{prefix}-5h-reset": str(now + 7200),
              f"{prefix}-7d-utilization": "1", f"{prefix}-7d-reset": str(now + 86400),
              "retry-after": "60"}, {}, 86405, "seven_day"),
            ({f"{prefix}-status": "rejected", f"{prefix}-representative-claim": "seven_day",
              f"{prefix}-reset": str(now + 86400)}, {}, 86405, "seven_day"),
            ({f"{prefix}-status": "allowed", f"{prefix}-representative-claim": "five_hour",
              f"{prefix}-reset": str(now + 7200), f"{prefix}-5h-reset": str(now + 7200),
              f"{prefix}-7d-reset": str(now + 86400), "retry-after": "30"}, {}, 35, "rate_limit"),
            ({}, {}, 300, "unknown"),
            ({"retry-after": "nan", f"{prefix}-reset": "inf"}, {}, 300, "unknown"),
            ({"retry-after": "1e300", f"{prefix}-reset": "1e300"}, {}, 300, "unknown"),
            ({"retry-after": "-10", f"{prefix}-reset": str(now - 100)}, {}, 300, "unknown"),
            ({"retry-after": "Fri, 15 Jan 2027 08:02:00 GMT"}, {}, 125, "rate_limit"),
            ({"retry-after-ms": "12000"}, {}, 17, "rate_limit"),
            ({}, {"reset_at": now + 600}, 605, "subscription"),
            ({}, {"resets_at": "2027-01-15T08:10:00Z"}, 605, "subscription"),
        ]
        client = self.client()
        api, player = arena._llm_player_config("opus-5-high-api")
        for headers, detail, expected, window in cases:
            with self.subTest(headers=headers, detail=detail):
                self.reply = lambda: httpx.Response(429, headers=headers, json={
                    "error": {"type": "rate_limit_error", "message": "quota", **detail},
                })
                with mock.patch.object(oauth.time, "time", return_value=now):
                    with self.assertRaises(anthropic.APIStatusError) as raised:
                        client.create(**arena._llm_request(api, player, "prompt"))
                self.assertEqual(arena._llm_api_retry_delay(raised.exception, 100), expected)
                self.assertEqual(raised.exception.arena_quota["quota_window"], window)
                self.assertNotIn("x-api-key", self.requests[-1].headers)

    def test_unknown_quota_timing_polls_until_access_returns(self):
        replies = iter([
            httpx.Response(429, json={"error": {"type": "rate_limit_error"}}),
            httpx.Response(429, json={"error": {"type": "rate_limit_error"}}),
            sse(message_events()),
        ])
        self.reply = lambda: next(replies)
        with (mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 0),
              mock.patch.object(arena.time, "sleep") as sleep):
            self.assertEqual(self.call(self.client())[0], "D4")
        self.assertEqual(sleep.call_args_list, [mock.call(300), mock.call(300)])
        self.assertTrue(all("x-api-key" not in request.headers for request in self.requests))

    def test_rejected_auth_never_uses_api_key(self):
        for status in (401, 403):
            with self.subTest(status=status):
                client = self.client()
                self.reply = lambda: httpx.Response(status, json={"error": {"message": "rejected"}})
                with mock.patch.object(arena.time, "sleep") as sleep:
                    with self.assertRaisesRegex(arena.ArenaError, "sign in with Claude Code"):
                        self.call(client)
                sleep.assert_not_called()
                self.assertNotIn("x-api-key", self.requests[-1].headers)

    def test_failed_refresh_never_uses_api_key_or_modifies_credentials(self):
        client = self.client()
        self.write_auth(expires=0)
        before = self.auth.read_bytes()
        with mock.patch.object(oauth, "_refresh", side_effect=oauth.ClaudeOAuthError("refresh rejected")):
            with self.assertRaisesRegex(arena.ArenaError, "refresh rejected"):
                self.call(client)
        self.assertEqual(self.auth.read_bytes(), before)
        self.assertEqual(self.requests, [])

    def test_quota_wait_keeps_partial_stream_usage_and_reset_headers(self):
        failure = sse(message_events()[:1] + [{"type": "error", "error": {
            "type": "rate_limit_error", "message": "limit",
        }}])
        failure.headers["retry-after"] = "120"
        replies = iter([failure, sse(message_events())])
        self.reply = lambda: next(replies)
        with (mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 2),
              mock.patch.object(arena.time, "sleep") as sleep):
            _, _, cost = self.call(self.client())
        sleep.assert_called_once_with(125)
        entries = [json.loads(line) for line in (self.root / "raw.jsonl").read_text().splitlines()]
        self.assertEqual(entries[0]["usage"]["input_tokens"], 100)
        self.assertGreater(entries[0]["cost_usd"], 0)
        self.assertAlmostEqual(cost, sum(e["cost_usd"] for e in entries))
        self.assertEqual(entries[0]["http_status"], 429)
        self.assertEqual(entries[0]["recovery_action"], "wait_for_quota_reset")

    def test_oauth_multiturn_caching_reaches_sdk_and_preserves_usage(self):
        name = "opus-5-high-api-multi"
        events = message_events(input_tokens=0)
        events[0]["message"]["usage"].update(cache_read_input_tokens=5000, cache_creation_input_tokens=200)
        self.reply = lambda: sse(events)
        client = self.client(name)
        self.call(client, name)
        _, _, cost = self.call(client, name, move=3)
        contents = [{"type": "thinking", "thinking": "Consider D4.", "signature": "opaque-signature"},
                    {"type": "redacted_thinking", "data": "opaque-thinking"},
                    {"type": "text", "text": "D4"}]
        first, second = [json.loads(request.content) for request in self.requests]
        self.assertEqual(second["messages"][:-1], first["messages"] + [
            {"role": "assistant", "content": contents},
        ])
        for request, body in zip(self.requests, (first, second)):
            self.assertNotIn("x-api-key", request.headers)
            self.assertEqual(request.headers["authorization"], "Bearer sk-ant-oat-test")
            self.assertEqual(body["cache_control"], {"type": "ephemeral"})
        self.assertAlmostEqual(cost, (5000 * .5 + 200 * 6.25 + 30 * 25) / 1e6)
        compact = json.loads((self.root / "compact.jsonl").read_text().splitlines()[-1])
        self.assertEqual(compact["input_tokens"], 0)
        self.assertEqual(compact["cached_input_tokens"], 5000)
        self.assertEqual(compact["cache_write_tokens"], 200)
        self.assertEqual(client.conversation.observed_tokens, 5230)

    def test_oauth_fully_cached_input_retains_measured_context_size(self):
        name = "opus-5-high-api-multi"
        self.reply = lambda: sse(message_events(input_tokens=0))
        client = self.client(name)
        self.call(client, name)
        self.assertEqual(client.conversation.observed_tokens, 40 + 20 + 30)

    def test_fresh_turns_reread_credentials_and_never_log_them(self):
        client = self.client()
        self.call(client)
        self.write_auth("sk-ant-oat-renewed")
        self.call(client, move=3)
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer sk-ant-oat-renewed")
        self.assertEqual(len(json.loads(self.requests[-1].content)["messages"]), 1)
        for path in self.root.glob("*.jsonl"):
            for secret in ("sk-ant-oat-test", "sk-ant-oat-renewed", "private-refresh",
                           "unused-paid-api-key", "unused-environment-token"):
                self.assertNotIn(secret, path.read_text())

    def test_multiturn_preserves_thinking_recovers_and_resets(self):
        name = "opus-5-high-api-multi"
        client = self.client(name)
        self.call(client, name)
        self.reply = lambda: sse(message_events(input_tokens=250000))
        self.call(client, name, move=3)
        body = json.loads(self.requests[-1].content)
        self.assertEqual(len(body["messages"]), 3)
        content = body["messages"][1]["content"]
        self.assertEqual(content[0]["signature"], "opaque-signature")
        self.assertEqual(content[1], {"type": "redacted_thinking", "data": "opaque-thinking"})
        self.assertEqual(content[2]["text"], "D4")
        self.assertEqual(body["system"], [{"type": "text", "text": oauth.IDENTITY}])
        recovered = self.client(name)
        output, elapsed, cost = self.call(recovered, name, move=3)
        self.assertEqual((output, elapsed, cost), ("D4", 0, 0))
        self.assertEqual(len(self.requests), 2)
        self.call(recovered, name, move=5)
        self.assertEqual(len(json.loads(self.requests[-1].content)["messages"]), 1)
        self.assertEqual(recovered.conversation.session, 2)
        for request in self.requests:
            self.assertEqual(json.loads(request.content)["cache_control"],
                             {"type": "ephemeral"})

    def test_invalid_or_missing_login_without_key_explains_configuration(self):
        for value in (None, "{", "[]", "{}", '{"anthropic":{"type":"api_key"}}'):
            with self.subTest(value=value):
                if value is None:
                    self.auth.unlink(missing_ok=True)
                else:
                    self.auth.write_text(value)
                with self.assertRaisesRegex(oauth.ClaudeOAuthError, "subscription OAuth login"):
                    self.client().create()
        self.assertEqual(self.requests, [])

    def test_explicit_token_takes_precedence_and_reloads(self):
        self.auth.unlink()
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-explicit"}):
            client = self.client()
            self.call(client)
            self.assertEqual(self.requests[-1].headers["authorization"], "Bearer sk-ant-oat-explicit")
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "sk-ant-api-not-oauth"
            with self.assertRaisesRegex(oauth.ClaudeOAuthError, "not a Claude OAuth token"):
                client.create()

    def test_claude_code_default_and_config_directory(self):
        os.environ.pop("ARENA_ANTHROPIC_AUTH_PATH")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root)}):
            self.assertEqual(oauth.access_token(), "sk-ant-oat-test")
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        config = self.root / ".claude"
        config.mkdir()
        (config / ".credentials.json").write_bytes(self.auth.read_bytes())
        with mock.patch.object(oauth.Path, "home", return_value=self.root):
            self.assertEqual(oauth.access_token(), "sk-ant-oat-test")

    def test_cli_login_during_refresh_is_preserved(self):
        self.write_auth(expires=0)

        def refresh(_token):
            self.write_auth("sk-ant-oat-cli-renewed")
            return {"accessToken": "sk-ant-oat-arena-renewed", "refreshToken": "arena-refresh",
                    "expiresAt": time.time() * 1000 + 3600000}

        with mock.patch.object(oauth, "_refresh", side_effect=refresh):
            self.assertEqual(oauth.access_token(), "sk-ant-oat-cli-renewed")
        self.assertEqual(json.loads(self.auth.read_text())["claudeAiOauth"]["accessToken"],
                         "sk-ant-oat-cli-renewed")

    def test_cli_rotation_can_recover_a_failed_refresh(self):
        self.write_auth(expires=0)

        def refresh(_token):
            self.write_auth("sk-ant-oat-cli-renewed")
            raise oauth.ClaudeOAuthError("refresh token consumed")

        with mock.patch.object(oauth, "_refresh", side_effect=refresh):
            self.assertEqual(oauth.access_token(), "sk-ant-oat-cli-renewed")

    def test_concurrent_refresh_rotates_once_and_preserves_other_credentials(self):
        self.write_auth(expires=0)

        def refresh(token):
            self.assertEqual(token, "private-refresh")
            self.assertTrue((self.root / ".oauth_refresh.lock").is_dir())
            self.assertTrue(Path(f"{self.root}.lock").is_dir())
            time.sleep(.05)
            return {"accessToken": "sk-ant-oat-new", "refreshToken": "rotated-refresh",
                    "expiresAt": time.time() * 1000 + 3600000}

        with mock.patch.object(oauth, "_refresh", side_effect=refresh) as mocked:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                tokens = list(pool.map(lambda _: oauth.access_token(), range(4)))
        self.assertEqual(tokens, ["sk-ant-oat-new"] * 4)
        mocked.assert_called_once()
        saved = json.loads(self.auth.read_text())
        self.assertEqual(saved["claudeAiOauth"]["refreshToken"], "rotated-refresh")
        self.assertEqual(saved["claudeAiOauth"]["subscriptionType"], "max")
        self.assertEqual(saved["claudeAiOauth"]["scopes"], ["user:inference"])
        self.assertEqual(saved["organizationUuid"], "organization-id")
        self.assertEqual(self.auth.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.root / ".oauth_refresh.lock").exists())
        self.assertFalse(Path(f"{self.root}.lock").exists())
        self.assertEqual(list(self.root.glob("..credentials.json.*")), [])

    def test_waits_for_cli_refresh_and_rereads_credentials(self):
        for lock in (self.root / ".oauth_refresh.lock", Path(f"{self.root}.lock")):
            with self.subTest(lock=lock):
                self.write_auth(expires=0)
                lock.mkdir()

                def finish_refresh(_delay):
                    self.write_auth("sk-ant-oat-cli-renewed")
                    lock.rmdir()

                with (mock.patch.object(oauth.time, "sleep", side_effect=finish_refresh),
                      mock.patch.object(oauth, "_refresh") as refresh):
                    self.assertEqual(oauth.access_token(), "sk-ant-oat-cli-renewed")
                refresh.assert_not_called()

    def test_abandoned_cli_locks_are_recovered(self):
        locks = (self.root / ".oauth_refresh.lock", Path(f"{self.root}.lock"))
        for lock in locks:
            lock.mkdir()
            os.utime(lock, (time.time() - 120, time.time() - 120))
        with oauth._auth_lock(self.auth) as check:
            check()
            for lock in locks:
                self.assertLess(time.time() - lock.stat().st_mtime, 5)
        self.assertTrue(all(not lock.exists() for lock in locks))

    def test_active_cli_lock_times_out_without_refreshing_or_removing_it(self):
        self.write_auth(expires=0)
        lock = self.root / ".oauth_refresh.lock"
        lock.mkdir()
        with (mock.patch.object(oauth.time, "monotonic", side_effect=[0, 71]),
              mock.patch.object(oauth, "_refresh") as refresh):
            with self.assertRaises(oauth.ClaudeOAuthError) as raised:
                oauth.access_token()
        self.assertTrue(raised.exception.body["retryable"])
        self.assertTrue(lock.is_dir())
        refresh.assert_not_called()

    def test_replaced_lock_is_detected_and_not_removed(self):
        lock = self.root / ".oauth_refresh.lock"
        with oauth._auth_lock(self.auth) as check:
            lock.rename(self.root / "old-lock")
            lock.mkdir()
            with self.assertRaisesRegex(oauth.ClaudeOAuthError, "lock was lost"):
                check()
        self.assertTrue(lock.is_dir())
        self.assertFalse(Path(f"{self.root}.lock").exists())

    def test_startup_refresh_failure_is_reported_without_traceback(self):
        with (mock.patch.object(arena, "_configure"),
              mock.patch.object(arena, "run_arena", side_effect=oauth.ClaudeOAuthError(
                  "Claude OAuth refresh failed (HTTP 403)")),
              contextlib.redirect_stderr(io.StringIO()) as stderr):
            self.assertEqual(arena.main([]), 1)
        self.assertEqual(stderr.getvalue(), "error: Claude OAuth refresh failed (HTTP 403)\n")

    def test_refresh_http_request_and_error_redaction(self):
        result = {"access_token": "sk-ant-oat-new", "refresh_token": "new-refresh", "expires_in": 3600}
        with mock.patch.object(oauth.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(result).encode())) as send:
            before = time.time() * 1000
            credentials = oauth._refresh("private-refresh")
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, oauth.TOKEN_URL)
        body = json.loads(request.data)
        self.assertEqual(body, {"grant_type": "refresh_token", "client_id": oauth.CLIENT_ID,
                                "refresh_token": "private-refresh"})
        self.assertGreaterEqual(credentials["expiresAt"], before + 3600000)
        self.assertLess(credentials["expiresAt"], before + 3601000)
        for status, retryable in ((400, False), (403, False), (429, True), (503, True)):
            error = urllib.error.HTTPError(oauth.TOKEN_URL, status, "private-refresh", {},
                                           io.BytesIO(b'private-refresh'))
            with mock.patch.object(oauth.urllib.request, "urlopen", side_effect=error):
                with self.assertRaises(oauth.ClaudeOAuthError) as raised:
                    oauth._refresh("private-refresh")
            self.assertNotIn("private-refresh", str(raised.exception))
            self.assertEqual(arena._retryable_llm_api_error(raised.exception), retryable)

    def test_refresh_failure_does_not_modify_credentials(self):
        self.write_auth(expires=0)
        original = self.auth.read_bytes()
        with mock.patch.object(oauth, "_refresh", side_effect=oauth.ClaudeOAuthError("refresh failed")):
            with self.assertRaises(oauth.ClaudeOAuthError):
                oauth.access_token()
        self.assertEqual(self.auth.read_bytes(), original)
        self.assertFalse((self.root / ".oauth_refresh.lock").exists())
        self.assertFalse(Path(f"{self.root}.lock").exists())

    def test_startup_auth_waits_for_login_and_resumes_same_move(self):
        self.auth.unlink()
        client = self.client()
        with (mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 0),
              mock.patch.object(arena.time, "sleep", side_effect=lambda _: self.write_auth()) as sleep):
            self.assertEqual(self.call(client)[0], "D4")
        sleep.assert_called_once_with(60)
        entries = [json.loads(line) for line in (self.root / "compact.jsonl").read_text().splitlines()]
        self.assertEqual(entries[0]["recovery_action"], "wait_for_authentication")
        self.assertEqual(entries[0]["move"], entries[1]["move"])
        self.assertEqual(len(self.requests), 1)

    def test_rejected_refresh_polls_without_resubmitting_and_keeps_conversation(self):
        name = "opus-5-high-api-multi"
        client = self.client(name)
        self.call(client, name)
        self.write_auth(expires=0)
        polls = 0

        def login(_delay):
            nonlocal polls
            polls += 1
            if polls == 3:
                self.write_auth("sk-ant-oat-new-login")

        with (mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 0),
              mock.patch.object(arena.time, "sleep", side_effect=login),
              mock.patch.object(oauth, "_refresh", side_effect=oauth.ClaudeOAuthError(
                  "Claude OAuth refresh failed (HTTP 403)")) as refresh):
            self.assertEqual(self.call(client, name, move=3)[0], "D4")
        refresh.assert_called_once()
        self.assertEqual(polls, 3)
        body = json.loads(self.requests[-1].content)
        self.assertEqual(len(body["messages"]), 3)
        self.assertEqual(body["messages"][1]["content"][0]["signature"], "opaque-signature")
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer sk-ant-oat-new-login")
        journal = self.auth.with_name(f"{self.auth.name}.arena-refresh.json")
        self.assertEqual(journal.stat().st_mode & 0o777, 0o600)
        for secret in ("private-refresh", "sk-ant-oat-test", "sk-ant-oat-new-login"):
            self.assertNotIn(secret, journal.read_text())

    def test_401_refreshes_even_if_expiry_is_in_future(self):
        replies = iter([httpx.Response(401, json={"error": {"message": "expired"}}),
                        sse(message_events())])
        self.reply = lambda: next(replies)
        updated = {"accessToken": "sk-ant-oat-renewed", "refreshToken": "rotated",
                   "expiresAt": time.time() * 1000 + 3600000}
        with (mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 0),
              mock.patch.object(arena.time, "sleep") as sleep,
              mock.patch.object(oauth, "_refresh", return_value=updated) as refresh):
            self.assertEqual(self.call(self.client())[0], "D4")
        refresh.assert_called_once()
        sleep.assert_called_once_with(60)
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer sk-ant-oat-renewed")

    def test_persistent_401_does_not_rotate_tokens_endlessly(self):
        self.reply = lambda: httpx.Response(401, json={"error": {"message": "rejected"}})
        updated = {"accessToken": "sk-ant-oat-renewed", "refreshToken": "rotated",
                   "expiresAt": time.time() * 1000 + 3600000}
        with (mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 5),
              mock.patch.object(arena.time, "sleep"),
              mock.patch.object(oauth, "_refresh", return_value=updated) as refresh):
            with self.assertRaises(arena.ArenaError):
                self.call(self.client())
        refresh.assert_called_once()
        self.assertEqual(len(self.requests), 2)

    def test_403_recovers_when_credentials_change_without_forced_refresh(self):
        replies = iter([httpx.Response(403, json={"error": {"message": "rejected"}}),
                        sse(message_events())])
        self.reply = lambda: next(replies)
        with (mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 0),
              mock.patch.object(arena.time, "sleep", side_effect=lambda _: self.write_auth("sk-ant-oat-login")),
              mock.patch.object(oauth, "_refresh") as refresh):
            self.assertEqual(self.call(self.client())[0], "D4")
        refresh.assert_not_called()
        self.assertEqual(len(self.requests), 2)

    def test_proactive_refresh_failure_keeps_still_valid_access_token(self):
        self.write_auth(expires=time.time() * 1000 + 120000)
        with mock.patch.object(oauth, "_refresh", side_effect=oauth.ClaudeOAuthError("rejected")) as refresh:
            self.assertEqual(oauth.access_token(), "sk-ant-oat-test")
            self.assertEqual(oauth.access_token(), "sk-ant-oat-test")
            self.write_auth(expires=0)
            with self.assertRaises(oauth.ClaudeOAuthError):
                oauth.access_token()
        refresh.assert_called_once()

    def test_transient_refresh_failure_has_shared_cooldown_then_recovers(self):
        self.write_auth(expires=0)
        updated = {"accessToken": "sk-ant-oat-renewed", "refreshToken": "rotated",
                   "expiresAt": time.time() * 1000 + 3600000}
        with (mock.patch.object(oauth.time, "time", return_value=1000) as now,
              mock.patch.object(oauth, "_refresh", side_effect=[
                  oauth.ClaudeOAuthError("service unavailable", retryable=True), updated,
              ]) as refresh):
            for _ in range(3):
                with self.assertRaises(oauth.ClaudeOAuthError):
                    oauth.access_token()
            self.assertEqual(refresh.call_count, 1)
            now.return_value = 1061
            self.assertEqual(oauth.access_token(), "sk-ant-oat-renewed")
        self.assertEqual(refresh.call_count, 2)

    def test_uncertain_refresh_is_not_replayed_after_network_failure(self):
        self.write_auth(expires=0)
        with mock.patch.object(oauth.urllib.request, "urlopen", side_effect=TimeoutError("private-refresh")) as send:
            for _ in range(2):
                with self.assertRaises(oauth.ClaudeOAuthError) as raised:
                    oauth.access_token()
                self.assertNotIn("private-refresh", str(raised.exception))
        send.assert_called_once()

    def test_refresh_identifies_client_to_avoid_browser_integrity_rejection(self):
        self.write_auth(expires=0)
        result = {"access_token": "sk-ant-oat-renewed", "refresh_token": "rotated",
                  "expires_in": 28800}

        def endpoint(request, **kwargs):
            agent = request.get_header("User-agent", "Python-urllib/3.12")
            if agent.startswith("Python-urllib/"):
                raise urllib.error.HTTPError(
                    request.full_url, 403, "Forbidden", {},
                    io.BytesIO(b'{"error_code":1010,"error_name":"browser_signature_banned"}'),
                )
            return io.BytesIO(json.dumps(result).encode())

        with mock.patch.object(oauth.urllib.request, "urlopen", side_effect=endpoint) as send:
            self.assertEqual(oauth.access_token(), "sk-ant-oat-renewed")
            self.assertEqual(oauth.access_token(), "sk-ant-oat-renewed")
        send.assert_called_once()
        saved = json.loads(self.auth.read_text())["claudeAiOauth"]
        self.assertEqual(saved["refreshToken"], "rotated")
        self.assertFalse(self.auth.with_name(self.auth.name + ".arena-refresh.json").exists())

    def test_connection_failure_can_retry_without_risking_a_consumed_token(self):
        self.write_auth(expires=0)
        result = {"access_token": "sk-ant-oat-new", "refresh_token": "new-refresh", "expires_in": 3600}
        with (mock.patch.object(oauth.time, "time", return_value=1000) as now,
              mock.patch.object(oauth.urllib.request, "urlopen", side_effect=[
                  urllib.error.URLError(socket.gaierror("DNS unavailable")),
                  io.BytesIO(json.dumps(result).encode()),
              ]) as send):
            with self.assertRaises(oauth.ClaudeOAuthError) as raised:
                oauth.access_token()
            self.assertTrue(raised.exception.body["retryable"])
            now.return_value = 1061
            self.assertEqual(oauth.access_token(), "sk-ant-oat-new")
        self.assertEqual(send.call_count, 2)

    def test_rejected_explicit_token_requires_replacement_without_touching_file_login(self):
        self.reply = lambda: httpx.Response(401, json={"error": {"message": "expired"}})
        with (mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-explicit"}),
              mock.patch.object(oauth, "_refresh") as refresh):
            client = self.client()
            with self.assertRaises(oauth.ClaudeOAuthError):
                client.create(model="claude-opus-5", max_tokens=10, messages=[])
            with self.assertRaisesRegex(oauth.ClaudeOAuthError, "replace it and restart"):
                client.create()
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "sk-ant-oat-replaced"
            self.reply = lambda: sse(message_events())
            self.assertEqual(self.call(client)[0], "D4")
        refresh.assert_not_called()
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer sk-ant-oat-replaced")

    def test_403_probes_again_after_backoff_without_churning_credentials(self):
        self.reply = lambda: httpx.Response(403, json={"error": {"message": "unavailable"}})
        client = self.client()
        with (mock.patch.object(oauth.time, "monotonic", return_value=1000) as now,
              mock.patch.object(oauth, "_refresh") as refresh):
            with self.assertRaises(arena.ArenaError):
                self.call(client)
            self.reply = lambda: sse(message_events())
            with self.assertRaises(oauth.ClaudeOAuthError) as raised:
                client.create()
            self.assertEqual(raised.exception.status_code, 403)
            now.return_value = 1301
            self.assertEqual(self.call(client)[0], "D4")
        refresh.assert_not_called()
        self.assertEqual(len(self.requests), 2)

    def test_save_failure_does_not_replay_consumed_refresh_token(self):
        self.write_auth(expires=0)
        updated = {"accessToken": "sk-ant-oat-renewed", "refreshToken": "rotated",
                   "expiresAt": time.time() * 1000 + 3600000}
        original = oauth._atomic_json

        def save(path, *args):
            if path == self.auth:
                raise OSError("disk full")
            return original(path, *args)

        with (mock.patch.object(oauth, "_refresh", return_value=updated) as refresh,
              mock.patch.object(oauth, "_atomic_json", side_effect=save)):
            with self.assertRaises(OSError):
                oauth.access_token()
            with self.assertRaises(oauth.ClaudeOAuthError):
                oauth.access_token()
        refresh.assert_called_once()

    def test_process_workers_share_refresh_results_and_failures(self):
        for outcome in ("success", "rejected"):
            with self.subTest(outcome=outcome):
                self.write_auth(expires=0)
                attempts = self.root / "refresh-attempts"
                attempts.unlink(missing_ok=True)
                with concurrent.futures.ProcessPoolExecutor(
                    max_workers=3, mp_context=multiprocessing.get_context("spawn")
                ) as pool:
                    results = list(pool.map(refresh_in_process, [str(self.auth)] * 3, [outcome] * 3))
                expected = "sk-ant-oat-worker" if outcome == "success" else "waiting"
                self.assertEqual(results, [expected] * 3)
                self.assertEqual(attempts.read_text().splitlines(), ["attempt"])

    def test_killed_refresher_leaves_a_durable_guard_against_replay(self):
        self.write_auth(expires=0)
        worker = multiprocessing.get_context("spawn").Process(
            target=refresh_in_process, args=(str(self.auth), "crash"),
        )
        worker.start()
        worker.join(15)
        if worker.is_alive():
            worker.kill()
            worker.join()
            self.fail("refresh worker did not exit")
        self.assertEqual(worker.exitcode, 17)
        for lock in (self.root / ".oauth_refresh.lock", Path(f"{self.root}.lock")):
            os.utime(lock, (time.time() - 120, time.time() - 120))
        with mock.patch.object(oauth, "_refresh") as refresh:
            with self.assertRaisesRegex(oauth.ClaudeOAuthError, "interrupted attempt"):
                oauth.access_token()
        refresh.assert_not_called()
        self.write_auth("sk-ant-oat-new-login")
        self.assertEqual(oauth.access_token(), "sk-ant-oat-new-login")

    def test_incomplete_stream_and_truncated_output_are_not_saved_as_moves(self):
        client = self.client()
        for events, retryable in ((message_events()[:-1], True),
                                  (message_events(stop_reason="max_tokens"), False)):
            self.reply = lambda: sse(events)
            with self.assertRaises(arena.ArenaError):
                self.call(client)
            entry = json.loads((self.root / "raw.jsonl").read_text().splitlines()[-1])
            self.assertFalse(entry["ok"])
            self.assertEqual(entry["retryable"], retryable)
        self.assertEqual(entry["usage"]["output_tokens"], 30)

    def test_http_failures_preserve_retry_information(self):
        client = self.client()
        api, player = arena._llm_player_config("opus-5-high-api")
        for status, retryable in ((400, False), (429, True), (503, True)):
            self.reply = lambda: httpx.Response(status, headers={"retry-after": "120"},
                                                json={"type": "error", "error": {
                                                    "type": "api_error", "message": "failure"}})
            with self.assertRaises(anthropic.APIStatusError) as raised:
                client.create(**arena._llm_request(api, player, "prompt"))
            self.assertEqual(arena._retryable_llm_api_error(raised.exception), retryable)
            self.assertGreaterEqual(arena._llm_api_retry_delay(raised.exception, 1), 120)

    def test_stream_disconnect_closes_response_and_is_retryable(self):
        class BrokenStream(httpx.SyncByteStream):
            closed = False

            def __iter__(self):
                yield sse(message_events()[:1]).content
                raise httpx.ReadError("disconnect")

            def close(self):
                self.closed = True

        broken = BrokenStream()
        self.reply = lambda: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=broken)
        client = self.client()
        api, player = arena._llm_player_config("opus-5-high-api")
        with self.assertRaisesRegex(oauth.ClaudeOAuthError, "transport failed") as raised:
            client.create(**arena._llm_request(api, player, "prompt"))
        self.assertTrue(arena._retryable_llm_api_error(raised.exception))
        self.assertTrue(broken.closed)
        self.assertEqual(raised.exception.arena_usage["input_tokens"], 100)

    def test_stream_overload_after_http_success_is_retryable(self):
        self.reply = lambda: sse(message_events()[:1] + [{
            "type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"},
        }])
        client = self.client()
        api, player = arena._llm_player_config("opus-5-high-api")
        with self.assertRaises(oauth.ClaudeOAuthError) as raised:
            client.create(**arena._llm_request(api, player, "prompt"))
        self.assertTrue(arena._retryable_llm_api_error(raised.exception))
        self.assertEqual(raised.exception.arena_usage["input_tokens"], 100)


if __name__ == "__main__":
    unittest.main()
