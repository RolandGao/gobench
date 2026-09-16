"""Published pricing boundaries and usage accounting, without API requests."""

import datetime as dt
import unittest
from unittest.mock import patch

import arena


class PricingTests(unittest.TestCase):
    def test_current_rates_for_every_registered_model_and_harness(self):
        rates = {
            "gpt-5.4": (2.5, .25, 15),
            "gpt-5.5": (5, .5, 30),
            "gpt-5.6-sol": (4, .4, 20),
            "gpt-5.6-luna": (.2, .02, 1.2),
            "gpt-6-astra": (10, 1, 50),
            "muse-spark-1.2": (1.25, .15, 4.25),
            "muse-spark-1.3-contributor": (.1, .002, .2),
            "grok-4.5": (2, .3, 6),
            "grok-4.6": (2, .5, 6),
            "deepseek-v4-flash": (.22, .007, .66),
            "deepseek-flash": (.15, .003, .6),
            "deepseek-v4-pro": (.66, .022, 1.98),
            "qwen/qwen3.8-max": (2, .25, 6),
            "moonshotai/kimi-k3": (3, .3, 15),
            "meta/muse-spark-1.2": (1.25, .15, 4.25),
            "gemini-3.6-flash": (.75, .075, 3.75),
            "gemini-3.8-flash": (.75, .075, 3.75),
            "gemini-3.1-pro-preview": (2, .2, 12),
            "claude-opus-5": (5, .5, 25),
        }
        for api in arena._Arena.LLM_APIS:
            for name, player in api.players.items():
                with self.subTest(player=name):
                    self.assertEqual(player.prices, rates[player.model])

    def test_deepseek_weekdays_hours_and_timezones(self):
        cases = {
            "2026-09-07T00:59:59Z": False,
            "2026-09-07T01:00:00Z": True,
            "2026-09-07T03:59:59Z": True,
            "2026-09-07T04:00:00Z": False,
            "2026-09-07T05:59:59Z": False,
            "2026-09-07T06:00:00Z": True,
            "2026-09-07T09:59:59Z": True,
            "2026-09-07T10:00:00Z": False,
            "2026-09-11T06:00:00Z": True,
            "2026-09-12T06:00:00Z": False,
            "2026-09-13T06:00:00Z": False,
            "2026-09-07T09:00:00+08:00": True,
            "2026-09-06T21:00:00-04:00": True,
            "2026-09-07T01:00:00": True,
            None: False,
            "invalid": False,
        }
        for provider, model, prices in (
            ("deepseek_responses", "deepseek-v4-flash", (.22, .007, .66)),
            ("deepseek_responses", "deepseek-flash", (.15, .003, .6)),
            ("deepseek", "deepseek-v4-pro", (.66, .022, 1.98)),
        ):
            api = arena._llm_api_config(provider)
            for instant, peak in cases.items():
                with self.subTest(provider=provider, instant=instant):
                    usage = ({"input_tokens": 100, "output_tokens": 20,
                              "input_tokens_details": {"cached_tokens": 40}}
                             if provider.endswith("responses") else
                             {"prompt_tokens": 100, "completion_tokens": 20,
                              "prompt_cache_hit_tokens": 40})
                    expected = (60 * prices[0] + 40 * prices[1] + 20 * prices[2])
                    self.assertAlmostEqual(
                        arena._llm_call_cost(usage, api.name, model, started_at=instant),
                        expected * (2 if peak else 1) / 1e6,
                    )

    def test_context_tiers_include_cached_input_and_all_output(self):
        cases = (
            ("openai", "gpt-5.4", 272001, (2.5, .25, 15), (5, .5, 22.5)),
            ("openai", "gpt-5.5", 272001, (5, .5, 30), (10, 1, 45)),
            ("openai", "gpt-5.6-sol", 272001, (4, .4, 20), (8, .8, 30)),
            ("openai", "gpt-6-astra", 272001, (10, 1, 50), (20, 2, 75)),
            ("openai_codex_workspace", "gpt-5.6-luna", 272001, (.2, .02, 1.2), (.4, .04, 1.8)),
            ("xai", "grok-4.5", 200000, (2, .3, 6), (4, .6, 12)),
            ("xai", "grok-4.6", 200000, (2, .5, 6), (4, 1, 12)),
            ("google", "gemini-3.1-pro-preview", 200001, (2, .2, 12), (4, .4, 18)),
        )
        for provider, model, threshold, short, long in cases:
            for inputs in (threshold - 1, threshold, threshold + 1):
                with self.subTest(model=model, inputs=inputs):
                    usage = {"input_tokens": inputs, "output_tokens": 100,
                             "input_tokens_details": {"cached_tokens": inputs - 10},
                             "output_tokens_details": {"reasoning_tokens": 60}}
                    if provider == "google":
                        usage = {"total_input_tokens": inputs,
                                 "total_cached_tokens": inputs - 10,
                                 "total_output_tokens": 40, "total_thought_tokens": 60}
                    inp, cached, out = short if inputs < threshold else long
                    self.assertAlmostEqual(
                        arena._llm_call_cost(usage, provider, model),
                        (10 * inp + (inputs - 10) * cached + 100 * out) / 1e6,
                    )

    def test_gemini_discount_expiry_uses_utc_request_date(self):
        usage = {"total_input_tokens": 100, "total_cached_tokens": 40,
                 "total_output_tokens": 10, "total_thought_tokens": 20}
        discounted = (60 * .75 + 40 * .075 + 30 * 3.75) / 1e6
        for instant, factor in (
            ("2026-12-31T23:59:59Z", 1),
            ("2027-01-01T00:00:00Z", 2),
            ("2027-01-01T07:00:00+08:00", 1),
            ("2026-12-31T20:00:00-04:00", 2),
            (dt.datetime(2027, 1, 1), 2),
        ):
            with self.subTest(instant=instant):
                self.assertAlmostEqual(arena._llm_call_cost(
                    usage, "google", "gemini-3.6-flash", started_at=instant
                ), discounted * factor)
        class FutureDatetime(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2027, 1, 1, tzinfo=tz)

        with patch.object(arena.dt, "datetime", FutureDatetime):
            self.assertAlmostEqual(arena._llm_call_cost(
                usage, "google", "gemini-3.6-flash"
            ), discounted * 2)

    def test_openai_cache_writes_replace_ordinary_input_charge(self):
        for provider in ("openai", "openai_codex_workspace"):
            for model, inp, cached, write, out in (
                ("gpt-5.6-sol", 4, .4, 5, 20),
                ("gpt-5.6-luna", .2, .02, .25, 1.2),
            ):
                if provider == "openai" and model.endswith("luna"):
                    continue
                for inputs in (1000, 272001):
                    with self.subTest(provider=provider, model=model, inputs=inputs):
                        usage = {"input_tokens": inputs, "output_tokens": 100,
                                 "input_tokens_details": {"cached_tokens": 100,
                                                          "cache_write_tokens": 800}}
                        factor = 2 if inputs > 272000 else 1
                        output_factor = 1.5 if inputs > 272000 else 1
                        expected = ((inputs - 900) * inp + 100 * cached + 800 * write) * factor
                        self.assertAlmostEqual(arena._llm_call_cost(usage, provider, model),
                                               (expected + 100 * out * output_factor) / 1e6)

    def test_anthropic_cache_writes_remain_separate(self):
        usage = {"input_tokens": 100, "cache_read_input_tokens": 200,
                 "cache_creation_input_tokens": 300, "output_tokens": 50}
        self.assertAlmostEqual(arena._llm_call_cost(usage, "anthropic", "claude-opus-5"),
                               (100 * 5 + 200 * .5 + 300 * 6.25 + 50 * 25) / 1e6)

    def test_harness_cache_write_usage_survives_normalization_and_aggregation(self):
        codex = arena._CodexGameClient._response_usage({
            "input_tokens": 1500, "cached_input_tokens": 400,
            "cache_write_input_tokens": 600, "output_tokens": 50,
            "reasoning_output_tokens": 20,
        })
        self.assertEqual(codex["input_tokens"], 1500)
        self.assertEqual(codex["input_tokens_details"]["cache_write_tokens"], 600)
        combined = arena._sum_response_usages([codex, codex])
        self.assertEqual(combined["input_tokens_details"]["cache_write_tokens"], 1200)
        self.assertAlmostEqual(arena._llm_call_cost(combined, "openai_codex_workspace", "gpt-5.6-sol"),
                               2 * (500 * 4 + 400 * .4 + 600 * 5 + 50 * 20) / 1e6)
        compact = arena._compact_llm_call({"provider": "openai_codex_workspace",
                                          "model": "gpt-5.6-sol", "usage": combined})
        self.assertEqual(compact["cache_write_tokens"], 1200)

    def test_requests_are_priced_before_aggregation(self):
        requests = [{"input_tokens": 150000, "output_tokens": 1000}] * 2
        self.assertAlmostEqual(arena._llm_call_cost(
            arena._sum_response_usages(requests), "openai_codex_workspace", "gpt-5.6-sol"
        ), 1.24)


if __name__ == "__main__":
    unittest.main()
