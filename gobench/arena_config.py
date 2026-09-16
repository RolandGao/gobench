"""Supporting arena configuration, player pools, and named run profiles.

Edit CONFIG and _FINAL_RUNS in arena.py for the default experiment and history.
Edit the pools, report exclusions, or named profiles here.
"""

from dataclasses import dataclass, replace

from gobench.strategies import KATAGO_NETWORKS
from gobench.workspace_runtime import WorkspaceSettings


@dataclass(frozen=True)
class ArenaConfig:
    """Settings intentionally edited when defining a new arena run.

    Active players receive scheduled games; opponent players are who they may face.
    The active list also determines whether the run uses KataGo or LLM execution.
    The KataGo backend independently selects the CPU or CUDA engine build.
    """

    active_players: tuple[str, ...]
    opponent_players: tuple[str, ...]
    total_games: int
    batch_games: int
    past_run_names: tuple[str, ...]
    ignore_players: tuple[str, ...] = ()
    katago_backend: str = "cpu"
    active_player_prior_elo_mean: float = 0.0
    active_player_prior_elo_sd: float = 10_000.0
    katago_gain_top_p: float = 1.0
    workspace: WorkspaceSettings = WorkspaceSettings()


# Temperature variants present in the canonical 2026-08-10 arena report.
_TEMPERATURE_PLAYER_POOL = (
    "kata1-b6c96-s16525312-d2925067-temp-0.5",
    "kata1-b6c96-s14649344-d2727367-temp-0.3",
    "kata1-b6c96-s16525312-d2925067-temp-0.7",
    "kata1-b6c96-s13733120-d2631546-temp-0.3",
    "kata1-b6c96-s13733120-d2631546-temp-0.5",
    "kata1-b6c96-s12849664-d2510774-temp-0.5",
    "kata1-b6c96-s11888896-d2416753-temp-0.5",
    "kata1-b6c96-s14649344-d2727367-temp-0.9",
    "kata1-b6c96-s10014464-d2201128-temp-0.3",
    "kata1-b6c96-s13733120-d2631546-temp-0.9",
    "kata1-b6c96-s8982784-d2082583-temp-0.3",
    "kata1-b6c96-s8080640-d1961030-temp-0.3",
    "kata1-b6c96-s8982784-d2082583-temp-0.5",
    "kata1-b6c96-s8080640-d1961030-temp-0.5",
    "kata1-b6c96-s8982784-d2082583-temp-0.7",
    "kata1-b6c96-s10014464-d2201128-temp-0.9",
    "kata1-b6c96-s8080640-d1961030-temp-0.7",
    "kata1-b6c96-s4136960-d1510003-temp-0.3",
    "kata1-b6c96-s5214720-d1690538-temp-0.5",
    "kata1-b6c96-s4136960-d1510003-temp-0.5",
    "kata1-b6c96-s5214720-d1690538-temp-0.7",
    "kata1-b6c96-s6127360-d1754797-temp-0.9",
    "kata1-b6c96-s4136960-d1510003-temp-0.7",
    "kata1-b6c96-s4136960-d1510003-temp-0.9",
    "kata1-b6c96-s1995008-d1329786-temp-0.3",
    "kata1-b6c96-s938496-d1208807-temp-0.3",
    "kata1-b6c96-s1995008-d1329786-temp-0.9",
    "kata1-b6c96-s1248000-d550347-temp-0.3",
)


# Canonical KataGo opponent pool from the 2026-08-10 arena report: all KataGo
# players except zhizi, including the fixed random anchor.
_CURRENT_PLAYER_POOL = (
    "kata1-random",
    *(
        network.name
        for network in KATAGO_NETWORKS
        if network.name != "kata1-zhizi-b40c768nbt-fdx6c"
    ),
    *_TEMPERATURE_PLAYER_POOL,
    "kata1-b28c512nbt-s12313658112-d5687582971-playouts60",
    "kata1-b28c512nbt-s12313658112-d5687582971-playouts600",
    "kata1-b28c512nbt-s8566598912-d4691918754-playouts60",
    "kata1-b28c512nbt-s8566598912-d4691918754-playouts600",
    "kata1-b28c512nbt-s7229617920-d4333415784-playouts60",
    "kata1-b28c512nbt-s7229617920-d4333415784-playouts600",
    "kata1-b18c384nbt-s9761732864-d4253420187-playouts60",
    "kata1-b18c384nbt-s9761732864-d4253420187-playouts600",
)


_NO_MULTI_PLAYOUT_PLAYER_POOL = tuple(
    name for name in _CURRENT_PLAYER_POOL if "-playouts" not in name
)

