"""Historical summaries must never launch games or modify their source runs."""

import contextlib
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import arena
from gobench import arena_summary


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for key, value in (
            ("ROOT", self.root),
            ("LOG_ROOT", self.root / "log"),
            ("UNTRACKED_LOG_ROOT", self.root / "untracked_log"),
        ):
            self.stack.enter_context(mock.patch.object(arena._Arena, key, value))
        state = SimpleNamespace(**{
            key: value for key, value in vars(arena._State).items()
            if not key.startswith("__")
        })
        self.stack.enter_context(mock.patch.object(arena, "_State", state))
        for name in ("run_arena", "play_batch", "recover_batch", "_llm_client",
                     "_ensure_game_dependencies", "_create_run"):
            self.stack.enter_context(mock.patch.object(
                arena, name, side_effect=AssertionError(f"summary called {name}"),
            ))

    def make_history(self):
        name = "gpt5.6-sol-high-api-multi"
        source = arena._Arena.LOG_ROOT / name
        source.mkdir(parents=True)
        metadata = {
            "arena_log_schema_version": 4,
            "run_directory_scheme": "llm_name",
            "active_players": [name],
            "active_player_prior_elo_mean": 1000.0,
            "active_player_prior_elo_sd": 2000.0,
            "past_run_dirs": [],
            "completed_games": 2,
            "games_scope": "current_run",
            "board_size": 9,
            "komi": 7.0,
            "rules": "tromp-taylor",
        }
        (source / "run.json").write_text(json.dumps(metadata))
        games = [arena.GameRecord(
            number, 1, name, arena._Arena.ANCHOR, "B+R", "B", name, 1.0,
            "resignation", (("B", "D4"), ("W", "resign")), "test", "",
            llm_cost_usd=1.0,
        ) for number in (1, 2)]
        arena._write_results(source / "results.csv", games)
        arena._write_game_records(source / "llm_games.jsonl", [
            *games, arena.replace(games[0], number=3),  # Not yet committed.
        ])
        (arena._Arena.LOG_ROOT / "katago_selfplay_benchmark.json").write_text(
            json.dumps({"results": []})
        )
        return name, source, games

    def test_summary_includes_active_players_history_and_refreshes_without_new_games(self):
        name, source, games = self.make_history()
        before = {p.name: p.read_bytes() for p in source.iterdir()}
        run = arena._Arena.LOG_ROOT / "summary"
        run.mkdir()
        for obsolete in ("report.md", "results.csv", "ratings.txt",
                         "api_llm_comparisons.txt", "all_llm_comparisons.txt",
                         "all_llm_matchup_results.txt"):
            (run / obsolete).write_text("obsolete")
        config = arena.replace(arena.CONFIG, active_players=(name,),
                               past_run_names=(name,), total_games=100)
        for past_names in ((name,), (name, "summary")):
            with mock.patch.object(arena, "CONFIG", arena.replace(
                config, past_run_names=past_names,
            )), mock.patch("builtins.print"):
                self.assertEqual(arena.main(["--summary"]), 0)
            run = arena._Arena.LOG_ROOT / "summary"
            result = json.loads((run / "run.json").read_text())
            self.assertEqual(result["completed_games"], 0)
            self.assertEqual(result["active_players"], [])
            self.assertEqual(result["rating_games"], 2)
            self.assertEqual(result["llm_comparisons"][0]["games"], 2)
            self.assertEqual(result["llm_comparisons"][0]["cost_usd_per_move"], 1.0)
            self.assertEqual({r["player"] for r in result["ratings"]},
                             {name, arena._Arena.ANCHOR})
            report = (run / "report.txt").read_text()
            self.assertIn(name, report)
            self.assertNotIn("```", report)
            self.assertEqual({p.name for p in run.iterdir()},
                             {"run.json", "report.txt", "results.json"})
            snapshot = json.loads((run / "results.json").read_text())
            self.assertEqual(snapshot["games"]["count"], 2)
            self.assertEqual(snapshot["games"]["move_count"], 4)
            rows = snapshot["datasets"]["llm_vs_katago_games"]
            self.assertEqual([r["source_game"] for r in rows], [1, 2])
            self.assertEqual(rows[0]["moves"], [
                {"number": 1, "color": "B", "move": "D4"},
                {"number": 2, "color": "W", "move": "resign"},
            ])
            self.assertEqual(snapshot["datasets"]["llm_players"][0]["cost_usd_per_move"], 1.0)
            self.assertIsNone(snapshot["datasets"]["katago_players"][0]["seconds_per_move"])
            self.assertEqual({p.name for p in arena._Arena.LOG_ROOT.iterdir()
                              if p.is_dir()}, {name, "summary"})
            self.assertFalse(arena._Arena.UNTRACKED_LOG_ROOT.exists())
            self.assertEqual(before, {p.name: p.read_bytes() for p in source.iterdir()})
        with self.assertRaisesRegex(arena.ArenaError, "cannot be resumed"):
            arena._read_run_config(run)

    def test_missing_or_incomplete_moves_fail_instead_of_exporting_partial_games(self):
        name, source, games = self.make_history()
        comparisons = [{"player": name, "games": 2, "moves": 2}]
        for records, message in ((games[:1], "Missing complete games"),
                                 ([arena.replace(g, moves=()) for g in games],
                                  "Incomplete move sequence")):
            with self.subTest(message=message):
                arena._write_game_records(source / "llm_games.jsonl", records)
                with self.assertRaisesRegex(ValueError, message):
                    arena_summary.llm_games([source], comparisons, self.root)

    def test_batch_committing_during_fit_is_included_only_in_next_summary(self):
        name, source, games = self.make_history()
        config = arena.replace(arena.CONFIG, past_run_names=(name,))
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in source.iterdir()}
        fit = arena._rating_snapshot

        def commit_during_fit(*args, **kwargs):
            updated = [*games, arena.replace(games[0], number=3, batch=2)]
            arena._write_results(source / "results.csv", updated)
            arena._write_game_records(source / "llm_games.jsonl", updated)
            metadata = json.loads((source / "run.json").read_text())
            metadata["completed_games"] = 3
            arena._write_json(source / "run.json", metadata)
            return fit(*args, **kwargs)

        with mock.patch.object(arena, "_rating_snapshot", side_effect=commit_during_fit):
            run = arena.run_summary(config)
        result = json.loads((run / "results.json").read_text())
        self.assertEqual(result["rating_games"], 2)
        self.assertEqual(result["games"]["count"], 2)
        self.assertEqual(result["datasets"]["llm_players"][0]["games"], 2)
        for provenance in result["sources"]:
            path = Path(provenance["path"])
            if path.parent.name == name:
                self.assertEqual(provenance["sha256"], before[path.name])
        # A fresh command sees the newly committed game without touching the run.
        arena.run_summary(config)
        result = json.loads((run / "results.json").read_text())
        self.assertEqual(result["rating_games"], 3)
        self.assertEqual(result["games"]["count"], 3)

    def test_snapshot_freezes_boundary_before_copying_new_results(self):
        name, source, games = self.make_history()
        ledger = source / "llm_calls.jsonl"
        ledger.write_bytes(b'{"game":1}\n{"game":')
        copy = arena_summary.shutil.copyfile

        def commit_after_metadata(src, dst):
            result = copy(src, dst)
            if src == source / "run.json":
                updated = [*games, arena.replace(games[0], number=3, batch=2)]
                arena._write_results(source / "results.csv", updated)
                arena._write_game_records(source / "llm_games.jsonl", updated)
                metadata = json.loads(src.read_text())
                metadata["completed_games"] = 3
                arena._write_json(src, metadata)
            return result

        with (
            mock.patch.object(arena_summary.shutil, "copyfile", side_effect=commit_after_metadata),
            arena_summary.history_snapshot([source], self.root, arena._Arena.LOG_ROOT) as snapshot,
        ):
            root, _, dirs = snapshot
            full, _ = arena_summary.llm_games(
                dirs, [{"player": name, "games": 2, "moves": 2}], root,
            )
            self.assertEqual([game["source_game"] for game in full], [1, 2])
            self.assertEqual((dirs[0] / "llm_calls.jsonl").read_bytes(), b'{"game":1}\n')
        self.assertEqual(ledger.read_bytes(), b'{"game":1}\n{"game":')

    def test_timing_matches_paper_weighting_playout_scaling_and_temperature_inheritance(self):
        base = "kata1-example"
        playout = base + "-playouts60"
        temp = base + "-temp-0.5"
        ratings = [{"player": name, "elo": 1000, "ci_low": 800, "ci_high": 1200,
                    "games": 14} for name in (base, playout, temp)]
        benchmark = {"results": [
            {"player": base, "timing_estimated": False, "game_timings": [
                {"moves": 2, "total_genmove_seconds": 1},
                {"moves": 8, "total_genmove_seconds": 9},
            ]},
            {"player": playout, "timing_estimated": True,
             "cpu_estimate": {"base_player": base, "playout_multiplier": 60}},
        ]}
        rows = arena_summary.katago_players(ratings, benchmark)
        self.assertEqual([row["seconds_per_move"] for row in rows], [1, 60, 1])
        self.assertEqual([row["elo_ci_95"] for row in rows], [200] * 3)
        self.assertAlmostEqual(rows[1]["cost_usd_per_move"], 60 * .071 / 3600)
        self.assertTrue(rows[1]["timing_estimated"])
        self.assertEqual(rows[2]["timing_inherited_from"], base)
        with self.assertRaisesRegex(ValueError, "No KataGo timing"):
            arena_summary.katago_players(ratings, {"results": []})

    def test_empty_history_does_not_create_a_run(self):
        with self.assertRaisesRegex(arena.ArenaError, "no committed historical games"):
            arena.run_summary(arena.replace(arena.CONFIG, past_run_names=()))
        self.assertFalse(arena._Arena.LOG_ROOT.exists())

    def test_summary_is_exclusive_with_resume_and_run_type(self):
        for args in (["--summary", "--resume", "example"],
                     ["--summary", "--run-type", "many_llm"]):
            with self.subTest(args=args), mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                arena.main(args)


if __name__ == "__main__":
    unittest.main()
