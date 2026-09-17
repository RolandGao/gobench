"""Run configured KataGo or LLM 9x9 Go arenas and estimate Elo ratings."""

# Edit CONFIG immediately below the imports to choose the default experiment.
# Execution: main -> run_arena -> _ArenaRun.execute.
# _Arena holds fixed defaults, _State the configured process state, and
# _ArenaRun the live state of one run directory.

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import csv
import datetime as dt
import fcntl
import hashlib
import http.client
import http.server
import json
import math
import multiprocessing
import os
import random
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import asdict, astuple, dataclass, fields, replace
from functools import cache, partial
from itertools import islice, pairwise
from pathlib import Path
from typing import ClassVar

import numpy as np

from gobench.anthropic_oauth import IDENTITY as CLAUDE_OAUTH_IDENTITY
from gobench.anthropic_oauth import AnthropicClient, ClaudeOAuthError
from gobench.arena_config import (
    ArenaConfig,
    _CHEAP_B6C96_PLAYER_POOL,
    _CODEX_TRAINING_SECONDS,
    _CODEX_WORKSPACE_HARNESSES,
    _CURRENT_PLAYER_POOL,
    _IGNORED_REPORT_PLAYERS,
    _MULTI_PLAYOUT_PLAYER_POOL,
    _NO_MULTI_PLAYOUT_PLAYER_POOL,
    _TEMPERATURE_PLAYER_POOL,
    _llm_player_name,
    build_run_types,
)
from gobench.game_engine import COLS, GameResult, GoEngineError, KataGoGameEngine
from gobench.workspace_runtime import (
    PROTOCOL_VERSION as WORKSPACE_PROTOCOL_VERSION,
    AgentClock,
    CoreLease,
    ProcessScope,
    WorkspaceError,
    WorkspaceSettings,
    WorkspaceResourceExceeded,
    WorkspaceTimeExpired,
    WorkspaceVolume,
    atomic_json as _workspace_atomic_json,
    copy_image as _copy_workspace_image,
    file_sha256 as _workspace_file_sha256,
    read_json as _workspace_read_json,
    runtime_identity as _workspace_runtime_identity,
)
from gobench.go_rules import LEGALITY_ENFORCEMENT_VERSION
from gobench.llm_conversation import (
    CONTEXT_RESET_TOKENS,
    CONVERSATION_VERSION,
    APIConversation,
    ConversationClient,
    qwen_cache_messages,
    cap_output_to_context,
)
from gobench.llm_conversation import (
    context_length_error as _context_length_error,
)
from gobench.strategies import (
    KATAGO_BINARY as KATAGO_CPU_BINARY,
)
from gobench.strategies import (
    KATAGO_CONFIG,
    KATAGO_CUDA_BINARY,
    KATAGO_MODEL,
    KATAGO_NETWORKS,
    KataGoNetworkStrategy,
    NetworkSpec,
    ensure_arena_networks,
    ensure_katago_cuda_installed,
    ensure_katago_installed,
)


# Keep the four KataGo-only baselines (320,000 games) and all recent LLM runs,
# including committed games from runs that are still in progress.
# Older LLM evaluations remain below, commented out.
# Add a named LLM run here to authorize extending its existing directory.
_FINAL_RUNS = (
    "arena_20260717_215813_957127_3b740750",
    "arena_20260722_210708_427338_47435160",
    "arena_20260723_055601_438304_148a54e8",
    "arena_20260805_040447_246130_2072c54f",
    "DeepSeek-V4-Flash-0731-high-api-multi2",
    "DeepSeek-V4-Flash-0731-max-api-multi",
    "DeepSeek-V4.1-Flash-high-api-multi",
    "DeepSeek-V4.1-Flash-max-api-multi",
    "gemini-3.6-flash-high-api-multi",
    "gemini-3.8-flash-high-api-multi",
    "gemini-3.1-pro-high-api-multi",
    "gpt5.6-luna-high-api-multi",
    "gpt5.6-luna-max-api-multi",
    "gpt5.6-sol-high-api-multi4",
    "gpt5.6-sol-max-api-multi",
    "gpt6-astra-high-api-multi",
    "gpt6-astra-high-api",
    "gpt6-astra-max-api-multi",
    "grok-4.6-high-api-multi2",
    "grok-4.6-xhigh-api-multi",
    "muse-spark-1.3-contributor-high-api-multi",
    "muse-spark-1.3-contributor-xhigh-api-multi",
    # "opus-5-high-api-multi",
    "opus-5-high-api-multi2",
    "gpt6-astra-high-codex-1h",
    "gpt6-astra-high-codex-0h",
    "gpt6-astra-high-codex-2h",
    "gpt6-astra-high-codex-4h",
    "gpt6-astra-high-codex-8h",
    "gpt5.6-sol-high-codex-0h",
    "gpt5.6-sol-high-codex-1h",
    "gpt5.6-sol-high-codex-2h",
    "gpt5.6-sol-high-codex-4h",
    "gpt5.6-sol-high-codex-8h",
)


# EDIT THIS BLOCK to choose the default experiment.
# Player pools and --run-type profiles live in
# gobench/arena_config.py. Only --resume loads settings from run.json.
CONFIG = ArenaConfig(
    active_players=(
        # "DeepSeek-V4.1-Flash-high-api-multi",
        # "DeepSeek-V4.1-Flash-max-api-multi",
        # "gpt6-astra-high-api",
        # "gpt6-astra-high-codex-1h",
        # "gpt6-astra-high-codex-0h",
        # "opus-5-high-api-multi2",
        # "gemini-3.1-pro-high-api-multi",
        # "DeepSeek-V4.1-Flash-high-api-multi",
        # "DeepSeek-V4.1-Flash-max-api-multi",
        # "gpt5.6-sol-high-codex-0h",
        # "gpt5.6-sol-high-codex-1h",
        # "gpt5.6-sol-high-codex-2h",
        # "gpt5.6-sol-high-codex-4h",
        # "gpt5.6-sol-high-codex-8h",
        "fable-5.1-max-api-multi",
        "opus-5-max-api-multi",
        # "gpt6-astra-high-codex-4h",
        # "gpt6-astra-high-codex-8h",
        # "gpt6-astra-high-api-multi",
        # "gpt6-astra-max-api-multi",
    ),
    opponent_players=_CURRENT_PLAYER_POOL,
    total_games=14,
    batch_games=2,
    past_run_names=_FINAL_RUNS,
    ignore_players=tuple(),
    active_player_prior_elo_mean=2000.0,
    active_player_prior_elo_sd=2000.0,
)


RUN_TYPES = build_run_types(_FINAL_RUNS)


@dataclass(frozen=True)
class _LLMPlayerConfig:
    model: str
    level: str
    prices: tuple[float, float, float]
    agentic_harness: str = "api"
    cache_write_price: float | None = None
    max_output_tokens: int | None = None
    context_window: int | None = None
    route: str | None = None
    peak_prices: tuple[float, float, float] | None = None
    peak_utc_hours: tuple[tuple[int, int], ...] = ()
    reprice_past_runs: bool = False
    peak_utc_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    long_context_min_tokens: int | None = None
    long_context_multipliers: tuple[float, float, float] = (1.0, 1.0, 1.0)
    scheduled_prices: tuple[tuple[str, tuple[float, float, float]], ...] = ()


@dataclass(frozen=True)
class _LLMAPIConfig:
    name: str
    players: dict[str, _LLMPlayerConfig]
    sdk_module: str
    sdk_client_path: tuple[str, ...]
    api_key_env: str
    manifest_kind: str
    manifest_level_name: str
    protocol: type[_LLMProtocol]
    endpoint_path: tuple[str, ...]
    base_url: str | None = None
    key_file_env: str | None = None
    key_file_default: str | None = None
    client_options: tuple[tuple[str, object], ...] = (
        ("timeout", None),
        ("max_retries", 0),
    )
    request_options: tuple[tuple[str, object], ...] = ()
    max_tokens_field: str | None = None
    cost_tracking: bool = False
    raw_response: bool = False


@dataclass(frozen=True)
class _LLMTokenUsage:
    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    reasoning_tokens: int


@dataclass(frozen=True)
class _OpenAIProxyCredential:
    bearer_token: str
    host: str
    path_prefix: str = ""
    headers: tuple[tuple[str, str], ...] = ()
    auth_mode: str = "api_key"

    def upstream_path(self, path):
        if not self.path_prefix:
            return path
        return f"{self.path_prefix}{path.removeprefix('/v1')}"


class _LLMProtocol:
    """Wire-format adapter used by entries in the LLM API registry."""

    cached_input_is_in_input = True
    reasoning_is_billed = False

    @staticmethod
    def manifest_options(_player):
        return {}

    @staticmethod
    def request_options(_player, _prompt):
        raise NotImplementedError

    @staticmethod
    def response_text(_response):
        raise NotImplementedError

    usage_fields: ClassVar[dict[str, str]] = {}

    @classmethod
    def token_usage(cls, usage):
        if not cls.usage_fields:
            raise NotImplementedError
        return _LLMTokenUsage(
            **{
                field.name: _first_token_count(usage, cls.usage_fields[field.name])
                if field.name in cls.usage_fields
                else 0
                for field in fields(_LLMTokenUsage)
            }
        )


class _ResponsesProtocol(_LLMProtocol):
    @staticmethod
    def request_options(player, prompt):
        return {
            "reasoning": {"effort": player.level},
            "input": prompt,
            "store": False,
        }

    @staticmethod
    def response_text(response):
        return getattr(response, "output_text", "")

    usage_fields = {
        "input_tokens": "input_tokens",
        "cached_input_tokens": "input_tokens_details.cached_tokens",
        "cache_write_tokens": "input_tokens_details.cache_write_tokens",
        "output_tokens": "output_tokens",
        "reasoning_tokens": "output_tokens_details.reasoning_tokens",
    }


def _deepseek_dummy_tool_options(*, responses=False):
    # DeepSeek retains previous reasoning when tools are supplied, even on
    # turns without tool calls. Keep the arena's move-only response contract.
    function = {
        "name": "arena_noop",
        "description": "Unused placeholder. Return the requested move directly.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }
    tool = {"type": "function"} | (function if responses else {"function": function})
    return {"tools": [tool], "tool_choice": "none"}


class _DeepSeekResponsesProtocol(_ResponsesProtocol):
    @staticmethod
    def manifest_options(_player):
        return _deepseek_dummy_tool_options(responses=True)

    @staticmethod
    def request_options(player, prompt):
        return _ResponsesProtocol.request_options(player, prompt) | (
            _deepseek_dummy_tool_options(responses=True)
        )


class _CodexProtocol(_ResponsesProtocol):
    """Log/pricing adapter for the Codex SDK's Responses-derived usage."""


class _OAuthResponsesProtocol(_ResponsesProtocol):
    """Direct subscription Responses calls, without an agent runtime."""

    @staticmethod
    def manifest_options(_player):
        return {
            "auth_mode": "chatgpt_oauth",
            "cost_basis": "api_equivalent_estimate",
        }

    @staticmethod
    def request_options(player, prompt):
        return _ResponsesProtocol.request_options(player, prompt) | {
            "stream": True,
            "include": ["reasoning.encrypted_content"],
        }


class _ChatProtocol(_LLMProtocol):
    @staticmethod
    def response_text(response):
        choices = getattr(response, "choices", ())
        message = getattr(choices[0], "message", None) if choices else None
        return getattr(message, "content", "")


class _OpenRouterChatProtocol(_ChatProtocol):
    @staticmethod
    def manifest_options(player):
        return {"reasoning": {"effort": player.level, "exclude": False}}

    @staticmethod
    def request_options(player, prompt):
        extra_body = {"reasoning": {"effort": player.level, "exclude": False}}
        if player.route is not None:
            extra_body["provider"] = {
                "order": [player.route],
                "allow_fallbacks": False,
            }
        return {
            "messages": (qwen_cache_messages([{"role": "user", "content": prompt}])
                         if player.route == "alibaba" else [{"role": "user", "content": prompt}]),
            "stream": False,
            "extra_body": extra_body,
        }

    usage_fields = {
        "input_tokens": "prompt_tokens",
        "cached_input_tokens": "prompt_tokens_details.cached_tokens",
        "cache_write_tokens": "prompt_tokens_details.cache_write_tokens",
        "output_tokens": "completion_tokens",
        "reasoning_tokens": "completion_tokens_details.reasoning_tokens",
    }


class _DeepSeekChatProtocol(_ChatProtocol):
    @staticmethod
    def manifest_options(player):
        return {
            "thinking": {"type": "disabled" if player.level == "none" else "enabled"},
            "system_message": None,
            **_deepseek_dummy_tool_options(),
        }

    @staticmethod
    def request_options(player, prompt):
        return {
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            **({"reasoning_effort": player.level} if player.level != "none" else {}),
            "extra_body": {
                "thinking": {"type": "disabled" if player.level == "none" else "enabled"}
            },
            **_deepseek_dummy_tool_options(),
        }

    usage_fields = {
        "input_tokens": "prompt_tokens",
        "cached_input_tokens": "prompt_cache_hit_tokens",
        "output_tokens": "completion_tokens",
        "reasoning_tokens": "completion_tokens_details.reasoning_tokens",
    }


class _GoogleInteractionsProtocol(_LLMProtocol):
    reasoning_is_billed = True

    @staticmethod
    def manifest_options(_player):
        return {"store": False}

    @staticmethod
    def request_options(player, prompt):
        return {
            "input": prompt,
            "generation_config": {"thinking_level": player.level},
            "store": False,
        }

    @staticmethod
    def response_text(response):
        return getattr(response, "output_text", "")

    usage_fields = {
        "input_tokens": "total_input_tokens",
        "cached_input_tokens": "total_cached_tokens",
        "output_tokens": "total_output_tokens",
        "reasoning_tokens": "total_thought_tokens",
    }


class _AnthropicMessagesProtocol(_LLMProtocol):
    cached_input_is_in_input = False

    @staticmethod
    def manifest_options(_player):
        return {
            "thinking": {"type": "adaptive"},
            "cache_control": {"type": "ephemeral"},
            "auth_mode": "oauth",
            "cost_basis": "api_equivalent_tokens; subscription OAuth",
            "oauth_system_prompt": CLAUDE_OAUTH_IDENTITY,
        }

    @staticmethod
    def request_options(player, prompt):
        return {
            "messages": [{"role": "user", "content": prompt}],
            # Anthropic requires opt-in even for identical history prefixes.
            # Automatic caching advances the breakpoint as each game grows.
            "thinking": {"type": "adaptive"},
            "cache_control": {"type": "ephemeral"},
            "output_config": {"effort": player.level},
        }

    @staticmethod
    def response_text(response):
        return "".join(
            getattr(block, "text", "")
            for block in getattr(response, "content", ())
            if getattr(block, "type", None) == "text"
        )

    usage_fields = {
        "input_tokens": "input_tokens",
        "cached_input_tokens": "cache_read_input_tokens",
        "cache_write_tokens": "cache_creation_input_tokens",
        "output_tokens": "output_tokens",
    }


def _env(name, default, cast=int):
    return cast(os.environ.get(f"ARENA_{name}", default))


def _llm_effort_players(label, model, efforts, prices, *, suffix="api", **options):
    """Register each API effort while sharing model pricing and request limits."""
    return {
        _llm_player_name(f"{label}-{effort}", suffix): _LLMPlayerConfig(
            model, effort, prices, **options
        )
        for effort in efforts
    }


def _with_multi_turn_players(api):
    return replace(
        api,
        players={
            **api.players,
            **{
                f"{name}-multi": replace(player, agentic_harness="api-multi")
                for name, player in api.players.items()
                if player.agentic_harness == "api"
            },
        },
    )


def _agent_players(harnesses):
    """The same Sol/Luna effort matrix is available through each agent harness."""
    return {
        _llm_player_name(
            f"gpt5.6-{family}-{effort}", agentic_harness
        ): _LLMPlayerConfig(
            f"gpt-5.6-{family}",
            effort,
            (4.0, 0.4, 20.0) if family == "sol" else (0.2, 0.02, 1.2),
            agentic_harness=agentic_harness,
            cache_write_price=5.0 if family == "sol" else 0.25,
            max_output_tokens=128_000,
            long_context_min_tokens=272_001,
            long_context_multipliers=(2.0, 2.0, 1.5),
        )
        for family in ("sol", "luna")
        for effort in ("low", "high", "max")
        for agentic_harness in harnesses
    }


class _Arena:
    """Fixed implementation details, derived manifests, and process tuning."""

    ROOT = Path(__file__).resolve().parent
    LOG_ROOT = ROOT / "log"
    UNTRACKED_LOG_ROOT = ROOT / "untracked_log"
    BOARD_SIZE, KOMI, RULES = 9, 7.0, "tromp-taylor"
    MAX_MOVES, MAX_VISITS = 1000, 1
    ORIGINAL_TEMPERATURE_EARLY, ORIGINAL_TEMPERATURE = 0.5, 0.1
    LOW_LATE_TEMPERATURE = 0.3
    NUM_SEARCH_THREADS = 1
    PLAYOUT_MAX_VISITS = 100_000_000
    KATAGO_PLAYOUT_COUNTS = 60, 600
    KATAGO_TOP_NETWORK_COUNT = 4
    EXCLUDED_MATCHMAKING_NETWORKS = frozenset({"kata1-zhizi-b40c768nbt-fdx6c"})
    ANCHOR = "kata1-random"
    PLAYOUTS_SUFFIX = re.compile(r"-playouts([1-9][0-9]*)$")
    TEMPERATURE_SUFFIX = re.compile(r"-temp-(0\.[0-9]+)$")

    # Standard token rates checked 2026-09-07 against provider pricing docs:
    # https://developers.openai.com/api/docs/pricing (Sol promotional rates)
    # https://api-docs.deepseek.com/quick_start/pricing/
    # https://ai.google.dev/gemini-api/docs/pricing
    # https://docs.x.ai/developers/pricing
    # API efforts checked 2026-09-07 against provider docs and OpenRouter's
    # /api/v1/models reasoning.supported_efforts. Accepted aliases are included:
    # Grok 4.5 xhigh -> high; DeepSeek medium/xhigh -> high, minimal -> low
    # (Responses only). OpenRouter Qwen levels follow its gateway catalog.
    # Output maxima checked 2026-09-16: provider model docs and OpenRouter's
    # /api/v1/models/{model}/endpoints for the configured Meta/Moonshot/Alibaba routes.
    # Codex OAuth rejects max_output_tokens: its server controls the GPT limit.
    # Grok has no separate text-output limit; omit an artificial cap.
    # LLM API registry. Add one _LLMAPIConfig here for an API that uses an
    # existing protocol. For a new wire format, first add one adjacent
    # _LLMProtocol subclass above. Manifests, clients, calls, logs, and pricing
    # are derived from this registry everywhere else.
    LLM_APIS: ClassVar[tuple[_LLMAPIConfig, ...]] = (
        _LLMAPIConfig(
            name="openai_codex_workspace",
            players={
                **_agent_players(_CODEX_TRAINING_SECONDS),
                **{
                    name: player
                    for harness in _CODEX_TRAINING_SECONDS
                    for name, player in _llm_effort_players(
                        "gpt6-astra", "gpt-6-astra",
                        ("low", "medium", "high", "xhigh", "max"),
                        (10.0, 1.0, 50.0),
                        suffix=harness,
                        agentic_harness=harness,
                        cache_write_price=12.5,
                        max_output_tokens=128_000,
                        long_context_min_tokens=272_001,
                        long_context_multipliers=(2.0, 2.0, 1.5),
                    ).items()
                },
            },
            sdk_module="openai_codex",
            sdk_client_path=("Codex",),
            api_key_env="",
            manifest_kind="openai_codex_workspace_agent",
            manifest_level_name="reasoning_effort",
            protocol=_CodexProtocol,
            endpoint_path=(),
            cost_tracking=True,
        ),
        _LLMAPIConfig(
            name="openai",
            players={
                **_llm_effort_players(
                    "gpt-5.4",
                    "gpt-5.4",
                    ("none", "low", "medium", "high", "xhigh"),
                    (2.5, 0.25, 15.0),
                    max_output_tokens=128_000,
                    long_context_min_tokens=272_001,
                    long_context_multipliers=(2.0, 2.0, 1.5),
                ),
                **_llm_effort_players(
                    "gpt-5.5",
                    "gpt-5.5",
                    ("none", "low", "medium", "high", "xhigh"),
                    (5.0, 0.5, 30.0),
                    max_output_tokens=128_000,
                    long_context_min_tokens=272_001,
                    long_context_multipliers=(2.0, 2.0, 1.5),
                ),
                **_llm_effort_players(
                    "gpt5.6-sol",
                    "gpt-5.6-sol",
                    ("none", "low", "medium", "high", "xhigh", "max"),
                    (4.0, 0.4, 20.0),
                    cache_write_price=5.0,
                    max_output_tokens=128_000,
                    long_context_min_tokens=272_001,
                    long_context_multipliers=(2.0, 2.0, 1.5),
                ),
                **_llm_effort_players(
                    "gpt5.6-luna",
                    "gpt-5.6-luna",
                    ("none", "low", "medium", "high", "xhigh", "max"),
                    (0.2, 0.02, 1.2),
                    cache_write_price=0.25,
                    max_output_tokens=128_000,
                    long_context_min_tokens=272_001,
                    long_context_multipliers=(2.0, 2.0, 1.5),
                ),
                **_llm_effort_players(
                    "gpt6-astra",
                    "gpt-6-astra",
                    ("low", "medium", "high", "xhigh", "max"),
                    (10.0, 1.0, 50.0),
                    cache_write_price=12.5,
                    max_output_tokens=128_000,
                    long_context_min_tokens=272_001,
                    long_context_multipliers=(2.0, 2.0, 1.5),
                ),
            },
            sdk_module="openai",
            sdk_client_path=("OpenAI",),
            api_key_env="",
            manifest_kind="openai_responses_api",
            manifest_level_name="reasoning_effort",
            protocol=_OAuthResponsesProtocol,
            endpoint_path=("responses",),
            base_url="https://chatgpt.com/backend-api/codex",
        ),
        _LLMAPIConfig(
            name="meta",
            players={
                **_llm_effort_players(
                    "muse-spark-1.2",
                    "muse-spark-1.2",
                    ("minimal", "low", "medium", "high", "xhigh"),
                    (1.25, 0.15, 4.25),
                    max_output_tokens=943_718,
                    context_window=1_048_576,
                ),
                **_llm_effort_players(
                    "muse-spark-1.3-contributor",
                    "muse-spark-1.3-contributor",
                    ("minimal", "low", "medium", "high", "xhigh", "max"),
                    (0.1, 0.002, 0.2),
                    max_output_tokens=943_718,
                    context_window=1_048_576,
                ),
            },
            sdk_module="openai",
            sdk_client_path=("OpenAI",),
            api_key_env="MODEL_API_KEY",
            manifest_kind="meta_responses_api",
            manifest_level_name="reasoning_effort",
            protocol=_ResponsesProtocol,
            endpoint_path=("responses",),
            base_url="https://api.meta.ai/v1",
            max_tokens_field="max_output_tokens",
            cost_tracking=True,
        ),
        _LLMAPIConfig(
            name="xai",
            players={
                **_llm_effort_players(
                    "grok-4.5",
                    "grok-4.5",
                    ("low", "medium", "high", "xhigh"),
                    (2.0, 0.3, 6.0),
                    long_context_min_tokens=200_000,
                    long_context_multipliers=(2.0, 2.0, 2.0),
                ),
                **_llm_effort_players(
                    "grok-4.6",
                    "grok-4.6",
                    ("low", "medium", "high", "xhigh"),
                    (2.0, 0.5, 6.0),
                    long_context_min_tokens=200_000,
                    long_context_multipliers=(2.0, 2.0, 2.0),
                ),
            },
            sdk_module="openai",
            sdk_client_path=("OpenAI",),
            api_key_env="XAI_API_KEY",
            manifest_kind="xai_responses_api",
            manifest_level_name="reasoning_effort",
            protocol=_ResponsesProtocol,
            endpoint_path=("responses",),
            base_url="https://api.x.ai/v1",
            cost_tracking=True,
        ),
        _LLMAPIConfig(
            name="deepseek_responses",
            players={
                # Historical V4 label; its API endpoint now aliases V4.1 Flash.
                # Use the V4.1 player names below for new evaluations.
                **_llm_effort_players(
                    "DeepSeek-V4-Flash-0731",
                    "deepseek-v4-flash",
                    ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
                    (0.22, 0.007, 0.66),
                    max_output_tokens=393_216,
                    peak_prices=(0.44, 0.014, 1.32),
                    peak_utc_hours=((1, 4), (6, 10)),
                    peak_utc_weekdays=(0, 1, 2, 3, 4),
                    reprice_past_runs=True,
                ),
                # V4.1 release and pricing checked 2026-09-10:
                # https://api-docs.deepseek.com/quick_start/pricing/
                **_llm_effort_players(
                    "DeepSeek-V4.1-Flash",
                    "deepseek-flash",
                    ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
                    (0.15, 0.003, 0.6),
                    max_output_tokens=393_216,
                    peak_prices=(0.3, 0.006, 1.2),
                    peak_utc_hours=((1, 4), (6, 10)),
                    peak_utc_weekdays=(0, 1, 2, 3, 4),
                ),
            },
            sdk_module="openai",
            sdk_client_path=("OpenAI",),
            api_key_env="DEEPSEEK_API_KEY",
            manifest_kind="deepseek_responses_api",
            manifest_level_name="reasoning_effort",
            protocol=_DeepSeekResponsesProtocol,
            endpoint_path=("responses",),
            base_url="https://api.deepseek.com",
            max_tokens_field="max_output_tokens",
            cost_tracking=True,
        ),
        _LLMAPIConfig(
            name="openrouter",
            players={
                **_llm_effort_players(
                    "qwen3.8-max",
                    "qwen/qwen3.8-max",
                    ("minimal", "low", "medium", "high", "xhigh"),
                    (2.0, 0.25, 6.0),
                    max_output_tokens=131_072,
                    route="alibaba",
                    cache_write_price=2.5,
                ),
                **_llm_effort_players(
                    "kimi-k3",
                    "moonshotai/kimi-k3",
                    ("low", "high", "max"),
                    (3.0, 0.3, 15.0),
                    route="moonshotai/mxfp4",
                    max_output_tokens=943_718,
                    context_window=1_048_576,
                ),
                **_llm_effort_players(
                    "muse-spark-1.2-openrouter",
                    "meta/muse-spark-1.2",
                    ("minimal", "low", "medium", "high", "xhigh"),
                    (1.25, 0.15, 4.25),
                    route="meta",
                    max_output_tokens=943_718,
                    context_window=1_048_576,
                ),
            },
            sdk_module="openai",
            sdk_client_path=("OpenAI",),
            api_key_env="OPENROUTER_API_KEY",
            manifest_kind="openrouter_chat_completions_api",
            manifest_level_name="reasoning_effort",
            protocol=_OpenRouterChatProtocol,
            endpoint_path=("chat", "completions"),
            base_url="https://openrouter.ai/api/v1",
            max_tokens_field="max_completion_tokens",
            cost_tracking=True,
            raw_response=True,
        ),
        _LLMAPIConfig(
            name="deepseek",
            players={
                **_llm_effort_players(
                    "deepseek-v4-pro",
                    "deepseek-v4-pro",
                    ("none", "low", "medium", "high", "xhigh", "max"),
                    (0.66, 0.022, 1.98),
                    max_output_tokens=393_216,
                    peak_prices=(1.32, 0.044, 3.96),
                    peak_utc_hours=((1, 4), (6, 10)),
                    peak_utc_weekdays=(0, 1, 2, 3, 4),
                ),
                # Preserve the original high-effort player name for saved runs.
                _llm_player_name("deepseek-v4-pro"): _LLMPlayerConfig(
                    "deepseek-v4-pro", "high", (0.66, 0.022, 1.98),
                    max_output_tokens=393_216,
                    peak_prices=(1.32, 0.044, 3.96),
                    peak_utc_hours=((1, 4), (6, 10)),
                    peak_utc_weekdays=(0, 1, 2, 3, 4),
                ),
            },
            sdk_module="openai",
            sdk_client_path=("OpenAI",),
            api_key_env="DEEPSEEK_API_KEY",
            manifest_kind="deepseek_chat_completions_api",
            manifest_level_name="reasoning_effort",
            protocol=_DeepSeekChatProtocol,
            endpoint_path=("chat", "completions"),
            base_url="https://api.deepseek.com",
            max_tokens_field="max_tokens",
            cost_tracking=True,
        ),
        _LLMAPIConfig(
            name="google",
            players={
                **_llm_effort_players(
                    "gemini-3.6-flash",
                    "gemini-3.6-flash",
                    ("minimal", "low", "medium", "high"),
                    (0.75, 0.075, 3.75),
                    max_output_tokens=65_536,
                    scheduled_prices=(("2027-01-01", (1.5, 0.15, 7.5)),),
                ),
                **_llm_effort_players(
                    "gemini-3.8-flash",
                    "gemini-3.8-flash",
                    ("low", "medium", "high"),
                    (0.75, 0.075, 3.75),
                    max_output_tokens=65_536,
                    scheduled_prices=(("2027-01-01", (1.5, 0.15, 7.5)),),
                ),
                **_llm_effort_players(
                    "gemini-3.1-pro",
                    "gemini-3.1-pro-preview",
                    ("low", "medium", "high"),
                    (2.0, 0.2, 12.0),
                    max_output_tokens=65_536,
                    long_context_min_tokens=200_001,
                    long_context_multipliers=(2.0, 2.0, 1.5),
                ),
            },
            sdk_module="google",
            sdk_client_path=("genai", "Client"),
            api_key_env="GEMINI_API_KEY",
            manifest_kind="google_interactions_api",
            manifest_level_name="thinking_level",
            protocol=_GoogleInteractionsProtocol,
            endpoint_path=("interactions",),
            max_tokens_field="generation_config.max_output_tokens",
            client_options=(),
            cost_tracking=True,
        ),
        _LLMAPIConfig(
            name="anthropic",
            players={
                **_llm_effort_players(
                    "fable-5.1",
                    "claude-fable-5-1",
                    ("low", "medium", "high", "xhigh", "max"),
                    (10.0, 0.25, 50.0),
                    cache_write_price=12.5,
                    max_output_tokens=128_000,
                ),
                **_llm_effort_players(
                    "opus-5",
                    "claude-opus-5",
                    ("low", "medium", "high", "xhigh", "max"),
                    (5.0, 0.5, 25.0),
                    cache_write_price=6.25,
                    max_output_tokens=128_000,
                ),
            },
            sdk_module="anthropic",
            sdk_client_path=("Anthropic",),
            api_key_env="",
            manifest_kind="anthropic_messages_api",
            manifest_level_name="effort",
            protocol=_AnthropicMessagesProtocol,
            endpoint_path=("messages",),
            max_tokens_field="max_tokens",
            cost_tracking=True,
        ),
    )
    LLM_APIS = tuple(_with_multi_turn_players(api) for api in LLM_APIS)
    ACTIVE_LLM_PLAYERS = tuple(name for api in LLM_APIS for name in api.players)
    # These non-executable labels occur in _FINAL_RUNS.
    FINAL_RUN_LLM_PLAYERS = (
        "muse-spark-1.2-contributor-high-api",
        "gpt5.6-luna-high-codex-workspace",
        "gpt5.6-sol-high-codex-workspace",
        "gpt5.6-sol-low-codex-workspace",
        "gpt5.6-sol-max-codex-workspace",
        *(
            f"{model}-{effort}-codex-workspace-{mode}"
            for model in ("gpt5.6-sol", "gpt5.6-luna", "gpt6-astra")
            for effort in ("low", "medium", "high", "xhigh", "max")
            for mode in ("isolated", "continual")
        ),
    )
    RESULT_LLM_PLAYERS = (*ACTIVE_LLM_PLAYERS, *FINAL_RUN_LLM_PLAYERS)
    ACTIVE_LLM_PLAYER_SET = frozenset(ACTIVE_LLM_PLAYERS)
    RESULT_LLM_PLAYER_SET = frozenset(RESULT_LLM_PLAYERS)
    RESULT_API_LLM_PLAYER_SET = frozenset(
        name
        for api in LLM_APIS
        for name, player in api.players.items()
        if player.agentic_harness in {"api", "api-multi"}
    ) | frozenset(name for name in FINAL_RUN_LLM_PLAYERS if name.endswith("-api"))
    LLM_MODEL_PRICING_USD_PER_MILLION: ClassVar[dict[str, dict[str, object]]] = {
        player.model: {
            "input": player.prices[0],
            "cached_input": player.prices[1],
            "output": player.prices[2],
            **(
                {"cache_write": player.cache_write_price}
                if player.cache_write_price is not None
                else {}
            ),
            **(
                {
                    "peak_input": player.peak_prices[0],
                    "peak_cached_input": player.peak_prices[1],
                    "peak_output": player.peak_prices[2],
                    "peak_utc_hours": player.peak_utc_hours,
                    "peak_utc_weekdays": player.peak_utc_weekdays,
                }
                if player.peak_prices is not None
                else {}
            ),
            **(
                {
                    "long_context_min_tokens": player.long_context_min_tokens,
                    "long_context_multipliers": player.long_context_multipliers,
                }
                if player.long_context_min_tokens is not None
                else {}
            ),
            **(
                {"scheduled_prices": player.scheduled_prices}
                if player.scheduled_prices
                else {}
            ),
        }
        for api in LLM_APIS
        for player in api.players.values()
    }

    FINETUNED_9X9_NETWORK = NetworkSpec(
        name="kata9x9-b18c384nbt-20231025",
        rating=0.0,
        sha256="a1298ce1adc1dad7bd868ca962b2384cc8388ed373a00e6bae1114fa6f9e2d61",
        file_size=97878277,
        download_url="https://media.katagotraining.org/uploaded/networks/models_extra/"
        "kata9x9-b18c384nbt-20231025.bin.gz",
        file_name="kata9x9-b18c384nbt-20231025.bin.gz",
    )
    ALL_KATAGO_NETWORKS = (*KATAGO_NETWORKS, FINETUNED_9X9_NETWORK)
    NETWORKS_BY_NAME: ClassVar[dict[str, NetworkSpec]] = {
        network.name: network for network in ALL_KATAGO_NETWORKS
    }
    TOP_KATAGO_NETWORKS = tuple(
        sorted(
            (
                network
                for network in KATAGO_NETWORKS
                if network.name != "kata1-zhizi-b40c768nbt-fdx6c"
            ),
            key=lambda network: network.rating,
            reverse=True,
        )[:KATAGO_TOP_NETWORK_COUNT]
    )
    KATAGO_ACTIVE_PLAYERS = tuple(
        f"{network.name}-playouts{playouts}"
        for network in TOP_KATAGO_NETWORKS
        for playouts in (60, 600)
    )

    COLOR_ADVANTAGE_MODEL = "average_elo_piecewise_linear_1500"
    COLOR_ADVANTAGE_NODE_SPACING = 1_500.0
    COLOR_ADVANTAGE_PRIOR_ELO_SD = 10_000.0
    DEFAULT_PLAYER_PRIOR = (0.0, 10_000.0)
    CONFIDENCE_Z = 1.959963984540054
    ELO_SCALE, RANDOM_SEED = math.log(10.0) / 400.0, 1729
    MATCH_GAME_THREADS = _env("MATCH_GAME_THREADS", 256)
    NN_MAX_BATCH_SIZE = _env("NN_MAX_BATCH_SIZE", 32)
    NN_CACHE_SIZE_POWER_OF_TWO = _env("NN_CACHE_SIZE_POWER_OF_TWO", 12)
    NN_MUTEX_POOL_SIZE_POWER_OF_TWO = _env("NN_MUTEX_POOL_SIZE_POWER_OF_TWO", 10)
    PROGRESS_INTERVAL_SECONDS = _env("PROGRESS_INTERVAL_SECONDS", 10, float)
    # Zero keeps transient outages from terminating a saved, long-running game.
    LLM_API_MAX_ATTEMPTS = _env("LLM_API_MAX_ATTEMPTS", 0)
    LLM_API_RETRY_INITIAL_SECONDS = _env("LLM_API_RETRY_INITIAL_SECONDS", 2, float)
    LLM_API_RETRY_MAX_SECONDS = _env("LLM_API_RETRY_MAX_SECONDS", 60, float)
    LLM_API_RETRY_JITTER_FRACTION = _env("LLM_API_RETRY_JITTER_FRACTION", 0.1, float)
    # Upstream Codex 404s have recovered on resume, but can also be permanent.
    CODEX_NOT_FOUND_MAX_ATTEMPTS = 5
    # Codex workspace players may use every local tool that can operate inside
    # the network-isolated bubblewrap sandbox. Keep this list explicit because
    # some local capabilities (notably memories) default to disabled upstream.
    CODEX_OFFLINE_TOOL_FEATURES = (
        "code_mode_host",
        "goals",
        "hooks",
        "memories",
        "multi_agent",
        "shell_snapshot",
        "shell_tool",
        "skill_search",
        "unified_exec",
        "view_image",
        "workspace_dependencies",
    )
    CODEX_WORKSPACE_DISABLED_FEATURES = (
        "apps",
        "auth_elicitation",
        "browser_use",
        "browser_use_external",
        "browser_use_full_cdp_access",
        "code_mode",
        "computer_use",
        "image_generation",
        "in_app_browser",
        "multi_agent_v2",
        "plugin_sharing",
        "plugins",
        "remote_plugin",
        "request_permissions_tool",
        "skill_mcp_dependency_install",
        "standalone_web_search",
        "tool_call_mcp_elicitation",
        "tool_search_always_defer_mcp_tools",
        "tool_suggest",
        "enable_request_compression",
    )
    CODEX_BASE_INSTRUCTIONS = ""
    CODEX_WORKSPACE_INSTRUCTIONS = (
        "You are in a sandboxed workspace, and you may read, write, and execute only "
        "files within the workspace. You may use the tools available to you to help "
        "you win the game. For example, you can write a MCTS algorithm in python. "
        "Python is available as python3. Do not access the internet, and do not "
        "access any external Go engines."
    )
    MOVE_OUTPUT_INSTRUCTIONS = (
        "Your entire final answer must be one entry copied exactly from Legal moves.\n"
        "Write that entry on a single line, then end the response immediately."
    )
    CODEX_WORKSPACE_PROVIDER = "arena_openai_proxy"
    CODEX_WORKSPACE_PROXY_PORT = 8765
    OPENAI_API_HOST = "api.openai.com"
    PROXY_HOP_BY_HOP_HEADERS = frozenset(
        {
            "connection",
            "content-length",
            "host",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade",
        }
    )
    FORBIDDEN_HOSTED_TOOL_MARKERS = (
        "browser",
        "code_interpreter",
        "computer",
        "container",
        "file_search",
        "image_generation",
        "mcp",
        "remote",
        "search",
        "web",
    )
    NETWORK_COMMAND_RE = re.compile(
        r"(?:https?://|\b(?:curl|wget|aria2c|ftp|sftp|ssh|scp|telnet|ping|dig|"
        r"nslookup|ncat|nc)\b|\bgit\s+(?:clone|fetch|pull|push|ls-remote)\b|"
        r"\b(?:pip|pip3)\s+(?:install|download)\b|\b(?:npm|pnpm|yarn)\s+"
        r"(?:add|install|publish)\b|\b(?:apt|apt-get)\s+"
        r"(?:download|install|update)\b)",
        re.IGNORECASE,
    )
    TRACKED_LOG_OMITTED_FIELDS = frozenset(
        {
            "authorization",
            "cookie",
            "proxy_authorization",
            "request_id",
            "response_body_excerpt",
            "response_headers",
            "response_id",
            "set_cookie",
            "x_api_key",
        }
    )
    TRACKED_LOG_SECRET_FIELDS = frozenset(
        {
            "access_token",
            "api_key",
            "apikey",
            "client_secret",
            "password",
            "refresh_token",
            "secret",
            "token",
        }
    )
    TRACKED_LOG_PATH_FIELDS = frozenset(
        {
            "katago_binary",
            "network_path",
            "past_run_dirs",
            "untracked_log_dir",
        }
    )


RUN_TYPES["api_multi"] = replace(
    RUN_TYPES["many_llm"],
    active_players=tuple(
        name
        for api in _Arena.LLM_APIS
        for name, player in api.players.items()
        if player.agentic_harness == "api-multi"
    ),
)


class _State:
    config = CONFIG
    katago_mode = False
    katago_binary = KATAGO_CPU_BINARY
    katago_backend = "cpu"
    random_game_workers = 16
    past_run_dirs: tuple[Path, ...] = ()
    past_player_priors: ClassVar[dict[str, tuple[float, float]]] = {}
    katago_rating_player_names: tuple[str, ...] = ()
    arena_player_names: tuple[str, ...] = ()
    jsonl_write_lock = threading.RLock()
    retry_random = random.SystemRandom()
    game_dependencies_lock = threading.Lock()
    katago_installed_for_games = False
    katago_cuda_installed_for_games = False
    installed_arena_networks: ClassVar[set[str]] = set()


def _player_playouts(player_name):
    match = _Arena.PLAYOUTS_SUFFIX.search(player_name)
    return int(match.group(1)) if match else None


def _player_temperature(player_name):
    player_name = _Arena.PLAYOUTS_SUFFIX.sub("", player_name)
    match = _Arena.TEMPERATURE_SUFFIX.search(player_name)
    return float(match.group(1)) if match else None


def _numbered_llm_player_base(player_name, candidates):
    """Resolve a terminal numeric instance suffix against canonical LLM names."""
    if player_name in candidates:
        return player_name
    if not isinstance(player_name, str):
        return None
    match = re.fullmatch(r"(?P<base>.*\D)(?P<instance>\d+)", player_name)
    if match is None:
        return None
    base = match.group("base")
    return base if base in candidates else None


def _canonical_active_llm_player_name(player_name):
    if not isinstance(player_name, str):
        return None
    # Read old histories without exposing authentication as a player variant.
    player_name = re.sub(r"-oauth(?=-multi(?:\d+)?$|\d*$)", "-api", player_name)
    if any(player_name in api.players for api in _Arena.LLM_APIS):
        return player_name
    match = re.fullmatch(r"(?P<base>.*\D)(?P<instance>\d+)", player_name)
    if match is None:
        return None
    base = match.group("base")
    return base if any(base in api.players for api in _Arena.LLM_APIS) else None


def _is_active_llm_player(player_name):
    return _canonical_active_llm_player_name(player_name) is not None


def _active_llm_players(player_names):
    return {name for name in player_names if _is_active_llm_player(name)}


def _is_result_llm_player(player_name):
    return _is_active_llm_player(player_name) or (
        _numbered_llm_player_base(player_name, _Arena.FINAL_RUN_LLM_PLAYERS) is not None
    )


def _result_llm_players(player_names):
    return {name for name in player_names if _is_result_llm_player(name)}


def _is_result_api_llm_player(player_name):
    canonical = _canonical_active_llm_player_name(player_name)
    if canonical is not None:
        for api in _Arena.LLM_APIS:
            if canonical in api.players:
                return api.players[canonical].agentic_harness in {"api", "api-multi"}
    return (
        _numbered_llm_player_base(player_name, _Arena.FINAL_RUN_LLM_PLAYERS) or ""
    ).endswith("-api")


def _network_name_for_player(player_name):
    if player_name == _Arena.ANCHOR or _is_result_llm_player(player_name):
        return None
    name = _Arena.PLAYOUTS_SUFFIX.sub("", player_name)
    return _Arena.TEMPERATURE_SUFFIX.sub("", name)


def _final_run_network_name(player_name):
    return _network_name_for_player(player_name.partition("-temp-")[0])


def _active_players_are_katago(active_players):
    if not active_players:
        raise ArenaError("active_players must not be empty")
    kata_players = [
        name
        for name in active_players
        if _network_name_for_player(name) in _Arena.NETWORKS_BY_NAME
    ]
    llm_players = [name for name in active_players if _is_active_llm_player(name)]
    unknown = [name for name in active_players
               if name not in kata_players and name not in llm_players]
    if unknown:
        raise ArenaError(f"unknown active player(s): {', '.join(map(str, unknown))}")
    if len(kata_players) == len(active_players):
        return True
    if len(llm_players) == len(active_players):
        return False
    raise ArenaError("active_players must be all KataGo players or all LLM players")


def _historical_katago_player_names(run_dirs):
    names = []
    for run in run_dirs:
        path = run / "results.csv"
        metadata = json.loads((run / "run.json").read_text(encoding="utf-8"))
        network_name = (
            _final_run_network_name
            if run.name in _FINAL_RUNS and metadata.get("arena_log_schema_version") == 2
            else _network_name_for_player
        )
        with path.open(newline="", encoding="utf-8") as results_file:
            reader = csv.DictReader(results_file)
            if not {"black", "white"} <= set(reader.fieldnames or ()):
                raise RuntimeError(f"historical results are missing columns: {path}")
            # Classify each distinct name once, rather than twice per game.
            run_names = dict.fromkeys(
                name
                for row in _committed_csv_rows(reader, metadata["completed_games"])
                for name in (row["black"], row["white"])
            )
            names += [
                name for name in run_names
                if name == _Arena.ANCHOR
                or network_name(name) in _Arena.NETWORKS_BY_NAME
            ]
    unique = tuple(dict.fromkeys(names))
    if run_dirs and _Arena.ANCHOR not in unique:
        raise RuntimeError(f"historical arenas do not contain anchor {_Arena.ANCHOR}")
    return unique or (_Arena.ANCHOR,)


@dataclass(frozen=True)
class _PastRunConfig:
    active_players: tuple[str, ...]
    past_run_names: tuple[str, ...]
    prior: tuple[float, float]


def _historical_run_name(name):
    renamed = re.sub(r"-oauth(?=-multi(?:\d+)?$|\d*$)", "-api", name)
    if (renamed != name and not (_Arena.LOG_ROOT / name).exists()
            and (_Arena.LOG_ROOT / renamed).is_dir()):
        return renamed
    return name


def _read_past_run_config(run_name):
    run_name = _historical_run_name(run_name)
    path = _Arena.LOG_ROOT / run_name / "run.json"
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArenaError(f"cannot read past arena config {path}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ArenaError(f"past arena config is not a JSON object: {path}")

    if metadata.get("arena_log_schema_version") == 4:

        def string_list(name):
            value = metadata.get(name)
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ArenaError(f"past arena config has invalid {name}: {path}")
            return tuple(value)

        def number(name):
            value = metadata.get(name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ArenaError(f"past arena config has invalid {name}: {path}")
            return float(value)

        active = string_list("active_players")
        if not active:
            raise ArenaError(f"past arena config has no active players: {path}")
        past_names = tuple(Path(value).name for value in string_list("past_run_dirs"))
        if metadata.get("run_directory_scheme") == "llm_name":
            # Named runs are mutable. Their stored active-player prior is
            # authoritative; following mutable peers can create history cycles.
            past_names = ()
        return _PastRunConfig(
            active,
            past_names,
            (
                number("active_player_prior_elo_mean"),
                number("active_player_prior_elo_sd"),
            ),
        )

    _check(run_name not in _FINAL_RUNS or metadata.get("arena_log_schema_version") != 2)
    players = metadata.get("players")
    _check(
        not isinstance(players, list)
        or not all(isinstance(name, str) for name in players)
    )
    active = metadata.get("information_gain_players")
    if active is None:
        llms = [name for name in players if _is_active_llm_player(name)]
        active = llms or [name for name in players if name != _Arena.ANCHOR]
    _check(
        not isinstance(active, list)
        or not active
        or not all(isinstance(name, str) for name in active)
    )
    past_values = metadata.get("past_run_dirs")
    _check(
        not isinstance(past_values, list)
        or not all(isinstance(value, str) for value in past_values)
    )
    past_names = tuple(Path(value).name for value in past_values)
    # Legacy baseline metadata also references the LLM runs now excluded from
    # the evaluation. Follow only the retained historical inputs.
    past_names = tuple(name for name in past_names if name in _FINAL_RUNS)

    playout_run = all(
        _player_playouts(name) in _Arena.KATAGO_PLAYOUT_COUNTS for name in active
    )
    if playout_run:
        prior = (
            float(metadata["katago_new_prior_elo_mean"]),
            float(metadata["katago_new_prior_elo_sd"]),
        )
    elif all(_final_run_network_name(name) is not None for name in active):
        prior = _Arena.DEFAULT_PLAYER_PRIOR
    else:
        prior = (
            float(metadata.get("llm_prior_elo_mean", 1_000.0)),
            float(metadata.get("llm_prior_elo_sd", 2_000.0)),
        )
    return _PastRunConfig(tuple(active), past_names, prior)


def _historical_player_priors(config):
    priors: dict[str, tuple[float, float]] = {}
    visited: set[str] = set()
    visiting: set[str] = set()

    def add_run(run_name):
        if run_name in visited:
            return
        if run_name in visiting:
            raise ArenaError(f"cyclic past arena history: {run_name}")
        visiting.add(run_name)
        run_config = _read_past_run_config(run_name)
        for earlier_name in run_config.past_run_names:
            add_run(earlier_name)
        for player_name in run_config.active_players:
            if (
                _is_active_llm_player(player_name)
                or _network_name_for_player(player_name) in _Arena.NETWORKS_BY_NAME
            ):
                priors.setdefault(player_name, run_config.prior)
        visiting.remove(run_name)
        visited.add(run_name)

    for name in config.past_run_names:
        add_run(name)
    return priors


def _configure_history(config):
    config = replace(config, past_run_names=tuple(dict.fromkeys(
        _historical_run_name(name) for name in config.past_run_names
    )))
    past_dirs = tuple(_Arena.LOG_ROOT / name for name in config.past_run_names)
    missing = [path for path in past_dirs if not path.is_dir()]
    if missing:
        raise ArenaError(f"past arena does not exist: {missing[0]}")
    historical = _historical_katago_player_names(past_dirs)
    _State.config = config
    _State.past_run_dirs = past_dirs
    _State.past_player_priors = _historical_player_priors(config)
    _State.katago_rating_player_names = tuple(dict.fromkeys(
        (*historical, *config.active_players)
    ))


def _configure(config):
    active = config.active_players
    opponents = config.opponent_players
    ignored = config.ignore_players
    if not active:
        raise ArenaError("active_players must not be empty")
    if not opponents:
        raise ArenaError("opponent_players must not be empty")
    if len(active) != len(set(active)) or len(opponents) != len(set(opponents)):
        raise ArenaError("active_players and opponent_players must each be unique")
    if not isinstance(ignored, tuple) or any(
        not isinstance(name, str) or not name for name in ignored
    ):
        raise ArenaError("ignore_players must contain only nonempty player names")
    if len(ignored) != len(set(ignored)):
        raise ArenaError("ignore_players must be unique")
    if config.katago_backend not in {"cpu", "cuda"}:
        raise ArenaError("katago_backend must be 'cpu' or 'cuda'")
    katago_mode = _active_players_are_katago(active)
    if not katago_mode:
        # These games will be recovered as this run's own records, not loaded
        # a second time as historical games. Also isolate concurrent LLM jobs.
        config = replace(
            config,
            past_run_names=tuple(
                name for name in config.past_run_names if name not in active
            ),
        )
    overlap = set(active) & set(opponents)
    if katago_mode and overlap != set(active):
        raise ArenaError("all active KataGo players must be opponent_players")
    if not katago_mode and overlap:
        raise ArenaError("active LLM players cannot be opponent_players")
    if any(
        name != _Arena.ANCHOR
        and _network_name_for_player(name) not in _Arena.NETWORKS_BY_NAME
        for name in opponents
    ):
        raise ArenaError("opponent_players must be executable KataGo players")
    _configure_history(config)
    player_names = (*opponents, *(name for name in active if name not in opponents))
    _State.katago_mode = katago_mode
    _State.katago_binary = (
        KATAGO_CUDA_BINARY if config.katago_backend == "cuda" else KATAGO_CPU_BINARY
    )
    _State.katago_backend = config.katago_backend
    _State.random_game_workers = _env(
        "RANDOM_GAME_WORKERS", 1 if config.katago_backend == "cuda" else 16
    )
    _State.arena_player_names = tuple(player_names)


def _rating_prior(player_name):
    config = _State.config
    if (player_name in config.active_players and _is_active_llm_player(player_name)
            and _llm_player_config(player_name)[1].agentic_harness in _CODEX_WORKSPACE_HARNESSES):
        return config.active_player_prior_elo_mean, config.active_player_prior_elo_sd
    if player_name in _State.past_player_priors:
        return _State.past_player_priors[player_name]
    if player_name in config.active_players:
        return config.active_player_prior_elo_mean, config.active_player_prior_elo_sd
    return _Arena.DEFAULT_PLAYER_PRIOR


class ArenaError(RuntimeError):
    pass


class _MissingSGFProperty(ArenaError):
    def __init__(self, name):
        self.name = name
        super().__init__(f"SGF is missing {name}")


class _WorkspaceCodexTransportError(RuntimeError):
    """A failed Codex turn caused by the workspace-local model proxy path."""


def _check(failed):
    if failed:
        raise ArenaError("invalid arena state")


def _call(function, *args, **kwargs):
    return function(*args, **kwargs) if function else None


@dataclass(frozen=True)
class Player:
    name: str
    network: Path | None
    network_name: str | None = None
    chosen_move_temperature_early: float | None = None
    chosen_move_temperature: float | None = None
    max_playouts: int | None = None


@dataclass(frozen=True)
class ScheduledGame:
    number: int
    batch: int
    black: str
    white: str


@dataclass(frozen=True)
class GameRecord(ScheduledGame):
    result: str
    winner_color: str | None
    winner: str | None
    score_black: float
    reason: str
    moves: tuple[tuple[str, str], ...]
    source: str
    sgf: str
    llm_illegal_moves: int = 0
    llm_api_problems: int = 0
    llm_api_seconds: float = 0.0
    llm_cost_usd: float = 0.0
    llm_input_tokens: int | None = None
    llm_cached_input_tokens: int | None = None
    llm_output_tokens: int | None = None


@dataclass(frozen=True)
class RatingRecord:
    player: str
    elo: float
    ci_low: float
    ci_high: float
    ci_width: float
    games: int
    wins: int
    losses: int
    draws: int


@dataclass(frozen=True)
class ColorAdvantageModel:
    nodes: tuple[float, ...]
    coefficients: tuple[float, ...]
    baseline_ratings: dict[str, float]

    @property
    def parameter_count(self):
        return len(self.nodes)

    def features_at_average(self, average_elo):
        return _piecewise_linear_basis(average_elo, self.nodes)

    def features(self, black, white):
        average_elo = (self.baseline_ratings[black] + self.baseline_ratings[white]) / 2
        return self.features_at_average(average_elo)

    def advantage_at_average(self, average_elo):
        return float(np.dot(self.coefficients, self.features_at_average(average_elo)))

    def advantage(self, black, white):
        average_elo = (self.baseline_ratings[black] + self.baseline_ratings[white]) / 2
        return self.advantage_at_average(average_elo)


def _game_record(head, *parts):
    vals = astuple(head) if isinstance(head, ScheduledGame) else tuple(head)
    return GameRecord(*vals + sum(parts, ()))


def _game_players(game):
    return {game.black, game.white}


def players():
    if not _State.arena_player_names:
        _configure(_State.config)
    vals = []
    for name in _State.arena_player_names:
        net_name = _network_name_for_player(name)
        if net_name is None:
            vals.append(Player(name, None))
            continue
        _check((net := _Arena.NETWORKS_BY_NAME.get(net_name)) is None)
        temperature = _player_temperature(name)
        if temperature is None:
            early_temperature = _Arena.ORIGINAL_TEMPERATURE_EARLY
            temperature = _Arena.ORIGINAL_TEMPERATURE
        else:
            early_temperature = (
                _Arena.ORIGINAL_TEMPERATURE_EARLY
                if temperature == _Arena.LOW_LATE_TEMPERATURE
                else temperature
            )
        vals.append(
            Player(
                name,
                net.path.resolve(),
                net_name,
                early_temperature,
                temperature,
                _player_playouts(name),
            )
        )
    names = [bot.name for bot in vals]
    _check(len(names) != len(set(names)) or _Arena.ANCHOR not in names)
    return tuple(vals)


def _ensure_game_dependencies(schedule, player_values):
    """Prepare only the engine and networks needed by scheduled games."""
    if not schedule:
        return
    scheduled_names = {name for game in schedule for name in (game.black, game.white)}
    network_names = tuple(
        dict.fromkeys(
            bot.network_name
            for bot in player_values
            if bot.name in scheduled_names and bot.network_name is not None
        )
    )
    _check(any(name not in _Arena.NETWORKS_BY_NAME for name in network_names))

    with _State.game_dependencies_lock:
        if not _State.katago_installed_for_games:
            ensure_katago_installed()
            _State.katago_installed_for_games = True
        if (
            _State.katago_backend == "cuda"
            and not _State.katago_cuda_installed_for_games
        ):
            ensure_katago_cuda_installed()
            _State.katago_cuda_installed_for_games = True
        missing = [
            _Arena.NETWORKS_BY_NAME[name]
            for name in network_names
            if name not in _State.installed_arena_networks
        ]
        if missing:
            ensure_arena_networks(missing)
            _State.installed_arena_networks.update(network.name for network in missing)


def _player_max_visits(player):
    return (
        _Arena.PLAYOUT_MAX_VISITS
        if player.max_playouts is not None
        else _Arena.MAX_VISITS
    )


def _player_manifest(player):
    if _is_active_llm_player(player.name):
        return _llm_player_manifest(player.name)
    if player.network is None:
        return {"name": player.name, "kind": "uniform_random"}
    manifest = {
        "name": player.name,
        "kind": "katago_network",
        "network_name": player.network_name,
        "network_path": _portable_path(player.network),
        "max_visits": _player_max_visits(player),
        "chosen_move_temperature_early": player.chosen_move_temperature_early,
        "chosen_move_temperature": player.chosen_move_temperature,
    }
    if player.max_playouts is not None:
        manifest["max_playouts"] = player.max_playouts
    return manifest


def _portable_path(path):
    resolved = Path(path).expanduser().resolve()
    try:
        return str(resolved.relative_to(_Arena.ROOT))
    except ValueError:
        return "<external-path>"


def _tracked_path_value(value, field):
    """Make path metadata useful without publishing a user's filesystem."""
    path = Path(value).expanduser()
    if field == "past_run_dirs" and re.fullmatch(r"arena_[A-Za-z0-9_.-]+", path.name):
        return str(Path("log") / path.name)
    if (
        field == "untracked_log_dir"
        and path.is_absolute()
        and re.fullmatch(r"arena_[A-Za-z0-9_.-]+", path.name)
    ):
        return str(Path("untracked_log") / path.name)
    marker = ".venv/katago/"
    normalized = str(value).replace("\\", "/")
    if marker in normalized:
        return marker.removesuffix("/") + "/" + normalized.split(marker, 1)[1]
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.resolve().relative_to(_Arena.ROOT))
    except ValueError:
        return "<external-path>"


def _tracked_llm_output(value):
    """Keep moves in Git while preventing arbitrary model prose from entering it."""
    if not isinstance(value, str):
        return "<invalid-output>"
    move = value.strip()
    return (
        move
        if re.fullmatch(r"(?i)(?:[A-HJ][1-9]|pass|resign)", move)
        else ("<invalid-output>" if move else "")
    )


def _tracked_error_type(value):
    if not isinstance(value, str):
        return "UnknownError"
    match = re.match(r"([A-Za-z_][A-Za-z0-9_.]*)(?::|,|$)", value.strip())
    return match.group(1) if match else "UnknownError"


def _sanitize_private_log_value(value):
    """Drop credential and HTTP identity fields even from ignored raw logs."""
    if isinstance(value, dict):
        sanitized = {}
        for name, item in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
            if normalized in _Arena.TRACKED_LOG_OMITTED_FIELDS:
                continue
            if normalized in _Arena.TRACKED_LOG_SECRET_FIELDS:
                sanitized[name] = "<redacted>"
                continue
            sanitized[name] = _sanitize_private_log_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_private_log_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_private_log_value(item) for item in value]
    return value


def _sanitize_tracked_log_value(value, field=None):
    """Recursively enforce the privacy boundary for Git-tracked JSON logs."""
    if isinstance(value, dict):
        private = _sanitize_private_log_value(value)
        return {
            name: _sanitize_tracked_log_value(
                item,
                re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_"),
            )
            for name, item in private.items()
        }
    if isinstance(value, list):
        return [_sanitize_tracked_log_value(item, field) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_tracked_log_value(item, field) for item in value]
    if isinstance(value, str) and field in _Arena.TRACKED_LOG_PATH_FIELDS:
        return _tracked_path_value(value, field)
    if field == "output" and isinstance(value, str):
        return _tracked_llm_output(value)
    if field == "error":
        return _tracked_error_type(value)
    return value


def _is_tracked_log_path(path):
    try:
        Path(path).resolve().relative_to(_Arena.LOG_ROOT.resolve())
        return True
    except ValueError:
        return False


def _ensure_untracked_log_root():
    _Arena.UNTRACKED_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    readme = _Arena.UNTRACKED_LOG_ROOT / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Untracked arena logs\n\n"
            "This Git-ignored directory contains visible, reboot-persistent "
            "arena checkpoints, raw game records, engine transcripts, generated "
            "configs, stderr, and progress logs. Each run corresponds to the "
            "same-named compact record under `../log/`.\n",
            encoding="utf-8",
        )


