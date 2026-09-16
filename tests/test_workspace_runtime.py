"""Checkpoint and budget regressions; optional real Linux sandbox integration.

GOBENCH_RESOURCE_TESTS=1 enables local cgroup/mount/SDK tests. They use fake
credentials and fake model results; no test sends a paid model request.
"""

import contextlib
import concurrent.futures
import http.client
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import arena
from gobench.workspace_runtime import (
    AgentClock, CoreLease, ProcessScope, WorkspaceError, WorkspaceSettings,
    WorkspaceResourceExceeded, WorkspaceTimeExpired, WorkspaceVolume, atomic_json, file_sha256,
    physical_cores, parse_cpu_list,
)


@contextlib.contextmanager
def fake_openai_server():
    """A real streaming HTTP endpoint for exercising the installed Codex binary."""
    calls = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            body = b'{"object":"list","data":[]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(request)
            message = {"id": "msg_fake", "type": "message", "role": "assistant",
                       "status": "completed", "phase": "final_answer",
                       "content": [{"type": "output_text", "text": "pass", "annotations": []}]}
            response = {"id": f"resp_fake_{len(calls)}", "object": "response", "created_at": 0,
                        "model": request["model"], "status": "completed", "output": [message],
                        "usage": {"input_tokens": 100, "output_tokens": 1,
                                  "input_tokens_details": {"cached_tokens": 0},
                                  "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 101}}
            events = [
                {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                {"type": "response.output_item.added", "output_index": 0,
                 "item": {**message, "status": "in_progress", "content": []}},
                {"type": "response.output_text.delta", "item_id": "msg_fake", "output_index": 0,
                 "content_index": 0, "delta": "pass"},
                {"type": "response.output_item.done", "output_index": 0, "item": message},
                {"type": "response.completed", "response": response},
            ]
            body = "".join("data: " + json.dumps({**event, "sequence_number": index}) + "\n\n"
                           for index, event in enumerate(events)).encode()
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
        with mock.patch.object(arena.http.client, "HTTPSConnection",
                               lambda *_a, **_k: original("127.0.0.1", server.server_port, timeout=5)):
            yield calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.now = 100.0

    def clock(self, seconds=100):
        return AgentClock(self.root / "clock.json", seconds, monotonic=lambda: self.now)

    def test_all_moves_share_one_clock_and_opponent_time_is_free(self):
        clock = self.clock()
        for elapsed in (12, 28, 7):
            clock.start(lambda: None)
            self.now += elapsed
            clock.pause()
            self.now += 200  # paused opponent time
        self.assertEqual(clock.remaining, 53)
        self.assertEqual(self.clock().remaining, 53)

    def test_crash_keeps_reserved_time_but_does_not_charge_downtime(self):
        clock = self.clock()
        clock.start(lambda: None)
        clock._stop.set()
        clock._worker.join()
        self.now += 90000
        resumed = self.clock()
        self.assertEqual(resumed.remaining, 99)
        clock._started = None  # simulate the original process having disappeared

    def test_clock_deadline_terminates_work_without_waiting_for_sdk_events(self):
        event = threading.Event()
        clock = AgentClock(self.root / "deadline.json", 0.15)
        clock.start(event.set)
        self.assertTrue(event.wait(2))
        clock.pause()
        self.assertTrue(clock.expired)
        with self.assertRaises(WorkspaceTimeExpired):
            clock.start(event.set)

    def test_resume_rejects_changed_limits_or_corrupt_counters(self):
        self.clock()
        with self.assertRaises(WorkspaceError):
            self.clock(200)
        atomic_json(self.root / "clock.json", {"limit_seconds": 100, "spent_seconds": -2})
        with self.assertRaises(WorkspaceError):
            self.clock()

    def test_resource_settings_validate_before_launch(self):
        for values in ({"training_seconds": -1}, {"evaluation_seconds": 0},
                       {"cpu_cores": float("nan")}, {"cpu_cores": 0.5}, {"max_tasks": True},
                       {"storage_mib": 1}):
            with self.assertRaises(WorkspaceError):
                WorkspaceSettings(**values)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def client(self, seconds=5):
        client = arena._CodexGameClient.__new__(arena._CodexGameClient)
        client.player_name = "gpt5.6-sol-low-codex-0h"
        client.player = arena._llm_player_config(client.player_name)[1]
        client.game_number = 1
        client._phase_dir = self.root
        client._pending_turn = None
        client._clock = AgentClock(self.root / "clock.json", seconds)
        client._scope = NS(thaw=mock.Mock(), freeze=mock.Mock(), kill=mock.Mock(), dead=False,
                           failure_reason=mock.Mock(return_value="success"))
        client._proxy = NS(set_enabled=mock.Mock())
        client._start_runtime = mock.Mock()
        client.begin_turn(1, 1, 1, 1, "position", self.root / "calls.jsonl")
        return client

    def test_eval_clock_includes_tool_and_model_time_and_freezes_after_move(self):
        client = self.client()

        def response(**_):
            time.sleep(0.15)
            return arena._CodexMoveResponse("D4", {})

        client._create_response = response
        self.assertEqual(client.create(input="position").output_text, "D4")
        self.assertGreater(client._clock.spent, 0.1)
        client._scope.freeze.assert_called_once()
        client._scope.thaw.assert_called_once()
        self.assertEqual(client._proxy.set_enabled.call_args.args, (False,))

    def test_deadline_beats_a_late_model_answer(self):
        client = self.client(seconds=0.1)

        def late(**_):
            time.sleep(0.3)
            return arena._CodexMoveResponse("D4", {"input_tokens": 123})

        client._create_response = late
        with self.assertRaises(WorkspaceTimeExpired) as raised:
            client.create(input="position")
        self.assertEqual(raised.exception.arena_usage["input_tokens"], 123)
        client._scope.kill.assert_called()

    def test_completed_response_recovery_never_runs_tools_again(self):
        client = self.client()
        saved = {"state": "completed", "output": "D4", "usage": {"input_tokens": 123},
                 "prompt_sha256": client._turn_context["prompt_sha256"]}
        atomic_json(client._journal_path(), saved)
        client._create_response = mock.Mock(side_effect=AssertionError("duplicate turn"))
        response = client.create(input="position")
        self.assertEqual(response.output_text, "D4")
        self.assertFalse(response.reused)  # first durable arena log still needs writing
        client._start_runtime.assert_not_called()
        arena._append_jsonl(self.root / "calls.jsonl", {
            "game": 1, "move": 1, "attempt": 1, "player": client.player_name,
            "ok": True, "output": "D4",
        })
        self.assertTrue(client.create(input="position").reused)

    def test_oom_forfeit_survives_cleanup_of_a_removed_cgroup(self):
        for cleanup_error in (FileNotFoundError("removed"),
                              WorkspaceError("tee failed: cgroup no longer exists")):
            with self.subTest(cleanup_error=type(cleanup_error).__name__):
                client = self.client()
                failure = WorkspaceResourceExceeded("agent exceeded its memory allocation")
                failure.arena_usage = {"input_tokens": 123}
                client._create_response = mock.Mock(side_effect=failure)
                client._scope.freeze.side_effect = cleanup_error
                with self.assertRaises(WorkspaceResourceExceeded) as raised:
                    client.create(input="position")
                self.assertIs(raised.exception, failure)
                self.assertEqual(raised.exception.arena_usage, {"input_tokens": 123})
                self.assertFalse(json.loads((self.root / "clock.json").read_text())["active"])

    def test_oom_during_response_or_freeze_is_a_memory_forfeit(self):
        for response_failed in (False, True):
            with self.subTest(response_failed=response_failed):
                client = self.client()
                usage = {"input_tokens": 123}
                failure = RuntimeError("runtime disconnected")
                failure.arena_usage = usage
                client._create_response = mock.Mock(
                    side_effect=failure if response_failed else None,
                    return_value=arena._CodexMoveResponse("D4", usage),
                )
                client._scope.freeze.side_effect = WorkspaceError("cgroup disappeared")
                client._scope.failure_reason.return_value = "oom-kill"
                with self.assertRaises(WorkspaceResourceExceeded) as raised:
                    client.create(input="position")
                self.assertEqual(raised.exception.arena_usage, usage)
                self.assertFalse(json.loads((self.root / "clock.json").read_text())["active"])
                self.assertFalse(client._journal_path().exists())

    def test_non_oom_cleanup_failure_still_stops_the_run(self):
        client = self.client()
        client._create_response = mock.Mock(return_value=arena._CodexMoveResponse("D4", {}))
        failure = WorkspaceError("cannot freeze agent")
        client._scope.freeze.side_effect = failure
        with self.assertRaises(WorkspaceError) as raised:
            client.create(input="position")
        self.assertIs(raised.exception, failure)

    def test_preparation_404_retries_are_bounded_without_resetting_clock(self):
        client = self.client(seconds=30)
        client.settings = WorkspaceSettings()
        client._resource_instructions = mock.Mock(return_value="resources")
        client._persistent_thread = mock.Mock()
        client._turn_options = mock.Mock(return_value={})
        client._run_turn = mock.Mock(side_effect=RuntimeError("unexpected status 404 Not Found"))
        client._dispose_runtime = mock.Mock()
        client._expire_runtime = mock.Mock()
        clock = client._clock
        with (mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 0),
              mock.patch.object(arena.time, "sleep"),
              self.assertRaisesRegex(RuntimeError, "404")):
            client._run_preparation()
        self.assertEqual(client._run_turn.call_count, 5)
        self.assertEqual(client._dispose_runtime.call_count, 4)
        self.assertIs(client._clock, clock)
        self.assertGreater(clock.spent, 0)
        self.assertFalse(json.loads((self.root / "clock.json").read_text())["active"])

    def test_evaluation_404_retries_preserve_clock_and_exclude_backoff(self):
        client = self.client(seconds=30)
        now = [100.0]
        client._clock = AgentClock(self.root / "clock.json", 30, monotonic=lambda: now[0])
        clock = client._clock
        attempts = []

        def response(**request):
            attempts.append(request)
            now[0] += 2
            if len(attempts) < 3:
                raise arena._WorkspaceCodexTransportError("unexpected status 404 Not Found")
            return arena._CodexMoveResponse("pass", {})

        def backoff(_delay):
            self.assertFalse(json.loads((self.root / "clock.json").read_text())["active"])
            now[0] += 100

        client._create_response = response
        with mock.patch.object(arena.time, "sleep", side_effect=backoff):
            answer, _, _ = arena._call_llm_move(
                client, "position", player_name=client.player_name,
                log_path=self.root / "calls.jsonl", game_number=1, move_number=1, attempt=1,
            )
        self.assertEqual(answer, "pass")
        self.assertEqual(len(attempts), 3)
        self.assertTrue(all(request == attempts[0] for request in attempts))
        self.assertIs(client._clock, clock)
        self.assertEqual(clock.spent, 6)
        self.assertEqual(clock.remaining, 24)

    def test_recovery_rejects_an_answer_for_a_different_position(self):
        client = self.client()
        atomic_json(client._journal_path(), {"state": "completed", "prompt_sha256": "wrong"})
        with self.assertRaisesRegex(WorkspaceError, "current position"):
            client.create(input="position")

    def test_timeout_is_not_retried_as_an_api_error(self):
        name = "gpt5.6-sol-low-codex-0h"
        client = NS(create=mock.Mock(side_effect=WorkspaceTimeExpired("expired")))
        with self.assertRaises(WorkspaceTimeExpired):
            arena._call_llm_move(client, "position", player_name=name,
                                 log_path=self.root / "calls.jsonl",
                                 game_number=1, move_number=1, attempt=1)
        client.create.assert_called_once()
        logged = json.loads((self.root / "calls.jsonl").read_text())
        self.assertFalse(logged["retryable"])

    def test_timeout_records_a_loss_in_both_colors_and_does_not_restart_games(self):
        self.check_resource_loss(WorkspaceTimeExpired("expired"), "T", "agent_time_limit")

    def test_oom_records_a_loss_in_both_colors_and_continues_the_batch(self):
        self.check_resource_loss(WorkspaceResourceExceeded("out of memory"),
                                 "F", "agent_memory_limit")

    def check_resource_loss(self, failure, suffix, reason):
        name = "gpt5.6-sol-low-codex-0h"
        anchor = arena._Arena.ANCHOR
        slots = [arena.ScheduledGame(1, 1, name, anchor),
                 arena.ScheduledGame(2, 1, anchor, name)]
        client = NS(reset_game=mock.Mock())
        failure.arena_api_seconds = 3
        failure.arena_cost_usd = 0.25
        with (mock.patch.object(arena, "_ensure_game_dependencies"),
              mock.patch.object(arena, "_write_random_bot_configs", return_value={}),
              mock.patch.object(arena._Arena, "UNTRACKED_LOG_ROOT", self.root),
              mock.patch.object(arena._CodexGameClient, "prune_evaluation_images",
                                wraps=arena._CodexGameClient.prune_evaluation_images) as prune,
              mock.patch.object(arena, "_llm_client", return_value=client),
              mock.patch.object(arena, "_game_engine", side_effect=lambda *_: contextlib.nullcontext(
                  NS(get_move_history=lambda: (("B", "D4"),))
              )),
              mock.patch.object(arena, "_play_llm_game", side_effect=failure) as play):
            records = arena.run_llm_games(slots, [arena.Player(anchor, None)], self.root, progress=None)
            self.assertEqual([record.result for record in records], [f"W+{suffix}", f"B+{suffix}"])
            self.assertTrue(all(record.reason == reason for record in records))
            self.assertTrue(all(record.winner == anchor for record in records))
            self.assertTrue(all(record.llm_cost_usd == 0.25 for record in records))
            self.assertEqual(play.call_count, 2)
            recovered = arena.run_llm_games(slots, [arena.Player(anchor, None)], self.root, progress=None)
            self.assertEqual(recovered, records)
            self.assertEqual(play.call_count, 2)
            prune.assert_called_once_with(self.root, name, {
                self.root / "agent-workspaces" / "game-000001",
                self.root / "agent-workspaces" / "game-000002",
            })
        client.reset_game.assert_not_called()

    def test_named_duration_overrides_shared_training_default_and_matches_manifest(self):
        work = self.root / "run" / "batch-001"
        work.mkdir(parents=True)
        settings = WorkspaceSettings(training_seconds=17, evaluation_seconds=90)
        with (mock.patch.object(arena._Arena, "UNTRACKED_LOG_ROOT", self.root),
              mock.patch.object(arena._State, "config", replace(arena.CONFIG, workspace=settings)),
              mock.patch.object(arena._CodexGameClient, "_prepare")):
            for hours in (0, 1, 2, 4, 8):
                for instance in ("", "2"):
                    name = f"gpt5.6-sol-low-codex-{hours}h{instance}"
                    client = arena._CodexGameClient(name, arena._llm_player_config(name)[1], work, 1)
                    expected = replace(settings, training_seconds=hours * 3600)
                    self.assertEqual(client.settings, expected)
                    self.assertEqual(client._continual, hours > 0)
                    manifest = arena._llm_player_manifest(name)
                    self.assertEqual(manifest["preparation_seconds"], hours * 3600)
                    self.assertEqual(manifest["resources"], expected.manifest())
                    self.assertEqual(manifest["evaluation_seconds"], 90)

    def test_fresh_checkpoint_uses_a_fresh_rating_prior(self):
        name = "gpt5.6-sol-low-codex-1h"
        config = replace(arena.CONFIG, active_players=(name,),
                         active_player_prior_elo_mean=0, active_player_prior_elo_sd=10000)
        with (mock.patch.object(arena._State, "config", config),
              mock.patch.object(arena._State, "past_player_priors", {name: (5000, 1)})):
            self.assertEqual(arena._rating_prior(name), (0, 10000))

    def test_workspace_configuration_round_trips_and_legacy_runs_are_rejected(self):
        name = "gpt5.6-sol-low-codex-1h"
        settings = WorkspaceSettings(training_seconds=12, evaluation_seconds=90,
                                     memory_mib=512, storage_mib=128, max_tasks=64)
        metadata = {
            "arena_log_schema_version": 4, "arena_players": [name, arena._Arena.ANCHOR],
            "active_players": [name], "opponent_players": [arena._Arena.ANCHOR],
            "past_run_dirs": [], "batch_policy": {"games_per_player_per_batch": 2},
            "katago_backend": "cpu", "total_games": 2,
            "active_player_prior_elo_mean": 0, "active_player_prior_elo_sd": 10000,
            "codex_workspace": settings.manifest(),
        }
        self.assertEqual(arena._config_from_metadata(metadata).workspace, settings)
        metadata.pop("codex_workspace")
        with self.assertRaisesRegex(arena.ArenaError, "legacy Codex"):
            arena._config_from_metadata(metadata)


class AllocationAndRetentionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_topology_groups_smt_siblings_across_sockets_and_rejects_one_core(self):
        (self.root / "online").write_text("0-3,6-7")
        for cpu, package, core in ((0, 0, 0), (1, 0, 1), (2, 1, 0),
                                   (3, 1, 1), (6, 0, 0), (7, 0, 1)):
            topology = self.root / f"cpu{cpu}" / "topology"
            topology.mkdir(parents=True)
            (topology / "physical_package_id").write_text(str(package))
            (topology / "core_id").write_text(str(core))
        self.assertEqual(physical_cores(self.root), [(0, 6), (1, 7), (2,), (3,)])
        (self.root / "online").write_text("0,6")
        with self.assertRaisesRegex(WorkspaceError, "only 1 core"):
            physical_cores(self.root)

    def test_default_image_is_two_gib_but_allocates_only_metadata(self):
        volume = WorkspaceVolume(self.root, WorkspaceSettings().storage_mib)
        volume.create()
        self.assertEqual(volume.image.stat().st_size, 2 * 1024**3)
        self.assertLess(volume.image.stat().st_blocks * 512, 128 * 1024**2)

    def client(self, game, *, player="player", run="run"):
        client = arena._CodexGameClient.__new__(arena._CodexGameClient)
        client.player_name = player
        client.game_number = game
        client.run_dir = self.root / run
        client.checkpoint_root = client.run_dir / "codex-checkpoints" / player
        client.checkpoint_root.mkdir(parents=True, exist_ok=True)
        client.checkpoint = {"checkpoint_id": "checkpoint"}
        client._phase_dir = client.run_dir / "batch-001" / "agent-workspaces" / f"game-{game:06d}"
        client._phase_dir.mkdir(parents=True, exist_ok=True)
        (client._phase_dir / "disk.img").write_bytes(b"evaluation")
        (client._phase_dir / "turns.jsonl").write_text("logs")
        client._clock = NS(spent=1, remaining=4, pause=mock.Mock())
        client._dispose_runtime = mock.Mock()
        client._volume = NS(close=mock.Mock())
        return client

    def test_retention_preserves_current_pair_training_incomplete_and_logs(self):
        first, last = self.client(9), self.client(1)
        incomplete = self.client(10)
        other_player = self.client(20, player="other")
        other_run = self.client(30, run="other-run")
        training = first.checkpoint_root / "checkpoint" / "disk.img"
        training.parent.mkdir()
        training.write_bytes(b"training")
        other_player.mark_complete()
        other_run.mark_complete()
        first.mark_complete()
        self.assertTrue((first._phase_dir / "disk.img").exists())
        last._volume.close.side_effect = lambda: self.assertFalse(
            (last._phase_dir / "evaluation-summary.json").exists())
        last.mark_complete()
        self.assertTrue((first._phase_dir / "disk.img").exists())
        arena._CodexGameClient.prune_evaluation_images(
            first.run_dir, first.player_name, {last._phase_dir, incomplete._phase_dir},
        )
        self.assertFalse((first._phase_dir / "disk.img").exists())
        self.assertTrue((first._phase_dir / "evaluation-summary.json").exists())
        self.assertTrue((first._phase_dir / "turns.jsonl").exists())
        self.assertTrue(training.exists())
        for client in (last, incomplete, other_player, other_run):
            self.assertTrue((client._phase_dir / "disk.img").exists())

    def test_next_pair_deletes_previous_pair_before_creating_images(self):
        clients = [self.client(number) for number in (1, 2)]
        training = clients[0].checkpoint_root / "checkpoint" / "disk.img"
        training.parent.mkdir()
        training.write_bytes(b"training")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda client: client.mark_complete(), clients))
        self.assertEqual(len(list(clients[0].run_dir.rglob("disk.img"))), 3)
        arena._CodexGameClient.prune_evaluation_images(
            clients[0].run_dir, clients[0].player_name, set(),
        )
        self.assertEqual(list(clients[0].run_dir.rglob("disk.img")), [training])
        for number in (3, 4):
            self.client(number).mark_complete()
            self.assertLessEqual(len(list(clients[0].run_dir.rglob("disk.img"))), 3)
        for client in clients:
            self.assertTrue((client._phase_dir / "evaluation-summary.json").exists())
            self.assertTrue((client._phase_dir / "turns.jsonl").exists())

    def test_valid_checkpoint_removes_redundant_preparation_image(self):
        client = self.client(1)
        checkpoint = client.checkpoint_root / "checkpoint"
        checkpoint.mkdir()
        image = checkpoint / "disk.img"
        image.write_bytes(b"training")
        preparation = client.checkpoint_root / "preparation"
        preparation.mkdir()
        (preparation / "disk.img").write_bytes(b"training")
        atomic_json(checkpoint / "manifest.json", {
            "specification": {}, "image_sha256": file_sha256(image),
            "thread_sha256": None,
        })
        client._ensure_checkpoint({})
        self.assertTrue(image.exists())
        self.assertFalse((preparation / "disk.img").exists())


