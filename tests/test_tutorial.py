"""Track 3 tutorial distillation without sandboxes, KataGo, or provider calls."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import arena
from gobench import tutorial
from gobench.llm_conversation import APIConversation, ConversationClient

TARGET = "claude-sonnet-5-5-high-api-multi"


def anthropic_sdk():
    """Client construction without the SDK package or a Claude login."""
    return patch.dict(sys.modules, {"anthropic": SimpleNamespace(Anthropic=object)})
PLAYER = f"{TARGET}-tutorial3.3-claude-opus-5-5-high-claude-code-4h"


class NameTests(unittest.TestCase):
    def test_tutorial_player_plays_as_its_multi_turn_target(self):
        spec = arena._tutorial_player(PLAYER + "2")
        self.assertEqual((spec.target, spec.subtrack, spec.hours, spec.replica),
                         (TARGET, "3.3", 4, "2"))
        self.assertEqual(spec.learner_player, "claude-opus-5-5-high-claude-code-4h")
        self.assertEqual(arena._canonical_active_llm_player_name(PLAYER + "2"), PLAYER)
        self.assertEqual(arena._llm_player_config(PLAYER + "2"),
                         arena._llm_player_config(TARGET))
        self.assertTrue(arena._is_checkpoint_player(PLAYER))
        self.assertFalse(arena._is_result_api_llm_player(PLAYER))
        self.assertTrue(arena._is_active_llm_player(
            "gpt6-sol-high-api-multi-tutorial3.1-gpt6-astra-high-codex-8h"))

    def test_invalid_names_are_not_players(self):
        for name in (
            PLAYER.replace("-4h", "-0h"),
            PLAYER.replace("-4h", "-3h"),
            PLAYER.replace("tutorial3.3", "tutorial3.5"),
            PLAYER.replace("-api-multi-", "-api-"),
            PLAYER.replace("claude-opus-5-5", "claude-unknown"),
            PLAYER + "0",
            # Budget tags only apply to chat subtracks.
            PLAYER.replace("tutorial3.3", "tutorial3.3-200usd"),
            PLAYER.replace("tutorial3.3", "tutorial3.4-0usd"),
        ):
            with self.subTest(name=name):
                self.assertFalse(arena._is_active_llm_player(name))

    def test_budget_tag_sets_the_student_cost_limit(self):
        tagged = arena._tutorial_player(PLAYER.replace("tutorial3.3", "tutorial3.4-200usd"))
        self.assertEqual((tagged.subtrack, tagged.student_cost_limit_usd), ("3.4", 200.0))
        self.assertEqual(tagged.learner_player, "claude-opus-5-5-high-claude-code-4h")
        manifest = arena._llm_player_manifest(tagged.name)
        self.assertEqual(manifest["student_cost_limit_usd"], 200.0)
        default = arena._tutorial_player(PLAYER.replace("tutorial3.3", "tutorial3.4"))
        self.assertEqual(default.student_cost_limit_usd, 50.0)

    def test_manifest_records_learning_and_evaluation(self):
        manifest = arena._llm_player_manifest(PLAYER)
        self.assertEqual(manifest["agentic_harness"], "api-multi")
        self.assertEqual(manifest["target_player"], TARGET)
        self.assertEqual(manifest["learner_model"], "claude-opus-5-5")
        self.assertEqual(manifest["learning_seconds"], 4 * 3600)
        self.assertTrue(manifest["student_calls"])
        self.assertFalse(manifest["learning_subagents"])
        self.assertEqual(manifest["tutorial_token_limit"], 5000)


class TokenAndFileTests(unittest.TestCase):
    def test_hard_truncation_at_5000_tokens(self):
        text, source = tutorial.truncate("joseki " * 7000)
        self.assertEqual(source, tutorial.count_tokens("joseki " * 7000))
        self.assertEqual(tutorial.count_tokens(text), 5000)
        self.assertTrue(("joseki " * 7000).startswith(text))
        self.assertEqual(tutorial.truncate("short"), ("short", 1))

    def test_truncation_inside_a_multibyte_character_still_fits(self):
        text, _source = tutorial.truncate("碁" * 20000)
        self.assertLessEqual(tutorial.count_tokens(text), 5000)

    def test_source_is_a_regular_file_never_a_link(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(tutorial.read_source(root / "tutorial.md"))
            (root / "secret").write_text("host secret", encoding="utf-8")
            (root / "tutorial.md").symlink_to(root / "secret")
            self.assertIsNone(tutorial.read_source(root / "tutorial.md"))
            (root / "tutorial.md").unlink()
            (root / "tutorial.md").mkdir()
            self.assertIsNone(tutorial.read_source(root / "tutorial.md"))
            (root / "tutorial.md").rmdir()
            (root / "tutorial.md").write_bytes(b"ok \xff")
            self.assertEqual(tutorial.read_source(root / "tutorial.md"), "ok �")


class PositionTests(unittest.TestCase):
    def test_replay_matches_track1_prompt_inputs(self):
        position = tutorial.replay_position(["B E5", "C3", "pass"])
        self.assertEqual(position.to_move, "W")
        self.assertEqual(position.move_number, 3)
        self.assertEqual(position.rows[4][4], "B")
        self.assertEqual(position.rows[6][2], "W")
        self.assertEqual(position.legal_moves[-2:], ("pass", "resign"))
        self.assertEqual(position.recent_moves[-1], ("B", "pass"))
        prompt = arena._llm_move_prompt(position, list(position.legal_moves), [],
                                        position.recent_moves)
        self.assertIn("You are playing White", prompt)
        self.assertIn("5 ZZZZBZZZZ", prompt)

    def test_ko_is_reported_like_a_game(self):
        # Black captures at E5; White may not retake at D5 immediately.
        moves = ["D6", "E6", "C5", "F5", "D4", "E4", "J9", "D5", "E5"]
        position = tutorial.replay_position(moves)
        self.assertIn("D5", position.ko_illegal_moves)
        self.assertNotIn("D5", position.legal_moves)

    def test_invalid_positions(self):
        for moves, message in (
            ("E5", "list"),
            (["W E5"], "must be played by B"),
            (["E5", "E5"], "occupied"),
            (["pass", "pass"], "ended"),
            (["pass", "pass", "E5"], "two consecutive passes"),
            (["Z9"], "invalid"),
            (["B E5 now"], "COLOR MOVE"),
        ):
            with self.subTest(moves=moves), self.assertRaisesRegex(ValueError, message):
                tutorial.replay_position(moves)


def reply(text):
    return SimpleNamespace(
        output_text=text,
        output=[{"type": "message", "role": "assistant", "status": "completed",
                 "content": [{"type": "output_text", "text": text, "annotations": []}]}],
        usage={"input_tokens": 10, "output_tokens": 2},
    )


class ConversationTests(unittest.TestCase):
    def test_tutorial_opens_each_session_only(self):
        session = APIConversation("openai", "gpt-6-sol", PLAYER, 1, "responses",
                                  tutorial="Play the center.")
        request = {"input": "", "reasoning": {"effort": "high"}}
        first = session.prepare(request, "move one")
        self.assertEqual(first["input"][0]["content"],
                         tutorial.with_tutorial("Play the center.", "move one"))
        session.accept(session.completed_event(reply("E5"), 1000), "E5", 1, 1)
        second = session.prepare(request, "move two")
        self.assertEqual(second["input"][-1]["content"], "move two")
        self.assertIn("Play the center.", second["input"][0]["content"])
        session.observed_tokens = 250000
        third = session.prepare(request, "move three")
        self.assertEqual(third["input"], [{"role": "user", "content":
                         tutorial.with_tutorial("Play the center.", "move three")}])
        self.assertEqual(session.pending["reset_reason"], "context_limit")

    def test_identity_separates_tutorials_and_keeps_existing_ledgers(self):
        plain = APIConversation("openai", "m", "p", 1, "responses")
        self.assertNotIn("tutorial_sha256", plain.identity)
        one = APIConversation("openai", "m", "p", 1, "responses", tutorial="a")
        two = APIConversation("openai", "m", "p", 1, "responses", tutorial="b")
        self.assertNotEqual(one.identity, two.identity)

    def test_eval_client_reads_the_published_tutorial(self):
        with TemporaryDirectory() as directory, \
                patch.object(arena, "_ensure_tutorial", return_value="frozen") as ensure, \
                patch.object(arena, "AnthropicClient"), anthropic_sdk():
            client = arena._llm_client(PLAYER, work_dir=Path(directory), game_number=3)
        ensure.assert_called_once()
        self.assertIsInstance(client, ConversationClient)
        self.assertEqual(client.conversation.tutorial, "frozen")
        self.assertEqual(client.conversation.identity["player"], PLAYER)

    def test_single_turn_players_cannot_read_a_tutorial(self):
        with patch.object(arena, "AnthropicClient"), anthropic_sdk(), \
                self.assertRaisesRegex(arena.ArenaError, "multi-turn"):
            arena._llm_client("claude-sonnet-5-5-high-api", tutorial="x")


class StudentTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.spec = arena._tutorial_player(PLAYER)
        self.server = arena._TutorialToolServer(Path(self.directory.name), self.spec)
        self.addCleanup(self.server.close)

    def request(self, value):
        import socket

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(str(self.server.socket_path))
            stream = connection.makefile("rwb")
            stream.write(json.dumps(value).encode() + b"\n")
            stream.flush()
            return json.loads(stream.readline())

    def fake_call(self, outputs, calls):
        def call(client, prompt, **kwargs):
            calls.append((client.conversation.tutorial, kwargs["game_number"],
                          kwargs["move_number"], kwargs["attempt"], prompt))
            return outputs.pop(0), 0.5, 0.25
        return call

    def test_tokens_and_disabled_student(self):
        self.assertEqual(self.request({"op": "tokens", "text": "hello"}),
                         {"tokens": 1, "limit": 5000})
        response = self.request({"op": "student", "tutorial": "t", "positions": [[]]})
        self.assertEqual(response, {"error": "the learning clock is not running"})
        self.assertIn("error", self.request({"op": "nope"}))

    def test_one_conversation_answers_every_position(self):
        self.server.set_enabled(True)
        calls = []
        outputs = ["Z9", "E5", "C3"]
        with patch.object(arena, "_call_llm_move", self.fake_call(outputs, calls)), \
                patch.object(arena, "AnthropicClient"), anthropic_sdk():
            result = self.request({"op": "student", "tutorial": "Take the center.",
                                   "positions": [[], ["E5", "D4"]]})
        self.assertEqual([p["move"] for p in result["positions"]], ["E5", "C3"])
        self.assertEqual([len(p["attempts"]) for p in result["positions"]], [2, 1])
        self.assertFalse(result["positions"][0]["attempts"][0]["legal"])
        self.assertEqual(result["cost_usd"], 0.75)
        self.assertEqual({call[0] for call in calls}, {"Take the center."})
        self.assertEqual([call[1:4] for call in calls], [(1, 1, 1), (1, 1, 2), (1, 2, 1)])
        self.assertIn("You are playing Black", calls[2][4])
        self.assertIn("4 ZZZWZZZZZ", calls[2][4])
        summary = json.loads((Path(self.directory.name) / "calls.jsonl").read_text())
        self.assertEqual(summary["call"], 1)

    def test_invalid_positions_and_other_subtracks(self):
        self.server.set_enabled(True)
        response = self.request({"op": "student", "tutorial": "t",
                                 "positions": [["E5"], ["E5", "E5"]]})
        self.assertRegex(response["error"], "position 2: .*occupied")
        self.server.tutorial_player = arena._tutorial_player(
            PLAYER.replace("tutorial3.3", "tutorial3.2"))
        response = self.request({"op": "student", "tutorial": "t", "positions": [[]]})
        self.assertEqual(response["error"], "student calls are not available in Track 3.2")

    def test_at_most_four_calls_run_at_once(self):
        self.server.set_enabled(True)
        lock, release = threading.Lock(), threading.Event()
        state = {"running": 0, "peak": 0}

        def call(*_args, **_kwargs):
            with lock:
                state["running"] += 1
                state["peak"] = max(state["peak"], state["running"])
            release.wait(5)
            with lock:
                state["running"] -= 1
            return "pass", 0.0, 0.0

        with patch.object(arena, "_call_llm_move", call), \
                patch.object(arena, "AnthropicClient"), anthropic_sdk():
            threads = [threading.Thread(target=self.request, args=(
                {"op": "student", "tutorial": "t", "positions": [[]]},)) for _ in range(6)]
            for thread in threads:
                thread.start()
            for _ in range(100):
                if state["running"] == 4:
                    break
                threading.Event().wait(0.02)
            self.assertEqual(state["running"], 4)
            release.set()
            for thread in threads:
                thread.join(10)
        self.assertEqual(state["peak"], 4)

    def test_stopping_the_clock_ends_calls_and_records_the_cost(self):
        self.server.set_enabled(True)
        started = threading.Event()

        def call(*_args, retry=None, **_kwargs):
            started.set()
            threading.Event().wait(0.2)
            return "pass", 0.0, 0.1

        results = []
        with patch.object(arena, "_call_llm_move", call), \
                patch.object(arena, "AnthropicClient"), anthropic_sdk():
            thread = threading.Thread(target=lambda: results.append(self.request(
                {"op": "student", "tutorial": "t", "positions": [[], [], []]})))
            thread.start()
            started.wait(5)
            self.server.set_enabled(False)  # Waits for the running request.
            thread.join(5)
        positions = results[0]["positions"]
        self.assertEqual(positions[0]["move"], "pass")
        self.assertEqual(positions[-1]["error"], "the learning clock is not running")
        self.assertTrue(results[0]["stopped_early"])

    def test_sandbox_programs_use_the_tool_socket(self):
        root = Path(self.directory.name)
        (root / "tutorial.md").write_text("word " * 10, encoding="utf-8")
        script = root / "tutorial-tokens"
        script.write_text(tutorial.TOKENS_PROGRAM.replace(
            tutorial.SANDBOX_TOOL_SOCKET, str(self.server.socket_path)), encoding="utf-8")
        output = subprocess.run([sys.executable, str(script), str(root / "tutorial.md")],
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(output.strip(),
                         f"{tutorial.count_tokens('word ' * 10)} tokens (limit 5000)")
        student = root / "student"
        student.write_text(tutorial.STUDENT_PROGRAM.replace(
            tutorial.SANDBOX_TOOL_SOCKET, str(self.server.socket_path)), encoding="utf-8")
        (root / "positions.json").write_text("[[]]", encoding="utf-8")
        failed = subprocess.run(
            [sys.executable, str(student), str(root / "tutorial.md"), str(root / "positions.json")],
            capture_output=True, text=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("learning clock is not running", failed.stderr)


CHAT_PLAYER = PLAYER.replace("tutorial3.3", "tutorial3.4")


def wait_until(predicate, timeout=5):
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return True
        threading.Event().wait(0.01)
    return predicate()


class ChatTests(unittest.TestCase):
    """Track 3.4: named, persistent, non-blocking multi-turn students."""

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.transcripts = self.root / "public" / "students"
        self.server = self.make_server()
        for context in (patch.object(arena, "AnthropicClient"), anthropic_sdk()):
            context.start()
            self.addCleanup(context.stop)
        # Each fake request waits for its game's gate, then writes one ledger entry.
        self.gates, self.costs, self.calls = {}, {}, []
        self.outputs = {}
        call = patch.object(arena, "_call_llm_move", self.fake_call)
        call.start()
        self.addCleanup(call.stop)

    def make_server(self):
        server = arena._TutorialToolServer(self.root / "student", arena._tutorial_player(
            CHAT_PLAYER), transcripts=self.transcripts)
        self.addCleanup(server.close)
        server.set_enabled(True)
        return server

    def fake_call(self, client, prompt, *, log_path, game_number, move_number, retry, **_):
        self.calls.append((client, prompt, game_number, move_number))
        gate = self.gates.get(game_number)
        if gate is not None:
            gate.wait(5)
        cost = self.costs.get(game_number, 0.25)
        with log_path.open("a") as ledger:
            ledger.write(json.dumps({"game": game_number, "ok": True, "cost_usd": cost}) + "\n")
        output = self.outputs.get(game_number, f"reply to {prompt}")
        if isinstance(output, Exception):
            raise output
        return output, 0.1, cost

    def request(self, value, server=None):
        import socket

        server = server or self.server
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(str(server.socket_path))
            stream = connection.makefile("rwb")
            stream.write(json.dumps(value).encode() + b"\n")
            stream.flush()
            return json.loads(stream.readline())

    def open(self, name=None):
        return self.request({"op": "student_open", "name": name})["name"]

    def send(self, name, text):
        return self.request({"op": "student_send", "name": name, "text": text})

    def reply(self, name):
        return self.request({"op": "student_reply", "name": name})

    def finished(self, name):
        return wait_until(lambda: self.reply(name) != {"reply": None})

    def cost(self):
        return json.loads((self.transcripts / "cost.json").read_text())

    def test_chats_only_in_3_4_and_no_batch_tool(self):
        batch = arena._TutorialToolServer(self.root / "batch", arena._tutorial_player(PLAYER))
        self.addCleanup(batch.close)
        self.assertEqual(self.request({"op": "student_open"}, batch),
                         {"error": "student chats are not available in Track 3.3"})
        self.assertIn("use the student Python module", self.request(
            {"op": "student", "tutorial": "t", "positions": [[]]})["error"])

    def test_send_returns_at_once_and_reply_never_blocks(self):
        name = self.open("ladders")
        self.gates[1] = threading.Event()
        self.assertEqual(self.reply(name), {"reply": None})
        self.assertEqual(self.send(name, "What is a ladder?"), {"turn": 1})
        self.assertEqual(self.reply(name), {"reply": None})
        self.assertEqual(self.send(name, "again")["error"], "student ladders is still replying")
        transcript = (self.transcripts / "ladders.md").read_text()
        self.assertIn("What is a ladder?", transcript)
        self.assertIn("(waiting for the reply)", transcript)
        self.assertEqual(self.cost()["pending_replies"], 1)
        self.gates[1].set()
        self.assertTrue(self.finished(name))
        self.assertEqual(self.reply(name), {"reply": "reply to What is a ladder?"})
        self.assertEqual(self.send(name, "Why?"), {"turn": 2})
        self.assertTrue(self.finished(name))
        self.assertEqual(self.reply(name), {"reply": "reply to Why?"})
        # One multi-turn Track 1 conversation: same client, no tutorial, no reset.
        (first, _, game, turn), (second, prompt, _, next_turn) = self.calls
        self.assertIs(first, second)
        self.assertIsInstance(first.conversation, arena._StudentConversation)
        self.assertIsNone(first.conversation.tutorial)
        self.assertEqual((game, turn, next_turn, prompt), (1, 1, 2, "Why?"))
        transcript = (self.transcripts / "ladders.md").read_text()
        self.assertIn("## 2. Student ($0.2500)\n\nreply to Why?", transcript)
        self.assertEqual(self.cost()["spent_usd"], 0.5)
        self.assertEqual(self.server.students[name].log,
                         self.root / "student" / "chats" / "ladders.jsonl")

    def test_names_reattach_and_are_generated(self):
        self.assertEqual(self.open(), "student-1")
        self.assertEqual(self.open("student-1"), "student-1")
        self.assertEqual(self.open("student-3"), "student-3")
        self.assertEqual(self.open(), "student-4")
        self.assertIn("error", self.request({"op": "student_open", "name": "../x"}))
        self.assertIn("no student named", self.send("nobody", "hi")["error"])
        self.assertIn("nonempty", self.send("student-1", "")["error"])
        self.assertEqual(len({s.number for s in self.server.students.values()}), 3)

    def test_failed_send_raises_then_student_continues(self):
        name = self.open()
        self.outputs[1] = arena.ArenaError("anthropic API call failed: overloaded")
        self.send(name, "hi")
        self.assertTrue(self.finished(name))
        self.assertEqual(self.reply(name), {"error": "anthropic API call failed: overloaded"})
        del self.outputs[1]
        self.assertEqual(self.send(name, "hi again"), {"turn": 2})
        self.assertTrue(self.finished(name))
        self.assertEqual(self.reply(name), {"reply": "reply to hi again"})

    def test_many_students_reply_at_once(self):
        names = [self.open() for _ in range(6)]
        gate = threading.Event()
        self.gates.update({number: gate for number in range(1, 7)})
        for name in names:
            self.assertEqual(self.send(name, name), {"turn": 1})
        self.assertTrue(wait_until(lambda: len(self.calls) == 6))
        gate.set()
        for name in names:
            self.assertTrue(self.finished(name))
            self.assertEqual(self.reply(name), {"reply": f"reply to {name}"})

    def test_cost_limit_discards_replies_still_pending(self):
        names = [self.open() for _ in range(3)]
        for number, cost in ((1, 40.0), (2, 20.0), (3, 5.0)):
            self.gates[number], self.costs[number] = threading.Event(), cost
        for name in names:
            self.send(name, "go")
        for number, name in enumerate(names, 1):
            self.gates[number].set()
            self.assertTrue(self.finished(name))
        # The reply that crosses $50 is kept; the next one is discarded but paid for.
        self.assertEqual(self.reply(names[0]), {"reply": "reply to go"})
        self.assertEqual(self.reply(names[1]), {"reply": "reply to go"})
        self.assertEqual(self.reply(names[2]), {"error": "student cost limit reached ($50)"})
        self.assertEqual(self.send(names[0], "more"),
                         {"error": "student cost limit reached ($50)"})
        self.assertEqual(self.cost(), {"spent_usd": 65.0, "limit_usd": 50.0,
                                       "remaining_usd": 0.0, "limit_reached": True,
                                       "pending_replies": 0})
        self.assertIn("(discarded: student cost limit reached ($50))",
                      (self.transcripts / "student-3.md").read_text())

    def test_context_limit_ends_the_student_without_a_reset(self):
        name = self.open()
        original = self.fake_call

        def fill(client, prompt, **kwargs):
            result = original(client, prompt, **kwargs)
            client.conversation.observed_tokens = arena.CONTEXT_RESET_TOKENS
            return result

        with patch.object(arena, "_call_llm_move", fill):
            self.send(name, "long game")
            self.assertTrue(self.finished(name))
        self.assertEqual(self.reply(name), {"reply": "reply to long game"})
        self.assertEqual(self.send(name, "next")["error"],
                         "context limit reached; start a new student")
        self.assertIn("finished: context limit reached",
                      (self.transcripts / f"{name}.md").read_text())
        conversation = self.server.students[name].client.conversation
        with self.assertRaises(arena._StudentContextLimit):
            conversation.reset("context_limit")
        # A provider context error inside a request ends the student too.
        other = self.open()
        self.outputs[2] = arena._StudentContextLimit("context limit reached; start a new student")
        self.send(other, "hi")
        self.assertTrue(self.finished(other))
        self.assertEqual(self.server.students[other].state, "context_limit")
        self.assertIn("alone exceeds", self.send(self.open(), "x" * 260000)["error"])

    def test_close_discards_a_pending_reply_but_counts_its_cost(self):
        name = self.open()
        self.gates[1] = threading.Event()
        self.send(name, "hi")
        self.assertEqual(self.request({"op": "student_close", "name": name}), {})
        self.assertEqual(self.reply(name), {"error": "the student was closed"})
        self.assertEqual(self.send(name, "hi")["error"], "this student is closed")
        self.gates[1].set()
        self.assertTrue(wait_until(lambda: self.cost()["pending_replies"] == 0))
        self.assertEqual(self.cost()["spent_usd"], 0.25)
        self.assertIn("(discarded: the student was closed)",
                      (self.transcripts / f"{name}.md").read_text())

    def test_stopping_the_clock_waits_for_pending_replies(self):
        name = self.open()
        self.gates[1] = threading.Event()
        self.send(name, "hi")
        threading.Timer(0.1, self.gates[1].set).start()
        self.server.set_enabled(False)
        self.assertEqual(self.cost()["spent_usd"], 0.25)
        self.assertEqual(self.send(name, "hi")["error"], "the learning clock is not running")
        self.assertEqual(self.request({"op": "student_open", "name": "new"})["error"],
                         "the learning clock is not running")

    def test_move_prompt_is_the_track1_prompt(self):
        position = tutorial.replay_position(["E5", "C3"])
        expected = arena._llm_move_prompt(position, list(position.legal_moves),
                                          list(position.ko_illegal_moves), position.recent_moves)
        self.assertEqual(self.request({"op": "move_prompt", "moves": ["B E5", "W C3"]}),
                         {"prompt": expected})
        self.assertIn("occupied", self.request({"op": "move_prompt",
                                                "moves": ["E5", "E5"]})["error"])

    def test_restarted_learning_keeps_names_and_cost(self):
        name = self.open("old")
        self.costs[1] = 49.0
        self.send(name, "hi")
        self.assertTrue(self.finished(name))
        self.server.close()
        restarted = self.make_server()
        self.assertEqual(self.request({"op": "student_open", "name": "old"}, restarted),
                         {"name": "old"})
        self.assertIn("ended", self.request({"op": "student_send", "name": "old",
                                             "text": "hi"}, restarted)["error"])
        self.assertEqual(json.loads((self.transcripts / "cost.json").read_text())["spent_usd"],
                         49.0)
        self.assertEqual(self.request({"op": "student_open"}, restarted), {"name": "student-2"})
        self.assertEqual(restarted.students["student-2"].number, 2)
        self.assertIn("Learning was restarted", (self.transcripts / "old.md").read_text())

    def test_sandbox_module_talks_to_the_host(self):
        package = self.root / "python"
        package.mkdir()
        (package / "student.py").write_text(tutorial.STUDENT_MODULE.replace(
            tutorial.SANDBOX_TOOL_SOCKET, str(self.server.socket_path)), encoding="utf-8")
        script = """
