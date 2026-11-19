"""Track 3.5 opening books without sandboxes, KataGo, or provider calls."""

import contextlib
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest import mock

import arena
from gobench import opening_book, tutorial
from gobench.game_engine import GameResult
from gobench.go_rules import TrompTaylorRules

LEARNER = "claude-opus-5-5-high-claude-code"
PLAYER = f"{tutorial.BOOK_STUDENT}-book3.5-{LEARNER}-4h"


class BookTests(unittest.TestCase):
    def test_size_counts_shared_prefixes_and_mirror_images_once(self):
        book = opening_book.parse(
            "B E5 C4 D4 C3\n"
            "B E5 C4 D4 D3 E3   # shares three moves with the line above\n"
            "B E5 G6 F6         # the first line's start, mirrored: nothing new\n"
            "W E5 C5\n",
            100,
        )
        self.assertEqual(book.size, 4 + 2 + 0 + 2)
        self.assertEqual((book.lines, book.problems, book.dropped_moves), (4, [], 0))
        # The student's moves only: Black's on B lines, White's on W lines.
        self.assertEqual(book.summary()["book_moves"], 3 + 1)

    def test_a_game_matches_up_to_symmetry_and_the_move_is_mapped_back(self):
        book = opening_book.parse("B E5 C4 D4\nW E5 C5 E3 E7\n", 100)
        self.assertEqual(book.move("B", []), "E5")
        self.assertEqual(book.move("B", ["E5", "C4"]), "D4")
        self.assertEqual(book.move("B", ["E5", "G6"]), "F6")
        self.assertEqual(book.move("B", ["E5", "F3"]), "F4")
        self.assertIsNone(book.move("B", ["E5", "C5"]))
        self.assertEqual(book.move("W", ["E5"]), "C5")
        self.assertEqual(book.move("W", ["E5", "G5", "E7"]), "E3")
        # A Black line says nothing about what White should play, and the reverse.
        self.assertIsNone(book.move("W", ["E5", "C4", "D4"]))
        self.assertIsNone(book.move("B", ["E5", "C5", "E3"]))

    def test_the_limit_keeps_the_moves_that_come_first(self):
        book = opening_book.parse("B E5 C4 D4 C3 C5\nB E5 C5 D5\nW E5 C5\n", 6)
        self.assertEqual((book.size, book.dropped_moves), (6, 3))
        self.assertEqual(book.move("B", ["E5", "C4", "D4", "C3"]), "C5")
        self.assertIsNone(book.move("B", ["E5", "C5"]))
        self.assertIsNone(book.move("W", ["E5"]))

    def test_a_line_is_kept_up_to_its_first_problem(self):
        book = opening_book.parse(
            "B E5 C4 E5 C3\n"      # E5 is occupied
            "B E5 C4 Z9\n"
            "X E5\n"
            "B E5 C4 D4\n"
            "B E5 C4 C5 D5\n"      # the book already answers C4 with D4
            "B D5\n",              # and already opens E5
            100,
        )
        self.assertEqual([number for number, _ in book.problems], [1, 2, 3, 5, 6])
        self.assertIn("illegal", book.problems[0][1])
        self.assertEqual(book.size, 3)
        self.assertEqual(book.move("B", ["E5", "C4"]), "D4")

    def test_superko_is_illegal_in_a_line(self):
        ko = "C4 F4 D5 E5 D3 E3 A1 D4 E4"
        book = opening_book.parse(f"W {ko} D4\nW {ko} A9\n", 100)
        self.assertEqual([number for number, _ in book.problems], [1])
        self.assertIn("superko", book.problems[0][1])
        self.assertEqual(book.move("W", ko.split()), "A9")

    def test_the_kept_book_reads_back_as_itself(self):
        source = "B G5 E3 F4 pass\nB G5 C5 D5\nW D4 F6\nW C3 G7 pass\n"
        book = opening_book.parse(source, 8)
        again = opening_book.parse(book.text(), 8)
        self.assertEqual((again.replies, set(again.nodes)), (book.replies, set(book.nodes)))
        self.assertEqual((again.problems, again.dropped_moves), ([], 0))
        for color, moves in book.nodes:
            rules = TrompTaylorRules(9)
            for index, move in enumerate(moves):
                evaluation = rules.evaluate("BW"[index % 2], move)
                self.assertTrue(evaluation.legal)
                rules.commit(evaluation)