_CHEAP_B6C96_PLAYER_POOL = tuple(
    name for name in _CURRENT_PLAYER_POOL if name.startswith("kata1-b6c96-")
)

_MULTI_PLAYOUT_PLAYER_POOL = tuple(
    name for name in _CURRENT_PLAYER_POOL if "-playouts" in name
)


def _llm_player_name(model, agentic_harness="api"):
    """Return the canonical model-agentic-harness player name."""
    return f"{model}-{agentic_harness}"


_OPENROUTER_PLAYERS = (
    _llm_player_name("qwen3.8-max-high"),
    _llm_player_name("kimi-k3-high"),
    _llm_player_name("muse-spark-1.2-openrouter-high"),
)


_CODEX_TRAINING_SECONDS = {
    f"codex-{hours}h": hours * 3600 for hours in (0, 1, 2, 4, 8)
}
_CODEX_WORKSPACE_HARNESSES = frozenset(_CODEX_TRAINING_SECONDS)
_CODEX_WORKSPACE_PLAYERS = {
    harness: tuple(
        _llm_player_name(f"{model}-{effort}", harness)
        for model in ("gpt5.6-sol", "gpt5.6-luna")
        for effort in ("low", "high", "max")
    )
    for harness in _CODEX_TRAINING_SECONDS
}


_IGNORED_REPORT_PLAYERS = (
    "gpt5.6-sol-low-codex-single",
    "gpt5.6-luna-max-codex-single",
    "gpt5.6-luna-low-codex-single",
    "gpt5.6-luna-high-codex-single",
    "qwen3.8-max-high-api",
)


def build_run_types(past_run_names):
    """Build named profiles using the historical runs selected in arena.py."""

    def _llm_run_config(active_players, *, total_games=14):
        """Shared defaults for the paired-color LLM experiment profiles."""
        return ArenaConfig(
            active_players=active_players,
            opponent_players=_CURRENT_PLAYER_POOL,
            total_games=total_games,
            batch_games=2,
            past_run_names=past_run_names,
            ignore_players=_IGNORED_REPORT_PLAYERS,
            active_player_prior_elo_mean=1000.0,
            active_player_prior_elo_sd=2000.0,
        )

    # Every selectable profile is an ArenaConfig defined here. Filtered selections
    # are available as _CHEAP_B6C96_PLAYER_POOL, _NO_MULTI_PLAYOUT_PLAYER_POOL, and
    # _MULTI_PLAYOUT_PLAYER_POOL.
    return {
        "katago_only": ArenaConfig(
            active_players=tuple(
                name for name in _CURRENT_PLAYER_POOL if name != "kata1-random"
            ),
            opponent_players=_CURRENT_PLAYER_POOL,
            total_games=100000,
            batch_games=4000,
            past_run_names=(),
            ignore_players=_IGNORED_REPORT_PLAYERS,
        ),
        "katago_cheap_only": ArenaConfig(
            active_players=_CHEAP_B6C96_PLAYER_POOL,
            opponent_players=("kata1-random", *_CHEAP_B6C96_PLAYER_POOL),
            total_games=500,
            batch_games=250,
            past_run_names=(),
            ignore_players=_IGNORED_REPORT_PLAYERS,
        ),
        "katago_cheap_and_medium": ArenaConfig(
            active_players=tuple(
                name for name in _NO_MULTI_PLAYOUT_PLAYER_POOL if name != "kata1-random"
            ),
            opponent_players=_NO_MULTI_PLAYOUT_PLAYER_POOL,
            total_games=500,
            batch_games=250,
            past_run_names=past_run_names,
            ignore_players=_IGNORED_REPORT_PLAYERS,
        ),
        "60_and_600_playouts_katago": ArenaConfig(
            active_players=_MULTI_PLAYOUT_PLAYER_POOL,
            opponent_players=_CURRENT_PLAYER_POOL,
            total_games=20000,
            batch_games=2000,
            past_run_names=past_run_names,
            ignore_players=_IGNORED_REPORT_PLAYERS,
            active_player_prior_elo_mean=4200.0,
            active_player_prior_elo_sd=500.0,
            katago_gain_top_p=0.95,
            katago_backend="cuda",
        ),
        "one_llm": _llm_run_config(("gpt-5.4-low-api",)),
        "many_llm": _llm_run_config(("gpt-5.4-low-api", "gpt5.6-sol-low-api")),
        **{
            harness: replace(
                _llm_run_config(players),
                workspace=WorkspaceSettings(
                    training_seconds=_CODEX_TRAINING_SECONDS[harness]
                ),
            )
            for harness, players in _CODEX_WORKSPACE_PLAYERS.items()
        },
        "result_aggregation": _llm_run_config(_OPENROUTER_PLAYERS, total_games=0),
    }