import time
from student import Student, StudentError, move_prompt
s = Student("chat")
s.send("hello")
while (text := s.reply()) is None:
    time.sleep(0.01)
print(text)
print(Student("chat").reply())
print(move_prompt(["E5"]).startswith("You are playing White"))
try:
    s.send(3)
except TypeError:
    print("type error")
s.close()
try:
    s.send("again")
except StudentError as exc:
    print(exc)
"""
        output = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                                env={**os.environ, "PYTHONPATH": str(package)},
                                timeout=30)
        self.assertEqual(output.stdout.splitlines(), [
            "reply to hello", "reply to hello", "True", "type error", "this student is closed",
        ], output.stderr)


class LearnerTests(unittest.TestCase):
    def learner(self, cls=arena._ClaudeCodeTutorialLearner, name=PLAYER):
        learner = object.__new__(cls)
        learner.tutorial_player = arena._tutorial_player(name)
        learner.target_api, learner.target = arena._registered_llm_player(
            learner.tutorial_player.target)
        learner.player = arena._registered_llm_player(learner.tutorial_player.learner_player)[1]
        learner.settings = arena._codex_workspace_settings(learner.player.agentic_harness)
        learner._resource_lock = None
        return learner

    def test_subagents_are_disabled(self):
        options = arena._ClaudeCodeTutorialLearner._cli_options(self.learner())
        self.assertEqual(options[options.index("--disallowedTools") + 1],
                         "WebSearch,WebFetch,Agent,Task")
        codex = self.learner(arena._CodexTutorialLearner,
                             "gpt6-sol-high-api-multi-tutorial3.1-gpt6-astra-high-codex-1h")
        self.assertIn("multi_agent = false\n", codex._codex_config_text())
        self.assertNotIn("multi_agent = true", codex._codex_config_text())
        self.assertIn("multi_agent = true", arena._CodexGameClient._codex_config_text())

    def test_katago_and_ladder_networks_are_mounted_read_only_from_3_2(self):
        bare = self.learner(name=PLAYER.replace("tutorial3.3", "tutorial3.1"))
        bare._tool_server = SimpleNamespace(socket_path=Path("/tmp/tools.sock"))
        self.assertEqual(bare._extra_readonly_mounts(),
                         ((Path("/tmp/tools.sock"), tutorial.SANDBOX_TOOL_SOCKET),))
        full = self.learner(name=PLAYER.replace("tutorial3.3", "tutorial3.2"))
        full._tool_server = bare._tool_server
        mounts = dict((str(destination), source)
                      for source, destination in full._extra_readonly_mounts())
        self.assertEqual(mounts[tutorial.SANDBOX_KATAGO_DIR], arena.KATAGO_HOME)
        networks = arena._tutorial_ladder_networks()
        self.assertIn("kata1-b18c384nbt-s9761732864-d4253420187",
                      {network.name for network in networks})
        self.assertNotIn("kata1-zhizi-b40c768nbt-fdx6c", {network.name for network in networks})
        for network in networks:
            self.assertEqual(
                mounts[f"{tutorial.SANDBOX_NETWORK_DIR}/{network.path.name}"], network.path)

    def test_instructions_follow_the_subtrack(self):
        full = self.learner()._instructions(3600)
        self.assertIn("/arena/bin/student", full)
        self.assertIn("claude-sonnet-5-5 at high effort", full)
        self.assertIn("Subagents are disabled.", full)
        bare = self.learner(name=PLAYER.replace("tutorial3.3", "tutorial3.1"))._instructions(1)
        self.assertNotIn("/arena/bin/student", bare)
        self.assertIn("no access to KataGo", bare)

    def test_3_4_teacher_chats_through_the_python_module(self):
        learner = self.learner(name=CHAT_PLAYER)
        instructions = learner._instructions(3600)
        self.assertIn("from student import Student, move_prompt", instructions)
        self.assertIn("at most $50 in total", instructions)
        self.assertIn("many students as you like", instructions)
        self.assertIn("faster and cheaper", instructions)
        self.assertIn("This is only an option", instructions)
        self.assertIn("claude-sonnet-5-5, high effort", instructions)
        self.assertNotIn("/arena/bin/student", instructions)
        self.assertEqual(learner._extra_environment(), {"PYTHONPATH": "/arena/python"})
        self.assertEqual(self.learner()._extra_environment(), {})
        chat, batch = (learner._tutorial_specification(),
                       self.learner()._tutorial_specification())
        self.assertEqual((chat["protocol"], chat["student_cost_limit_usd"]),
                         ("tutorial-distillation-v2", 50.0))
        self.assertNotIn("student_max_positions", chat)
        self.assertEqual((batch["protocol"], batch["student_max_positions"]),
                         ("tutorial-distillation-v1", 200))
        self.assertNotIn("student_cost_limit_usd", batch)
        manifest = arena._llm_player_manifest(CHAT_PLAYER)
        self.assertEqual((manifest["tutorial_protocol"], manifest["student_interface"]),
                         ("tutorial-distillation-v2", "chat"))
        with TemporaryDirectory() as directory:
            learner._phase_dir = Path(directory)
            learner._write_public_files()
            public = Path(directory) / "public"
            self.assertEqual((public / "python" / "student.py").read_text(),
                             tutorial.STUDENT_MODULE)
            self.assertFalse((public / "bin" / "student").exists())
            self.assertTrue((public / "bin" / "tutorial-tokens").exists())

    def test_3_4_checkpoint_counts_chat_cost(self):
        learner = self.learner(name=CHAT_PLAYER)
        learner.api_name = "anthropic_claude_code_workspace"
        learner.proxy_log_name = "anthropic-proxy"
        with TemporaryDirectory() as directory:
            preparation, staging = Path(directory) / "preparation", Path(directory) / "staging"
            learner.cwd = Path(directory) / "workspace"
            for path in (preparation / "student" / "chats", staging, learner.cwd):
                path.mkdir(parents=True)
            learner._capture_preparation_outputs(preparation)
            for name, cost in (("a", 1.5), ("b", 2.0)):
                (preparation / "student" / "chats" / f"{name}.jsonl").write_text(
                    json.dumps({"ok": True, "cost_usd": cost, "usage": {}}) + "\n")
            (preparation / "anthropic-proxy.usage.jsonl").write_text("")
            fields = learner._checkpoint_fields(preparation, staging)
            self.assertEqual((fields["students"], fields["student_requests"],
                              fields["student_cost_usd"]), (2, 2, 3.5))

    def test_capture_truncates_and_checkpoint_counts_student_cost(self):
        learner = self.learner()
        learner.api_name = "anthropic_claude_code_workspace"
        learner.proxy_log_name = "anthropic-proxy"
        with TemporaryDirectory() as directory:
            preparation, staging = Path(directory) / "preparation", Path(directory) / "staging"
            learner.cwd = Path(directory) / "workspace"
            for path in (preparation / "student", staging, learner.cwd):
                path.mkdir(parents=True)
            (learner.cwd / "tutorial.md").write_text("tip " * 6000, encoding="utf-8")
            learner._capture_preparation_outputs(preparation)
            with (preparation / "student" / "call-000001.jsonl").open("w") as ledger:
                for ok, cost, usage in ((True, 0.5, {"input_tokens": 7, "output_tokens": 3}),
                                        (False, 0.25, {})):
                    ledger.write(json.dumps({"ok": ok, "cost_usd": cost, "usage": usage}) + "\n")
            (preparation / "anthropic-proxy.usage.jsonl").write_text("")
            fields = learner._checkpoint_fields(preparation, staging)
            self.assertEqual(fields["tutorial_tokens"], 5000)
            self.assertTrue(fields["tutorial_truncated"])
            self.assertEqual(fields["student_requests"], 2)
            self.assertEqual(fields["student_failed_requests"], 1)
            self.assertEqual(fields["student_tokens"]["input_tokens"], 7)
            self.assertEqual(fields["learning_cost_usd"], 0.75)
            self.assertTrue((preparation / "tutorial-source.md").exists())
            self.assertEqual(os.stat(staging / "tutorial.md").st_mode & 0o777, 0o400)

    def test_missing_tutorial_publishes_an_empty_one(self):
        learner = self.learner()
        with TemporaryDirectory() as directory:
            learner.cwd = Path(directory) / "workspace"
            learner.cwd.mkdir()
            learner._capture_preparation_outputs(Path(directory))
            self.assertEqual((Path(directory) / "tutorial.md").read_text(), "")
            capture = json.loads((Path(directory) / "tutorial-capture.json").read_text())
            self.assertFalse(capture["source_present"])


if __name__ == "__main__":
    unittest.main()
