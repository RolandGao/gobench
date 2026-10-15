"""Track 2 code-only evaluation: registry, GTP reader and real sandboxed games.

GOBENCH_RESOURCE_TESTS=1 enables the real cgroup/mount/bubblewrap games. They
mock the paid Codex preparation turn and never send a model request.
"""

import os
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import arena
from gobench.go_rules import TrompTaylorRules
from gobench.workspace_runtime import (
    WorkspaceEngineForfeit, WorkspaceSettings, WorkspaceTimeExpired, atomic_json,
)

PLAYER = "gpt6-astra-high-codex-engine-1h"

# Answers every command; genmove plays the first empty point in a fixed order
# unless told otherwise, and logs every command it receives.
ENGINE = r'''#!/usr/bin/python3
import os, sys, time, threading
mode = open("/workspace/mode").read().strip()
log = open("/workspace/commands.log", "a")
if mode == "ticker":
    def tick():
        n = 0
        while True:
            n += 1
            with open("/tmp/ticks", "w") as f:
                f.write(str(n))
            time.sleep(0.01)
    threading.Thread(target=tick, daemon=True).start()
for line in sys.stdin:
    command = line.strip()
    log.write(command + "\n"); log.flush()
    words = command.split()
    if not words:
        continue
    if words[0] == "genmove":
        if mode == "sleep":
            time.sleep(60)
        if mode == "crash":
            sys.exit(3)
        move = {"illegal": "Z9", "ko": "D5"}.get(mode, "pass")
        print("= " + move + "\n", flush=True)
    elif words[0] == "time_left":
        print("? unknown command\n", flush=True)
    elif words[0] == "quit":
        print("=\n", flush=True)
        break
    else:
        print("=\n", flush=True)
'''


def fake_game(history, to_move):
    return NS(get_move_history=lambda: tuple(history), to_move=to_move,
              get_possible_moves=lambda: (["pass", "E5", "D4"], []))


def refereed_game(history):
    """The real referee's legality for history, without starting KataGo."""
    rules = TrompTaylorRules(9)
    for color, move in history:
        evaluation = rules.evaluate(color, move)
        assert evaluation.legal, (color, move, evaluation.reason)
        rules.commit(evaluation)
    to_move = "W" if history[-1][0] == "B" else "B"
    return NS(get_move_history=lambda: tuple(history), to_move=to_move,
              get_possible_moves=lambda: rules.possible_moves(to_move))


# Black E5 has just captured White D5. Retaking at D5 recreates the board after
# move 8, so it is illegal by positional superko although D5 is empty.
KO_HISTORY = [("B", "C5"), ("W", "E6"), ("B", "D6"), ("W", "F5"), ("B", "D4"),
              ("W", "E4"), ("B", "A1"), ("W", "D5"), ("B", "E5")]


class RegistryTests(unittest.TestCase):
    def test_clock_tag_fixes_the_evaluation_clock(self):
        configured = replace(arena.CONFIG, workspace=WorkspaceSettings(evaluation_seconds=300))
        with mock.patch.object(arena._State, "config", configured):
            for name, training, clock in (
                ("gpt6-astra-high-codex-engine-60s-4h", 14400, 60),
                ("gpt5.6-sol-high-codex-engine-60s-8h", 28800, 60),
                ("claude-opus-5-5-high-claude-code-engine-60s-2h", 7200, 60),
                ("gpt6-astra-high-codex-engine-4h", 14400, 300),
            ):
                harness = arena._llm_player_config(name)[1].agentic_harness
                settings = arena._codex_workspace_settings(harness)
                self.assertEqual((settings.training_seconds, settings.evaluation_seconds),
                                 (training, clock), name)
                self.assertEqual(arena._result_llm_track(name), 2)
        self.assertIs(arena._workspace_client_class_for_player(
            "claude-opus-5-5-high-claude-code-engine-60s-1h"), arena._ClaudeCodeEngineGameClient)

    def test_engine_players_are_codex_workspace_players_with_their_own_client(self):
        api, player = arena._llm_player_config(PLAYER)
        self.assertEqual((api.name, player.model, player.level),
                         ("openai_codex_workspace", "gpt-6-astra", "high"))
        self.assertEqual(arena._workspace_training_seconds(player.agentic_harness), 3600)
        for name in (PLAYER, f"{PLAYER}2"):
            self.assertIs(arena._workspace_client_class_for_player(name),
                          arena._CodexEngineGameClient)
        self.assertIs(arena._workspace_client_class_for_player("gpt6-astra-high-codex-1h"),
                      arena._CodexGameClient)

    def test_claude_code_and_sol_code_only_players(self):
        cases = (("claude-opus-5-5-high-claude-code-engine-2h", arena._ClaudeCodeEngineGameClient,
                  "anthropic_claude_code_workspace", 7200),
                 ("gpt5.6-sol-high-codex-engine-1h", arena._CodexEngineGameClient,
                  "openai_codex_workspace", 3600))
        for name, client_class, api_name, seconds in cases:
            with self.subTest(name=name):
                api, player = arena._llm_player_config(name)
                self.assertEqual(api.name, api_name)
                self.assertIs(arena._workspace_client_class_for_player(name), client_class)
                self.assertEqual(arena._workspace_training_seconds(player.agentic_harness), seconds)
                manifest = arena._llm_player_manifest(name)
                self.assertEqual(manifest["evaluation"], "code_only")
        self.assertEqual(arena._llm_player_manifest("claude-opus-5-5-high-claude-code-engine-1h")
                         ["network_access"], "anthropic_proxy_during_preparation_only")

    def test_manifest_declares_code_only_gtp_evaluation(self):
        manifest = arena._llm_player_manifest(PLAYER)
        self.assertEqual(manifest["evaluation"], "code_only")
        self.assertEqual(manifest["engine_interface"], "gtp-v1")
        self.assertEqual(manifest["engine_failure_policy"], "forfeit")


