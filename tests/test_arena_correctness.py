"""Regressions for capped games, empty replies, and historical call accounting."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import arena


class ArenaCorrectnessTests(unittest.TestCase):
    def test_native_retry_preserves_finished_games_and_replays_only_capped_slots(self):
        slots = [
            arena.ScheduledGame(1, 1, "black", "white"),
            arena.ScheduledGame(2, 1, "white", "black"),
        ]
        players = [
            arena.Player(name, Path(f"/{name}.bin.gz"))
            for name in ("black", "white")
        ]

        def finish_attempt(slate, _players, work, *, attempt, max_moves, progress):
            self.assertEqual(slate, slots if attempt == 1 else slots[1:])
            self.assertEqual(max_moves, 2)
            path = arena._native_attempt_paths(work, attempt)[2]
            path.mkdir()
            sgfs = (
                "(;PB[black]PW[white]RE[B+R])\n"
                "(;PB[white]PW[black];B[aa];W[bb])"
                if attempt == 1
                else "(;PB[white]PW[black]RE[W+R])"
            )
            (path / "games.sgfs").write_text(sgfs, encoding="utf-8")
            return path

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(arena._Arena, "MAX_MOVES", 2),
            mock.patch.object(arena, "_ensure_game_dependencies"),
            mock.patch.object(
                arena, "_run_native_attempt", side_effect=finish_attempt
            ) as run_attempt,
        ):
            records = arena._run_or_recover_native_chunk(
                slots, players, Path(tmp), progress=None, recovering=False
            )

        self.assertEqual(run_attempt.call_count, 2)
        self.assertEqual([record.number for record in records], [1, 2])
        self.assertEqual([record.result for record in records], ["B+R", "W+R"])

    def test_native_invalid_sgfs_are_not_treated_as_capped_games(self):
        slot = arena.ScheduledGame(1, 1, "black", "white")
        cases = (
            ("(;PB[black]PW[white];B[aa])", "missing RE after only 1/2 moves"),
            ("(;PW[white];B[aa];W[bb])", "SGF is missing PB"),
            (
                "(;PB[black]PW[white]RE[invalid];B[aa];W[bb])",
                "unsupported game result",
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for sgf, error in cases:
                with self.subTest(sgf=sgf):
                    (path / "game.sgf").write_text(sgf, encoding="utf-8")
                    with self.assertRaisesRegex(arena.ArenaError, error):
                        arena._collect_native_games([slot], path, max_moves=2)

    def test_null_chat_reply_is_logged_counted_and_retried(self):
        responses = [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                usage={"prompt_tokens": 100, "completion_tokens": 10},
            )
            for content in (None, "pass")
        ]
        create = mock.Mock(
            side_effect=[SimpleNamespace(parse=lambda r=r: r) for r in responses]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    with_raw_response=SimpleNamespace(create=create)
                )
            )
        )
        state = SimpleNamespace(size=9, rows=["." * 9] * 9, to_move="B")
        game = SimpleNamespace(
            get_possible_moves=lambda: (["pass"], []),
            get_board_state=lambda: state,
            get_move_history=lambda: [],
        )
        stats = arena.LLMGameStats()
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "calls.jsonl"
            move = arena._choose_llm_move(
                game,
                client,
                stats,
                player_name="qwen3.8-max-high-api",
                log_path=log,
                game_number=1,
                move_number=1,
            )
            entries = [json.loads(line) for line in log.read_text().splitlines()]
            recovered = arena._recovered_llm_stats(
                arena.ScheduledGame(1, 1, "qwen3.8-max-high-api", arena._Arena.ANCHOR),
                (),
                entries,
            )

        self.assertEqual(move, "pass")
        self.assertEqual(create.call_count, 2)
        self.assertEqual([entry["output"] for entry in entries], ["", "pass"])
        self.assertEqual(stats.api_problems, 1)
        self.assertEqual(stats.illegal_moves, 0)
        self.assertEqual(recovered.api_problems, 1)
        self.assertAlmostEqual(stats.cost_usd, recovered.cost_usd)

    def write_past_game(self, run, successful_calls):
        player = "DeepSeek-V4-Flash-0731-high-api"
        slot = arena.ScheduledGame(1, 1, player, arena._Arena.ANCHOR)
        record = arena._finished_record(
            slot,
            SimpleNamespace(ended=True, score="W+R", reason="resignation"),
            (("B", "resign"),),
            "deepseek_responses_api",
            arena.LLMGameStats(illegal_moves=1),
        )
        (run / "run.json").write_text(
            json.dumps({
                "arena_log_schema_version": 4,
                "completed_games": 1,
                "games_scope": "current_run",
                "board_size": arena._Arena.BOARD_SIZE,
                "komi": arena._Arena.KOMI,
                "rules": arena._Arena.RULES,
            }),
            encoding="utf-8",
        )
        arena._write_results(run / "results.csv", [record])
        call = {
            "game": 1,
            "provider": "deepseek_responses",
            "model": "deepseek-v4-flash",
            "ok": True,
            "input_tokens": 100,
            "output_tokens": 10,
            "started_at": "2026-08-18T05:00:00+00:00",
        }
        calls = [call] * successful_calls + [call | {"ok": False}]
        (run / "llm_calls.jsonl").write_text(
            "".join(json.dumps(entry) + "\n" for entry in calls), encoding="utf-8"
        )
        return (player, arena._Arena.ANCHOR)

    def test_historical_repricing_includes_discarded_attempt_calls(self):
        # A legal move in a discarded attempt, an invalid reply, then resignation.
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            players = self.write_past_game(run, successful_calls=3)
            games = arena._load_past_games([run], players)
        self.assertEqual(len(games), 1)
        self.assertAlmostEqual(games[0].llm_cost_usd, 3 * (100 * 0.22 + 10 * 0.66) / 1e6)
        self.assertEqual(games[0].llm_illegal_moves, 1)

    def test_historical_repricing_still_rejects_missing_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            players = self.write_past_game(run, successful_calls=1)
            with self.assertRaises(arena.ArenaError):
                arena._load_past_games([run], players)


if __name__ == "__main__":
    unittest.main()
