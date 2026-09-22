"""Run naming, extension, isolation, and collision tests without paid games."""

import contextlib
import concurrent.futures
import fcntl
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest import mock

import arena


class RunDirectoryTests(unittest.TestCase):
    name = "gpt5.6-sol-high-api-multi"

    def setUp(self):
        self.resources = contextlib.ExitStack()
        self.addCleanup(self.resources.close)
        self.root = Path(self.resources.enter_context(TemporaryDirectory()))
        for key, value in [("ROOT", self.root), ("LOG_ROOT", self.root / "log"),
                           ("UNTRACKED_LOG_ROOT", self.root / "untracked_log")]:
            self.resources.enter_context(mock.patch.object(arena._Arena, key, value))

    def config(self, **changes):
        value = dict(
            arena_log_schema_version=4, legality_enforcement_version=1,
            active_players=[self.name], independent_player_batches=True,
            total_games=2, games_per_active_player=2, board_size=9,
            past_run_dirs=[], bots=[arena._llm_player_manifest(self.name)],
        )
        return value | changes

    def open(self, config=None):
        return arena._open_run(None, config or self.config(), [], lambda size: size == 2,
                               {"completed_batch_ids": []})

    def test_named_llm_and_timestamped_katago_directories(self):
        run, work, meta, *_ = self.open()
        self.assertEqual(run.name, self.name)
        self.assertEqual(work.name, self.name)
        self.assertEqual(meta["run_directory_scheme"], "llm_name")
        kata, *_ = self.open(self.config(active_players=[arena._CURRENT_PLAYER_POOL[1]]))
        self.assertRegex(kata.name, r"^arena_katago_\d{8}_\d{6}_\d{6}_[0-9a-f]{8}$")

    def test_existing_directory_requires_final_runs_even_if_empty(self):
        run = self.root / "log" / self.name
        run.mkdir(parents=True)
        marker = run / "keep.txt"
        marker.write_text("keep these results")
        with self.assertRaisesRegex(arena.ArenaError, "_FINAL_RUNS"):
            self.open()
        self.assertEqual(marker.read_text(), "keep these results")
        self.assertEqual(list(run.iterdir()), [marker])

    def record(self, number):
        return arena.GameRecord(number, 1, self.name, arena._Arena.ANCHOR,
                                "B+R", "B", self.name, 1.0, "resignation", (), "test", "")

    def finish(self, run, work, metadata):
        arena._write_game_records(work / "games.jsonl", [self.record(1), self.record(2)])
        metadata.update(completed_games=2, batch_sizes=[2], completed_batch_ids=[1],
                        finished_at="2026-09-04T00:00:00+00:00")
        arena._write_json(run / "run.json", metadata)

    def test_finished_run_extends_without_losing_or_duplicating_records(self):
        run, work, meta, *_ = self.open()
        self.finish(run, work, meta)
        with mock.patch.object(arena, "_FINAL_RUNS", (self.name,)):
            reopened, recovered_work, updated, done, batch, _log = self.open(
                self.config(total_games=4, games_per_active_player=4))
        self.assertEqual((reopened, recovered_work), (run, work))
        self.assertEqual([g.number for g in done], [1, 2])
        self.assertEqual(batch, 1)
        self.assertEqual(updated["total_games"], 4)
        self.assertNotIn("finished_at", updated)
        self.assertEqual(updated["extensions"][0]["completed_games"], 2)
        self.assertEqual(len(arena._read_games(work / "games.jsonl")), 2)

    def test_extension_rejects_protocol_change_without_modifying_metadata(self):
        run, work, meta, *_ = self.open()
        self.finish(run, work, meta)
        before = (run / "run.json").read_bytes()
        with mock.patch.object(arena, "_FINAL_RUNS", (self.name,)):
            with self.assertRaisesRegex(arena.ArenaError, "different game/player settings"):
                self.open(self.config(board_size=19))
        self.assertEqual((run / "run.json").read_bytes(), before)

    def test_finished_api_run_rebuilds_deleted_journal_before_extending(self):
        run, work, meta, *_ = self.open()
        self.finish(run, work, meta)
        records = [arena.replace(self.record(n), moves=(("B", "D4"), ("W", "resign")),
                                 llm_cost_usd=1.25, llm_api_seconds=3.5) for n in (1, 2)]
        arena._write_game_records(run / "llm_games.jsonl", records)
        arena._write_results(run / "results.csv", records)
        before = {p.name: p.read_bytes() for p in run.iterdir() if p.name != "run.json"}
        shutil.rmtree(work)
        with mock.patch.object(arena, "_FINAL_RUNS", (self.name,)):
            _, _, updated, done, batch, _ = self.open(self.config(total_games=4, games_per_active_player=4))
        self.assertEqual(done, records)
        self.assertEqual(arena._read_games(work / "games.jsonl"), records)
        self.assertEqual(batch, 1)
        self.assertEqual(updated["total_games"], 4)
        self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir() if p.name != "run.json"})

    def test_missing_interrupted_journal_requires_original_conversation(self):
        run, work, meta, *_ = self.open()
        self.finish(run, work, meta)
        meta.pop("finished_at")
        arena._write_json(run / "run.json", meta)
        shutil.rmtree(work)
        before = (run / "run.json").read_bytes()
        with mock.patch.object(arena, "_FINAL_RUNS", (self.name,)):
            with self.assertRaisesRegex(arena.ArenaError, "unfinished games and conversations"):
                self.open()
        self.assertEqual((run / "run.json").read_bytes(), before)
        self.assertFalse(work.exists())

    def test_invalid_archived_results_do_not_create_a_journal(self):
        run, work, meta, *_ = self.open()
        self.finish(run, work, meta)
        records = [self.record(1), self.record(2)]
        arena._write_game_records(run / "llm_games.jsonl", records)
        arena._write_results(run / "results.csv", [arena.replace(r, result="W+R") for r in records])
        shutil.rmtree(work)
        before = (run / "run.json").read_bytes()
        with mock.patch.object(arena, "_FINAL_RUNS", (self.name,)):
            with self.assertRaisesRegex(arena.ArenaError, "disagrees with its committed result"):
                self.open()
        self.assertFalse(work.exists())
        self.assertEqual((run / "run.json").read_bytes(), before)

    def test_archived_workspace_requires_its_checkpoint(self):
        run, work, meta, *_ = self.open()
        self.finish(run, work, meta)
        meta["active_players"] = ["gpt6-astra-high-codex-1h"]
        shutil.rmtree(work)
        with self.assertRaisesRegex(arena.ArenaError, "workspace checkpoint"):
            arena._restore_archived_api_games(run, meta, work, lambda size: size == 2)
        self.assertFalse(work.exists())

    def test_orphaned_untracked_directory_is_not_overwritten(self):
        work = self.root / "untracked_log" / self.name
        work.mkdir(parents=True)
        with self.assertRaisesRegex(arena.ArenaError, "untracked run directory already exists"):
            self.open()
        self.assertFalse((self.root / "log" / self.name).exists())

    def test_own_run_is_excluded_from_historical_inputs(self):
        (self.root / "log" / "baseline").mkdir(parents=True)
        config = arena.replace(arena.CONFIG, active_players=(self.name,),
                               past_run_names=(self.name, "baseline"))
        state = SimpleNamespace()
        with (mock.patch.object(arena, "_State", state),
              mock.patch.object(arena, "_historical_katago_player_names", return_value=(arena._Arena.ANCHOR,)),
              mock.patch.object(arena, "_historical_player_priors", return_value={})):
            arena._configure(config)
        self.assertEqual(state.config.past_run_names, ("baseline",))
        self.assertEqual([p.name for p in state.past_run_dirs], ["baseline"])

    def test_many_players_get_independent_process_configs(self):
        names = (self.name, "grok-4.5-high-api-multi")
        config = arena.replace(arena.CONFIG, active_players=names, past_run_names=())
        captured = []
        def dispatch(fn, config):
            self.assertIs(fn, arena._run_player_arena)
            captured.append(config)
            future = concurrent.futures.Future()
            future.set_result(arena._Arena.LOG_ROOT / config.active_players[0])
            return future
        with (mock.patch.object(arena._State, "config", config),
              mock.patch.object(arena._State, "katago_mode", False),
              mock.patch.object(arena.concurrent.futures, "ProcessPoolExecutor") as pool):
            pool.return_value.__enter__.return_value.submit.side_effect = dispatch
            result = arena.run_arena()
        self.assertEqual([c.active_players for c in captured], [(names[0],), (names[1],)])
        self.assertEqual([p.name for p in result], list(names))

    def test_later_player_failure_is_reported_before_first_player_finishes(self):
        names = (self.name, "grok-4.5-high-api-multi")
        config = arena.replace(arena.CONFIG, active_players=names, past_run_names=())
        pending, failed = concurrent.futures.Future(), concurrent.futures.Future()
        failed.set_exception(FileNotFoundError("network download failed"))

        def report(message, **kwargs):
            if message == f"error: {names[1]}: network download failed":
                self.assertFalse(pending.done())
                self.assertTrue(kwargs.get("flush"))
                self.assertIs(kwargs.get("file"), arena.sys.stderr)
                pending.set_result(arena._Arena.LOG_ROOT / names[0])

        # A timeout turns delayed reporting into a bounded test failure.
        as_completed = concurrent.futures.as_completed
        with (mock.patch.object(arena._State, "config", config),
              mock.patch.object(arena._State, "katago_mode", False),
              mock.patch.object(arena.concurrent.futures, "ProcessPoolExecutor") as pool,
              mock.patch.object(arena.concurrent.futures, "as_completed",
                                side_effect=lambda fs: as_completed(fs, timeout=2)),
              mock.patch("builtins.print", side_effect=report) as output):
            pool.return_value.__enter__.return_value.submit.side_effect = [pending, failed]
            with self.assertRaisesRegex(arena.ArenaError, names[1]):
                arena.run_arena()
        self.assertTrue(pending.done())
        self.assertFalse(pending.cancelled())
        self.assertIn(f"error: {names[1]}: network download failed",
                      [call.args[0] for call in output.call_args_list])

    def test_multi_run_preflight_blocks_collisions_before_starting_jobs(self):
        names = (self.name, "grok-4.5-high-api-multi")
        (self.root / "log" / names[1]).mkdir(parents=True)
        config = arena.replace(arena.CONFIG, active_players=names)
        with (mock.patch.object(arena._State, "config", config),
              mock.patch.object(arena._State, "katago_mode", False),
              mock.patch.object(arena.concurrent.futures, "ProcessPoolExecutor") as pool):
            with self.assertRaisesRegex(arena.ArenaError, "_FINAL_RUNS"):
                arena.run_arena()
            pool.assert_not_called()

    def test_second_writer_is_rejected(self):
        config = arena.replace(arena.CONFIG, active_players=(self.name,))
        arena._ensure_untracked_log_root()
        with (arena._Arena.UNTRACKED_LOG_ROOT / f".{self.name}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with (mock.patch.object(arena._State, "config", config),
                  mock.patch.object(arena._State, "katago_mode", False),
                  mock.patch.object(arena, "_run_arena") as execute):
                with self.assertRaisesRegex(arena.ArenaError, "another process"):
                    arena.run_arena()
                execute.assert_not_called()

        # Explicit resume permits directory reuse but still enforces the lock.
        run = arena._Arena.LOG_ROOT / self.name
        run.mkdir(parents=True)
        with (arena._Arena.UNTRACKED_LOG_ROOT / f".{self.name}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with (mock.patch.object(arena._State, "config", config),
                  mock.patch.object(arena, "_run_arena") as execute):
                with self.assertRaisesRegex(arena.ArenaError, "another process"):
                    arena.run_arena(run)
                execute.assert_not_called()

    def test_resume_cli_accepts_name_and_directory_without_changing_final_runs(self):
        run = arena._Arena.LOG_ROOT / self.name
        config = arena.replace(arena.CONFIG, active_players=(self.name,))
        original = arena._FINAL_RUNS
        for selection in (self.name, str(run)):
            with (self.subTest(selection=selection),
                  mock.patch.object(arena, "_read_run_config", return_value=({}, config)) as read,
                  mock.patch.object(arena, "_configure") as configure,
                  mock.patch.object(arena, "run_arena", return_value=run) as execute,
                  mock.patch("builtins.print")):
                self.assertEqual(arena.main(["--resume", selection]), 0)
                read.assert_called_once_with(run)
                configure.assert_called_once_with(config)
                execute.assert_called_once_with(run)
                self.assertEqual(arena._FINAL_RUNS, original)

    def test_resume_cli_dispatches_independent_saved_configs_and_reports_failures(self):
        names = (self.name, "gpt5.6-luna-max-api-multi")
        runs = [arena._Arena.LOG_ROOT / name for name in names]
        configs = [arena.replace(arena.CONFIG, active_players=(name,), total_games=target)
                   for name, target in zip(names, (14, 28))]
        failed, completed = concurrent.futures.Future(), concurrent.futures.Future()
        failed.set_exception(arena.ArenaError("connection failed"))
        completed.set_result(runs[1])
        with (mock.patch.object(arena, "_read_run_config",
                                side_effect=[({}, config) for config in configs]),
              mock.patch.object(arena.concurrent.futures, "ProcessPoolExecutor") as pool,
              mock.patch("builtins.print") as output):
            executor = pool.return_value.__enter__.return_value
            executor.submit.side_effect = [failed, completed]
            self.assertEqual(arena.main(["--resume", ", ".join(names)]), 1)
        self.assertEqual(pool.call_args.kwargs["max_workers"], 2)
        self.assertEqual(pool.call_args.kwargs["mp_context"].get_start_method(), "spawn")
        self.assertEqual(executor.submit.call_args_list, [
            mock.call(arena._resume_player_arena, config, run)
            for config, run in zip(configs, runs)
        ])
        messages = [call.args[0] for call in output.call_args_list]
        self.assertIn(f"error: {self.name}: connection failed", messages)
        self.assertIn(f"Arena complete: {runs[1]}", messages)

    def test_resume_cli_rejects_empty_duplicate_and_missing_entries_before_launch(self):
        run = arena._Arena.LOG_ROOT / self.name
        config = arena.replace(arena.CONFIG, active_players=(self.name,))
        def read(path):
            if path != run:
                raise arena.ArenaError("missing run metadata")
            return {}, config
        for selection in ("", self.name + ",", self.name + ",," + self.name,
                          self.name + "," + str(run), self.name + ",missing-run"):
            with (self.subTest(selection=selection),
                  mock.patch.object(arena, "_read_run_config", side_effect=read),
                  mock.patch.object(arena, "_resume_player_arena") as resume,
                  mock.patch.object(arena.concurrent.futures, "ProcessPoolExecutor") as pool,
                  mock.patch("builtins.print")):
                self.assertEqual(arena.main(["--resume", selection]), 1)
                resume.assert_not_called()
                pool.assert_not_called()

    def test_resume_cli_overrides_target_for_each_saved_config(self):
        names = (self.name, "gpt5.6-luna-max-api-multi")
        configs = [arena.replace(arena.CONFIG, active_players=(name,), total_games=target)
                   for name, target in zip(names, (14, 28))]
        with (mock.patch.object(arena, "_read_run_config",
                                side_effect=[({}, config) for config in configs]),
              mock.patch.object(arena.concurrent.futures, "ProcessPoolExecutor") as pool,
              mock.patch("builtins.print")):
            executor = pool.return_value.__enter__.return_value
            futures = []
            for name in names:
                future = concurrent.futures.Future()
                future.set_result(arena._Arena.LOG_ROOT / name)
                futures.append(future)
            executor.submit.side_effect = futures
            self.assertEqual(arena.main(["--resume", ",".join(names), "-n", "30"]), 0)
        self.assertEqual(executor.submit.call_args_list, [
            mock.call(arena._resume_player_arena, arena.replace(config, total_games=30),
                      arena._Arena.LOG_ROOT / name)
            for config, name in zip(configs, names)
        ])

    def test_full_run_extends_to_cumulative_target_then_noops(self):
        config = arena.replace(arena.CONFIG, active_players=(self.name,),
                               opponent_players=(arena._Arena.ANCHOR,),
                               total_games=2, batch_games=2, past_run_names=(),
                               ignore_players=())
        state = SimpleNamespace(**{key: value for key, value in vars(arena._State).items()
                                   if not key.startswith("__")})
        played = []
        def play(slate, _bots, _work, _progress, **kwargs):
            played.extend(g.number for g in slate)
            return [arena.GameRecord(g.number, g.batch, g.black, g.white,
                                     "B+R", "B", g.black, 1.0, "resignation", (), "test", "")
                    for g in slate]
        with (mock.patch.object(arena, "_State", state),
              mock.patch.object(arena, "play_batch", side_effect=play),
              mock.patch.object(arena, "_progress_logger", return_value=lambda *_: None)):
            arena._configure(config)
            run = arena.run_arena()
            self.assertEqual(played, [1, 2])
            with mock.patch.object(arena, "_FINAL_RUNS", (self.name,)):
                # Completed API runs can be extended even after cleanup removed
                # all raw conversations and the local recovery journal.
                shutil.rmtree(arena._Arena.UNTRACKED_LOG_ROOT / self.name)
                extended = arena.replace(config, total_games=4, past_run_names=(self.name,))
                arena._configure(extended)
                self.assertEqual(arena.run_arena(), run)
                self.assertEqual(played, [1, 2, 3, 4])
                arena._configure(extended)
                arena.run_arena()
                self.assertEqual(played, [1, 2, 3, 4])
            with mock.patch("builtins.print"):
                self.assertEqual(arena.main(["--resume", self.name]), 0)
            self.assertEqual(played, [1, 2, 3, 4])
            meta = json.loads((run / "run.json").read_text())
            self.assertEqual(meta["completed_games"], 4)
            self.assertEqual(meta["rating_games"], 4)
            self.assertEqual(meta["past_games"], 0)
            self.assertEqual(meta["completed_batch_ids"], [1, 2])
            with mock.patch("builtins.print"):
                self.assertEqual(arena.main(["--resume", self.name, "-n", "6"]), 0)
                self.assertEqual(arena.main(["--resume", self.name]), 0)
            self.assertEqual(played, [1, 2, 3, 4, 5, 6])
            meta = json.loads((run / "run.json").read_text())
            self.assertEqual(meta["total_games"], 6)
            self.assertEqual(meta["completed_games"], 6)
            self.assertEqual(meta["extensions"][-2]["previous_total_games"], 4)


if __name__ == "__main__":
    unittest.main()