def win_probability(rating_difference):
    value = _Arena.ELO_SCALE * rating_difference
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _solve_spd(matrix, values):
    try:
        lower = np.linalg.cholesky(matrix)
        return np.linalg.solve(lower.T, np.linalg.solve(lower, values)).tolist()
    except np.linalg.LinAlgError as exc:
        raise ArenaError("rating information matrix is not positive definite") from exc


def _inverse_spd(matrix):
    try:
        lower = np.linalg.cholesky(matrix)
        inverse = np.linalg.solve(lower.T, np.linalg.solve(lower, np.eye(len(lower))))
    except np.linalg.LinAlgError as exc:
        raise ArenaError("rating information matrix is not positive definite") from exc
    return ((inverse + inverse.T) / 2).tolist()


def _fixed_elo_nodes(values, spacing):
    """Return observed boundaries and regularly spaced absolute-Elo nodes."""
    if spacing <= 0.0:
        raise ValueError("piecewise-linear spacing must be positive")
    if not len(values):
        return (0.0,)
    lower, upper = float(np.min(values)), float(np.max(values))
    if upper - lower < 1e-12:
        return (lower,)
    first = (math.floor(lower / spacing) + 1) * spacing
    regular = np.arange(first, upper, spacing, dtype=float).tolist()
    if regular and upper - regular[-1] < 0.5 * spacing:
        regular.pop()
    return lower, *regular, upper


def _piecewise_linear_basis(value, nodes):
    """Return the continuous linear hat-function values at one Elo value."""
    if not nodes:
        raise ValueError("piecewise-linear model requires at least one node")
    if len(nodes) == 1:
        return (1.0,)
    if any(right <= left for left, right in pairwise(nodes)):
        raise ValueError("piecewise-linear nodes must be strictly increasing")
    basis = [0.0] * len(nodes)
    if value <= nodes[0]:
        basis[0] = 1.0
    elif value >= nodes[-1]:
        basis[-1] = 1.0
    else:
        left = int(np.searchsorted(nodes, value, side="right") - 1)
        fraction = (value - nodes[left]) / (nodes[left + 1] - nodes[left])
        basis[left] = 1.0 - fraction
        basis[left + 1] = fraction
    return tuple(basis)


def _prior_vectors(names):
    priors = [_rating_prior(name) for name in names]
    return np.array([mean for (mean, _sd) in priors]), np.array(
        [sd**-2 for (_mean, sd) in priors]
    )


def _rating_design(games, positions, model=None):
    width = len(positions) + (model.parameter_count if model else 0)
    xmat = np.zeros((len(games), width))
    for row, game in enumerate(games):
        for name, sign in ((game.black, 1.0), (game.white, -1.0)):
            if name in positions:
                xmat[row, positions[name]] += sign
        if model:
            xmat[row, len(positions) :] = model.features(game.black, game.white)
    return xmat, np.array([game.score_black for game in games])


def _grouped_rating_data(games, positions, model=None):
    aggregates = {}
    for game in games:
        key = game.black, game.white
        entry = aggregates.setdefault(key, [0.0, 0.0])
        entry[0] += 1.0
        entry[1] += game.score_black
    matchups = tuple(aggregates)
    width = len(positions) + (model.parameter_count if model else 0)
    design = np.zeros((len(matchups), width))
    for row, (black, white) in enumerate(matchups):
        for name, sign in ((black, 1.0), (white, -1.0)):
            if name in positions:
                design[row, positions[name]] += sign
        if model:
            design[row, len(positions) :] = model.features(black, white)
    totals = np.array([aggregates[key][0] for key in matchups])
    scores = np.array([aggregates[key][1] for key in matchups])
    return design, scores, totals, matchups


def _logit_objective(design, scores, totals, values, means, precision):
    logits = _Arena.ELO_SCALE * design @ values
    penalty = np.sum(precision * (values - means) ** 2) / 2
    likelihood = scores * logits - totals * np.logaddexp(0, logits)
    return float(np.sum(likelihood) - penalty)


def _fit_logit(design, scores, totals, values, means, precision):
    prec, vals = precision, values
    for _iteration in range(500):
        logits = _Arena.ELO_SCALE * design @ vals
        prob = np.exp(-np.logaddexp(0, -logits))
        gradient = _Arena.ELO_SCALE * design.T @ (scores - totals * prob)
        gradient -= prec * (vals - means)
        weights = _Arena.ELO_SCALE**2 * totals * prob * (1 - prob)
        info = design.T * weights @ design + np.diag(prec)
        change = np.array(_solve_spd(info.tolist(), gradient.tolist()))
        if max(abs(change), default=0.0) < 1e-7:
            return vals
        objective = _logit_objective(design, scores, totals, vals, means, prec)
        step = 1.0
        while step >= 2**-60:
            option = vals + step * change
            if (
                _logit_objective(design, scores, totals, option, means, prec)
                >= objective
            ):
                vals = option
                break
            step /= 2
        else:
            raise ArenaError("rating optimizer could not improve its objective")
        # At machine precision the objective can no longer distinguish nearby
        # candidates. Only accept this as convergence near a stationary point.
        if max(abs(step * change), default=0.0) < 1e-7:
            if float(gradient @ change) < 1e-8:
                return vals
            raise ArenaError("rating optimizer stalled before convergence")
    raise ArenaError("rating optimizer did not converge")


def _fit_no_color_ratings(games, player_names, initial=None):
    names = [name for name in player_names if name != _Arena.ANCHOR]
    pos = {name: index for (index, name) in enumerate(names)}
    means, prec = _prior_vectors(names)
    vals = np.array(
        [
            float(initial[name]) if initial and name in initial else mean
            for (name, mean) in zip(names, means)
        ]
    )
    xmat, scores, totals, _matchups = _grouped_rating_data(games, pos)
    vals = _fit_logit(xmat, scores, totals, vals, means, prec)
    return {_Arena.ANCHOR: 0.0, **dict(zip(names, map(float, vals)))}


def fit_ratings_and_color_advantage(
    games, player_names, initial=None, initial_color_advantage=None
):
    all_names, initial_color = player_names, initial_color_advantage
    names = [name for name in all_names if name != _Arena.ANCHOR]
    pos = {name: index for (index, name) in enumerate(names)}
    base = _fit_no_color_ratings(games, all_names, initial)
    _rating_design, _scores, _totals, matchups = _grouped_rating_data(games, pos)
    observed = np.array(
        [0.5 * (base[black] + base[white]) for black, white in matchups]
    )
    nodes = _fixed_elo_nodes(observed, _Arena.COLOR_ADVANTAGE_NODE_SPACING)
    coefficients = (
        tuple(
            sum(
                coefficient * weight
                for coefficient, weight in zip(
                    initial_color.coefficients,
                    _piecewise_linear_basis(node, initial_color.nodes),
                )
            )
            for node in nodes
        )
        if initial_color is not None
        else (0.0,) * len(nodes)
    )
    model = ColorAdvantageModel(nodes, coefficients, base)
    design, scores, totals, _matchups = _grouped_rating_data(games, pos, model)
    rating_means, rating_prec = _prior_vectors(names)
    means = np.append(rating_means, np.zeros(len(nodes)))
    prec = np.append(
        rating_prec,
        np.full(len(nodes), _Arena.COLOR_ADVANTAGE_PRIOR_ELO_SD**-2),
    )
    vals = np.array([*(base[name] for name in names), *coefficients])
    vals = _fit_logit(design, scores, totals, vals, means, prec)
    elos = {_Arena.ANCHOR: 0.0, **dict(zip(names, map(float, vals)))}
    model = replace(model, coefficients=tuple(vals[len(names) :]))
    return elos, model


def rating_covariance(
    games, player_names, ratings, *, color_advantage=None, include_color=False
):
    elos, with_color, color = ratings, include_color, color_advantage
    names = [name for name in player_names if name != _Arena.ANCHOR]
    pos = {name: index for (index, name) in enumerate(names)}
    _check(with_color and color is None)
    xmat, _scores, totals, matchups = _grouped_rating_data(
        games, pos, color if with_color else None
    )
    diffs = np.array(
        [
            elos[black] - elos[white] + (color.advantage(black, white) if color else 0)
            for black, white in matchups
        ]
    )
    prob = 1 / (1 + np.exp(-_Arena.ELO_SCALE * diffs))
    weights = _Arena.ELO_SCALE**2 * totals * prob * (1 - prob)
    _means, prec = _prior_vectors(names)
    if with_color:
        prec = np.append(
            prec,
            np.full(color.parameter_count, _Arena.COLOR_ADVANTAGE_PRIOR_ELO_SD**-2),
        )
    info = xmat.T * weights @ xmat + np.diag(prec)
    return _inverse_spd(info.tolist()), pos


def _information_weight(rating_difference):
    prob = win_probability(rating_difference)
    return _Arena.ELO_SCALE * _Arena.ELO_SCALE * prob * (1.0 - prob)


def _paired_information_gain(
    covariance,
    left_index,
    right_index,
    rating_difference,
    color_advantage=0.0,
    color_features=(),
    objective_indices=None,
):
    obj_ids, color, rating_gap = (
        objective_indices,
        color_advantage,
        rating_difference,
    )
    cov, right_idx, left_idx = covariance, right_index, left_index
    size = len(cov)
    first = np.zeros(size)
    for index, coef in color_features:
        first[index] = coef
    if left_idx is not None:
        first[left_idx] += 1
    if right_idx is not None:
        first[right_idx] -= 1
    second = first.copy()
    if left_idx is not None:
        second[left_idx] -= 2
    if right_idx is not None:
        second[right_idx] += 2
    mat = np.asarray(cov)
    first_proj = mat @ first
    first_var = max(float(first @ first_proj), 0)
    weight = _information_weight(rating_gap + color)
    first_beta = weight / (1 + weight * first_var)
    second_proj, cross = mat @ second, float(first_proj @ second)
    second_proj -= first_beta * first_proj * cross
    second_var = max(float(second @ mat @ second) - first_beta * cross**2, 0)
    weight = _information_weight(-rating_gap + color)
    second_beta, current = weight / (1 + weight * second_var), np.diag(mat)
    updated = current - first_beta * first_proj**2
    updated -= second_beta * second_proj**2
    indices = obj_ids if obj_ids is not None else range(size)
    gain = sum(
        math.sqrt(max(current[index], 0)) - math.sqrt(max(updated[index], 0))
        for index in indices
    )
    return max(2 * _Arena.CONFIDENCE_Z * gain, 0.0)


def information_gain_matrix(
    player_names,
    ratings,
    covariance,
    positions,
    *,
    color_advantage=None,
    active_players=None,
):
    elos, color, cov = ratings, color_advantage, covariance
    pos, active = positions, active_players
    if active is None and not _State.katago_mode:
        active = _State.config.active_players
    _check(len(names := list(player_names)) < 2)
    _check(len(names) != len(set(names)))
    _check(not cov or any(len(row) != len(cov) for row in cov))
    _check(any(name not in elos for name in names))
    if active is not None:
        _check(not active)
        _check(len(active) != len(set(active)))
        missing = [name for name in active if name not in pos]
        _check(missing)
    count = len(pos)
    _check(len(cov) != count + (color.parameter_count if color else 0))
    mat = [[0.0] * len(names) for _ in names]
    obj_ids = sorted(pos.values()) if active is None else [pos[name] for name in active]
    for left, left_name in enumerate(names):
        for right in range(left + 1, len(names)):
            right_name = names[right]
            color_terms: list[tuple[int, float]] = []
            match_color = 0.0
            if color is not None:
                features = color.features(left_name, right_name)
                color_terms = [
                    (count + index, coef)
                    for (index, coef) in enumerate(features)
                    if coef
                ]
                match_color = color.advantage(left_name, right_name)
            gain = _paired_information_gain(
                cov,
                pos.get(left_name),
                pos.get(right_name),
                elos[left_name] - elos[right_name],
                match_color,
                color_terms,
                obj_ids,
            )
            _check(not math.isfinite(gain))
            mat[left][right] = gain
            mat[right][left] = gain
    return mat


def _validate_color_swapped_schedule(schedule, pair_count):
    pairs, slate = pair_count, schedule
    _check(len(slate) != pairs * 2)
    for first, swapped in zip(slate[:pairs], slate[pairs:]):
        _check((swapped.black, swapped.white) != (first.white, first.black))


def _gain_nucleus(options, weights, top_p):
    _check(
        not math.isfinite(top_p)
        or top_p <= 0.0
        or top_p > 1.0
        or len(options) != len(weights)
        or not options
    )
    ranked = sorted(zip(options, weights), key=lambda item: item[1], reverse=True)
    total = sum(weight for (_option, weight) in ranked)
    _check(not math.isfinite(total) or total <= 0.0)
    threshold, cumulative = top_p * total, 0.0
    retained = []
    for option, weight in ranked:
        retained.append((option, weight))
        cumulative += weight
        if cumulative >= threshold:
            break
    nucleus_options, nucleus_weights = zip(*retained)
    return tuple(nucleus_options), tuple(nucleus_weights)