class NameTests(unittest.TestCase):
    def test_book_player_is_a_track_3_checkpoint_player_without_an_api(self):
        spec = arena._book_player(PLAYER + "2")
        self.assertEqual((spec.network, spec.opponent, spec.hours, spec.replica),
                         (tutorial.BOOK_STUDENT, tutorial.BOOK_OPPONENT, 4, "2"))
        self.assertEqual(spec.learner_player, f"{LEARNER}-4h")
        self.assertEqual(arena._canonical_active_llm_player_name(PLAYER + "2"), PLAYER)
        self.assertIsNone(arena._tutorial_player(PLAYER))
        self.assertEqual(arena._result_llm_track(PLAYER), 3)
        self.assertTrue(arena._is_checkpoint_player(PLAYER))
        self.assertFalse(arena._is_result_api_llm_player(PLAYER))
        # The name starts like a network's, but it is not a ladder bot.
        self.assertIsNone(arena._network_name_for_player(PLAYER))
        self.assertIsNone(arena._workspace_client_class_for_player(PLAYER))
        api, player = arena._llm_player_config(PLAYER)
        self.assertEqual((api.manifest_kind, player.model, player.prices),
                         ("katago_book", tutorial.BOOK_STUDENT, (0.0, 0.0, 0.0)))

    def test_invalid_names_are_not_players(self):
        for name in (
            PLAYER.replace("-4h", "-3h"),
            PLAYER.replace("book3.5", "book3.4"),
            PLAYER.replace(tutorial.BOOK_STUDENT, tutorial.BOOK_OPPONENT),
            PLAYER.replace("claude-opus-5-5", "claude-unknown"),
            PLAYER.replace("-claude-code-", "-api-"),
            PLAYER + "0",
        ):
            with self.subTest(name=name):
                self.assertFalse(arena._is_active_llm_player(name))

    def test_manifest_describes_the_bot_and_its_learner(self):
        manifest = arena._llm_player_manifest(PLAYER)
        self.assertEqual((manifest["kind"], manifest["track"], manifest["subtrack"]),
                         ("katago_book", 3, "3.5"))
        self.assertEqual((manifest["network"], manifest["opponent"]),
                         (tutorial.BOOK_STUDENT, tutorial.BOOK_OPPONENT))
        self.assertEqual(manifest["book_move_limit"], tutorial.BOOK_MOVE_LIMIT)
        self.assertEqual(manifest["learner_model"], "claude-opus-5-5")
        self.assertEqual(manifest["learning_seconds"], 4 * 3600)
        self.assertEqual(manifest["max_visits"], 1)


