"""Track 2 with Claude Code: registry, proxy accounting, and turn protocol.

These tests use fake credentials and a fake stream-json process; they never
start the Claude Code CLI or send a model request.
"""

import contextlib
import http.client
import http.server
import json
import os
import sys
import tempfile
import textwrap
import threading
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest import mock

import arena
from gobench.workspace_runtime import WorkspaceSettings

MODEL = "claude-opus-5-5"
PLAYER = "claude-opus-5-5-high-claude-code-2h"


class ClaudeCodeRegistryTests(unittest.TestCase):
    def test_players_profiles_and_training_budgets(self):
        for hours in (0, 1, 2, 4, 8):
            harness = f"claude-code-{hours}h"
            name = f"claude-opus-5-5-high-{harness}"
            api, player = arena._llm_player_config(name)
            self.assertEqual((api.name, player.model, player.level, player.agentic_harness),
                             ("anthropic_claude_code_workspace", MODEL, "high", harness))
            self.assertEqual(arena._workspace_training_seconds(harness), hours * 3600)
            self.assertIs(arena._workspace_client_class(harness), arena._ClaudeCodeGameClient)
            self.assertEqual(arena.RUN_TYPES[harness].active_players, (name,))
            self.assertEqual(arena.RUN_TYPES[harness].workspace.training_seconds, hours * 3600)
        # Numbered replicas keep the duration from their base name.
        self.assertIs(arena._workspace_client_class_for_player(f"{PLAYER}3"),
                      arena._ClaudeCodeGameClient)
        self.assertIs(arena._workspace_client_class_for_player("gpt6-astra-high-codex-2h"),
                      arena._CodexGameClient)
        self.assertIsNone(arena._workspace_client_class_for_player("opus-5-high-api-multi"))

    def test_manifest_records_the_claude_code_protocol(self):
        # The default clock, independent of the experiment selected in CONFIG.
        default = replace(arena.CONFIG, workspace=WorkspaceSettings())
        with mock.patch.object(arena._State, "config", default):
            manifest = arena._llm_player_manifest(PLAYER)
        self.assertEqual(manifest["kind"], "anthropic_claude_code_workspace_agent")
        self.assertEqual(manifest["network_access"], "anthropic_proxy_only")
        self.assertEqual(manifest["preparation_seconds"], 7200)
        self.assertEqual(manifest["evaluation_seconds"], 1800)
        self.assertEqual(manifest["claude_code_disallowed_tools"], ["WebSearch", "WebFetch"])
        self.assertEqual(manifest["cost_tracking"], "api_equivalent_token_usage")


