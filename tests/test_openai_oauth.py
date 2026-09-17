"""Exercise subscription authentication and real SDK SSE parsing without network."""

import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx2 as httpx
import openai

import arena


def completed_events(text="D4", *, input_tokens=100):
    items = [
        {
            "id": "rs_test",
            "type": "reasoning",
            "summary": [],
            "encrypted_content": "opaque-reasoning",
        },
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        },
    ]
    response = {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "gpt-5.6-sol",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": items,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": 20,
            "total_tokens": input_tokens + 20,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens_details": {"reasoning_tokens": 15},
        },
    }
    return [
        {"type": "response.output_item.done", "output_index": i, "item": item}
        for i, item in enumerate(items)
    ] + [{"type": "response.completed", "response": response}]


def sse(events):
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(f"data: {json.dumps(event)}\n\n" for event in events),
    )


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.auth = self.root / "auth.json"
        self.write_auth()
        self.stack.enter_context(
            mock.patch.dict(
                arena.os.environ,
                {
                    "CODEX_HOME": str(self.root),
                    "OPENAI_API_KEY": "unused-api-key",
                },
            )
        )
        self.stack.enter_context(
            mock.patch.object(
                arena, "_llm_api_key", side_effect=AssertionError("API key used")
            )
        )
        self.requests = []
        self.reply = lambda: sse(completed_events())
        sdk_class = openai.OpenAI

        def handle(request):
            self.requests.append(request)
            return self.reply()

        def create_sdk(**kwargs):
            return sdk_class(
                **kwargs,
                http_client=httpx.Client(transport=httpx.MockTransport(handle)),
            )

        self.stack.enter_context(mock.patch.object(openai, "OpenAI", create_sdk))

    def write_auth(self, token="oauth-token", account="account", mode="chatgpt"):
        self.auth.write_text(
            json.dumps(
                {
                    "auth_mode": mode,
                    "tokens": {"access_token": token, "account_id": account},
                }
            )
        )

    def client(self, name="gpt5.6-sol-high-api", game=1):
        client = arena._llm_client(name, work_dir=self.root, game_number=game)
        self.stack.callback(client.close)
        return client

    def call(self, client, name="gpt5.6-sol-high-api", move=1):
        return arena._call_llm_move(
            client,
            f"Move {move}: legal moves D4, pass",
            player_name=name,
            log_path=self.root / "raw.jsonl",
            compact_log_path=self.root / "compact.jsonl",
            game_number=1,
            move_number=move,
            attempt=1,
        )

    def test_all_gpt_modes_use_oauth_and_keep_model_and_effort(self):
        api = arena._llm_api_config("openai")
        for name, player in api.players.items():
            with self.subTest(name=name):
                # Separate each player's journal so recovery cannot mix identities.
                for path in self.root.glob("*.jsonl"):
                    path.unlink()
                output, _, cost = self.call(self.client(name), name)
                self.assertEqual(output, "D4")
                self.assertGreater(cost, 0)
                request = self.requests[-1]
                self.assertEqual(
                    str(request.url), "https://chatgpt.com/backend-api/codex/responses"
                )
                self.assertEqual(request.headers["authorization"], "Bearer oauth-token")
                self.assertEqual(request.headers["chatgpt-account-id"], "account")
                self.assertEqual(request.headers["originator"], "codex_cli_rs")
                self.assertEqual(
                    request.headers["openai-beta"], "responses=experimental"
                )
                body = json.loads(request.content)
                self.assertEqual(body["model"], player.model)
                self.assertEqual(body["reasoning"]["effort"], player.level)
                self.assertEqual(
                    body["input"],
                    [
                        {
                            "role": "user",
                            "content": "Move 1: legal moves D4, pass",
                        }
                    ],
                )
                self.assertTrue(body["stream"])
                self.assertFalse(body["store"])
                self.assertEqual(body["include"], ["reasoning.encrypted_content"])
                for field in ("tools", "context_management", "service_tier"):
                    self.assertNotIn(field, body)
                manifest = arena._llm_player_manifest(name)
                self.assertEqual(manifest["auth_mode"], "chatgpt_oauth")
                self.assertEqual(manifest["cost_basis"], "api_equivalent_estimate")

    def test_single_turn_stays_fresh_and_reloads_credentials_without_logging_them(self):
        client = self.client()
        self.call(client)
        self.write_auth(token="renewed-token", account="renewed-account")
        self.call(client, move=3)
        request = self.requests[-1]
        self.assertEqual(request.headers["authorization"], "Bearer renewed-token")
        self.assertEqual(request.headers["chatgpt-account-id"], "renewed-account")
        self.assertEqual(len(json.loads(request.content)["input"]), 1)
        for path in self.root.glob("*.jsonl"):
            log = path.read_text()
            for secret in (
                "oauth-token",
                "renewed-token",
                "unused-api-key",
                "renewed-account",
            ):
                self.assertNotIn(secret, log)
        entry = json.loads((self.root / "raw.jsonl").read_text().splitlines()[0])
        self.assertEqual(entry["usage"]["input_tokens"], 100)
        self.assertEqual(
            entry["usage"]["output_tokens_details"]["reasoning_tokens"], 15
        )

    def test_multi_turn_replays_encrypted_reasoning_and_resets_at_250k(self):
        name = "gpt5.6-sol-high-api-multi"
        client = self.client(name)
        self.call(client, name)
        self.reply = lambda: sse(completed_events(input_tokens=250000))
        self.call(client, name, move=3)
        body = json.loads(self.requests[-1].content)
        self.assertEqual(len(body["input"]), 4)
        self.assertEqual(body["input"][1]["encrypted_content"], "opaque-reasoning")
        self.assertEqual(body["input"][2]["content"][0]["text"], "D4")
        self.assertEqual(body["reasoning"]["context"], "all_turns")
        self.call(client, name, move=5)
        self.assertEqual(len(json.loads(self.requests[-1].content)["input"]), 1)
        self.assertEqual(client.conversation.session, 2)
        self.assertEqual(client.conversation.limit, 250000)

    def test_missing_invalid_and_api_key_logins_never_fall_back(self):
        for contents in (
            None,
            "{",
            "[]",
            '{"auth_mode":"apikey"}',
            '{"auth_mode":"chatgpt","tokens":null}',
        ):
            with self.subTest(contents=contents):
                if contents is None:
                    self.auth.unlink(missing_ok=True)
                else:
                    self.auth.write_text(contents)
                with self.assertRaisesRegex(arena.ArenaError, "OAuth login"):
                    self.client()
        self.assertEqual(self.requests, [])

    def test_stream_completion_fallback_and_truncation(self):
        client = self.client()
        api, player = arena._llm_player_config("gpt5.6-sol-high-api")
        request = arena._llm_request(api, player, "prompt")
        events = completed_events()
        # Some streams deliver complete items only in output_item.done events.
        events[-1]["response"]["output"] = events[-1]["response"]["output"][1:]
        self.reply = lambda: sse(events)
        response = client.create(**request)
        self.assertEqual(response.output_text, "D4")
        self.assertEqual(response.output[0].encrypted_content, "opaque-reasoning")
        self.reply = lambda: sse(events[:-1])
        with self.assertRaisesRegex(arena.ArenaError, "without a completed") as raised:
            client.create(**request)
        self.assertTrue(arena._retryable_llm_api_error(raised.exception))

    def test_midstream_disconnect_is_retryable_and_closes_response(self):
        class BrokenStream(httpx.SyncByteStream):
            closed = False

            def __iter__(self):
                yield b'data: {"type":"response.output_text.delta","delta":"D"}\n\n'
                raise httpx.ReadError("connection dropped")

            def close(self):
                self.closed = True

        stream = BrokenStream()
        self.reply = lambda: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream
        )
        client = self.client()
        api, player = arena._llm_player_config("gpt5.6-sol-high-api")
        with self.assertRaisesRegex(arena.ArenaError, "transport failed") as raised:
            client.create(**arena._llm_request(api, player, "prompt"))
        self.assertTrue(arena._retryable_llm_api_error(raised.exception))
        self.assertTrue(stream.closed)

    def test_chunked_disconnect_retries_same_turn_without_partial_history(self):
        class BrokenStream(httpx.SyncByteStream):
            closed = False

            def __iter__(self):
                # Even a complete output item must not enter history until the
                # entire response completes successfully.
                event = completed_events(text="pass")[1]
                yield f"data: {json.dumps(event)}\n\n".encode()
                raise httpx.RemoteProtocolError(
                    "peer closed connection without sending complete message "
                    "body (incomplete chunked read)"
                )

            def close(self):
                self.closed = True

        name = "gpt5.6-luna-high-api-multi"
        client = self.client(name)
        self.call(client, name)
        history = list(client.conversation.history)
        broken = BrokenStream()
        self.reply = mock.Mock(side_effect=[
            httpx.Response(200, headers={"content-type": "text/event-stream"},
                           stream=broken),
            sse(completed_events()),
        ])
        with mock.patch.object(arena.time, "sleep") as sleep:
            output, _, _ = self.call(client, name, move=3)

        self.assertEqual(output, "D4")
        self.assertTrue(broken.closed)
        sleep.assert_called_once()
        self.assertEqual(self.reply.call_count, 2)
        requests = [json.loads(request.content) for request in self.requests[-2:]]
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(client.conversation.history[:len(history)], history)
        self.assertEqual(len(client.conversation.history), len(history) + 3)
        self.assertNotIn('"text": "pass"', json.dumps(client.conversation.history))
        entries = [json.loads(line) for line in
                   (self.root / "raw.jsonl").read_text().splitlines()]
        failure, success = entries[-2:]
        self.assertFalse(failure["ok"])
        self.assertTrue(failure["retryable"])
        self.assertEqual(failure["api_attempt"], 1)
        self.assertTrue(success["ok"])
        self.assertEqual(success["api_attempt"], 2)

    def test_quota_retry_stays_on_oauth_with_api_key_configured(self):
        name = "gpt5.6-sol-high-api-multi"
        client = self.client(name)
        replies = iter([
            httpx.Response(429, headers={"retry-after": "120"},
                           json={"error": {"message": "usage limit reached"}}),
            sse(completed_events()),
        ])
        self.reply = lambda: next(replies)
        with (mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 2),
              mock.patch.object(arena.time, "sleep") as sleep):
            self.call(client, name)
        self.assertEqual(sleep.call_count, 1)
        self.assertGreaterEqual(sleep.call_args.args[0], 120)
        self.assertEqual(len(self.requests), 2)
        for request in self.requests:
            self.assertEqual(request.url.host, "chatgpt.com")
            self.assertEqual(request.headers["authorization"], "Bearer oauth-token")
        self.assertEqual(self.requests[0].content, self.requests[1].content)

    def test_workspace_requires_oauth_even_with_api_key_configured(self):
        api = arena._llm_api_config("openai_codex_workspace")
        credential = arena._codex_workspace_proxy_credential(api)
        self.assertEqual(credential.auth_mode, "oauth")
        self.auth.unlink()
        with self.assertRaisesRegex(arena.ArenaError, "OAuth login"):
            arena._codex_workspace_proxy_credential(api)
        self.write_auth(mode="apikey")
        with self.assertRaisesRegex(arena.ArenaError, "OAuth login"):
            arena._codex_workspace_proxy_credential(api)

    def test_http_errors_keep_status_and_retry_after(self):
        client = self.client()
        api, player = arena._llm_player_config("gpt5.6-sol-high-api")
        request = arena._llm_request(api, player, "prompt")
        for status, retryable in ((400, False), (401, False), (429, True), (503, True)):
            with self.subTest(status=status):
                self.reply = lambda: httpx.Response(
                    status,
                    headers={"retry-after": "120"},
                    json={"error": {"message": "test failure"}},
                )
                with self.assertRaises(openai.APIStatusError) as raised:
                    client.create(**request)
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(
                    arena._retryable_llm_api_error(raised.exception), retryable
                )
                self.assertGreaterEqual(
                    arena._llm_api_retry_delay(raised.exception, 1), 120
                )

    def test_failed_and_incomplete_responses_are_not_moves(self):
        client = self.client()
        api, player = arena._llm_player_config("gpt5.6-sol-high-api")
        request = arena._llm_request(api, player, "prompt")
        for status, code, retryable in (
            ("failed", "server_error", True),
            ("failed", "context_length_exceeded", False),
            ("incomplete", "max_output_tokens", False),
        ):
            with self.subTest(status=status, code=code):
                response = completed_events()[-1]["response"]
                response["status"] = status
                if status == "failed":
                    response["error"] = {"code": code, "message": code}
                else:
                    response["incomplete_details"] = {"reason": code}
                self.reply = lambda: sse(
                    [
                        {
                            "type": f"response.{status}",
                            "response": response,
                        }
                    ]
                )
                with self.assertRaises(arena.ArenaError) as raised:
                    client.create(**request)
                self.assertEqual(
                    arena._retryable_llm_api_error(raised.exception), retryable
                )
                if code == "context_length_exceeded":
                    self.assertTrue(arena._context_length_error(raised.exception))


if __name__ == "__main__":
    unittest.main()