class ConfiguredTests(unittest.TestCase):
    """Tests that need the Track 3.5 run profile configured."""

    def setUp(self):
        state = {name: value for name, value in vars(arena._State).items()
                 if not name.startswith("__")}
        self.enterContext(mock.patch.multiple(arena._State, **state))
        self.config = arena.RUN_TYPES["book3.5-claude-opus-5-5-4h"]
        arena._configure(replace(self.config, past_run_names=()))

    def learner(self, cls=arena._ClaudeCodeBookLearner):
        learner = object.__new__(cls)
        learner.tutorial_player = arena._book_player(PLAYER)
        learner.target_api = learner.target = None
        learner.player = arena._registered_llm_player(f"{LEARNER}-4h")[1]
        learner.settings = arena._codex_workspace_settings(learner.player.agentic_harness)
        learner._resource_lock = None
        return learner

    def test_profile_plays_many_games_against_the_one_opponent(self):
        self.assertEqual(self.config.active_players, (PLAYER,))
        self.assertEqual(self.config.total_games, 1000)
        # The whole ladder is configured, so the learner's sandbox has every network...
        ladder = {network.name for network in arena._tutorial_ladder_networks()}
        self.assertLessEqual({tutorial.BOOK_STUDENT, tutorial.BOOK_OPPONENT}, ladder)
        self.assertIn("kata1-b18c384nbt-s9761732864-d4253420187", ladder)
        # ...but evaluation games are only scheduled against the opponent.
        self.assertEqual(arena._llm_matchmaking_opponents(arena._State.arena_player_names),
                         [tutorial.BOOK_OPPONENT])

    def test_other_runs_keep_the_whole_ladder_as_opponents(self):
        arena._configure(replace(self.config, past_run_names=(),
                                 active_players=("claude-opus-5-5-high-api-multi",)))
        self.assertGreater(
            len(arena._llm_matchmaking_opponents(arena._State.arena_player_names)), 50)

    def test_instructions_describe_the_task_the_bots_and_the_book(self):
        text = self.learner()._instructions(3600)
        self.assertIn("# Track 3.5: opening book", text)
        self.assertIn(f"{tutorial.BOOK_STUDENT} (2241 Elo)", text)
        self.assertIn(f"{tutorial.BOOK_OPPONENT} (2603 Elo)", text)
        self.assertIn("play 1000 complete 9x9 games", text)
        self.assertIn("maxVisits=1,numSearchThreads=1,chosenMoveTemperatureEarly=0.5,"
                      "chosenMoveTemperature=0.1", text)
        self.assertIn(f"The limit is {tutorial.BOOK_MOVE_LIMIT}.", text)
        self.assertIn("/arena/bin/book-check", text)
        self.assertIn("/workspace/book.txt", text)
        self.assertIn("Subagents are disabled.", text)
        self.assertNotIn("tutorial", text)
        codex = self.learner(arena._CodexBookLearner)
        self.assertIn("multi_agent = false\n", codex._codex_config_text())

    def test_sandbox_has_katago_the_ladder_and_the_book_tool_only(self):
        learner = self.learner()
        learner._tool_server = SimpleNamespace(socket_path=Path("/tmp/tools.sock"))
        mounts = dict((str(destination), source)
                      for source, destination in learner._extra_readonly_mounts())
        self.assertEqual(mounts[tutorial.SANDBOX_KATAGO_DIR], arena.KATAGO_HOME)
        for name in (tutorial.BOOK_STUDENT, tutorial.BOOK_OPPONENT):
            self.assertIn(f"{tutorial.SANDBOX_NETWORK_DIR}/{name}.txt.gz", mounts)
        with TemporaryDirectory() as directory:
            learner._phase_dir = Path(directory)
            learner._write_public_files()
            public = Path(directory) / "public"
            self.assertEqual(sorted(path.name for path in (public / "bin").iterdir()),
                             ["book-check", "katago"])
            self.assertTrue(os.access(public / "bin" / "book-check", os.X_OK))
            self.assertIn("2603", (public / "ladder.tsv").read_text())
            self.assertEqual((public / "instructions.md").read_text(),
                             learner._instructions(learner.settings.training_seconds))
        specification = learner._tutorial_specification()
        self.assertEqual((specification["protocol"], specification["book_move_limit"]),
                         (tutorial.BOOK_PROTOCOL_VERSION, tutorial.BOOK_MOVE_LIMIT))

    def test_the_book_is_cut_to_the_limit_and_frozen(self):
        learner = self.learner()
        with TemporaryDirectory() as directory, \
                mock.patch.object(tutorial, "BOOK_MOVE_LIMIT", 4):
            preparation, staging = Path(directory) / "preparation", Path(directory) / "staging"
            learner.cwd = Path(directory) / "workspace"
            for path in (preparation, staging, learner.cwd):
                path.mkdir(parents=True)
            (learner.cwd / "book.txt").write_text("B E5 C4 D4 C3 C5\nB E5 C4 Q1\nW E5 C5\n")
            learner._capture_preparation_outputs(preparation)
            (preparation / "anthropic-proxy.usage.jsonl").write_text("")
            fields = learner._checkpoint_fields(preparation, staging)
            self.assertEqual((fields["book_size"], fields["book_move_limit"]), (4, 4))
            self.assertEqual((fields["book_dropped_moves"], fields["book_problem_lines"]), (3, 1))
            self.assertEqual(fields["book_student_moves"], 2)
            self.assertEqual(fields["learning_cost_usd"], 0)
            self.assertEqual((staging / "book.txt").read_text(), "B E5 C4 D4 C3\n")
            self.assertEqual(os.stat(staging / "book.txt").st_mode & 0o777, 0o400)
            self.assertIn("Q1", (preparation / "book-source.txt").read_text())

    def test_a_missing_book_is_an_empty_book(self):
        learner = self.learner()
        with TemporaryDirectory() as directory:
            learner.cwd = Path(directory) / "workspace"
            learner.cwd.mkdir()
            learner._capture_preparation_outputs(Path(directory))
            self.assertEqual((Path(directory) / "book.txt").read_text(), "")
            capture = json.loads((Path(directory) / "book-capture.json").read_text())
            self.assertEqual((capture["source_present"], capture["size"]), (False, 0))

    def test_the_tool_socket_checks_a_book(self):
        with TemporaryDirectory() as directory:
            server = arena._TutorialToolServer(Path(directory), arena._book_player(PLAYER))
            try:
                result = server.dispatch({"op": "book", "text": "B E5 C4 D4\nB E5 C4 D4 Q1\n"})
                self.assertEqual((result["size"], result["limit"], result["lines"]),
                                 (3, tutorial.BOOK_MOVE_LIMIT, 2))
                self.assertEqual(result["problems"][0][0], 2)
                with self.assertRaisesRegex(ValueError, "not available in Track 3.5"):
                    server.dispatch({"op": "student_open"})
            finally:
                server.close()

    def test_a_learner_needs_both_bots_in_the_sandbox(self):
        arena._configure(replace(self.config, past_run_names=(), opponent_players=(
            arena._Arena.ANCHOR, tutorial.BOOK_OPPONENT)))
        with self.assertRaisesRegex(arena.ArenaError, "among opponent_players"):
            arena._ClaudeCodeBookLearner(arena._book_player(PLAYER), Path("/nonexistent"))


