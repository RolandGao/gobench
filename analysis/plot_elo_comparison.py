#!/usr/bin/env python3
"""Plot cost efficiency as a compact two-panel paper figure."""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter

from gobench.paths import ROOT

DEFAULT_KATAGO_RATINGS = None
DEFAULT_KATAGO_BENCHMARK = ROOT / "log" / "katago_selfplay_benchmark.json"
DEFAULT_LLM_RESULTS = (
    ROOT / "data" / "paper_results.json"
)
DEFAULT_CPU_COST_PER_SECOND = 0.071 / 3600
DEFAULT_OUTPUT = ROOT / "paper" / "elo_efficiency_panels.pdf"
DEFAULT_LLM_ONLY_OUTPUT = (
    ROOT / "paper" / "llm_elo_efficiency_panels.pdf"
)
DEFAULT_CONTEXT_OUTPUT = ROOT / "paper" / "sol_context_comparison.pdf"
PAPER_EXCLUDED_LLM_PLAYERS = frozenset(
    {
        "qwen3.8-max-high",
        "codex-luna-max-single",
        "codex-sol-high-context",
        "codex-sol-max-context",
        "codex-luna-high-context",
        "codex-luna-max-context",
        "codex-luna-high-workspace",
    }
)
LLM_STYLES = {
    "opus-5-high": ("#A65A3A", "o"),
    "gemini-3.1-pro-high": ("#4285F4", "s"),
    "gemini-3.6-flash-high": ("#4285F4", "v"),
    "gpt5.6-sol-high": ("#10A37F", "^"),
    "gpt5.6-sol-low": ("#10A37F", "D"),
    "gpt5.6-sol-high-context": ("#087F5B", "s"),
    "gpt5.6-sol-max-context": ("#087F5B", "P"),
    "gpt5.6-luna-high": ("#6D5BD0", "^"),
    "gpt5.6-luna-low": ("#6D5BD0", "D"),
    "gpt-5.4-low": ("#10A37F", "P"),
    "grok-4.5-high": ("#202124", "X"),
    "DeepSeek-V4-Flash-0731-high": ("#6246EA", "<"),
    "kimi-k3-high": ("#F59E0B", "h"),
    "muse-spark-1.2-openrouter-high": ("#EC4899", "*"),
    "qwen3.8-max-high": ("#7C3AED", ">"),
}
DEFAULT_LLM_STYLE = ("#6B7280", "o")

KATAGO_ROW = re.compile(
    r"^\|\s*`(?P<name>[^`]+)`\s*"
    r"\|\s*(?P<elo>-?\d+(?:\.\d+)?)\s*"
    r"\|\s*(?P<games>[\d,]+)\s*"
    r"\|\s*(?P<seconds>\d+(?:\.\d+)?)\s*\|$"
)
LLM_TIME_ROW = re.compile(
    r"^\s*\d+(?:-\d+)?\s+"
    r"(?P<name>\S+)\s+"
    r"(?P<elo>-?\d+(?:\.\d+)?)\s+"
    r"(?:±|\+/-)\s*(?P<ci>\d+(?:\.\d+)?)\s+"
    r"(?P<games>\d+)\s+"
    r"(?P<moves>\d+)\s+"
    r"\d+/\d+\s+"
    r"\d+/\d+\s+"
    r"(?P<seconds>\d+(?:\.\d+)?)s(?:\s+|$)"
)
LLM_COST_ROW = re.compile(
    r"^\s*\d+(?:-\d+)?\s+"
    r"(?P<name>\S+)\s+"
    r"(?P<elo>-?\d+(?:\.\d+)?)\s+"
    r"(?:±|\+/-)\s*(?P<ci>\d+(?:\.\d+)?)\s+"
    r"(?P<games>\d+)\s+"
    r"(?P<moves>\d+)\s+"
    r"\d+/\d+\s+"
    r"\d+/\d+\s+"
    r"\d+(?:\.\d+)?s\s+"
    r"\$\d+(?:\.\d+)?\s+"
    r"\$(?P<cost>\d+(?:\.\d+)?)\s*$"
)


@dataclass(frozen=True)
class PlayerTiming:
    name: str
    elo: float
    games: int
    seconds_per_move: float
    elo_ci: float | None = None


@dataclass(frozen=True)
class PlayerCost:
    name: str
    elo: float
    cost_per_move: float
    elo_ci: float | None = None


def _llm_rows(data: dict[str, object]) -> list[dict[str, object]]:
    datasets = data.get("datasets")
    if isinstance(datasets, dict):
        rows = datasets.get("llm_players", [])
    else:
        rows = data.get("llm_comparisons", [])
    if not isinstance(rows, list):
        raise ValueError("LLM results must be a list")
    return rows