def schedule_batch(
    completed,
    player_names,
    information_gain,
    *,
    first_game_number=None,
    pair_count=None,
    batch_number,
    rng=None,
    progress=None,
    required_player=None,
    active_players=None,
    scheduled_active_players=None,
    selection=None,
    allow_active_player_pairs=False,
    top_p=None,
):
    required, batch, gains = required_player, batch_number, information_gain
    active, scheduled, pairs = active_players, scheduled_active_players, pair_count
    names = list(player_names)
    _check(selection not in {None, "gain_proportional"})
    _check(selection == "gain_proportional" and scheduled is not None)
    _check(top_p is not None and selection != "gain_proportional")
    if scheduled is None:
        if pairs is None:
            pairs = _State.config.batch_games // 2
        _check(pairs < 1)
    _check(pairs is not None and scheduled is not None)
    _check(len(gains) != len(names) or any(len(row) != len(names) for row in gains))
    active_set = None
    if active is not None:
        _check(not active)
        _check(len(active) != len(set(active)) or bool(set(active) - set(names)))
        active_set = set(active)
    if scheduled is not None:
        _check(
            active_set is None
            or not scheduled
            or len(scheduled) != len(set(scheduled))
            or bool(set(scheduled) - active_set)
        )
    opts = [
        ((left, right), gains[left_idx][right_idx])
        for left_idx, left in enumerate(names)
        for right_idx, right in enumerate(names[left_idx + 1 :], left_idx + 1)
        if (
            active_set is None
            or (
                (left in active_set or right in active_set)
                and (
                    allow_active_player_pairs
                    or (left in active_set) != (right in active_set)
                )
            )
        )
        and (required is None or required in {left, right})
    ]
    _check(any(not math.isfinite(weight) or weight < 0 for (pair, weight) in opts))
    opts, weights = zip(*opts) if opts else ((), ())
    _check(not opts)
    if scheduled is None:
        _check(not any(weight > 0.0 for weight in weights))
        if active_set is None or selection == "gain_proportional":
            if top_p is not None:
                original_count = len(opts)
                opts, weights = _gain_nucleus(opts, weights, top_p)
                _call(
                    progress,
                    f"Batch {batch}: top-p={top_p:g} retained "
                    f"{len(opts)}/{original_count} gain-weighted pairs",
                )
            if rng is None:
                rng = random.Random(_Arena.RANDOM_SEED + batch)
            picks = rng.choices(opts, weights=weights, k=pairs)
        else:
            best_index = max(range(len(opts)), key=weights.__getitem__)
            picks = [opts[best_index]] * pairs
    else:
        picks = []
        for bot in scheduled:
            player_choices = [
                index for (index, option) in enumerate(opts) if bot in option
            ]
            _check(not player_choices)
            best_index = max(player_choices, key=weights.__getitem__)
            _check(weights[best_index] <= 0.0)
            picks.append(opts[best_index])
        pairs = len(picks)
    first_number = (
        len(completed) + 1 if first_game_number is None else first_game_number
    )
    _check(not isinstance(first_number, int) or first_number < 1)
    pairings = [*picks, *((right, left) for (left, right) in picks)]
    slot = [
        ScheduledGame(first_number + offset, batch, left, right)
        for (offset, (left, right)) in enumerate(pairings)
    ]
    _validate_color_swapped_schedule(slot, pairs)
    _call(
        progress,
        f"Batch {batch}: selected {pairs} pairs and scheduled "
        f"{len(slot)} color-swapped games",
    )
    return slot


def _match_config(
    network_players,
    schedule,
    *,
    max_moves=_Arena.MAX_MOVES,
    max_visits=_Arena.MAX_VISITS,
    num_game_threads=_Arena.MATCH_GAME_THREADS,
    nn_max_batch_size=_Arena.NN_MAX_BATCH_SIZE,
    num_eigen_threads_per_model=1,
):
    player_ids = {bot.name: index for (index, bot) in enumerate(network_players)}
    pairs = ",".join(
        f"{player_ids[game.black]}-{player_ids[game.white]}" for game in schedule
    )
    _check(not pairs)
    header = (
        "# Generated by arena.py. extraPairs are exact Black-White games.\n"
        "logSearchInfo = false\nlogMoves = false\nlogGamesEvery = 50\n"
        f"logToStdout = false\nnumBots = {len(network_players)}"
    )
    lines = header.splitlines()
    for index, bot in enumerate(network_players):
        _check(bot.network is None)
        _check(
            bot.chosen_move_temperature_early is None
            or bot.chosen_move_temperature is None
        )
        lines.extend(
            [
                f"botName{index} = {bot.name}",
                f"nnModelFile{index} = {bot.network}",
                f"chosenMoveTemperatureEarly{index} = "
                + f"{bot.chosen_move_temperature_early:g}",
                f"chosenMoveTemperature{index} = {bot.chosen_move_temperature:g}",
                *(
                    [
                        f"maxVisits{index} = {_player_max_visits(bot)}",
                        f"maxPlayouts{index} = {bot.max_playouts}",
                    ]
                    if bot.max_playouts is not None
                    else []
                ),
            ]
        )
    tail = (
        f"includeBots = 0\nextraPairs = {pairs}\nextraPairsAreOneSidedBW = true\n"
        f"numGameThreads = {min(num_game_threads, len(schedule))}\n"
        f"numGamesTotal = {len(schedule)}\nmaxMovesPerGame = {max_moves}\n"
        "allowResignation = true\nresignThreshold = -0.95\nresignConsecTurns = 3\n"
        "koRules = POSITIONAL\nscoringRules = AREA\ntaxRules = NONE\n"
        "multiStoneSuicideLegals = true\nhasButtons = false\n"
        f"bSizes = {_Arena.BOARD_SIZE}\nbSizeRelProbs = 1\nkomiAuto = false\n"
        f"komiMean = {_Arena.KOMI:g}\nhandicapProb = 0.0\n"
        "handicapCompensateKomiProb = 1.0\n"
        f"maxVisits = {max_visits}\nnumSearchThreads = {_Arena.NUM_SEARCH_THREADS}\n"
        f"nnMaxBatchSize = {nn_max_batch_size}\n"
        f"nnCacheSizePowerOfTwo = {_Arena.NN_CACHE_SIZE_POWER_OF_TWO}\n"
        f"nnMutexPoolSizePowerOfTwo = {_Arena.NN_MUTEX_POOL_SIZE_POWER_OF_TWO}\n"
        f"nnRandomize = true\nnumEigenThreadsPerModel = {num_eigen_threads_per_model}"
    )
    lines.extend(tail.splitlines())
    return "\n".join(lines) + "\n"


def _split_sgf_collection(contents):
    games: list[str] = []
    depth = 0
    start: int | None = None
    inside, escaped = False, False
    for index, character in enumerate(contents):
        if inside:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == "]":
                inside = False
            continue
        if character == "[":
            inside = True
        elif character == "(":
            if depth == 0:
                start = index
            depth += 1
        elif character == ")":
            depth -= 1
            _check(depth < 0)
            if depth == 0 and start is not None:
                games.append(contents[start : index + 1])
                start = None
    _check(depth != 0 or inside)
    return games


def _unescape_sgf(value):
    value = re.sub(r"\\\r\n|\\\n\r|\\[\r\n]", "", value)
    return re.sub("\\\\(.)", "\\1", value, flags=re.DOTALL)


def _sgf_main_line(sgf):
    """Parse SGF nodes, choosing the first variation at each branch."""
    position = 0

    def whitespace():
        nonlocal position
        while position < len(sgf) and sgf[position].isspace():
            position += 1

    def tree():
        nonlocal position
        whitespace()
        _check(position >= len(sgf) or sgf[position] != "(")
        position += 1
        nodes = []
        whitespace()
        while position < len(sgf) and sgf[position] == ";":
            position += 1
            node = {}
            whitespace()
            while position < len(sgf) and sgf[position].isalpha():
                start = position
                while position < len(sgf) and sgf[position].isalpha():
                    position += 1
                name = sgf[start:position]
                _check(name in node)
                values = []
                whitespace()
                while position < len(sgf) and sgf[position] == "[":
                    position += 1
                    start = position
                    while position < len(sgf) and sgf[position] != "]":
                        position += 2 if sgf[position] == "\\" else 1
                    _check(position >= len(sgf))
                    values.append(_unescape_sgf(sgf[start:position]))
                    position += 1
                    whitespace()
                _check(not values)
                node[name] = values
            nodes.append(node)
        _check(not nodes)
        first = True
        while position < len(sgf) and sgf[position] == "(":
            variation = tree()
            if first:
                nodes.extend(variation)
                first = False
            whitespace()
        _check(position >= len(sgf) or sgf[position] != ")")
        position += 1
        return nodes

    nodes = tree()
    whitespace()
    _check(position != len(sgf))
    return nodes


def _sgf_property(sgf, name):
    values = _sgf_main_line(sgf)[0].get(name)
    if values is None:
        raise _MissingSGFProperty(name)
    _check(len(values) != 1)
    return values[0]


def _sgf_moves(sgf):
    moves = []
    for node in _sgf_main_line(sgf):
        colors = [color for color in ("B", "W") if color in node]
        _check(len(colors) > 1)
        for color in colors:
            _check(len(node[color]) != 1)
            moves.append((color, _sgf_to_gtp(node[color][0])))
    return moves


def _sgf_to_gtp(value):
    if value == "":
        return "pass"
    _check(len(value) != 2)
    x, y = ord(value[0].lower()) - ord("a"), ord(value[1].lower()) - ord("a")
    _check(not (0 <= x < _Arena.BOARD_SIZE and 0 <= y < _Arena.BOARD_SIZE))
    return f"{COLS[x]}{_Arena.BOARD_SIZE - y}"


def _gtp_to_sgf(value):
    if value.lower() in {"pass", "resign"}:
        return ""
    x, row = COLS.index(value[0].upper()), int(value[1:])
    return chr(ord("a") + x) + chr(ord("a") + _Arena.BOARD_SIZE - row)


def _parse_result(result):
    if (upper := result.strip().upper()).startswith("B+"):
        return "B", 1.0, "resignation" if upper.endswith("+R") else "score"
    if upper.startswith("W+"):
        return "W", 0.0, "resignation" if upper.endswith("+R") else "score"
    if upper in {"0", "DRAW", "JIGO"}:
        return None, 0.5, "draw"
    raise ArenaError(f"unsupported game result {result!r}")


def _parse_native_sgf(sgf, slot):
    black, white = _sgf_property(sgf, "PB"), _sgf_property(sgf, "PW")
    _check((black, white) != (slot.black, slot.white))
    res = _sgf_property(sgf, "RE")
    side, score, reason = _parse_result(res)
    moves = _sgf_moves(sgf)
    if reason == "resignation":
        losing_color = "W" if side == "B" else "B"
        moves.append((losing_color, "resign"))
    winner = black if side == "B" else white if side == "W" else None
    outcome = res, side, winner, score, reason
    return _game_record(slot, outcome, (tuple(moves), "katago_match", sgf))


def _collect_native_games(slate, sgf_dir, *, max_moves):
    queues: dict[tuple[str, str], deque[ScheduledGame]] = defaultdict(deque)
    for game in slate:
        queues[game.black, game.white].append(game)
    recs: list[GameRecord] = []
    capped: list[ScheduledGame] = []
    for path in sorted(sgf_dir.glob("*.sgfs")) + sorted(sgf_dir.glob("*.sgf")):
        for sgf in _split_sgf_collection(path.read_text(encoding="utf-8")):
            pair = _sgf_property(sgf, "PB"), _sgf_property(sgf, "PW")
            _check(not queues[pair])
            slot = queues[pair].popleft()
            try:
                recs.append(_parse_native_sgf(sgf, slot))
            except _MissingSGFProperty as exc:
                if exc.name != "RE":
                    raise
                move_total = len(_sgf_moves(sgf))
                if move_total < max_moves:
                    raise ArenaError(
                        f"KataGo game {slot.number} is missing RE after only "
                        f"{move_total}/{max_moves} moves"
                    ) from exc
                capped.append(slot)
    _check([game for queue in queues.values() for game in queue])
    _check(len(recs) + len(capped) != len(slate))
    return recs, capped


def _native_attempt_paths(work_dir, attempt):
    suffix = "" if attempt == 1 else f"-retry-{attempt}"
    return (
        work_dir / f"match{suffix}.cfg",
        work_dir / f"katago-match{suffix}.log",
        work_dir / f"katago-sgfs{suffix}",
    )


def _discarded_game(game, attempt):
    return dict(zip(("game", "batch", "black", "white"), astuple(game))) | {
        "attempt": attempt,
        "move_limit": _Arena.MAX_MOVES,
    }


def _write_discarded_native_games(work_dir, games, attempt):
    _write_json(
        work_dir / f"discarded-native-games-attempt-{attempt}.json",
        [_discarded_game(game, attempt) for game in games],
    )


def _count_sgf_results(path):
    """Count completed games without trying to parse files still being written."""
    total = 0
    paths = path.glob("*.sgfs") if path.is_dir() else (path,)
    for sgf_path in paths:
        try:
            total += sgf_path.read_bytes().count(b"RE[")
        except OSError:
            # KataGo can create or rotate a shard while the heartbeat is scanning.
            continue
    return total


def _report_native_heartbeats(
    stopped, sgf_dir, *, batch, attempt, game_count, progress
):
    while not stopped.wait(_Arena.PROGRESS_INTERVAL_SECONDS):
        finished = min(_count_sgf_results(sgf_dir), game_count)
        _call(
            progress,
            f"Batch {batch} heartbeat: {finished}/{game_count} games finished "
            f"(KataGo attempt {attempt})",
        )


def _run_native_attempt(
    slate, network_players, work_dir, *, attempt, max_moves, progress
):
    config_path, log_path, sgf_dir = _native_attempt_paths(work_dir, attempt)
    console_path = log_path.with_suffix(".console.log")
    _check(
        config_path.exists()
        or log_path.exists()
        or console_path.exists()
        or sgf_dir.exists()
    )
    sgf_dir.mkdir(parents=True)
    config_path.write_text(
        _match_config(network_players, slate, max_moves=max_moves), encoding="utf-8"
    )
    command = [
        str(_State.katago_binary),
        "match",
        "-config",
        str(config_path),
        "-log-file",
        str(log_path),
        "-sgf-output-dir",
        str(sgf_dir),
    ]
    retry = "" if attempt == 1 else f" retry {attempt - 1}"
    _call(
        progress,
        f"Batch {slate[0].batch}: katago match{retry} starting "
        f"{len(slate)} network games (move limit {max_moves})",
    )
    stopped = threading.Event()
    heartbeat = None
    if progress is not None:
        heartbeat = threading.Thread(
            target=_report_native_heartbeats,
            args=(stopped, sgf_dir),
            kwargs={
                "batch": slate[0].batch,
                "attempt": attempt,
                "game_count": len(slate),
                "progress": progress,
            },
            name=f"arena-native-heartbeat-batch-{slate[0].batch}",
            daemon=True,
        )
        heartbeat.start()
    try:
        with console_path.open("w", encoding="utf-8") as out:
            subprocess.run(
                command,
                cwd=_Arena.ROOT,
                check=True,
                stdout=out,
                stderr=subprocess.STDOUT,
            )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ArenaError(
            f"katago match attempt {attempt} failed for {work_dir.name}: {exc}; "
            f"console output: {console_path}"
        ) from exc
    finally:
        stopped.set()
        if heartbeat is not None:
            heartbeat.join()
    _call(
        progress,
        f"Batch {slate[0].batch} heartbeat: "
        f"{min(_count_sgf_results(sgf_dir), len(slate))}/{len(slate)} games finished "
        f"(KataGo attempt {attempt} complete)",
    )
    _replace_text(
        work_dir / f"native-attempt-{attempt}.complete",
        f"games={len(slate)}\nmax_moves={max_moves}\n",
    )
    return sgf_dir


def _retry_capped_native_games(
    records,
    capped,
    network_players,
    work_dir,
    *,
    first_attempt,
    progress,
    recovering=False,
):
    log, recs = progress, records
    todo, attempt = list(capped), first_attempt
    if todo:
        _write_discarded_native_games(work_dir, todo, attempt - 1)
    while todo:
        _call(
            log,
            f"Batch {todo[0].batch}: retrying {len(todo)}"
            f" games discarded at the {_Arena.MAX_MOVES}-move limit",
        )
        pending_names = {name for game in todo for name in (game.black, game.white)}
        players = [bot for bot in network_players if bot.name in pending_names]
        marker_path = work_dir / f"native-attempt-{attempt}.complete"
        marker = f"games={len(todo)}\nmax_moves={_Arena.MAX_MOVES}\n"
        while (
            recovering
            and (
                not marker_path.is_file() or marker_path.read_bytes() != marker.encode()
            )
            and (
                marker_path.exists()
                or any(
                    path.exists() for path in _native_attempt_paths(work_dir, attempt)
                )
            )
        ):
            attempt += 1
            marker_path = work_dir / f"native-attempt-{attempt}.complete"
        if marker_path.is_file():
            _check(marker_path.read_text(encoding="utf-8") != marker)
            sgf_dir = _native_attempt_paths(work_dir, attempt)[2]
        else:
            _ensure_game_dependencies(todo, players)
            sgf_dir = _run_native_attempt(
                todo,
                players,
                work_dir,
                attempt=attempt,
                max_moves=_Arena.MAX_MOVES,
                progress=log,
            )
        batch_records, todo = _collect_native_games(
            todo, sgf_dir, max_moves=_Arena.MAX_MOVES
        )
        recs.extend(batch_records)
        if todo:
            _write_discarded_native_games(work_dir, todo, attempt)
        attempt += 1
    return recs


def run_native_games(schedule, player_values, work_dir, progress=None):
    slate = schedule
    if not slate:
        return []
    chunks = _partition_native_games(slate, player_values)
    manifest = _native_chunk_manifest(chunks, player_values)
    manifest_path = work_dir / "native-chunks.json"
    _check(manifest_path.exists())
    _write_json(manifest_path, manifest)
    recs = []
    for index, chunk in enumerate(chunks, 1):
        chunk_dir = work_dir / f"native-chunk-{index:03d}"
        chunk_dir.mkdir()
        recs.extend(
            _run_or_recover_native_chunk(
                chunk, player_values, chunk_dir, progress=progress, recovering=False
            )
        )
    return _ordered_results(sorted(recs, key=lambda game: game.number), slate)


def _partition_native_games(schedule, player_values):
    model_by_name = {
        bot.name: str(bot.network) for bot in player_values if bot.network is not None
    }
    _check(
        any(
            game.black not in model_by_name or game.white not in model_by_name
            for game in schedule
        )
    )
    return (tuple(schedule),)


def _native_chunk_manifest(chunks, player_values):
    model_by_name = {
        bot.name: str(bot.network) for bot in player_values if bot.network is not None
    }
    return [
        {
            "chunk": index,
            "games": [game.number for game in chunk],
            "models": sorted(
                {
                    model_by_name[name]
                    for game in chunk
                    for name in (game.black, game.white)
                }
            ),
        }
        for index, chunk in enumerate(chunks, 1)
    ]


def _run_or_recover_native_chunk(
    slate, player_values, work_dir, *, progress, recovering
):
    scheduled_names = {name for game in slate for name in (game.black, game.white)}
    bots = [
        bot
        for bot in player_values
        if bot.network is not None and bot.name in scheduled_names
    ]
    expected_marker = f"games={len(slate)}\nmax_moves={_Arena.MAX_MOVES}\n"
    completed_attempts = []
    for marker in work_dir.glob("native-attempt-*.complete"):
        match = re.fullmatch(r"native-attempt-([1-9][0-9]*)\.complete", marker.name)
        if match and marker.read_text(encoding="utf-8") == expected_marker:
            completed_attempts.append(int(match.group(1)))
    if completed_attempts:
        attempt = min(completed_attempts)
        sgf_dir = _native_attempt_paths(work_dir, attempt)[2]
    else:
        attempt = 1
        if recovering:
            while any(
                path.exists() for path in _native_attempt_paths(work_dir, attempt)
            ):
                attempt += 1
        _ensure_game_dependencies(slate, bots)
        sgf_dir = _run_native_attempt(
            slate,
            bots,
            work_dir,
            attempt=attempt,
            max_moves=_Arena.MAX_MOVES,
            progress=progress,
        )
    recs, capped = _collect_native_games(slate, sgf_dir, max_moves=_Arena.MAX_MOVES)
    return _retry_capped_native_games(
        recs,
        capped,
        bots,
        work_dir,
        first_attempt=attempt + 1,
        progress=progress,
        recovering=recovering,
    )


def _recover_native_games(schedule, player_values, work_dir, progress):
    manifest_path = work_dir / "native-chunks.json"
    if not manifest_path.is_file():
        if not any(
            path.exists() for path in _native_attempt_paths(work_dir, 1)
        ) and not any(work_dir.glob("native-chunk-*")):
            return run_native_games(schedule, player_values, work_dir, progress)
        bots = [bot for bot in player_values if bot.network is not None]
        sgf_dir = _native_attempt_paths(work_dir, 1)[2]
        _check(not sgf_dir.is_dir())
        recs, capped = _collect_native_games(
            schedule, sgf_dir, max_moves=_Arena.MAX_MOVES
        )
        return _retry_capped_native_games(
            recs,
            capped,
            bots,
            work_dir,
            first_attempt=2,
            progress=progress,
            recovering=True,
        )

    chunks = _partition_native_games(schedule, player_values)
    expected = _native_chunk_manifest(chunks, player_values)
    try:
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArenaError(
            f"cannot load native chunk manifest {manifest_path}: {exc}"
        ) from exc
    _check(saved != expected)
    recs = []
    for index, chunk in enumerate(chunks, 1):
        chunk_dir = work_dir / f"native-chunk-{index:03d}"
        if not chunk_dir.exists():
            chunk_dir.mkdir()
        recs.extend(
            _run_or_recover_native_chunk(
                chunk, player_values, chunk_dir, progress=progress, recovering=True
            )
        )
    return sorted(recs, key=lambda game: game.number)


def _escape_sgf(value):
    return value.replace("\\", "\\\\").replace("]", "\\]")


def _random_game_sgf(nodes, result, moves):
    move_nodes = "".join(
        f";{color}[{_gtp_to_sgf(move)}]" for (color, move) in moves if move != "resign"
    )
    return (
        f"(;FF[4]GM[1]SZ[{_Arena.BOARD_SIZE}]KM[{_Arena.KOMI:g}]RU[Tromp-Taylor]PB["
        f"{_escape_sgf(nodes.black)}]PW[{_escape_sgf(nodes.white)}]RE["
        f"{_escape_sgf(result)}]{move_nodes})"
    )


class _ArenaRandomStrategy:
    def __init__(self, seed, name):
        self.name = name
        self._random = random.Random(seed)

    def choose_move(self, state):
        opts = [
            f"{COLS[column]}{state.size - row}"
            for (row, vals) in enumerate(state.rows)
            for (column, value) in enumerate(vals)
            if value == "."
        ]
        opts.append("pass")
        return self._random.choice(opts)


@dataclass
class LLMGameStats:
    illegal_moves: int = 0
    api_problems: int = 0
    api_seconds: float = 0.0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class LLMGameAction:
    color: str
    move: str
    success: bool


@dataclass(frozen=True)
class LLMGameRecovery:
    game_attempt: int
    resume_game_id: str
    source_path: Path
    actions: tuple[LLMGameAction, ...]
    moves: tuple[tuple[str, str], ...]
    stats: LLMGameStats


def _llm_player_config(name):
    canonical = _canonical_active_llm_player_name(name)
    if canonical is None:
        raise ArenaError(f"unknown LLM player {name}")
    for api in _Arena.LLM_APIS:
        if canonical in api.players:
            return api, api.players[canonical]
    raise ArenaError(f"unknown LLM player {name}")


def _llm_api_config(name):
    if name == "anthropic_oauth":
        name = "anthropic"
    for api in _Arena.LLM_APIS:
        if name == api.name:
            return api
    raise ArenaError(f"unknown LLM API {name}")


def _llm_config(name):
    api, player = _llm_player_config(name)
    return api.name, player.model, player.level


def _codex_workspace_settings(harness):
    """The player name fixes preparation time, including for numbered replicas."""
    return replace(_State.config.workspace,
                   training_seconds=_CODEX_TRAINING_SECONDS[harness])


def _llm_player_manifest(name):
    api, player = _llm_player_config(name)
    manifest = {
        "name": name,
        "kind": api.manifest_kind,
        "model": player.model,
        "agentic_harness": player.agentic_harness,
        api.manifest_level_name: player.level,
        "timeout_seconds": None,
    }
    if player.agentic_harness == "api-multi":
        manifest.update(
            conversation="per_game_history_with_fresh_context_reset",
            conversation_version=CONVERSATION_VERSION,
            context_reset_tokens=CONTEXT_RESET_TOKENS,
            context_estimator="previous_usage_plus_current_prompt_utf8_bytes_v1",
            compaction=False,
            tools=False,
        )
    if player.agentic_harness in _CODEX_WORKSPACE_HARNESSES:
        settings = _codex_workspace_settings(player.agentic_harness)
        manifest.update(
            conversation="independent_checkpoint_copy_per_game",
            sandbox="bubblewrap_workspace_write",
            network_access="openai_proxy_only",
            workspace_retained=True,
            persistence="immutable_preparation_checkpoint_with_private_evaluation_copies",
            preparation_seconds=settings.training_seconds,
            evaluation_seconds=settings.evaluation_seconds,
            workspace_protocol=WORKSPACE_PROTOCOL_VERSION,
            resources=settings.manifest(),
            timeout_seconds=settings.evaluation_seconds,
            training_katago_access=False,
            apply_patch_preflight=False,
        )
    if api.base_url is not None:
        manifest["base_url"] = api.base_url
    manifest.update(api.protocol.manifest_options(player))
    if player.max_output_tokens is not None:
        _set_output_limit(manifest, api.max_tokens_field or "max_output_tokens", player.max_output_tokens)
        if api.max_tokens_field is None:
            manifest["output_limit_control"] = "subscription_server"
    elif api.name == "xai":
        manifest["output_limit_control"] = "no_separate_text_output_limit"
    if api.cost_tracking:
        manifest["cost_tracking"] = (
            "api_equivalent_token_usage"
            if api.protocol is _CodexProtocol
            else "token_usage"
        )
    return manifest


def _llm_api_key(api):
    api_key = os.environ.get(api.api_key_env)
    if not api_key and api.key_file_env is not None:
        _check(api.key_file_default is None)
        key_path = Path(
            os.environ.get(api.key_file_env, api.key_file_default)
        ).expanduser()
        try:
            api_key = key_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ArenaError(
                f"set {api.api_key_env} or provide an API key file via "
                f"{api.key_file_env}"
            ) from exc
        if not api_key:
            raise ArenaError(f"LLM API key file is empty: {key_path}")
    if not api_key:
        raise ArenaError(f"{api.api_key_env} is required for {api.name} players")
    return api_key


def _codex_workspace_proxy_credential(_api):
    return _openai_oauth_proxy_credential()


def _openai_oauth_proxy_credential():
    try:
        auth_path = _codex_auth_source()
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        if not isinstance(auth, dict) or auth.get("auth_mode") != "chatgpt":
            raise TypeError("Codex auth mode is not ChatGPT OAuth")
        tokens = auth["tokens"]
        access_token = tokens["access_token"]
        account_id = tokens["account_id"]
        if not isinstance(access_token, str) or not access_token:
            raise TypeError("access_token must be a nonempty string")
        if not isinstance(account_id, str) or not account_id:
            raise TypeError("account_id must be a nonempty string")
    except (OSError, KeyError, TypeError, json.JSONDecodeError, ArenaError) as exc:
        raise ArenaError(
            "This player requires a host OpenAI OAuth login; "
            "run `codex login` once on this VM"
        ) from exc
    return _OpenAIProxyCredential(
        bearer_token=access_token,
        host="chatgpt.com",
        path_prefix="/backend-api/codex",
        headers=(
            ("ChatGPT-Account-Id", account_id),
            ("originator", "codex_cli_rs"),
        ),
        auth_mode="oauth",
    )


class _OAuthResponseError(ArenaError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.body = {"retryable": retryable}


class _OpenAIOAuthClient:
    """Use the SDK only as an HTTP/SSE transport for the Codex OAuth endpoint.

    Authentication and streaming follow examples/simple_agent.py. Credentials
    are reread for each request so a renewed login takes effect during long runs.
    """

    def __init__(self, client_cls, api):
        credential = _openai_oauth_proxy_credential()
        self._client = client_cls(
            api_key=credential.bearer_token,
            base_url=api.base_url,
            **dict(api.client_options),
        )
        self._session_id = str(uuid.uuid4())
        self.responses = self

    def close(self):
        self._client.close()

    def create(self, **request):
        from httpx2 import TransportError

        credential = _openai_oauth_proxy_credential()
        headers = dict(credential.headers) | {
            "Authorization": f"Bearer {credential.bearer_token}",
            "OpenAI-Beta": "responses=experimental",
            "Accept": "text/event-stream",
            "session_id": self._session_id,
            "x-client-request-id": str(uuid.uuid4()),
        }
        # Keep the current-turn prompt as text in the arena's audit logs.
        if isinstance(request.get("input"), str):
            request["input"] = [{"role": "user", "content": request["input"]}]
        try:
            with self._client.responses.create(
                **request, extra_headers=headers
            ) as stream:
                return self._read_response(stream)
        except TransportError as exc:
            # The SDK uses httpx2, whose errors are distinct from httpx's.
            # Transport errors can escape directly while iterating a stream.
            raise _OAuthResponseError(
                "OAuth stream transport failed", retryable=True
            ) from exc

    @staticmethod
    def _read_response(stream):
        output_items = {}
        for event in stream:
            if event.type == "response.output_item.done":
                output_items[event.output_index] = event.item
            elif event.type == "response.completed":
                response = event.response
                if output_items:
                    response.output = [
                        output_items[index] for index in sorted(output_items)
                    ]
                return response
            elif event.type in {"response.failed", "response.incomplete"}:
                response = event.response
                detail = response.error or response.incomplete_details
                code = getattr(detail, "code", "")
                raise _OAuthResponseError(
                    f"OAuth response {response.status}: {detail}",
                    retryable=code in {"server_error", "rate_limit_exceeded"},
                )
            elif event.type == "error":
                raise _OAuthResponseError(
                    f"OAuth response error ({event.code}): {event.message}",
                    retryable=event.code in {"server_error", "rate_limit_exceeded"},
                )
        raise _OAuthResponseError(
            "OAuth stream ended without a completed response", retryable=True
        )


def _llm_client(player_name, *, work_dir=None, game_number=None):
    api, player = _llm_player_config(player_name)
    if player.agentic_harness in _CODEX_WORKSPACE_HARNESSES:
        if work_dir is None or game_number is None:
            raise ArenaError("Codex players require a game work directory and number")
        return _CodexGameClient(
            player_name,
            player,
            work_dir,
            game_number,
            proxy_credential=_codex_workspace_proxy_credential(api),
        )
    try:
        client_cls = __import__(api.sdk_module, fromlist=[api.sdk_client_path[0]])
        for attribute in api.sdk_client_path:
            client_cls = getattr(client_cls, attribute)
    except ModuleNotFoundError as exc:
        raise ArenaError(f"{api.sdk_module} Python package is missing") from exc
    if api.protocol is _OAuthResponsesProtocol:
        client = _OpenAIOAuthClient(client_cls, api)
    elif api.name == "anthropic":
        client = AnthropicClient(client_cls, api)
    else:
        kwargs = dict(api.client_options)
        kwargs["api_key"] = _llm_api_key(api)
        if api.base_url is not None:
            kwargs["base_url"] = api.base_url
        client = client_cls(**kwargs)
    if player.agentic_harness == "api-multi":
        if work_dir is None or game_number is None:
            client.close()
            raise ArenaError(
                "Multi-turn API players require a game work directory and number"
            )
        wire_format = (
            "responses"
            if issubclass(api.protocol, _ResponsesProtocol)
            else "google"
            if api.protocol is _GoogleInteractionsProtocol
            else "anthropic"
            if issubclass(api.protocol, _AnthropicMessagesProtocol)
            else "chat"
        )
        return ConversationClient(
            client,
            APIConversation(
                api.name,
                player.model,
                player_name,
                game_number,
                wire_format,
                context_window=player.context_window,
                max_tokens_field=api.max_tokens_field,
            ),
        )
    return client


def _prompt_board(state):
    columns = "".join(COLS[: state.size])
    lines = [columns]
    for row_index, row in enumerate(state.rows):
        row_number = state.size - row_index
        vals = "".join("Z" if value == "." else value for value in row)
        lines.append(f"{row_number} {vals}")
    return "\n".join(lines)


def _llm_move_prompt(state, legal_moves, ko_illegal_moves, recent_moves=()):
    bot = "Black" if state.to_move == "B" else "White"
    columns, board = " ".join(COLS[: state.size]), _prompt_board(state)
    legal_text = ", ".join(legal_moves)
    recent_text = (
        ", ".join(f"{color} {move}" for (color, move) in recent_moves) or "none"
    )
    ko_illegal_text = ", ".join(ko_illegal_moves) or "none"
    return (
        f"You are playing {bot} in an ongoing 9x9 Go game against another bot. "
        f"It is {bot} to move.\n\nRules: White komi 7.0, positional superko, "
        "passing allowed, self-capture of stones legal. "
        "Resolve captures by first removing opposing groups with no liberties, "
        "then removing any friendly groups with no liberties. "
        "Self-capture remains subject to positional superko. "
        "Resigning loses immediately. Two consecutive "
        "passes end the game. A draw is worth 0.5 points. Scoring uses strict "
        "Tromp-Taylor area scoring with no dead stone removal.\n\nCoordinates: columns "
        f"{columns} from left to right (I is "
        "skipped); rows 9 through 1 from top to bottom. B = Black, W = White, "
        f"Z = empty.\n\n{board}\n\nRecent 5 moves (oldest to newest): "
        f"{recent_text}\n\nCurrently illegal because of ko/superko: "
        f"{ko_illegal_text}\n\nLegal moves: {legal_text}\n\nLegal moves "
        "is authoritative for the current position and already accounts for ko and positional "
        f"superko.\n\n{_Arena.MOVE_OUTPUT_INSTRUCTIONS}"
    )


def _insert_before_move_output_instructions(prompt, instructions):
    marker = _Arena.MOVE_OUTPUT_INSTRUCTIONS
    index = prompt.rfind(marker)
    if index < 0:
        return f"{prompt}\n\n{instructions}"
    return f"{prompt[:index]}{instructions}\n\n{prompt[index:]}"


def _usage_dict(response):
    if (usage := getattr(response, "usage", None)) is None:
        return {}
    if isinstance(usage, dict):
        return usage
    dump = getattr(usage, "model_dump", None)
    return dump(mode="json") if callable(dump) else {}


def _llm_model_config(api, model):
    for player in api.players.values():
        if player.model == model:
            return player
    raise ArenaError(f"missing LLM pricing for {api.name} model {model}")


def _llm_token_usage(api, usage):
    return api.protocol.token_usage(usage)


def _input_token_counts(api, counts):
    cached = counts.cached_input_tokens
    if api is None or api.protocol.cached_input_is_in_input:
        cached = min(cached, counts.input_tokens)
        uncached = counts.input_tokens - cached
    else:
        uncached = counts.input_tokens
    return uncached, cached


def _llm_prices_at(player, started_at=None):
    if player.peak_prices is None and not player.scheduled_prices:
        return player.prices
    if started_at is None:
        # Calls normally carry their start time; undated estimates use the
        # configured base tier, but still respect announced future rate changes.
        if not player.scheduled_prices:
            return player.prices
        started_at = dt.datetime.now(dt.timezone.utc)
    try:
        instant = (
            started_at
            if isinstance(started_at, dt.datetime)
            else dt.datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        )
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=dt.timezone.utc)
        instant = instant.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return player.prices
    prices = player.prices
    for effective_date, scheduled_prices in sorted(player.scheduled_prices):
        if instant.date() >= dt.date.fromisoformat(effective_date):
            prices = scheduled_prices
    return (
        player.peak_prices
        if player.peak_prices is not None
        and instant.weekday() in player.peak_utc_weekdays
        and any(start <= instant.hour < end for start, end in player.peak_utc_hours)
        else prices
    )


def _llm_call_cost(usage, provider, model, *, started_at=None):
    if isinstance(usage.get("request_usages"), list):
        return sum(
            _llm_call_cost(request, provider, model, started_at=started_at)
            for request in usage["request_usages"]
        )
    api = _llm_api_config(provider)
    player = _llm_model_config(api, model)
    counts = _llm_token_usage(api, usage)
    input_price, cached_price, output_price = _llm_prices_at(player, started_at)
    cache_write_price = player.cache_write_price or 0.0
    if (
        player.long_context_min_tokens is not None
        and counts.input_tokens >= player.long_context_min_tokens
    ):
        # The elevated tier applies to the whole request, including cache reads
        # and writes, rather than only the tokens above the threshold.
        input_factor, cached_factor, output_factor = player.long_context_multipliers
        input_price *= input_factor
        cached_price *= cached_factor
        output_price *= output_factor
        cache_write_price *= input_factor
    uncached, cached = _input_token_counts(api, counts)
    cache_writes = counts.cache_write_tokens
    if api.protocol.cached_input_is_in_input and player.cache_write_price is not None:
        # Responses input_tokens includes writes. Anthropic instead reports
        # writes separately from input_tokens, so they must not be subtracted.
        cache_writes = min(cache_writes, uncached)
        uncached -= cache_writes
    billed_output = counts.output_tokens + (
        counts.reasoning_tokens if api.protocol.reasoning_is_billed else 0
    )
    cache_write_cost = cache_writes * cache_write_price
    return (
        uncached * input_price
        + cached * cached_price
        + cache_write_cost
        + billed_output * output_price
    ) / 1e6


def _append_jsonl(path, entry, **fields):
    value = entry | fields
    if _is_tracked_log_path(path):
        value = _sanitize_tracked_log_value(value)
    with _State.jsonl_write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size:
            with path.open("rb") as source:
                source.seek(-1, os.SEEK_END)
                incomplete = source.read(1) != b"\n"
            if incomplete:
                _read_jsonl_objects(path, "append log")
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(value, separators=(",", ":")) + "\n")
            if "conversation" in value:
                out.flush()
                os.fsync(out.fileno())


def _first_token_count(usage, *paths):
    for path in paths:
        value = usage
        for name in path.split("."):
            value = value.get(name) if isinstance(value, dict) else None
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return 0


def _sum_response_usages(requests):
    return {
        "input_tokens": sum(item.get("input_tokens", 0) for item in requests),
        "output_tokens": sum(item.get("output_tokens", 0) for item in requests),
        "input_tokens_details": {
            "cached_tokens": sum(
                item.get("input_tokens_details", {}).get("cached_tokens", 0)
                for item in requests
            ),
            "cache_write_tokens": sum(
                item.get("input_tokens_details", {}).get("cache_write_tokens", 0)
                for item in requests
            ),
        },
        "output_tokens_details": {
            "reasoning_tokens": sum(
                item.get("output_tokens_details", {}).get("reasoning_tokens", 0)
                for item in requests
            )
        },
        "request_usages": requests,
    }


def _request_prompt_text(request):
    prompt = request.get("input")
    if isinstance(prompt, str):
        return prompt
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict):
        return ""
    content = messages[0].get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block["text"] for block in content
                       if isinstance(block, dict) and isinstance(block.get("text"), str))
    return ""


