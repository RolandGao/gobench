import dataclasses
import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import arena
from gobench import strategies


def _fake_codex_run_turn(_client, thread, prompt, **options):
    """Keep transport doubles for tests of harness setup and lifecycle."""
    return thread.run(prompt, **options), []


class ConfigurationSurfaceTests(unittest.TestCase):
    def test_cli_help_advertises_run_selection_options(self):
        result = subprocess.run(
            [sys.executable, arena.__file__, "--help"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ("--resume", "--run-type", "--summary", "--num-games"):
            with self.subTest(option=option):
                self.assertIn(option, result.stdout)

    def test_run_type_uses_source_config_without_reading_run_metadata(self):
        name = next(iter(arena.RUN_TYPES))
        with (
            mock.patch.object(arena, "_read_run_config") as read_config,
            mock.patch.object(arena, "_configure") as configure,
            mock.patch.object(arena, "run_arena", return_value=Path("new-run")),
            mock.patch("builtins.print"),
        ):
            result = arena.main(["--run-type", name])

        self.assertEqual(result, 0)
        read_config.assert_not_called()
        configure.assert_called_once_with(arena.RUN_TYPES[name])

    def test_game_target_override_for_new_runs(self):
        name = next(iter(arena.RUN_TYPES))
        for args, config in (([], arena.CONFIG),
                             (["--run-type", name], arena.RUN_TYPES[name])):
            with (self.subTest(args=args),
                  mock.patch.object(arena, "_configure") as configure,
                  mock.patch.object(arena, "run_arena", return_value=Path("new-run")),
                  mock.patch("builtins.print")):
                self.assertEqual(arena.main([*args, "--num-games", "30"]), 0)
                configure.assert_called_once_with(replace(config, total_games=30))

    def test_invalid_game_target_arguments_fail_before_launch(self):
        for args in (["--resume", "example", "-n", "-1"],
                     ["--resume", "example", "-n", "1.5"],
                     ["--summary", "-n", "30"]):
            with (self.subTest(args=args),
                  mock.patch.object(arena, "_resume_runs") as resume,
                  mock.patch.object(arena, "run_arena") as run,
                  mock.patch("sys.stderr"),
                  self.assertRaises(SystemExit) as error):
                arena.main(args)
            self.assertEqual(error.exception.code, 2)
            resume.assert_not_called()
            run.assert_not_called()

    def test_saved_katago_gain_top_p_is_loaded_from_batch_policy(self):
        active = (arena._MULTI_PLAYOUT_PLAYER_POOL[0],)
        metadata = {
            "arena_log_schema_version": 4,
            "arena_players": [arena._Arena.ANCHOR, *active],
            "active_players": list(active),
            "opponent_players": [arena._Arena.ANCHOR, *active],
            "ignore_players": ["hidden-player"],
            "total_games": 20,
            "past_run_dirs": [],
            "katago_backend": "cuda",
            "active_player_prior_elo_mean": 4_200.0,
            "active_player_prior_elo_sd": 500.0,
            "batch_policy": {
                "games_per_batch": 2,
                "selection_top_p": 0.8,
            },
        }

        config = arena._config_from_metadata(metadata)

        self.assertEqual(config.katago_gain_top_p, 0.8)
        self.assertEqual(config.ignore_players, ("hidden-player",))

    def test_resume_config_rejects_old_metadata_schema(self):
        with self.assertRaisesRegex(arena.ArenaError, "schema_version 4"):
            arena._config_from_metadata(
                {
                    "arena_log_schema_version": 2,
                    "players": [arena._Arena.ANCHOR],
                    "kata_bots_only": True,
                    "total_games": 0,
                }
            )

    def test_reports_omit_matchmaking_details(self):
        paths = {
            "ratings_path": Path("ratings.txt"),
            "api_comparisons_path": Path("api-comparisons.txt"),
            "all_comparisons_path": Path("all-comparisons.txt"),
            "matchup_path": Path("matchups.txt"),
            "all_llm_matchup_path": Path("all-llm-matchups.txt"),
        }

        with mock.patch.object(arena._State, "katago_mode", False):
            llm_sections = arena._arena_report_sections(
                has_llm_comparisons=True, **paths
            )
        with mock.patch.object(arena._State, "katago_mode", True):
            katago_sections = arena._arena_report_sections(
                has_llm_comparisons=False, **paths
            )

        self.assertEqual(
            [title for title, _path in llm_sections],
            [
                "Elo ratings",
                "API-only LLM comparisons",
                "All LLM comparisons",
                "Active-player matchup results",
                "All LLM matchup results",
            ],
        )
        self.assertEqual(
            [title for title, _path in katago_sections],
            ["Elo ratings"],
        )

    def test_empty_llm_comparison_table_is_written_for_katago_only_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_comparisons.txt"

            arena._write_llm_comparisons(path, [], [])

            report = path.read_text(encoding="utf-8")
        self.assertTrue(report.startswith("LLM comparisons\nRank"))
        self.assertIn("Cost per move", report)

    def test_api_only_comparisons_exclude_agentic_harnesses(self):
        api_player = "gpt5.6-sol-high-api"
        codex_player = "gpt5.6-sol-high-codex-0h"
        trained_player = "gpt5.6-sol-high-codex-1h"
        records = [
            arena.RatingRecord(api_player, 300.0, 290.0, 310.0, 20.0, 2, 2, 0, 0),
            arena.RatingRecord(codex_player, 200.0, 190.0, 210.0, 20.0, 2, 1, 1, 0),
            arena.RatingRecord(trained_player, 100.0, 90.0, 110.0, 20.0, 2, 0, 2, 0),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api_path = root / "api.txt"
            all_path = root / "all.txt"
            arena._write_llm_comparisons(
                api_path,
                [],
                records,
                title="API-only LLM comparisons",
                include_players=arena._Arena.RESULT_API_LLM_PLAYER_SET,
            )
            arena._write_llm_comparisons(
                all_path, [], records, title="All LLM comparisons"
            )
            api_text = api_path.read_text(encoding="utf-8")
            all_text = all_path.read_text(encoding="utf-8")

        self.assertIn(api_player, api_text)
        self.assertNotIn(codex_player, api_text)
        self.assertNotIn(trained_player, api_text)
        self.assertIn(api_player, all_text)
        self.assertIn(codex_player, all_text)
        self.assertIn(trained_player, all_text)

    def test_comparison_token_rates_include_retries_and_normalize_provider_input(self):
        player = "gpt5.6-sol-high-api"
        game = arena.GameRecord(
            1, 1, player, arena._Arena.ANCHOR, "B+R", "B", player, 1.0,
            "resign", (("B", "D4"), ("W", "pass"), ("B", "pass")), "test", "",
        )
        rating = arena.RatingRecord(player, 100, 90, 110, 20, 1, 1, 0, 0)
        calls = [
            {"game": 1, "provider": "openai", "input_tokens": 100,
             "cached_input_tokens": 60, "output_tokens": 20, "ok": True},
            {"game": 1, "provider": "anthropic", "ok": False,
             "usage": {"input_tokens": 10, "cache_read_input_tokens": 30,
                       "cache_creation_input_tokens": 10, "output_tokens": 10}},
            {"game": 2, "provider": "openai", "input_tokens": 999,
             "cached_input_tokens": 999, "output_tokens": 999},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "llm_calls.jsonl").write_text(
                "".join(json.dumps(call) + "\n" for call in calls), encoding="utf-8",
            )
            games = arena._with_llm_token_counts([game], root)
            row = arena._llm_comparison_records(games, [rating])[0]
            arena._write_llm_comparisons(root / "table.txt", games, [rating])
            report = (root / "table.txt").read_text()
        self.assertEqual(games[0].llm_input_tokens, 150)
        self.assertEqual(row["cached_input_rate"], 0.6)
        self.assertEqual(row["output_tokens_per_move"], 15)
        self.assertIn("Cached input rate", report)
        self.assertIn("60.00%", report)
        self.assertIn("Output tokens per move", report)
        self.assertIn("15.00", report)
        missing = arena._llm_comparison_records([game], [rating])[0]
        self.assertIsNone(missing["cached_input_rate"])
        self.assertIsNone(missing["output_tokens_per_move"])

    def test_all_llm_matchup_results_are_grouped_by_llm(self):
        stronger = "gpt5.6-sol-high-api"
        weaker = "gpt-5.4-low-api"
        high_opponent = "kata1-high"
        low_opponent = arena._Arena.ANCHOR
        records = [
            arena.RatingRecord(stronger, 300.0, 290.0, 310.0, 3.0, 3, 2, 1, 0),
            arena.RatingRecord(weaker, 200.0, 190.0, 210.0, 1.0, 1, 0, 1, 0),
            arena.RatingRecord(high_opponent, 100.0, 80.0, 120.0, 2.0, 2, 0, 2, 0),
            arena.RatingRecord(low_opponent, 0.0, -30.0, 30.0, 2.0, 2, 1, 1, 0),
        ]
        games = [
            arena.GameRecord(
                1, 1, stronger, low_opponent, "B+R", "B", stronger, 1.0,
                "resign", (), "test", "",
            ),
            arena.GameRecord(
                2, 1, high_opponent, stronger, "B+R", "B", high_opponent, 1.0,
                "resign", (), "test", "",
            ),
            arena.GameRecord(
                3, 1, low_opponent, stronger, "W+R", "W", stronger, 0.0,
                "resign", (), "test", "",
            ),
            arena.GameRecord(
                4, 1, weaker, high_opponent, "W+R", "W", high_opponent, 0.0,
                "resign", (), "test", "",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "all-llm-matchups.txt"
            arena._write_all_llm_matchup_results(path, games, records)
            text = path.read_text(encoding="utf-8")

        self.assertLess(text.index(f"LLM: {stronger}"), text.index(f"LLM: {weaker}"))
        stronger_group = text.split(f"LLM: {stronger}\n", 1)[1].split("\n\n", 1)[0]
        self.assertLess(
            stronger_group.index(high_opponent), stronger_group.index(low_opponent)
        )
        self.assertIn("0-1-0", stronger_group)
        self.assertIn("2-0-0", stronger_group)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "active.txt"
            config = replace(arena.CONFIG, active_players=(stronger,))
            with mock.patch.object(arena._State, "config", config):
                arena._write_matchup_results(path, games[:3], records)
            active_text = path.read_text()
        self.assertEqual(
            active_text.split(f"Active player: {stronger}\n", 1)[1].strip(),
            stronger_group.strip(),
        )

    def test_ignored_players_do_not_appear_in_report_sections(self):
        ignored = "gpt5.6-sol-low-codex-single"
        visible = "gpt-5.4-low-api"
        opponent = arena._Arena.ANCHOR
        records = [
            arena.RatingRecord(ignored, 100.0, 90.0, 110.0, 20.0, 2, 1, 1, 0),
            arena.RatingRecord(visible, 200.0, 190.0, 210.0, 20.0, 2, 2, 0, 0),
            arena.RatingRecord(opponent, 0.0, -10.0, 10.0, 20.0, 4, 1, 3, 0),
        ]
        games = [
            arena.GameRecord(
                1, 1, ignored, opponent, "B+R", "B", ignored, 1.0,
                "resign", (), "test", "",
            ),
            arena.GameRecord(
                2, 1, visible, opponent, "B+R", "B", visible, 1.0,
                "resign", (), "test", "",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ratings = root / "ratings.txt"
            comparisons = root / "all-comparisons.txt"
            matchups = root / "matchups.txt"
            report = root / "report.txt"
            arena._write_ratings(
                ratings, records, games=2, ignore_players=(ignored,)
            )
            arena._write_llm_comparisons(
                comparisons,
                games,
                records,
                title="All LLM comparisons",
                ignore_players=(ignored,),
            )
            config = replace(
                arena.CONFIG,
                active_players=(ignored, visible),
                ignore_players=(ignored,),
            )
            with mock.patch.object(arena._State, "config", config):
                arena._write_matchup_results(
                    matchups, games, records, ignore_players=(ignored,)
                )
            arena._write_report(
                report,
                [
                    ("Elo ratings", ratings),
                    ("All LLM comparisons", comparisons),
                    ("Active-player matchup results", matchups),
                ],
            )
            text = report.read_text(encoding="utf-8")

        self.assertNotIn(ignored, text)
        self.assertIn(visible, text)


class PlayoutPlayerTests(unittest.TestCase):
    def test_filtered_player_pools_partition_the_current_pool(self):
        pools = {
            name: set(getattr(arena, name))
            for name in (
                "_CURRENT_PLAYER_POOL",
                "_CHEAP_B6C96_PLAYER_POOL",
                "_NO_MULTI_PLAYOUT_PLAYER_POOL",
                "_MULTI_PLAYOUT_PLAYER_POOL",
            )
        }
        current = pools["_CURRENT_PLAYER_POOL"]
        no_multi = pools["_NO_MULTI_PLAYOUT_PLAYER_POOL"]
        multi = pools["_MULTI_PLAYOUT_PLAYER_POOL"]
        cheap = pools["_CHEAP_B6C96_PLAYER_POOL"]

        self.assertTrue(
            all("kata1-zhizi-b40c768nbt-fdx6c" not in pool for pool in pools.values())
        )
        self.assertEqual(
            {name for name in current if "-temp-" in name},
            set(arena._TEMPERATURE_PLAYER_POOL),
        )
        self.assertEqual(no_multi | multi, current)
        self.assertFalse(no_multi & multi)
        self.assertTrue(cheap)
        self.assertLess(cheap, no_multi)
        self.assertTrue(all(name.startswith("kata1-b6c96-") for name in cheap))
        self.assertTrue(
            all((arena._player_playouts(name) or 1) <= 1 for name in no_multi)
        )
        self.assertTrue(
            all((arena._player_playouts(name) or 0) > 1 for name in multi)
        )
        self.assertTrue(
            all(
                name == arena._Arena.ANCHOR
                or arena._network_name_for_player(name)
                in arena._Arena.NETWORKS_BY_NAME
                for name in current
            )
        )

    def test_temperature_players_restore_their_named_move_temperatures(self):
        try:
            arena._configure(arena.RUN_TYPES["katago_cheap_only"])
            players = {player.name: player for player in arena.players()}
        finally:
            arena._configure(arena.CONFIG)

        low = players["kata1-b6c96-s4136960-d1510003-temp-0.3"]
        high = players["kata1-b6c96-s4136960-d1510003-temp-0.9"]
        self.assertEqual(
            (low.chosen_move_temperature_early, low.chosen_move_temperature),
            (0.5, 0.3),
        )
        self.assertEqual(
            (high.chosen_move_temperature_early, high.chosen_move_temperature),
            (0.9, 0.9),
        )

    def test_only_playout_runs_use_restricted_gain_nucleus(self):
        for config in arena.RUN_TYPES.values():
            playout_run = bool(config.active_players) and all(
                arena._player_playouts(name) in arena._Arena.KATAGO_PLAYOUT_COUNTS
                for name in config.active_players
            )
            self.assertEqual(config.katago_gain_top_p, 0.95 if playout_run else 1.0)
            self.assertEqual(config.katago_backend, "cuda" if playout_run else "cpu")

    def test_opponent_players_follow_the_derived_mode(self):
        for config in arena.RUN_TYPES.values():
            katago_mode = not any(
                arena._is_active_llm_player(name) for name in config.active_players
            )
            self.assertEqual(
                arena._active_players_are_katago(config.active_players), katago_mode
            )
            overlap = set(config.active_players) & set(config.opponent_players)
            expected_overlap = set(config.active_players) if katago_mode else set()
            self.assertEqual(overlap, expected_overlap)

    def test_every_run_type_includes_the_rating_anchor(self):
        for config in arena.RUN_TYPES.values():
            self.assertIn(arena._Arena.ANCHOR, config.opponent_players)

    def test_invalid_active_and_opponent_groups_are_rejected(self):
        with self.assertRaisesRegex(arena.ArenaError, "unknown active player.*gpt6-astra-high-workspace-isolated"):
            arena._active_players_are_katago(("gpt6-astra-high-workspace-isolated",))
        active = arena.CONFIG.active_players[0]
        overlap = replace(
            arena.CONFIG,
            opponent_players=(*arena.CONFIG.opponent_players, active),
        )
        with self.assertRaisesRegex(arena.ArenaError, "active LLM"):
            arena._configure(overlap)

        katago = arena.RUN_TYPES["60_and_600_playouts_katago"]
        missing_active = replace(
            katago,
            opponent_players=tuple(
                name
                for name in katago.opponent_players
                if name != katago.active_players[0]
            ),
        )
        with self.assertRaisesRegex(arena.ArenaError, "all active KataGo"):
            arena._configure(missing_active)

        with self.assertRaisesRegex(arena.ArenaError, "all KataGo players or all LLM"):
            arena._active_players_are_katago(
                (arena._CHEAP_B6C96_PLAYER_POOL[0], arena.CONFIG.active_players[0])
            )

    def test_regular_katago_arena_selects_cpu_binary(self):
        config = arena.RUN_TYPES["katago_only"]
        try:
            arena._configure(config)
            self.assertTrue(arena._State.katago_mode)
            self.assertEqual(arena._State.katago_backend, "cpu")
            self.assertEqual(arena._State.katago_binary, strategies.KATAGO_BINARY)
        finally:
            arena._configure(arena.CONFIG)

    def test_playout_arena_selects_cuda_binary(self):
        config = arena.RUN_TYPES["60_and_600_playouts_katago"]
        try:
            arena._configure(config)
            self.assertTrue(arena._State.katago_mode)
            self.assertEqual(arena._State.katago_backend, "cuda")
            self.assertEqual(arena._State.katago_binary, strategies.KATAGO_CUDA_BINARY)
        finally:
            arena._configure(arena.CONFIG)

    def test_invalid_katago_backend_is_rejected(self):
        with self.assertRaisesRegex(arena.ArenaError, "katago_backend"):
            arena._configure(replace(arena.CONFIG, katago_backend="metal"))

    def test_selected_networks_have_each_supported_playout_variant(self):
        networks = {network.name for network in arena._Arena.TOP_KATAGO_NETWORKS}
        self.assertTrue(networks)
        self.assertTrue(arena._Arena.KATAGO_PLAYOUT_COUNTS)
        self.assertCountEqual(
            [
                (arena._network_name_for_player(name), arena._player_playouts(name))
                for name in arena._Arena.KATAGO_ACTIVE_PLAYERS
            ],
            [
                (network, playouts)
                for network in networks
                for playouts in arena._Arena.KATAGO_PLAYOUT_COUNTS
            ],
        )

    def test_active_katago_players_use_requested_gaussian_prior(self):
        playout_config = arena.RUN_TYPES["60_and_600_playouts_katago"]
        regular_config = arena.RUN_TYPES["katago_only"]
        with (
            mock.patch.object(arena._State, "config", playout_config),
            mock.patch.object(arena._State, "past_player_priors", {}),
        ):
            self.assertEqual(
                arena._rating_prior(arena._Arena.KATAGO_ACTIVE_PLAYERS[0]),
                (4200, 500),
            )
        with (
            mock.patch.object(arena._State, "config", regular_config),
            mock.patch.object(arena._State, "past_player_priors", {}),
        ):
            self.assertEqual(
                arena._rating_prior(regular_config.active_players[0]),
                (0.0, 10_000.0),
            )

    def test_past_player_priors_come_from_their_introducing_runs(self):
        priors = arena._historical_player_priors(arena.CONFIG)

        self.assertEqual(
            priors[arena._CHEAP_B6C96_PLAYER_POOL[0]], (0.0, 10_000.0)
        )
        # The historical LLM runs are excluded while all LLMs are rerun.
        self.assertNotIn("gpt5.6-sol-high-api", priors)
        self.assertEqual(
            priors[arena._MULTI_PLAYOUT_PLAYER_POOL[0]], (4_200.0, 500.0)
        )

    def test_playout_suffix_resolves_to_base_network(self):
        player_name = (
            "kata1-b28c512nbt-s8566598912-d4691918754-playouts600"
        )
        self.assertEqual(arena._player_playouts(player_name), 600)
        self.assertEqual(
            arena._network_name_for_player(player_name),
            "kata1-b28c512nbt-s8566598912-d4691918754",
        )

    def test_match_config_uses_per_player_playout_limit(self):
        network = arena._Arena.TOP_KATAGO_NETWORKS[0]
        regular = arena.Player("regular", network.path, network.name, 0.5, 0.1)
        playout = arena.Player(
            "playouts600", network.path, network.name, 0.5, 0.1, 600
        )
        schedule = [arena.ScheduledGame(1, 1, regular.name, playout.name)]

        config = arena._match_config([regular, playout], schedule)

        self.assertIn("maxVisits = 1\n", config)
        self.assertNotIn("maxPlayouts0", config)
        self.assertIn("maxVisits1 = 100000000\n", config)
        self.assertIn("maxPlayouts1 = 600\n", config)

    def test_gtp_strategy_uses_new_playouts_and_disables_search_reductions(self):
        captured = {}

        class FakeGTPProcess:
            def __init__(self, args, *_paths):
                captured["args"] = args

            def command(self, _command):
                return ""

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            network = Path(tmp) / "network.bin.gz"
            network.touch()
            game = SimpleNamespace(
                komi=7.0,
                rules="tromp-taylor",
                get_board_state=lambda: SimpleNamespace(size=9),
            )
            player = strategies.KataGoNetworkStrategy(
                network,
                config_path=Path(tmp) / "config.cfg",
                log_dir=tmp,
                max_visits=arena._Arena.PLAYOUT_MAX_VISITS,
                max_playouts=600,
            )
            with mock.patch.object(strategies, "GTPProcess", FakeGTPProcess):
                player._start(game)

        override = captured["args"][-1]
        self.assertIn("maxVisits=100000000,", override)
        self.assertIn("maxPlayouts=600,", override)
        self.assertIn("searchFactorAfterOnePass=1,", override)
        self.assertIn("searchFactorAfterTwoPass=1,", override)
        self.assertIn("searchFactorWhenWinning=1,", override)


class LLMConfigurationAndRecoveryTests(unittest.TestCase):
    def test_all_anthropic_players_enable_caching_in_requests_and_manifests(self):
        for api in arena._Arena.LLM_APIS:
            if not issubclass(api.protocol, arena._AnthropicMessagesProtocol):
                continue
            for name, player in api.players.items():
                with self.subTest(player=name):
                    request = arena._llm_request(api, player, "prompt")
                    self.assertEqual(request["cache_control"], {"type": "ephemeral"})
                    self.assertEqual(arena._llm_player_manifest(name)["cache_control"],
                                     request["cache_control"])

    def test_output_limits_use_provider_fields_and_oauth_server_control(self):
        expected = {
            "openai": 128_000,
            "openai_codex_workspace": 128_000,
            "meta": 943_718,
            "xai": None,
            "deepseek_responses": 393_216,
            "deepseek": 393_216,
            "google": 65_536,
            "anthropic": 128_000,
        }
        for api in arena._Arena.LLM_APIS:
            for name, player in api.players.items():
                with self.subTest(player=name):
                    limit = (131_072 if player.route == "alibaba" else 943_718) if api.name == "openrouter" else expected[api.name]
                    self.assertEqual(player.max_output_tokens, limit)
                    request = arena._llm_request(api, player, "prompt")
                    manifest = arena._llm_player_manifest(name)
                    if api.max_tokens_field:
                        value, declared = request, manifest
                        for key in api.max_tokens_field.split("."):
                            value, declared = value[key], declared[key]
                        self.assertEqual(value, limit)
                        self.assertEqual(declared, limit)
                    else:
                        self.assertNotIn("max_output_tokens", request)
                        self.assertNotIn("max_tokens", request)
                        self.assertIn("output_limit_control", manifest)
                    if api.name == "google":
                        from pydantic import TypeAdapter
                        from google.genai._gaos.types.interactions.generationconfig import GenerationConfig
                        TypeAdapter(GenerationConfig).validate_python(request["generation_config"])

    def test_cached_prompt_blocks_keep_the_same_audit_digest(self):
        api, player = arena._llm_player_config("qwen3.8-max-high-api")
        request = arena._llm_request(api, player, "Legal moves: D4, pass")
        plain = request | {"messages": [{"role": "user", "content": "Legal moves: D4, pass"}]}
        self.assertEqual(arena._request_prompt_text(request), "Legal moves: D4, pass")
        entries = [arena._compact_llm_call({"provider": "openrouter", "request": req, "usage": {}})
                   for req in (request, plain)]
        self.assertEqual(entries[0]["prompt_sha256"], entries[1]["prompt_sha256"])

    def test_new_api_efforts_reach_requests_and_manifests(self):
        cases = (
            ("gpt-5.4-xhigh-api", "xhigh"),
            ("gpt-5.5-none-api", "none"),
            ("gpt5.6-sol-max-api", "max"),
            ("gpt5.6-luna-medium-api", "medium"),
            ("gpt6-astra-max-api", "max"),
            ("muse-spark-1.2-minimal-api", "minimal"),
            ("muse-spark-1.3-contributor-max-api", "max"),
            ("grok-4.5-xhigh-api", "xhigh"),
            ("grok-4.6-low-api", "low"),
            ("DeepSeek-V4-Flash-0731-minimal-api", "minimal"),
            ("DeepSeek-V4-Flash-0731-none-api", "none"),
            ("DeepSeek-V4.1-Flash-none-api", "none"),
            ("DeepSeek-V4.1-Flash-high-api", "high"),
            ("DeepSeek-V4.1-Flash-max-api", "max"),
            ("deepseek-v4-pro-max-api", "max"),
            ("qwen3.8-max-xhigh-api", "xhigh"),
            ("kimi-k3-max-api", "max"),
            ("muse-spark-1.2-openrouter-low-api", "low"),
            ("gemini-3.6-flash-minimal-api", "minimal"),
            ("gemini-3.8-flash-medium-api", "medium"),
            ("gemini-3.1-pro-low-api", "low"),
            ("opus-5-max-api", "max"),
            ("opus-5-xhigh-api", "xhigh"),
            ("claude-opus-5-5-high-api", "high"),
            ("fable-5.1-high-api", "high"),
            ("fable-5.1-xhigh-api", "xhigh"),
            ("fable-5.1-max-api", "max"),
        )
        for base_name, effort in cases:
            for suffix in ("", "-multi"):
                name = base_name + suffix
                with self.subTest(player=name):
                    self.assertIn(name, arena._Arena.ACTIVE_LLM_PLAYER_SET)
                    api, player = arena._llm_player_config(name)
                    request = arena._llm_request(api, player, "prompt")
                    if api.name == "openrouter":
                        actual = request["extra_body"]["reasoning"]["effort"]
                    elif api.name == "google":
                        actual = request["generation_config"]["thinking_level"]
                    elif api.name.startswith("anthropic"):
                        actual = request["output_config"]["effort"]
                    elif api.name == "deepseek":
                        actual = request["reasoning_effort"]
                    else:
                        actual = request["reasoning"]["effort"]
                    self.assertEqual(actual, effort)
                    manifest = arena._llm_player_manifest(name)
                    self.assertEqual(manifest[api.manifest_level_name], effort)

    def test_deepseek_nonthinking_chat_disables_thinking(self):
        for suffix in ("", "-multi"):
            name = "deepseek-v4-pro-none-api" + suffix
            with self.subTest(player=name):
                api, player = arena._llm_player_config(name)
                request = arena._llm_request(api, player, "prompt")
                self.assertEqual(
                    request["extra_body"]["thinking"], {"type": "disabled"}
                )
                self.assertNotIn("reasoning_effort", request)
                self.assertEqual(
                    arena._llm_player_manifest(name)["thinking"],
                    {"type": "disabled"},
                )

    def test_effort_expansion_preserves_legacy_deepseek_player(self):
        for suffix in ("", "-multi"):
            legacy_api, legacy = arena._llm_player_config(
                "deepseek-v4-pro-api" + suffix
            )
            api, player = arena._llm_player_config(
                "deepseek-v4-pro-high-api" + suffix
            )
            self.assertEqual(legacy, player)
            self.assertEqual(
                arena._llm_request(legacy_api, legacy, "prompt"),
                arena._llm_request(api, player, "prompt"),
            )

    def test_unsupported_api_efforts_are_not_registered(self):
        for name in (
            "gpt-5.4-max-api", "gpt-5.5-max-api", "gpt6-astra-none-api",
            "muse-spark-1.2-max-api", "grok-4.6-max-api",
            "deepseek-v4-pro-minimal-api", "qwen3.8-max-none-api",
            "kimi-k3-medium-api", "gemini-3.8-flash-minimal-api",
            "gemini-3.1-pro-minimal-api", "opus-5-none-api",
        ):
            for suffix in ("", "-multi"):
                with self.subTest(player=name + suffix):
                    self.assertNotIn(
                        name + suffix, arena._Arena.ACTIVE_LLM_PLAYER_SET
                    )

    def test_terminal_number_creates_equivalent_llm_player_aliases(self):
        players_and_suffixes = (
            ("gpt5.6-sol-low-api", "2"),
            ("gpt5.6-sol-low-codex-0h", "7"),
            ("gpt5.6-sol-low-codex-1h", "42"),
            ("DeepSeek-V4-Flash-0731-high-api", "9"),
        )

        for canonical, suffix in players_and_suffixes:
            with self.subTest(player=canonical):
                alias = f"{canonical}{suffix}"
                canonical_api, canonical_player = arena._llm_player_config(canonical)
                alias_api, alias_player = arena._llm_player_config(alias)
                self.assertIs(alias_api, canonical_api)
                self.assertIs(alias_player, canonical_player)
                self.assertTrue(arena._is_active_llm_player(alias))

                canonical_manifest = arena._llm_player_manifest(canonical)
                alias_manifest = arena._llm_player_manifest(alias)
                self.assertEqual(alias_manifest["name"], alias)
                self.assertEqual(
                    {key: value for key, value in alias_manifest.items() if key != "name"},
                    {
                        key: value
                        for key, value in canonical_manifest.items()
                        if key != "name"
                    },
                )

        self.assertEqual(
            arena._llm_game_worker_count(
                "gpt5.6-sol-low-codex-1h2", 8
            ),
            2,
        )
        with self.assertRaisesRegex(arena.ArenaError, "unknown LLM player"):
            arena._llm_player_config("not-a-player2")

    def test_move_prompt_uses_canonical_wording(self):
        state = SimpleNamespace(
            to_move="B",
            size=9,
            rows=["........."] * 9,
        )

        prompt = arena._llm_move_prompt(
            state,
            ["A1", "pass", "resign"],
            [],
        )

        self.assertEqual(
            prompt,
            "You are playing Black in an ongoing 9x9 Go game against another bot. "
            "It is Black to move.\n\n"
            "Rules: White komi 7.0, positional superko, "
            "passing allowed, self-capture of stones legal. "
            "Resolve captures by first removing opposing groups with no liberties, "
            "then removing any friendly groups with no liberties. "
            "Self-capture remains subject to positional superko. "
            "Resigning loses immediately. Two consecutive passes end the "
            "game. A draw is worth 0.5 points. Scoring uses strict Tromp-Taylor "
            "area scoring with no dead stone removal.\n\n"
            "Coordinates: columns A B C D E F G H J from left to right (I is "
            "skipped); rows 9 through 1 from top to bottom. B = Black, W = White, "
            "Z = empty.\n\n"
            "ABCDEFGHJ\n"
            "9 ZZZZZZZZZ\n"
            "8 ZZZZZZZZZ\n"
            "7 ZZZZZZZZZ\n"
            "6 ZZZZZZZZZ\n"
            "5 ZZZZZZZZZ\n"
            "4 ZZZZZZZZZ\n"
            "3 ZZZZZZZZZ\n"
            "2 ZZZZZZZZZ\n"
            "1 ZZZZZZZZZ\n\n"
            "Recent 5 moves (oldest to newest): none\n\n"
            "Currently illegal because of ko/superko: none\n\n"
            "Legal moves: A1, pass, resign\n\n"
            "Legal moves is authoritative for the current position and already accounts for ko and "
            "positional superko.\n\n"
            "Your entire final answer must be one entry copied exactly from Legal moves.\n"
            "Write that entry on a single line, then end the response immediately.",
        )

    def test_compact_call_ledger_omits_prompt_and_normalizes_usage(self):
        entry = {
            "game": 3,
            "move": 9,
            "attempt": 1,
            "provider": "openai",
            "request": {"model": "gpt-test", "input": "large repeated prompt"},
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 60},
                "output_tokens": 25,
                "output_tokens_details": {"reasoning_tokens": 20},
            },
            "ok": True,
            "output": "E5",
            "response_id": "provider-trace-id",
            "cost_usd": 0.25,
        }

        compact = arena._compact_llm_call(entry)

        self.assertNotIn("request", compact)
        self.assertNotIn("usage", compact)
        self.assertEqual(compact["input_tokens"], 100)
        self.assertEqual(compact["cached_input_tokens"], 60)
        self.assertEqual(compact["output_tokens"], 25)
        self.assertEqual(compact["reasoning_tokens"], 20)
        self.assertEqual(compact["output"], "E5")
        self.assertNotIn("response_id", compact)
        self.assertEqual(compact["schema_version"], 2)
        self.assertEqual(len(compact["prompt_sha256"]), 64)

    def test_anthropic_cache_reads_are_separate_from_uncached_input(self):
        usage = {
            "input_tokens": 50,
            "cache_read_input_tokens": 100_000,
            "cache_creation_input_tokens": 0,
            "output_tokens": 0,
        }

        cost = arena._llm_call_cost(usage, "anthropic", "claude-opus-5")
        compact = arena._compact_llm_call(
            {
                "provider": "anthropic",
                "request": {
                    "model": "claude-opus-5",
                    "messages": [{"role": "user", "content": "prompt"}],
                },
                "usage": usage,
                "ok": True,
            }
        )

        self.assertAlmostEqual(cost, (50 * 5.0 + 100_000 * 0.5) / 1e6)
        self.assertEqual(compact["input_tokens"], 50)
        self.assertEqual(compact["cached_input_tokens"], 100_000)

    def test_tracked_log_sanitizer_removes_identity_secrets_and_arbitrary_text(self):
        value = arena._sanitize_tracked_log_value(
            {
                "katago_binary": "/Users/private-name/tools/katago",
                "response_id": "provider-trace-id",
                "response_headers": {"set-cookie": "private-cookie"},
                "api_key": "private-key",
                "output": "My name is Private Person",
                "error": "ProviderError: private provider details",
            }
        )

        self.assertEqual(value["katago_binary"], "<external-path>")
        self.assertNotIn("response_id", value)
        self.assertNotIn("response_headers", value)
        self.assertEqual(value["api_key"], "<redacted>")
        self.assertEqual(value["output"], "<invalid-output>")
        self.assertEqual(value["error"], "ProviderError")

    def test_external_portable_path_does_not_publish_home_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "personal" / "katago"

            self.assertEqual(arena._portable_path(outside), "<external-path>")

    def test_raw_call_writer_drops_credentials_headers_and_provider_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calls.jsonl"
            arena._append_llm_call(
                path,
                None,
                {
                    "output": "debug prose stays in the ignored raw journal",
                    "response_id": "provider-trace-id",
                    "response_headers": {"set-cookie": "private-cookie"},
                    "request": {"api_key": "private-key"},
                },
            )
            saved = json.loads(path.read_text())

        self.assertEqual(
            saved["output"], "debug prose stays in the ignored raw journal"
        )
        self.assertNotIn("response_id", saved)
        self.assertNotIn("response_headers", saved)
        self.assertEqual(saved["request"]["api_key"], "<redacted>")

    def test_new_run_uses_visible_tracked_and_untracked_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tracked, untracked = root / "log", root / "untracked_log"
            with (
                mock.patch.object(arena._Arena, "ROOT", root),
                mock.patch.object(arena._Arena, "LOG_ROOT", tracked),
                mock.patch.object(arena._Arena, "UNTRACKED_LOG_ROOT", untracked),
            ):
                run, work, metadata, *_rest = arena._open_run(
                    None,
                    {
                        "legality_enforcement_version":
                            arena.LEGALITY_ENFORCEMENT_VERSION,
                    },
                    [], lambda _size: True, {}
                )

            self.assertEqual(run.parent, tracked)
            self.assertEqual(work.parent, untracked)
            self.assertEqual(
                metadata["untracked_log_dir"], str(work.relative_to(root))
            )
            self.assertNotIn("temporary_log_dir", metadata)
            self.assertEqual(metadata["legality_enforcement_version"], 1)

    def test_resume_rejects_legacy_or_different_legality_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for version in (None, 999):
                metadata = {"arena_log_schema_version": 4}
                if version is not None:
                    metadata["legality_enforcement_version"] = version
                (run / "run.json").write_text(json.dumps(metadata))
                with self.assertRaisesRegex(arena.ArenaError, "legality enforcement"):
                    arena._open_run(
                        run, {"legality_enforcement_version": 1}, [],
                        lambda _size: True, {},
                    )

    def test_resume_ignores_game_records_staged_after_the_last_metadata_commit(self):
        def record(number):
            return arena.GameRecord(
                number,
                number,
                arena._Arena.ANCHOR,
                "network-a",
                "W+R",
                "W",
                "network-a",
                0.0,
                "resignation",
                (),
                "test",
                "",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run, work = root / "log" / "arena_test", root / "work"
            run.mkdir(parents=True)
            work.mkdir()
            (run / "run.json").write_text(
                json.dumps(
                    {
                        "arena_log_schema_version": 4,
                        "untracked_log_dir": str(work),
                        "completed_games": 1,
                        "batch_sizes": [1],
                        "independent_player_batches": False,
                    }
                ),
                encoding="utf-8",
            )
            arena._write_game_records(
                work / "games.jsonl", [record(1), record(2)]
            )

            _run, _work, _metadata, completed, batch, *_rest = arena._open_run(
                run, {}, [], lambda size: size == 1, {}
            )

        self.assertEqual([game.number for game in completed], [1])
        self.assertEqual(batch, 1)

    def test_resume_compares_run_configuration_as_json_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run, work = root / "log" / "arena_test", root / "work"
            run.mkdir(parents=True)
            work.mkdir()
            run_config = {
                "arena_log_schema_version": 4,
                "legality_enforcement_version": 1,
                "independent_player_batches": False,
                "pricing": {"peak_utc_hours": ((1, 4), (6, 10))},
            }
            metadata = json.loads(json.dumps(run_config)) | {
                "untracked_log_dir": str(work),
                "completed_games": 0,
                "batch_sizes": [],
            }
            (run / "run.json").write_text(
                json.dumps(metadata), encoding="utf-8"
            )

            reopened, *_rest = arena._open_run(
                run, run_config, [], lambda _size: True, {}
            )

        self.assertEqual(reopened, run)

    def test_openrouter_uses_chat_completions_with_high_reasoning(self):
        captured = {}

        class FakeCompletions:
            @property
            def with_raw_response(self):
                return self

            def create(self, **kwargs):
                captured.update(kwargs)
                response = SimpleNamespace(
                    id="response-id",
                    choices=[
                        SimpleNamespace(message=SimpleNamespace(content="E5"))
                    ],
                    usage={
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "prompt_tokens_details": {"cached_tokens": 40},
                    },
                )
                return SimpleNamespace(parse=lambda: response)

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )
        with tempfile.TemporaryDirectory() as tmp:
            output, _seconds, cost = arena._call_llm_move(
                client,
                "prompt",
                player_name="qwen3.8-max-high-api",
                log_path=Path(tmp) / "calls.jsonl",
                game_number=1,
                move_number=1,
                attempt=1,
            )

        self.assertEqual(output, "E5")
        self.assertEqual(captured["model"], "qwen/qwen3.8-max")
        self.assertEqual(captured["messages"], [{"role": "user", "content": [{
            "type": "text", "text": "prompt", "cache_control": {"type": "ephemeral"},
        }]}])
        self.assertFalse(captured["stream"])
        self.assertEqual(captured["max_completion_tokens"], 131_072)
        self.assertEqual(
            {key: value for key, value in captured["extra_body"].items() if key != "session_id"},
            {
                "reasoning": {"effort": "high", "exclude": False},
                "provider": {
                    "order": ["alibaba"],
                    "allow_fallbacks": False,
                },
            },
        )
        self.assertAlmostEqual(cost, (60 * 2 + 40 * 0.25 + 20 * 6) / 1e6)

    def test_openrouter_retries_malformed_json_without_logging_http_values(self):
        bad_body = b'{"partial":' + b"x" * 5_000
        bad_http_response = SimpleNamespace(
            status_code=200,
            headers={
                "content-type": "application/json",
                "x-request-id": "request-id",
            },
            content=bad_body,
        )
        decode_error = json.JSONDecodeError("Expecting value", bad_body.decode(), 11)
        good_response = SimpleNamespace(
            id="response-id",
            choices=[SimpleNamespace(message=SimpleNamespace(content="E5"))],
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 1,
            },
        )

        class FakeRawResponse:
            def __init__(self, response, error=None):
                self.http_response = response
                self.error = error

            def parse(self):
                if self.error is not None:
                    raise self.error
                return good_response

        class FakeCompletions:
            def __init__(self):
                self.calls = 0

            @property
            def with_raw_response(self):
                return self

            def create(self, **_kwargs):
                self.calls += 1
                return FakeRawResponse(
                    bad_http_response,
                    decode_error if self.calls == 1 else None,
                )

        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        retries = []
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(arena._Arena, "LLM_API_RETRY_INITIAL_SECONDS", 0),
            mock.patch.object(arena._Arena, "LLM_API_RETRY_MAX_SECONDS", 0),
            mock.patch.object(arena._Arena, "LLM_API_RETRY_JITTER_FRACTION", 0),
        ):
            log_path = Path(tmp) / "calls.jsonl"
            output, _seconds, _cost = arena._call_llm_move(
                client,
                "prompt",
                player_name="qwen3.8-max-high-api",
                log_path=log_path,
                game_number=1,
                move_number=1,
                attempt=1,
                retry=lambda *args: retries.append(args),
            )
            entries = [json.loads(line) for line in log_path.read_text().splitlines()]

        self.assertEqual(output, "E5")
        self.assertEqual(completions.calls, 2)
        self.assertEqual(len(retries), 1)
        self.assertEqual(len(entries), 2)
        failure = entries[0]
        self.assertFalse(failure["ok"])
        self.assertTrue(failure["retryable"])
        self.assertEqual(failure["response_status"], 200)
        self.assertEqual(failure["response_body_bytes"], len(bad_body))
        self.assertEqual(failure["error"], "JSONDecodeError")
        self.assertNotIn("response_headers", failure)
        self.assertNotIn("response_body_excerpt", failure)
        self.assertNotIn("response_id", failure)
        self.assertTrue(entries[1]["ok"])
        self.assertNotIn("response_id", entries[1])

    def test_openrouter_kimi_uses_route_maximum_output(self):
        captured = {}

        class FakeCompletions:
            @property
            def with_raw_response(self):
                return self

            def create(self, **kwargs):
                captured.update(kwargs)
                response = SimpleNamespace(
                    id="response-id",
                    choices=[SimpleNamespace(message=SimpleNamespace(content="E5"))],
                    usage={"prompt_tokens": 10, "completion_tokens": 1},
                )
                return SimpleNamespace(parse=lambda: response)

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )
        with tempfile.TemporaryDirectory() as tmp:
            arena._call_llm_move(
                client,
                "prompt",
                player_name="kimi-k3-high-api",
                log_path=Path(tmp) / "calls.jsonl",
                game_number=1,
                move_number=1,
                attempt=1,
            )

        self.assertEqual(captured["max_completion_tokens"], 943_718)

    def test_openrouter_models_are_pinned_to_first_party_providers(self):
        api = next(api for api in arena._Arena.LLM_APIS if api.name == "openrouter")
        self.assertEqual(
            {player.model: player.route for player in api.players.values()},
            {
                "qwen/qwen3.8-max": "alibaba",
                "moonshotai/kimi-k3": "moonshotai/mxfp4",
                "meta/muse-spark-1.2": "meta",
            },
        )

    def test_compatible_api_is_added_with_one_registry_entry(self):
        player = arena._LLMPlayerConfig(
            "example-model",
            "high",
            (2.0, 0.25, 6.0),
            max_output_tokens=8_192,
        )
        api = arena._LLMAPIConfig(
            name="example",
            players={"example-high": player},
            sdk_module="openai",
            sdk_client_path=("OpenAI",),
            api_key_env="EXAMPLE_API_KEY",
            manifest_kind="example_responses_api",
            manifest_level_name="reasoning_effort",
            protocol=arena._ResponsesProtocol,
            endpoint_path=("responses",),
            base_url="https://example.invalid/v1",
            max_tokens_field="max_output_tokens",
            cost_tracking=True,
        )
        with mock.patch.object(arena._Arena, "LLM_APIS", (*arena._Arena.LLM_APIS, api)):
            client_options = {}

            class FakeClient:
                def __init__(self, **kwargs):
                    client_options.update(kwargs)

            self.assertEqual(
                arena._llm_config("example-high"),
                ("example", "example-model", "high"),
            )
            with (
                mock.patch.dict(
                    arena.os.environ, {"EXAMPLE_API_KEY": "example-key"}
                ),
                mock.patch(
                    "builtins.__import__",
                    return_value=SimpleNamespace(OpenAI=FakeClient),
                ),
            ):
                self.assertIsInstance(arena._llm_client("example-high"), FakeClient)
            self.assertEqual(
                client_options,
                {
                    "api_key": "example-key",
                    "timeout": None,
                    "max_retries": 0,
                    "base_url": "https://example.invalid/v1",
                },
            )
            self.assertEqual(
                arena._llm_request(api, player, "prompt"),
                {
                    "model": "example-model",
                    "reasoning": {"effort": "high"},
                    "input": "prompt",
                    "store": False,
                    "max_output_tokens": 8_192,
                },
            )
            self.assertEqual(
                arena._llm_player_manifest("example-high"),
                {
                    "name": "example-high",
                    "kind": "example_responses_api",
                    "model": "example-model",
                    "agentic_harness": "api",
                    "reasoning_effort": "high",
                    "timeout_seconds": None,
                    "base_url": "https://example.invalid/v1",
                    "max_output_tokens": 8_192,
                    "cost_tracking": "token_usage",
                },
            )
            self.assertAlmostEqual(
                arena._llm_call_cost(
                    {
                        "input_tokens": 100,
                        "input_tokens_details": {"cached_tokens": 40},
                        "output_tokens": 20,
                    },
                    "example",
                    "example-model",
                ),
                (60 * 2.0 + 40 * 0.25 + 20 * 6.0) / 1e6,
            )

    def test_deepseek_responses_uses_documented_maximum_output_tokens(self):
        captured = {}

        class FakeResponses:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    id="response-id",
                    output_text="E5",
                    usage={
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "input_tokens_details": {"cached_tokens": 40},
                    },
                )

        client = SimpleNamespace(responses=FakeResponses())
        with tempfile.TemporaryDirectory() as tmp:
            output, _seconds, _cost = arena._call_llm_move(
                client,
                "prompt",
                player_name="DeepSeek-V4-Flash-0731-high-api",
                log_path=Path(tmp) / "calls.jsonl",
                game_number=1,
                move_number=1,
                attempt=1,
            )

        self.assertEqual(output, "E5")
        self.assertEqual(captured["model"], "deepseek-v4-flash")
        self.assertEqual(captured["reasoning"], {"effort": "high"})
        self.assertEqual(captured["input"], "prompt")
        self.assertFalse(captured["store"])
        self.assertEqual(captured["max_output_tokens"], 393_216)

    def test_deepseek_uses_updated_peak_and_off_peak_prices(self):
        usage = {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens": 20,
        }
        off_peak = arena._llm_call_cost(
            usage,
            "deepseek_responses",
            "deepseek-v4-flash",
            started_at="2026-08-18T05:00:00+00:00",
        )
        peak = arena._llm_call_cost(
            usage,
            "deepseek_responses",
            "deepseek-v4-flash",
            started_at="2026-08-18T06:00:00+00:00",
        )

        self.assertAlmostEqual(
            off_peak, (60 * 0.22 + 40 * 0.007 + 20 * 0.66) / 1e6
        )
        self.assertAlmostEqual(
            peak, (60 * 0.44 + 40 * 0.014 + 20 * 1.32) / 1e6
        )
        self.assertEqual(
            arena._Arena.LLM_MODEL_PRICING_USD_PER_MILLION[
                "deepseek-v4-flash"
            ],
            {
                "input": 0.22,
                "cached_input": 0.007,
                "output": 0.66,
                "peak_input": 0.44,
                "peak_cached_input": 0.014,
                "peak_output": 1.32,
                "peak_utc_hours": ((1, 4), (6, 10)),
                "peak_utc_weekdays": (0, 1, 2, 3, 4),
            },
        )

    def test_past_deepseek_game_cost_is_repriced_from_call_ledger(self):
        player = "DeepSeek-V4-Flash-0731-high-api"
        opponent = "kata-opponent"
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "past-run"
            run.mkdir()
            (run / "run.json").write_text(
                json.dumps(
                    {
                        "arena_log_schema_version": 4,
                        "completed_games": 1,
                        "games_scope": "current_run",
                        "board_size": arena._Arena.BOARD_SIZE,
                        "komi": arena._Arena.KOMI,
                        "rules": arena._Arena.RULES,
                    }
                ),
                encoding="utf-8",
            )
            (run / "results.csv").write_text(
                "game,batch,black,white,result,winner,score_black,moves,source,"
                "llm_moves,llm_illegal_moves,llm_api_problems,llm_api_seconds,"
                "llm_cost_usd\n"
                f"1,1,{player},{opponent},B+R,{player},1,1,"
                "deepseek_responses_api,1,0,0,2.0,999.0\n",
                encoding="utf-8",
            )
            call = {
                "schema_version": 2,
                "game": 1,
                "player": player,
                "provider": "deepseek_responses",
                "model": "deepseek-v4-flash",
                "started_at": "2026-08-18T06:00:00+00:00",
                "ok": True,
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 20,
            }
            (run / "llm_calls.jsonl").write_text(
                json.dumps(call) + "\n", encoding="utf-8"
            )

            games = arena._load_past_games([run], (player, opponent))

        expected = (60 * 0.44 + 40 * 0.014 + 20 * 1.32) / 1e6
        self.assertEqual(len(games), 1)
        self.assertAlmostEqual(games[0].llm_cost_usd, expected)

    def test_llm_schedule_requires_one_active_player(self):
        first = "gpt-5.4-low-api"
        second = "DeepSeek-V4-Flash-0731-high-api"
        opponent = "kata-opponent"
        slate = [
            arena.ScheduledGame(1, 1, first, opponent),
            arena.ScheduledGame(2, 1, second, opponent),
            arena.ScheduledGame(3, 1, opponent, first),
            arena.ScheduledGame(4, 1, opponent, second),
        ]
        config = replace(arena.CONFIG, active_players=(first, second))
        with (
            mock.patch.object(arena._State, "config", config),
            self.assertRaises(arena.ArenaError),
        ):
            arena._validate_llm_schedule(slate)

    def test_midgame_deepseek_actions_are_loaded_for_resume(self):
        slot = arena.ScheduledGame(
            2,
            1,
            "DeepSeek-V4-Flash-0731-high-api",
            "kata-opponent",
        )
        entries = [
            {
                "event": "game_started",
                "board_size": arena._Arena.BOARD_SIZE,
                "komi": arena._Arena.KOMI,
                "rules": arena._Arena.RULES,
                "max_moves": None,
            },
            {"event": "move_played", "color": "B", "move": "E5", "success": True},
            {"event": "move_played", "color": "W", "move": "D5", "success": True},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "game-000002.actions.jsonl"
            path.write_text(
                "".join(json.dumps(entry) + "\n" for entry in entries),
                encoding="utf-8",
            )

            recovery = arena._load_llm_game_recovery(Path(tmp), slot, [])

        self.assertIsNotNone(recovery)
        self.assertEqual(recovery.game_attempt, 1)
        self.assertEqual(recovery.resume_game_id, "game-000002-resume-1")
        self.assertEqual(recovery.moves, (("B", "E5"), ("W", "D5")))

class MatchmakingTests(unittest.TestCase):
    names = ("new-a", "new-b", "old-a", "old-b")
    gains = (
        (0.0, 0.0, 5.0, 1.0),
        (0.0, 0.0, 2.0, 6.0),
        (5.0, 2.0, 0.0, 0.0),
        (1.0, 6.0, 0.0, 0.0),
    )

    def test_default_selection_picks_one_deterministic_pair_per_active_player(self):
        schedule = arena.schedule_batch(
            [],
            self.names,
            self.gains,
            batch_number=1,
            active_players=self.names[:2],
            scheduled_active_players=self.names[:2],
        )

        self.assertEqual(len(schedule), 4)
        self.assertEqual(
            [(game.black, game.white) for game in schedule],
            [
                ("new-a", "old-a"),
                ("new-b", "old-b"),
                ("old-a", "new-a"),
                ("old-b", "new-b"),
            ],
        )

    def test_independent_pair_can_reserve_numbers_while_another_pair_runs(self):
        schedule = arena.schedule_batch(
            [],
            self.names,
            self.gains,
            first_game_number=7,
            batch_number=4,
            active_players=self.names[:2],
            scheduled_active_players=["new-a"],
        )

        self.assertEqual([game.number for game in schedule], [7, 8])
        self.assertEqual(
            [(game.black, game.white) for game in schedule],
            [("new-a", "old-a"), ("old-a", "new-a")],
        )

    def test_gain_proportional_selection_samples_pairs_by_gain(self):
        schedule = arena.schedule_batch(
            [],
            self.names,
            self.gains,
            pair_count=500,
            batch_number=2,
            rng=random.Random(7),
            active_players=self.names[:2],
            selection="gain_proportional",
            allow_active_player_pairs=True,
            top_p=0.95,
        )

        self.assertEqual(len(schedule), 1_000)
        arena._validate_color_swapped_schedule(schedule, 500)
        for game in schedule:
            self.assertGreaterEqual(
                len({game.black, game.white} & set(self.names[:2])), 1
            )

    def test_katago_mode_can_select_active_pairs_but_default_cannot(self):
        gains = (
            (0.0, 10.0, 5.0, 1.0),
            (10.0, 0.0, 2.0, 6.0),
            (5.0, 2.0, 0.0, 0.0),
            (1.0, 6.0, 0.0, 0.0),
        )
        kata_schedule = arena.schedule_batch(
            [],
            self.names,
            gains,
            batch_number=1,
            active_players=self.names[:2],
            scheduled_active_players=self.names[:2],
            allow_active_player_pairs=True,
        )
        llm_schedule = arena.schedule_batch(
            [],
            self.names,
            gains,
            batch_number=1,
            active_players=self.names[:2],
            scheduled_active_players=self.names[:2],
        )

        self.assertEqual(len(kata_schedule), 4)
        self.assertTrue(
            all(
                game.black in self.names[:2] and game.white in self.names[:2]
                for game in kata_schedule
            )
        )
        self.assertTrue(
            all(
                len({game.black, game.white} & set(self.names[:2])) == 1
                for game in llm_schedule
            )
        )

    def test_gain_nucleus_drops_tail_before_sampling(self):
        names = ("new", "old-a", "old-b", "old-c", "old-tail")
        weights = (60.0, 30.0, 9.0, 1.0)
        gains = tuple(
            tuple(
                0.0
                if left == right
                else weights[right - 1]
                if left == 0
                else weights[left - 1]
                if right == 0
                else 0.0
                for right in range(len(names))
            )
            for left in range(len(names))
        )
        schedule = arena.schedule_batch(
            [],
            names,
            gains,
            pair_count=200,
            batch_number=2,
            rng=random.Random(11),
            active_players=("new",),
            selection="gain_proportional",
            top_p=0.95,
        )

        scheduled_players = {
            name for game in schedule for name in (game.black, game.white)
        }
        self.assertNotIn("old-tail", scheduled_players)

    def test_active_active_games_count_for_both_active_players(self):
        first, second = "new-a", "new-b"
        config = replace(
            arena.CONFIG,
            active_players=(first, second),
            opponent_players=arena.CONFIG.opponent_players,
        )
        with mock.patch.object(arena._State, "config", config):
            counts = arena._active_player_game_counts(
                [arena.ScheduledGame(1, 1, first, second)]
            )

        self.assertEqual(counts[first], 1)
        self.assertEqual(counts[second], 1)

    def test_native_execution_loads_all_distinct_models_in_one_process(self):
        players = tuple(
            arena.Player(f"bot-{index}", Path(f"/models/model-{index}.bin.gz"))
            for index in range(7)
        )
        schedule = [
            arena.ScheduledGame(index + 1, 1, f"bot-{index}", f"bot-{index + 1}")
            for index in range(6)
        ]

        chunks = arena._partition_native_games(schedule, players)
        manifest = arena._native_chunk_manifest(chunks, players)

        self.assertEqual(chunks, (tuple(schedule),))
        self.assertEqual(len(manifest), 1)
        self.assertEqual(len(manifest[0]["models"]), 7)

    def test_native_attempt_reports_completed_game_heartbeats(self):
        messages = []
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            network = work_dir / "network.bin.gz"
            network.touch()
            player = arena.Player("bot", network, None, 0.5, 0.1)
            schedule = [arena.ScheduledGame(1, 3, "bot", "bot")]

            def fake_run(*_args, **_kwargs):
                sgf_dir = work_dir / "katago-sgfs"
                (sgf_dir / "games.sgfs").write_text(
                    "(;PB[bot]PW[bot]RE[B+R])\n", encoding="utf-8"
                )
                time.sleep(0.035)

            with (
                mock.patch.object(arena._Arena, "PROGRESS_INTERVAL_SECONDS", 0.01),
                mock.patch.object(arena.subprocess, "run", side_effect=fake_run),
            ):
                arena._run_native_attempt(
                    schedule,
                    [player],
                    work_dir,
                    attempt=1,
                    max_moves=arena._Arena.MAX_MOVES,
                    progress=messages.append,
                )

        heartbeats = [message for message in messages if "heartbeat" in message]
        self.assertGreaterEqual(len(heartbeats), 1)
        self.assertTrue(any("1/1 games finished" in message for message in heartbeats))

    def test_random_anchor_games_report_count_and_progress(self):
        messages = []
        slot = arena.ScheduledGame(1, 4, arena._Arena.ANCHOR, "network-a")
        record = arena.GameRecord(
            slot.number,
            slot.batch,
            slot.black,
            slot.white,
            "W+R",
            "W",
            slot.white,
            0.0,
            "resignation",
            (),
            "uniform_random",
            "(;PB[kata1-random]PW[network-a]RE[W+R])",
        )

        def finish(*_args, **_kwargs):
            time.sleep(0.035)
            return record

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(arena._Arena, "PROGRESS_INTERVAL_SECONDS", 0.01),
            mock.patch.object(arena, "_run_random_game", side_effect=finish),
        ):
            arena.run_random_games(
                [slot], (), Path(tmp) / "batch", progress=messages.append
            )

        self.assertIn(
            "Batch 4: random-anchor games starting (1 game, 1 worker)", messages
        )
        self.assertTrue(
            any(
                "random-anchor heartbeat: 0/1 games finished" in message
                for message in messages
            )
        )
        self.assertIn(
            "Batch 4 random-anchor heartbeat: 1/1 games finished (complete)",
            messages,
        )

    def test_native_recovery_skips_an_interrupted_capped_retry_attempt(self):
        slot = arena.ScheduledGame(1, 3, "bot-a", "bot-b")
        players = (
            arena.Player("bot-a", Path("/models/a.bin.gz"), None, 0.5, 0.1),
            arena.Player("bot-b", Path("/models/b.bin.gz"), None, 0.5, 0.1),
        )
        attempts = []

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            arena._native_attempt_paths(work, 2)[0].write_text(
                "partial retry", encoding="utf-8"
            )

            def finish_retry(
                slate,
                _players,
                work_dir,
                *,
                attempt,
                max_moves,
                progress,
            ):
                self.assertEqual(slate, [slot])
                self.assertEqual(max_moves, arena._Arena.MAX_MOVES)
                self.assertIsNone(progress)
                attempts.append(attempt)
                sgf_dir = arena._native_attempt_paths(work_dir, attempt)[2]
                sgf_dir.mkdir()
                (sgf_dir / "games.sgfs").write_text(
                    "(;PB[bot-a]PW[bot-b]RE[B+R])\n", encoding="utf-8"
                )
                return sgf_dir

            with (
                mock.patch.object(arena, "_ensure_game_dependencies"),
                mock.patch.object(
                    arena, "_run_native_attempt", side_effect=finish_retry
                ),
            ):
                records = arena._retry_capped_native_games(
                    [],
                    [slot],
                    players,
                    work,
                    first_attempt=2,
                    progress=None,
                    recovering=True,
                )

        self.assertEqual(attempts, [3])
        self.assertEqual([game.number for game in records], [1])

    def test_random_game_recovery_replays_when_the_aggregate_is_incomplete(self):
        slot = arena.ScheduledGame(
            1, 3, arena._Arena.ANCHOR, "network-a"
        )
        record = arena.GameRecord(
            slot.number,
            slot.batch,
            slot.black,
            slot.white,
            "W+R",
            "W",
            slot.white,
            0.0,
            "resignation",
            (),
            "uniform_random",
            "",
        )
        player = arena.Player("network-a", Path("/models/a.bin.gz"))

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "schedule.json").write_text(
                json.dumps([dataclasses.asdict(slot)]), encoding="utf-8"
            )
            (work / "random-games.sgfs").write_text(
                "(;PB[kata1-random]", encoding="utf-8"
            )
            with (
                mock.patch.object(arena._State, "katago_mode", True),
                mock.patch.object(arena, "_ensure_game_dependencies") as ensure,
                mock.patch.object(
                    arena, "run_random_games", return_value=[record]
                ) as replay,
            ):
                recovered_slate, recovered = arena.recover_batch(work, (player,))

        ensure.assert_called_once_with([slot], (player,))
        replay.assert_called_once_with([slot], (player,), work, progress=None)
        self.assertEqual(recovered_slate, [slot])
        self.assertEqual(recovered, [record])

    def test_cpu_batch_restores_schedule_order_after_parallel_execution(self):
        random_slot = arena.ScheduledGame(
            1, 1, arena._Arena.ANCHOR, "network-a"
        )
        native_slot = arena.ScheduledGame(2, 1, "network-a", "network-b")

        def record(slot):
            return arena.GameRecord(
                slot.number,
                slot.batch,
                slot.black,
                slot.white,
                "B+R",
                "B",
                slot.black,
                1.0,
                "resignation",
                (),
                "test",
                "",
            )

        messages = []
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(arena._State, "katago_mode", True),
            mock.patch.object(arena._State, "katago_backend", "cpu"),
            mock.patch.object(arena, "_ensure_game_dependencies"),
            mock.patch.object(
                arena, "run_native_games", return_value=[record(native_slot)]
            ),
            mock.patch.object(
                arena, "run_random_games", return_value=[record(random_slot)]
            ),
        ):
            records = arena.play_batch(
                [random_slot, native_slot], (), Path(tmp) / "batch", messages.append
            )

        self.assertEqual([game.number for game in records], [1, 2])
        self.assertIn(
            "Batch 1: executing 2 games (1 network, 1 random-anchor)", messages
        )


