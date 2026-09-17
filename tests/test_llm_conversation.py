"""Multi-turn wire replay, reset boundaries, and crash recovery without API calls."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import arena
from gobench.llm_conversation import APIConversation, ConversationClient


class Dumpable:
    def __init__(self, **value):
        self.value = value

    def model_dump(self, **kwargs):
        return self.value


def response(text="D4", input_tokens=1000, output_tokens=200):
    return SimpleNamespace(
        output_text=text,
        output=[
            {"id": "rs_required", "type": "reasoning", "summary": [],
             "encrypted_content": "opaque reasoning"},
            {"type": "message", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": text, "annotations": []}]},
        ],
        usage=Dumpable(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class ConversationTests(unittest.TestCase):
    def session(self, wire="responses", game=1, **kwargs):
        return APIConversation("openai", "gpt-5.6-sol", "test", game, wire, **kwargs)

    def test_native_history_and_reset_at_250000(self):
        session = self.session()
        original = {"input": "first", "reasoning": {"effort": "high"}, "store": False}
        first = session.prepare(original, "first")
        self.assertEqual(original["input"], "first")
        self.assertEqual(first["reasoning"]["context"], "all_turns")
        session.accept(session.completed_event(response(), 1000), "D4", 1, 1)
        second = session.prepare(original, "second")
        self.assertEqual(second["input"][1]["encrypted_content"], "opaque reasoning")
        self.assertEqual(second["input"][-1]["content"], "second")
        self.assertEqual(len(second["input"]), 4)
        session.observed_tokens = 250000
        third = session.prepare(original, "third")
        self.assertEqual(third["input"], [{"role": "user", "content": "third"}])
        self.assertEqual(session.pending["reset_reason"], "context_limit")
        self.assertEqual(session.session, 2)

    def test_qwen_caching_preserves_every_prior_reasoning_turn(self):
        name = "qwen3.8-max-high-api-multi"
        api, player = arena._llm_player_config(name)
        session = APIConversation(api.name, player.model, name, 1, "chat")
        reasoning = []
        for turn in range(6):
            prompt = f"turn {turn}"
            request = session.prepare(arena._llm_request(api, player, prompt), prompt)
            self.assertEqual(request["extra_body"]["reasoning"], {"effort": "high", "exclude": False})
            markers = [block for message in request["messages"] if message["role"] == "user"
                       for block in message["content"] if "cache_control" in block]
            self.assertEqual(len(markers), min(turn + 1, 4))
            assistants = [message for message in request["messages"] if message["role"] == "assistant"]
            self.assertEqual([message["reasoning_details"] for message in assistants], reasoning)
            details = [{"type": "reasoning.encrypted", "data": f"opaque {turn}", "signature": f"sig {turn}"}]
            reasoning.append(details)
            result = SimpleNamespace(choices=[SimpleNamespace(message={
                "role": "assistant", "content": "D4", "reasoning_details": details,
            })])
            session.accept(session.completed_event(result, 1000), "D4", turn, 1)
        self.assertTrue(all(isinstance(m["content"], str) for m in session.history if m["role"] == "user"))

    def test_shared_window_reserves_room_without_dropping_reasoning(self):
        name = "kimi-k3-high-api-multi"
        api, player = arena._llm_player_config(name)
        session = APIConversation(api.name, player.model, name, 1, "chat",
                                  context_window=player.context_window,
                                  max_tokens_field=api.max_tokens_field)
        prompt = "first"
        request = session.prepare(arena._llm_request(api, player, prompt), prompt)
        self.assertEqual(request["max_completion_tokens"], 943_718)
        result = SimpleNamespace(choices=[SimpleNamespace(message={
            "role": "assistant", "content": "D4", "reasoning_content": "all previous reasoning",
        })])
        session.accept(session.completed_event(result, 200_000), "D4", 1, 1)
        request = session.prepare(arena._llm_request(api, player, "next"), "next")
        self.assertEqual(request["max_completion_tokens"],
                         1_048_576 - session.pending["estimated_input_tokens"])
        self.assertEqual(request["messages"][1]["reasoning_content"], "all previous reasoning")
        self.assertEqual(session.session, 1)

    def test_current_prompt_alone_too_large_and_missing_usage(self):
        session = self.session(limit=1000)
        with self.assertRaisesRegex(ValueError, "alone"):
            session.prepare({}, "x" * 1000)
        session.history = [{"role": "assistant", "content": "x" * 1000}]
        session.prepare({"reasoning": {}}, "small")
        self.assertEqual(session.session, 2)

    def test_anthropic_thinking_and_signature(self):
        session = self.session("anthropic")
        blocks = [{"type": "thinking", "thinking": "analysis", "signature": "signed"},
                  {"type": "text", "text": "D4"}]
        session.prepare({}, "first")
        event = session.completed_event(SimpleNamespace(content=blocks), 500)
        session.accept(event, "D4", 1, 1)
        self.assertEqual(session.prepare({}, "next")["messages"][1]["content"], blocks)

    def test_google_steps_and_thought_signature(self):
        session = self.session("google")
        steps = [{"type": "thought", "signature": "c2lnbmVk"},
                 {"type": "model_output", "content": [{"type": "text", "text": "D4"}]}]
        session.prepare({}, "first")
        session.accept(session.completed_event(SimpleNamespace(steps=steps), 500), "D4", 1, 1)
        request = session.prepare({}, "next")
        self.assertEqual(request["input"][0]["type"], "user_input")
        self.assertEqual(request["input"][1:3], steps)
        # Validate against the installed SDK's actual stateless input schema.
        from pydantic import TypeAdapter
        from google.genai._gaos.types.interactions.interactionsinput import InteractionsInput
        TypeAdapter(InteractionsInput).validate_python(request["input"])

    def test_chat_native_reasoning(self):
        for field, value in [("reasoning_details", [{"type": "reasoning.encrypted", "data": "abc"}]),
                             ("reasoning_content", "analysis")]:
            with self.subTest(field=field):
                session = self.session("chat")
                message = {"role": "assistant", "content": "D4", field: value}
                session.prepare({}, "first")
                result = SimpleNamespace(choices=[SimpleNamespace(message=Dumpable(**message))])
                session.accept(session.completed_event(result, 500), "D4", 1, 1)
                self.assertEqual(session.prepare({}, "next")["messages"][1], message)

    def test_games_and_capped_attempts_do_not_share_history(self):
        first, second = self.session(), self.session(game=2)
        first.prepare({"reasoning": {}}, "first")
        first.accept(first.completed_event(response(), 1000), "D4", 1, 1)
        self.assertEqual(second.history, [])
        first.reset_game()
        self.assertEqual(first.history, [])
        self.assertEqual(first.game_attempt, 2)
        self.assertIsNone(first.cached_reply("first", 1, 1))

    def test_recovery_rejects_changed_policy_and_ignores_other_game_attempts(self):
        session = self.session()
        session.prepare({"reasoning": {}}, "first")
        event = session.completed_event(response(), 1000)
        entry = dict(game=1, player="test", ok=True, conversation=event,
                     output="D4", move=1, attempt=1)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calls.jsonl"
            path.write_text(json.dumps(entry) + "\n")
            changed = self.session(limit=200000)
            with self.assertRaisesRegex(ValueError, "policy"):
                changed.load(path)
            second_attempt = self.session()
            second_attempt.set_game_attempt(2)
            second_attempt.load(path)
            self.assertEqual(second_attempt.history, [])


class ArenaConversationTests(unittest.TestCase):
    name = "gpt5.6-sol-high-api-multi"

    def client(self, create, name=None):
        name = name or self.name
        api, player = arena._llm_player_config(name)
        session = APIConversation(api.name, player.model, name, 1, "responses")
        return ConversationClient(SimpleNamespace(responses=SimpleNamespace(create=create)), session)

    def call(self, client, root, prompt="Legal moves now: D4, pass", move=1, attempt=1):
        return arena._call_llm_move(
            client, prompt, player_name=self.name, log_path=root / "raw.jsonl",
            compact_log_path=root / "compact.jsonl", game_number=1,
            move_number=move, attempt=attempt,
        )

    def test_modes_are_separate_and_manifest_records_policy(self):
        singles = {name for api in arena._Arena.LLM_APIS for name, p in api.players.items()
                   if p.agentic_harness == "api"}
        multis = set(arena.RUN_TYPES["api_multi"].active_players)
        self.assertEqual(multis, {name + "-multi" for name in singles})
        for name in multis:
            self.assertTrue(arena._is_result_api_llm_player(name))
            manifest = arena._llm_player_manifest(name)
            self.assertEqual(manifest["context_reset_tokens"], 250000)
            self.assertFalse(manifest["compaction"])
            if arena._llm_player_config(name)[0].name in {"deepseek", "deepseek_responses"}:
                self.assertEqual(len(manifest["tools"]), 1)
                self.assertEqual(manifest["tool_choice"], "none")
            else:
                self.assertFalse(manifest["tools"])
        api, player = arena._llm_player_config("gpt5.6-sol-high-api")
        self.assertEqual(arena._llm_request(api, player, "prompt")["input"], "prompt")

    def test_recovery_reuses_reply_and_preserves_history_without_duplicate_billing(self):
        requests = []
        def create(**request):
            requests.append(request)
            return response()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.client(create)
            self.call(first, root)
            resumed = self.client(create)
            self.assertEqual(self.call(resumed, root), ("D4", 0.0, 0.0))
            self.assertTrue(resumed.conversation.last_reused)
            self.assertEqual(len(requests), 1)
            self.call(resumed, root, move=3, prompt="Legal moves now: E5, pass")
            self.assertEqual(len(requests[-1]["input"]), 4)
            raw = [json.loads(line) for line in (root / "raw.jsonl").read_text().splitlines()]
            compact = [json.loads(line) for line in (root / "compact.jsonl").read_text().splitlines()]
            self.assertEqual(len(raw), 2)
            self.assertIsInstance(raw[-1]["request"]["input"], str)
            self.assertNotIn("assistant_items", compact[-1]["conversation"])
            self.assertIn("assistant_items", raw[-1]["conversation"])
            # A changed game prompt must never silently reuse an old move.
            with self.assertRaisesRegex(arena.ArenaError, "does not match"):
                self.call(resumed, root, prompt="Legal moves now: A1")

    def test_transient_retry_does_not_duplicate_user_turn(self):
        requests = []
        class Unavailable(Exception):
            status_code = 503
        def create(**request):
            requests.append(request)
            if len(requests) == 1:
                raise Unavailable("unavailable")
            return response()
        with TemporaryDirectory() as directory, patch.object(arena.time, "sleep"):
            client = self.client(create)
            self.call(client, Path(directory))
            self.assertEqual(requests[0], requests[1])
            self.assertEqual(len(client.conversation.history), 3)

    def test_responses_request_and_replay_all_reasoning_after_recovery(self):
        names = [
            "muse-spark-1.3-contributor-high-api-multi",
            "grok-4.5-high-api-multi",
            *(f"grok-4.6-{effort}-api-multi" for effort in ("low", "medium", "high", "xhigh")),
            "gpt6-astra-high-api-multi",
        ]
        for name in names:
            with self.subTest(player=name), patch.object(self, "name", name):
                self._check_responses_reasoning_recovery()

    def _check_responses_reasoning_recovery(self):
        requests, outputs = [], []
        api, player = arena._llm_player_config(self.name)
        expected_reasoning = {"effort": player.level}
        if api.name == "openai":
            expected_reasoning["context"] = "all_turns"

        def create(**request):
            self.assertEqual(request["model"], player.model)
            self.assertEqual(request["include"], ["reasoning.encrypted_content"])
            self.assertEqual(request["reasoning"], expected_reasoning)
            self.assertFalse(request["store"])
            if api.name in {"openai", "xai"}:
                self.assertTrue(request["prompt_cache_key"])
                if requests:
                    self.assertEqual(request["prompt_cache_key"], requests[0]["prompt_cache_key"])
            requests.append(request)
            result = response()
            result.output[0].update(
                id=f"rs_{len(requests)}",
                encrypted_content=f"opaque {api.name} reasoning {len(requests)}",
            )
            outputs.append(result.output)
            return result

        with TemporaryDirectory() as directory:
            root = Path(directory)
            client = self.client(create)
            self.call(client, root, prompt="first", move=1)
            self.call(client, root, prompt="second", move=3)
            self.assertEqual(requests[1]["input"][1:3], outputs[0])
            resumed = self.client(create)
            self.call(resumed, root, prompt="third", move=5)
            self.assertEqual(requests[2]["input"], [
                {"role": "user", "content": "first"}, *outputs[0],
                {"role": "user", "content": "second"}, *outputs[1],
                {"role": "user", "content": "third"},
            ])

    def test_context_error_resets_once_then_fails_if_fresh_prompt_rejected(self):
        requests = []
        def create(**request):
            requests.append(request)
            if len(requests) > 1:
                raise ValueError("maximum context length exceeded")
            return response()
        with TemporaryDirectory() as directory, patch.object(arena.time, "sleep"):
            root = Path(directory)
            client = self.client(create)
            self.call(client, root)
            with self.assertRaises(arena.ArenaError):
                self.call(client, root, move=3)
            self.assertEqual(len(requests), 3)
            self.assertEqual(len(requests[-1]["input"]), 1)

    def test_reset_is_restored_from_ledger(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            client = self.client(lambda **kwargs: response(input_tokens=249900, output_tokens=200))
            self.call(client, root)
            self.call(client, root, move=3)
            self.assertEqual(client.conversation.session, 2)
            restored = self.client(None)
            restored.conversation.load(root / "raw.jsonl")
            self.assertEqual(restored.conversation.session, 2)
            self.assertEqual(restored.conversation.history, client.conversation.history)

    def test_recovered_invalid_outputs_are_not_counted_twice(self):
        state = SimpleNamespace(size=9, to_move="B", rows=["........."] * 9)
        game = SimpleNamespace(
            get_possible_moves=lambda: (["D4", "pass"], []),
            get_board_state=lambda: state,
            get_move_history=lambda: (),
        )
        outputs = iter(["J10", "D4\nextra text", "D4"])
        prompts = []
        def create(**request):
            prompts.append(request["input"][-1]["content"])
            return response(next(outputs))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = dict(player_name=self.name, log_path=root / "raw.jsonl",
                          game_number=1, move_number=1)
            first_stats = arena.LLMGameStats()
            arena._choose_llm_move(game, self.client(create),
                                   first_stats, **kwargs)
            original = arena._llm_move_prompt(state, ["D4", "pass", "resign"], [])
            self.assertEqual(prompts, [original] * 3)
            entries = arena._read_jsonl_objects(root / "raw.jsonl", "test calls")
            recovered = arena._recovered_llm_stats(SimpleNamespace(number=1), [], entries)
            restored = self.client(lambda **kw: self.fail("must reuse saved replies"))
            self.assertEqual(arena._choose_llm_move(game, restored, recovered, **kwargs), "D4")
            self.assertEqual(recovered.illegal_moves, 2)
            self.assertEqual(recovered.cost_usd, first_stats.cost_usd)

    def test_legacy_retry_recovery_uses_original_prompt_for_new_requests(self):
        state = SimpleNamespace(size=9, to_move="B", rows=["........."] * 9)
        game = SimpleNamespace(
            get_possible_moves=lambda: (["D4", "pass"], []),
            get_board_state=lambda: state,
            get_move_history=lambda: (),
        )
        original = arena._llm_move_prompt(state, ["D4", "pass", "resign"], [])
        legacy = arena._insert_before_move_output_instructions(
            original, "The previous move was not legal. Try again.")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.client(lambda **kw: response("D4\nextra text"))
            self.call(first, root, prompt=original)
            self.call(first, root, prompt=legacy, attempt=2)
            entries = arena._read_jsonl_objects(root / "raw.jsonl", "test calls")
            stats = arena._recovered_llm_stats(SimpleNamespace(number=1), [], entries)
            prompts = []
            def create(**request):
                prompts.append(request["input"][-1]["content"])
                return response("D4")
            restored = self.client(create)
            self.assertEqual(arena._choose_llm_move(
                game, restored, stats, player_name=self.name,
                log_path=root / "raw.jsonl", game_number=1, move_number=1), "D4")
            self.assertEqual(prompts, [original])
            self.assertEqual(stats.illegal_moves, 2)
            self.assertEqual(len(arena._read_jsonl_objects(
                root / "raw.jsonl", "test calls")), 3)
            # Compatibility must not allow unrelated changes to saved prompts.
            with self.assertRaisesRegex(arena.ArenaError, "prompt"):
                self.call(restored, root, prompt=original + "changed", attempt=2)

    def test_provider_usage_includes_cached_input_and_separate_thinking(self):
        cases = [
            ("opus-5-high-api-multi", "anthropic", "messages",
             SimpleNamespace(content=[Dumpable(type="text", text="D4")],
                             usage=Dumpable(input_tokens=10, cache_read_input_tokens=100,
                                            cache_creation_input_tokens=20, output_tokens=30)), 160),
            ("gemini-3.6-flash-high-api-multi", "google", "interactions",
             SimpleNamespace(output_text="D4", steps=[{"type": "model_output", "content": []}],
                             usage=Dumpable(total_input_tokens=100, total_cached_tokens=50,
                                            total_output_tokens=10, total_thought_tokens=30)), 140),
        ]
        for name, wire, endpoint, result, expected in cases:
            with self.subTest(name=name), TemporaryDirectory() as directory:
                api, player = arena._llm_player_config(name)
                session = APIConversation(api.name, player.model, name, 1, wire)
                client = ConversationClient(SimpleNamespace(**{
                    endpoint: SimpleNamespace(create=lambda **kw: result),
                }), session)
                arena._call_llm_move(client, "Legal moves now: D4", player_name=name,
                                     log_path=Path(directory) / "calls.jsonl", game_number=1,
                                     move_number=1, attempt=1)
                self.assertEqual(session.observed_tokens, expected)


if __name__ == "__main__":
    unittest.main()