def _compact_llm_call(entry):
    """Strip repeated prompts and normalize provider usage for the tracked ledger."""
    request = entry.get("request")
    request = request if isinstance(request, dict) else {}
    usage = entry.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    prompt = _request_prompt_text(request)
    provider = entry.get("provider")
    if not isinstance(provider, str):
        provider = "openai" if request.get("model") else "unknown"
    try:
        api = _llm_api_config(provider)
        counts = _llm_token_usage(api, usage)
    except ArenaError:
        api = None
        counts = _LLMTokenUsage(
            input_tokens=_first_token_count(
                usage, "input_tokens", "total_input_tokens", "prompt_tokens"
            ),
            cached_input_tokens=_first_token_count(
                usage,
                "cache_read_input_tokens",
                "total_cached_tokens",
                "input_tokens_details.cached_tokens",
                "prompt_tokens_details.cached_tokens",
                "prompt_cache_hit_tokens",
            ),
            cache_write_tokens=_first_token_count(
                usage,
                "cache_creation_input_tokens",
                "input_tokens_details.cache_write_tokens",
            ),
            output_tokens=_first_token_count(
                usage, "output_tokens", "total_output_tokens", "completion_tokens"
            ),
            reasoning_tokens=_first_token_count(
                usage,
                "total_thought_tokens",
                "output_tokens_details.reasoning_tokens",
                "completion_tokens_details.reasoning_tokens",
            ),
        )
    billed_output_tokens = counts.output_tokens + (
        counts.reasoning_tokens
        if api is not None and api.protocol.reasoning_is_billed
        else 0
    )
    _uncached_input_tokens, cached_input_tokens = _input_token_counts(api, counts)
    compact = {
        "schema_version": 2,
        "game": entry.get("game"),
        "move": entry.get("move"),
        "response_attempt": entry.get("attempt"),
        "api_attempt": entry.get("api_attempt", 1),
        "player": entry.get("player"),
        "provider": provider,
        "model": request.get("model"),
        "started_at": entry.get("started_at"),
        "api_seconds": entry.get("api_seconds", 0.0),
        "ok": entry.get("ok") is True,
        "input_tokens": counts.input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_tokens": counts.cache_write_tokens,
        "output_tokens": billed_output_tokens,
        "reasoning_tokens": counts.reasoning_tokens,
        "cost_usd": entry.get("cost_usd", 0.0),
        "output": entry.get("output", ""),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    if isinstance(usage.get("request_usages"), list):
        compact["usage"] = usage
    if isinstance(entry.get("conversation"), dict):
        compact["conversation"] = {
            key: value
            for key, value in entry["conversation"].items()
            if key not in {"user_items", "assistant_items"}
        }
    if entry.get("ok") is not True:
        compact.update(
            error=entry.get("error"),
            retryable=entry.get("retryable"),
            retry_in_seconds=entry.get("retry_in_seconds"),
            response_status=entry.get("response_status"),
        )
        for field in ("http_status", "recovery_action", "auth_mode", "quota_window", "quota_reset_at"):
            if field in entry:
                compact[field] = entry[field]
    elif "auth_mode" in entry:
        compact["auth_mode"] = entry["auth_mode"]
    return _sanitize_tracked_log_value(compact)


def _append_llm_call(raw_path, compact_path, entry, **fields):
    complete = _sanitize_private_log_value(entry | fields)
    with _State.jsonl_write_lock:
        _append_jsonl(raw_path, complete)
        if compact_path is not None:
            _append_jsonl(compact_path, _compact_llm_call(complete))


def _repair_compact_llm_calls(raw_path, compact_path):
    """Restore missing compact records from the authoritative raw ledger."""
    if compact_path is None or not raw_path.exists():
        return
    with _State.jsonl_write_lock:
        raw = _read_jsonl_objects(raw_path, "saved LLM API calls")
        partial_tail = False
        if compact_path.exists() and compact_path.stat().st_size:
            with compact_path.open("rb") as source:
                source.seek(-1, os.SEEK_END)
                partial_tail = source.read(1) != b"\n"
        compact = _read_jsonl_objects(
            compact_path, "compact LLM API calls", allow_partial_tail=True
        )
        counts = defaultdict(int)
        for entry in compact:
            counts[json.dumps(entry, sort_keys=True)] += 1
        missing = []
        for entry in raw:
            rendered = _compact_llm_call(entry)
            key = json.dumps(rendered, sort_keys=True)
            if counts[key]:
                counts[key] -= 1
            else:
                missing.append(rendered)
        if missing or partial_tail:
            compact_path.parent.mkdir(parents=True, exist_ok=True)
            _replace_text(
                compact_path,
                "".join(
                    json.dumps(entry, separators=(",", ":")) + "\n"
                    for entry in [*compact, *missing]
                ),
            )


def _write_first_prompt(path, prompt):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as out:
            out.write(prompt + "\n")
    except FileExistsError:
        return
    except OSError as exc:
        raise ArenaError(f"cannot write first LLM prompt to {path}: {exc}") from exc


def _llm_api_error(exc):
    body = getattr(exc, "body", None)
    body = body if isinstance(body, dict) else {}
    for value in (
        getattr(exc, "status_code", None),
        getattr(exc, "code", None),
        body.get("status"),
    ):
        if isinstance(value, int) or isinstance(value, str) and value.isdigit():
            return body, int(value)
    # The Codex SDK raises RuntimeError(turn.error.message). Some failed turns
    # have no structured HTTP details, including our proxy's 502 responses.
    if isinstance(exc, RuntimeError):
        match = re.match(r"unexpected status ([1-5][0-9]{2})\b", str(exc))
        if match:
            return body, int(match[1])
    if type(exc).__name__ == "ClaudeOAuthError":
        match = re.match(r"Claude OAuth refresh failed \(HTTP ([1-5][0-9]{2})\)", str(exc))
        if match:
            return body, int(match[1])
    return body, None


def _retryable_llm_api_error(exc):
    body, status = _llm_api_error(exc)
    return (
        isinstance(
            exc,
            (
                json.JSONDecodeError,
                _WorkspaceCodexTransportError,
            ),
        )
        or body.get("retryable") is True
        or status in {408, 409, 429}
        or status is not None
        and status >= 500
        or re.fullmatch(
            r"(?:APIConnection|APITimeout|InternalServer|RateLimit)Error",
            type(exc).__name__,
        )
        is not None
    )


def _http_parse_diagnostics(response):
    content = getattr(response, "content", b"")
    if not isinstance(content, bytes):
        content = str(content).encode("utf-8", errors="replace")
    return {
        "response_status": getattr(response, "status_code", None),
        "response_body_bytes": len(content),
    }


def _create_raw_llm_response(endpoint, request):
    raw = endpoint.with_raw_response.create(**request)
    try:
        return raw.parse()
    except json.JSONDecodeError as exc:
        exc.arena_http_diagnostics = _http_parse_diagnostics(raw.http_response)
        raise


def _positive_seconds(value, *, scale=1.0):
    try:
        secs = float(value) * scale
    except (TypeError, ValueError):
        return None
    return secs if math.isfinite(secs) and secs >= 0 else None


def _llm_api_retry_delay(exc, failed_attempt):
    quota_delay = getattr(exc, "arena_quota_retry_after", None)
    if quota_delay is not None:
        # The transport already includes a small reset buffer. Ordinary
        # proportional jitter would add many minutes to a weekly quota wait.
        return quota_delay
    body, _status = _llm_api_error(exc)
    hdrs = getattr(getattr(exc, "response", None), "headers", None)
    try:
        hdrs = hdrs or {}
        delays = (
            _positive_seconds(body.get("retry_after")),
            _positive_seconds(hdrs.get("retry-after-ms"), scale=0.001),
            _positive_seconds(hdrs.get("retry-after")),
        )
    except (AttributeError, TypeError):
        delays = (_positive_seconds(body.get("retry_after")),)
    initial = max(_Arena.LLM_API_RETRY_INITIAL_SECONDS, 0)
    maximum = max(_Arena.LLM_API_RETRY_MAX_SECONDS, 0)
    # Cap the exponent before exponentiating: retries can now last indefinitely.
    max_exponent = (
        max(0, math.ceil(math.log2(maximum) - math.log2(initial)))
        if initial and maximum else 0
    )
    exponent = min(max(failed_attempt - 1, 0), max_exponent)
    backoff = min(initial * 2.0 ** exponent, maximum)
    delay = max(
        (backoff, *(retry_delay for retry_delay in delays if retry_delay is not None))
    )
    jitter = delay * max(_Arena.LLM_API_RETRY_JITTER_FRACTION, 0)
    return delay + (_State.retry_random.uniform(0, jitter) if jitter else 0)


def _llm_api_attempts_remaining(attempt, *, codex_not_found_failures=0):
    return (
        (_Arena.LLM_API_MAX_ATTEMPTS <= 0 or attempt < _Arena.LLM_API_MAX_ATTEMPTS)
        and codex_not_found_failures < _Arena.CODEX_NOT_FOUND_MAX_ATTEMPTS
    )


def _llm_auth_recovery_hint(exc, api):
    status = _llm_api_error(exc)[1]
    if api.name in {"openai", "openai_codex_workspace"} and status == 401:
        return (
            "OpenAI credentials were rejected; renew the host login with `codex login` "
            "then use --resume."
        )
    if api.name in {"anthropic", "anthropic_oauth"} and (
        status in {401, 403}
        or type(exc).__name__ == "ClaudeOAuthError" and any(
            text in str(exc).lower() for text in ("sign in", "login has expired")
        )
    ):
        return (
            "Claude credentials were rejected; sign in with Claude Code again "
            "then use --resume."
        )
    return None


def _set_output_limit(options, field, limit):
    path = field.split(".")
    for key in path[:-1]:
        options = options.setdefault(key, {})
    options[path[-1]] = limit


def _llm_request(api, player, prompt):
    request = {"model": player.model}
    request.update(api.protocol.request_options(player, prompt))
    request.update(api.request_options)
    if player.max_output_tokens is not None and api.max_tokens_field is not None:
        _set_output_limit(request, api.max_tokens_field, player.max_output_tokens)
        cap_output_to_context(request, player.context_window, api.max_tokens_field)
    return request


def _llm_endpoint(client, api):
    endpoint = client
    for attribute in api.endpoint_path:
        endpoint = getattr(endpoint, attribute)
    return endpoint


def _llm_response_text(api, response):
    text = api.protocol.response_text(response)
    return text if isinstance(text, str) else ""


def _call_llm_move(
    client,
    prompt,
    *,
    player_name,
    log_path,
    compact_log_path=None,
    first_prompt_path=None,
    game_number,
    move_number,
    attempt,
    retry=None,
):
    name = player_name
    log, prompt_path = log_path, first_prompt_path
    api, player = _llm_player_config(name)
    endpoint = _llm_endpoint(client, api)
    prepare_prompt = getattr(endpoint, "prepare_prompt", None)
    if callable(prepare_prompt):
        prompt = prepare_prompt(prompt)
        if not isinstance(prompt, str):
            raise ArenaError(f"{api.name} produced a non-text turn prompt")
    req = _llm_request(api, player, prompt)
    cache_key = hashlib.sha256(f"{Path(log).resolve()}:{name}:{game_number}".encode()).hexdigest()
    if api.name in {"openai", "xai"}:
        req["prompt_cache_key"] = cache_key
    elif api.name == "openrouter":
        req.setdefault("extra_body", {})["session_id"] = cache_key
    log_entry = {
        "game": game_number,
        "move": move_number,
        "attempt": attempt,
        "player": name,
        "provider": api.name,
        "request": req,
    }
    conversation = (
        client.conversation if isinstance(client, ConversationClient) else None
    )
    if conversation is not None:
        try:
            with _State.jsonl_write_lock:
                if not conversation.loaded:
                    _read_jsonl_objects(log, "saved API conversation")
                conversation.load(log)
            try:
                saved = conversation.cached_reply(prompt, move_number, attempt)
            except ValueError:
                if attempt <= 1:
                    raise
                # Read-only compatibility for retries saved before we began
                # repeating the original prompt. Never send this legacy text.
                legacy_prompt = _insert_before_move_output_instructions(
                    prompt, "The previous move was not legal. Try again."
                )
                saved = conversation.cached_reply(legacy_prompt, move_number, attempt)
            if saved is not None:
                _repair_compact_llm_calls(log, compact_log_path)
                # Recovery statistics already include this durable successful call.
                return saved, 0.0, 0.0
            req = conversation.prepare(req, prompt)
            log_entry["conversation"] = conversation.pending
        except (ValueError, OSError) as exc:
            raise ArenaError(f"cannot prepare API conversation: {exc}") from exc
    total_time, failed_cost, api_try = 0.0, 0.0, 1
    context_resets = 0
    codex_not_found_failures = 0
    while True:
        started_at = dt.datetime.now(dt.timezone.utc).isoformat()
        start = time.perf_counter()
        try:
            harness_turn_id = _call(
                getattr(endpoint, "begin_turn", None),
                game_number,
                move_number,
                attempt,
                api_try,
                prompt,
                log,
            )
            if harness_turn_id is not None:
                log_entry["harness_turn_id"] = harness_turn_id
            materialize_prompt = getattr(endpoint, "prompt_for_log", None)
            logged_prompt = (
                materialize_prompt(prompt) if callable(materialize_prompt) else prompt
            )
            if not isinstance(logged_prompt, str):
                raise ArenaError(f"{api.name} produced a non-text logged prompt")
            _write_first_prompt(
                prompt_path or log.parent / "first_prompt.txt", logged_prompt
            )
            response = (
                _create_raw_llm_response(endpoint, req)
                if api.raw_response
                else endpoint.create(**req)
            )
        except Exception as exc:
            call_time = time.perf_counter() - start
            total_time += call_time
            failed_usage = getattr(exc, "arena_usage", {})
            cost = _llm_call_cost(
                failed_usage, api.name, player.model, started_at=started_at
            )
            failed_cost += cost
            auth_mode = getattr(exc, "arena_auth_mode", getattr(endpoint, "auth_mode", None))
            if auth_mode in {"oauth", "api_key"}:
                log_entry["auth_mode"] = auth_mode
                log_entry["request"] = (req | {"system": [{"type": "text", "text": CLAUDE_OAUTH_IDENTITY}]}
                                        if auth_mode == "oauth" and api.name == "anthropic" else req)
            quota_wait = getattr(exc, "arena_quota", None)
            reset_context = (
                conversation is not None
                and bool(conversation.history)
                and _context_length_error(exc)
                and context_resets == 0
            )
            retryable = reset_context or _retryable_llm_api_error(exc)
            if (isinstance(exc, _WorkspaceCodexTransportError)
                    and _workspace_codex_not_found(exc)):
                codex_not_found_failures += 1
            retrying = retryable and _llm_api_attempts_remaining(
                api_try, codex_not_found_failures=codex_not_found_failures
            )
            retry_delay = _llm_api_retry_delay(exc, api_try) if retrying else None
            status = _llm_api_error(exc)[1]
            recovery_hint = _llm_auth_recovery_hint(exc, api)
            if isinstance(exc, (WorkspaceTimeExpired, WorkspaceResourceExceeded)):
                recovery_action = "record_game_forfeit"
            elif retrying and quota_wait:
                recovery_action = "wait_for_quota_reset"
            elif retrying:
                recovery_action = "retry"
            elif recovery_hint:
                recovery_action = "renew_login_then_resume"
            else:
                recovery_action = "retry_limit_reached" if retryable else "inspect_error_then_resume"
            _append_llm_call(
                log,
                compact_log_path,
                log_entry,
                api_attempt=api_try,
                started_at=started_at,
                api_seconds=call_time,
                usage=failed_usage,
                cost_usd=cost,
                ok=False,
                retryable=retryable,
                retry_in_seconds=retry_delay,
                error=type(exc).__name__,
                http_status=status,
                recovery_action=recovery_action,
                **(quota_wait or {}),
                **getattr(exc, "arena_http_diagnostics", {}),
            )
            if retry_delay is None:
                if isinstance(exc, (WorkspaceTimeExpired, WorkspaceResourceExceeded)):
                    exc.arena_api_seconds = total_time
                    exc.arena_cost_usd = failed_cost
                    raise
                attempt_text = f" after {api_try} attempts" if api_try > 1 else ""
                raise ArenaError(
                    f"{api.name} API call failed{attempt_text}: {exc}"
                    + (f" {recovery_hint}" if recovery_hint else "")
                ) from exc
            if reset_context:
                context_resets += 1
                conversation.reset("provider_context_limit")
                req = conversation.prepare(_llm_request(api, player, prompt), prompt)
                log_entry["conversation"] = conversation.pending
            error = f"{type(exc).__name__}{f', HTTP {status}' if status else ''}"
            if quota_wait:
                error += f"; waiting for Claude quota ({quota_wait['quota_window']})"
                if "quota_reset_at" in quota_wait:
                    error += f"; reset at {dt.datetime.fromtimestamp(quota_wait['quota_reset_at'], dt.timezone.utc).isoformat()}"
            _call(retry, api_try, retry_delay, error)
            time.sleep(retry_delay)
            api_try += 1
            continue
        call_time = time.perf_counter() - start
        total_time += call_time
        break
    auth_mode = getattr(endpoint, "auth_mode", None)
    if auth_mode in {"oauth", "api_key"}:
        log_entry["auth_mode"] = auth_mode
        log_entry["request"] = (req | {"system": [{"type": "text", "text": CLAUDE_OAUTH_IDENTITY}]}
                                if auth_mode == "oauth" and api.name == "anthropic" else req)
    text = _llm_response_text(api, response)
    if getattr(response, "reused", False) is True:
        _repair_compact_llm_calls(log, compact_log_path)
        return text, 0.0, 0.0
    usage = _usage_dict(response)
    cost = _llm_call_cost(usage, api.name, player.model, started_at=started_at)
    event = None
    if conversation is not None:
        counts = _llm_token_usage(api, usage)
        observed = counts.input_tokens + counts.output_tokens
        if not api.protocol.cached_input_is_in_input:
            observed += counts.cached_input_tokens + counts.cache_write_tokens
        if api.protocol.reasoning_is_billed:
            observed += counts.reasoning_tokens
        if not (counts.input_tokens or counts.cached_input_tokens or counts.cache_write_tokens):
            observed = 0  # Missing input usage: estimate the full retained payload.
        event = conversation.completed_event(response, observed)
        log_entry["conversation"] = event
    _append_llm_call(
        log,
        compact_log_path,
        log_entry,
        api_attempt=api_try,
        started_at=started_at,
        api_seconds=call_time,
        cost_usd=cost,
        ok=True,
        output=text,
        usage=usage,
    )
    if event is not None:
        conversation.accept(event, text, move_number, attempt)
    return text, total_time, cost + failed_cost


def _choose_llm_move(
    game,
    client,
    stats,
    *,
    player_name,
    log_path,
    compact_log_path=None,
    first_prompt_path=None,
    game_number,
    move_number,
    retry=None,
    illegal_move=None,
):
    board_moves, ko_illegal_moves = game.get_possible_moves()
    legal_moves, state = [*board_moves, "resign"], game.get_board_state()
    recent_moves = game.get_move_history()[-5:]
    prompt = _llm_move_prompt(state, legal_moves, ko_illegal_moves, recent_moves)
    attempt = 1
    while True:
        raw, secs, cost = _call_llm_move(
            client,
            prompt,
            player_name=player_name,
            log_path=log_path,
            compact_log_path=compact_log_path,
            first_prompt_path=first_prompt_path,
            game_number=game_number,
            move_number=move_number,
            attempt=attempt,
            retry=retry,
        )
        stats.api_seconds += secs
        stats.cost_usd += cost
        move = raw.strip()
        if move in legal_moves:
            return move
        reused = (
            isinstance(client, ConversationClient) and client.conversation.last_reused
        ) or getattr(client, "last_reused", False) is True
        if move and not reused:
            stats.illegal_moves += 1
        elif not move and not reused:
            stats.api_problems += 1
        _call(illegal_move, raw, "response is not in the current legal-move list")
        attempt += 1


def _play_random_anchor_game(game, black, white):
    strategies = {"B": black, "W": white}
    moves: list[tuple[str, str]] = []
    while not game.get_game_result().ended:
        color = game.to_move
        strategy = strategies[color]
        if isinstance(strategy, _ArenaRandomStrategy):
            move = strategy.choose_move(game.get_board_state())
        else:
            move = strategy.choose_move(game)
        result = game.do_action(move, color)
        if not result.success:
            if isinstance(strategy, _ArenaRandomStrategy):
                continue
            raise RuntimeError(
                f"{strategy.name} selected illegal move {move}: " + f"{result.reason}"
            )
        moves.append((color, move))
        if not game.get_game_result().ended and len(moves) >= _Arena.MAX_MOVES:
            return None, tuple(moves)
    return game.get_game_result(), tuple(moves)


def _llm_game_record(slot, result, moves, stats):
    _check(not result.ended or result.score is None)
    _check(len(llm_names := _active_llm_players(_game_players(slot))) != 1)
    llm_name = next(iter(llm_names))
    api, _player = _llm_player_config(llm_name)
    return _finished_record(slot, result, moves, api.manifest_kind, stats)


def _finished_record(slot, result, moves, source, stats=None):
    _check(not result.ended or result.score is None)
    side, score, reason = _parse_result(result.score)
    winner = {"B": slot.black, "W": slot.white}.get(side)
    stats = stats or LLMGameStats()
    outcome = result.score, side, winner, score, result.reason or reason
    metrics = (
        stats.illegal_moves,
        stats.api_problems,
        stats.api_seconds,
        stats.cost_usd,
    )
    return _game_record(
        slot,
        outcome,
        (moves, source, _random_game_sgf(slot, result.score, moves)),
        metrics,
    )


def _play_llm_game(
    game,
    scheduled,
    opponent_strategy,
    client,
    stats,
    *,
    log_path,
    compact_log_path=None,
    first_prompt_path=None,
    move_completed,
    move_begin=None,
    api_retry=None,
    illegal_move=None,
    initial_moves=(),
):
    on_move, opp, slot = move_completed, opponent_strategy, scheduled
    moves, engine_moves = list(initial_moves), tuple(game.get_move_history())
    expected_moves = tuple((color, move) for (color, move) in moves if move != "resign")
    _check(engine_moves != expected_moves)
    if not game.get_game_result().ended and len(moves) >= _Arena.MAX_MOVES:
        return None, tuple(moves)
    move_time = time.perf_counter()
    announced_move = 0
    while not game.get_game_result().ended:
        color = game.to_move
        name = slot.black if color == "B" else slot.white
        move_num = len(moves) + 1
        if move_begin is not None and move_num != announced_move:
            move_begin(slot, move_num, color, name)
            announced_move = move_num
        if _is_active_llm_player(name):
            move = _choose_llm_move(
                game,
                client,
                stats,
                player_name=name,
                log_path=log_path,
                compact_log_path=compact_log_path,
                first_prompt_path=first_prompt_path,
                game_number=slot.number,
                move_number=len(moves) + 1,
                retry=partial(api_retry, slot, move_num, name)
                if api_retry is not None
                else None,
                illegal_move=partial(illegal_move, slot, move_num, color, name)
                if illegal_move is not None
                else None,
            )
        elif isinstance(opp, _ArenaRandomStrategy):
            move = opp.choose_move(game.get_board_state())
        else:
            move = opp.choose_move(game)
        result = game.do_action(move, color)
        if not result.success:
            if _is_active_llm_player(name):
                stats.illegal_moves += 1
                _call(
                    illegal_move,
                    slot,
                    move_num,
                    color,
                    name,
                    move,
                    result.reason or "Go engine rejected the move",
                )
                continue
            if isinstance(opp, _ArenaRandomStrategy):
                continue
            raise ArenaError(
                f"{opp.name} selected illegal move {move}: " + f"{result.reason}"
            )
        moves.append((color, move))
        if on_move is not None:
            on_move(
                slot, len(moves), color, name, move, time.perf_counter() - move_time
            )
        move_time = time.perf_counter()
        if not game.get_game_result().ended and len(moves) >= _Arena.MAX_MOVES:
            return None, tuple(moves)
    return game.get_game_result(), tuple(moves)


def _game_entry(record, *, numbered_moves):
    entry = {"game": record.number, **asdict(record)}
    entry.pop("number")
    moves = [
        {"number": number, "color": color, "move": move}
        for number, (color, move) in enumerate(record.moves, 1)
    ]
    if numbered_moves:
        entry.pop("sgf")
        entry["moves"] = moves
    else:
        entry["moves"] = [
            {"color": move["color"], "move": move["move"]} for move in moves
        ]
    return entry


def _batch_record_from_entry(entry):
    moves = tuple((str(move["color"]), str(move["move"])) for move in entry["moves"])
    game = (
        int(entry["game"]),
        int(entry["batch"]),
        str(entry["black"]),
        str(entry["white"]),
    )
    result = (
        str(entry["result"]),
        entry["winner_color"],
        entry["winner"],
        float(entry["score_black"]),
        str(entry["reason"]),
    )
    metrics = (
        int(entry["llm_illegal_moves"]),
        int(entry["llm_api_problems"]),
        float(entry["llm_api_seconds"]),
        float(entry["llm_cost_usd"]),
    )
    record = _game_record(
        game, result, (moves, str(entry["source"]), str(entry.get("sgf", ""))), metrics
    )
    return replace(
        record,
        llm_input_tokens=entry.get("llm_input_tokens"),
        llm_cached_input_tokens=entry.get("llm_cached_input_tokens"),
        llm_output_tokens=entry.get("llm_output_tokens"),
    )


def _read_jsonl_objects(path, description, *, allow_partial_tail=True):
    if not path.exists():
        return []
    items = []
    try:
        with _State.jsonl_write_lock, path.open("rb") as src:
            offset = 0
            for line in src:
                if line.strip():
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        if allow_partial_tail and not line.endswith(b"\n"):
                            # Remove the torn append before any future writer can
                            # concatenate another record onto its invalid bytes.
                            with path.open("r+b") as repair:
                                repair.truncate(offset)
                            break
                        raise
                    _check(not isinstance(entry, dict))
                    items.append(entry)
                offset += len(line)
                if allow_partial_tail and not line.endswith(b"\n"):
                    with path.open("ab") as repair:
                        repair.write(b"\n")
    except (OSError, TypeError, ValueError) as exc:
        raise ArenaError(f"cannot read {description} {path}: {exc}") from exc
    return items


def _recovered_llm_stats(scheduled, actions, call_entries):
    stats = LLMGameStats()
    for entry in call_entries:
        try:
            game_num = int(entry.get("game", -1))
        except (TypeError, ValueError):
            continue
        if game_num != scheduled.number:
            continue
        _check((api_time := _positive_seconds(entry.get("api_seconds"))) is None)
        stats.api_seconds += api_time
        _check((cost := _positive_seconds(entry.get("cost_usd", 0))) is None)
        stats.cost_usd += cost
        if entry.get("ok") is not True:
            continue
        req, out = entry.get("request"), entry.get("output")
        _check(not isinstance(req, dict) or not isinstance(out, str))
        prompt = _request_prompt_text(req)
        match = re.search("^Legal moves(?: now)?: (.+)$", prompt or "", re.MULTILINE)
        _check(match is None)
        legal_moves = {act.strip() for act in match.group(1).split(",")}
        move = out.strip()
        if move not in legal_moves:
            if move:
                stats.illegal_moves += 1
            else:
                stats.api_problems += 1
    stats.illegal_moves += sum(
        act.color in {"B", "W"}
        and _is_active_llm_player(
            scheduled.black if act.color == "B" else scheduled.white
        )
        and not act.success
        for act in actions
    )
    return stats


def _read_llm_action_log(path, scheduled):
    items = _read_jsonl_objects(path, "saved game actions")
    starts = [
        index
        for index, entry in enumerate(items)
        if entry.get("event") == "game_started"
    ]
    _check(not starts)
    items, acts, game_ended = items[starts[-1] :], [], False
    version = items[0].get("legality_enforcement_version")
    if version is not None and version != LEGALITY_ENFORCEMENT_VERSION:
        raise ArenaError(
            f"unsupported legality enforcement version in {path}: {version}"
        )
    header = {
        "board_size": _Arena.BOARD_SIZE,
        "komi": _Arena.KOMI,
        "rules": _Arena.RULES,
        "max_moves": None,
    }
    _check(any(items[0].get(field) != wanted for (field, wanted) in header.items()))
    for entry in items[1:]:
        event = entry.get("event")
        if event == "game_ended":
            game_ended = True
            continue
        _check(event not in {"move_played", "move_rejected"} or game_ended)
        color, move, success = map(entry.get, ("color", "move", "success"))
        expected_success = event == "move_played"
        _check(
            color not in {"B", "W"}
            or not isinstance(move, str)
            or success is not expected_success
        )
        acts.append(LLMGameAction(color, move, expected_success))
    return tuple(acts)


def _load_llm_game_recovery(work_dir, slot, call_entries):
    opts = []
    prefix = re.escape(f"game-{slot.number:06d}")
    for path in work_dir.glob(f"game-{slot.number:06d}*.actions.jsonl"):
        match = re.fullmatch(
            rf"{prefix}(?:-retry-(\d+))?(?:-resume-(\d+))?\.actions\.jsonl", path.name
        )
        if match:
            acts = _read_llm_action_log(path, slot)
            opts.append(
                (
                    int(match.group(1) or 1),
                    sum(act.success for act in acts),
                    int(match.group(2) or 0),
                    path.stat().st_mtime_ns,
                    path,
                    acts,
                )
            )
    if not opts:
        return None
    attempt, *_, src, acts = max(opts, key=lambda candidate: candidate[:4])
    next_resume_index = 1 + max(option[2] for option in opts if option[0] == attempt)
    suffix = "" if attempt == 1 else f"-retry-{attempt}"
    moves = tuple((act.color, act.move) for act in acts if act.success)
    resume_id = f"game-{slot.number:06d}{suffix}-resume-{next_resume_index}"
    stats = _recovered_llm_stats(slot, acts, call_entries)
    return LLMGameRecovery(attempt, resume_id, src, acts, moves, stats)


def _replay_llm_game(game, slot, opponent, recovery):
    accepted = []
    for act in recovery.actions:
        name = slot.black if act.color == "B" else slot.white
        if isinstance(opponent, _ArenaRandomStrategy) and not _is_active_llm_player(
            name
        ):
            _check(opponent.choose_move(game.get_board_state()) != act.move)
        result = game.do_action(act.move, act.color)
        if result.success != act.success:
            raise ArenaError(
                f"cannot recover game {slot.number} from {recovery.source_path}: "
                f"saved action {act.color} {act.move} after {len(accepted)} moves "
                f"is incompatible with strict legality version "
                f"{LEGALITY_ENFORCEMENT_VERSION}: "
                f"{result.reason or 'saved rejection is now legal'}"
            )
        if result.success:
            accepted.append((result.color, result.move))
    _check(tuple(accepted) != recovery.moves)
    return tuple(accepted)


def _game_engine(log_dir, game_id):
    return KataGoGameEngine(
        board_size=_Arena.BOARD_SIZE,
        komi=_Arena.KOMI,
        rules=_Arena.RULES,
        katago_binary=_State.katago_binary,
        model_path=KATAGO_MODEL,
        config_path=KATAGO_CONFIG,
        log_dir=log_dir,
        game_id=game_id,
        max_moves=None,
    )


def _network_strategy(player, config, log_dir):
    return KataGoNetworkStrategy(
        player.network,
        name=player.name,
        katago_binary=_State.katago_binary,
        config_path=config,
        log_dir=log_dir,
        max_visits=_player_max_visits(player),
        max_playouts=player.max_playouts,
        num_search_threads=_Arena.NUM_SEARCH_THREADS,
        delay_move_scale=0,
        delay_move_max=0,
    )


def _llm_log_path(work_dir, stem):
    return work_dir / f"llm-{stem}.jsonl"


def _llm_game_worker_count(player_name, game_count):
    _llm_player_config(player_name)
    return min(2, game_count)


def run_llm_games(
    schedule,
    player_values,
    work_dir,
    *,
    first_prompt_path=None,
    compact_calls_path=None,
    progress,
    starting_move_count=0,
    progress_tracker=None,
):
    log, slate, track = progress, schedule, progress_tracker
    work, prompt_path = work_dir, first_prompt_path
    if not slate:
        return []
    llm_by_game = [_active_llm_players(_game_players(game)) for game in slate]
    _check(any(len(players) != 1 for players in llm_by_game))
    llm_names = set().union(*llm_by_game)
    _check(len(llm_names) != 1)
    llm_name = next(iter(llm_names))
    opponents = {game.white if game.black == llm_name else game.black for game in slate}
    _check(len(opponents) != 1)
    opponent_name = next(iter(opponents))
    bots = {bot.name: bot for bot in player_values}
    _check((opp := bots.get(opponent_name)) is None)
    records_path = _llm_log_path(work, "games")
    calls_path = _llm_log_path(work, "calls")
    _repair_compact_llm_calls(calls_path, compact_calls_path)
    calls = _read_jsonl_objects(calls_path, "saved LLM API calls")
    saved_games = [
        _batch_record_from_entry(entry)
        for entry in _read_jsonl_objects(records_path, "saved LLM games")
    ]
    for rec in saved_games:
        _call(track and track.finish_game, rec.number, len(rec.moves))
    saved_numbers = {rec.number for rec in saved_games}
    todo = [game for game in slate if game.number not in saved_numbers]
    _check(len(saved_numbers) != len(saved_games))
    _check(saved_numbers - {game.number for game in slate})
    if not todo:
        return sorted(saved_games, key=lambda game: game.number)
    _ensure_game_dependencies(todo, player_values)
    if _llm_player_config(llm_name)[1].agentic_harness in _CODEX_WORKSPACE_HARNESSES:
        _CodexGameClient.prune_evaluation_images(
            _agent_run_dir(Path(work).resolve()),
            llm_name,
            {
                Path(work).resolve() / "agent-workspaces" / f"game-{game.number:06d}"
                for game in slate
            },
        )
    cfgs = _write_random_bot_configs([opp] if opp.network is not None else [], work)
    total_moves = starting_move_count + sum(len(rec.moves) for rec in saved_games)
    move_lock = threading.Lock()

    def on_move(slot, game_moves, color, player, move, seconds):
        nonlocal total_moves
        with move_lock:
            total_moves += 1
            move_total = total_moves
        _call(track and track.finish_move, slot.number, seconds)
        _call(
            log,
            f"Batch {slot.batch}: {move_total} moves finished "
            f"(game {slot.number}, move {game_moves}: "
            f"{player} ({color}) played {move} in {seconds:.3f}s)",
        )

    def on_api_retry(slot, move, player, attempt, delay, error):
        limit = (
            f"/{_Arena.LLM_API_MAX_ATTEMPTS}" if _Arena.LLM_API_MAX_ATTEMPTS > 0
            else " (automatic recovery)"
        )
        _call(
            log,
            f"Batch {slot.batch}: game {slot.number}, move {move}: "
            f"{player} API request failed with {error}; retrying attempt "
            f"{attempt + 1}{limit} in {delay:.1f}s",
        )

    def on_illegal_move(slot, move, color, player, output, reason):
        rendered = json.dumps(output, ensure_ascii=False)
        if len(rendered) > 500:
            rendered = rendered[:496] + '..."'
        problem = "illegal move" if output.strip() else "API problem"
        _call(
            log,
            f"Batch {slot.batch}: LLM {problem} in game {slot.number}, "
            f"move {move}: {player} ({color}) returned {rendered}; {reason}",
        )

    def run_one(slot):
        _call(track and track.start_game, slot)
        resume = _load_llm_game_recovery(work, slot, calls)
        stats = resume.stats if resume else LLMGameStats()
        attempt = resume.game_attempt if resume else 1
        with contextlib.ExitStack() as resources:
            client = _llm_client(llm_name, work_dir=work, game_number=slot.number)
            close = getattr(client, "close", None)
            if callable(close):
                resources.callback(close)
            if isinstance(client, ConversationClient):
                client.conversation.set_game_attempt(attempt)
                if resume and any(
                    color == ("B" if slot.black == llm_name else "W")
                    for color, _move in resume.moves
                ):
                    with _State.jsonl_write_lock:
                        client.conversation.load(calls_path)
                    if not client.conversation.replies:
                        raise ArenaError(
                            "cannot resume multi-turn game without its raw "
                            "conversation ledger"
                        )
            game_id = resume.resume_game_id if resume else f"game-{slot.number:06d}"
            game = resources.enter_context(_game_engine(work, game_id))
            uses_network = opp.network is not None
            strategy = (
                _network_strategy(opp, cfgs[opp.name], work)
                if uses_network
                else _ArenaRandomStrategy(
                    _Arena.RANDOM_SEED + slot.number + (attempt if attempt > 1 else 0),
                    _Arena.ANCHOR,
                )
            )
            if uses_network:
                resources.callback(strategy.close)
            opening = _replay_llm_game(game, slot, strategy, resume) if resume else ()
            if resume:
                nonlocal total_moves
                with move_lock:
                    total_moves += len(opening)
                _call(
                    log,
                    f"Batch {slot.batch}: resumed game {slot.number} "
                    f"after {len(opening)} saved moves from {resume.source_path}",
                )
            while True:
                try:
                    res, moves = _play_llm_game(
                        game,
                        slot,
                        strategy,
                        client,
                        stats,
                        log_path=calls_path,
                        compact_log_path=compact_calls_path,
                        first_prompt_path=prompt_path,
                        move_completed=on_move,
                        move_begin=track.start_move if track else None,
                        api_retry=on_api_retry,
                        illegal_move=on_illegal_move,
                        initial_moves=opening,
                    )
                except (WorkspaceTimeExpired, WorkspaceResourceExceeded) as exc:
                    stats.api_seconds += getattr(exc, "arena_api_seconds", 0)
                    stats.cost_usd += getattr(exc, "arena_cost_usd", 0)
                    winner = "W" if slot.black == llm_name else "B"
                    reason = "agent_time_limit" if isinstance(exc, WorkspaceTimeExpired) else "agent_memory_limit"
                    suffix = "T" if isinstance(exc, WorkspaceTimeExpired) else "F"
                    res = GameResult(True, winner, f"{winner}+{suffix}", reason)
                    moves = tuple(game.get_move_history())
                if res is None and isinstance(client, _CodexGameClient):
                    # Capped evaluation attempts cannot buy another clock or
                    # another opportunity to learn from the same checkpoint.
                    winner = "W" if slot.black == llm_name else "B"
                    res = GameResult(True, winner, f"{winner}+F", "move_limit")
                if res is not None:
                    break
                attempt += 1
                _call(getattr(client, "reset_game", None))
                game.reset_for_game(
                    game_id=f"game-{slot.number:06d}-retry-{attempt}", log_dir=work
                )
                if uses_network:
                    strategy.reset_for_game(game)
                else:
                    strategy = _ArenaRandomStrategy(
                        _Arena.RANDOM_SEED + slot.number + attempt, _Arena.ANCHOR
                    )
                opening = ()
            rec = _llm_game_record(slot, res, moves, stats)
            _append_jsonl(records_path, _game_entry(rec, numbered_moves=False))
            _call(getattr(client, "mark_complete", None))
            _call(track and track.finish_game, slot.number, len(rec.moves))
            return rec

    workers = _llm_game_worker_count(llm_name, len(todo))
    if workers == 1:
        new_games = [run_one(slot) for slot in todo]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            new_games = list(executor.map(run_one, todo))
    return sorted([*saved_games, *new_games], key=lambda game: game.number)


def _write_random_bot_configs(players_to_configure, log_dir):
    try:
        base_config = KATAGO_CONFIG.read_text(encoding="utf-8").rstrip()
    except OSError as exc:
        raise ArenaError(f"cannot read KataGo config {KATAGO_CONFIG}: {exc}") from exc
    config_dir = log_dir / "bot-configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for bot in players_to_configure:
        if bot.network is None:
            continue
        _check(
            bot.chosen_move_temperature_early is None
            or bot.chosen_move_temperature is None
        )
        path = config_dir / f"{bot.name}.cfg"
        text = (
            f"{base_config}\n\n# Arena bot-specific move-selection parameters.\n"
            "chosenMoveTemperatureEarly = "
            f"{bot.chosen_move_temperature_early:g}\nchosenMoveTemperature = "
            f"{bot.chosen_move_temperature:g}\n"
        )
        path.write_text(text, encoding="utf-8")
        paths[bot.name] = path
    return paths


def _run_random_game(slot, player_by_name, log_dir, discard=None):
    names = _game_players(slot) - {_Arena.ANCHOR}
    _check(len(names) != 1 or (opp := player_by_name.get(names.pop())) is None)
    _check(opp.network is None)
    config = _write_random_bot_configs([opp], log_dir)[opp.name]
    with (
        _game_engine(log_dir, f"game-{slot.number:04d}") as game,
        _network_strategy(opp, config, log_dir) as net,
    ):
        attempt = 1
        while True:
            if attempt > 1:
                game.reset_for_game(
                    game_id=f"game-{slot.number:04d}-retry-{attempt}", log_dir=log_dir
                )
                net.reset_for_game(game)
            seed = (
                _Arena.RANDOM_SEED
                + slot.number
                + (attempt - 1) * (_State.config.total_games + 1)
            )
            random_bot = _ArenaRandomStrategy(
                random.Random(seed).randrange(2**63), _Arena.ANCHOR
            )
            black = random_bot if slot.black == _Arena.ANCHOR else net
            white = random_bot if slot.white == _Arena.ANCHOR else net
            res, moves = _play_random_anchor_game(game, black, white)
            if res is not None:
                return _finished_record(slot, res, moves, "uniform_random")
            _call(discard, slot, attempt)
            attempt += 1


def _report_random_heartbeats(stopped, finished, lock, *, batch, game_count, progress):
    while not stopped.wait(_Arena.PROGRESS_INTERVAL_SECONDS):
        with lock:
            count = finished[0]
        _call(
            progress,
            f"Batch {batch} random-anchor heartbeat: "
            f"{count}/{game_count} games finished",
        )


def run_random_games(schedule, player_values, work_dir, completion=None, progress=None):
    slate = schedule
    if not slate:
        return []
    logs = work_dir / "random-game-logs"
    logs.mkdir(parents=True, exist_ok=True)
    bots = {bot.name: bot for bot in player_values}
    workers = min(max(_State.random_game_workers, 1), len(slate))
    lock = threading.Lock()
    finished = [0]

    def on_discard(game, attempt):
        with lock:
            _append_jsonl(
                work_dir / "discarded-random-games.jsonl",
                _discarded_game(game, attempt),
            )

    batch = slate[0].batch
    game_word = "game" if len(slate) == 1 else "games"
    worker_word = "worker" if workers == 1 else "workers"
    _call(
        progress,
        f"Batch {batch}: random-anchor games starting "
        f"({len(slate)} {game_word}, {workers} {worker_word})",
    )
    stopped = threading.Event()
    heartbeat = None
    if progress is not None:
        heartbeat = threading.Thread(
            target=_report_random_heartbeats,
            args=(stopped, finished, lock),
            kwargs={
                "batch": batch,
                "game_count": len(slate),
                "progress": progress,
            },
            name=f"arena-random-heartbeat-batch-{batch}",
            daemon=True,
        )
        heartbeat.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _run_random_game,
                    game,
                    bots,
                    logs / f"game-{game.number:06d}",
                    on_discard,
                )
                for game in slate
            }
            recs = []
            for future in concurrent.futures.as_completed(futures):
                recs.append(future.result())
                with lock:
                    finished[0] += 1
                    count = finished[0]
                _call(completion, count)
    finally:
        stopped.set()
        if heartbeat is not None:
            heartbeat.join()
    _call(
        progress,
        f"Batch {batch} random-anchor heartbeat: "
        f"{len(recs)}/{len(slate)} games finished (complete)",
    )
    sgf_path = work_dir / "random-games.sgfs"
    serialized = "\n".join(
        game.sgf for game in sorted(recs, key=lambda game: game.number)
    )
    _replace_text(sgf_path, serialized + "\n")
    return sorted(recs, key=lambda game: game.number)


