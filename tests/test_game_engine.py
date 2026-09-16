"""Referee regressions; set RUN_KATAGO_TESTS=1 for native differential tests."""

import json
import math
import os
import random
import tempfile
import unittest
from pathlib import Path

from types import SimpleNamespace

from analysis.audit_superko import ReplayBoard
from gobench.game_engine import GTPError, GoEngineError, KataGoGameEngine
from gobench.go_rules import COLS, LEGALITY_ENFORCEMENT_VERSION, TrompTaylorRules

KO_MOVES = "B3 C3 D3 B2 C4 D2 A5 C1 C2".split()


class TolerantGTP:
    """Independent audit board, deliberately accepting repetitions like GTP."""

    def __init__(self):
        self.board = ReplayBoard(5)
        self.commands = []
        self.closed = False
        self.corrupt = False
        self.reject_play = False
        self.wrong_rules = False

    def command(self, command):
        self.commands.append(command)
        parts = command.split()
        if parts[0] == "boardsize":
            self.board = ReplayBoard(int(parts[1]))
        elif command == "clear_board":
            self.board = ReplayBoard(self.board.size)
        elif command == "kata-get-rules":
            return json.dumps({
                "ko": "SIMPLE" if self.wrong_rules else "POSITIONAL",
                "suicide": True,
            })
        elif parts[0] == "play":
            if self.reject_play:
                raise GTPError(command, "illegal move")
            self.board.play(parts[1], parts[2])
        elif command == "showboard":
            size = self.board.size
            cells = self.board.board if not self.corrupt else (".",) * (size * size)
            return "\n".join(
                f"{y + 1} " + " ".join(
                    {".": ".", "B": "X", "W": "O"}[c]
                    for c in cells[y * size:(y + 1) * size]
                ) for y in range(size - 1, -1, -1)
            )
        elif command == "final_score":
            return "B+1.0"
        return ""

    def close(self):
        self.closed = True


class RefereeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.transport = TolerantGTP()
        self.engine = KataGoGameEngine(
            board_size=5, log_dir=self.directory.name, _gtp=self.transport,
        )
        self.addCleanup(self.engine.close)

    def play_ko(self):
        for move in KO_MOVES:
            self.assertTrue(self.engine.do_action(move))

    def snapshot(self):
        game = self.engine
        return (
            game._rules.position, frozenset(game._rules.seen_positions),
            game.get_move_history(), game.to_move, game._consecutive_passes,
            game.get_game_result(),
        )

    def test_ko_list_and_rejection_are_pure_and_never_send_gtp(self):
        self.play_ko()
        before, commands = self.snapshot(), list(self.transport.commands)
        for _ in range(2):
            legal, forbidden = self.engine.get_possible_moves()
            self.assertNotIn("C3", legal)
            self.assertIn("C3", forbidden)
            result = self.engine.do_action("C3")
            self.assertFalse(result)
            self.assertIn("superko", result.reason)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.transport.commands, commands)

    def test_ko_threat_and_answer_allow_recapture(self):
        self.play_ko()
        for move in ("E5", "E4", "C3"):
            self.assertTrue(self.engine.do_action(move))

    def test_bad_moves_leave_pass_count_and_turn_unchanged(self):
        self.engine.do_action("A1")
        self.engine.do_action("pass")
        before = self.snapshot()
        for move, color in (("A1", "B"), ("I2", "B"), ("B2", "W")):
            self.assertFalse(self.engine.do_action(move, color))
            self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.engine.do_action("pass"))
        self.assertEqual(self.engine.get_game_result().reason, "two_passes")
        self.assertEqual(self.engine.get_possible_moves(), ([], []))

    def test_resignation_and_move_cap(self):
        before = self.engine._rules.position
        self.assertTrue(self.engine.do_action("resign"))
        self.assertEqual(self.engine._rules.position, before)
        self.assertEqual(self.engine.get_game_result().winner, "W")
        self.assertFalse(self.engine.do_action("A1"))
        self.engine.reset_for_game(game_id="capped", log_dir=self.directory.name)
        self.engine.max_moves = 1
        self.assertTrue(self.engine.do_action("A1"))
        self.assertEqual(self.engine.get_game_result().reason, "max_moves")

    def test_reset_clears_history_and_logs_version(self):
        self.play_ko()
        self.engine.reset_for_game(game_id="reset", log_dir=self.directory.name)
        self.assertEqual(self.engine.get_move_history(), ())
        self.assertEqual(self.engine._rules.seen_positions, {bytes(25)})
        self.assertEqual(len(self.engine.get_possible_moves()[0]), 26)
        self.assertTrue(self.engine.do_action("C3"))
        entry = json.loads(self.engine.action_log_path.read_text().splitlines()[0])
        self.assertEqual(entry["legality_enforcement_version"],
                         LEGALITY_ENFORCEMENT_VERSION)

    def test_board_disagreement_closes_engine_without_committing_move(self):
        before = self.snapshot()
        self.transport.corrupt = True
        with self.assertRaisesRegex(GoEngineError, "board disagrees"):
            self.engine.do_action("A1")
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.transport.closed)
        for operation in (lambda: self.engine.do_action("A2"),
                          self.engine.get_possible_moves):
            with self.assertRaisesRegex(GoEngineError, "closed"):
                operation()

    def test_gtp_rejecting_a_legal_move_is_an_engine_error(self):
        before = self.snapshot()
        self.transport.reject_play = True
        with self.assertRaisesRegex(GoEngineError, "referee-legal"):
            self.engine.do_action("A1")
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.transport.closed)

    def test_prompt_contains_the_referees_ko_list(self):
        import arena

        self.play_ko()
        legal, forbidden = self.engine.get_possible_moves()
        prompt = arena._llm_move_prompt(
            self.engine.get_board_state(), legal + ["resign"], forbidden,
            self.engine.get_move_history()[-5:],
        )
        lines = prompt.splitlines()
        illegal_line = next(v for v in lines if v.startswith("Currently illegal"))
        legal_line = next(v for v in lines if v.startswith("Legal moves:"))
        self.assertIn("C3", illegal_line)
        self.assertNotIn("C3", legal_line)

    def test_unsupported_or_mismatched_rules_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "only tromp-taylor"):
            KataGoGameEngine(rules="japanese", _gtp=self.transport)
        self.transport.wrong_rules = True
        with self.assertRaisesRegex(GoEngineError, "rules disagree"):
            KataGoGameEngine(log_dir=self.directory.name, _gtp=self.transport)

    def test_recovery_rebuilds_history_and_rejects_legacy_illegal_action(self):
        import arena

        moves = [("B" if n % 2 == 0 else "W", move)
                 for n, move in enumerate(KO_MOVES)]
        actions = tuple(arena.LLMGameAction(c, m, True) for c, m in moves)
        recovery = SimpleNamespace(
            actions=actions, moves=tuple(moves), source_path=Path("old.actions.jsonl")
        )
        slot = SimpleNamespace(number=1, black="llm", white="kata")
        self.assertEqual(arena._replay_llm_game(self.engine, slot, None, recovery),
                         tuple(moves))
        self.assertIn("C3", self.engine.get_possible_moves()[1])
        self.engine.reset_for_game(game_id="legacy", log_dir=self.directory.name)
        recovery.actions += (arena.LLMGameAction("W", "C3", True),)
        with self.assertRaisesRegex(arena.ArenaError, "incompatible.*superko"):
            arena._replay_llm_game(self.engine, slot, None, recovery)


class SuicideTests(unittest.TestCase):
    def position(self, rows):
        rules = TrompTaylorRules(len(rows))
        rules.position = bytes(".BW".index(c) for row in rows for c in row)
        rules.seen_positions = {rules.position}
        return rules

    def test_single_stone_suicide_repeats_position(self):
        rules = self.position(["...", "W..", ".W."])
        result = rules.evaluate("B", "A1")
        self.assertFalse(result.legal)
        self.assertIn("superko", result.reason)
        with self.assertRaises(ValueError):
            rules.commit(result)

    def test_multi_stone_suicide_legal_but_recreation_after_pass_illegal(self):
        rules = self.position(["WW..", "WBW.", "W.W.", ".W.."])
        suicide = rules.evaluate("B", "B2")
        self.assertTrue(suicide.legal)
        self.assertEqual(suicide.position.count(1), 0)
        rules.commit(suicide)
        rules.commit(rules.evaluate("W", "pass"))
        self.assertFalse(rules.evaluate("B", "B3").legal)

    def test_capture_is_resolved_before_suicide(self):
        rules = self.position(["WWB", "W.B", "BBB"])
        move = rules.evaluate("B", "B2")
        self.assertTrue(move.legal)
        self.assertEqual(move.position.count(2), 0)
        self.assertEqual(move.position.count(1), 6)