def parse_katago_speed(path: Path) -> list[PlayerTiming]:
    """Read KataGo Elo and seconds-per-game values from a Markdown table."""
    players = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = KATAGO_ROW.match(line)
        if match:
            players.append(
                PlayerTiming(
                    name=match["name"],
                    elo=float(match["elo"]),
                    games=int(match["games"].replace(",", "")),
                    seconds_per_move=float(match["seconds"]),
                )
            )
    if not players:
        raise ValueError(f"No KataGo rows found in {path}")
    return players


def parse_isolated_katago_results(
    benchmark_path: Path,
    ratings_path: Path | None = None,
) -> list[PlayerTiming]:
    """Read aggregate per-move timings, with optional rating-table fallback."""
    ratings = (
        {player.name: player for player in parse_katago_speed(ratings_path)}
        if ratings_path is not None
        else {}
    )
    data = json.loads(benchmark_path.read_text(encoding="utf-8"))
    results = data.get("results", [])
    by_name = {result.get("player"): result for result in results}
    players = []
    for result in results:
        name = result.get("player") or result.get("network")
        if not isinstance(name, str):
            raise ValueError(f"Missing player name in benchmark row: {result!r}")
        estimate = result.get("cpu_estimate")
        if isinstance(estimate, dict):
            base_name = estimate.get("base_player")
            timing_result = by_name.get(base_name)
            multiplier = estimate.get("playout_multiplier")
            if not isinstance(timing_result, dict):
                raise ValueError(f"Missing base timing row {base_name!r} for {name}")
            if not isinstance(multiplier, (int, float)) or multiplier <= 0:
                raise ValueError(f"Invalid playout multiplier for {name}")
        else:
            timing_result, multiplier = result, 1
        timings = timing_result.get("game_timings", [])
        if not isinstance(timings, list) or not timings:
            raise ValueError(f"Missing isolated game timings for {name}")
        total_seconds = sum(float(game["total_genmove_seconds"]) for game in timings)
        total_moves = sum(int(game["moves"]) for game in timings)
        if total_seconds <= 0 or total_moves <= 0:
            raise ValueError(f"Invalid isolated move timing for {name}")
        elo = result.get("elo")
        if not isinstance(elo, (int, float)):
            if name not in ratings:
                raise ValueError(f"Missing KataGo rating for benchmark row {name!r}")
            elo = ratings[name].elo
        elo_ci = result.get("elo_ci_95")
        if elo_ci is None and name in ratings:
            elo_ci = ratings[name].elo_ci
        players.append(
            PlayerTiming(
                name=name,
                elo=float(elo),
                elo_ci=float(elo_ci) if elo_ci is not None else None,
                games=int(result.get("arena_games", result["games"])),
                seconds_per_move=total_seconds / total_moves * float(multiplier),
            )
        )
    if not players:
        raise ValueError(f"No isolated KataGo results found in {benchmark_path}")
    return players


def parse_llm_results(path: Path) -> list[PlayerTiming]:
    """Read LLM Elo, confidence interval, and API seconds per move."""
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        players = [
            PlayerTiming(
                name=str(row["player"]),
                elo=float(row["elo"]),
                elo_ci=float(row["elo_ci_95"]),
                games=int(row["games"]),
                seconds_per_move=float(row["api_seconds_per_move"]),
            )
            for row in _llm_rows(data)
        ]
        if not players:
            raise ValueError(f"No LLM timing rows found in {path}")
        return players
    players = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LLM_TIME_ROW.match(line)
        if match:
            players.append(
                PlayerTiming(
                    name=match["name"],
                    elo=float(match["elo"]),
                    elo_ci=float(match["ci"]),
                    games=int(match["games"]),
                    seconds_per_move=float(match["seconds"]),
                )
            )
    if not players:
        raise ValueError(f"No LLM timing rows found in {path}")
    return players


def parse_llm_costs(path: Path) -> list[PlayerCost]:
    """Read LLM Elo, confidence interval, and measured API cost per move."""
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        players = [
            PlayerCost(
                name=str(row["player"]),
                elo=float(row["elo"]),
                elo_ci=float(row["elo_ci_95"]),
                cost_per_move=float(row["cost_usd_per_move"]),
            )
            for row in _llm_rows(data)
        ]
        if not players:
            raise ValueError(f"No LLM cost rows found in {path}")
        return players
    players = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LLM_COST_ROW.match(line)
        if match:
            players.append(
                PlayerCost(
                    name=match["name"],
                    elo=float(match["elo"]),
                    elo_ci=float(match["ci"]),
                    cost_per_move=float(match["cost"]),
                )
            )
    if not players:
        raise ValueError(f"No LLM cost rows found in {path}")
    return players