class OAuthAndProxyTests(unittest.TestCase):
    def test_oauth_requires_login_without_api_key_fallback(self):
        with (
            mock.patch.object(
                arena, "_codex_auth_source", side_effect=arena.ArenaError("missing")
            ),
            mock.patch.object(
                arena, "_llm_api_key", side_effect=AssertionError("API fallback")
            ),
            self.assertRaisesRegex(arena.ArenaError, "OAuth login"),
        ):
            arena._openai_oauth_proxy_credential()

    def test_oauth_rejects_codex_api_key_auth_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = Path(tmp) / "auth.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "auth_mode": "apikey",
                        "tokens": {
                            "access_token": "stale-access-token",
                            "account_id": "stale-account",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    arena, "_codex_auth_source", return_value=auth_path
                ),
                self.assertRaisesRegex(arena.ArenaError, "OAuth login"),
            ):
                arena._openai_oauth_proxy_credential()

    def test_proxy_normalizes_codex_paths(self):
        self.assertEqual(
            arena._canonical_openai_proxy_path("/v1/codex/responses"),
            "/v1/responses",
        )
        self.assertEqual(
            arena._canonical_openai_proxy_path(
                "/v1/codex/models?client_version=0.147.0"
            ),
            "/v1/models?client_version=0.147.0",
        )
        self.assertIsNone(
            arena._canonical_openai_proxy_path("/v1/chat/completions")
        )

    def test_agent_proxy_can_suppress_deep_readable_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "openai-proxy.jsonl"
            proxy = arena._OpenAIReverseProxy(
                SimpleNamespace(auth_mode="oauth"),
                log_path,
                write_readable=False,
            )
            proxy.close()

            self.assertTrue(log_path.is_file())
            self.assertFalse((Path(tmp) / "openai-proxy-readable.log").exists())