class ClaudeCodeAccountingTests(unittest.TestCase):
    STREAM = [
        {"type": "message_start", "message": {"model": MODEL, "usage": {
            "input_tokens": 10, "cache_read_input_tokens": 1000,
            "cache_creation_input_tokens": 300,
            "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 200},
            "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {
            "type": "tool_use", "name": "Bash", "input": {}}},
        {"type": "content_block_delta", "index": 0, "delta": {
            "type": "input_json_delta", "partial_json": '{"command": "pip ins'}},
        {"type": "content_block_delta", "index": 0, "delta": {
            "type": "input_json_delta", "partial_json": 'tall numpy"}'}},
        {"type": "content_block_start", "index": 1, "content_block": {
            "type": "server_tool_use", "name": "web_search", "input": {}}},
        {"type": "message_delta", "usage": {"output_tokens": 50}},
        {"type": "message_stop"},
    ]

    def test_stream_usage_completes_at_message_stop_and_prices_cache_tiers(self):
        state, completed = {}, []
        for event in self.STREAM:
            result = arena._AnthropicUnixProxyServer.completed_usage(event, state)
            completed.append(result)
        self.assertEqual(completed[:-1], [None] * (len(self.STREAM) - 1))
        usage = completed[-1]["usage"]
        self.assertEqual(completed[-1]["model"], MODEL)
        self.assertEqual(usage["input_tokens"], 1310)
        self.assertEqual(usage["output_tokens"], 50)
        self.assertEqual(usage["input_tokens_details"],
                         {"cached_tokens": 1000, "cache_write_tokens": 300,
                          "cache_write_1h_tokens": 200})
        expected = (10 * 4.0 + 1000 * 0.2 + 100 * 5.0 + 200 * 8.0 + 50 * 20.0) / 1e6
        cost = arena._llm_call_cost(usage, "anthropic_claude_code_workspace", MODEL)
        self.assertAlmostEqual(cost, expected)
        summed = arena._sum_response_usages([usage, usage])
        self.assertAlmostEqual(
            arena._llm_call_cost(summed, "anthropic_claude_code_workspace", MODEL), 2 * expected
        )

    def test_streamed_tool_calls_are_flagged_once_in_responses(self):
        reasons = [flag["reason"] for flag in arena._claude_internet_tool_flags(self.STREAM)]
        self.assertEqual(reasons, ["network-oriented shell command", "server tool:web_search"])
        self.assertEqual(arena._AnthropicUnixProxyServer.request_flags({"messages": []}), [])

    def test_proxy_paths_tools_and_headers(self):
        server = arena._AnthropicUnixProxyServer
        self.assertEqual(server.canonical_path("/v1/messages?beta=true"), "/v1/messages?beta=true")
        self.assertIsNotNone(server.canonical_path("/v1/messages/count_tokens?beta=true"))
        for path in ("/v1/responses", "/v1/messages/batches", "/api/oauth/profile", "/v1/files"):
            self.assertIsNone(server.canonical_path(path))
        body = {"model": MODEL, "mcp_servers": [{"url": "https://example.com"}], "tools": [
            {"name": "Bash", "input_schema": {}},
            {"name": "Grep", "input_schema": {}},
            {"name": "ToolSearch", "input_schema": {}},
            {"type": "web_search_20250305", "name": "web_search"},
            {"type": "code_execution_20250825", "name": "code_execution"},
        ]}
        filtered, removed = server.filter_request(body)
        self.assertEqual([tool["name"] for tool in filtered["tools"]], ["Bash", "Grep", "ToolSearch"])
        self.assertNotIn("mcp_servers", filtered)
        self.assertEqual(len(removed), 3)
        unchanged = {"model": MODEL, "tools": [{"name": "Bash"}]}
        self.assertIs(server.filter_request(unchanged)[0], unchanged)

        proxy = object.__new__(server)
        headers = proxy.credential_headers(None, {"anthropic-beta": "claude-code-20250219, effort-2025-11-24"})
        self.assertEqual(headers["anthropic-beta"],
                         "claude-code-20250219,effort-2025-11-24,oauth-2025-04-20")
        self.assertIn("x-api-key", server.REPLACED_HEADERS)
        credential = arena._OpenAIProxyCredential(bearer_token="old", host="api.anthropic.com")
        proxy.upstream_status(401, credential)
        self.assertEqual(proxy._rejected_token, "old")
        proxy.upstream_status(200, arena._OpenAIProxyCredential(bearer_token="new", host="x"))
        self.assertIsNone(proxy._rejected_token)


class ClaudeCodeTurnTests(unittest.TestCase):
    def test_result_errors_follow_arena_retry_policy(self):
        def error(status, text):
            return arena._claude_code_result_error(
                {"type": "result", "subtype": "success", "is_error": True,
                 "api_error_status": status, "terminal_reason": "api_error", "result": text})

        overloaded = error(529, "API Error: 529 Overloaded")
        self.assertTrue(arena._retryable_llm_api_error(overloaded))
        self.assertFalse(getattr(overloaded, "arena_auth_wait", False))
        login = error(401, "Failed to authenticate. API Error: 401 Host Claude OAuth login unavailable")
        self.assertTrue(arena._retryable_llm_api_error(login))
        self.assertTrue(login.arena_auth_wait)
        self.assertEqual(arena._llm_api_retry_delay(login, 1), arena.CLAUDE_AUTH_POLL_SECONDS)
        policy = error(403, "API Error: 403 request must use this player's configured model")
        self.assertFalse(arena._retryable_llm_api_error(policy))
        too_long = arena._claude_code_result_error(
            {"type": "result", "is_error": True, "terminal_reason": "blocking_limit",
             "result": "Prompt is too long"})
        self.assertIsNone(too_long.status_code)
        self.assertFalse(arena._retryable_llm_api_error(too_long))
        legacy = error(None, "API Error: 500 Internal server error")
        self.assertEqual(legacy.status_code, 500)

    def test_turns_use_one_persistent_stream_json_session(self):
        fake = textwrap.dedent('''
            import json, sys
            turns = 0
            for line in sys.stdin:
                message = json.loads(line)
                assert message["type"] == "user" and message["message"]["role"] == "user"
                turns += 1
                if turns == 3:
                    print("fatal: simulated crash", file=sys.stderr, flush=True)
                    sys.exit(3)
                emit = lambda value: print(json.dumps(value), flush=True)
                emit({"type": "system", "subtype": "init", "session_id": message["session_id"]})
                emit({"type": "assistant", "message": {"content": [
                    {"type": "text", "text": "thinking"},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "python3 mcts.py"}},
                    {"type": "tool_use", "name": "Write", "input": {"file_path": "/workspace/book.txt"}},
                ]}})
                if turns == 2:
                    emit({"type": "result", "subtype": "success", "is_error": True,
                          "api_error_status": 529, "result": "API Error: 529 Overloaded"})
                else:
                    emit({"type": "result", "subtype": "success", "is_error": False,
                          "result": "C3", "session_id": message["session_id"]})
        ''')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = object.__new__(arena._ClaudeCodeGameClient)
            client._phase_dir = root
            client.state_path = root / "thread.json"
            client.home = root / "runtime"
            client._thread = None
            session = client._persistent_thread()
            self.assertEqual(str(uuid.UUID(session)), session)
            self.assertFalse(json.loads(client.state_path.read_text())["has_turns"])
            self.assertFalse(client._session_exists(session))
            client._claude = arena._ClaudeCodeProcess(
                [sys.executable, "-c", fake], cwd=directory, stderr_path=root / "stderr.log")
            try:
                result, requests = client._run_turn(session, "Legal moves: C3, pass")
                self.assertEqual((result.final_response, requests), ("C3", []))
                self.assertIsNone(result.usage)
                self.assertEqual(client._tool_calls(result), [
                    {"type": "Bash", "item": {"command": "python3 mcts.py", "status": "requested"}},
                    {"type": "Write", "item": {"name": "Write", "status": "requested", "changes": [
                        {"kind": "write", "path": "/workspace/book.txt"}]}},
                ])
                self.assertTrue(json.loads(client.state_path.read_text())["has_turns"])
                with self.assertRaises(arena._ClaudeCodeTurnError) as failed:
                    client._run_turn(session, "again")
                self.assertEqual(failed.exception.status_code, 529)
                with self.assertRaises(arena._ClaudeCodeTurnError) as crashed:
                    client._run_turn(session, "crash")
                self.assertTrue(arena._retryable_llm_api_error(crashed.exception))
                self.assertIn("simulated crash", str(crashed.exception))
                self.assertFalse(client._claude.alive())
            finally:
                client._claude.close()
            # A restarted runtime reloads the same session.
            client._thread = None
            self.assertEqual(client._persistent_thread(), session)
            (client.home / "claude-home" / "projects" / "-workspace").mkdir(parents=True)
            (client.home / "claude-home" / "projects" / "-workspace" / f"{session}.jsonl").touch()
            self.assertTrue(client._session_exists(session))


@contextlib.contextmanager
def fake_anthropic_server():
    """A streaming Messages endpoint standing in for api.anthropic.com."""
    calls = []

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append({"path": self.path, "headers": dict(self.headers), "body": request})
            usage = {"input_tokens": 100, "cache_read_input_tokens": 0,
                     "cache_creation_input_tokens": 0, "output_tokens": 1}
            events = [
                {"type": "message_start", "message": {
                    "id": f"msg_{len(calls)}", "type": "message", "role": "assistant",
                    "model": request["model"], "content": [], "stop_reason": None, "usage": usage}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "pass"}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}},
                {"type": "message_stop"},
            ]
            body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                           for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    original = http.client.HTTPConnection
    try:
        with (mock.patch.object(arena.http.client, "HTTPSConnection",
                                lambda *_a, **_k: original("127.0.0.1", server.server_port, timeout=5)),
              mock.patch.object(arena, "_claude_oauth_access_token",
                                return_value="sk-ant-oat01-test-host-token")):
            yield calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@unittest.skipUnless(os.environ.get("GOBENCH_RESOURCE_TESTS") == "1",
                     "set GOBENCH_RESOURCE_TESTS=1 for real local Linux resource tests")