def format_seconds_tick(value: float, _position: float) -> str:
    if value >= 1000:
        return f"{value / 1000:g}k"
    if value >= 1:
        return f"{value:g}"
    return f"{value:.1g}"


def format_cost_power(value: float, _position: float) -> str:
    if value <= 0:
        return ""
    exponent = int(round(math.log10(value)))
    return rf"$10^{{{exponent}}}$"


def style_axes(ax: plt.Axes) -> None:
    ax.set_xscale("log")
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.grid(True, which="major", color="#D5DAE0", linewidth=0.7)
    ax.grid(True, which="minor", axis="x", color="#E9ECEF", linewidth=0.4)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", which="both", length=0, labelsize=6.2)


def draw_time_panel(
    ax: plt.Axes,
    katago_players: list[PlayerTiming],
    llm_players: list[PlayerTiming],
    *,
    katago_reference_only: bool = False,
    title: str = "(a) Time per move",
) -> None:
    if katago_reference_only:
        top_katago_elo = max(player.elo for player in katago_players)
        ax.axhline(
            top_katago_elo,
            color="#7A8491",
            linestyle="--",
            linewidth=1.1,
            label=f"KataGo ({top_katago_elo:.0f} Elo)",
            zorder=2,
        )
    else:
        ax.scatter(
            [player.seconds_per_move for player in katago_players],
            [player.elo for player in katago_players],
            s=13,
            color="#9AA3AD",
            edgecolor="white",
            linewidth=0.35,
            alpha=0.78,
            label=f"KataGo ({len(katago_players)})",
            zorder=2,
        )
    for player in llm_players:
        color, marker = LLM_STYLES.get(player.name, DEFAULT_LLM_STYLE)
        ax.errorbar(
            player.seconds_per_move,
            player.elo,
            yerr=player.elo_ci,
            fmt=marker,
            markersize=4.5,
            capsize=2,
            elinewidth=0.9,
            color=color,
            markeredgecolor="white",
            markeredgewidth=0.55,
            label=player.name,
            zorder=4,
        )
    style_axes(ax)
    if katago_reference_only:
        llm_seconds = [player.seconds_per_move for player in llm_players]
        ax.set_xlim(min(llm_seconds) * 0.8, max(llm_seconds) * 1.25)
        ax.xaxis.set_major_locator(FixedLocator([1e3, 2e3, 5e3]))
    else:
        ax.set_xlim(left=0.1)
    ax.xaxis.set_major_formatter(FuncFormatter(format_seconds_tick))
    ax.set_title(title, fontsize=7.8, pad=3)
    ax.set_xlabel("Seconds (log scale)", fontsize=6.8)
    ax.set_ylabel("Elo", fontsize=7)


def draw_cost_panel(
    ax: plt.Axes,
    katago_players: list[PlayerCost],
    llm_players: list[PlayerCost],
    *,
    katago_reference_only: bool = False,
    title: str = "(b) Cost per move",
) -> None:
    if katago_reference_only:
        ax.axhline(
            max(player.elo for player in katago_players),
            color="#7A8491",
            linestyle="--",
            linewidth=1.1,
            label=f"KataGo ({max(player.elo for player in katago_players):.0f} Elo)",
            zorder=2,
        )
    else:
        ax.scatter(
            [player.cost_per_move for player in katago_players],
            [player.elo for player in katago_players],
            s=13,
            color="#9AA3AD",
            edgecolor="white",
            linewidth=0.35,
            alpha=0.78,
            label=f"KataGo ({len(katago_players)})",
            zorder=2,
        )
    for player in llm_players:
        color, marker = LLM_STYLES.get(player.name, DEFAULT_LLM_STYLE)
        ax.errorbar(
            player.cost_per_move,
            player.elo,
            yerr=player.elo_ci,
            fmt=marker,
            markersize=4.5,
            capsize=2,
            elinewidth=0.9,
            color=color,
            markeredgecolor="white",
            markeredgewidth=0.55,
            label=player.name,
            zorder=4,
        )
    style_axes(ax)
    if katago_reference_only:
        llm_costs = [player.cost_per_move for player in llm_players]
        ax.set_xlim(min(llm_costs) * 0.8, max(llm_costs) * 1.25)
        ax.xaxis.set_major_locator(FixedLocator([0.02, 0.05, 0.1, 0.2]))
        ax.xaxis.set_major_formatter(
            FuncFormatter(lambda value, _position: f"${value:g}")
        )
    else:
        ax.set_xlim(
            left=min(player.cost_per_move for player in katago_players) * 0.7
        )
        ax.xaxis.set_major_locator(FixedLocator([1e-7, 1e-5, 1e-3, 1e-1]))
        ax.xaxis.set_major_formatter(FuncFormatter(format_cost_power))
    ax.set_title(title, fontsize=7.8, pad=3)
    ax.set_xlabel("Cost, USD (log scale)", fontsize=6.8)


