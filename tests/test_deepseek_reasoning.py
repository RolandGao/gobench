"""DeepSeek-only dummy tool declarations and reasoning replay; no API calls."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from openai.types.chat import ChatCompletionMessage
from openai.types.responses import ResponseReasoningItem

import arena
from gobench.llm_conversation import APIConversation, ConversationClient


class DeepSeekReasoningTests(unittest.TestCase):
    def test_only_deepseek_requests_declare_a_disabled_dummy_tool(self):
        for api in arena._Arena.LLM_APIS:
            for name, player in api.players.items():
                with self.subTest(player=name):
                    request = arena._llm_request(api, player, "Legal moves now: pass")
                    if api.name not in {"deepseek", "deepseek_responses"}:
                        self.assertNotIn("tools", request)
                        self.assertNotIn("tool_choice", request)
                        continue
                    self.assertEqual(request["tool_choice"], "none")
                    self.assertEqual(len(request["tools"]), 1)
                    tool = request["tools"][0]
                    self.assertEqual(tool["type"], "function")
                    function = (
                        tool if api.name == "deepseek_responses" else tool["function"]
                    )
                    self.assertEqual(function["name"], "arena_noop")
                    self.assertEqual(function["parameters"]["properties"], {})
                    manifest = arena._llm_player_manifest(name)
                    self.assertEqual(manifest["tools"], request["tools"])
                    self.assertEqual(manifest["tool_choice"], "none")

    def test_reasoning_is_resent_after_multiple_moves_and_restart(self):
        for api in arena._Arena.LLM_APIS:
            if api.name not in {"deepseek", "deepseek_responses"}:
                continue
            name, player = next(
                (name, player)
                for name, player in api.players.items()
                if player.agentic_harness == "api-multi"
            )
            with self.subTest(provider=api.name), tempfile.TemporaryDirectory() as tmp:
                requests = []
                responses = api.name == "deepseek_responses"
                wire = "responses" if responses else "chat"

                def create(**request):
                    requests.append(request)
                    thought = f"retained reasoning {len(requests)}"
                    if responses:
                        return NS(
                            output_text="pass",
                            output=[
                                ResponseReasoningItem.model_validate(
                                    {
                                        "id": f"rs_{len(requests)}",
                                        "type": "reasoning",
                                        "summary": [],
                                        "content": [
                                            {"type": "reasoning_text", "text": thought}
                                        ],
                                    }
                                ),
                                {
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [
                                        {"type": "output_text", "text": "pass"}
                                    ],
                                },
                            ],
                            usage={"input_tokens": 100, "output_tokens": 10},
                        )
                    return NS(
                        choices=[
                            NS(
                                message=ChatCompletionMessage(
                                    role="assistant",
                                    content="pass",
                                    reasoning_content=thought,
                                )
                            )
                        ],
                        usage={"prompt_tokens": 100, "completion_tokens": 10},
                    )

                def client():
                    transport = (
                        NS(responses=NS(create=create))
                        if responses
                        else NS(chat=NS(completions=NS(create=create)))
                    )
                    return ConversationClient(
                        transport,
                        APIConversation(api.name, player.model, name, 1, wire),
                    )

                current = client()
                for move in (1, 3, 5):
                    if move == 5:
                        current = client()  # Rebuild from the durable raw ledger.
                    output, _, _ = arena._call_llm_move(
                        current,
                        f"Move {move}\nLegal moves now: pass",
                        player_name=name,
                        log_path=Path(tmp) / "calls.jsonl",
                        game_number=1,
                        move_number=move,
                        attempt=1,
                    )
                    self.assertEqual(output, "pass")
                for index, request in enumerate(requests):
                    self.assertEqual(len(request["tools"]), 1)
                    self.assertEqual(request["tool_choice"], "none")
                    if responses:
                        thoughts = [
                            item["content"][0]["text"]
                            for item in request["input"]
                            if item.get("type") == "reasoning"
                        ]
                    else:
                        thoughts = [
                            item["reasoning_content"]
                            for item in request["messages"]
                            if item.get("role") == "assistant"
                        ]
                    self.assertEqual(
                        thoughts, [f"retained reasoning {i + 1}" for i in range(index)]
                    )


if __name__ == "__main__":
    unittest.main()
