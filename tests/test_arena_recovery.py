"""Exercise interrupted execution and request-level agent cost accounting."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import arena


def empty_game():
    state = NS(size=9, rows=["." * 9] * 9, to_move="B")
    return NS(get_possible_moves=lambda: (["pass"], []),
              get_board_state=lambda: state, get_move_history=lambda: ())


class RecoveryTests(unittest.TestCase):
    def test_transient_outage_longer_than_old_retry_limit_recovers_same_move(self):
        error = RuntimeError("unexpected status 502 Bad Gateway: OpenAI proxy request failed")
        usage = {"input_tokens": 100, "output_tokens": 10}
        error.arena_usage = usage
        response = NS(output_text="pass", usage=usage)
        create = mock.Mock(side_effect=[error] * 10 + [response])
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 0),
            mock.patch.object(arena.time, "sleep") as sleep,
        ):
            path = Path(tmp) / "calls.jsonl"
            output, _, cost = arena._call_llm_move(
                NS(responses=NS(create=create)), "Legal moves now: pass",
                player_name="gpt5.6-sol-high-api", log_path=path,
                compact_log_path=Path(tmp) / "compact.jsonl",
                game_number=1, move_number=7, attempt=1,
            )
            entries = arena._read_jsonl_objects(path, "calls")
            compact = arena._read_jsonl_objects(Path(tmp) / "compact.jsonl", "calls")
        self.assertEqual(output, "pass")
        self.assertEqual(sleep.call_count, 10)
        self.assertEqual(len(entries), 11)
        self.assertTrue(all(call == create.call_args_list[0] for call in create.call_args_list))
        self.assertTrue(all(row["move"] == 7 and row["attempt"] == 1 for row in entries))
        self.assertEqual(compact[0]["http_status"], 502)
        self.assertEqual(compact[0]["recovery_action"], "retry")
        self.assertAlmostEqual(cost, sum(row["cost_usd"] for row in entries))
        self.assertGreater(cost, 0)

    def test_finite_retry_limit_and_auth_rejection_still_stop(self):
        for status, expected_calls, action in (
            (502, 2, "retry_limit_reached"),
            (401, 1, "renew_login_then_resume"),
            (400, 1, "inspect_error_then_resume"),
            (404, 1, "inspect_error_then_resume"),
        ):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as tmp,
                mock.patch.object(arena._Arena, "LLM_API_MAX_ATTEMPTS", 2),
                mock.patch.object(arena.time, "sleep"),
            ):
                create = mock.Mock(side_effect=RuntimeError(f"unexpected status {status} failure"))
                path = Path(tmp) / "calls.jsonl"
                with self.assertRaises(arena.ArenaError) as raised:
                    arena._call_llm_move(
                        NS(responses=NS(create=create)), "Legal moves now: pass",
                        player_name="gpt5.6-sol-high-api", log_path=path,
                        game_number=1, move_number=1, attempt=1,
                    )
                self.assertEqual(create.call_count, expected_calls)
                self.assertEqual(arena._read_jsonl_objects(path, "calls")[-1]["recovery_action"], action)
                if status == 401:
                    self.assertIn("codex login", str(raised.exception))

    def test_retry_delay_stays_bounded_after_many_failures_and_honors_provider(self):
        with (
            mock.patch.object(arena._Arena, "LLM_API_RETRY_INITIAL_SECONDS", 2),
            mock.patch.object(arena._Arena, "LLM_API_RETRY_MAX_SECONDS", 60),
            mock.patch.object(arena._Arena, "LLM_API_RETRY_JITTER_FRACTION", 0),
        ):
            error = RuntimeError("transient")
            self.assertEqual(arena._llm_api_retry_delay(error, 100000), 60)
            error.response = NS(headers={"retry-after": "14400"})
            self.assertEqual(arena._llm_api_retry_delay(error, 100000), 14400)

    def test_claude_rejected_refresh_explains_manual_recovery(self):
        from gobench.anthropic_oauth import ClaudeOAuthError

        error = ClaudeOAuthError("Claude OAuth refresh failed (HTTP 403); sign in again if expired")
        hint = arena._llm_auth_recovery_hint(error, NS(name="anthropic_oauth"))
        self.assertFalse(arena._retryable_llm_api_error(error))
        self.assertIn("sign in with Claude Code", hint)
        self.assertIn("--resume", hint)

    def test_native_batch_resumes_before_manifest_was_written(self):
        slots = [arena.ScheduledGame(1, 1, "black", "white"),
                 arena.ScheduledGame(2, 1, "white", "black")]
        bots = [arena.Player(name, Path("/fake-model")) for name in ("black", "white")]

        def finish(slate, _bots, work, *, attempt, max_moves, progress):
            path = arena._native_attempt_paths(work, attempt)[2]
            path.mkdir()
            (path / "games.sgfs").write_text("\n".join(
                f"(;PB[{slot.black}]PW[{slot.white}]RE[B+R])" for slot in slate
            ))
            return path

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(arena._State, "katago_mode", True),
            mock.patch.object(arena._State, "katago_backend", "cuda"),
            mock.patch.object(arena, "_ensure_game_dependencies"),
        ):
            work = Path(tmp) / "batch-001"
            with mock.patch.object(arena, "run_native_games", side_effect=OSError):
                with self.assertRaises(OSError):
                    arena.play_batch(slots, bots, work)
            self.assertTrue((work / "schedule.json").exists())
            self.assertFalse((work / "native-chunks.json").exists())
            with mock.patch.object(arena, "_run_native_attempt", side_effect=finish):
                slate, records = arena.recover_batch(work, bots)
            self.assertEqual(slate, slots)
            self.assertEqual([record.number for record in records], [1, 2])
            self.assertTrue((work / "native-chunks.json").exists())

    def test_recovery_restores_compact_record_once_and_preserves_other_games(self):
        name = "DeepSeek-V4-Flash-0731-high-api-multi"
        api, player = arena._llm_player_config(name)
        create = mock.Mock(return_value=NS(
            output_text="resign", output=[{"role": "assistant", "content": "resign"}],
            usage={"input_tokens": 100, "output_tokens": 10},
        ))

        def client():
            return arena.ConversationClient(NS(responses=NS(create=create)),
                arena.APIConversation(api.name, player.model, name, 1, "responses"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, compact = root / "raw.jsonl", root / "llm_calls.jsonl"
            other = {"game": 99, "ok": False}
            arena._append_jsonl(compact, other)
            append = arena._append_jsonl

            def interrupted_append(path, *args, **kwargs):
                if path == compact:
                    raise OSError("interrupted compact write")
                return append(path, *args, **kwargs)

            opts = dict(player_name=name, log_path=raw, compact_log_path=compact,
                        game_number=1, move_number=1, attempt=1)
            with mock.patch.object(
                arena, "_append_jsonl", side_effect=interrupted_append
            ):
                with self.assertRaises(OSError):
                    arena._call_llm_move(client(), "Legal moves now: resign", **opts)
            for _ in range(2):
                self.assertEqual(
                    arena._call_llm_move(client(), "Legal moves now: resign", **opts),
                    ("resign", 0.0, 0.0),
                )
            self.assertEqual(create.call_count, 1)
            entries = arena._read_jsonl_objects(compact, "compact calls")
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0], other)
            self.assertGreater(arena._repriced_past_llm_costs(root)[1][0], 0)

    def test_completed_batch_repairs_a_partial_compact_write(self):
        name = "DeepSeek-V4-Flash-0731-high-api-multi"
        slot = arena.ScheduledGame(1, 1, name, arena._Arena.ANCHOR)
        record = arena._finished_record(
            slot, NS(ended=True, score="W+R", reason="resignation"),
            (("B", "resign"),), "deepseek_responses_api",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            call = dict(
                game=1, move=1, attempt=1, player=name, provider="deepseek_responses",
                request={"model": "deepseek-v4-flash",
                         "input": "Legal moves now: resign"},
                ok=True, output="resign",
                usage={"input_tokens": 100, "output_tokens": 10},
            )
            arena._append_jsonl(root / "llm-calls.jsonl", call)
            arena._append_jsonl(
                root / "llm-games.jsonl",
                arena._game_entry(record, numbered_moves=False),
            )
            compact = root / "llm_calls.jsonl"
            compact.write_text('{"game":1,"ok":tr')
            with mock.patch.object(arena, "_ensure_game_dependencies") as dependencies:
                result = arena.run_llm_games(
                    [slot], [arena.Player(arena._Arena.ANCHOR, None)], root,
                    compact_calls_path=compact, progress=None,
                )
            dependencies.assert_not_called()
            self.assertEqual(result, [record])
            self.assertEqual(arena._read_jsonl_objects(compact, "calls"),
                             [arena._compact_llm_call(call)])
            arena._write_results(root / "results.csv", result)
            (root / "run.json").write_text(json.dumps(dict(
                arena_log_schema_version=4, completed_games=1,
                games_scope="current_run",
                board_size=arena._Arena.BOARD_SIZE, komi=arena._Arena.KOMI,
                rules=arena._Arena.RULES,
            )))
            past = arena._load_past_games([root], [name, arena._Arena.ANCHOR])
            self.assertEqual(len(past), 1)
            self.assertGreater(past[0].llm_cost_usd, 0)


class AgentCostTests(unittest.TestCase):
    def codex_thread(self, inputs):
        from openai_codex.generated.v2_all import (
            ItemCompletedNotification,
            ThreadTokenUsageUpdatedNotification,
            TurnCompletedNotification,
        )

        def stream():
            total_input = total_output = 0
            for input_tokens in inputs:
                total_input += input_tokens
                total_output += 1000

                def counts(inp, out):
                    return dict(input_tokens=inp, output_tokens=out,
                                cached_input_tokens=0, reasoning_output_tokens=0,
                                total_tokens=inp + out)

                payload = ThreadTokenUsageUpdatedNotification(
                    thread_id="thread", turn_id="turn",
                    token_usage=dict(last=counts(input_tokens, 1000),
                                     total=counts(total_input, total_output)),
                )
                # Duplicate notifications must not double the estimated cost.
                for _ in range(2):
                    yield NS(method="thread/tokenUsage/updated", payload=payload)
            yield NS(method="item/completed", payload=ItemCompletedNotification(
                thread_id="thread", turn_id="turn", completed_at_ms=0,
                item=dict(type="agentMessage", id="message",
                          phase="final_answer", text="pass"),
            ))
            yield NS(method="turn/completed", payload=TurnCompletedNotification(
                thread_id="thread", turn=dict(id="turn", status="completed", items=[]),
            ))

        return NS(id="thread",
                  turn=lambda *args, **kwargs: NS(id="turn", stream=stream))

    def test_codex_prices_individual_requests_including_mixed_tiers(self):
        for inputs in ((150000, 150000), (300000, 150000)):
            with self.subTest(inputs=inputs), tempfile.TemporaryDirectory() as tmp:
                name = "gpt5.6-sol-high-codex-0h"
                api, player = arena._llm_player_config(name)
                client = arena._CodexGameClient.__new__(arena._CodexGameClient)
                client.player_name, client.player, client.game_number = name, player, 1
                client.agentic_harness = player.agentic_harness
                client.cwd = Path(tmp)
                client.state_path = Path(tmp) / "thread.json"
                client._usage_total = client._zero_usage()
                client._start_runtime = lambda: None
                client._thread_options = lambda: {}
                client._sdk = NS(Sandbox=NS(full_access="full"),
                                 ApprovalMode=NS(deny_all="deny"))
                client._thread = self.codex_thread(inputs)
                output, _, cost = arena._call_llm_move(
                    client, "Legal moves now: pass", player_name=name,
                    log_path=Path(tmp) / "calls.jsonl", game_number=1, move_number=1,
                    attempt=1,
                )
                expected = sum(arena._llm_call_cost(
                    {"input_tokens": inp, "output_tokens": 1000}, api.name, player.model
                ) for inp in inputs)
                self.assertEqual(output, "pass")
                self.assertAlmostEqual(cost, expected)
                entry = arena._read_jsonl_objects(Path(tmp) / "calls.jsonl", "calls")[0]
                usage = entry["usage"]
                self.assertEqual(usage["input_tokens"], sum(inputs))
                self.assertEqual(len(usage["request_usages"]), 2)


if __name__ == "__main__":
    unittest.main()