def plot(
    katago_timings: list[PlayerTiming],
    llm_timings: list[PlayerTiming],
    katago_costs: list[PlayerCost],
    llm_costs: list[PlayerCost],
    output: Path,
    *,
    katago_reference_only: bool = False,
) -> None:
    fig = plt.figure(figsize=(5.5, 2.8))
    grid = fig.add_gridspec(1, 2)
    time_ax = fig.add_subplot(grid[0, 0])
    cost_ax = fig.add_subplot(grid[0, 1], sharey=time_ax)
    draw_time_panel(
        time_ax,
        katago_timings,
        llm_timings,
        katago_reference_only=katago_reference_only,
    )
    draw_cost_panel(
        cost_ax,
        katago_costs,
        llm_costs,
        katago_reference_only=katago_reference_only,
    )
    if katago_reference_only:
        time_ax.set_ylim(bottom=0)
    cost_ax.tick_params(labelleft=False)

    handles, labels = time_ax.get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="center right",
        bbox_to_anchor=(0.995, 0.54),
        ncol=1,
        frameon=True,
        framealpha=0.96,
        fontsize=5.6,
        handletextpad=0.3,
        borderpad=0.4,
        labelspacing=0.25,
    )
    fig.subplots_adjust(
        left=0.06,
        right=0.785,
        bottom=0.20,
        top=0.88,
        wspace=0.15,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        output,
        dpi=300,
        bbox_inches="tight",
        pad_inches=0.01,
    )
    plt.close(fig)


def add_legend(
    fig: plt.Figure,
    ax: plt.Axes,
) -> None:
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.01),
        ncol=3,
        frameon=True,
        framealpha=0.96,
        fontsize=5.2,
        handletextpad=0.3,
        borderpad=0.4,
        labelspacing=0.2,
        columnspacing=0.8,
    )


def plot_combined(
    katago_timings: list[PlayerTiming],
    llm_timings: list[PlayerTiming],
    katago_costs: list[PlayerCost],
    llm_costs: list[PlayerCost],
    output: Path,
) -> None:
    fig = plt.figure(figsize=(5.5, 2.8))
    grid = fig.add_gridspec(1, 2)

    all_cost_ax = fig.add_subplot(grid[0, 0])
    llm_cost_ax = fig.add_subplot(grid[0, 1])

    draw_cost_panel(
        all_cost_ax,
        katago_costs,
        llm_costs,
        title="(a) All players: cost per move",
    )
    draw_cost_panel(
        llm_cost_ax,
        katago_costs,
        llm_costs,
        katago_reference_only=True,
        title="(b) LLMs only: cost per move",
    )

    llm_cost_ax.set_ylim(bottom=0)

    add_legend(fig, all_cost_ax)
    fig.subplots_adjust(
        left=0.07,
        right=0.99,
        bottom=0.29,
        top=0.88,
        wspace=0.15,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=300, bbox_inches="tight", pad_inches=0.01)
    plt.close(fig)