class FakeGame:
    """A referee in which a pass by each side ends the game; stones decide it."""

    def __init__(self):
        self.reset_for_game(game_id="", log_dir=None)

    def reset_for_game(self, *, game_id, log_dir):
        self.rules, self.moves, self.to_move = TrompTaylorRules(9), [], "B"
        self.result = GameResult(False)

    def get_game_result(self):
        return self.result

    def get_move_history(self):
        return tuple(self.moves)

    def get_possible_moves(self):
        return self.rules.possible_moves(self.to_move)

    def do_action(self, move, color):
        evaluation = self.rules.evaluate(color, move)
        if not evaluation.legal:
            return SimpleNamespace(success=False, reason=evaluation.reason)
        self.rules.commit(evaluation)
        self.moves.append((color, move))
        self.to_move = "W" if color == "B" else "B"
        if [m for _, m in self.moves[-2:]] == ["pass", "pass"]:
            black, white = (self.rules.position.count(value) for value in (1, 2))
            winner = "B" if black > white else "W"
            self.result = GameResult(True, winner, f"{winner}+1.0", "two_passes")
        return SimpleNamespace(success=True, reason=None)


class Passer:
    """A network bot that always passes, and records being reset."""

    def __init__(self, name):
        self.name, self.resets, self.closed = name, 0, False

    def choose_move(self, game):
        return "pass"

    def reset_for_game(self, game):
        self.resets += 1

    def close(self):
        self.closed = True


class GameTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        state = {name: value for name, value in vars(arena._State).items()
                 if not name.startswith("__")}
        self.enterContext(mock.patch.multiple(arena._State, **state))
        arena._configure(replace(arena.RUN_TYPES["book3.5-claude-opus-5-5-4h"],
                                 past_run_names=()))
        self.bots = []

        def strategy(player, _config, _work):
            self.bots.append(Passer(player.name))
            return self.bots[-1]

        for name, value in (
            ("_ensure_game_dependencies", mock.Mock()),
            ("ensure_arena_networks", mock.Mock()),
            ("_write_random_bot_configs",
             lambda players, _work: {bot.name: None for bot in players}),
            ("_game_engine", lambda *_: contextlib.nullcontext(FakeGame())),
            ("_network_strategy", strategy),
            ("_book_game_worker_count", lambda _count: 1),
        ):
            self.enterContext(mock.patch.object(arena, name, value))

    def play(self, book_text, games=2):
        opponent = tutorial.BOOK_OPPONENT
        slots = [arena.ScheduledGame(number, 1, *((PLAYER, opponent) if number % 2
                                                  else (opponent, PLAYER)))
                 for number in range(1, games + 1)]
        book = opening_book.parse(book_text, tutorial.BOOK_MOVE_LIMIT)
        log = []
        with mock.patch.object(arena, "_ensure_book", return_value=book) as ensure:
            records = arena.run_llm_games(slots, arena.players(), self.root,
                                          progress=log.append)
            again = arena.run_llm_games(slots, arena.players(), self.root, progress=None)
        self.assertEqual(again, records)
        self.assertEqual(ensure.call_count, 1)
        return records, log

    def test_the_student_plays_the_book_and_then_its_own_moves(self):
        records, log = self.play("B E5\nW pass E5\n")
        first, second = records
        self.assertEqual(first.moves, (("B", "E5"), ("W", "pass"), ("B", "pass")))
        self.assertEqual(second.moves,
                         (("B", "pass"), ("W", "E5"), ("B", "pass"), ("W", "pass")))
        self.assertEqual([record.winner for record in records], [PLAYER, PLAYER])
        self.assertEqual([record.llm_cost_usd for record in records], [0, 0])
        self.assertIn("1 from the book", log[0])
        # One worker keeps its referee and bots for both games.
        self.assertEqual(sorted(bot.name for bot in self.bots),
                         sorted([tutorial.BOOK_STUDENT, tutorial.BOOK_OPPONENT]))
        self.assertTrue(all(bot.closed for bot in self.bots))

    def test_without_a_book_the_student_is_the_plain_network(self):
        records, log = self.play("")
        self.assertEqual([record.moves for record in records],
                         [(("B", "pass"), ("W", "pass"))] * 2)
        self.assertIn("0 from the book", log[0])

    def test_a_book_move_the_referee_would_refuse_is_not_played(self):
        book = opening_book.parse("B E5\n", 10)
        strategy = arena._BookStrategy(PLAYER, book, Passer("own"))
        game = FakeGame()
        game.do_action("E5", "B")
        game.do_action("pass", "W")
        # Pretend the book still said E5 here: the point is taken.
        book.replies["B", opening_book.canonical(("E5", "pass"))[0]] = "E5"
        self.assertEqual(strategy.choose_move(game), "pass")
        self.assertEqual(strategy.book_moves, 0)


if __name__ == "__main__":
    unittest.main()
