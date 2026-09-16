"""Regression coverage for the retained findings in docs/development.md."""

import contextlib
import http.client
import http.server
import io
import json
import runpy
import socket
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import numpy as np

import arena
from tests import test_arena_recovery as recovery
from tests.test_arena_recovery import empty_game


class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        state = {
            name: value
            for name, value in vars(arena._State).items()
            if not name.startswith("__")
        }
        self.enterContext(mock.patch.multiple(arena._State, **state))
        self.name = "gpt5.6-sol-high-api"
        self.anchor = arena._Arena.ANCHOR
        arena._configure(
            replace(
                arena.CONFIG,
                active_players=(self.name,),
                opponent_players=(self.anchor,),
                past_run_names=(),
                total_games=2,
            )
        )

    def record(self, number):
        slot = arena.ScheduledGame(number, 1, self.name, self.anchor)
        return arena._finished_record(
            slot,
            NS(ended=True, score="W+R", reason="resignation"),
            (("B", "resign"),),
            "test",
        )

    def codex_client(self, streams):
        name = "gpt5.6-sol-high-codex-0h"
        client = arena._CodexGameClient.__new__(arena._CodexGameClient)
        client.player_name, client.player = name, arena._llm_player_config(name)[1]
        client.game_number = 1
        client.agentic_harness = client.player.agentic_harness
        client.cwd, client.state_path = self.root, self.root / "thread.json"
        client._usage_total = client._zero_usage()
        client._start_runtime = lambda: None
        client._thread_options = lambda: {}
        client._sdk = NS(
            Sandbox=NS(full_access="full"), ApprovalMode=NS(deny_all="deny")
        )
        client._restart_workspace_runtime = mock.Mock()
        streams = iter(streams)
        client._thread = NS(
            id="thread",
            turn=lambda *a, **kw: NS(
                id="turn", stream=lambda: (event for event in next(streams))
            ),
        )
        return client

    def call(self, client):
        with mock.patch.object(arena.time, "sleep"):
            return arena._call_llm_move(
                client,
                "Legal moves now: pass",
                player_name=client.player_name,
                log_path=self.root / "calls.jsonl",
                compact_log_path=self.root / "compact.jsonl",
                game_number=1,
                move_number=1,
                attempt=1,
            )

    def test_codex_failed_turn_cost_survives_retry_and_recovery(self):
        events = list(
            recovery.AgentCostTests().codex_thread([150000, 150000]).turn().stream()
        )

        def failed():
            yield events[0]
            raise RuntimeError("stream disconnected before completion")

        client = self.codex_client([failed(), events[2:]])
        answer, _, cost = self.call(client)
        self.assertEqual(answer, "pass")
        self.assertAlmostEqual(cost, 1.24)
        for filename in ("calls.jsonl", "compact.jsonl"):
            entries = arena._read_jsonl_objects(self.root / filename, "calls")
            self.assertAlmostEqual(sum(row["cost_usd"] for row in entries), 1.24)
            self.assertEqual(entries[0]["usage"]["input_tokens"], 150000)
        entries = arena._read_jsonl_objects(self.root / "calls.jsonl", "calls")
        self.assertEqual(entries[1]["usage"]["input_tokens"], 150000)
        recovered = arena._recovered_llm_stats(NS(number=1), (), entries)
        self.assertAlmostEqual(recovered.cost_usd, cost)
        self.assertEqual(
            json.loads(client.state_path.read_text())["usage_total"]["input_tokens"],
            300000,
        )

    def test_codex_typed_failure_retries_404_and_503_but_not_401(self):
        from openai_codex.generated.v2_all import TurnCompletedNotification

        for status in (404, 503, 401):
            with self.subTest(status=status):
                failure = NS(
                    method="turn/completed",
                    payload=TurnCompletedNotification(
                        thread_id="thread",
                        turn=dict(
                            id="turn",
                            status="failed",
                            items=[],
                            error={
                                "message": "upstream service unavailable",
                                "codexErrorInfo": {
                                    "httpConnectionFailed": {"httpStatusCode": status}
                                },
                            },
                        ),
                    ),
                )
                success = list(
                    recovery.AgentCostTests().codex_thread([100]).turn().stream()
                )
                client = self.codex_client([[failure], success])
                if status in (404, 503):
                    self.assertEqual(self.call(client)[0], "pass")
                    client._restart_workspace_runtime.assert_called_once()
                else:
                    with self.assertRaises(arena.ArenaError):
                        self.call(client)
                    client._restart_workspace_runtime.assert_not_called()
                entries = arena._read_jsonl_objects(self.root / "calls.jsonl", "calls")
                self.assertEqual(entries[-1]["ok"], status in (404, 503))

    def test_codex_unstructured_404_retries_are_bounded_and_keep_the_move(self):
        from openai_codex.generated.v2_all import TurnCompletedNotification

        failure = NS(
            method="turn/completed",
            payload=TurnCompletedNotification(
                thread_id="thread",
                turn=dict(id="turn", status="failed", items=[], error={
                    "message": "unexpected status 404 Not Found: ",
                    "codexErrorInfo": "other",
                }),
            ),
        )
        success = list(recovery.AgentCostTests().codex_thread([100]).turn().stream())
        for general_limit, failures, recovers, expected_calls in (
            (0, 4, True, 5),
            (0, 5, False, 5),
            (2, 5, False, 2),
        ):
            with (self.subTest(general_limit=general_limit, failures=failures),
                  mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", general_limit)):
                for filename in ("calls.jsonl", "compact.jsonl"):
                    (self.root / filename).unlink(missing_ok=True)
                client = self.codex_client([[failure]] * failures + [success])
                thread = client._thread
                if recovers:
                    self.assertEqual(self.call(client)[0], "pass")
                else:
                    with self.assertRaises(arena.ArenaError):
                        self.call(client)
                entries = arena._read_jsonl_objects(self.root / "calls.jsonl", "calls")
                self.assertEqual(len(entries), expected_calls)
                self.assertTrue(all(row["game"] == 1 and row["move"] == 1 for row in entries))
                self.assertEqual(len({row["request"]["input"] for row in entries}), 1)
                self.assertIs(client._thread, thread)
                self.assertTrue(all(row["retryable"] for row in entries if not row["ok"]))
                if not recovers:
                    self.assertEqual(entries[-1]["recovery_action"], "retry_limit_reached")
                    self.assertIsNone(entries[-1]["retry_in_seconds"])
                self.assertEqual(client._restart_workspace_runtime.call_count,
                                 min(failures, expected_calls))

    def test_codex_unstructured_proxy_502_restarts_runtime_and_recovers(self):
        from openai_codex.generated.v2_all import TurnCompletedNotification

        failure = NS(
            method="turn/completed",
            payload=TurnCompletedNotification(
                thread_id="thread",
                turn=dict(id="turn", status="failed", items=[], error={
                    "message": "unexpected status 502 Bad Gateway: OpenAI proxy request failed",
                    "codexErrorInfo": "other",
                }),
            ),
        )
        success = list(recovery.AgentCostTests().codex_thread([100]).turn().stream())
        client = self.codex_client([[failure], success])
        self.assertEqual(self.call(client)[0], "pass")
        client._restart_workspace_runtime.assert_called_once()


    def test_schedule_is_published_only_after_complete_write(self):
        slots = [arena.ScheduledGame(1, 1, self.name, self.anchor)]
        work = self.root / "batch-001"
        original = arena._write_json

        def fail(path, value):
            if path.name == "schedule.json":
                path.write_text('[{"game":')
                raise OSError("interrupted schedule publication")
            return original(path, value)

        with (
            mock.patch.object(arena, "_ensure_game_dependencies"),
            mock.patch.object(arena, "_write_json", fail),
        ):
            with self.assertRaises(OSError):
                arena.play_batch(slots, [], work)
        self.assertFalse(work.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_legacy_empty_schedule_quarantine_preserves_execution_evidence(self):
        for contents in (None, '[{"game":'):
            work = self.root / "batch-001"
            work.mkdir()
            if contents is not None:
                (work / "schedule.json").write_text(contents)
            self.assertTrue(arena._quarantine_incomplete_batch(work))
            self.assertFalse(work.exists())
        work.mkdir()
        (work / "llm-calls.jsonl").write_text("{}\n")
        self.assertFalse(arena._quarantine_incomplete_batch(work))
        self.assertTrue(work.exists())

    def test_torn_jsonl_tail_repairs_without_losing_complete_records(self):
        for tail in (b'{"game":2,"ok":', b'{"text":"\xe2', b'{"game":2}'):
            with self.subTest(tail=tail):
                path = self.root / "calls.jsonl"
                path.write_bytes(b'{"game":1}\n' + tail)
                entries = arena._read_jsonl_objects(path, "calls")
                expected = (
                    [{"game": 1}, {"game": 2}] if tail.endswith(b"}") else [{"game": 1}]
                )
                self.assertEqual(entries, expected)
                arena._append_jsonl(path, {"game": 3})
                self.assertEqual(
                    arena._read_jsonl_objects(path, "calls"), expected + [{"game": 3}]
                )
        path.write_bytes(b'{"game":1}\nBROKEN\n{"game":3}\n')
        with self.assertRaises(arena.ArenaError):
            arena._read_jsonl_objects(path, "calls")

    def test_history_uses_metadata_committed_prefix(self):
        with mock.patch.multiple(
            arena._Arena,
            ROOT=self.root,
            LOG_ROOT=self.root / "log",
            UNTRACKED_LOG_ROOT=self.root / "untracked_log",
        ):
            run = arena._ArenaRun(None)
            run.done = [self.record(1), self.record(2)]
            run.meta.update(completed_games=2, batch_sizes=[2], completed_batch_ids=[1])
            original = arena._write_json

            def interrupt(path, value):
                if path.name == "run.json":
                    raise OSError("interrupted metadata commit")
                original(path, value)

            with mock.patch.object(arena, "_write_json", interrupt):
                with self.assertRaises(OSError):
                    run._save_reports()
            self.assertEqual(
                arena._load_past_games([run.run], (self.name, self.anchor)), []
            )
            run._save_reports()
            self.assertEqual(
                len(arena._load_past_games([run.run], (self.name, self.anchor))), 2
            )
            arena._write_results(run.run / "results.csv", run.done[:1])
            with self.assertRaises(arena.ArenaError):
                arena._load_past_games([run.run], (self.name, self.anchor))

    def test_results_replacement_keeps_previous_csv_on_failure(self):
        path = self.root / "results.csv"
        arena._write_results(path, [self.record(1)])
        before = path.read_bytes()
        with mock.patch.object(Path, "replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                arena._write_results(path, [self.record(1), self.record(2)])
        self.assertEqual(path.read_bytes(), before)

    def test_optimizer_handles_strongly_contradicted_prior(self):
        games = [
            NS(black=self.name, white=self.anchor, score_black=0.0),
            NS(black=self.anchor, white=self.name, score_black=1.0),
        ] * 50000
        arena._State.config = replace(
            arena._State.config,
            active_player_prior_elo_mean=10000.0,
            active_player_prior_elo_sd=10000.0,
        )
        ratings, _ = arena.fit_ratings_and_color_advantage(
            games, [self.anchor, self.name]
        )
        design, scores, totals, _ = arena._grouped_rating_data(games, {self.name: 0})
        means, precision = arena._prior_vectors([self.name])

        def objective(value):
            return arena._logit_objective(
                design, scores, totals, np.array([value]), means, precision
            )

        self.assertLess(ratings[self.name], -2000)
        self.assertGreaterEqual(objective(ratings[self.name]), objective(-2000))
        self.assertGreaterEqual(
            objective(ratings[self.name]), objective(ratings[self.name] + 0.01)
        )
        self.assertGreaterEqual(
            objective(ratings[self.name]), objective(ratings[self.name] - 0.01)
        )

    def test_self_play_preserves_strength_prior_and_covariance_design(self):
        games = [NS(black=self.name, white=self.name, score_black=1.0)] * 20
        for design in (
            arena._rating_design(games, {self.name: 0})[0],
            arena._grouped_rating_data(games, {self.name: 0})[0],
        ):
            self.assertTrue(np.all(design == 0))
        ratings = arena._fit_no_color_ratings(games, [self.anchor, self.name])
        self.assertEqual(ratings[self.name], arena._rating_prior(self.name)[0])

    def test_rating_records_count_both_colors_self_play_and_unplayed_players(self):
        unplayed = "gpt5.6-sol-low-api"
        games = [
            NS(black=self.name, white=self.anchor, score_black=1.0),
            NS(black=self.anchor, white=self.name, score_black=1.0),
            NS(black=self.name, white=self.anchor, score_black=0.5),
            NS(black=self.name, white=self.name, score_black=1.0),
            NS(black=self.anchor, white=self.anchor, score_black=0.5),
        ]
        names = [self.anchor, self.name, unplayed]
        records = arena.rating_records(
            games, names, {self.anchor: 0.0, self.name: 1000.0, unplayed: 500.0},
        )
        self.assertEqual(
            {row.player: (row.games, row.wins, row.losses, row.draws) for row in records},
            {self.name: (4, 2, 1, 1), self.anchor: (4, 1, 1, 2), unplayed: (0, 0, 0, 0)},
        )

    def test_sgf_ignores_comment_properties_and_moves_and_other_variations(self):
        slot = arena.ScheduledGame(1, 1, "black", "white")
        sgf = (
            r"(;PB[black]PW[white]C[note RE[W+R\];B[aa\]]RE[B+1]"
            r"; B[bb](;W[cc])(;W[dd];B[ee]))"
        )
        record = arena._parse_native_sgf(sgf, slot)
        self.assertEqual(record.winner_color, "B")
        self.assertEqual(record.moves, (("B", "B8"), ("W", "C7")))
        self.assertEqual(arena._unescape_sgf("a\\\r\nb\\]"), "ab]")

    def test_sgf_comment_and_variation_do_not_satisfy_move_cap(self):
        sgf = r"(;PB[black]PW[white]C[;B[aa\];W[bb\]];B[bb](;W[])(;W[cc];B[dd]))"
        (self.root / "games.sgfs").write_text(sgf)
        with self.assertRaisesRegex(arena.ArenaError, "only 2/3 moves"):
            arena._collect_native_games(
                [arena.ScheduledGame(1, 1, "black", "white")], self.root, max_moves=3
            )


    def test_import_and_cli_help_do_not_load_default_history(self):
        with (
            mock.patch.object(
                Path, "is_dir", side_effect=AssertionError("history accessed")
            ),
            mock.patch.object(sys, "argv", ["arena.py", "--help"]),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(arena.__file__, run_name="__main__")
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--run-type", output.getvalue())

    def test_cheap_medium_profile_uses_available_history(self):
        arena._configure(arena.RUN_TYPES["katago_cheap_and_medium"])
        self.assertTrue(arena._State.past_run_dirs)
        self.assertTrue(all(path.is_dir() for path in arena._State.past_run_dirs))

    def test_proxy_accepts_both_model_catalog_routes(self):
        for path in ("/v1/models", "/v1/codex/models"):
            self.assertEqual(
                arena._canonical_openai_proxy_path(path + "?limit=2"),
                "/v1/models?limit=2",
            )
        self.assertIsNone(arena._canonical_openai_proxy_path("/v1/models-evil"))

    def test_table_widths_include_headers(self):
        lines = arena._aligned_table(
            ("Name", "Long column", "Tail"), [("x", "1", "end")], left_aligned=(0, 2)
        )
        self.assertEqual(lines[0].index("Tail"), lines[2].index("end"))
        self.assertEqual(len(lines[0]), len(lines[1]))

    def test_combined_temperature_and_playout_modifiers(self):
        name = f"{arena.KATAGO_NETWORKS[0].name}-temp-0.7-playouts60"
        arena._configure(
            replace(
                arena._State.config,
                active_players=(name,),
                opponent_players=(self.anchor, name),
            )
        )
        bot = next(bot for bot in arena.players() if bot.name == name)
        self.assertEqual(
            (
                bot.max_playouts,
                bot.chosen_move_temperature,
                bot.chosen_move_temperature_early,
            ),
            (60, 0.7, 0.7),
        )

    def test_empty_chat_choices_are_logged_retried_and_replayed(self):
        from openai.types.chat import ChatCompletion

        name = "kimi-k3-high-api-multi"
        api, player = arena._llm_player_config(name)
        replies = [
            ChatCompletion(
                id="local",
                created=0,
                model=player.model,
                object="chat.completion",
                choices=choices,
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "total_tokens": 110,
                },
            )
            for choices in (
                [],
                [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "pass"},
                    }
                ],
            )
        ]
        create = mock.Mock(
            side_effect=[NS(parse=lambda reply=reply: reply) for reply in replies]
        )

        def client():
            return arena.ConversationClient(
                NS(chat=NS(completions=NS(with_raw_response=NS(create=create)))),
                arena.APIConversation(api.name, player.model, name, 1, "chat"),
            )

        opts = dict(
            player_name=name,
            log_path=self.root / "calls.jsonl",
            game_number=1,
            move_number=1,
        )
        stats = arena.LLMGameStats()
        self.assertEqual(
            arena._choose_llm_move(empty_game(), client(), stats, **opts), "pass"
        )
        entries = arena._read_jsonl_objects(opts["log_path"], "calls")
        self.assertEqual(len(entries), 2)
        self.assertEqual(stats.api_problems, 1)
        self.assertGreater(stats.cost_usd, 0)
        with opts["log_path"].open("ab") as log:
            log.write(b'{"game":')
        recovered = arena._recovered_llm_stats(NS(number=1), (), entries)
        self.assertEqual(
            arena._choose_llm_move(empty_game(), client(), recovered, **opts), "pass"
        )
        self.assertEqual(create.call_count, 2)
        self.assertEqual(recovered.cost_usd, stats.cost_usd)
        self.assertEqual(recovered.api_problems, 1)

    def test_torn_native_retry_marker_skips_only_unfinished_attempt(self):
        slot = arena.ScheduledGame(2, 1, "white", "black")
        bot = arena.Player("white", self.root / "model")
        attempt = arena._native_attempt_paths(self.root, 2)[2]
        attempt.mkdir()
        (self.root / "native-attempt-2.complete").write_text("games=")
        complete = self.record(1)

        def finish(slate, bots, work, *, attempt, max_moves, progress):
            self.assertEqual(slate, [slot])
            self.assertEqual(attempt, 3)
            path = arena._native_attempt_paths(work, attempt)[2]
            path.mkdir()
            (path / "games.sgfs").write_text("(;PB[white]PW[black]RE[W+7];B[];W[])")
            return path

        with (
            mock.patch.object(arena, "_ensure_game_dependencies"),
            mock.patch.object(arena, "_run_native_attempt", side_effect=finish),
        ):
            records = arena._retry_capped_native_games(
                [complete],
                [slot],
                [bot],
                self.root,
                first_attempt=2,
                progress=None,
                recovering=True,
            )
        self.assertEqual(records[0], complete)
        self.assertEqual([record.number for record in records], [1, 2])

    def test_external_untracked_symlink_preserves_resume_locator(self):
        repo, storage = self.root / "repo", self.root / "storage"
        repo.mkdir()
        storage.mkdir()
        (repo / "untracked_log").symlink_to(storage, target_is_directory=True)
        base = arena.KATAGO_NETWORKS[0].name
        arena._configure(
            replace(
                arena._State.config,
                active_players=(base,),
                opponent_players=(self.anchor, base),
            )
        )
        with mock.patch.multiple(
            arena._Arena,
            ROOT=repo,
            LOG_ROOT=repo / "log",
            UNTRACKED_LOG_ROOT=repo / "untracked_log",
        ):
            run = arena._ArenaRun(None)
            metadata = json.loads((run.run / "run.json").read_text())
            self.assertEqual(
                metadata["untracked_log_dir"], f"untracked_log/{run.run.name}"
            )
            resumed = arena._ArenaRun(run.run)
            self.assertEqual(resumed.temp_dir, run.temp_dir)
            metadata["untracked_log_dir"] = "<external-path>"
            arena._write_json(run.run / "run.json", metadata)
            self.assertEqual(arena._ArenaRun(run.run).temp_dir, run.temp_dir)


class ProxyIntegrationTests(unittest.TestCase):
    def test_proxy_reloads_oauth_for_each_request_and_reports_missing_login(self):
        class UnixConnection(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(3)
                self.sock.connect(self.host)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            with (
                mock.patch.object(arena, "_codex_auth_source", return_value=auth),
                mock.patch.object(arena.http.client, "HTTPSConnection") as upstream,
            ):
                response = upstream.return_value.getresponse.return_value
                response.status, response.reason = 200, "OK"
                response.getheaders.return_value = [("Content-Type", "application/json")]
                proxy = arena._OpenAIReverseProxy(
                    arena._OpenAIProxyCredential("stale-token", "chatgpt.com", auth_mode="oauth"),
                    root / "proxy.jsonl", write_readable=False,
                )
                try:
                    for token in ("first-token", "renewed-token", None):
                        if token:
                            auth.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {
                                "access_token": token, "account_id": "test-account",
                            }}))
                        else:
                            auth.unlink()
                        response.read1.side_effect = [b"{}", b""]
                        client = UnixConnection(str(proxy.socket_path))
                        try:
                            client.request("POST", "/v1/responses", "{}")
                            reply = client.getresponse()
                            reply.read()
                            self.assertEqual(reply.status, 200 if token else 401)
                        finally:
                            client.close()
                    requests = upstream.return_value.request.call_args_list
                    self.assertEqual([call.args[3]["Authorization"] for call in requests],
                                     ["Bearer first-token", "Bearer renewed-token"])
                finally:
                    proxy.close()
            log = (root / "proxy.jsonl").read_text()
            self.assertNotIn("first-token", log)
            self.assertNotIn("renewed-token", log)

    def test_small_sse_events_stream_and_usage_commits_before_delivery(self):
        release = threading.Event()
        finish = threading.Event()
        usage = {"input_tokens": 150000, "output_tokens": 1000}

        class Upstream(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                body = b'{"object":"list","data":[]}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                def chunk(value):
                    self.wfile.write(f"{len(value):x}\r\n".encode() + value + b"\r\n")
                    self.wfile.flush()

                chunk(b'data: {"type":"heartbeat"}\n\n')
                release.wait(3)
                event = (
                    b"data: "
                    + json.dumps(
                        {
                            "type": "response.completed",
                            "response": {"model": "gpt-5.6-sol", "usage": usage},
                        }
                    ).encode()
                    + b"\n\n"
                )
                # Split the JSON across chunks to exercise incremental parsing.
                chunk(event[:37])
                chunk(event[37:])
                finish.wait(3)
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()

        class UnixConnection(http.client.HTTPConnection):
            def __init__(self, path):
                super().__init__("local", timeout=1)
                self.path = path

            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(self.timeout)
                self.sock.connect(str(self.path))

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                original = http.client.HTTPConnection
                with mock.patch.object(
                    arena.http.client,
                    "HTTPSConnection",
                    lambda *a, **kw: original(
                        "127.0.0.1", server.server_port, timeout=4
                    ),
                ):
                    proxy = arena._OpenAIReverseProxy(
                        arena._OpenAIProxyCredential("dummy", "unused.invalid"),
                        root / "proxy.jsonl",
                        write_readable=False,
                    )
                    client = UnixConnection(proxy.socket_path)
                    try:
                        client.request(
                            "POST",
                            "/v1/responses",
                            "{}",
                            {"Content-Type": "application/json"},
                        )
                        response = client.getresponse()
                        self.assertEqual(
                            response.readline(), b'data: {"type":"heartbeat"}\n'
                        )
                        response.readline()
                        release.set()
                        self.assertIn(b"response.completed", response.readline())
                        entries = arena._read_jsonl_objects(
                            root / "proxy.usage.jsonl", "usage"
                        )
                        self.assertEqual([entry["usage"] for entry in entries], [usage])
                        # The upstream has not closed yet; its full exchange log
                        # is still pending, but the usage is already available.
                        self.assertEqual(
                            len(
                                arena._read_jsonl_objects(root / "proxy.jsonl", "proxy")
                            ),
                            1,
                        )
                        finish.set()
                        response.read()
                        client.close()
                        client = UnixConnection(proxy.socket_path)
                        client.request("GET", "/v1/models")
                        response = client.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertEqual(json.loads(response.read())["data"], [])
                    finally:
                        release.set()
                        finish.set()
                        client.close()
                        proxy.close()
        finally:
            release.set()
            finish.set()
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