class GTPReaderTests(unittest.TestCase):
    def run_program(self, source):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        program = directory / "program.py"
        program.write_text(source)
        process = arena._GTPEngineProcess((sys.executable, program),
                                          stderr_path=directory / "stderr.log")
        self.addCleanup(process.close)
        return process

    def test_reads_success_error_and_multiline_replies(self):
        process = self.run_program(
            "import sys\n"
            "for line in sys.stdin:\n"
            "    w = line.split()\n"
            "    if w[0] == 'genmove': print('= D4\\n', flush=True)\n"
            "    elif w[0] == 'showboard': print('= a\\nb\\n', flush=True)\n"
            "    else: print('? nope\\n', flush=True)\n")
        deadline = time.monotonic() + 10
        self.assertEqual(process.command("genmove B", deadline=deadline), (True, "D4"))
        self.assertEqual(process.command("showboard", deadline=deadline), (True, "a\nb"))
        self.assertEqual(process.command("time_left B 3 0", deadline=deadline), (False, "nope"))

    def test_garbage_exit_and_silence_are_forfeits(self):
        garbage = self.run_program("import sys\nsys.stdin.readline()\nprint('D4', flush=True)\n")
        with self.assertRaises(WorkspaceEngineForfeit) as raised:
            garbage.command("genmove B", deadline=time.monotonic() + 10)
        self.assertEqual(raised.exception.reason, "protocol_error")
        exited = self.run_program("import sys\nsys.exit(0)\n")
        with self.assertRaises(WorkspaceEngineForfeit) as raised:
            exited.command("genmove B", deadline=time.monotonic() + 10)
        self.assertEqual(raised.exception.reason, "crash")
        silent = self.run_program("import time\ntime.sleep(30)\n")
        with self.assertRaises(WorkspaceEngineForfeit) as raised:
            silent.command("genmove B", deadline=time.monotonic() + 0.3)
        self.assertEqual(raised.exception.reason, "no_reply")


@unittest.skipUnless(os.environ.get("GOBENCH_RESOURCE_TESTS") == "1",
                     "set GOBENCH_RESOURCE_TESTS=1 for real local Linux resource tests")
class SandboxedEngineTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="gobench-engine-test-")))
        self.work = self.root / "untracked_log" / "run" / "batch-001"
        self.work.mkdir(parents=True)

    def client(self, mode, *, evaluation_seconds=20, game=1, install=True, player=PLAYER):
        settings = WorkspaceSettings(training_seconds=0.15, evaluation_seconds=evaluation_seconds,
                                     storage_mib=64, memory_mib=256)

        def start(client):
            client._scope = NS(thaw=lambda: None, kill=lambda: None, close=lambda: None)
            client._proxy = NS(set_enabled=lambda _: None, close=lambda: None)

        def train(client, _thread, prompt, **_kwargs):
            self.prompt = prompt
            if install:
                (client.cwd / "engine").write_text(ENGINE)
                (client.cwd / "engine").chmod(0o755)
            (client.cwd / "mode").write_text(mode)
            atomic_json(client.state_path, {"thread_id": "training-thread"})
            time.sleep(0.3)
            return NS(usage=None, final_response="saved"), []

        harness = arena._llm_player_config(player)[1].agentic_harness
        client_class = arena._workspace_client_class(harness)
        # Mock the paid agent session on the harness's own runtime class.
        runtime_class = client_class.__mro__[2]
        durations = (arena._CLAUDE_CODE_ENGINE_TRAINING_SECONDS
                     if runtime_class is arena._ClaudeCodeGameClient
                     else arena._CODEX_ENGINE_TRAINING_SECONDS)
        patches = (
            mock.patch.dict(durations, {harness: settings.training_seconds}),
            mock.patch.object(arena._Arena, "ROOT", self.root),
            mock.patch.object(arena._Arena, "UNTRACKED_LOG_ROOT", self.root / "untracked_log"),
            mock.patch.object(arena._State, "config", replace(arena.CONFIG, workspace=settings)),
            mock.patch.object(runtime_class, "_start_runtime", start),
            mock.patch.object(runtime_class, "_persistent_thread", lambda _: None),
            mock.patch.object(runtime_class, "_turn_options", lambda _: {}),
            mock.patch.object(runtime_class, "_run_turn", train),
        )
        for patch in patches:
            self.enterContext(patch)
        client = client_class(
            player, arena._llm_player_config(player)[1], self.work, game,
            proxy_credential=NS(auth_mode="fake"))
        self.addCleanup(client.close)
        return client

    def move(self, client, history, color):
        client.observe_game(fake_game(history, color))
        return client.create(model="gpt-6-astra", reasoning={"effort": "high"}, input="unused")

    def test_preparation_prompt_defines_the_code_only_interface(self):
        self.client("normal")
        for text in ("CODE-ONLY", "/workspace/engine", "genmove <color>", "`= <result>`",
                     "POSITIONAL SUPERKO", "including the empty starting board",
                     "must accept",
                     "20-second clock", "frozen during the opponent's turn"):
            self.assertIn(text, self.prompt)

    def test_engine_plays_over_gtp_with_full_history_and_private_game_copies(self):
        first = self.client("normal")
        self.assertEqual(self.move(first, [("B", "E5")], "W").output_text, "pass")
        self.assertEqual(self.move(first, [("B", "E5"), ("W", "pass"), ("B", "D4")], "W")
                         .output_text, "pass")
        commands = (first.cwd / "commands.log").read_text().splitlines()
        self.assertEqual(commands, [
            "boardsize 9", "clear_board", "komi 7", "play B E5",
            commands[4], "genmove W", "play B D4", commands[7], "genmove W",
        ])
        self.assertTrue(commands[4].startswith("time_left W "))
        self.assertGreater(first._clock.spent, 0)
        self.assertLess(first._clock.spent, 20)
        first.mark_complete()
        first.close()
        second = self.client("normal", game=2)
        self.assertFalse((second.cwd / "commands.log").exists())

    def test_program_is_frozen_while_the_opponent_moves(self):
        client = self.client("ticker")
        self.move(client, [("B", "E5")], "W")
        ticks = client._volume.mountpoint / "tmp" / "ticks"
        before = ticks.read_text()
        time.sleep(0.5)
        self.assertEqual(ticks.read_text(), before)
        spent = client._clock.spent
        time.sleep(0.3)
        self.assertEqual(client._clock.spent, spent)

    def test_illegal_move_crash_and_missing_program_forfeit(self):
        for mode, reason in (("illegal", "illegal_move"), ("crash", "crash")):
            with self.subTest(mode=mode):
                self.work = self.root / "untracked_log" / mode / "batch-001"
                self.work.mkdir(parents=True)
                client = self.client(mode)
                with self.assertRaises(WorkspaceEngineForfeit) as raised:
                    self.move(client, [("B", "E5")], "W")
                self.assertEqual(raised.exception.reason, reason)
                # Release the exclusive core now; busy hosts may have few free.
                client.close()
        self.work = self.root / "untracked_log" / "missing" / "batch-001"
        self.work.mkdir(parents=True)
        with self.assertRaises(WorkspaceEngineForfeit) as raised:
            self.move(self.client("normal", install=False), [], "B")
        self.assertEqual(raised.exception.reason, "missing_program")

    def test_claude_code_preparation_also_evaluates_only_the_program(self):
        client = self.client("normal", player="claude-opus-5-5-high-claude-code-engine-1h")
        self.assertIsInstance(client, arena._ClaudeCodeEngineGameClient)
        self.assertIn("CODE-ONLY", self.prompt)
        specification = client.checkpoint["specification"]
        self.assertEqual((specification["evaluation"], specification["engine_interface"]),
                         ("code_only", "gtp-v1"))
        self.assertIn("claude_code", specification["runtime"])
        self.assertEqual(self.move(client, [("B", "E5")], "W").output_text, "pass")
        self.assertIn("genmove W", (client.cwd / "commands.log").read_text())

    def test_superko_illegal_ko_retake_forfeits_after_full_history_is_sent(self):
        game = refereed_game(KO_HISTORY)
        legal, superko = game.get_possible_moves()
        self.assertIn("D5", superko)
        self.assertNotIn("D5", legal)
        client = self.client("ko")
        client.observe_game(game)
        with self.assertRaises(WorkspaceEngineForfeit) as raised:
            client.create(model="gpt-6-astra", reasoning={"effort": "high"}, input="unused")
        self.assertEqual((raised.exception.reason, str(raised.exception)),
                         ("illegal_move", "illegal_move: D5"))
        commands = (client.cwd / "commands.log").read_text().splitlines()
        self.assertEqual([c for c in commands if c.startswith("play ")],
                         [f"play {color} {move}" for color, move in KO_HISTORY])

    def test_slow_program_loses_on_time(self):
        client = self.client("sleep", evaluation_seconds=1)
        started = time.monotonic()
        with self.assertRaises(WorkspaceTimeExpired):
            self.move(client, [("B", "E5")], "W")
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(client._clock.remaining, 0)


if __name__ == "__main__":
    unittest.main()