def plot_context_comparison(results_path: Path, output: Path) -> None:
    data = json.loads(results_path.read_text(encoding="utf-8"))
    datasets = data.get("datasets")
    if not isinstance(datasets, dict):
        raise ValueError("Context comparison requires the paper results snapshot")
    rows = datasets.get("context_comparison_players")
    if not isinstance(rows, list) or len(rows) != 4:
        raise ValueError("Expected four context-comparison players")

    fig, ax = plt.subplots(figsize=(5.5, 2.45))
    series = (
        ("Standard prompt", rows[:2], "#10A37F", "--", ("D", "^")),
        ("Full context", rows[2:], "#087F5B", "-", ("s", "P")),
    )
    annotation_styles = {
        "gpt5.6-sol-low": ((5, -13), "left"),
        "gpt5.6-sol-high": ((-5, 5), "right"),
        "gpt5.6-sol-high-context": ((5, 5), "left"),
        "gpt5.6-sol-max-context": ((5, 5), "left"),
    }
    for label, series_rows, color, linestyle, markers in series:
        costs = [float(row["cost_usd_per_move"]) for row in series_rows]
        elos = [float(row["elo"]) for row in series_rows]
        ax.plot(
            costs,
            elos,
            color=color,
            linestyle=linestyle,
            linewidth=1.1,
            alpha=0.8,
            label=label,
            zorder=2,
        )
        for row, marker in zip(series_rows, markers):
            cost = float(row["cost_usd_per_move"])
            elo = float(row["elo"])
            ax.errorbar(
                cost,
                elo,
                yerr=float(row["elo_ci_95"]),
                fmt=marker,
                markersize=6.2,
                capsize=3,
                elinewidth=1.1,
                color=color,
                markeredgecolor="white",
                markeredgewidth=0.6,
                zorder=3,
            )
            offset, alignment = annotation_styles[str(row["player"])]
            short_name = str(row["player"]).removeprefix("gpt5.6-")
            ax.annotate(
                f"{short_name} ({elo:.0f})",
                (cost, elo),
                xytext=offset,
                textcoords="offset points",
                ha=alignment,
                va="bottom",
                fontsize=6.3,
            )

    ax.set_xscale("log")
    ax.set_xlim(0.035, 0.31)
    ax.xaxis.set_major_locator(FixedLocator([0.04, 0.05, 0.1, 0.2, 0.3]))
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda value, _position: f"${value:g}")
    )
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("Cost per move, USD (log scale)", fontsize=6.8)
    ax.set_ylabel("Elo", fontsize=7)
    ax.set_ylim(bottom=1000)
    ax.grid(True, which="major", color="#D5DAE0", linewidth=0.7)
    ax.grid(True, which="minor", axis="x", color="#E9ECEF", linewidth=0.4)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", which="both", length=0, labelsize=6.2)
    ax.legend(loc="lower right", frameon=True, fontsize=6.2)
    fig.subplots_adjust(left=0.09, right=0.99, bottom=0.18, top=0.96)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=300, bbox_inches="tight", pad_inches=0.01)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--katago-ratings",
        type=Path,
        default=DEFAULT_KATAGO_RATINGS,
    )
    parser.add_argument(
        "--katago-benchmark",
        type=Path,
        default=DEFAULT_KATAGO_BENCHMARK,
    )
    parser.add_argument(
        "--llm-results",
        type=Path,
        default=DEFAULT_LLM_RESULTS,
    )
    parser.add_argument(
        "--cpu-cost-per-second",
        type=float,
        default=DEFAULT_CPU_COST_PER_SECOND,
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="output image (selected automatically when omitted)",
    )
    parser.add_argument(
        "--llm-only",
        action="store_true",
        help="plot only LLMs plus the top KataGo Elo reference line",
    )
    parser.add_argument(
        "--context-comparison",
        action="store_true",
        help="plot the four standard/context gpt5.6-sol configurations",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.cpu_cost_per_second <= 0:
        raise ValueError("--cpu-cost-per-second must be positive")

    if args.context_comparison:
        output = args.output or DEFAULT_CONTEXT_OUTPUT
        plot_context_comparison(args.llm_results, output)
        print(f"Saved {output} (4 gpt5.6-sol configurations)")
        return

    katago_timings = parse_isolated_katago_results(
        args.katago_benchmark,
        args.katago_ratings,
    )
    llm_timings = [
        player
        for player in parse_llm_results(args.llm_results)
        if player.name not in PAPER_EXCLUDED_LLM_PLAYERS
    ]
    katago_costs = [
        PlayerCost(
            name=player.name,
            elo=player.elo,
            cost_per_move=player.seconds_per_move * args.cpu_cost_per_second,
        )
        for player in katago_timings
    ]
    llm_costs = [
        player
        for player in parse_llm_costs(args.llm_results)
        if player.name not in PAPER_EXCLUDED_LLM_PLAYERS
    ]
    output = args.output or (
        DEFAULT_LLM_ONLY_OUTPUT if args.llm_only else DEFAULT_OUTPUT
    )
    if args.llm_only:
        plot(
            katago_timings,
            llm_timings,
            katago_costs,
            llm_costs,
            output,
            katago_reference_only=True,
        )
    else:
        plot_combined(
            katago_timings,
            llm_timings,
            katago_costs,
            llm_costs,
            output,
        )
    print(
        f"Saved {output} "
        f"({len(katago_timings)} KataGo players, {len(llm_timings)} LLM players)"
    )


if __name__ == "__main__":
    main()