@unittest.skipUnless(os.environ.get("GOBENCH_RESOURCE_TESTS") == "1",
                     "set GOBENCH_RESOURCE_TESTS=1 for real local Linux resource tests")
class ResourceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="gobench-resource-test-")))

    def test_core_pool_excludes_host_waits_when_full_and_reuses_a_released_core(self):
        cores = physical_cores()
        if len(cores) > 16:
            self.skipTest("avoid reserving a large host for this integration test")
        leases = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        pending = None
        try:
            for _ in cores[1:]:
                leases.append(CoreLease())
            allocated = [lease.cpus for lease in leases]
            self.assertEqual(sorted(allocated), sorted(cores[1:]))
            host = parse_cpu_list(Path("/sys/fs/cgroup/cpuset.cpus.effective").read_text())
            self.assertEqual(host, set(cores[0]))
            pending = executor.submit(CoreLease)
            time.sleep(0.3)
            self.assertFalse(pending.done())
            released = leases.pop()
            released.close()
            replacement = pending.result(timeout=15)
            pending = None
            leases.append(replacement)
            self.assertEqual(replacement.cpus, released.cpus)
        finally:
            for lease in leases:
                lease.close()
            if pending is not None:
                pending.result(timeout=15).close()
            executor.shutdown(wait=True)
        self.assertEqual(parse_cpu_list(Path("/sys/fs/cgroup/cpuset.cpus.effective").read_text()),
                         {cpu for core in cores for cpu in core})

    def test_killed_arena_releases_its_core_and_stops_its_sandbox(self):
        script = (
            "import json,subprocess,time\n"
            "from gobench.workspace_runtime import CoreLease,ProcessScope,WorkspaceSettings\n"
            f"scope=ProcessScope({str(self.root / 'crashed-scope')!r}, WorkspaceSettings())\n"
            "child=subprocess.Popen(scope.command(['/usr/bin/python3','-c',"
            "'import time; print(\"ready\",flush=True); time.sleep(60)']),"
            "stdout=subprocess.PIPE,text=True)\n"
            "assert child.stdout.readline().strip() == 'ready'\n"
            "scope.attach()\n"
            "print(json.dumps({'slice':scope.core.slice,'cpus':scope.core.cpus}),flush=True)\n"
            "time.sleep(60)\n"
        )
        process = subprocess.Popen([sys.executable, "-c", script],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            lease = json.loads(process.stdout.readline())
            partition = Path("/sys/fs/cgroup") / lease["slice"]
            process.kill()
            process.wait(timeout=10)
            deadline = time.monotonic() + 15
            while partition.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(partition.exists(), "dead arena left its sandbox partition running")
            host = parse_cpu_list(Path("/sys/fs/cgroup/cpuset.cpus.effective").read_text())
            self.assertTrue(set(lease["cpus"]) <= host)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=15)

    def test_cgroup_freezes_all_descendants_and_enforces_limits(self):
        settings = WorkspaceSettings(memory_mib=128, storage_mib=64, max_tasks=32)
        scope = ProcessScope(self.root / "scope", settings)
        marker = self.root / "ticks"
        child_script = ("import time\nfrom pathlib import Path\n"
                        f"p = Path({str(marker)!r})\n"
                        "while True:\n p.write_text(str(time.monotonic()))\n time.sleep(0.01)\n")
        script = ("import subprocess,sys,time; "
                  f"subprocess.Popen([sys.executable,'-c',{child_script!r}]); "
                  "print('ready',flush=True); time.sleep(60)")
        process = subprocess.Popen(scope.command(["/usr/bin/python3", "-c", script]),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            scope.attach()
            deadline = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            scope.freeze()
            before = marker.read_text()
            time.sleep(0.15)
            self.assertEqual(marker.read_text(), before)
            scope.thaw()
            time.sleep(0.15)
            self.assertNotEqual(marker.read_text(), before)
        finally:
            scope.close()
            process.wait(timeout=10)
            process.stdout.close()
            process.stderr.close()

    def test_bounded_disk_and_independent_image_copies(self):
        first = WorkspaceVolume(self.root / "first", 64)
        first.create()
        first.mount()
        try:
            (first.mountpoint / "workspace" / "learned.cpp").write_text("int learned = 1;\n")
            with self.assertRaises(OSError):
                with (first.mountpoint / "workspace" / "too-large").open("wb") as out:
                    for _ in range(80):
                        out.write(b"x" * 1024 * 1024)
            (first.mountpoint / "workspace" / "too-large").unlink()
        finally:
            first.close()
        self.assertLess(first.image.stat().st_blocks * 512, 16 * 1024**2)
        digest = file_sha256(first.image)
        for number in (1, 2):
            copy = WorkspaceVolume(self.root / f"evaluation-{number}", 64)
            copy.create(first.image)
            copy.mount()
            try:
                learned = copy.mountpoint / "workspace" / "learned.cpp"
                self.assertEqual(learned.read_text(), "int learned = 1;\n")
                learned.write_text(f"int learned = {number + 1};\n")
            finally:
                copy.close()
        self.assertEqual(file_sha256(first.image), digest)

    def test_cpp_compiles_inside_the_actual_network_isolated_sandbox(self):
        settings = WorkspaceSettings(memory_mib=512, storage_mib=128)
        volume = WorkspaceVolume(self.root / "volume", settings.storage_mib)
        volume.create()
        volume.mount()
        scope = ProcessScope(self.root / "scope", settings)
        socket_path = self.root / "unused.sock"
        socket_path.touch()
        workspace = volume.mountpoint / "workspace"
        sandbox = arena._WorkspaceBubblewrap(
            workspace, volume.mountpoint / "runtime", socket_path,
            binary=arena._CodexGameClient._workspace_bwrap_binary(),
        )
        script = (
            "import subprocess,socket\nfrom pathlib import Path\n"
            "print('ready',flush=True)\ninput()\n"
            "Path('main.cpp').write_text('#include <iostream>\\nint main(){std::cout << 42;}\\n')\n"
            "subprocess.run(['g++','-O3','main.cpp','-o','main'],check=True)\n"
            "assert subprocess.check_output(['./main']) == b'42'\n"
            f"assert not Path({str(Path(arena.__file__).resolve())!r}).exists()\n"
            "try:\n socket.create_connection(('1.1.1.1',443),timeout=0.1)\n"
            "except OSError:\n pass\nelse:\n raise AssertionError('network escaped')\n"
            "print('compiled and isolated',flush=True)\n"
        )
        command = sandbox.command(
            ("/usr/bin/python3", "-c", script), {"PATH": "/usr/bin:/bin", "TMPDIR": "/tmp"},
            writable_mounts=((volume.mountpoint / "tmp", "/tmp"),),
            hidden_paths=arena._workspace_hidden_katago_paths(),
        )
        process = subprocess.Popen(scope.command(command), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            scope.attach()
            out, err = process.communicate("go\n", timeout=30)
            self.assertEqual(process.returncode, 0, err)
            self.assertIn("compiled and isolated", out)
        finally:
            scope.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()
            volume.close()

    def test_memory_overage_is_killed_by_the_kernel_and_identifiable(self):
        scope = ProcessScope(self.root / "scope", WorkspaceSettings(memory_mib=64))
        process = subprocess.Popen(scope.command([
            "/usr/bin/python3", "-c", "print('ready',flush=True); input(); data=bytearray(256*1024*1024)"
        ]), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            scope.attach()

            def allocate(**_):
                process.communicate("go\n", timeout=15)
                failure = RuntimeError("agent process disconnected")
                failure.arena_usage = {"input_tokens": 123}
                raise failure

            client = arena._CodexGameClient.__new__(arena._CodexGameClient)
            client._clock = AgentClock(self.root / "clock.json", 30)
            client._scope = scope
            client._proxy = NS(set_enabled=mock.Mock())
            client._start_runtime = mock.Mock()
            client._saved_turn = mock.Mock(return_value=None)
            client._create_response = allocate
            # Exercise the real cgroup cleanup after the kernel kills it, not
            # just the systemd result. Cleanup must preserve the game forfeit.
            with self.assertRaises(WorkspaceResourceExceeded) as raised:
                client.create(input="position")
            self.assertEqual(raised.exception.arena_usage, {"input_tokens": 123})
            self.assertFalse(json.loads((self.root / "clock.json").read_text())["active"])
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(scope.failure_reason(), "oom-kill")
        finally:
            scope.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()

    def test_real_preparation_checkpoints_are_private_and_resume_without_retraining(self):
        settings = WorkspaceSettings(training_seconds=0.15, evaluation_seconds=5,
                                     storage_mib=64, memory_mib=256)
        work = self.root / "untracked_log" / "run" / "batch-001"
        work.mkdir(parents=True)
        name = "gpt5.6-sol-low-codex-1h"
        trained = []

        def start(client):
            client._scope = NS(thaw=lambda: None, kill=lambda: None, close=lambda: None)
            client._proxy = NS(set_enabled=lambda _: None, close=lambda: None)

        def train(client, *_args, **_kwargs):
            trained.append(True)
            (client.cwd / "learned.cpp").write_text("int learned = 1;\n")
            (client.home / "memory.txt").write_text("training memory")
            atomic_json(client.state_path, {"thread_id": "training-thread"})
            time.sleep(0.3)
            return NS(usage=None, final_response="saved"), []

        with (mock.patch.dict(arena._CODEX_TRAINING_SECONDS, {"codex-1h": settings.training_seconds}),
              mock.patch.object(arena._Arena, "ROOT", self.root),
              mock.patch.object(arena._Arena, "UNTRACKED_LOG_ROOT", self.root / "untracked_log"),
              mock.patch.object(arena._State, "config", replace(arena.CONFIG, workspace=settings)),
              mock.patch.object(arena._CodexGameClient, "_start_runtime", start),
              mock.patch.object(arena._CodexGameClient, "_persistent_thread", lambda _: None),
              mock.patch.object(arena._CodexGameClient, "_turn_options", lambda _: {}),
              mock.patch.object(arena._CodexGameClient, "_run_turn", train)):
            checkpoint_id = None
            for number in (1, 2):
                client = arena._CodexGameClient(name, arena._llm_player_config(name)[1], work, number,
                                               proxy_credential=NS(auth_mode="fake"))
                try:
                    self.assertEqual((client.cwd / "learned.cpp").read_text(), "int learned = 1;\n")
                    self.assertEqual((client.home / "memory.txt").read_text(), "training memory")
                    self.assertEqual(json.loads(client.state_path.read_text())["thread_id"], "training-thread")
                    if checkpoint_id is not None:
                        self.assertEqual(client.checkpoint["checkpoint_id"], checkpoint_id)
                    checkpoint_id = client.checkpoint["checkpoint_id"]
                    (client.cwd / "learned.cpp").write_text("evaluation modification")
                    (client.home / "memory.txt").write_text("evaluation memory")
                    atomic_json(client.state_path, {"thread_id": "evaluation-thread"})
                finally:
                    client.close()
            self.assertEqual(len(trained), 1)

    def test_real_codex_can_resume_a_thread_in_an_independent_volume(self):
        settings = WorkspaceSettings(training_seconds=0, evaluation_seconds=5, storage_mib=128)
        work = self.root / "untracked_log" / "run" / "batch-001"
        work.mkdir(parents=True)
        name = "gpt5.6-sol-low-codex-0h"
        with (mock.patch.object(arena._Arena, "ROOT", self.root),
              mock.patch.object(arena._Arena, "UNTRACKED_LOG_ROOT", self.root / "untracked_log"),
              mock.patch.object(arena._State, "config", replace(arena.CONFIG, workspace=settings)),
              fake_openai_server() as calls):
            client = arena._CodexGameClient(name, arena._llm_player_config(name)[1], work, 1,
                                           proxy_credential=arena._OpenAIProxyCredential("dummy", "unused.invalid"))
            try:
                client.begin_turn(1, 1, 1, 1, "Legal moves: pass", self.root / "calls.jsonl")
                response = client.create(model=client.player.model, reasoning={"effort": "low"},
                                         input="Legal moves: pass")
                self.assertEqual(response.output_text, "pass")
                thread_id = client._thread.id
                self.assertTrue(calls)
            finally:
                client.close()
            resumed = arena._CodexGameClient(name, arena._llm_player_config(name)[1], work, 1,
                                            proxy_credential=arena._OpenAIProxyCredential("dummy", "unused.invalid"))
            try:
                resumed._start_runtime()
                resumed._scope.thaw()
                self.assertEqual(resumed._persistent_thread().id, thread_id)
                resumed._scope.freeze()
            finally:
                resumed.close()

    def test_real_sdk_evaluation_conversations_do_not_flow_into_later_games(self):
        settings = WorkspaceSettings(training_seconds=3, evaluation_seconds=15, storage_mib=128)
        work = self.root / "untracked_log" / "run" / "batch-001"
        work.mkdir(parents=True)
        name = "gpt5.6-sol-low-codex-1h"
        credential = arena._OpenAIProxyCredential("dummy", "unused.invalid")
        with (mock.patch.dict(arena._CODEX_TRAINING_SECONDS, {"codex-1h": settings.training_seconds}),
              mock.patch.object(arena._Arena, "ROOT", self.root),
              mock.patch.object(arena._Arena, "UNTRACKED_LOG_ROOT", self.root / "untracked_log"),
              mock.patch.object(arena._State, "config", replace(arena.CONFIG, workspace=settings)),
              fake_openai_server() as calls):
            first = arena._CodexGameClient(name, arena._llm_player_config(name)[1], work, 1,
                                          proxy_credential=credential)
            try:
                self.assertGreater(first.checkpoint["training_model_requests"], 0)
                preparation_requests = len(calls)
                prompt = "evaluation-sentinel-one\nLegal moves: pass"
                first.begin_turn(1, 1, 1, 1, prompt, self.root / "calls.jsonl")
                first.create(model=first.player.model, reasoning={"effort": "low"}, input=prompt)
                (first.cwd / "evaluation-only.txt").write_text("must not transfer")
                checkpoint_id = first.checkpoint["checkpoint_id"]
            finally:
                first.close()
            second = arena._CodexGameClient(name, arena._llm_player_config(name)[1], work, 2,
                                           proxy_credential=credential)
            try:
                self.assertEqual(second.checkpoint["checkpoint_id"], checkpoint_id)
                self.assertFalse((second.cwd / "evaluation-only.txt").exists())
                second._start_runtime()
                second._scope.thaw()
                history = second._persistent_thread().read(include_turns=True).model_dump_json()
                second._scope.freeze()
                self.assertNotIn("evaluation-sentinel-one", history)
                self.assertGreater(len(calls), preparation_requests)
                self.assertEqual(second._clock.remaining, settings.evaluation_seconds)
            finally:
                second.close()


if __name__ == "__main__":
    unittest.main()