def _load_saved_random_games(schedule, sgf_path):
    wanted = sorted(schedule, key=lambda game: game.number)
    try:
        saved = _split_sgf_collection(sgf_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ArenaError(f"cannot load saved random SGFs {sgf_path}: {exc}") from exc
    _check(len(saved) != len(wanted))
    recs = []
    for slot, sgf in zip(wanted, saved):
        rec = _parse_native_sgf(sgf, slot)
        recs.append(replace(rec, source="uniform_random"))
    return recs


def _active_player_game_counts(games):
    counts = {bot: 0 for bot in _State.config.active_players}
    for game in games:
        players = _active_players_in_game(game)
        _check(not players)
        for bot in players:
            counts[bot] += 1
    return counts


def _active_players_in_game(game):
    return tuple(
        name
        for name in (game.black, game.white)
        if name in _State.config.active_players
    )


def _active_matchup(game):
    active_players = _active_players_in_game(game)
    _check(len(active_players) != 1)
    active_black = game.black == active_players[0]
    return (
        (game.black, game.white, True)
        if active_black
        else (game.white, game.black, False)
    )


def _validate_llm_schedule(schedule):
    active_players = set()
    for game in schedule:
        bot, _opponent, _active_black = _active_matchup(game)
        active_players.add(bot)
    _check(len(active_players) != 1 or len(schedule) != _State.config.batch_games)
    _validate_color_swapped_schedule(schedule, _State.config.batch_games // 2)
    return next(iter(active_players))


def _quarantine_incomplete_batch(work_dir):
    """Set aside legacy initialization failures only when no execution exists."""
    if not work_dir.is_dir():
        return False
    if any(
        path.name not in {"schedule.json", "schedule.json.tmp"}
        for path in work_dir.iterdir()
    ):
        return False
    try:
        _load_saved_schedule(work_dir)
        return False
    except ArenaError:
        work_dir.rename(
            work_dir.with_name(f".{work_dir.name}-incomplete-{uuid.uuid4().hex}")
        )
        return True


def _load_saved_schedule(work_dir):
    schedule_path = work_dir / "schedule.json"
    try:
        items = json.loads(schedule_path.read_text(encoding="utf-8"))
        slate = [ScheduledGame(**entry) for entry in items]
    except (OSError, TypeError, ValueError, KeyError) as exc:
        raise ArenaError(f"cannot load saved schedule {schedule_path}: {exc}") from exc
    _check(not slate)
    return slate


def _llm_matchmaking_opponents(player_names):
    return [
        name
        for name in player_names
        if name not in _State.config.active_players and not _is_active_llm_player(name)
    ]


def _ordered_results(records, schedule):
    wanted = [game.number for game in schedule]
    _check(len(records) != len(schedule) or [game.number for game in records] != wanted)
    return records


def recover_batch(
    work_dir,
    player_values,
    progress=None,
    *,
    first_prompt_path=None,
    compact_calls_path=None,
    starting_move_count=0,
    progress_tracker=None,
):
    move_total, prompt_path = starting_move_count, first_prompt_path
    roster, track, log = player_values, progress_tracker, progress
    recovery_options = {
        "first_prompt_path": prompt_path,
        "compact_calls_path": compact_calls_path,
        "starting_move_count": move_total,
        "progress_tracker": track,
    }
    slate = _load_saved_schedule(work_dir)
    if not _State.katago_mode:
        _validate_llm_schedule(slate)
    if any(_active_llm_players(_game_players(game)) for game in slate):
        _check(any(not _active_llm_players(_game_players(game)) for game in slate))
        recs = run_llm_games(slate, roster, work_dir, progress=log, **recovery_options)
        return slate, _ordered_results(recs, slate)
    native_games = [game for game in slate if _Arena.ANCHOR not in _game_players(game)]
    random_schedule = [game for game in slate if _Arena.ANCHOR in _game_players(game)]
    if native_games:
        native = _recover_native_games(native_games, roster, work_dir, log)
        if log is not None:
            log(f"Batch {slate[0].batch}: recovered {len(native)} native games")
    else:
        native = []
    if random_schedule:
        random_path = work_dir / "random-games.sgfs"
        random = None
        if random_path.is_file():
            try:
                random = _load_saved_random_games(random_schedule, random_path)
            except ArenaError as exc:
                _call(
                    log,
                    f"Batch {slate[0].batch}: ignoring incomplete random-game "
                    f"checkpoint: {exc}",
                )
        if random is None:
            _call(
                log,
                f"Batch {slate[0].batch}: replaying {len(random_schedule)} "
                "interrupted random-anchor games",
            )
            _ensure_game_dependencies(random_schedule, roster)
            random = run_random_games(random_schedule, roster, work_dir, progress=log)
    else:
        random = []
    recs = _ordered_results(
        sorted(native + random, key=lambda game: game.number), slate
    )
    return slate, recs


def play_batch(
    schedule,
    player_values,
    work_dir,
    progress=None,
    *,
    first_prompt_path=None,
    compact_calls_path=None,
    starting_move_count=0,
    progress_tracker=None,
):
    move_total, prompt_path = starting_move_count, first_prompt_path
    bots, log, track, slate = player_values, progress, progress_tracker, schedule
    _ensure_game_dependencies(slate, bots)
    execution = {
        "first_prompt_path": prompt_path,
        "compact_calls_path": compact_calls_path,
        "starting_move_count": move_total,
        "progress_tracker": track,
    }
    work_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{work_dir.name}-", dir=work_dir.parent
    ) as staging:
        staged = Path(staging) / "batch"
        staged.mkdir()
        _write_json(staged / "schedule.json", [asdict(game) for game in slate])
        staged.rename(work_dir)
    native_games = [game for game in slate if _Arena.ANCHOR not in _game_players(game)]
    random_games = [game for game in slate if _Arena.ANCHOR in _game_players(game)]
    if not _State.katago_mode:
        _validate_llm_schedule(slate)
    if llms := [game for game in slate if _active_llm_players(_game_players(game))]:
        _check(len(llms) != len(slate))
        return run_llm_games(slate, bots, work_dir, progress=log, **execution)
    _call(
        log,
        f"Batch {slate[0].batch}: executing {len(slate)} games "
        f"({len(native_games)} network, {len(random_games)} random-anchor)",
    )
    if _State.katago_mode and _State.katago_backend == "cuda":
        native = run_native_games(native_games, bots, work_dir, progress=log)
        random = run_random_games(random_games, bots, work_dir, progress=log)
        return _ordered_results(
            sorted(native + random, key=lambda game: game.number), slate
        )
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        native_future = executor.submit(
            run_native_games, native_games, bots, work_dir, progress=log
        )
        random_future = executor.submit(
            run_random_games, random_games, bots, work_dir, progress=log
        )
        native = native_future.result()
        random = random_future.result()
    return _ordered_results(
        sorted(native + random, key=lambda game: game.number), slate
    )


def _games_by_player(games, player_names):
    """Index requested players in one pass, counting self-play only once."""
    indexed = {name: [] for name in player_names}
    if not indexed:
        return indexed
    for game in games:
        for name in _game_players(game):
            if name in indexed:
                indexed[name].append(game)
    return indexed


def rating_records(
    games,
    player_names,
    ratings,
    *,
    color_advantage=None,
    include_color_uncertainty=False,
):
    names, elos = player_names, ratings
    cov, pos = rating_covariance(
        games,
        names,
        elos,
        color_advantage=color_advantage,
        include_color=include_color_uncertainty,
    )

    player_games = _games_by_player(games, names)

    def rec(player):
        scores = [
            game.score_black if game.black == player else 1 - game.score_black
            for game in player_games[player]
        ]
        error = (
            0.0
            if player == _Arena.ANCHOR
            else math.sqrt(max(cov[pos[player]][pos[player]], 0.0))
        )
        half_width = _Arena.CONFIDENCE_Z * error
        wins, losses = scores.count(1.0), scores.count(0.0)
        return RatingRecord(
            player,
            elos[player],
            elos[player] - half_width,
            elos[player] + half_width,
            2 * half_width,
            len(scores),
            wins,
            losses,
            len(scores) - wins - losses,
        )

    return sorted(map(rec, names), key=lambda rec: (-rec.elo, rec.player))


def _llm_move_count(game):
    llms = _result_llm_players(_game_players(game))
    if not llms:
        return 0
    _check(len(llms) != 1)
    llm = next(iter(llms))
    color = "B" if game.black == llm else "W"
    return sum(move_color == color for move_color, _move in game.moves)


def _write_results(path, games):
    fields = [
        "game",
        "batch",
        "black",
        "white",
        "result",
        "winner",
        "score_black",
        "moves",
        "source",
        "llm_moves",
        "llm_illegal_moves",
        "llm_api_problems",
        "llm_api_seconds",
        "llm_cost_usd",
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(fields)
        writer.writerows(
            (
                *astuple(game)[:5],
                game.winner or "",
                f"{game.score_black:g}",
                len(game.moves),
                game.source,
                _llm_move_count(game),
                game.llm_illegal_moves,
                game.llm_api_problems,
                f"{game.llm_api_seconds:.6f}",
                f"{game.llm_cost_usd:.12f}",
            )
            for game in games
        )
    temporary.replace(path)


def _read_games(path):
    recs = [
        _batch_record_from_entry(entry)
        for entry in _read_jsonl_objects(path, "saved games")
    ]
    numbers = [rec.number for rec in recs]
    _check(
        any(not isinstance(number, int) or number < 1 for number in numbers)
        or len(numbers) != len(set(numbers))
    )
    return recs


def _write_game_records(path, games):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as out:
        for rec in games:
            entry = _game_entry(rec, numbered_moves=True)
            out.write(json.dumps(entry, separators=(",", ":")) + "\n")
    temporary.replace(path)


def _repriced_past_llm_costs(run):
    path = run / "llm_calls.jsonl"
    if not path.exists():
        return {}
    costs = defaultdict(float)
    call_counts = defaultdict(int)
    for entry in _read_jsonl_objects(path, "saved LLM calls"):
        if entry.get("ok") is not True and not entry.get("usage"):
            continue
        provider = entry.get("provider")
        request = entry.get("request")
        request = request if isinstance(request, dict) else {}
        model = entry.get("model") or request.get("model")
        if not isinstance(provider, str) or not isinstance(model, str):
            continue
        try:
            api = _llm_api_config(provider)
            player = _llm_model_config(api, model)
        except ArenaError:
            continue
        if not player.reprice_past_runs:
            continue
        try:
            game = int(entry["game"])
        except (KeyError, TypeError, ValueError):
            raise ArenaError(f"saved LLM call has invalid game number: {path}")
        usage = entry.get("usage")
        if not isinstance(usage, dict):
            usage = {
                "input_tokens": entry.get("input_tokens", 0),
                "input_tokens_details": {
                    "cached_tokens": entry.get("cached_input_tokens", 0)
                },
                # Compact ledgers store the provider-billed output total already.
                "output_tokens": entry.get("output_tokens", 0),
            }
        costs[game] += _llm_call_cost(
            usage,
            provider,
            model,
            started_at=entry.get("started_at"),
        )
        call_counts[game] += entry.get("ok") is True
    return {game: (cost, call_counts[game]) for game, cost in costs.items()}


def _with_llm_token_counts(games, run):
    """Join usage to game numbers before historical games are renumbered."""
    totals = defaultdict(lambda: [0, 0, 0])
    for entry in _read_jsonl_objects(run / "llm_calls.jsonl", "saved LLM calls"):
        if "input_tokens" not in entry:
            if not entry.get("usage"):
                continue
            entry = _compact_llm_call(entry)
        try:
            number = int(entry["game"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ArenaError(f"saved LLM call has invalid game number: {run}") from exc
        inputs = entry.get("input_tokens", 0)
        cached = entry.get("cached_input_tokens", 0)
        try:
            api = _llm_api_config(entry.get("provider"))
        except ArenaError:
            api = None
        if api is not None and not api.protocol.cached_input_is_in_input:
            inputs += cached + entry.get("cache_write_tokens", 0)
        counts = totals[number]
        counts[0] += inputs
        counts[1] += cached
        counts[2] += entry.get("output_tokens", 0)
    return [
        replace(
            game,
            llm_input_tokens=totals[game.number][0],
            llm_cached_input_tokens=totals[game.number][1],
            llm_output_tokens=totals[game.number][2],
        )
        if game.number in totals else game
        for game in games
    ]


def _load_past_games(run_dirs, eligible_players):
    eligible = set(eligible_players)
    # Scope lookups to this load so registry edits between runs remain visible.
    is_result_llm = cache(_is_result_llm_player)

    @cache
    def needs_repricing(name):
        return (
            _is_active_llm_player(name)
            and _llm_player_config(name)[1].reprice_past_runs
        )

    past: list[GameRecord] = []
    next_batch = 1
    for run in run_dirs:
        meta_path = run / "run.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        repriced_costs = None
        final_run = (
            run.name in _FINAL_RUNS and meta.get("arena_log_schema_version") == 2
        )
        _check(meta.get("arena_log_schema_version") != (2 if final_run else 4))
        expected_games = meta["completed_games"]
        _check(
            not isinstance(expected_games, int)
            or isinstance(expected_games, bool)
            or expected_games < 0
        )
        games_scope = (
            meta.get("games_scope", "current_run") if final_run else meta["games_scope"]
        )
        _check(games_scope != "current_run")
        for field, wanted in (
            ("board_size", _Arena.BOARD_SIZE),
            ("komi", _Arena.KOMI),
            ("rules", _Arena.RULES),
        ):
            _check(meta.get(field) != wanted)
        results_path = run / "results.csv"
        run_games = []
        row_count = 0
        with results_path.open(encoding="utf-8", newline="") as src:
            reader = csv.DictReader(src)
            current_fields = {
                "game",
                "batch",
                "black",
                "white",
                "result",
                "winner",
                "score_black",
                "moves",
                "source",
                "llm_moves",
                "llm_illegal_moves",
                "llm_api_problems",
                "llm_api_seconds",
                "llm_cost_usd",
            }
            _check(not final_run and not current_fields <= set(reader.fieldnames or ()))
            for row in islice(reader, expected_games):
                row_count += 1
                res = str(row["result"])
                side, score, reason = _parse_result(res)
                black, white = str(row["black"]), str(row["white"])
                if {black, white} - eligible:
                    continue
                game = int(row["game"]), int(row["batch"]), black, white
                repriced_players = {
                    name
                    for name in (black, white)
                    if needs_repricing(name)
                }
                _check(len(repriced_players) > 1)
                outcome = (
                    res,
                    side,
                    str(row.get("winner") or "") or None
                    if final_run
                    else str(row["winner"] or "") or None,
                    score,
                    reason,
                )
                stored_cost = float(row.get("llm_cost_usd") or 0.0)
                if repriced_players:
                    if repriced_costs is None:
                        repriced_costs = _repriced_past_llm_costs(run)
                    _check(game[0] not in repriced_costs)
                    stored_cost, successful_calls = repriced_costs[game[0]]
                    minimum_calls = (
                        int(row.get("llm_moves") or 0)
                        + int(row.get("llm_illegal_moves") or 0)
                        + int(row.get("llm_api_problems") or 0)
                    )
                    # The ledger also bills legal moves from discarded capped
                    # attempts. Only the final attempt's moves are in results.csv,
                    # so its counters provide a lower bound on successful calls.
                    _check(successful_calls < minimum_calls)
                metrics = (
                    (
                        int(row.get("llm_illegal_moves") or 0),
                        int(row.get("llm_api_problems") or 0),
                        float(row.get("llm_api_seconds") or 0.0),
                        stored_cost,
                    )
                    if final_run
                    else (
                        int(row["llm_illegal_moves"]),
                        int(row["llm_api_problems"]),
                        float(row["llm_api_seconds"]),
                        stored_cost,
                    )
                )
                moves = (
                    tuple(
                        ("B" if index % 2 == 0 else "W", "")
                        for index in range(int(row["moves"]))
                    )
                    if is_result_llm(black) or is_result_llm(white)
                    else ()
                )
                source = (
                    str(row.get("source") or "past_run")
                    if final_run
                    else str(row["source"])
                )
                tail = moves, source, ""
                run_games.append(_game_record(game, outcome, tail, metrics))
        _check(row_count != expected_games)
        batch_map = {
            batch: next_batch + offset
            for (offset, batch) in enumerate(sorted({game.batch for game in run_games}))
        }
        next_batch += len(batch_map)
        for game in _with_llm_token_counts(run_games, run):
            past.append(
                replace(game, number=len(past) + 1, batch=batch_map[game.batch])
            )
    return past


def _load_past_average_game_moves(run_dirs):
    total_moves, game_count = 0, 0
    for run in run_dirs:
        results_path = run / "results.csv"
        metadata = json.loads((run / "run.json").read_text(encoding="utf-8"))
        with results_path.open(encoding="utf-8", newline="") as src:
            for row in _committed_csv_rows(
                csv.DictReader(src), metadata["completed_games"]
            ):
                total_moves += int(row["moves"])
                game_count += 1
    return total_moves / game_count if game_count else _Arena.BOARD_SIZE**2


def _committed_csv_rows(reader, count):
    # run.json commits a prefix only after results.csv has been replaced.
    _check(type(count) is not int or count < 0)
    rows = list(islice(reader, count))
    _check(len(rows) != count)
    return rows


def _cumulative_llm_games(prior_games, current_games):
    batch_offset = max((game.batch for game in prior_games), default=0)
    return [
        *prior_games,
        *(
            replace(
                game, number=len(prior_games) + offset, batch=batch_offset + game.batch
            )
            for (offset, game) in enumerate(current_games, start=1)
        ),
    ]


def _aligned_table(headers, rows, *, left_aligned=()):
    rows = [tuple(map(str, row)) for row in rows]
    widths = [
        max(len(header), max((len(row[index]) for row in rows), default=0))
        for index, header in enumerate(headers)
    ]
    left_aligned = set(left_aligned)

    def format_row(row):
        return "  ".join(
            (f"{value:<{width}}" if index in left_aligned else f"{value:>{width}}")
            for index, (value, width) in enumerate(zip(row, widths))
        )

    header = format_row(headers)
    return [header, "-" * len(header), *(format_row(row) for row in rows)]


def _write_ratings(
    path,
    records,
    *,
    games,
    color=None,
    color_sds=None,
    ignore_players=(),
):
    ignored = frozenset(ignore_players)
    lines = ["Elo ratings", f"Games: {games}"]
    if _Arena.ANCHOR not in ignored:
        lines.append(f"Anchor: {_Arena.ANCHOR} = 0 Elo")
    if color is not None:
        lines += [
            f"Color advantage model: {_Arena.COLOR_ADVANTAGE_MODEL}",
            "Black advantage at average-Elo nodes:",
        ]
        for index, (node, coefficient) in enumerate(
            zip(color.nodes, color.coefficients)
        ):
            interval = (
                f" (95% CI ± {_Arena.CONFIDENCE_Z * color_sds[index]:.0f})"
                if color_sds is not None
                else ""
            )
            lines.append(f"  {node:+.0f}: {coefficient:+.0f} Elo{interval}")
    rows = (
        (
            rec.player,
            f"{rec.elo:.0f}",
            f"± {(rec.ci_high - rec.ci_low) / 2:.0f}",
            f"{rec.wins}-{rec.losses}-{rec.draws}",
            rec.games,
        )
        for rec in records
        if rec.player not in ignored
    )
    lines += _aligned_table(
        ("Player", "Elo", "95% CI", "W-L-D", "Games"),
        rows,
        left_aligned=(0,),
    )
    _replace_text(path, "\n".join(lines) + "\n")


def _replace_text(path, text):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _llm_comparison_records(games, rating_records):
    llm_rows = sorted(
        (record for record in rating_records if _is_result_llm_player(record.player)),
        key=lambda rec: (-rec.elo, rec.player),
    )
    player_games = _games_by_player(games, (rec.player for rec in llm_rows))
    comparisons = []
    for rec in llm_rows:
        low_rank = 1 + sum(
            other.ci_low > rec.ci_high for other in llm_rows if other != rec
        )
        high_rank = len(llm_rows) - sum(
            other.ci_high < rec.ci_low for other in llm_rows if other != rec
        )
        rank = str(low_rank) if low_rank == high_rank else f"{low_rank}-{high_rank}"
        llms = player_games[rec.player]
        secs = sum(game.llm_api_seconds for game in llms)
        cost = sum(game.llm_cost_usd for game in llms)
        illegal_moves = sum(game.llm_illegal_moves for game in llms)
        api_problems = sum(game.llm_api_problems for game in llms)
        total_moves_count = sum(
            color == ("B" if game.black == rec.player else "W")
            for game in llms
            for color, _move in game.moves
        )
        usage_known = bool(llms) and all(
            game.llm_input_tokens is not None for game in llms
        )
        inputs = sum(game.llm_input_tokens or 0 for game in llms)
        cached = sum(game.llm_cached_input_tokens or 0 for game in llms)
        outputs = sum(game.llm_output_tokens or 0 for game in llms)
        comparisons.append(
            {
                "rank": rank,
                "player": rec.player,
                "elo": rec.elo,
                "elo_ci_95": (rec.ci_high - rec.ci_low) / 2,
                "games": rec.games,
                "moves": total_moves_count,
                "cached_input_rate": cached / inputs if usage_known and inputs else None,
                "output_tokens_per_move": (
                    outputs / total_moves_count
                    if usage_known and total_moves_count else None
                ),
                "illegal_moves": illegal_moves,
                "api_problems": api_problems,
                "api_seconds": secs,
                "api_seconds_per_move": (
                    secs / total_moves_count if total_moves_count else 0.0
                ),
                "cost_usd": cost,
                "cost_usd_per_move": (
                    cost / total_moves_count if total_moves_count else 0.0
                ),
            }
        )
    return comparisons


def _write_llm_comparisons(
    path,
    games,
    rating_records,
    *,
    title="LLM comparisons",
    include_players=None,
    ignore_players=(),
):
    ignored = frozenset(ignore_players)
    included = None if include_players is None else frozenset(include_players)
    comparisons = _llm_comparison_records(
        games,
        (
            record
            for record in rating_records
            if record.player not in ignored
            and (included is None or record.player in included)
        ),
    )
    rows = [
        (
            item["rank"],
            item["player"],
            f"{item['elo']:.0f}",
            f"± {item['elo_ci_95']:.0f}",
            item["games"],
            item["moves"],
            f"{item['illegal_moves']}/{item['moves']}",
            f"{item['api_problems']}/{item['moves']}",
            (f"{item['cached_input_rate']:.2%}"
             if item["cached_input_rate"] is not None else "N/A"),
            (f"{item['output_tokens_per_move']:.2f}"
             if item["output_tokens_per_move"] is not None else "N/A"),
            f"{item['api_seconds_per_move']:.2f}s",
            f"${item['cost_usd']:.12f}",
            f"${item['cost_usd_per_move']:.18f}",
        )
        for item in comparisons
    ]
    lines = [title]
    lines += _aligned_table(
        (
            "Rank",
            "LLM",
            "Elo",
            "95% CI",
            "Games",
            "Moves",
            "Illegal move rate",
            "API problem rate",
            "Cached input rate",
            "Output tokens per move",
            "API time per move",
            "Total cost",
            "Cost per move",
        ),
        rows,
        left_aligned=(1,),
    )
    _replace_text(path, "\n".join(lines) + "\n")


def _arena_report_sections(
    *,
    has_llm_comparisons,
    ratings_path,
    api_comparisons_path,
    all_comparisons_path,
    matchup_path,
    all_llm_matchup_path,
):
    sections = [("Elo ratings", ratings_path)]
    if has_llm_comparisons:
        sections += [
            ("API-only LLM comparisons", api_comparisons_path),
            ("All LLM comparisons", all_comparisons_path),
        ]
    if not _State.katago_mode:
        sections += [
            ("Active-player matchup results", matchup_path),
            ("All LLM matchup results", all_llm_matchup_path),
        ]
    return sections


def _write_report(path, sections):
    lines = [
        "# Arena report",
        "",
        (
            "Canonical machine-readable data: run.json, results.csv, and the "
            "optional LLM-only llm_games.jsonl and llm_calls.jsonl files."
        ),
    ]
    for title, section_path in sections:
        if not section_path.is_file():
            continue
        text = section_path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        first, separator, rest = text.partition("\n")
        body = rest if separator and first.strip().lower() == title.lower() else text
        lines.extend(("", f"## {title}", "", body))
    _replace_text(path, "\n".join(lines) + "\n")


def _write_matchup_results(path, games, rating_records, *, ignore_players=()):
    ignored = frozenset(ignore_players)
    rating_map = {rec.player: rec for rec in rating_records}
    results = defaultdict(lambda: [0, 0, 0])
    for game in games:
        active, opp, active_black = _active_matchup(game)
        if active in ignored or opp in ignored:
            continue
        score = game.score_black if active_black else 1 - game.score_black
        results[active, opp][0 if score == 1 else 1 if score == 0 else 2] += 1
    lines = ["Active-player matchup results"]
    for active in _State.config.active_players:
        if active in ignored:
            continue
        if len(lines) > 1:
            lines.append("")
        lines.append(f"Active player: {active}")
        rows = []
        opponents = (opp for player, opp in results if player == active)
        for opp in sorted(opponents, key=lambda name: (-rating_map[name].elo, name)):
            rating = rating_map[opp]
            wins, losses, draws = results[active, opp]
            rows.append(
                (opp, f"{rating.elo:.0f}",
                 f"± {(rating.ci_high - rating.ci_low) / 2:.0f}",
                 f"{wins}-{losses}-{draws}")
            )
        lines += _aligned_table(
            ("Opponent", "Opp Elo", "95% CI", "W-L-D"), rows, left_aligned=(0,),
        )
    _replace_text(path, "\n".join(lines) + "\n")


def _write_all_llm_matchup_results(path, games, rating_records, *, ignore_players=()):
    ignored = frozenset(ignore_players)
    rating_map = {rec.player: rec for rec in rating_records}
    is_result_llm = cache(_is_result_llm_player)
    results = defaultdict(lambda: [0, 0, 0])
    for game in games:
        for llm in _game_players(game):
            if not is_result_llm(llm):
                continue
            opponent = game.white if game.black == llm else game.black
            if llm in ignored or opponent in ignored:
                continue
            score = game.score_black if game.black == llm else 1 - game.score_black
            results[llm, opponent][0 if score == 1 else 1 if score == 0 else 2] += 1

    lines = ["All LLM matchup results"]
    llms = {llm for llm, _opponent in results}
    if not llms:
        lines.append("No LLM matchup results.")
    for llm in sorted(llms, key=lambda name: (-rating_map[name].elo, name)):
        if len(lines) > 1:
            lines.append("")
        rows = []
        opponents = (opponent for player, opponent in results if player == llm)
        for opponent in sorted(
            opponents, key=lambda name: (-rating_map[name].elo, name)
        ):
            rating = rating_map[opponent]
            wins, losses, draws = results[llm, opponent]
            rows.append(
                (
                    opponent,
                    f"{rating.elo:.0f}",
                    f"± {(rating.ci_high - rating.ci_low) / 2:.0f}",
                    f"{wins}-{losses}-{draws}",
                )
            )
        lines.append(f"LLM: {llm}")
        lines += _aligned_table(
            ("Opponent", "Opp Elo", "95% CI", "W-L-D"),
            rows,
            left_aligned=(0,),
        )
    _replace_text(path, "\n".join(lines) + "\n")


def _progress_logger(path):
    lock = threading.Lock()

    def report(message):
        timestamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        line = f"{timestamp} {message}"
        with lock:
            print(line, flush=True)
            with path.open("a", encoding="utf-8") as out:
                out.write(line + "\n")

    return report


class ArenaProgressTracker:
    def __init__(self, path, *, total_games, finished_games, estimated_game_moves):
        self.path, self.total_games = path, total_games
        self.estimated_game_moves = max(estimated_game_moves, 1.0)
        self.finished_games, self._running = finished_games, {}
        self._finished_in_process, self._lock = set(), threading.RLock()
        self._move_seconds, self._observed_moves, self._game_moves = 0.0, 0, []
        self._refresh()

    def _refresh(self):
        with self._lock:
            now = time.monotonic()
            move_time = self._move_seconds / max(self._observed_moves, 1) or 5.0
            avg_moves = (
                sum(self._game_moves) / len(self._game_moves)
                if self._game_moves
                else self.estimated_game_moves
            )
            lines = [
                "Arena progress",
                f"Finished: {self.finished_games}/{self.total_games}",
                f"Running: {len(self._running)}",
                f"Updated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
            ]
            running = map(self._running.__getitem__, sorted(self._running))
            for slot, game_started, move_num, move_start, color, bot in running:
                remaining = (
                    max(move_time - (now - move_start), 0)
                    + max(avg_moves - move_num, 0) * move_time
                )
                lines.append(
                    f"Game {slot.number} (batch {slot.batch}): "
                    f"{slot.black} vs {slot.white}; move {move_num}, "
                    f"{bot} ({color}); spent {now - game_started:.0f}s, "
                    f"estimated remaining {remaining:.0f}s"
                )
            _replace_text(self.path, "\n".join(lines) + "\n")

    def start_game(self, slot):
        with self._lock:
            now = time.monotonic()
            self._running[slot.number] = [slot, now, 1, now, "B", slot.black]
            self._refresh()

    def start_move(self, slot, move_number, color, player):
        with self._lock:
            if slot.number in self._running:
                self._running[slot.number][2:] = (
                    move_number,
                    time.monotonic(),
                    color,
                    player,
                )
                self._refresh()

    def finish_move(self, game_number, move_seconds):
        with self._lock:
            if game_number in self._running:
                self._move_seconds += max(move_seconds, 0)
                self._observed_moves += 1
                self._refresh()

    def finish_game(self, game_num, move_count):
        with self._lock:
            self._running.pop(game_num, None)
            if game_num not in self._finished_in_process:
                self._finished_in_process.add(game_num)
                self.finished_games += 1
                self._game_moves.append(move_count)
            self._refresh()

    def set_finished_games(self, count):
        with self._lock:
            self.finished_games = count
            self._refresh()

    def close(self):
        self._refresh()


@dataclass(frozen=True)
class _RatingSnapshot:
    ratings: dict[str, float]
    color: ColorAdvantageModel
    color_sds: list[float]
    records: list[RatingRecord]
    curve: list[dict[str, object]]


def _rating_snapshot(games, player_names, ratings, color):
    names, elos = player_names, ratings
    elos, color = fit_ratings_and_color_advantage(games, names, elos, color)
    cov, pos = rating_covariance(
        games, names, elos, color_advantage=color, include_color=True
    )
    start = len(pos)
    color_sds = [
        math.sqrt(max(cov[start + index][start + index], 0.0))
        for index in range(color.parameter_count)
    ]
    lower, upper = color.nodes[0], color.nodes[-1]
    grid = sorted({*np.linspace(lower, upper, 401), *color.nodes})
    color_cov = np.asarray(cov)[start:, start:]
    curve = []
    for average_elo in grid:
        features = np.asarray(color.features_at_average(float(average_elo)))
        estimate = color.advantage_at_average(float(average_elo))
        variance = max(float(features @ color_cov @ features), 0.0)
        half_width = _Arena.CONFIDENCE_Z * math.sqrt(variance)
        curve.append(
            {
                "average_elo": float(average_elo),
                "black_advantage_elo": estimate,
                "black_advantage_95_ci": [
                    estimate - half_width,
                    estimate + half_width,
                ],
            }
        )
    recs = rating_records(
        games, names, elos, color_advantage=color, include_color_uncertainty=True
    )
    return _RatingSnapshot(elos, color, color_sds, recs, curve)


def _write_json(path, value):
    if _is_tracked_log_path(path):
        value = _sanitize_tracked_log_value(value)
    _replace_text(path, json.dumps(value, indent=2) + "\n")


def _named_llm_directory(active_players):
    if len(active_players) != 1 or not _is_active_llm_player(active_players[0]):
        return None
    name = active_players[0]
    if Path(name).name != name or name in {".", ".."}:
        raise ArenaError(f"invalid LLM directory name: {name}")
    return _Arena.LOG_ROOT / name


def _check_named_run_reuse(run):
    if run.exists() and run.name not in _FINAL_RUNS:
        raise ArenaError(
            f"LLM directory already exists: {run}. Add {run.name!r} to "
            "_FINAL_RUNS before reusing it; existing results were not modified."
        )


def _validate_named_extension(meta, run_config):
    mutable = {
        "total_games",
        "games_per_active_player",
        "planned_current_games",
        "past_run_dirs",
        "past_games",
        "past_games_by_active_player",
        "statistical_players",
        "ignore_players",
        "llm_pricing_usd_per_1m_tokens",
        "report_file",
        "matchup_results_file",
    }
    def comparable(key, value):
        if key == "bots" and isinstance(value, list):
            # Authentication is a transport choice, not a new model/player.
            return [
                {key: value for key, value in bot.items()
                 if key not in {"auth_mode", "cost_basis", "oauth_system_prompt"}}
                if bot.get("kind") == "anthropic_messages_api" else bot
                for bot in value
            ]
        return value

    changed = [
        key
        for key, value in run_config.items()
        if key not in mutable and comparable(key, meta.get(key)) != comparable(key, value)
    ]
    if changed:
        raise ArenaError(
            "cannot extend LLM run with different game/player settings: "
            + ", ".join(changed)
        )


def _create_run(run_config, past_dirs, extra, named):
    """Create both output directories and the initial metadata commit."""
    _Arena.LOG_ROOT.mkdir(parents=True, exist_ok=True)
    _ensure_untracked_log_root()
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    run = named or _Arena.LOG_ROOT / f"arena_katago_{timestamp}_{uuid.uuid4().hex[:8]}"
    temp_dir = (_Arena.UNTRACKED_LOG_ROOT / run.name).resolve()
    if temp_dir.exists():
        raise ArenaError(f"untracked run directory already exists: {temp_dir}")
    run.mkdir()
    _check(run.resolve() in past_dirs)
    temp_dir.mkdir()
    meta = {
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "batch_sizes": [],
        "completed_games": 0,
        **run_config,
        **extra,
        "untracked_log_dir": os.path.relpath(
            os.path.abspath(_Arena.UNTRACKED_LOG_ROOT / run.name), _Arena.ROOT
        ),
    }
    if named is not None:
        meta["run_directory_scheme"] = "llm_name"
    _write_json(run / "run.json", meta)
    return run, temp_dir, meta


def _recover_committed_batches(meta, temp_dir, valid_size, *, saved_games=None):
    """Read the committed prefix; any staged suffix is recovered from its batch."""
    games_path = temp_dir / "games.jsonl"
    if saved_games is None:
        saved_games = _read_games(games_path) if games_path.exists() else []
    committed_games = meta["completed_games"]
    _check(
        not isinstance(committed_games, int)
        or committed_games < 0
        or len(saved_games) < committed_games
    )
    # games.jsonl is atomically replaced before run.json at commit time. If
    # the process stops between those writes, its suffix is a staged batch;
    # recover that batch from its work directory instead of rejecting the run.
    done = saved_games[:committed_games]
    batch_sizes = meta["batch_sizes"]
    independent_batches = meta["independent_player_batches"]
    completed_batch_ids = meta["completed_batch_ids"] if independent_batches else []
    _check(
        not isinstance(batch_sizes, list)
        or not all(isinstance(size, int) and valid_size(size) for size in batch_sizes)
        or sum(batch_sizes) != len(done)
        or independent_batches
        and (
            not isinstance(completed_batch_ids, list)
            or len(completed_batch_ids) != len(batch_sizes)
            or any(
                not isinstance(value, int) or value < 1 for value in completed_batch_ids
            )
            or len(completed_batch_ids) != len(set(completed_batch_ids))
        )
    )
    batch = (
        max(completed_batch_ids, default=0) if independent_batches else len(batch_sizes)
    )
    return done, batch


def _restore_archived_api_games(run, meta, temp_dir, valid_size):
    """Rebuild completed API-game journals after disposable logs were removed."""
    active = meta.get("active_players", [])
    if not meta.get("finished_at"):
        raise ArenaError(
            f"missing recovery journal in {temp_dir}; this run was interrupted. "
            "Restore its original untracked_log directory to retain unfinished "
            "games and conversations."
        )
    if not active or any(
        not _is_active_llm_player(name)
        or _llm_player_config(name)[1].agentic_harness not in {"api", "api-multi"}
        for name in active
    ):
        raise ArenaError(
            f"missing recovery journal in {temp_dir}; automatic reconstruction "
            "is supported only for completed API runs. Restore the original "
            "untracked_log directory, including any workspace checkpoint."
        )
    try:
        saved = _read_games(run / "llm_games.jsonl")
        if len(saved) != meta["completed_games"]:
            raise ValueError("complete game records do not match completed_games")
        with (run / "results.csv").open(encoding="utf-8", newline="") as stream:
            results = list(csv.DictReader(stream))
        if len(results) != len(saved):
            raise ValueError("results.csv and complete game records disagree")
        for record, row in zip(saved, results):
            if (
                (record.number, record.batch, record.black, record.white,
                 record.result, len(record.moves))
                != (int(row["game"]), int(row["batch"]), row["black"],
                    row["white"], row["result"], int(row["moves"]))
                or len(set(active) & {record.black, record.white}) != 1
                or any(color != ("B" if index % 2 == 0 else "W") or not move
                       for index, (color, move) in enumerate(record.moves))
            ):
                raise ValueError(f"game {record.number} disagrees with its committed result")
        # Validate batch boundaries before creating or writing any recovery files.
        _recover_committed_batches(meta, temp_dir, valid_size, saved_games=saved)
    except (OSError, ValueError, KeyError, TypeError, ArenaError) as exc:
        raise ArenaError(f"cannot reconstruct completed run {run.name}: {exc}") from exc
    temp_dir.mkdir(parents=True, exist_ok=True)
    _write_game_records(temp_dir / "games.jsonl", saved)
    _progress_logger(temp_dir / "progress.log")(
        f"Restored {len(saved)} completed API games from tracked records; "
        "new games will start with fresh conversations"
    )


def _open_run(resume_dir, run_config, past_dirs, valid_size, extra):
    # Compare the same JSON data model that is persisted in run.json. In-memory
    # configuration may contain tuples, which JSON necessarily reloads as lists.
    run_config = json.loads(json.dumps(run_config))
    named = _named_llm_directory(run_config.get("active_players", []))
    extending = False
    if named is not None and (
        resume_dir is None or resume_dir.resolve() == named.resolve()
    ):
        if resume_dir is None:
            _check_named_run_reuse(named)
        if named.exists():
            resume_dir, extending = named, True
    if resume_dir is None:
        run, temp_dir, meta = _create_run(run_config, past_dirs, extra, named)
        done, batch = [], 0
    else:
        run = resume_dir.expanduser().resolve()
        _check(run in past_dirs)
        try:
            meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ArenaError(
                f"cannot read existing run metadata {run / 'run.json'}: {exc}"
            ) from exc
        _check(not isinstance(meta, dict))
        for field in ("report_file", "matchup_results_file"):
            if field in run_config:
                meta[field] = run_config[field]
        expected_legality = run_config.get("legality_enforcement_version")
        if (
            isinstance(meta, dict)
            and expected_legality is not None
            and meta.get("legality_enforcement_version") != expected_legality
        ):
            raise ArenaError(
                "cannot resume a run with different legality enforcement: "
                f"saved={meta.get('legality_enforcement_version', 'legacy GTP')}, "
                f"current={expected_legality}. Start a new run to keep "
                "the evaluation protocols separate."
            )
        if extending:
            _validate_named_extension(meta, run_config)
        _check(
            not isinstance(meta, dict)
            or meta.get("arena_log_schema_version") != 4
            or not extending
            and any(
                name not in meta or meta[name] != wanted
                for name, wanted in run_config.items()
            )
        )
        _check(not extending and "finished_at" in meta)
        temp_value = meta["untracked_log_dir"]
        _check(not isinstance(temp_value, str))
        if temp_value == "<external-path>":
            # Older metadata resolved away the repository's untracked_log link.
            temp_value = str(_Arena.UNTRACKED_LOG_ROOT / run.name)
        temp_path = Path(temp_value).expanduser()
        temp_dir = (
            _Arena.ROOT / temp_path if not temp_path.is_absolute() else temp_path
        ).resolve()
        if not (temp_dir / "games.jsonl").exists():
            if not temp_dir.is_dir() or meta.get("finished_at") or meta.get("completed_games", 0):
                _restore_archived_api_games(run, meta, temp_dir, valid_size)
        done, batch = _recover_committed_batches(meta, temp_dir, valid_size)
        if extending:
            meta.setdefault("extensions", []).append(
                {
                    "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "previous_total_games": meta.get("total_games"),
                    "previous_past_run_dirs": meta.get("past_run_dirs", []),
                    "completed_games": len(done),
                }
            )
            meta.update(run_config)
            meta.pop("finished_at", None)
            _write_json(run / "run.json", meta)
    log = _progress_logger(temp_dir / "progress.log")
    return run, temp_dir, meta, done, batch, log


def _run_player_arena(config):
    """Process entry point: each player owns its configuration and run files."""
    _configure(config)
    return run_arena()


def run_arena(resume_run_dir=None):
    if not _State.arena_player_names:
        _configure(_State.config)
    config = _State.config
    if (
        resume_run_dir is None
        and not _State.katago_mode
        and len(config.active_players) > 1
    ):
        # Check every destination before launching any paid evaluation jobs.
        for name in config.active_players:
            _check_named_run_reuse(_named_llm_directory((name,)))
        configs = [
            replace(config, active_players=(name,)) for name in config.active_players
        ]
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=len(configs), mp_context=multiprocessing.get_context("spawn")
        ) as executor:
            return tuple(executor.map(_run_player_arena, configs))
    named = _named_llm_directory(config.active_players)
    if named is None or (
        resume_run_dir is not None and resume_run_dir.resolve() != named.resolve()
    ):
        return _run_arena(resume_run_dir)
    if resume_run_dir is None:
        _check_named_run_reuse(named)
    _ensure_untracked_log_root()
    with (_Arena.UNTRACKED_LOG_ROOT / f".{named.name}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ArenaError(
                f"another process is already running {named.name}"
            ) from exc
        return _run_arena(resume_run_dir)


class _ArenaRun:
    """The state and lifecycle of one run directory.

    LLM and native KataGo scheduling share history, ratings, and reporting;
    their execution loops stay separate because their recovery rules differ.
    """

    def __init__(self, resume_run_dir):
        if not _State.arena_player_names:
            _configure(_State.config)
        self._validate_settings()
        self._load_history()
        self._prepare_matchmaking()
        self._open(resume_run_dir)

    def _validate_settings(self):
        _check(
            _State.config.total_games < 0
            or (_State.config.batch_games // 2) * 2 != _State.config.batch_games
            or not math.isfinite(_State.config.active_player_prior_elo_mean)
            or not math.isfinite(_State.config.active_player_prior_elo_sd)
            or _State.config.active_player_prior_elo_sd <= 0.0
        )
        _check(_Arena.PROGRESS_INTERVAL_SECONDS <= 0)
        if _State.katago_mode:
            _check(
                not _State.config.active_players
                or _State.config.batch_games <= 0
                or _State.config.total_games % _State.config.batch_games
                or _State.config.batch_games % 2
                or not math.isfinite(_State.config.katago_gain_top_p)
                or not 0.0 < _State.config.katago_gain_top_p <= 1.0
            )
        else:
            _check(_State.config.batch_games != 2)

    def _load_history(self):
        self.bots = players()
        self.names = [bot.name for bot in self.bots]
        self.past_dirs = [path.expanduser().resolve() for path in _State.past_run_dirs]
        _check(len(self.past_dirs) != len(set(self.past_dirs)))
        eligible = list(
            dict.fromkeys(
                (
                    *_State.katago_rating_player_names,
                    *_Arena.RESULT_LLM_PLAYERS,
                    *_State.past_player_priors,
                )
            )
        )
        self.past = _load_past_games(self.past_dirs, eligible)
        checkpoint_players = {
            name for name in _State.config.active_players
            if _is_active_llm_player(name)
            and _llm_player_config(name)[1].agentic_harness in _CODEX_WORKSPACE_HARNESSES
        }
        # A new preparation is a new experimental subject. Old results for the
        # same model/harness name must not be counted as this checkpoint's games.
        self.past = [game for game in self.past
                     if not checkpoint_players.intersection(_game_players(game))]
        history_names = (bot for game in self.past for bot in (game.black, game.white))
        self.fit_names = list(dict.fromkeys((*self.names, *history_names)))

    def _prepare_matchmaking(self):
        _check(any(name not in self.names for name in _State.config.active_players))
        if _State.katago_mode:
            _check(any(_is_active_llm_player(name) for name in self.names))
            _check(
                any(
                    _network_name_for_player(name) is None
                    for name in _State.config.active_players
                )
            )
            self.info_names, self.pool = list(_State.config.active_players), self.names
            self.llm_past, self.past_counts = [], {}
            self.game_target = _State.config.total_games
            self.policy = {
                "rule": "gain-proportional information-gain matchmaking "
                "with paired colors",
                "active_vs_active_matches": True,
                "selection": "with replacement proportional to gain within nucleus",
                "selection_top_p": _State.config.katago_gain_top_p,
                "games_per_batch": _State.config.batch_games,
                "total_games_scope": "all active KataGo players combined",
                "random_seed": _Arena.RANDOM_SEED,
            }
        else:
            old_names = _llm_matchmaking_opponents(self.names)
            self.pool = [*_State.config.active_players, *old_names]
            self.llm_past = [
                game for game in self.past if _result_llm_players(_game_players(game))
            ]
            batch_map = {
                history_batch: index
                for index, history_batch in enumerate(
                    sorted({game.batch for game in self.llm_past}), start=1
                )
            }
            self.llm_past = [
                replace(game, number=number, batch=batch_map[game.batch])
                for number, game in enumerate(self.llm_past, start=1)
            ]
            active_set = set(_State.config.active_players)
            match_history = [
                game
                for game in self.past
                if (game.black in active_set) != (game.white in active_set)
            ]
            self.past_counts = _active_player_game_counts(match_history)
            self.game_target = 2 * sum(
                max(
                    math.ceil((_State.config.total_games - self.past_counts[name]) / 2),
                    0,
                )
                for name in _State.config.active_players
            )
            self.info_names = _State.config.active_players
            self.policy = {
                "rule": "maximum-information-gain selection with paired colors",
                "games_per_player_per_batch": _State.config.batch_games,
                "selected_pairs_per_active_player": (_State.config.batch_games // 2),
                "maximum_games_per_batch": _State.config.batch_games,
                "selection": "deterministic maximum",
                "completion_barrier": "per-player",
            }

    def valid_size(self, size):
        return isinstance(size, int) and size == _State.config.batch_games

    def _run_metadata(self):
        run_config = {
            "arena_log_schema_version": 4,
            "tracked_log_privacy_schema_version": 1,
            "legality_enforcement_version": LEGALITY_ENFORCEMENT_VERSION,
            "anchor": _Arena.ANCHOR,
            "active_player_prior_elo_mean": _State.config.active_player_prior_elo_mean,
            "active_player_prior_elo_sd": _State.config.active_player_prior_elo_sd,
            "color_advantage_model": _Arena.COLOR_ADVANTAGE_MODEL,
            "color_advantage_node_spacing_elo": _Arena.COLOR_ADVANTAGE_NODE_SPACING,
            "rating_model": "regularized Bradley-Terry with a jointly fitted 1500-Elo "
            "piecewise-linear Black advantage over no-color baseline "
            "matchup average Elo",
            "confidence_level": 0.95,
            "ci_method": "Laplace covariance from regularized color-adjusted "
            "Bradley-Terry "
            "information, including all piecewise color parameters",
            "active_players": list(self.info_names),
            "opponent_players": list(_State.config.opponent_players),
            "ignore_players": list(_State.config.ignore_players),
            "board_size": _Arena.BOARD_SIZE,
            "komi": _Arena.KOMI,
            "rules": _Arena.RULES,
            "max_moves": _Arena.MAX_MOVES,
            "move_cap_policy": "Discard capped attempts without ratings and replay "
            "only their scheduled game slots at the same cap",
            "max_visits": _Arena.MAX_VISITS,
            "katago_backend": _State.katago_backend,
            "katago_binary": _portable_path(_State.katago_binary),
            "arena_players": self.names,
            "statistical_players": self.fit_names,
            "bots": [_player_manifest(bot) for bot in self.bots],
            "past_run_dirs": [str(Path("log") / path.name) for path in self.past_dirs],
            "past_games": len(self.past),
            "results_scope": "current_run",
            "games_scope": "current_run",
            "report_file": "report.txt",
            "random_bot_note": "Uniform-random games use KataGoGameEngine because "
            "katago match does not support arbitrary policy bots. They remain in the "
            "same blind batch. Move-capped attempts are discarded and replayed without "
            "scoring.",
            "total_games": _State.config.total_games,
            "planned_current_games": self.game_target,
            "batch_policy": self.policy,
            "independent_player_batches": not _State.katago_mode,
        }
        if _State.katago_mode:
            run_config.update(
                excluded_matchmaking_networks=sorted(
                    _Arena.EXCLUDED_MATCHMAKING_NETWORKS
                ),
                katago_match_game_threads=_Arena.MATCH_GAME_THREADS,
                katago_num_search_threads=_Arena.NUM_SEARCH_THREADS,
                katago_nn_max_batch_size=_Arena.NN_MAX_BATCH_SIZE,
                katago_random_game_workers=_State.random_game_workers,
            )
        if not _State.katago_mode:
            run_config.update(
                games_per_active_player=_State.config.total_games,
                past_games_by_active_player=self.past_counts,
                cumulative_results_file="cumulative_results.csv",
                cumulative_results_location="untracked_log_dir",
                matchup_results_scope="current_run",
                matchup_results_file="report.txt",
                llm_calls_file="llm_calls.jsonl",
                llm_games_file="llm_games.jsonl",
                llm_pricing_usd_per_1m_tokens=_Arena.LLM_MODEL_PRICING_USD_PER_MILLION,
            )
        codex_training = {
            name: _CODEX_TRAINING_SECONDS[_llm_player_config(name)[1].agentic_harness]
            for name in self.info_names if _is_active_llm_player(name)
            and _llm_player_config(name)[1].agentic_harness in _CODEX_WORKSPACE_HARNESSES
        }
        if codex_training:
            run_config["codex_workspace"] = _State.config.workspace.manifest()
            run_config["codex_workspace"]["training_seconds_by_player"] = codex_training
            if len(set(codex_training.values())) == 1:
                run_config["codex_workspace"]["training_seconds"] = next(iter(codex_training.values()))
            run_config["move_cap_policy"] = "workspace evaluation: forfeit at move limit"
        return run_config

    def _open(self, resume_run_dir):
        run_config = self._run_metadata()
        run_state = {"rating_games": len(self.past)}
        if _State.katago_mode:
            run_state.update(
                total_games_by_active_player={
                    name: 0 for name in _State.config.active_players
                },
            )
        else:
            run_state.update(
                total_games_by_active_player=self.past_counts,
                cumulative_llm_games=len(self.llm_past),
                completed_batch_ids=[],
            )
        self.run, self.temp_dir, self.meta, self.done, self.batch, self.log = _open_run(
            resume_run_dir, run_config, self.past_dirs, self.valid_size, run_state
        )
        self.initial_done_count = len(self.done)
        self.elos = {name: _rating_prior(name)[0] for name in self.fit_names}
        self.color = None
        self.track = None
        if not _State.katago_mode:
            self.track = ArenaProgressTracker(
                self.temp_dir / "progress.txt",
                total_games=self.game_target,
                finished_games=len(self.done),
                estimated_game_moves=_load_past_average_game_moves(self.past_dirs),
            )

    def totals(self, games):
        if _State.katago_mode:
            return _active_player_game_counts(games)
        current = _active_player_game_counts(games)
        return {
            name: self.past_counts[name] + current[name]
            for name in _State.config.active_players
        }

    def unfinished_active_players(self, games):
        if _State.katago_mode:
            return (
                list(_State.config.active_players)
                if len(games) < _State.config.total_games
                else []
            )
        counts = self.totals(games)
        return [
            name
            for name in _State.config.active_players
            if counts[name] < _State.config.total_games
        ]

    def write_reports(self):
        self.done = _with_llm_token_counts(self.done, self.run)
        self.meta["report_file"] = "report.txt"
        if not _State.katago_mode:
            self.meta["matchup_results_file"] = "report.txt"
        fit = [*self.past, *self.done]
        snap = _rating_snapshot(fit, self.fit_names, self.elos, self.color)
        self.elos, self.color = snap.ratings, snap.color
        self.meta["color_advantage_curve"] = snap.curve
        self.meta["ratings"] = [asdict(record) for record in snap.records]
        self.meta["llm_comparisons"] = _llm_comparison_records(fit, snap.records)
        _write_results(self.run / "results.csv", self.done)
        _write_game_records(self.temp_dir / "games.jsonl", self.done)
        llm_games = [
            game for game in self.done if _active_llm_players(_game_players(game))
        ]
        if llm_games:
            _write_game_records(self.run / "llm_games.jsonl", llm_games)
        ratings_path = self.temp_dir / "ratings.txt"
        api_comparisons_path = self.temp_dir / "api_llm_comparisons.txt"
        all_comparisons_path = self.temp_dir / "all_llm_comparisons.txt"
        matchup_path = self.temp_dir / "matchup_results.txt"
        all_llm_matchup_path = self.temp_dir / "all_llm_matchup_results.txt"
        _write_ratings(
            ratings_path,
            snap.records,
            games=len(fit),
            color=snap.color,
            color_sds=snap.color_sds,
            ignore_players=_State.config.ignore_players,
        )
        _write_llm_comparisons(
            api_comparisons_path,
            fit,
            snap.records,
            title="API-only LLM comparisons",
            include_players={
                record.player
                for record in snap.records
                if _is_result_api_llm_player(record.player)
            },
            ignore_players=_State.config.ignore_players,
        )
        _write_llm_comparisons(
            all_comparisons_path,
            fit,
            snap.records,
            title="All LLM comparisons",
            ignore_players=_State.config.ignore_players,
        )
        if not _State.katago_mode:
            llms = [
                game for game in self.done if _active_llm_players(_game_players(game))
            ]
            _write_results(
                self.temp_dir / "cumulative_results.csv",
                _cumulative_llm_games(self.llm_past, llms),
            )
            _write_matchup_results(
                matchup_path,
                self.done,
                snap.records,
                ignore_players=_State.config.ignore_players,
            )
            _write_all_llm_matchup_results(
                all_llm_matchup_path,
                fit,
                snap.records,
                ignore_players=_State.config.ignore_players,
            )
        visible_llm_comparisons = any(
            _is_result_llm_player(record.player)
            and record.player not in _State.config.ignore_players
            for record in snap.records
        )
        sections = _arena_report_sections(
            has_llm_comparisons=visible_llm_comparisons,
            ratings_path=ratings_path,
            api_comparisons_path=api_comparisons_path,
            all_comparisons_path=all_comparisons_path,
            matchup_path=matchup_path,
            all_llm_matchup_path=all_llm_matchup_path,
        )
        _write_report(self.run / "report.txt", sections)
        (self.run / "report.md").unlink(missing_ok=True)
        return snap

    def latest_gains(self):
        fit = [*self.past, *self.done]
        self.elos, self.color = fit_ratings_and_color_advantage(
            fit, self.fit_names, self.elos, self.color
        )
        cov, pos = rating_covariance(
            fit,
            self.fit_names,
            self.elos,
            color_advantage=self.color,
            include_color=True,
        )
        return information_gain_matrix(
            self.pool,
            self.elos,
            cov,
            pos,
            color_advantage=self.color,
            active_players=self.info_names,
        )

    def _pending_llm_batches(self):
        self.completed_batch_ids = set(self.meta["completed_batch_ids"])
        pending_jobs = []
        pending_players = set()
        self.next_game_number = max((game.number for game in self.done), default=0) + 1
        batch_dirs = []
        for path in self.temp_dir.iterdir():
            match = re.fullmatch(r"batch-([0-9]+)", path.name)
            if path.is_dir() and match:
                batch_dirs.append((int(match.group(1)), path))
        for saved_batch, work in sorted(batch_dirs):
            if saved_batch in self.completed_batch_ids:
                continue
            if _quarantine_incomplete_batch(work):
                continue
            self.batch = max(self.batch, saved_batch)
            saved_slate = _load_saved_schedule(work)
            _check(any(game.batch != saved_batch for game in saved_slate))
            self.next_game_number = max(
                self.next_game_number, max(game.number for game in saved_slate) + 1
            )
            player = _validate_llm_schedule(saved_slate)
            _check(player in pending_players)
            pending_players.add(player)
            pending_jobs.append(((player,), saved_slate, work))

        self.execution_base = {
            "first_prompt_path": self.run / "prompt.txt",
            "compact_calls_path": self.run / "llm_calls.jsonl",
            "progress_tracker": self.track,
        }
        self.futures = {}
        return pending_jobs, pending_players

    def execution_options(self):
        return self.execution_base | {
            "starting_move_count": sum(len(game.moves) for game in self.done)
        }

    def submit_new(self, executor, bot):
        gains = self.latest_gains()
        self.batch += 1
        work = self.temp_dir / f"batch-{self.batch:03d}"
        slate = schedule_batch(
            self.done,
            self.pool,
            gains,
            first_game_number=self.next_game_number,
            batch_number=self.batch,
            progress=self.log,
            active_players=_State.config.active_players,
            scheduled_active_players=[bot],
        )
        self.next_game_number += len(slate)
        self.log(
            f"Batch {self.batch}: {bot} scheduled for {len(slate)} games "
            "without waiting for other active players"
        )
        future = executor.submit(
            play_batch, slate, self.bots, work, self.log, **self.execution_options()
        )
        self.futures[future] = ((bot,), slate, work, False)

    def submit_recovery(self, executor, players_in_job, slate, work):
        self.log(
            f"Recovering uncommitted Batch {slate[0].batch} for "
            f"{', '.join(players_in_job)}"
        )
        future = executor.submit(
            recover_batch, work, self.bots, self.log, **self.execution_options()
        )
        self.futures[future] = (players_in_job, slate, work, True)

    def _commit_llm_batch(self, players_in_job, slate, recs):
        moves = self._record_batch(slate, recs)
        self.completed_batch_ids.add(slate[0].batch)
        self.meta["completed_batch_ids"] = sorted(self.completed_batch_ids)
        all_games = [*self.past, *self.done]
        llms = [game for game in self.done if _active_llm_players(_game_players(game))]
        self.meta.update(
            cumulative_llm_games=len(self.llm_past) + len(llms),
            cumulative_llm_cost_usd=sum(rec.llm_cost_usd for rec in all_games),
            llm_illegal_moves=sum(rec.llm_illegal_moves for rec in self.done),
            llm_api_problems=sum(rec.llm_api_problems for rec in self.done),
            llm_api_seconds=sum(rec.llm_api_seconds for rec in self.done),
            llm_cost_usd=sum(rec.llm_cost_usd for rec in self.done),
        )
        self.track.set_finished_games(len(self.done))
        self._save_reports()
        self.log(
            f"Batch {slate[0].batch} committed; {moves} moves finished; "
            f"updated ratings available to {', '.join(players_in_job)}"
        )

    def _record_batch(self, slate, records):
        self.done.extend(records)
        moves = sum(len(game.moves) for game in self.done)
        self.meta["batch_sizes"].append(len(slate))
        self.meta.update(
            completed_games=len(self.done),
            completed_moves=moves,
            rating_games=len(self.past) + len(self.done),
            total_games_by_active_player=self.totals(self.done),
        )
        return moves

    def _save_reports(self):
        # A metadata commit must never get ahead of its game records.
        preparation_root = self.temp_dir / "codex-checkpoints"
        if preparation_root.is_dir():
            self.meta["codex_checkpoints"] = {
                path.parents[1].name: _workspace_read_json(path)
                for path in preparation_root.glob("*/checkpoint/manifest.json")
            }
            self.meta["codex_evaluations"] = [
                _workspace_read_json(path) for path in sorted(self.temp_dir.glob(
                    "batch-*/agent-workspaces/game-*/evaluation-summary.json"
                ))
            ]
        self.write_reports()
        _write_json(self.run / "run.json", self.meta)

    def _run_llm_batches(self, todo):
        pending_jobs, pending_players = self._pending_llm_batches()
        workers = max(len(_State.config.active_players), 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            for players_in_job, slate, work in pending_jobs:
                self.submit_recovery(executor, players_in_job, slate, work)
            for bot in todo:
                if bot not in pending_players:
                    self.submit_new(executor, bot)

            while self.futures:
                finished, _pending = concurrent.futures.wait(
                    self.futures, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in finished:
                    players_in_job, slate, _work, recovering = self.futures.pop(future)
                    result = future.result()
                    if recovering:
                        recovered_slate, recs = result
                        _check(recovered_slate != slate)
                    else:
                        recs = result
                    self._commit_llm_batch(players_in_job, slate, recs)
                    counts = self.totals(self.done)
                    for bot in players_in_job:
                        if counts[bot] < _State.config.total_games:
                            self.submit_new(executor, bot)

    def _run_katago_batches(self, todo):
        while todo and _State.katago_mode:
            self.batch += 1
            first = len(self.done)
            work = self.temp_dir / f"batch-{self.batch:03d}"
            gains = self.latest_gains()
            wanted_batch_games = min(
                _State.config.batch_games,
                _State.config.total_games - first,
            )
            _quarantine_incomplete_batch(work)
            if work.exists():
                self.log(f"Recovering uncommitted Batch {self.batch}")
                slate, recs = recover_batch(work, self.bots, self.log)
                _check(slate[0].batch != self.batch)
                numbers = range(first + 1, first + len(slate) + 1)
                _check([game.number for game in slate] != list(numbers))
                _check(len(slate) != wanted_batch_games)
                _validate_color_swapped_schedule(slate, len(slate) // 2)
                for game in slate:
                    _check(not _active_players_in_game(game))
            else:
                self.log(f"Scheduling batch {self.batch} from game {first + 1}")
                options = {
                    "pair_count": wanted_batch_games // 2,
                    "active_players": _State.config.active_players,
                    "selection": "gain_proportional",
                    "allow_active_player_pairs": True,
                    "top_p": _State.config.katago_gain_top_p,
                }
                slate = schedule_batch(
                    self.done,
                    self.pool,
                    gains,
                    batch_number=self.batch,
                    progress=self.log,
                    **options,
                )
                self.log(f"Batch {self.batch}: {len(slate)} games")
                recs = play_batch(slate, self.bots, work, self.log)
            moves = self._record_batch(slate, recs)
            self._save_reports()
            self.log(f"Batch {self.batch} committed; {moves} moves finished")
            todo = self.unfinished_active_players(self.done)

    def _finish(self):
        if not self.done or (
            not _State.katago_mode and len(self.done) == self.initial_done_count
        ):
            self.write_reports()
            if not _State.katago_mode:
                self.meta.update(
                    rating_games=len(self.past) + len(self.done),
                    total_games_by_active_player=self.totals(self.done),
                    cumulative_llm_cost_usd=sum(
                        game.llm_cost_usd for game in [*self.past, *self.done]
                    ),
                )
            if not self.done:
                self.log(
                    f"Aggregate reports written from {len(self.past)} historical games"
                )
        self.meta.update(
            finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            elapsed_seconds=time.perf_counter() - self.started,
        )
        _write_json(self.run / "run.json", self.meta)
        self.log(f"Arena finished in {self.meta['elapsed_seconds']:.1f}s")
        return self.run

    def execute(self):
        self.started = time.perf_counter()
        todo = self.unfinished_active_players(self.done)
        try:
            if _State.katago_mode:
                self._run_katago_batches(todo)
            elif todo:
                self._run_llm_batches(todo)
            return self._finish()
        finally:
            _call(self.track and self.track.close)


def _run_arena(resume_run_dir=None):
    return _ArenaRun(resume_run_dir).execute()


def run_summary(config):
    """Fit and report historical games without opening an executable arena run."""
    from gobench.arena_summary import build_results, history_snapshot

    started = time.perf_counter()
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    # No active LLM: configuration must not exclude its own historical records.
    _configure_history(replace(
        config,
        active_players=(),
        opponent_players=(),
        total_games=0,
        past_run_names=tuple(dict.fromkeys(
            name for name in config.past_run_names if name != "summary"
        )),
    ))
    past_dirs = list(_State.past_run_dirs)
    eligible = set(_State.katago_rating_player_names) | set(_Arena.RESULT_LLM_PLAYERS)
    eligible.update(_State.past_player_priors)
    if not past_dirs:
        raise ArenaError("no committed historical games available for --summary")
    try:
        with history_snapshot(past_dirs, _Arena.ROOT, _Arena.LOG_ROOT) as (
            snapshot_root, snapshot_log, snapshot_dirs,
        ):
            games = _load_past_games(snapshot_dirs, eligible)
            if not games:
                raise ArenaError("no committed historical games available for --summary")
            names = list(dict.fromkeys(name for game in games for name in (game.black, game.white)))
            snap = _rating_snapshot(games, names, {name: _rating_prior(name)[0] for name in names}, None)
            comparisons = _llm_comparison_records(games, snap.records)
            results = build_results(
                root=snapshot_root, log_root=snapshot_log, past_dirs=snapshot_dirs,
                ratings=[asdict(record) for record in snap.records],
                comparisons=comparisons, rating_games=len(games),
                color_advantage_curve=snap.curve,
                settings={"board_size": _Arena.BOARD_SIZE, "komi": _Arena.KOMI,
                          "rules": _Arena.RULES, "max_moves": _Arena.MAX_MOVES},
            )
    except (OSError, ValueError, KeyError) as exc:
        raise ArenaError(f"cannot build summary results: {exc}") from exc
    run = _Arena.LOG_ROOT / "summary"
    _Arena.LOG_ROOT.mkdir(parents=True, exist_ok=True)
    with (_Arena.LOG_ROOT / ".summary.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ArenaError("another process is already writing summary") from exc
        run.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="arena-summary-") as temporary:
            staging = Path(temporary)
            _write_ratings(
                staging / "ratings.txt", snap.records, games=len(games),
                color=snap.color, color_sds=snap.color_sds,
                ignore_players=config.ignore_players,
            )
            sections = [staging / "ratings.txt"]
            for filename, title, include in (
                ("api_llm_comparisons.txt", "API-only LLM comparisons",
                 {r.player for r in snap.records if _is_result_api_llm_player(r.player)}),
                ("all_llm_comparisons.txt", "All LLM comparisons", None),
            ):
                path = staging / filename
                _write_llm_comparisons(
                    path, games, snap.records, title=title,
                    include_players=include, ignore_players=config.ignore_players,
                )
                sections.append(path)
            matchup = staging / "all_llm_matchup_results.txt"
            _write_all_llm_matchup_results(
                matchup, games, snap.records, ignore_players=config.ignore_players,
            )
            sections.append(matchup)
            report = "\n\n".join([
                "Arena report\nMachine-readable results: results.json; run metadata: run.json.",
                *(path.read_text(encoding="utf-8").strip() for path in sections),
            ]) + "\n"
        _replace_text(run / "report.txt", report)
        _write_json(run / "results.json", results)
        _write_json(run / "run.json", {
            "arena_log_schema_version": 4,
            "tracked_log_privacy_schema_version": 1,
            "run_directory_scheme": "summary",
            "started_at": started_at,
            "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "elapsed_seconds": time.perf_counter() - started,
            "past_run_dirs": [str(Path("log") / path.name) for path in past_dirs],
            "active_players": [],
            "ignore_players": list(config.ignore_players),
            "total_games": 0,
            "planned_current_games": 0,
            "completed_games": 0,
            "past_games": len(games),
            "rating_games": len(games),
            "games_scope": "historical_summary",
            "results_scope": "historical_summary",
            "anchor": _Arena.ANCHOR,
            "confidence_level": 0.95,
            "color_advantage_model": _Arena.COLOR_ADVANTAGE_MODEL,
            "color_advantage_curve": snap.curve,
            "ratings": [asdict(record) for record in snap.records],
            "llm_comparisons": comparisons,
            "cumulative_llm_cost_usd": sum(game.llm_cost_usd for game in games),
            "report_file": "report.txt",
            "results_file": "results.json",
        })
        for obsolete in ("report.md", "results.csv", "ratings.txt",
                         "api_llm_comparisons.txt", "all_llm_comparisons.txt",
                         "all_llm_matchup_results.txt"):
            (run / obsolete).unlink(missing_ok=True)
    return run


def _run_type_names():
    return tuple(RUN_TYPES)


def _config_from_metadata(metadata):
    if not isinstance(metadata, dict) or metadata.get("arena_log_schema_version") != 4:
        raise ArenaError("run metadata must use arena_log_schema_version 4")

    def string_list(name):
        value = metadata.get(name)
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ArenaError(f"run metadata has invalid {name}")
        return tuple(value)

    def number(value, name):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ArenaError(f"run metadata has invalid {name}")
        return float(value)

    arena_players = string_list("arena_players")
    active_players = string_list("active_players")
    opponent_players = string_list("opponent_players")
    past_values = string_list("past_run_dirs")
    ignore_players = (
        string_list("ignore_players") if "ignore_players" in metadata else ()
    )
    if not set((*active_players, *opponent_players)) <= set(arena_players) or any(
        name != _Arena.ANCHOR
        and not _is_active_llm_player(name)
        and _network_name_for_player(name) not in _Arena.NETWORKS_BY_NAME
        for name in arena_players
    ):
        raise ArenaError("run metadata has invalid arena_players")
    mode = _active_players_are_katago(active_players)
    policy = metadata.get("batch_policy")
    if not isinstance(policy, dict):
        raise ArenaError("run metadata has invalid batch_policy")
    batch_key = "games_per_batch" if mode else "games_per_player_per_batch"
    batch_games = policy.get(batch_key)
    if not isinstance(batch_games, int) or isinstance(batch_games, bool):
        raise ArenaError(f"run metadata has invalid batch_policy.{batch_key}")
    saved_backend = metadata.get("katago_backend")
    if saved_backend not in {"cpu", "cuda"}:
        raise ArenaError("run metadata has invalid katago_backend")
    total_games = metadata.get("total_games")
    if not isinstance(total_games, int) or isinstance(total_games, bool):
        raise ArenaError("run metadata has invalid total_games")
    prior_mean = number(
        metadata.get("active_player_prior_elo_mean"),
        "active_player_prior_elo_mean",
    )
    prior_sd = number(
        metadata.get("active_player_prior_elo_sd"), "active_player_prior_elo_sd"
    )
    gain_top_p = (
        number(policy.get("selection_top_p"), "batch_policy.selection_top_p")
        if mode
        else 1.0
    )
    workspace = WorkspaceSettings()
    if any(_is_active_llm_player(name)
           and _llm_player_config(name)[1].agentic_harness in _CODEX_WORKSPACE_HARNESSES
           for name in active_players):
        saved_workspace = metadata.get("codex_workspace")
        if not isinstance(saved_workspace, dict) or saved_workspace.get("protocol") != WORKSPACE_PROTOCOL_VERSION:
            raise ArenaError("legacy Codex workspace runs use a different experiment protocol; start a new run")
        try:
            workspace = WorkspaceSettings(**{
                field.name: saved_workspace[field.name] for field in fields(WorkspaceSettings)
            })
        except (KeyError, WorkspaceError) as exc:
            raise ArenaError(f"invalid saved workspace configuration: {exc}") from exc
    return ArenaConfig(
        active_players=active_players,
        opponent_players=opponent_players,
        total_games=total_games,
        batch_games=batch_games,
        past_run_names=tuple(Path(path).name for path in past_values),
        ignore_players=ignore_players,
        katago_backend=saved_backend,
        active_player_prior_elo_mean=prior_mean,
        active_player_prior_elo_sd=prior_sd,
        katago_gain_top_p=gain_top_p,
        workspace=workspace,
    )


def _read_run_config(run_dir):
    path = run_dir.expanduser().resolve() / "run.json"
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArenaError(f"cannot read run metadata {path}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ArenaError(f"run metadata is not a JSON object: {path}")
    if metadata.get("run_directory_scheme") == "summary":
        raise ArenaError("summary directories cannot be resumed; use --summary to refresh")
    return metadata, _config_from_metadata(metadata)


def _resume_player_arena(config, run_dir):
    """Process entry point for a run with its own saved configuration."""
    _configure(config)
    return run_arena(run_dir)


def _resume_runs(value):
    runs = []
    configs = []
    # Validate every selection before launching any evaluation work.
    for entry in value.split(","):
        entry = entry.strip()
        if not entry:
            raise ArenaError("--resume requires nonempty run names or directory paths")
        run = Path(entry).expanduser()
        if run.parent == Path(".") and not run.is_dir():
            run = _Arena.LOG_ROOT / run
        run = run.resolve()
        if run in runs:
            raise ArenaError(f"duplicate resume directory: {run}")
        _metadata, config = _read_run_config(run)
        runs.append(run)
        configs.append(config)

    if len(runs) == 1:
        run = _resume_player_arena(configs[0], runs[0])
        print(f"Arena complete: {run}")
        return 0

    failed = False
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=len(runs), mp_context=multiprocessing.get_context("spawn")
    ) as executor:
        futures = {
            executor.submit(_resume_player_arena, config, run): run
            for config, run in zip(configs, runs)
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                run = future.result()
            except Exception as exc:
                failed = True
                print(f"error: {futures[future].name}: {exc}", file=sys.stderr,
                      flush=True)
            else:
                print(f"Arena complete: {run}", flush=True)
    return int(failed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--resume", metavar="RUN[,RUN...]",
        help="resume saved run names or directory paths; multiple runs use separate processes",
    )
    selection.add_argument("--run-type", choices=_run_type_names(), metavar="TYPE")
    selection.add_argument(
        "--summary", action="store_true",
        help="write past-run reports to log/summary without playing new games",
    )
    args = parser.parse_args(argv)
    try:
        if args.resume is not None:
            return _resume_runs(args.resume)
        elif args.summary:
            run = run_summary(CONFIG)
            print(f"Summary complete: {run}")
            return 0
        elif args.run_type is not None:
            config = RUN_TYPES[args.run_type]
        else:
            config = CONFIG
        _configure(config)
        run = run_arena(args.resume)
    except (ArenaError, GoEngineError, WorkspaceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for path in run if isinstance(run, tuple) else (run,):
        print(f"Arena complete: {path}")
    return 0


@dataclass(frozen=True)
class _CodexMoveResponse:
    output_text: str
    usage: dict
    reused: bool = False


def _codex_config_text():
    feature_lines = "\n".join(
        [
            *(f"{name} = false" for name in _Arena.CODEX_WORKSPACE_DISABLED_FEATURES),
            *(f"{name} = true" for name in _Arena.CODEX_OFFLINE_TOOL_FEATURES),
        ]
    )
    lines = [
        'approval_policy = "never"',
        'sandbox_mode = "danger-full-access"',
        'web_search = "disabled"',
        "check_for_update_on_startup = false",
        "allow_login_shell = false",
        f'model_provider = "{_Arena.CODEX_WORKSPACE_PROVIDER}"',
        "",
        "[feedback]",
        "enabled = false",
        "",
        "[features]",
        feature_lines,
        "",
        f"[model_providers.{_Arena.CODEX_WORKSPACE_PROVIDER}]",
        'name = "Arena OpenAI proxy"',
        f'base_url = "http://127.0.0.1:{_Arena.CODEX_WORKSPACE_PROXY_PORT}/v1"',
        'env_key = "ARENA_PROXY_TOKEN"',
        'wire_api = "responses"',
        "requires_openai_auth = false",
        "request_max_retries = 0",
        "stream_max_retries = 0",
        "supports_standalone_web_search = false",
        "supports_websockets = false",
    ]
    return "\n".join(lines) + "\n"


def _codex_auth_source():
    home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    path = home / "auth.json"
    if not path.is_file():
        raise ArenaError(
            f"Codex login is required; expected credentials at {path}. "
            "Run `codex login` once on this VM."
        )
    return path


def _tool_identity(value):
    if not isinstance(value, dict):
        return ""
    vals = [value.get("type"), value.get("name")]
    function = value.get("function")
    if isinstance(function, dict):
        vals += [function.get("name"), function.get("type")]
    return " ".join(str(item).lower() for item in vals if isinstance(item, str))


def _forbidden_hosted_tool(value):
    identity = value.lower() if isinstance(value, str) else _tool_identity(value)
    return any(marker in identity for marker in _Arena.FORBIDDEN_HOSTED_TOOL_MARKERS)


def _remove_forbidden_hosted_tools(value):
    """Remove provider-hosted non-coding tools while retaining local coding tools."""
    if not isinstance(value, dict) or not isinstance(value.get("tools"), list):
        return value, []
    kept, removed = [], []
    for tool in value["tools"]:
        if _forbidden_hosted_tool(tool):
            removed.append(_tool_identity(tool) or "unknown")
        else:
            kept.append(tool)
    if not removed:
        return value, []
    filtered = dict(value)
    filtered["tools"] = kept
    if _forbidden_hosted_tool(filtered.get("tool_choice")):
        filtered["tool_choice"] = "auto"
    return filtered, removed


def _potential_internet_tool_flags(value, *, source, path="$"):
    flags = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            flags += _potential_internet_tool_flags(
                item, source=source, path=f"{path}[{index}]"
            )
        return flags
    if not isinstance(value, dict):
        return flags

    identity = _tool_identity(value)
    item_type = str(value.get("type", "")).lower()
    is_call = "call" in item_type or item_type in {
        "commandexecution",
        "dynamictoolcall",
        "mcp_tool_call",
        "websearch",
    }
    if is_call and any(
        marker in identity for marker in _Arena.FORBIDDEN_HOSTED_TOOL_MARKERS
    ):
        flags.append({"source": source, "path": path, "reason": f"tool:{identity}"})

    if is_call and any(name in identity for name in ("shell", "command", "exec")):
        candidates = []
        for key in ("arguments", "command", "input"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                candidates.append(candidate)
        action = value.get("action")
        if isinstance(action, dict):
            command = action.get("command")
            if isinstance(command, str):
                candidates.append(command)
            elif isinstance(command, list):
                candidates.append(" ".join(str(part) for part in command))
        for candidate in candidates:
            try:
                decoded = json.loads(candidate)
            except (json.JSONDecodeError, TypeError):
                decoded = None
            if isinstance(decoded, dict):
                candidates += [
                    item
                    for key in ("cmd", "command", "script")
                    if isinstance((item := decoded.get(key)), str)
                ]
            if _Arena.NETWORK_COMMAND_RE.search(candidate):
                flags.append(
                    {
                        "source": source,
                        "path": path,
                        "reason": "network-oriented shell command",
                        "excerpt": candidate[:500],
                    }
                )
                break

    for key, item in value.items():
        flags += _potential_internet_tool_flags(
            item, source=source, path=f"{path}.{key}"
        )
    return flags


def _decoded_proxy_body(body, content_type=""):
    text = body.decode("utf-8", errors="replace")
    if "text/event-stream" in content_type:
        events = []
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                events.append(payload)
        return {"events": events, "raw": text}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _proxy_stream_events(value):
    if isinstance(value, dict) and isinstance(value.get("events"), list):
        return value["events"]
    if not isinstance(value, str):
        return []
    events = []
    for line in value.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            events.append(payload)
    return events


def _readable_proxy_value(value, *, field=None):
    if field in {
        "encrypted_content",
        "internal_chat_message_metadata_passthrough",
        "raw",
    }:
        size = len(value) if isinstance(value, (str, list, dict)) else None
        detail = f" ({size:,} characters/items)" if size is not None else ""
        return (
            f"<opaque field omitted from readable log{detail}; "
            "retained in openai-proxy.jsonl>"
        )
    if isinstance(value, dict):
        return {
            name: _readable_proxy_value(item, field=str(name))
            for name, item in value.items()
        }
    if isinstance(value, list):
        return [_readable_proxy_value(item) for item in value]
    if isinstance(value, tuple):
        return [_readable_proxy_value(item) for item in value]
    return value


def _readable_proxy_tool(tool):
    if not isinstance(tool, dict):
        return _readable_proxy_value(tool)
    summary = {name: tool[name] for name in ("type", "name", "title") if name in tool}
    if isinstance(tool.get("tools"), list):
        summary["tools"] = [_readable_proxy_tool(item) for item in tool["tools"]]
    return summary


def _readable_proxy_request(value):
    if not isinstance(value, dict):
        return _readable_proxy_value(value)
    readable = {}
    for name, item in value.items():
        if name == "tools" and isinstance(item, list):
            readable[name] = [_readable_proxy_tool(tool) for tool in item]
            readable["tools_note"] = (
                "Tool descriptions and schemas are omitted here; see "
                "openai-proxy.jsonl for the exact definitions."
            )
            continue
        if name == "input" and isinstance(item, list):
            readable_input = []
            for input_item in item:
                if (
                    isinstance(input_item, dict)
                    and input_item.get("type") == "additional_tools"
                    and isinstance(input_item.get("tools"), list)
                ):
                    summarized = {
                        key: _readable_proxy_value(input_item[key], field=key)
                        for key in input_item
                        if key != "tools"
                    }
                    summarized["tools"] = [
                        _readable_proxy_tool(tool) for tool in input_item["tools"]
                    ]
                    summarized["tools_note"] = (
                        "Tool descriptions and schemas are omitted here; see "
                        "openai-proxy.jsonl for the exact definitions."
                    )
                    readable_input.append(summarized)
                else:
                    readable_input.append(_readable_proxy_value(input_item))
            readable[name] = readable_input
            continue
        readable[name] = _readable_proxy_value(item, field=name)
    return readable


def _readable_proxy_response(value):
    events = _proxy_stream_events(value)
    if not events:
        return _readable_proxy_value(value)

    event_counts = defaultdict(int)
    output_items = []
    final_response = None
    errors = []
    partial_text = []
    for event in events:
        if not isinstance(event, dict):
            event_counts["<unparsed>"] += 1
            continue
        event_type = str(event.get("type", "<unknown>"))
        event_counts[event_type] += 1
        if event_type == "response.output_item.done" and "item" in event:
            output_items.append(event["item"])
        if event_type == "response.output_text.delta" and isinstance(
            event.get("delta"), str
        ):
            partial_text.append(event["delta"])
        if event_type in {
            "response.completed",
            "response.failed",
            "response.incomplete",
        } and isinstance(event.get("response"), dict):
            final_response = event["response"]
        if event_type == "error" or event_type.endswith(".failed"):
            errors.append(event)

    response_summary = None
    if final_response is not None:
        response_summary = {
            name: final_response[name]
            for name in (
                "id",
                "status",
                "model",
                "error",
                "incomplete_details",
                "usage",
            )
            if name in final_response
        }
        if not output_items and isinstance(final_response.get("output"), list):
            output_items = final_response["output"]

    readable = {
        "stream_event_counts": dict(sorted(event_counts.items())),
        "response": response_summary,
        "output_items": output_items,
    }
    if errors:
        readable["errors"] = errors
    if not output_items and partial_text:
        readable["partial_output_text"] = "".join(partial_text)
    return _readable_proxy_value(readable)


def _format_readable_proxy_entry(entry):
    if entry.get("event") == "proxy_started":
        return (
            "=" * 80
            + "\nPROXY STARTED\n"
            + f"time: {entry.get('started_at', 'unknown')}\n"
            + f"authentication: {entry.get('auth_mode', 'unknown')}\n\n"
        )

    flags = entry.get("potential_internet_tool_calls")
    flags = flags if isinstance(flags, list) else []
    lines = [
        "=" * 80,
        f"EXCHANGE {entry.get('exchange_id', 'unknown')}",
        f"started: {entry.get('started_at', 'unknown')}",
        f"completed: {entry.get('completed_at', 'unknown')}",
        f"request: {entry.get('method', 'unknown')} {entry.get('path', 'unknown')}",
        f"status: {entry.get('response_status', 'unknown')} "
        f"({'ok' if entry.get('ok') else 'failed'})",
        f"authentication: {entry.get('auth_mode', 'unknown')}",
        f"potential internet tool calls: {len(flags)}",
    ]
    if entry.get("error"):
        lines.append(f"error: {entry['error']}")
    lines += [
        "",
        "INTERNET-TOOL FLAGS",
        json.dumps(_readable_proxy_value(flags), indent=2, ensure_ascii=False),
        "",
        "REQUEST BODY",
        json.dumps(
            _readable_proxy_request(entry.get("request_body")),
            indent=2,
            ensure_ascii=False,
        ),
        "",
        "RESPONSE",
        json.dumps(
            _readable_proxy_response(entry.get("response_body")),
            indent=2,
            ensure_ascii=False,
        ),
        "",
    ]
    return "\n".join(lines) + "\n"


def _append_readable_proxy_log(path, entry):
    rendered = _format_readable_proxy_entry(entry)
    with _State.jsonl_write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as out:
            out.write(rendered)


def _canonical_openai_proxy_path(path):
    match = re.match(r"^/v1/(?:codex/)?responses(?P<suffix>[/?].*)?$", path)
    if match is not None:
        return "/v1/responses" + (match.group("suffix") or "")
    match = re.match(r"^/v1/(?:codex/)?models(?P<suffix>[/?].*)?$", path)
    return "/v1/models" + (match.group("suffix") or "") if match else None


class _OpenAIProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def address_string(self):
        return "workspace"

    def log_message(self, _format, *_args):
        return

    def _request_body(self):
        transfer = self.headers.get("Transfer-Encoding", "").lower()
        if transfer == "chunked":
            chunks = []
            while True:
                line = self.rfile.readline().strip().split(b";", 1)[0]
                size = int(line, 16)
                if size == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.read(2)
            return b"".join(chunks)
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _error_response(self, status, message):
        body = json.dumps({"error": {"message": message}}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _proxy(self):
        with self.server.exchange_condition:
            self.server.active_exchanges += 1
        try:
            return self._proxy_request()
        finally:
            with self.server.exchange_condition:
                self.server.active_exchanges -= 1
                self.server.exchange_condition.notify_all()

    def _proxy_request(self):
        exchange_id = uuid.uuid4().hex
        started_at = dt.datetime.now(dt.timezone.utc).isoformat()
        raw_request = self._request_body()
        request_type = self.headers.get("Content-Type", "")
        request_body = _decoded_proxy_body(raw_request, request_type)
        filtered_body, removed_tools = _remove_forbidden_hosted_tools(request_body)
        forwarded_request = (
            json.dumps(filtered_body, separators=(",", ":")).encode("utf-8")
            if filtered_body is not request_body
            else raw_request
        )
        request_flags = _potential_internet_tool_flags(request_body, source="request")
        for tool in removed_tools:
            request_flags.append(
                {
                    "source": "request",
                    "path": "$.tools",
                    "reason": f"removed hosted tool:{tool}",
                }
            )
        entry = {
            "schema_version": 1,
            "exchange_id": exchange_id,
            "started_at": started_at,
            "auth_mode": self.server.credential.auth_mode,
            "method": self.command,
            "path": self.path,
            "request_headers": dict(self.headers.items()),
            "request_body": request_body,
            "potential_internet_tool_calls": request_flags,
        }
        canonical_path = _canonical_openai_proxy_path(self.path)
        if canonical_path is None:
            entry.update(ok=False, response_status=403, error="forbidden proxy path")
            self.server.append_log(entry)
            self._error_response(
                403, "the arena proxy permits only OpenAI Responses and model catalog"
            )
            return
        if getattr(self.server, "allowed_model", None) is not None and canonical_path.startswith("/v1/responses"):
            if not self.server.enabled:
                self._error_response(403, "agent clock is not running")
                return
            if (self.command != "POST" or not isinstance(filtered_body, dict)
                    or filtered_body.get("model") != self.server.allowed_model):
                self._error_response(403, "request must use this player's configured model")
                return

        connection = None
        tracked_socket = None
        response_body = bytearray()
        response_headers = {}
        status = None
        pending_event = b""
        usage_recorded = False

        def record_usage(value):
            nonlocal usage_recorded
            if not isinstance(value, dict) or usage_recorded:
                return
            response = value.get("response", value)
            if not isinstance(response, dict) or not isinstance(
                response.get("usage"), dict
            ):
                return
            # Commit usage before forwarding the terminal event to the client. The
            # RPC completion can otherwise race the proxy's exchange log write.
            _append_jsonl(
                self.server.log_path.with_suffix(".usage.jsonl"),
                {
                    "exchange_id": exchange_id,
                    "started_at": started_at,
                    "model": response.get("model")
                    or (
                        request_body.get("model")
                        if isinstance(request_body, dict)
                        else None
                    ),
                    "usage": response["usage"],
                },
            )
            usage_recorded = True

        try:
            # A proxy can live for hours. Pick up credentials renewed by the
            # host CLI instead of retaining its startup token for the whole game.
            credential = self.server.credential
            if credential.auth_mode == "oauth":
                try:
                    credential = _openai_oauth_proxy_credential()
                except ArenaError:
                    status = 401
                    entry.update(ok=False, response_status=status,
                                 error="host OAuth login unavailable")
                    self._error_response(status, "Host OpenAI OAuth login unavailable; run codex login")
                    return
            connection = http.client.HTTPSConnection(
                credential.host,
                timeout=30 if getattr(self.server, "allowed_model", None) is not None else None,
            )
            if getattr(self.server, "allowed_model", None) is not None and canonical_path.startswith("/v1/responses"):
                connection.connect()
                tracked_socket = connection.sock
                tracked_socket.settimeout(None)  # the agent clock bounds model thinking
                with self.server.connection_lock:
                    if not self.server.enabled:
                        raise ConnectionAbortedError("agent clock stopped before forwarding request")
                    self.server.connections.add(tracked_socket)
            headers = {
                name: value
                for name, value in self.headers.items()
                if name.lower() not in _Arena.PROXY_HOP_BY_HOP_HEADERS
                and name.lower()
                not in {
                    "authorization",
                    "accept-encoding",
                    "chatgpt-account-id",
                    "originator",
                }
            }
            headers.update(
                {
                    "Authorization": (f"Bearer {credential.bearer_token}"),
                    "Content-Length": str(len(forwarded_request)),
                    "Host": credential.host,
                    "Accept-Encoding": "identity",
                }
            )
            headers.update(dict(credential.headers))
            upstream_path = credential.upstream_path(canonical_path)
            entry["upstream_path"] = upstream_path
            connection.request(self.command, upstream_path, forwarded_request, headers)
            upstream = connection.getresponse()
            status = upstream.status
            upstream_headers = upstream.getheaders()
            response_headers = dict(upstream_headers)
            is_stream = any(
                name.lower() == "content-type" and "text/event-stream" in value
                for name, value in upstream_headers
            )
            self.send_response(upstream.status, upstream.reason)
            for name, value in upstream_headers:
                if name.lower() not in _Arena.PROXY_HOP_BY_HOP_HEADERS:
                    self.send_header(name, value)
            self.send_header("Connection", "close")
            self.end_headers()
            client_connected = True
            while chunk := upstream.read1(65536):
                response_body.extend(chunk)
                if is_stream:
                    pending_event += chunk
                    lines = pending_event.split(b"\n")
                    pending_event = lines.pop()
                    for line in lines:
                        if line.startswith(b"data:"):
                            try:
                                record_usage(json.loads(line[5:]))
                            except (ValueError, UnicodeDecodeError):
                                pass
                elif not usage_recorded:
                    try:
                        record_usage(json.loads(response_body))
                    except (ValueError, UnicodeDecodeError):
                        pass
                if client_connected:
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        client_connected = False
            self.close_connection = True
            content_type = next(
                (
                    value
                    for name, value in upstream_headers
                    if name.lower() == "content-type"
                ),
                "",
            )
            decoded_response = _decoded_proxy_body(response_body, content_type)
            stream_events = _proxy_stream_events(decoded_response)
            response_flags = _potential_internet_tool_flags(
                stream_events or decoded_response, source="response"
            )
            entry["potential_internet_tool_calls"] += response_flags
            entry.update(
                ok=200 <= upstream.status < 400,
                response_status=upstream.status,
                response_headers=response_headers,
                response_body=decoded_response,
            )
        except Exception as exc:
            entry.update(
                ok=False,
                response_status=status,
                response_headers=response_headers,
                response_body=_decoded_proxy_body(response_body),
                error=f"{type(exc).__name__}: {exc}",
            )
            if status is None:
                try:
                    self._error_response(502, "OpenAI proxy request failed")
                except (BrokenPipeError, ConnectionResetError):
                    pass
        finally:
            if tracked_socket is not None:
                with self.server.connection_lock:
                    self.server.connections.discard(tracked_socket)
            if connection is not None:
                connection.close()
            entry["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self.server.append_log(entry)

    do_POST = _proxy
    do_CONNECT = _proxy
    do_DELETE = _proxy
    do_GET = _proxy
    do_HEAD = _proxy
    do_OPTIONS = _proxy
    do_PATCH = _proxy
    do_PUT = _proxy


class _OpenAIUnixProxyServer(
    socketserver.ThreadingMixIn, socketserver.UnixStreamServer
):
    daemon_threads = True

    def __init__(self, socket_path, credential, log_path, *, write_readable, allowed_model=None):
        self.credential = credential
        self.allowed_model = allowed_model
        self.enabled = allowed_model is None
        self.connections = set()
        self.connection_lock = threading.Lock()
        self.exchange_condition = threading.Condition()
        self.active_exchanges = 0
        self.log_path = Path(log_path)
        self.readable_log_path = (
            self.log_path.with_name(f"{self.log_path.stem}-readable.log")
            if write_readable
            else None
        )
        super().__init__(str(socket_path), _OpenAIProxyHandler)

    def append_log(self, entry):
        sanitized = _sanitize_private_log_value(entry)
        _append_jsonl(self.log_path, sanitized)
        if self.readable_log_path is not None:
            _append_readable_proxy_log(self.readable_log_path, sanitized)


class _OpenAIReverseProxy:
    """Host-side, OpenAI-only proxy exposed to a sandbox through one Unix socket."""

    def __init__(self, credential, log_path, *, write_readable=True, allowed_model=None):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(prefix="gobench-openai-proxy-")
        self.socket_path = Path(self._temp.name) / "openai.sock"
        self._server = _OpenAIUnixProxyServer(
            self.socket_path,
            credential,
            self.log_path,
            write_readable=write_readable,
            allowed_model=allowed_model,
        )
        self._server.append_log(
            {
                "schema_version": 1,
                "event": "proxy_started",
                "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "auth_mode": credential.auth_mode,
            }
        )
        os.chmod(self.socket_path, 0o600)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="arena-openai-proxy",
            daemon=True,
        )
        self._thread.start()

    def set_enabled(self, enabled):
        server = self._server
        if server is not None:
            with server.connection_lock:
                server.enabled = bool(enabled)
                if not enabled:
                    # Discard outstanding auxiliary responses when the chess
                    # clock stops; they cannot be cached during opponent time.
                    for connection in server.connections:
                        with contextlib.suppress(OSError):
                            connection.shutdown(socket.SHUT_RDWR)

    def close(self):
        if self._server is None:
            return
        if self._server.allowed_model is not None:
            self.set_enabled(False)
        self._server.shutdown()
        self._server.server_close()
        if self._server.allowed_model is not None:
            with self._server.exchange_condition:
                self._server.exchange_condition.wait_for(
                    lambda: self._server.active_exchanges == 0, timeout=5
                )
        self._thread.join(timeout=2)
        self._server = None
        self._temp.cleanup()


def _workspace_proxy_launcher():
    return r"""#!/usr/bin/python3
import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time

SOCKET_PATH = os.environ.get("ARENA_PROXY_SOCKET", "/runtime/openai.sock")
PORT = int(os.environ["ARENA_PROXY_PORT"])
READY_PATH = os.environ.get("ARENA_PROXY_READY_PATH", "/tmp/arena-proxy-ready")


def report(event, **fields):
    record = {"event": event, "time_ns": time.time_ns(), **fields}
    print("ARENA_BRIDGE " + json.dumps(record, separators=(",", ":")),
          file=sys.stderr, flush=True)


def shutdown(sock, how):
    try:
        sock.shutdown(how)
    except OSError:
        pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sockets = (self.request, upstream)
        failed = threading.Event()

        def pump(source, destination, direction):
            try:
                while data := source.recv(65536):
                    destination.sendall(data)
                shutdown(destination, socket.SHUT_WR)
            except OSError as exc:
                if not failed.is_set():
                    report(
                        "relay_error",
                        direction=direction,
                        error_type=type(exc).__name__,
                        error=str(exc)[:500],
                    )
                failed.set()
                for current in sockets:
                    shutdown(current, socket.SHUT_RDWR)

        try:
            upstream.connect(SOCKET_PATH)
            request_pump = threading.Thread(
                target=pump,
                args=(self.request, upstream, "tcp_to_unix"),
                daemon=True,
            )
            request_pump.start()
            pump(upstream, self.request, "unix_to_tcp")
            request_pump.join()
        except OSError as exc:
            report(
                "connect_error",
                error_type=type(exc).__name__,
                error=str(exc)[:500],
            )
        finally:
            for current in sockets:
                current.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


server = Server(("127.0.0.1", PORT), Handler)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()
with open(READY_PATH, "w", encoding="utf-8") as ready:
    ready.write("ready\n")

child = subprocess.Popen(sys.argv[1:])


def forward_signal(signum, _frame):
    if child.poll() is None:
        try:
            child.send_signal(signum)
        except ProcessLookupError:
            pass


for signal_name in ("SIGINT", "SIGTERM", "SIGHUP"):
    if hasattr(signal, signal_name):
        signal.signal(getattr(signal, signal_name), forward_signal)

try:
    while child.poll() is None:
        if not server_thread.is_alive():
            report("server_stopped")
            child.terminate()
            break
        try:
            child.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
    return_code = child.wait()
finally:
    if server_thread.is_alive():
        server.shutdown()
    server.server_close()
    server_thread.join(timeout=2)

raise SystemExit(return_code)
"""


class _WorkspaceBubblewrap:
    """Harness-neutral bubblewrap launcher for one persistent workspace process."""

    _launcher_cache: ClassVar[dict[str, tuple[str, ...]]] = {}
    _launcher_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, workspace, runtime_dir, proxy_socket, *, binary=None):
        self.workspace = Path(workspace).resolve()
        self.runtime_dir = Path(runtime_dir).resolve()
        self.proxy_socket = Path(proxy_socket).resolve()
        self._configured_binary = binary

    def _binary(self):
        binary = self._configured_binary or shutil.which("bwrap")
        if binary is None:
            raise ArenaError(
                "bubblewrap (bwrap) is required for workspace agent harnesses"
            )
        resolved = Path(binary).resolve()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ArenaError(f"bubblewrap is not executable: {resolved}")
        return str(resolved)

    @classmethod
    def _probe_command(cls, binary, prefix):
        return (
            *prefix,
            binary,
            "--die-with-parent",
            "--new-session",
            "--unshare-user",
            "--unshare-all",
            "--disable-userns",
            "--assert-userns-disabled",
            "--cap-drop",
            "ALL",
            *cls._system_mounts(),
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--",
            "/usr/bin/true",
        )

    @classmethod
    def _launcher_prefix(cls, binary):
        with cls._launcher_lock:
            cached = cls._launcher_cache.get(binary)
            if cached is not None:
                return cached

            candidates = [()]
            restriction = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
            try:
                apparmor_restricts_userns = (
                    restriction.read_text(encoding="utf-8").strip() == "1"
                )
            except OSError:
                apparmor_restricts_userns = False
            aa_exec = shutil.which("aa-exec")
            if apparmor_restricts_userns and aa_exec is not None:
                candidates.append(
                    (str(Path(aa_exec).resolve()), "-p", "userbindmount", "--")
                )

            errors = []
            for prefix in candidates:
                try:
                    result = subprocess.run(
                        cls._probe_command(binary, prefix),
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=10,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
                    continue
                if result.returncode == 0:
                    cls._launcher_cache[binary] = prefix
                    return prefix
                detail = result.stderr.strip().replace("\n", " ")
                errors.append(detail or f"exit status {result.returncode}")

            detail = "; ".join(errors)
            raise ArenaError(
                "bubblewrap cannot create the required unprivileged namespaces"
                + (f": {detail}" if detail else "")
            )

    @staticmethod
    def _system_mounts():
        args = ["--ro-bind", "/usr", "/usr"]
        for path in (Path("/bin"), Path("/lib"), Path("/lib64")):
            if path.is_symlink():
                args += ["--symlink", os.readlink(path), str(path)]
            elif path.exists():
                args += ["--ro-bind", str(path), str(path)]
        certificates = Path("/etc/ssl/certs")
        if certificates.is_dir():
            args += ["--ro-bind", str(certificates), str(certificates)]
        return args

    def command(
        self,
        inner_command,
        environment,
        readonly_mounts=(),
        writable_mounts=(),
        hidden_paths=(),
    ):
        binary = self._binary()
        launcher_prefix = self._launcher_prefix(binary)
        args = [
            "/usr/bin/env",
            "-i",
            "PATH=/usr/bin:/bin",
            *launcher_prefix,
            binary,
            "--die-with-parent",
            "--new-session",
            "--unshare-user",
            "--unshare-all",
            "--disable-userns",
            "--assert-userns-disabled",
            "--cap-drop",
            "ALL",
            "--clearenv",
        ]
        for name, value in environment.items():
            args += ["--setenv", str(name), str(value)]
        args += self._system_mounts()
        args += [
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/usr/local",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/harness-home",
            "--dir",
            "/runtime",
            "--bind",
            str(self.workspace),
            "/workspace",
            "--ro-bind",
            str(self.runtime_dir),
            "/runtime-files",
            "--ro-bind",
            str(self.proxy_socket),
            "/runtime/openai.sock",
        ]
        for source, destination in writable_mounts:
            args += ["--bind", str(Path(source).resolve()), str(destination)]
        for source, destination in readonly_mounts:
            args += ["--ro-bind", str(Path(source).resolve()), str(destination)]
        for path in hidden_paths:
            resolved = Path(path).resolve()
            if resolved.is_relative_to("/usr") and resolved.exists():
                args += ["--ro-bind", "/dev/null", str(resolved)]
        args += ["--chdir", "/workspace", *map(str, inner_command)]
        return tuple(args)


def _workspace_hidden_katago_paths():
    candidates = {
        Path(path).resolve()
        for path in (
            KATAGO_CPU_BINARY,
            KATAGO_CUDA_BINARY,
            KATAGO_MODEL,
            shutil.which("katago"),
        )
        if path is not None
    }
    for directory in (Path("/usr/bin"), Path("/usr/games")):
        if directory.is_dir():
            candidates.update(
                path.resolve()
                for path in directory.iterdir()
                if "katago" in path.name.lower()
            )
    return tuple(sorted(candidates))


def _workspace_codex_not_found(exc):
    return isinstance(exc, RuntimeError) and _llm_api_error(exc)[1] == 404


def _workspace_codex_transport_failure(exc):
    message = str(exc).lower()
    return isinstance(exc, RuntimeError) and (
        "stream disconnected before completion" in message
        or _workspace_codex_not_found(exc)
        or _retryable_llm_api_error(exc)
    )


def _agent_run_dir(work_dir):
    work = Path(work_dir).resolve()
    try:
        work.relative_to(_Arena.UNTRACKED_LOG_ROOT.resolve())
    except ValueError as exc:
        raise ArenaError("agent game data must be under untracked_log") from exc
    return work.parent if re.fullmatch(r"batch-[0-9]+", work.name) else work


def _agent_workspace_path(run_dir, game_number):
    return Path(run_dir) / f"game-{game_number:06d}-workspace"


def _agent_log_jsonable(value):
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _agent_log_jsonable(dump(mode="json"))
    if isinstance(value, dict):
        return {str(name): _agent_log_jsonable(item) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_agent_log_jsonable(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    try:
        fields = vars(value)
    except TypeError:
        return str(value)
    return {
        str(name): _agent_log_jsonable(item)
        for name, item in fields.items()
        if not str(name).startswith("_")
    }


def _workspace_filenames(workspace):
    workspace = Path(workspace)
    if not workspace.is_dir():
        return []
    names = []
    for root, directories, files in os.walk(workspace, followlinks=False):
        base = Path(root)
        symlink_directories = [
            name for name in directories if (base / name).is_symlink()
        ]
        directories[:] = [
            name for name in directories if name not in symlink_directories
        ]
        names.extend((base / name).relative_to(workspace).as_posix() for name in files)
        names.extend(
            (base / name).relative_to(workspace).as_posix()
            for name in symlink_directories
        )
    return sorted(names)


def _agent_log_one_line(value, *, limit=240):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    rendered = " ".join(value.split())
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(limit - 1, 0)].rstrip() + "…"


def _agent_log_command_output(value, *, failed):
    if not isinstance(value, str):
        return _agent_log_one_line(value, limit=180)
    lines = [" ".join(line.split()) for line in value.splitlines() if line.strip()]
    if not lines:
        return ""
    if failed:
        return _agent_log_one_line(lines[-1], limit=180)
    summary = "; ".join(lines[:2])
    if len(lines) > 2:
        summary += f" (+{len(lines) - 2} lines)"
    return _agent_log_one_line(summary, limit=180)


def _agent_log_file_path(value):
    if not isinstance(value, str):
        return "?"
    return value.removeprefix("/workspace/") or "."


def _compact_agent_tool_event(event):
    if not isinstance(event, dict):
        return _agent_log_one_line(event, limit=360)
    item = event.get("item") if isinstance(event.get("item"), dict) else event
    kind = event.get("type") or item.get("type") or "tool"
    lowered_kind = str(kind).lower()

    if "filechange" in lowered_kind or isinstance(item.get("changes"), list):
        changes = []
        for change in item.get("changes", ()):
            if not isinstance(change, dict):
                continue
            change_kind = change.get("kind")
            if isinstance(change_kind, dict):
                change_kind = change_kind.get("type")
            changes.append(
                f"{change_kind or 'change'} {_agent_log_file_path(change.get('path'))}"
            )
        if len(changes) > 4:
            changes = [*changes[:4], f"+{len(changes) - 4} more"]
        parts = ["file", str(item.get("status") or "unknown")]
        if changes:
            parts.append(", ".join(changes))
        return _agent_log_one_line(" | ".join(parts), limit=360)

    if "command" in lowered_kind or isinstance(item.get("command"), str):
        actions = item.get("command_actions")
        command = None
        if isinstance(actions, list):
            command = next(
                (
                    action.get("command")
                    for action in actions
                    if isinstance(action, dict)
                    and isinstance(action.get("command"), str)
                ),
                None,
            )
        command = command or item.get("command") or "?"
        status = str(item.get("status") or "unknown")
        parts = ["command", status, _agent_log_one_line(command, limit=180)]
        if item.get("exit_code") is not None:
            parts.append(f"exit {item['exit_code']}")
        duration = item.get("duration_ms")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            parts.append(f"{duration / 1000:.1f}s")
        output = _agent_log_command_output(
            item.get("aggregated_output"), failed=status != "completed"
        )
        if output:
            parts.append(output)
        return _agent_log_one_line(" | ".join(parts), limit=360)

    return _agent_log_one_line(
        {"type": kind, "name": item.get("name"), "status": item.get("status")},
        limit=360,
    )


def _append_agent_log(
    path,
    *,
    player,
    game,
    move,
    attempt,
    workspace,
    state,
    state_changed,
    tool_calls,
    workspace_files,
    workspace_files_changed,
):
    workspace = Path(workspace)
    sanitized_state = _sanitize_private_log_value(_agent_log_jsonable(state))
    sanitized_tools = _sanitize_private_log_value(_agent_log_jsonable(tool_calls))
    relative_workspace = _portable_path(workspace)
    detail = []
    if state_changed:
        detail += [
            "  AGENTIC STATE",
            (
                json.dumps(
                    sanitized_state,
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                if sanitized_state
                else "  (none)"
            ),
        ]
    if sanitized_tools:
        detail += [
            "  TOOL EVENTS",
            *(f"  - {_compact_agent_tool_event(event)}" for event in sanitized_tools),
        ]
    if workspace_files_changed:
        detail += [
            f"  WORKSPACE FILES: {relative_workspace}",
            *(f"  - {name}" for name in workspace_files),
        ]
        if not workspace_files:
            detail.append("  (empty)")
    lines = [
        (
            f"[{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}] "
            f"game {game}, move {move}, attempt {attempt} | {player} | "
            f"tool events: {len(sanitized_tools)} | "
            f"workspace files: {len(workspace_files)}"
        ),
        *detail,
    ]
    path = Path(path)
    with _State.jsonl_write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not path.exists() or path.stat().st_size == 0
        with path.open("a", encoding="utf-8") as out:
            if new_file:
                out.write("# Agent activity log\n\n")
            out.write("\n".join(lines) + "\n")


def _codex_tool_calls(result):
    calls = []
    for wrapped in getattr(result, "items", ()):
        item = getattr(wrapped, "root", wrapped)
        kind = type(item).__name__
        if any(
            marker in kind
            for marker in ("Command", "FileChange", "ToolCall", "WebSearch")
        ):
            calls.append({"type": kind, "item": _agent_log_jsonable(item)})
    return calls


class _CodexGameClient:
    """Evaluate a private copy of one run's autonomous-preparation checkpoint."""

    _workspace_label = "Codex workspace"
    _location_label = "codex-workspace"

    def __init__(
        self,
        player_name,
        player,
        work_dir,
        game_number,
        *,
        proxy_credential=None,
    ):
        if player.agentic_harness not in _CODEX_WORKSPACE_HARNESSES:
            raise ArenaError(f"invalid Codex agentic harness: {player.agentic_harness}")
        self.player_name = player_name
        self.player = player
        self.agentic_harness = player.agentic_harness
        self.game_number = game_number
        self._codex = None
        self._thread = None
        self._sdk = None
        self._proxy = None
        self._runtime_generation = 0
        self._usage_total = None
        self._proxy_credential = proxy_credential
        self._resource_lock = None
        self._scope = None
        self._volume = None
        self._clock = None
        self._training = False
        self._pending_turn = None
        work = Path(work_dir).resolve()
        self._initialize_workspace(work, game_number)
        self.settings = _codex_workspace_settings(self.agentic_harness)
        self.checkpoint_root = self.run_dir / "codex-checkpoints" / self.player_name
        self._set_phase(self.private_dir, training=False)
        try:
            self._prepare()
        except Exception:
            self.close()
            raise

    @property
    def _continual(self):
        return _CODEX_TRAINING_SECONDS[self.agentic_harness] > 0

    def _initialize_workspace(self, work, game_number):
        try:
            work.relative_to(_Arena.UNTRACKED_LOG_ROOT.resolve())
        except ValueError as exc:
            raise ArenaError(
                f"{self._location_label} game data must be under untracked_log"
            ) from exc
        self.run_dir = _agent_run_dir(work)
        self.agents_log_path = self.run_dir / "agents_log.txt"
        self.workspace_view = _agent_workspace_path(self.run_dir, game_number)
        private_root = work / "agent-workspaces"
        if private_root.is_symlink():
            raise ArenaError(
                f"unsafe {self._workspace_label} private root: {private_root}"
            )
        self.private_dir = private_root / f"game-{game_number:06d}"

    def _prepare(self):
        if self.private_dir.is_symlink():
            raise ArenaError(f"unsafe Codex private path: {self.private_dir}")
        self.private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.private_dir, 0o700)
        if self._proxy_credential is None:
            raise ArenaError("OpenAI proxy credentials are required for Codex")
        identity = _workspace_runtime_identity()
        specification = {
            **self.settings.manifest(), "player": self.player_name,
            "model": self.player.model, "effort": self.player.level,
            "runtime": identity,
            "codex_config_sha256": hashlib.sha256(_codex_config_text().encode()).hexdigest(),
        }
        # Color-swapped games share one immutable checkpoint. Wait for training
        # before acquiring another core, so checkpoint waiters do not hoard CPUs.
        self.checkpoint_root.mkdir(parents=True, exist_ok=True)
        with (self.checkpoint_root / "preparation.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._resource_lock = CoreLease()
            self._ensure_checkpoint(specification)
        self._set_phase(self.private_dir, training=False)
        marker = self.private_dir / "evaluation.json"
        expected = {"protocol": WORKSPACE_PROTOCOL_VERSION,
                    "checkpoint_id": self.checkpoint["checkpoint_id"],
                    "game": self.game_number}
        if marker.exists():
            if _workspace_read_json(marker) != expected:
                raise WorkspaceError("evaluation belongs to a different training checkpoint")
        else:
            if self.state_path.exists() or self._volume.image.exists():
                raise WorkspaceError("legacy/incomplete evaluation state cannot be silently reused")
            _workspace_atomic_json(marker, expected)
        ProcessScope.recover(self._phase_dir)
        self._volume.create(self.checkpoint_root / "checkpoint" / "disk.img")
        checkpoint_thread = self.checkpoint_root / "checkpoint" / "thread.json"
        if not self.state_path.exists() and checkpoint_thread.exists():
            _workspace_atomic_json(self.state_path, _workspace_read_json(checkpoint_thread))
        self._volume.mount()
        self._clock = AgentClock(self._phase_dir / "clock.json", self.settings.evaluation_seconds,
                                 display_path=self._phase_dir / "public" / "clock.json")
        if os.path.lexists(self.workspace_view):
            if not self.workspace_view.is_symlink() or self.workspace_view.resolve() != self.cwd.resolve():
                raise WorkspaceError("legacy or mismatched per-game workspace view")
        else:
            self.workspace_view.symlink_to(os.path.relpath(self.cwd, self.workspace_view.parent),
                                           target_is_directory=True)
        # Runtime startup is deferred until the first move. A finished clock
        # can therefore be recovered as a timeout without starting Codex.

    def _set_phase(self, directory, *, training):
        self._phase_dir = Path(directory)
        self._training = training
        self._volume = WorkspaceVolume(self._phase_dir, self.settings.storage_mib)
        self.cwd = self._volume.mountpoint / "workspace"
        self.home = self._volume.mountpoint / "runtime"
        self.state_path = self._phase_dir / "thread.json"
        self._thread = None
        self._usage_total = None
        self._pending_turn = None

    def _ensure_checkpoint(self, specification):
        checkpoint_dir = self.checkpoint_root / "checkpoint"
        manifest = checkpoint_dir / "manifest.json"
        if manifest.exists():
            self.checkpoint = _workspace_read_json(manifest)
            if self.checkpoint.get("specification") != specification:
                raise WorkspaceError("checkpoint configuration/runtime changed; start a new run")
            if _workspace_file_sha256(checkpoint_dir / "disk.img") != self.checkpoint["image_sha256"]:
                raise WorkspaceError("immutable training checkpoint image was modified")
            thread_file = checkpoint_dir / "thread.json"
            digest = _workspace_file_sha256(thread_file) if thread_file.exists() else None
            if digest != self.checkpoint.get("thread_sha256"):
                raise WorkspaceError("immutable training checkpoint thread was modified")
            # The published checkpoint is the retained training image.
            (self.checkpoint_root / "preparation" / "disk.img").unlink(missing_ok=True)
            return
        if checkpoint_dir.exists():
            raise WorkspaceError("incomplete training checkpoint publication")
        preparation = self.checkpoint_root / "preparation"
        preparation.mkdir(parents=True, exist_ok=True)
        spec_path = preparation / "specification.json"
        if spec_path.exists() and _workspace_read_json(spec_path) != specification:
            raise WorkspaceError("cannot resume preparation with different settings")
        _workspace_atomic_json(spec_path, specification)
        self._set_phase(preparation, training=True)
        ProcessScope.recover(preparation)
        self._volume.create()
        self._volume.mount()
        self._clock = AgentClock(preparation / "clock.json", self.settings.training_seconds,
                                 display_path=preparation / "public" / "clock.json")
        try:
            if self._clock.remaining > 0:
                self._run_preparation()
        finally:
            self._dispose_runtime()
            self._clock.pause()
            self._volume.close()
        if self._clock.remaining > 0:
            raise WorkspaceError("preparation stopped before its allocated time was consumed")
        staging = self.checkpoint_root / f".checkpoint-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            _copy_workspace_image(self._volume.image, staging / "disk.img")
            image_digest = _workspace_file_sha256(staging / "disk.img")
            if self.state_path.exists():
                _workspace_atomic_json(staging / "thread.json", _workspace_read_json(self.state_path))
            usages = _read_jsonl_objects(preparation / "openai-proxy.usage.jsonl", "training usage")
            exchanges = _read_jsonl_objects(preparation / "openai-proxy.jsonl", "training exchanges")
            accounted = {entry["exchange_id"] for entry in usages}
            unaccounted = sum(entry.get("method") == "POST"
                              and entry.get("exchange_id") not in accounted
                              for entry in exchanges)
            cost = sum(_llm_call_cost(entry["usage"], "openai_codex_workspace",
                                      self.player.model,
                                      started_at=entry.get("started_at")) for entry in usages)
            self.checkpoint = {
                "checkpoint_id": uuid.uuid4().hex,
                "specification": specification, "image_sha256": image_digest,
                "thread_sha256": (_workspace_file_sha256(staging / "thread.json")
                                  if (staging / "thread.json").exists() else None),
                "training_seconds": self._clock.spent,
                "training_model_requests": len(usages), "training_cost_usd": cost,
                "training_requests_without_reported_usage": unaccounted,
                "training_usage": _sum_response_usages([entry["usage"] for entry in usages]),
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            _workspace_atomic_json(staging / "manifest.json", self.checkpoint)
            os.chmod(staging / "disk.img", 0o400)
            staging.rename(checkpoint_dir)
            self._volume.image.unlink()
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        self._clock = None

    def _run_preparation(self):
        _append_jsonl(self._phase_dir / "training-events.jsonl", {
            "event": "preparation_started", "remaining_seconds": self._clock.remaining,
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
        self._clock.start(self._expire_runtime)
        failures = 0
        codex_not_found_failures = 0
        try:
            self._start_runtime()
            self._scope.thaw()
            self._proxy.set_enabled(True)
            while self._clock.remaining > 0:
                prompt = (
                    "You are preparing to play 9x9 Go. Use this autonomous preparation "
                    "period to improve your future play by writing and testing code, "
                    "self-play, search, experiments, and notes. You have no access to "
                    "KataGo, an arena opponent, external Go engines, or the internet. "
                    "Python3, g++, and make are available. Build your own tools in /workspace. "
                    "Rules: 9x9, White komi 7.0, Tromp-Taylor area scoring without dead-stone "
                    "removal, positional superko, legal self-capture subject to superko, "
                    "two passes end the game. Columns A-H,J, rows 1-9. "
                    "After preparation, each evaluation game will receive an independent "
                    "copy of your workspace and harness state. You will have "
                    f"{self.settings.evaluation_seconds:g} seconds per evaluation game "
                    "across all your moves, model thinking and tools. "
                    f"Preparation time remaining: {self._clock.remaining:.1f} seconds. "
                    "Read /arena/clock.json for a live deadline. Save useful code and notes "
                    "incrementally; the runtime is stopped at the deadline with no extra "
                    "cleanup time. If a prior preparation turn finished, continue improving "
                    "or testing your work until time expires. " + self._resource_instructions()
                )
                try:
                    result, requests = self._run_turn(
                        self._persistent_thread(), prompt, **self._turn_options()
                    )
                    if result.usage is not None:
                        self._turn_usage(result)
                    _append_jsonl(self._phase_dir / "training-events.jsonl", {
                        "event": "preparation_turn", "remaining_seconds": self._clock.remaining,
                        "output": result.final_response, "request_usages": requests,
                    })
                    failures = 0
                    codex_not_found_failures = 0
                except Exception as exc:
                    if self._clock.expired or self._clock.remaining <= 0:
                        break
                    failures += 1
                    if _workspace_codex_not_found(exc):
                        codex_not_found_failures += 1
                    if (not _llm_api_attempts_remaining(
                            failures, codex_not_found_failures=codex_not_found_failures
                        ) or not _workspace_codex_transport_failure(exc)):
                        raise
                    self._dispose_runtime()
                    # The training clock continues through retry overhead.
                    delay = min(_llm_api_retry_delay(exc, failures), self._clock.remaining)
                    _append_jsonl(self._phase_dir / "training-events.jsonl", {
                        "event": "preparation_retry", "attempt": failures,
                        "error": type(exc).__name__, "http_status": _llm_api_error(exc)[1],
                        "retry_in_seconds": delay,
                    })
                    time.sleep(max(delay, 0))
                    if self._clock.remaining <= 0:
                        break
                    self._start_runtime()
                    self._scope.thaw()
                    self._proxy.set_enabled(True)
        except Exception:
            if not self._clock.expired and self._clock.remaining > 0:
                raise
        finally:
            self._expire_runtime()
            self._clock.pause()

    def _resource_instructions(self):
        return ("Your entire agent has exclusive use of 1 physical CPU core "
                f"with {len(self._resource_lock.cpus)} logical CPUs, "
                f"{self.settings.memory_mib} MiB RAM, {self.settings.storage_mib} MiB "
                f"writable storage and {self.settings.max_tasks} processes/threads; "
                "there is no GPU or swap. Subagents share these limits.")

    def _turn_options(self):
        return {"approval_mode": self._sdk.ApprovalMode.deny_all,
                "cwd": "/workspace", "effort": self.player.level,
                "model": self.player.model, "sandbox": self._sdk.Sandbox.full_access}

    def _expire_runtime(self):
        if self._proxy is not None:
            self._proxy.set_enabled(False)
        if self._scope is not None:
            self._scope.kill()

    def _dispose_runtime(self):
        codex, proxy, scope = self._codex, self._proxy, self._scope
        self._codex = self._proxy = self._scope = self._sdk = self._thread = None
        try:
            if scope is not None:
                scope.close()
        finally:
            try:
                if codex is not None:
                    self._close_sdk(codex)
            finally:
                if proxy is not None:
                    proxy.close()

    @staticmethod
    def _close_sdk(codex):
        # SDK 0.147 closes stdin/processes but leaves the reader pipe objects
        # open. Close them after its reader threads have been joined.
        process = getattr(getattr(codex, "_client", None), "_proc", None)
        codex.close()
        if process is not None:
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()

    @staticmethod
    def _sdk_and_binary():
        try:
            import openai_codex
            from openai_codex.client import _resolve_codex_bin
        except ModuleNotFoundError as exc:
            raise ArenaError("openai-codex Python package is missing") from exc
        base_config = openai_codex.CodexConfig()
        return openai_codex, Path(_resolve_codex_bin(base_config)).resolve()

    @staticmethod
    def _workspace_bwrap_binary():
        system_binary = shutil.which("bwrap")
        if system_binary is not None:
            return Path(system_binary).resolve()
        try:
            from codex_cli_bin import bundled_package_dir

            bundled_binary = bundled_package_dir() / "codex-resources" / "bwrap"
        except (ImportError, OSError) as exc:
            raise ArenaError(
                "bubblewrap is required and the Codex bundled copy is unavailable"
            ) from exc
        if not bundled_binary.is_file() or not os.access(bundled_binary, os.X_OK):
            raise ArenaError(
                f"Codex bundled bubblewrap is not executable: {bundled_binary}"
            )
        return bundled_binary.resolve()

    def _workspace_runtime(self, workspace, runtime_dir, proxy_log):
        sdk, codex_bin = self._sdk_and_binary()
        code_mode_host = codex_bin.with_name("codex-code-mode-host")
        if not code_mode_host.is_file() or not os.access(code_mode_host, os.X_OK):
            raise ArenaError(
                f"Codex code-mode host is not executable: {code_mode_host}"
            )
        runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        codex_home = runtime_dir / "codex-home"
        codex_home.mkdir(mode=0o700, exist_ok=True)
        os.chmod(codex_home, 0o700)
        launcher_path = runtime_dir / "proxy-launcher.py"
        config_path = runtime_dir / "config.toml"
        launcher_path.write_text(_workspace_proxy_launcher(), encoding="utf-8")
        config_path.write_text(_codex_config_text(), encoding="utf-8")
        os.chmod(launcher_path, 0o600)
        os.chmod(config_path, 0o600)
        proxy = _OpenAIReverseProxy(
            self._proxy_credential, proxy_log, write_readable=False,
            allowed_model=self.player.model,
        )
        scope = ProcessScope(self._phase_dir, self.settings, core=self._resource_lock)
        self._scope = scope
        codex = None
        try:
            sandbox = _WorkspaceBubblewrap(
                workspace,
                runtime_dir,
                proxy.socket_path,
                binary=self._workspace_bwrap_binary(),
            )
            environment = {
                "HOME": "/harness-home",
                "CODEX_HOME": "/harness-home",
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "TMPDIR": "/tmp",
                "ARENA_PROXY_PORT": str(_Arena.CODEX_WORKSPACE_PROXY_PORT),
                "ARENA_PROXY_TOKEN": "arena-proxy-no-provider-secret",
            }
            inner = (
                "/usr/bin/python3",
                "/runtime/launcher.py",
                "/runtime/codex",
                "app-server",
                "--listen",
                "stdio://",
            )
            launch_args = sandbox.command(
                inner,
                environment,
                readonly_mounts=(
                    (launcher_path, "/runtime/launcher.py"),
                    (config_path, "/harness-home/config.toml"),
                    (codex_bin, "/runtime/codex"),
                    (code_mode_host, "/runtime/codex-code-mode-host"),
                    (self._phase_dir / "public", "/arena"),
                ),
                writable_mounts=((codex_home, "/harness-home"),
                                 (self._volume.mountpoint / "tmp", "/tmp")),
                hidden_paths=_workspace_hidden_katago_paths(),
            )
            config = sdk.CodexConfig(
                launch_args_override=scope.command(launch_args),
                cwd=str(workspace),
                client_name="gobench",
                client_title="GoBench",
            )
            if self._clock.remaining <= 0:
                raise WorkspaceTimeExpired("agent clock expired during startup")
            codex = sdk.Codex(config)
            scope.attach()
            scope.freeze()
        except Exception:
            scope.close()
            if codex is not None:
                self._close_sdk(codex)
            proxy.close()
            raise
        return sdk, codex, proxy

    def _workspace_options(self, sdk):
        return {
            "approval_mode": sdk.ApprovalMode.deny_all,
            "base_instructions": _Arena.CODEX_BASE_INSTRUCTIONS,
            "cwd": "/workspace",
            "model": self.player.model,
            "model_provider": _Arena.CODEX_WORKSPACE_PROVIDER,
            "sandbox": sdk.Sandbox.full_access,
        }

    @staticmethod
    def _item_kinds(result):
        return tuple(
            type(getattr(wrapped, "root", wrapped)).__name__ for wrapped in result.items
        )

    def _start_runtime(self):
        if self._codex is not None:
            return
        self._sdk, self._codex, self._proxy = self._workspace_runtime(
            self.cwd, self.home, self._phase_dir / "openai-proxy.jsonl"
        )
        self._runtime_generation += 1

    def _workspace_bridge_events(self):
        client = getattr(self._codex, "_client", None)
        stderr_tail = getattr(client, "_stderr_tail", None)
        if not callable(stderr_tail):
            return []
        try:
            lines = stderr_tail(100).splitlines()
        except Exception:
            return []
        events = []
        for line in lines:
            if not line.startswith("ARENA_BRIDGE "):
                continue
            try:
                event = json.loads(line.removeprefix("ARENA_BRIDGE "))
            except json.JSONDecodeError:
                event = {"event": "invalid_bridge_diagnostic", "line": line[:1000]}
            events.append(event)
        return events

    def _restart_workspace_runtime(self, exc):
        bridge_events = self._workspace_bridge_events()
        codex, proxy = self._codex, self._proxy
        self._codex = self._thread = self._sdk = self._proxy = None
        cleanup_errors = []
        scope = getattr(self, "_scope", None)
        if scope is not None:
            scope.close()
            self._scope = None
        for resource in (codex, proxy):
            if resource is None:
                continue
            try:
                if resource is codex:
                    self._close_sdk(resource)
                else:
                    resource.close()
            except Exception as cleanup_exc:
                cleanup_errors.append(f"{type(cleanup_exc).__name__}: {cleanup_exc}")
        _append_jsonl(
            self.private_dir / "runtime-events.jsonl",
            _sanitize_private_log_value(
                {
                    "schema_version": 1,
                    "event": "workspace_runtime_restart",
                    "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "runtime_generation": self._runtime_generation,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "bridge_events": bridge_events,
                    "cleanup_errors": cleanup_errors,
                }
            ),
        )

    def _thread_options(self):
        return self._workspace_options(self._sdk)

    def _persistent_thread(self):
        if self._thread is not None:
            return self._thread
        options = self._thread_options()
        if self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                thread_id = state["thread_id"]
                if not isinstance(thread_id, str) or not thread_id:
                    raise TypeError("thread_id must be a nonempty string")
                saved_usage = state.get("usage_total")
                self._thread_has_turns = state.get("has_turns", True)
                if saved_usage is not None:
                    self._usage_total = self._validate_saved_usage(saved_usage)
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ArenaError(
                    f"invalid saved Codex thread state: {self.state_path}"
                ) from exc
            try:
                self._thread = self._codex.thread_resume(thread_id, **options)
            except Exception as exc:
                # Codex does not persist an empty thread until its first turn.
                # Only that explicitly recorded empty state can start afresh.
                if self._thread_has_turns or "no rollout found" not in str(exc):
                    raise
                self._thread = self._codex.thread_start(ephemeral=False, **options)
                self._save_thread_state()
        else:
            self._thread = self._codex.thread_start(ephemeral=False, **options)
            self._thread_has_turns = False
            self._usage_total = self._zero_usage()
            self._save_thread_state()
        return self._thread

    _USAGE_FIELDS = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )

    @classmethod
    def _zero_usage(cls):
        return {field: 0 for field in cls._USAGE_FIELDS}

    @classmethod
    def _validate_saved_usage(cls, usage):
        if not isinstance(usage, dict):
            raise TypeError("usage_total must be an object")
        counts = {}
        for field in cls._USAGE_FIELDS:
            value = usage.get(field, 0)
            if type(value) is not int or value < 0:
                raise TypeError(f"invalid usage_total.{field}")
            counts[field] = value
        return counts

    @classmethod
    def _usage_counts(cls, usage):
        counts = {}
        for field in cls._USAGE_FIELDS:
            value = getattr(usage, field, 0) or 0
            if type(value) is not int or value < 0:
                raise ArenaError(f"Codex reported invalid token usage for {field}")
            counts[field] = value
        return counts

    def _save_thread_state(self):
        state = {"thread_id": self._thread.id,
                 "has_turns": getattr(self, "_thread_has_turns", False)}
        if self._usage_total is not None:
            state["usage_total"] = self._usage_total
        _workspace_atomic_json(self.state_path, state)

    def _turn_usage(self, result):
        usage = getattr(result, "usage", None)
        last = getattr(usage, "last", None)
        if last is None:
            raise ArenaError("Codex turn did not report token usage")
        last_counts = self._usage_counts(last)
        total = getattr(usage, "total", None)
        if total is None:
            return last_counts

        current_total = self._usage_counts(total)
        previous_total = getattr(self, "_usage_total", None)
        if previous_total is None or any(
            current_total[field] < previous_total[field] for field in self._USAGE_FIELDS
        ):
            turn_counts = last_counts
        else:
            turn_counts = {
                field: current_total[field] - previous_total[field]
                for field in self._USAGE_FIELDS
            }
        self._usage_total = current_total
        self._save_thread_state()
        return turn_counts

    @staticmethod
    def _response_usage(counts):
        return {
            "input_tokens": counts["input_tokens"],
            "input_tokens_details": {
                "cached_tokens": counts["cached_input_tokens"],
                "cache_write_tokens": counts["cache_write_input_tokens"],
            },
            "output_tokens": counts["output_tokens"],
            "output_tokens_details": {
                "reasoning_tokens": counts["reasoning_output_tokens"]
            },
        }

    def _run_turn(self, thread, prompt, **options):
        # Use the SDK's result collector, retaining the request usage updates
        # that Thread.run otherwise discards in favor of the final update.
        from openai_codex._run import _collect_turn_result

        turn = thread.turn(prompt, **options)
        self._thread_has_turns = True
        if getattr(self, "_clock", None) is not None:
            self._save_thread_state()
        pending = getattr(self, "_pending_turn", None)
        if pending is not None:
            pending["codex_turn_id"] = turn.id
            _workspace_atomic_json(self._journal_path(), pending)
        requests = []
        failure = None
        previous = getattr(self, "_usage_total", None)

        def capture(stream):
            nonlocal previous, failure
            for event in stream:
                payload = event.payload
                if (
                    event.method == "thread/tokenUsage/updated"
                    and payload.turn_id == turn.id
                ):
                    total = self._usage_counts(payload.token_usage.total)
                    if total != previous:
                        requests.append(
                            self._response_usage(
                                self._usage_counts(payload.token_usage.last)
                            )
                        )
                    previous = total
                if event.method == "turn/completed" and payload.turn.id == turn.id:
                    if payload.turn.error is not None:
                        failure = payload.turn.error.model_dump(
                            mode="json", by_alias=True
                        )
                yield event

        try:
            with contextlib.closing(turn.stream()) as stream:
                result = _collect_turn_result(capture(stream), turn_id=turn.id)
        except Exception as exc:
            exc.arena_usage = _sum_response_usages(requests)
            if failure is not None:
                info = failure.get("codexErrorInfo")
                exc.body = {"codex_error": failure}
                if isinstance(info, dict):
                    for details in info.values():
                        if (
                            isinstance(details, dict)
                            and details.get("httpStatusCode") is not None
                        ):
                            exc.status_code = details["httpStatusCode"]
                if info in ("serverOverloaded", "internalServerError") or (
                    isinstance(info, dict)
                    and any(
                        key in info
                        for key in (
                            "responseStreamConnectionFailed",
                            "responseStreamDisconnected",
                            "responseTooManyFailedAttempts",
                            "httpConnectionFailed",
                        )
                    )
                    and getattr(exc, "status_code", None) is None
                ):
                    exc.body["retryable"] = True
            if previous is not None:
                self._usage_total = previous
                self._save_thread_state()
            raise
        return result, requests

    def begin_turn(
        self,
        game_number,
        move_number,
        attempt,
        api_attempt,
        prompt,
        log_path,
    ):
        if game_number != self.game_number or not isinstance(prompt, str):
            raise ArenaError("Codex turn context does not match its game")
        self._turn_context = {
            "game": game_number,
            "move": move_number,
            "attempt": attempt,
            "api_attempt": api_attempt,
            "log_path": str(Path(log_path).resolve()),
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "marker": f"gobench-game-{game_number}-move-{move_number}-attempt-{attempt}",
        }

    def _log_agent_turn(self, result):
        path = getattr(self, "agents_log_path", None)
        context = getattr(self, "_turn_context", None)
        if path is None or not isinstance(context, dict):
            return
        try:
            files = _workspace_filenames(self.cwd)
            files_key = tuple(files)
            files_changed = files_key != getattr(self, "_agents_log_files_key", None)
            _append_agent_log(
                path,
                player=self.player_name,
                game=context["game"],
                move=context["move"],
                attempt=context["attempt"],
                workspace=self.cwd,
                state=None,
                state_changed=False,
                tool_calls=_codex_tool_calls(result),
                workspace_files=files,
                workspace_files_changed=files_changed,
            )
            self._agents_log_files_key = files_key
        except (OSError, TypeError, ValueError):
            return

    def prepare_prompt(self, prompt):
        if _Arena.CODEX_WORKSPACE_INSTRUCTIONS in prompt:
            return prompt
        instructions = (
            f"{_Arena.CODEX_WORKSPACE_INSTRUCTIONS}\n\n"
            "This evaluation game starts from a private copy of the preparation "
            "checkpoint. Your conversation and files persist within this game. "
            "No evaluation game affects another game or the training checkpoint. "
            "Python3, g++, and make are available. There is no undo or opponent "
            "analysis access. Your total game clock includes model thinking and "
            "all tool use; allocate it freely across moves. The clock pauses "
            "and your processes are frozen during the opponent's turn. "
            "Read /arena/clock.json for your remaining time and active deadline."
        )
        return _insert_before_move_output_instructions(prompt, instructions)

    def create(self, **request):
        clock = getattr(self, "_clock", None)
        if clock is None:
            return self._create_response(**request)
        saved = self._saved_turn()
        if saved is not None and saved.get("state") == "completed":
            return self._journal_response(saved)
        if clock.remaining <= 0:
            raise WorkspaceTimeExpired("agent's cumulative game clock is exhausted")
        clock.start(self._expire_runtime)
        response = failure = None
        try:
            self._start_runtime()
            self._scope.thaw()
            self._proxy.set_enabled(True)
            response = self._create_response(**request)
        except Exception as exc:
            failure = exc
        finally:
            if self._proxy is not None:
                self._proxy.set_enabled(False)
            try:
                if self._scope is not None and not self._scope.dead:
                    try:
                        self._scope.freeze()
                    except FileNotFoundError:
                        self._scope.dead = True
                        if failure is None:
                            failure = WorkspaceError("agent runtime exited before it could be frozen")
                    except (OSError, WorkspaceError) as exc:
                        # OOM can remove the cgroup before cleanup. Do not let
                        # a failed freeze hide the original resource failure.
                        if failure is None:
                            failure = exc
            finally:
                clock.pause()
        if clock.expired or clock.remaining <= 0:
            expired = WorkspaceTimeExpired("agent's cumulative game clock is exhausted")
            expired.arena_usage = (response.usage if response is not None
                                   else getattr(failure, "arena_usage", {}))
            raise expired from failure
        if failure is not None:
            # Also cover failures outside _run_turn, including a cgroup that
            # disappears after the SDK returns but before we freeze it.
            if (not isinstance(failure, WorkspaceResourceExceeded)
                    and self._scope is not None
                    and self._scope.failure_reason() == "oom-kill"):
                exceeded = WorkspaceResourceExceeded("agent exceeded its memory allocation")
                exceeded.arena_usage = (response.usage if response is not None
                                       else getattr(failure, "arena_usage", {}))
                raise exceeded from failure
            raise failure
        if self._pending_turn is not None:
            self._pending_turn.update(state="completed", output=response.output_text,
                                      usage=response.usage)
            _workspace_atomic_json(self._journal_path(), self._pending_turn)
        return response

    def _journal_path(self):
        context = getattr(self, "_turn_context", None)
        if context is None:
            raise WorkspaceError("evaluation request has no turn identity")
        return self._phase_dir / "turns" / f"{context['marker']}.json"

    def _saved_turn(self):
        path = self._journal_path()
        if not path.exists():
            return None
        saved = _workspace_read_json(path)
        if saved.get("prompt_sha256") != self._turn_context["prompt_sha256"]:
            raise WorkspaceError("saved evaluation turn does not match the current position")
        return saved

    def _journal_response(self, saved):
        context = self._turn_context
        logged = any(entry.get("ok") is True and entry.get("player") == self.player_name
                     and all(entry.get(key) == context[key] for key in ("game", "move", "attempt"))
                     for entry in _read_jsonl_objects(Path(context["log_path"]), "Codex move log"))
        return _CodexMoveResponse(saved["output"], saved["usage"], reused=logged)

    def _proxy_usage_since(self, offset):
        path = self._phase_dir / "openai-proxy.usage.jsonl"
        if not path.exists():
            return []
        # Validate/repair a torn final append before consuming the byte range.
        _read_jsonl_objects(path, "Codex proxy usage")
        with _State.jsonl_write_lock, path.open("rb") as source:
            source.seek(offset)
            return [json.loads(line)["usage"] for line in source]

    def _recover_codex_turn(self, thread, saved):
        from openai_codex._run import _final_assistant_response_from_items

        marker = self._turn_context["marker"]
        for turn in reversed(thread.read(include_turns=True).thread.turns):
            matched = turn.id == saved.get("codex_turn_id")
            if not matched:
                for wrapped in turn.items:
                    item = getattr(wrapped, "root", wrapped)
                    if getattr(item, "type", None) == "userMessage" and marker in json.dumps(
                        item.model_dump(mode="json")
                    ):
                        matched = True
                        break
            if matched:
                if getattr(turn.status, "value", turn.status) == "completed":
                    return _final_assistant_response_from_items(turn.items)
                return None
        return None

    def _create_response(self, **request):
        if request.get("model") != self.player.model:
            raise ArenaError("Codex request model does not match player specification")
        effort = request.get("reasoning", {}).get("effort")
        if effort != self.player.level:
            raise ArenaError(
                "Codex request reasoning effort does not match player specification"
            )
        prompt = request.get("input")
        if not isinstance(prompt, str):
            raise ArenaError("Codex move prompt is not text")
        prompt = self.prepare_prompt(prompt)
        self._start_runtime()
        thread = self._persistent_thread()
        timed = getattr(self, "_clock", None) is not None
        usage_offset = 0
        if timed:
            saved = self._saved_turn()
            path = self._phase_dir / "openai-proxy.usage.jsonl"
            usage_offset = path.stat().st_size if path.exists() else 0
            if saved is not None:
                recovered = self._recover_codex_turn(thread, saved)
                if recovered is not None:
                    requests = self._proxy_usage_since(saved["usage_offset"])
                    saved.update(state="completed", output=recovered,
                                 usage=_sum_response_usages(requests), recovered_from_thread=True)
                    self._pending_turn = saved
                    return self._journal_response(saved)
                prompt = ("The previous execution of this request was interrupted. "
                          "Continue from your retained files and conversation, checking "
                          "existing work before repeating tool effects.\n" + prompt)
            self._pending_turn = {
                "state": "inflight", "prompt_sha256": self._turn_context["prompt_sha256"],
                "usage_offset": usage_offset,
            }
            _workspace_atomic_json(self._journal_path(), self._pending_turn)
            prompt = _insert_before_move_output_instructions(
                prompt,
                f"Request: {self._turn_context['marker']}. "
                f"Evaluation game {self.game_number}, move {self._turn_context['move']}. "
                f"Remaining game time: {self._clock.remaining:.1f} seconds. "
                + self._resource_instructions(),
            )
        try:
            result, request_usages = self._run_turn(
                thread,
                prompt,
                approval_mode=self._sdk.ApprovalMode.deny_all,
                cwd="/workspace",
                effort=self.player.level,
                model=self.player.model,
                sandbox=self._sdk.Sandbox.full_access,
            )
        except Exception as exc:
            if timed:
                proxy_requests = self._proxy_usage_since(usage_offset)
                if proxy_requests:
                    exc.arena_usage = _sum_response_usages(proxy_requests)
                if self._clock.expired:
                    raise
                if self._scope is not None and self._scope.failure_reason() == "oom-kill":
                    failure = WorkspaceResourceExceeded("agent exceeded its memory allocation")
                    failure.arena_usage = getattr(exc, "arena_usage", {})
                    raise failure from exc
            if not _workspace_codex_transport_failure(exc):
                raise
            self._restart_workspace_runtime(exc)
            wrapped = _WorkspaceCodexTransportError(str(exc))
            wrapped.__dict__.update(exc.__dict__)
            raise wrapped from exc
        counts = self._turn_usage(result)
        usage = self._response_usage(counts) | {"request_usages": request_usages}
        if timed:
            proxy_requests = self._proxy_usage_since(usage_offset)
            if proxy_requests:
                usage = _sum_response_usages(proxy_requests)
        self._log_agent_turn(result)
        return _CodexMoveResponse(result.final_response or "", usage)

    def reset_game(self):
        raise WorkspaceError("checkpoint evaluation games cannot reset their state or clock")

    def mark_complete(self):
        # Publish completion only after stopping writers and trimming/unmounting.
        # The next evaluation batch can then safely remove this image.
        self._dispose_runtime()
        self._clock.pause()
        self._volume.close()
        requests = _read_jsonl_objects(self._phase_dir / "openai-proxy.usage.jsonl", "evaluation usage")
        summary = {
            "protocol": WORKSPACE_PROTOCOL_VERSION,
            "game": self.game_number, "player": self.player_name,
            "checkpoint_id": self.checkpoint["checkpoint_id"],
            "agent_seconds": self._clock.spent,
            "remaining_seconds": self._clock.remaining,
            "model_requests": len(requests),
            "usage": _sum_response_usages([entry["usage"] for entry in requests]),
        }
        with (self.checkpoint_root / "retention.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            summary["completed_at_ns"] = time.time_ns()
            _workspace_atomic_json(self._phase_dir / "evaluation-summary.json", summary)

    @staticmethod
    def prune_evaluation_images(run_dir, player_name, keep_directories):
        """Remove previous pairs before either new evaluation image is created."""
        checkpoint_root = run_dir / "codex-checkpoints" / player_name
        checkpoint_root.mkdir(parents=True, exist_ok=True)
        with (checkpoint_root / "retention.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for marker in run_dir.glob("**/agent-workspaces/game-*/evaluation-summary.json"):
                if marker.parent in keep_directories:
                    continue
                summary = _workspace_read_json(marker)
                if (summary.get("protocol") != WORKSPACE_PROTOCOL_VERSION
                        or summary.get("player") != player_name):
                    continue
                if os.path.ismount(marker.parent / "fs"):
                    raise WorkspaceError("completed evaluation image is still mounted")
                (marker.parent / "disk.img").unlink(missing_ok=True)

    def close(self):
        try:
            try:
                self._dispose_runtime()
            finally:
                try:
                    if self._clock is not None:
                        self._clock.pause()
                finally:
                    if self._volume is not None:
                        self._volume.close()
        finally:
            lock = self._resource_lock
            if lock is not None:
                lock.close()
                self._resource_lock = None


if __name__ == "__main__":
    raise SystemExit(main())