class CodexPlayerTests(unittest.TestCase):
    def test_workspace_config_enables_offline_tools_and_disables_hosted_tools(self):
        workspace = arena._codex_config_text()

        for feature in arena._Arena.CODEX_OFFLINE_TOOL_FEATURES:
            self.assertIn(f"{feature} = true", workspace)
            self.assertNotIn(f"{feature} = false", workspace)

        for feature in (
            "apps",
            "browser_use",
            "image_generation",
            "remote_plugin",
            "skill_mcp_dependency_install",
            "standalone_web_search",
        ):
            self.assertIn(f"{feature} = false", workspace)
        self.assertIn('web_search = "disabled"', workspace)

    def test_first_prompt_file_contains_the_materialized_continual_prompt(self):
        client = arena._CodexGameClient.__new__(arena._CodexGameClient)
        client.agentic_harness = "codex-1h"
        client.game_number = 1
        captured = {}

        def create(**request):
            captured.update(request)
            return arena._CodexMoveResponse(
                "E5",
                {
                    "input_tokens": 10,
                    "input_tokens_details": {"cached_tokens": 2},
                    "output_tokens": 3,
                    "output_tokens_details": {"reasoning_tokens": 1},
                },
            )

        client.create = create
        base_prompt = (
            "turn\n\n"
            f"{arena._Arena.MOVE_OUTPUT_INSTRUCTIONS}"
        )
        expected = client.prepare_prompt(base_prompt)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt_path = root / "prompt.txt"
            calls_path = root / "calls.jsonl"
            arena._call_llm_move(
                client,
                base_prompt,
                player_name="gpt5.6-sol-low-codex-1h",
                log_path=calls_path,
                first_prompt_path=prompt_path,
                game_number=1,
                move_number=1,
                attempt=1,
            )
            logged = json.loads(calls_path.read_text(encoding="utf-8"))

            self.assertEqual(prompt_path.read_text(encoding="utf-8"), expected + "\n")
            self.assertEqual(logged["request"]["input"], expected)
            self.assertEqual(captured["input"], expected)

    def test_readable_agent_log_compacts_codex_tool_events(self):
        file_event = {
            "type": "FileChangeThreadItem",
            "item": {
                "type": "fileChange",
                "status": "completed",
                "changes": [
                    {
                        "kind": {"type": "add"},
                        "path": "/workspace/life.py",
                        "diff": "large source line\n" * 1_000,
                    }
                ],
            },
        }
        command_event = {
            "type": "CommandExecutionThreadItem",
            "item": {
                "type": "commandExecution",
                "status": "failed",
                "command": "/usr/bin/bash -c 'python3 -u life.py'",
                "command_actions": [{"command": "python3 -u life.py"}],
                "duration_ms": 70_882,
                "exit_code": 130,
                "aggregated_output": "Traceback\nmore details\nKeyboardInterrupt\n",
            },
        }

        file_summary = arena._compact_agent_tool_event(file_event)
        command_summary = arena._compact_agent_tool_event(command_event)

        self.assertEqual(file_summary, "file | completed | add life.py")
        self.assertEqual(
            command_summary,
            "command | failed | python3 -u life.py | exit 130 | 70.9s | "
            "KeyboardInterrupt",
        )
        self.assertNotIn("\n", file_summary + command_summary)
        self.assertNotIn("large source line", file_summary)

    def test_codex_isolated_workspace_and_agent_log_are_at_run_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            untracked = root / "untracked_log"
            run = untracked / "arena_test"
            work = run / "batch-003"
            work.mkdir(parents=True)
            player = arena._LLMPlayerConfig(
                "gpt-5.6-sol",
                "low",
                (5.0, 0.5, 30.0),
                agentic_harness="codex-0h",
            )
            with (
                mock.patch.object(arena._Arena, "UNTRACKED_LOG_ROOT", untracked),
                mock.patch.object(arena._CodexGameClient, "_prepare"),
            ):
                client = arena._CodexGameClient(
                    "gpt5.6-sol-low-codex-0h",
                    player,
                    work,
                    12,
                    proxy_credential=SimpleNamespace(auth_mode="oauth"),
                )

        self.assertEqual(client.cwd, work / "agent-workspaces" / "game-000012" / "fs" / "workspace")
        self.assertEqual(client.agents_log_path, run / "agents_log.txt")
        self.assertEqual(
            client.private_dir,
            work / "agent-workspaces" / "game-000012",
        )

    def test_codex_continual_workspace_and_runtime_belong_to_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            untracked = root / "untracked_log"
            run = untracked / "arena_test"
            work = run / "batch-003"
            work.mkdir(parents=True)
            name = "gpt5.6-sol-low-codex-1h"
            player = arena._LLMPlayerConfig(
                "gpt-5.6-sol",
                "low",
                (5.0, 0.5, 30.0),
                agentic_harness="codex-1h",
            )
            with (
                mock.patch.object(arena._Arena, "ROOT", root),
                mock.patch.object(arena._Arena, "UNTRACKED_LOG_ROOT", untracked),
                mock.patch.object(arena._CodexGameClient, "_prepare"),
            ):
                client = arena._CodexGameClient(
                    name,
                    player,
                    work,
                    12,
                    proxy_credential=SimpleNamespace(auth_mode="oauth"),
                )

        player_root = work / "agent-workspaces" / "game-000012"
        self.assertEqual(client.cwd, player_root / "fs" / "workspace")
        self.assertEqual(client.home, player_root / "fs" / "runtime")
        self.assertEqual(client.state_path, player_root / "thread.json")
        self.assertEqual(client.checkpoint_root, run / "codex-checkpoints" / name)
        self.assertEqual(client.workspace_view, run / "game-000012-workspace")
        self.assertEqual(client.agents_log_path, run / "agents_log.txt")
        self.assertEqual(
            client.private_dir,
            work / "agent-workspaces" / "game-000012",
        )

    def test_codex_games_share_a_checkpoint_but_have_private_state_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "run" / "batch-001"
            work.mkdir(parents=True)
            name = "gpt5.6-sol-low-codex-1h"
            player = arena._llm_player_config(name)[1]
            with (mock.patch.object(arena._Arena, "UNTRACKED_LOG_ROOT", root),
                  mock.patch.object(arena._CodexGameClient, "_prepare")):
                first = arena._CodexGameClient(name, player, work, 1)
                second = arena._CodexGameClient(name, player, work, 2)
            self.assertEqual(first.checkpoint_root, second.checkpoint_root)
            self.assertNotEqual(first.cwd, second.cwd)
            self.assertNotEqual(first.home, second.home)
            self.assertNotEqual(first.state_path, second.state_path)

    def test_removed_codex_modes_are_not_registered_or_constructible(self):
        self.assertNotIn("codex_workspace_isolated", arena.RUN_TYPES)
        for harness in ("codex", "codex-continual", "codex-3h", "codex-16h"):
            self.assertNotIn(harness, arena.RUN_TYPES)
            for model in ("gpt5.6-sol-low", "gpt5.6-luna-max", "gpt6-astra-high"):
                for instance in ("", "2"):
                    name = f"{model}-{harness}{instance}"
                    self.assertFalse(arena._is_active_llm_player(name))
                    with self.assertRaisesRegex(arena.ArenaError, "unknown LLM player"):
                        arena._llm_player_config(name)
            player = arena._LLMPlayerConfig("gpt-5.6-sol", "high", (4, 0.4, 20), harness)
            with self.assertRaisesRegex(arena.ArenaError, "invalid Codex agentic harness"):
                arena._CodexGameClient(f"gpt5.6-sol-high-{harness}", player, Path("/unused"), 1)
        for mode in ("isolated", "continual"):
            old_name = f"gpt5.6-sol-high-codex-workspace-{mode}"
            for suffix in ("", "2"):
                self.assertFalse(arena._is_active_llm_player(old_name + suffix))
                self.assertTrue(arena._is_result_llm_player(old_name + suffix))
        with self.assertRaises(arena.ArenaError):
            arena._llm_api_config("openai_codex")
        for mode in ("single", "multi"):
            name = f"gpt5.6-sol-high-codex-{mode}"
            for suffix in ("", "2"):
                with self.subTest(player=name + suffix):
                    with self.assertRaises(arena.ArenaError):
                        arena._llm_player_config(name + suffix)
            player = arena._LLMPlayerConfig(
                "gpt-5.6-sol", "high", (4.0, 0.4, 20.0), f"codex-{mode}")
            with self.assertRaisesRegex(arena.ArenaError, "invalid Codex agentic harness"):
                arena._CodexGameClient(name, player, Path("/unused"), 1)

    def test_workspace_registry_has_all_five_training_durations(self):
        api = arena._llm_api_config("openai_codex_workspace")
        actual = {
            (player.model, player.level, player.agentic_harness)
            for player in api.players.values()
        }
        expected = {
            (model, effort, harness)
            for model in ("gpt-5.6-sol", "gpt-5.6-luna")
            for effort in ("low", "high", "max")
            for harness in ("codex-0h", "codex-1h", "codex-2h", "codex-4h", "codex-8h")
        }

        expected.update(
            ("gpt-6-astra", effort, harness)
            for effort in ("low", "medium", "high", "xhigh", "max")
            for harness in ("codex-0h", "codex-1h", "codex-2h", "codex-4h", "codex-8h")
        )
        self.assertEqual(actual, expected)
        self.assertEqual(len(api.players), 55)
        for harness in ("codex-0h", "codex-1h", "codex-2h", "codex-4h", "codex-8h"):
            name = f"gpt6-astra-high-{harness}"
            self.assertFalse(arena._active_players_are_katago((name,)))
            self.assertEqual(api.players[name].prices,
                             arena._llm_player_config("gpt6-astra-high-api")[1].prices)
            self.assertEqual(set(arena.RUN_TYPES[harness].active_players), {
                f"{model}-{effort}-{harness}"
                for model in ("gpt5.6-sol", "gpt5.6-luna")
                for effort in ("low", "high", "max")
            })
            self.assertEqual(arena.RUN_TYPES[harness].workspace.training_seconds,
                             int(harness.removeprefix("codex-").removesuffix("h")) * 3600)
        self.assertFalse(any(name.endswith("-codex-workspace") for name in api.players))

    def test_renamed_codex_players_use_the_bounded_workspace_client(self):
        for harness in ("codex-0h", "codex-1h", "codex-2h", "codex-4h", "codex-8h"):
            name = f"gpt6-astra-high-{harness}"
            with (mock.patch.object(arena, "_CodexGameClient") as client,
                  mock.patch.object(arena, "_codex_workspace_proxy_credential",
                                    return_value="test-credential")):
                actual = arena._llm_client(name, work_dir=Path("/unused"), game_number=1)
                self.assertIs(actual, client.return_value)
                client.assert_called_once_with(
                    name, arena._llm_player_config(name)[1], Path("/unused"), 1,
                    proxy_credential="test-credential",
                )

    def test_workspace_instructions_match_general_and_persistence_modes(self):
        self.assertEqual(
            arena._Arena.CODEX_WORKSPACE_INSTRUCTIONS,
            "You are in a sandboxed workspace, and you may read, write, and execute "
            "only files within the workspace. You may use the tools available to "
            "you to help you win the game. For example, you can write a MCTS "
            "algorithm in python. Python is available as python3. Do not access the "
            "internet, and do not access any external Go engines.",
        )

    @mock.patch.object(arena._CodexGameClient, "_run_turn", _fake_codex_run_turn)
    def test_workspace_prompt_uses_mode_specific_persistence(self):
        class FakeThread:
            id = "thread-1"

            def __init__(self):
                self.prompts = []

            def run(self, prompt, **_options):
                self.prompts.append(prompt)
                tokens = SimpleNamespace(
                    input_tokens=10,
                    cached_input_tokens=2,
                    output_tokens=3,
                    reasoning_output_tokens=1,
                )
                return SimpleNamespace(
                    items=[],
                    final_response="E5",
                    usage=SimpleNamespace(last=tokens),
                )

        class FakeCodex:
            def __init__(self):
                self.thread = FakeThread()

            def thread_start(self, **_options):
                return self.thread

        sdk = SimpleNamespace(
            ApprovalMode=SimpleNamespace(deny_all="deny"),
            Sandbox=SimpleNamespace(full_access="full-access"),
        )

        def run(harness, root):
            client = arena._CodexGameClient.__new__(arena._CodexGameClient)
            client.player = arena._LLMPlayerConfig(
                "gpt-5.6-sol", "low", (5.0, 0.5, 30.0), harness
            )
            client.agentic_harness = harness
            client.cwd = root
            client.state_path = root / f"{harness}.json"
            client._sdk = sdk
            client._codex = FakeCodex()
            client._thread = None
            client._usage_total = None
            client._start_runtime = lambda: None
            client.create(
                model="gpt-5.6-sol",
                input=(
                    "choose\n\n"
                    f"{arena._Arena.MOVE_OUTPUT_INSTRUCTIONS}"
                ),
                reasoning={"effort": "low"},
            )
            return client._codex.thread.prompts[0]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            isolated = run("codex-0h", root)
            continual = run("codex-1h", root)

        self.assertEqual(isolated, continual)
        self.assertIn("No evaluation game affects another game", continual)
        for prompt in (isolated, continual):
            self.assertLess(
                prompt.index(arena._Arena.CODEX_WORKSPACE_INSTRUCTIONS),
                prompt.index(arena._Arena.MOVE_OUTPUT_INSTRUCTIONS),
            )
            self.assertTrue(
                prompt.endswith(arena._Arena.MOVE_OUTPUT_INSTRUCTIONS)
            )

    def test_workspace_games_run_concurrently_and_cannot_reset_their_clock(self):
        for harness in ("codex-0h", "codex-1h"):
            name = f"gpt5.6-sol-low-{harness}"
            self.assertEqual(arena._llm_game_worker_count(name, 2), 2)
            self.assertEqual(arena._llm_game_worker_count(name, 1), 1)
            client = arena._CodexGameClient.__new__(arena._CodexGameClient)
            client.agentic_harness = harness
            with self.assertRaisesRegex(arena.WorkspaceError, "cannot reset"):
                client.reset_game()

    def test_workspace_mounts_persistent_codex_home_below_read_only_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            runtime = root / "runtime"
            codex_home = runtime / "codex-home"
            config = runtime / "config.toml"
            socket_path = root / "openai.sock"
            for directory in (workspace, runtime, codex_home):
                directory.mkdir(exist_ok=True)
            config.touch()
            socket_path.touch()
            sandbox = arena._WorkspaceBubblewrap(
                workspace, runtime, socket_path, binary="/fake/bwrap"
            )
            with (
                mock.patch.object(sandbox, "_binary", return_value="/fake/bwrap"),
                mock.patch.object(sandbox, "_launcher_prefix", return_value=()),
                mock.patch.object(sandbox, "_system_mounts", return_value=[]),
            ):
                command = sandbox.command(
                    ("/runtime/codex",),
                    {},
                    readonly_mounts=((config, "/harness-home/config.toml"),),
                    writable_mounts=((codex_home, "/harness-home"),),
                )

        writable = command.index(str(codex_home.resolve()))
        readonly = command.index(str(config.resolve()))
        self.assertEqual(command[writable - 1], "--bind")
        self.assertEqual(command[writable + 1], "/harness-home")
        self.assertEqual(command[readonly - 1], "--ro-bind")
        self.assertEqual(command[readonly + 1], "/harness-home/config.toml")
        self.assertLess(writable, readonly)

    def test_workspace_thread_resumes_and_aggregates_every_model_request(self):
        class FakeThread:
            def __init__(self, identity):
                self.id = identity

        class FakeCodex:
            def __init__(self):
                self.started = []
                self.resumed = []

            def thread_start(self, **options):
                self.started.append(options)
                return FakeThread("durable-thread")

            def thread_resume(self, thread_id, **options):
                self.resumed.append((thread_id, options))
                return FakeThread(thread_id)

        sdk = SimpleNamespace(
            ApprovalMode=SimpleNamespace(deny_all="deny"),
            Sandbox=SimpleNamespace(full_access="full-access"),
        )

        def client(path):
            value = arena._CodexGameClient.__new__(arena._CodexGameClient)
            value.player = arena._LLMPlayerConfig(
                "gpt-5.6-sol",
                "low",
                (5.0, 0.5, 30.0),
                agentic_harness="codex-0h",
            )
            value.agentic_harness = "codex-0h"
            value.state_path = path
            value._usage_total = None
            value._sdk = sdk
            value._codex = FakeCodex()
            value._thread = None
            return value

        def tokens(input_tokens, cached_tokens, output_tokens, reasoning_tokens):
            return SimpleNamespace(
                input_tokens=input_tokens,
                cached_input_tokens=cached_tokens,
                cache_write_input_tokens=0,
                output_tokens=output_tokens,
                reasoning_output_tokens=reasoning_tokens,
            )

        def result(last, total):
            return SimpleNamespace(usage=SimpleNamespace(last=last, total=total))

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "thread.json"
            first = client(state_path)
            first._persistent_thread()
            first_turn = first._turn_usage(
                result(tokens(40, 10, 5, 2), tokens(100, 25, 20, 8))
            )
            second_turn = first._turn_usage(
                result(tokens(70, 20, 9, 4), tokens(260, 80, 50, 20))
            )
            saved = json.loads(state_path.read_text(encoding="utf-8"))

            resumed = client(state_path)
            resumed._persistent_thread()
            resumed_turn = resumed._turn_usage(
                result(tokens(60, 15, 7, 3), tokens(400, 120, 75, 30))
            )

        self.assertEqual(first._codex.started[0]["ephemeral"], False)
        self.assertEqual(first_turn["input_tokens"], 100)
        self.assertEqual(second_turn["input_tokens"], 160)
        self.assertEqual(second_turn["output_tokens"], 30)
        self.assertEqual(saved["usage_total"]["input_tokens"], 260)
        self.assertEqual(resumed._codex.resumed[0][0], "durable-thread")
        self.assertEqual(resumed_turn["input_tokens"], 140)
        self.assertEqual(resumed_turn["reasoning_output_tokens"], 10)

    def test_proxy_writes_a_condensed_human_readable_log(self):
        output_item = {
            "type": "custom_tool_call",
            "name": "exec_command",
            "input": "curl https://example.com",
            "encrypted_content": "opaque-response-ciphertext",
        }
        completed = {
            "type": "response.completed",
            "response": {
                "id": "response-1",
                "status": "completed",
                "model": "gpt-5.6-sol",
                "output": [],
                "usage": {
                    "input_tokens": 123,
                    "output_tokens": 45,
                },
            },
        }
        stream = "\n".join(
            (
                "event: response.output_item.done",
                "data: "
                + json.dumps(
                    {"type": "response.output_item.done", "item": output_item}
                ),
                "event: response.output_text.delta",
                "data: "
                + json.dumps(
                    {
                        "type": "response.output_text.delta",
                        "delta": "discarded streaming delta",
                    }
                ),
                "event: response.completed",
                "data: " + json.dumps(completed),
            )
        )
        entry = {
            "schema_version": 1,
            "exchange_id": "exchange-1",
            "started_at": "2026-08-26T00:00:00+00:00",
            "completed_at": "2026-08-26T00:00:01+00:00",
            "auth_mode": "oauth",
            "method": "POST",
            "path": "/v1/responses",
            "request_headers": {"Authorization": "Bearer secret"},
            "request_body": {
                "model": "gpt-5.6-sol",
                "input": [
                    {
                        "type": "reasoning",
                        "encrypted_content": "opaque-request-ciphertext",
                    }
                ],
            },
            "potential_internet_tool_calls": [
                {"reason": "network-oriented shell command"}
            ],
            "ok": True,
            "response_status": 200,
            "response_body": stream,
        }

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "openai-proxy.jsonl"
            proxy = arena._OpenAIReverseProxy(
                SimpleNamespace(auth_mode="oauth"), log_path
            )
            try:
                proxy._server.append_log(entry)
            finally:
                proxy.close()
            machine_lines = log_path.read_text(encoding="utf-8").splitlines()
            readable = (Path(tmp) / "openai-proxy-readable.log").read_text(
                encoding="utf-8"
            )

        self.assertEqual(len(machine_lines), 2)
        self.assertEqual(json.loads(machine_lines[1])["response_body"], stream)
        self.assertIn("PROXY STARTED", readable)
        self.assertIn("EXCHANGE exchange-1", readable)
        self.assertIn("potential internet tool calls: 1", readable)
        self.assertIn("network-oriented shell command", readable)
        self.assertIn('"input_tokens": 123', readable)
        self.assertIn('"input": "curl https://example.com"', readable)
        self.assertIn("opaque field omitted from readable log", readable)
        self.assertNotIn("opaque-request-ciphertext", readable)
        self.assertNotIn("opaque-response-ciphertext", readable)
        self.assertNotIn("discarded streaming delta", readable)
        response_flags = arena._potential_internet_tool_flags(
            arena._proxy_stream_events(stream), source="response"
        )
        self.assertTrue(
            any(
                flag["reason"] == "network-oriented shell command"
                for flag in response_flags
            )
        )

    def test_workspace_manifests_distinguish_persistence_modes(self):
        isolated = arena._llm_player_manifest(
            "gpt5.6-sol-low-codex-0h"
        )
        continual = arena._llm_player_manifest(
            "gpt5.6-luna-max-codex-1h"
        )

        self.assertEqual(isolated["conversation"], "independent_checkpoint_copy_per_game")
        self.assertEqual(continual["conversation"], isolated["conversation"])
        self.assertEqual(continual["persistence"], isolated["persistence"])
        self.assertEqual(isolated["preparation_seconds"], 0)
        self.assertEqual(continual["preparation_seconds"], 3600)
        self.assertTrue(isolated["workspace_retained"])
        self.assertTrue(continual["workspace_retained"])
        self.assertEqual(continual["sandbox"], "bubblewrap_workspace_write")

    def test_codex_cost_uses_last_turn_tokens_and_long_context_tier(self):
        usage = {
            "input_tokens": 1_000,
            "input_tokens_details": {"cached_tokens": 100},
            "output_tokens": 200,
            "output_tokens_details": {"reasoning_tokens": 50},
        }
        cost = arena._llm_call_cost(usage, "openai_codex_workspace", "gpt-5.6-sol")
        self.assertAlmostEqual(cost, (900 * 4 + 100 * 0.4 + 200 * 20) / 1e6)
        self.assertGreater(cost, 0)

        long_usage = usage | {"input_tokens": 272_001}
        long_cost = arena._llm_call_cost(
            long_usage, "openai_codex_workspace", "gpt-5.6-sol"
        )
        expected = ((272_001 - 100) * 8 + 100 * 0.8 + 200 * 30) / 1e6
        self.assertAlmostEqual(long_cost, expected)

    def test_workspace_bridge_relays_a_backpressured_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unix_path = root / "proxy.sock"
            ready_path = root / "ready"
            launcher_path = root / "launcher.py"
            launcher_path.write_text(
                arena._workspace_proxy_launcher(), encoding="utf-8"
            )

            unix_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            unix_server.bind(str(unix_path))
            unix_server.listen()

            def echo():
                connection, _address = unix_server.accept()
                with connection:
                    while data := connection.recv(65536):
                        connection.sendall(data)

            echo_thread = threading.Thread(target=echo, daemon=True)
            echo_thread.start()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]

            environment = os.environ | {
                "ARENA_PROXY_PORT": str(port),
                "ARENA_PROXY_SOCKET": str(unix_path),
                "ARENA_PROXY_READY_PATH": str(ready_path),
            }
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(launcher_path),
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            try:
                deadline = time.monotonic() + 5
                while not ready_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready_path.exists())

                payload = bytes(range(256)) * 32768
                with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
                    client.settimeout(10)
                    send_thread = threading.Thread(
                        target=lambda: (
                            client.sendall(payload),
                            client.shutdown(socket.SHUT_WR),
                        ),
                        daemon=True,
                    )
                    send_thread.start()
                    received = bytearray()
                    while chunk := client.recv(65536):
                        received.extend(chunk)
                    send_thread.join(timeout=5)
                    self.assertFalse(send_thread.is_alive())
                self.assertEqual(received, payload)
            finally:
                if process.poll() is None:
                    process.terminate()
                _stdout, stderr = process.communicate(timeout=5)
                unix_server.close()
                echo_thread.join(timeout=2)

        self.assertNotIn('"event":"relay_error"', stderr)

    @mock.patch.object(arena._CodexGameClient, "_run_turn", _fake_codex_run_turn)
    def test_workspace_transport_failure_restarts_runtime_and_is_retryable(self):
        message = "stream disconnected before completion: idle timeout waiting for SSE"
        self.assertTrue(arena._workspace_codex_transport_failure(RuntimeError(message)))
        self.assertTrue(
            arena._workspace_codex_transport_failure(
                RuntimeError(
                    "stream disconnected before completion: error sending request "
                    "for url (http://127.0.0.1:8765/v1/responses)"
                )
            )
        )
        self.assertFalse(
            arena._workspace_codex_transport_failure(
                RuntimeError("unrelated model runtime failure")
            )
        )

        class FakeThread:
            def run(self, _prompt, **_options):
                raise RuntimeError(message)

        class FakeCodex:
            def __init__(self):
                self.closed = False
                self._client = SimpleNamespace(
                    _stderr_tail=lambda _limit: (
                        'ARENA_BRIDGE {"event":"relay_error",'
                        '"direction":"unix_to_tcp"}'
                    )
                )

            def close(self):
                self.closed = True

        class FakeProxy:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            marker = workspace / "persistent.txt"
            marker.write_text("keep\n", encoding="utf-8")
            client = arena._CodexGameClient.__new__(arena._CodexGameClient)
            client.player = arena._LLMPlayerConfig(
                "gpt-5.6-sol",
                "low",
                (5.0, 0.5, 30.0),
                agentic_harness="codex-0h",
            )
            client.agentic_harness = "codex-0h"
            client.private_dir = root
            client.cwd = workspace
            client._runtime_generation = 1
            client._sdk = SimpleNamespace(
                ApprovalMode=SimpleNamespace(deny_all="deny"),
                Sandbox=SimpleNamespace(full_access="full-access"),
            )
            codex, proxy = FakeCodex(), FakeProxy()
            client._codex = codex
            client._proxy = proxy
            client._thread = FakeThread()
            client._start_runtime = lambda: None

            with self.assertRaises(arena._WorkspaceCodexTransportError) as raised:
                client.create(
                    model="gpt-5.6-sol",
                    input="move",
                    reasoning={"effort": "low"},
                )

            event = json.loads((root / "runtime-events.jsonl").read_text())
            marker_text = marker.read_text(encoding="utf-8")

        self.assertEqual(str(raised.exception), message)
        self.assertTrue(arena._retryable_llm_api_error(raised.exception))
        self.assertTrue(codex.closed)
        self.assertTrue(proxy.closed)
        self.assertIsNone(client._codex)
        self.assertIsNone(client._proxy)
        self.assertIsNone(client._thread)
        self.assertEqual(marker_text, "keep\n")
        self.assertEqual(event["event"], "workspace_runtime_restart")
        self.assertEqual(event["bridge_events"][0]["event"], "relay_error")


if __name__ == "__main__":
    unittest.main()