class ClaudeCodeResourceIntegrationTests(unittest.TestCase):
    """The installed native Claude Code inside the real sandbox, with fake responses."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="gobench-claude-test-")))
        self.work = self.root / "untracked_log" / "run" / "batch-001"
        self.work.mkdir(parents=True)

    def arena_paths(self, settings):
        return (mock.patch.object(arena._Arena, "ROOT", self.root),
                mock.patch.object(arena._Arena, "UNTRACKED_LOG_ROOT", self.root / "untracked_log"),
                mock.patch.object(arena._State, "config", replace(arena.CONFIG, workspace=settings)))

    def test_real_claude_code_answers_and_resumes_its_session(self):
        settings = WorkspaceSettings(training_seconds=0, evaluation_seconds=60, storage_mib=256)
        name = "claude-opus-5-5-low-claude-code-0h"
        player = arena._llm_player_config(name)[1]
        with contextlib.ExitStack() as stack:
            for patch in self.arena_paths(settings):
                stack.enter_context(patch)
            calls = stack.enter_context(fake_anthropic_server())
            client = arena._ClaudeCodeGameClient(name, player, self.work, 1)
            try:
                client.begin_turn(1, 1, 1, 1, "Legal moves: pass", self.root / "calls.jsonl")
                response = client.create(model=player.model, reasoning={"effort": "low"},
                                         input="Legal moves: pass")
                self.assertEqual(response.output_text, "pass")
                self.assertGreater(response.usage["input_tokens"], 0)
                session = client._persistent_thread()
            finally:
                client.close()
            self.assertTrue(calls)
            self.assertEqual({call["body"]["model"] for call in calls}, {player.model})
            self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer sk-ant-oat01-test-host-token")
            self.assertIn("oauth-2025-04-20", calls[0]["headers"]["anthropic-beta"])
            log = (client._phase_dir / "anthropic-proxy.jsonl").read_text()
            self.assertNotIn("test-host-token", log)
            resumed = arena._ClaudeCodeGameClient(name, player, self.work, 1)
            try:
                self.assertEqual(resumed._persistent_thread(), session)
                self.assertTrue(resumed._session_exists(session))
                resumed.begin_turn(1, 2, 1, 1, "second-move-sentinel\nLegal moves: pass",
                                   self.root / "calls.jsonl")
                resumed.create(model=player.model, reasoning={"effort": "low"},
                               input="second-move-sentinel\nLegal moves: pass")
            finally:
                resumed.close()
            history = json.dumps(calls[-1]["body"]["messages"])
            self.assertIn("Request: gobench-game-1-move-1-attempt-1", history)
            self.assertIn("second-move-sentinel", history)

    def test_real_preparation_checkpoint_isolates_evaluation_games(self):
        settings = WorkspaceSettings(training_seconds=5, evaluation_seconds=60, storage_mib=256)
        name = "claude-opus-5-5-low-claude-code-1h"
        player = arena._llm_player_config(name)[1]
        with contextlib.ExitStack() as stack:
            for patch in self.arena_paths(settings):
                stack.enter_context(patch)
            stack.enter_context(mock.patch.dict(
                arena._CLAUDE_CODE_TRAINING_SECONDS, {"claude-code-1h": settings.training_seconds}))
            calls = stack.enter_context(fake_anthropic_server())
            first = arena._ClaudeCodeGameClient(name, player, self.work, 1)
            try:
                self.assertGreater(first.checkpoint["training_model_requests"], 0)
                self.assertGreater(first.checkpoint["training_cost_usd"], 0)
                prompt = "evaluation-sentinel-one\nLegal moves: pass"
                first.begin_turn(1, 1, 1, 1, prompt, self.root / "calls.jsonl")
                first.create(model=player.model, reasoning={"effort": "low"}, input=prompt)
                (first.cwd / "evaluation-only.txt").write_text("must not transfer")
                checkpoint_id = first.checkpoint["checkpoint_id"]
            finally:
                first.close()
            second = arena._ClaudeCodeGameClient(name, player, self.work, 2)
            try:
                self.assertEqual(second.checkpoint["checkpoint_id"], checkpoint_id)
                self.assertFalse((second.cwd / "evaluation-only.txt").exists())
                prompt = "evaluation-sentinel-two\nLegal moves: pass"
                second.begin_turn(2, 1, 1, 1, prompt, self.root / "calls.jsonl")
                second.create(model=player.model, reasoning={"effort": "low"}, input=prompt)
                self.assertGreater(second._clock.remaining, 0)
            finally:
                second.close()
            history = json.dumps(calls[-1]["body"]["messages"])
            self.assertIn("evaluation-sentinel-two", history)
            self.assertIn("You are preparing to play 9x9 Go", history)
            self.assertNotIn("evaluation-sentinel-one", history)


if __name__ == "__main__":
    unittest.main()