def historical_games():
    path = Path(__file__).parent / "fixtures/historical_games.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    for game in fixture["games"]:
        yield game["run"], game


class HistoricalTests(unittest.TestCase):
    def test_all_historical_games_reject_exactly_the_audited_first_violations(self):
        clean = rejected = 0
        with tempfile.TemporaryDirectory() as directory:
            with KataGoGameEngine(board_size=9, log_dir=directory,
                                  _gtp=TolerantGTP()) as engine:
                for index, (run, game) in enumerate(historical_games()):
                    engine.reset_for_game(game_id=str(index), log_dir=directory)
                    expected = game["first_violation_move"]
                    for number, action in enumerate(game["moves"], 1):
                        color, move = action["color"], action["move"]
                        if number == expected:
                            before = (engine.get_move_history(), engine.to_move,
                                      engine._rules.position,
                                      set(engine._rules.seen_positions))
                            legal, forbidden = engine.get_possible_moves()
                            self.assertNotIn(move, legal)
                            self.assertIn(move, forbidden)
                            self.assertFalse(engine.do_action(move, color))
                            self.assertEqual(before, (
                                engine.get_move_history(), engine.to_move,
                                engine._rules.position, engine._rules.seen_positions,
                            ))
                            rejected += 1
                            break
                        self.assertTrue(engine.do_action(move, color),
                                        (run, game["game"], number))
                    else:
                        self.assertIsNone(expected)
                        clean += 1
        self.assertEqual(rejected, 95)
        self.assertEqual(clean, 343)


@unittest.skipUnless(os.environ.get("RUN_KATAGO_TESTS") == "1", "native opt-in")
class NativeKataGoTests(unittest.TestCase):
    def test_historical_and_generated_positions_against_native_katago(self):
        from gobench.strategies import KATAGO_BINARY, KATAGO_CONFIG, KATAGO_NETWORKS_DIR

        counts = {"clean_games": 0, "rejected_games": 0, "legal_masks": 0,
                  "accepted_moves": 0}

        def check_mask(engine):
            tokens = engine._command("kata-raw-nn 0").split()
            start = tokens.index("policy") + 1
            policy = [float(v) for v in tokens[start:start + 81]]
            expected = {
                f"{COLS[i % 9]}{9 - i // 9}" for i, value in enumerate(policy)
                if math.isfinite(value) and value >= 0
            } | {"pass"}
            legal, forbidden = engine.get_possible_moves()
            self.assertEqual(set(legal), expected)
            empty = {f"{COLS[i % 9]}{9 - i // 9}"
                     for i, cell in enumerate(engine._rules.position) if cell == 0}
            self.assertEqual(set(forbidden), empty - expected)
            counts["legal_masks"] += 1

        with tempfile.TemporaryDirectory() as directory:
            with KataGoGameEngine(
                komi=7.0, log_dir=directory, katago_binary=KATAGO_BINARY,
                config_path=KATAGO_CONFIG,
                model_path=KATAGO_NETWORKS_DIR / "kata1-b6c96-s8080640-d1961030.txt.gz",
            ) as engine:
                for index, (_run, game) in enumerate(historical_games()):
                    engine.reset_for_game(game_id=str(index), log_dir=directory)
                    for number, action in enumerate(game["moves"], 1):
                        move, color = action["move"], action["color"]
                        invalid = move != "resign" and not engine._rules.evaluate(
                            color, move).legal
                        if invalid or number % 31 == 0:
                            check_mask(engine)
                        if invalid:
                            self.assertFalse(engine.do_action(move, color))
                            counts["rejected_games"] += 1
                            break
                        self.assertTrue(engine.do_action(move, color))
                        counts["accepted_moves"] += 1
                    else:
                        counts["clean_games"] += 1
                    if (index + 1) % 100 == 0:
                        print(f"Native historical games checked: {index + 1}",
                              flush=True)
                rng = random.Random(20260904)
                for index in range(10):
                    engine.reset_for_game(game_id=f"random-{index}", log_dir=directory)
                    for _ in range(120):
                        if engine.get_game_result().ended:
                            break
                        check_mask(engine)
                        moves, _ = engine.get_possible_moves()
                        self.assertTrue(engine.do_action(rng.choice(moves)))
                self.assertEqual(counts["clean_games"], 343)
                self.assertEqual(counts["rejected_games"], 95)
        print(f"Native strict-legality validation: {counts}", flush=True)


if __name__ == "__main__":
    unittest.main()
