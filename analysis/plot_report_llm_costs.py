#!/usr/bin/env python3
"""Plot LLM Elo against measured cost per move from an arena report."""

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
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter

from gobench.paths import ROOT


DEFAULT_REPORT = (
    ROOT / "log" / "arena_20260830_062108_941863_ed7548b9" / "report.md"
)
DEFAULT_PAPER_RESULTS = ROOT / "data" / "paper_results.json"
DEFAULT_API_OUTPUT = ROOT / "paper" / "api_llm_elo_vs_cost.pdf"
DEFAULT_SOL_OUTPUT = (
    ROOT / "paper" / "gpt5_6_sol_api_and_harnesses_elo_vs_cost.pdf"
)
PAPER_FONT_SIZE = 10
MODEL_LABEL_FONT_SIZE = 5

ROW = re.compile(
    r"^\s*\d+(?:-\d+)?\s+"
    r"(?P<name>\S+)\s+"
    r"(?P<elo>-?\d+(?:\.\d+)?)\s+"
    r"(?:±|\+/-)\s*(?P<ci>\d+(?:\.\d+)?)\s+"
    r"(?P<games>\d+)\s+"
    r"(?P<moves>\d+)\s+"
    r"\d+/\d+\s+"
    r"\d+/\d+\s+"
    r"\d+(?:\.\d+)?s\s+"
    r"\$(?P<total_cost>\d+(?:\.\d+)?)\s+"
    r"\$(?P<cost_per_move>\d+(?:\.\d+)?)\s*$"
)


@dataclass(frozen=True)
class Result:
    name: str
    elo: float
    ci: float
    games: int
    moves: int
    cost_per_move: float


@dataclass(frozen=True)
class KataGoResult:
    name: str
    elo: float
    ci: float
    cost_per_move: float


def report_section(text: str, heading: str) -> str:
    """Return one level-two Markdown section, excluding its heading."""
    marker = f"## {heading}"
    try:
        section = text.split(marker, 1)[1]
    except IndexError as error:
        raise ValueError(f"Missing report section: {heading}") from error
    return section.split("\n## ", 1)[0]


def parse_results(section: str) -> list[Result]:
    results = []
    for line in section.splitlines():
        match = ROW.match(line)
        if not match:
            continue
        results.append(
            Result(
                name=match["name"],
                elo=float(match["elo"]),
                ci=float(match["ci"]),
                games=int(match["games"]),
                moves=int(match["moves"]),
                cost_per_move=float(match["cost_per_move"]),
            )
        )
    if not results:
        raise ValueError("No LLM result rows found")
    return results


def parse_katago_results(path: Path) -> list[KataGoResult]:
    """Read the paper's KataGo Elo and measured/estimated CPU costs."""
    data = json.loads(path.read_text(encoding="utf-8"))
    datasets = data.get("datasets")
    rows = datasets.get("katago_players") if isinstance(datasets, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"No KataGo player rows found in {path}")
    return [
        KataGoResult(
            name=str(row["player"]),
            elo=float(row["elo"]),
            ci=float(row["elo_ci_95"]),
            cost_per_move=float(row["cost_usd_per_move"]),
        )
        for row in rows
        if row.get("cost_usd_per_move") is not None
    ]


def cost_tick(value: float, _position: float) -> str:
    return f"${value:g}"


def cost_power_tick(value: float, _position: float) -> str:
    if value <= 0:
        return ""
    exponent = int(round(math.log10(value)))
    return rf"$10^{{{exponent}}}$"


def style_axes(
    ax: plt.Axes,
    *,
    xlim: tuple[float, float],
    ticks: list[float] | None = None,
    formatter: FuncFormatter | None = None,
) -> None:
    ax.set_xscale("log")
    ax.set_xlim(*xlim)
    ax.xaxis.set_major_locator(
        FixedLocator(ticks or [0.03, 0.05, 0.1, 0.2, 0.4])
    )
    ax.xaxis.set_major_formatter(formatter or FuncFormatter(cost_tick))
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("Cost per move (USD, log scale)", fontsize=PAPER_FONT_SIZE)
    ax.set_ylabel("Elo", fontsize=PAPER_FONT_SIZE)
    ax.grid(True, which="major", color="#D5DAE0", linewidth=0.7)
    ax.grid(True, which="minor", axis="x", color="#E9ECEF", linewidth=0.4)
    ax.set_axisbelow(True)
    ax.tick_params(
        axis="both", which="both", length=0, labelsize=PAPER_FONT_SIZE
    )
    for spine in ax.spines.values():
        spine.set_color("#9AA3AD")
        spine.set_linewidth(0.6)


def errorbar(
    ax: plt.Axes,
    result: Result,
    *,
    color: str,
    marker: str,
    markersize: float = 5.8,
) -> None:
    ax.errorbar(
        result.cost_per_move,
        result.elo,
        yerr=result.ci,
        fmt=marker,
        markersize=markersize,
        capsize=2.5,
        elinewidth=0.9,
        capthick=0.9,
        color=color,
        markeredgecolor="white",
        markeredgewidth=0.65,
        zorder=3,
    )


API_STYLE = {
    "opus-5-high-api": "#A65A3A",
    "gemini-3.1-pro-high-api": "#4285F4",
    "DeepSeek-V4-Flash-0731-high-api": "#6246EA",
    "kimi-k3-high-api": "#F59E0B",
    "gpt5.6-sol-high-api": "#10A37F",
    "muse-spark-1.2-openrouter-high-api": "#EC4899",
    "grok-4.5-high-api": "#202124",
    "gemini-3.6-flash-high-api": "#4285F4",
}

API_LABEL = {
    "opus-5-high-api": "Opus 5",
    "gemini-3.1-pro-high-api": "Gemini 3.1 Pro",
    "DeepSeek-V4-Flash-0731-high-api": "DeepSeek V4 Flash",
    "kimi-k3-high-api": "Kimi K3",
    "gpt5.6-sol-high-api": "GPT-5.6 Sol",
    "muse-spark-1.2-openrouter-high-api": "Muse Spark 1.2",
    "grok-4.5-high-api": "Grok 4.5",
    "gemini-3.6-flash-high-api": "Gemini 3.6 Flash",
}

# Offsets are in display points. They keep nearby confidence intervals legible.
API_OFFSET = {
    "opus-5-high-api": (-3, 3, "right"),
    "gemini-3.1-pro-high-api": (-3, 3, "right"),
    "DeepSeek-V4-Flash-0731-high-api": (3, 1, "left"),
    "kimi-k3-high-api": (-4, 0, "right"),
    "gpt5.6-sol-high-api": (4, 6, "left"),
    "muse-spark-1.2-openrouter-high-api": (4, -4, "left"),
    "grok-4.5-high-api": (4, 2, "left"),
    "gemini-3.6-flash-high-api": (4, -6, "left"),
}


# Multi-turn API model families: (display label, color). Shared with other plots.
API_MODEL_LABELS = {
    "gpt6-astra": ("GPT-6 Astra", "#007C91"),
    "gpt5.6-sol": ("GPT-5.6 Sol", "#159447"),
    "gpt5.6-luna": ("GPT-5.6 Luna", "#9467BD"),
    "opus-5": ("Opus 5", "#A65A3A"),
    "gemini-3.1-pro": ("Gemini 3.1 Pro", "#173B85"),
    "gemini-3.8-flash": ("Gemini 3.8 Flash", "#3985D0"),
    "gemini-3.6-flash": ("Gemini 3.6 Flash", "#84B8E6"),
    "DeepSeek-V4.1-Flash": ("DeepSeek V4.1 Flash", "#DB8C00"),
    "DeepSeek-V4-Flash-0731": ("DeepSeek V4 Flash 0731", "#746042"),
    "muse-spark-1.3-contributor": ("Muse Spark 1.3", "#CB3586"),
    "grok-4.6": ("Grok 4.6", "#30343A"),
}
API_EFFORT_MARKERS = {"high": "D", "xhigh": "s", "max": "p"}


def plot_api(
    results: list[Result],
    katago_results: list[KataGoResult],
    output: Path,
) -> None:
    expected = set(API_STYLE)
    actual = {result.name for result in results}
    if actual != expected:
        raise ValueError(
            "Unexpected API-only rows: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )

    # Match the NeurIPS text width so LaTeX does not scale the fonts.
    fig = plt.figure(figsize=(5.5, 2.2))
    grid = fig.add_gridspec(1, 2, width_ratios=(0.9, 1.1))
    all_ax = fig.add_subplot(grid[0, 0])
    api_ax = fig.add_subplot(grid[0, 1])

    all_ax.scatter(
        [result.cost_per_move for result in katago_results],
        [result.elo for result in katago_results],
        s=11,
        color="#9AA3AD",
        edgecolor="white",
        linewidth=0.35,
        alpha=0.8,
        zorder=2,
    )
    for result in results:
        errorbar(all_ax, result, color=API_STYLE[result.name], marker="D")
        errorbar(api_ax, result, color=API_STYLE[result.name], marker="D")
        dx, dy, alignment = API_OFFSET[result.name]
        api_ax.annotate(
            API_LABEL[result.name],
            (result.cost_per_move, result.elo),
            xytext=(dx, dy),
            textcoords="offset points",
            ha=alignment,
            va="bottom",
            fontsize=MODEL_LABEL_FONT_SIZE,
            color="#27313D",
        )

    style_axes(
        all_ax,
        xlim=(8e-8, 0.5),
        ticks=[1e-7, 1e-5, 1e-3, 1e-1],
        formatter=FuncFormatter(cost_power_tick),
    )
    all_ax.set_ylim(0, 4700)
    all_ax.set_title(
        "(a) KataGo and API LLMs", fontsize=PAPER_FONT_SIZE, pad=6
    )

    style_axes(api_ax, xlim=(0.023, 0.70), ticks=[0.03, 0.1, 0.4])
    api_ax.set_ylim(850, 2550)
    api_ax.set_title(
        "(b) API LLMs (high reasoning)",
        fontsize=PAPER_FONT_SIZE,
        pad=6,
    )
    fig.subplots_adjust(
        left=0.135, right=0.985, bottom=0.25, top=0.81, wspace=0.36
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=300)
    plt.close(fig)


def plot_api_summary(path: Path, output: Path) -> None:
    """Plot multi-turn API rows, excluding single-turn and tool-use runs."""
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    rows = [row for row in snapshot["datasets"]["llm_players"]
            if re.fullmatch(r"(.+)-(high|xhigh|max)-api-multi\d*", row["player"])]
    if not rows:
        raise ValueError("No multi-turn API configurations found")
    katago = parse_katago_results(path)
    labels = API_MODEL_LABELS
    markers = API_EFFORT_MARKERS
    plt.rcParams.update({"pdf.fonttype": 42, "font.family": "DejaVu Sans"})
    fig, (all_ax, api_ax) = plt.subplots(
        1, 2, figsize=(5.5, 3.85), gridspec_kw={"width_ratios": (0.85, 1.15)},
    )
    all_ax.scatter([r.cost_per_move for r in katago], [r.elo for r in katago],
                   s=10, color="#9AA3AD", edgecolor="white", linewidth=.3, alpha=.8)
    present = set()
    by_model = {}
    for row in rows:
        match = re.fullmatch(r"(.+)-(high|xhigh|max)-api-multi\d*", row["player"])
        base, effort = match.groups()
        present.add(base)
        by_model.setdefault(base, []).append((effort, row))
        _, color = labels[base]
        result = Result(row["player"], row["elo"], row["elo_ci_95"], row["games"],
                        row["moves"], row["cost_usd_per_move"])
        for ax in (all_ax, api_ax):
            errorbar(ax, result, color=color, marker=markers[effort], markersize=4.8)
    effort_order = {"high": 0, "xhigh": 1, "max": 2}
    for base, variants in by_model.items():
        if len(variants) < 2:
            continue
        variants.sort(key=lambda pair: effort_order[pair[0]])
        api_ax.plot([row["cost_usd_per_move"] for _, row in variants],
                    [row["elo"] for _, row in variants],
                    color=labels[base][1], linewidth=1, alpha=.8, zorder=2)
    style_axes(all_ax, xlim=(8e-8, .25), ticks=[1e-7, 1e-5, 1e-3, 1e-1],
               formatter=FuncFormatter(cost_power_tick))
    all_ax.set_ylim(-100, 4650)
    all_ax.set_title("(a) KataGo and LLMs", fontsize=8)
    style_axes(api_ax, xlim=(.0015, .26), ticks=[.002, .01, .05, .2])
    api_ax.set_ylim(600, 2850)
    api_ax.set_title("(b) LLMs", fontsize=8)
    for ax in (all_ax, api_ax):
        ax.set_xlabel("Cost per move (USD, log scale)", fontsize=7)
        ax.set_ylabel("Elo", fontsize=8)
        ax.tick_params(labelsize=7)
    model_handles = [Line2D([], [], color=color, marker="o", linestyle="none",
                           markersize=4, label=label)
                     for base, (label, color) in labels.items() if base in present]
    model_handles.append(Line2D([], [], color="#9AA3AD", marker="o", linestyle="none",
                               markersize=4, label="KataGo"))
    fig.legend(handles=model_handles, loc="lower center", ncol=3, frameon=False,
               fontsize=6.5, bbox_to_anchor=(.51, .005), columnspacing=1.4,
               handletextpad=.4)
    fig.legend(handles=[Line2D([], [], marker=marker, linestyle="none",
                              color="#56616D", label=effort, markersize=5)
                        for effort, marker in markers.items()],
               loc="lower center", ncol=3, frameon=False, fontsize=7,
               bbox_to_anchor=(.52, .205))
    fig.subplots_adjust(left=.1, right=.975, bottom=.37, top=.93, wspace=.40)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=300)
    plt.close(fig)


HARNESS_COLORS = {
    "API": "#10A37F",
    "Codex multi": "#3B82F6",
    "Codex workspace": "#7C3AED",
    "Codex workspace continual": "#E07A2D",
}

EFFORT_ORDER = {"low": 0, "high": 1, "max": 2}
EFFORT_MARKERS = {"low": "^", "high": "D", "max": "p"}
# Equal nominal marker sizes do not produce equal areas in Matplotlib: the
# diamond path is twice the area of the triangle. These compensate by shape.
EFFORT_MARKER_SIZES = {"low": 6.2, "high": 4.4, "max": 5.7}


def sol_effort(name: str) -> str:
    match = re.match(r"gpt5\.6-sol-(low|high|max)-", name)
    if not match:
        raise ValueError(f"Invalid GPT-5.6 Sol result name: {name}")
    return match.group(1)


def sol_harness(name: str) -> str:
    suffix = re.sub(r"^gpt5\.6-sol-(?:low|high|max)-", "", name)
    if suffix == "api":
        return "API"
    if suffix == "codex-multi":
        return "Codex multi"
    if suffix == "codex-workspace":
        return "Codex workspace"
    if suffix.startswith("codex-workspace-continual"):
        return "Codex workspace continual"
    raise ValueError(f"Unknown GPT-5.6 Sol harness: {name}")


SOL_EXPECTED = frozenset(
    {
        "gpt5.6-sol-max-codex-workspace-continual",
        "gpt5.6-sol-max-codex-workspace",
        "gpt5.6-sol-max-codex-multi",
        "gpt5.6-sol-high-codex-workspace",
        "gpt5.6-sol-high-api",
        "gpt5.6-sol-high-codex-multi",
        "gpt5.6-sol-low-api",
        "gpt5.6-sol-low-codex-workspace",
        "gpt5.6-sol-low-codex-workspace-continual2",
        "gpt5.6-sol-high-codex-workspace-continual2",
        "gpt5.6-sol-low-codex-multi",
    }
)


def plot_sol(results: list[Result], output: Path) -> None:
    expected = SOL_EXPECTED
    actual = {result.name for result in results}
    if actual != expected:
        raise ValueError(
            "Unexpected completed GPT-5.6 Sol rows: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )

    # Match 80% of the NeurIPS text width so LaTeX does not scale the fonts.
    # Side legends keep the figure vertically compact.
    fig, ax = plt.subplots(figsize=(4.4, 1.95))
    for harness, color in HARNESS_COLORS.items():
        series = sorted(
            (result for result in results if sol_harness(result.name) == harness),
            key=lambda result: EFFORT_ORDER[sol_effort(result.name)],
        )
        if len(series) > 1:
            ax.plot(
                [result.cost_per_move for result in series],
                [result.elo for result in series],
                color=color,
                linewidth=1.25,
                alpha=0.72,
                zorder=2,
            )
    for result in results:
        effort = sol_effort(result.name)
        harness = sol_harness(result.name)
        errorbar(
            ax,
            result,
            color=HARNESS_COLORS[harness],
            marker=EFFORT_MARKERS[effort],
            markersize=EFFORT_MARKER_SIZES[effort],
        )

    style_axes(ax, xlim=(0.022, 0.46), ticks=[0.03, 0.1, 0.4])
    ax.set_ylim(850, 2500)
    ax.set_title("GPT-5.6 Sol Harnesses", fontsize=PAPER_FONT_SIZE, pad=7)
    harness_handles = [
        Line2D(
            [0],
            [0],
            color=color,
            linewidth=1.25,
            label=harness,
        )
        for harness, color in HARNESS_COLORS.items()
    ]
    harness_legend = fig.legend(
        handles=harness_handles,
        labels=["API", "Multi", "Workspace", "Continual"],
        title="Harness",
        loc="center left",
        bbox_to_anchor=(0.67, 0.67),
        ncol=1,
        frameon=True,
        fontsize=PAPER_FONT_SIZE,
        title_fontsize=PAPER_FONT_SIZE,
        borderpad=0.25,
        labelspacing=0.22,
        columnspacing=0.8,
        handlelength=1.6,
        handletextpad=0.4,
    )
    fig.add_artist(harness_legend)
    effort_handles = [
        Line2D(
            [0],
            [0],
            color="#56616D",
            marker=marker,
            linestyle="none",
            markeredgecolor="white",
            markeredgewidth=0.65,
            markersize=EFFORT_MARKER_SIZES[effort],
            label=effort.capitalize(),
        )
        for effort, marker in EFFORT_MARKERS.items()
    ]
    fig.legend(
        handles=effort_handles,
        title="Reasoning effort",
        loc="center left",
        bbox_to_anchor=(0.67, 0.21),
        ncol=1,
        frameon=True,
        fontsize=PAPER_FONT_SIZE,
        title_fontsize=PAPER_FONT_SIZE,
        alignment="left",
        borderpad=0.25,
        labelspacing=0.22,
        columnspacing=0.8,
        handletextpad=0.35,
    )
    fig.subplots_adjust(left=0.15, right=0.63, bottom=0.29, top=0.81)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=300)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary-results", type=Path,
                        default=ROOT / "log" / "summary" / "results.json",
                        help="current multi-turn API and KataGo summary snapshot")
    parser.add_argument("--api-only", action="store_true",
                        help="refresh the API figure while preserving the harness figure")
    parser.add_argument(
        "--paper-results",
        type=Path,
        default=DEFAULT_PAPER_RESULTS,
        help="JSON containing the KataGo Elo/cost dataset",
    )
    parser.add_argument("--api-output", type=Path, default=DEFAULT_API_OUTPUT)
    parser.add_argument("--sol-output", type=Path, default=DEFAULT_SOL_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plot_api_summary(args.summary_results, args.api_output)
    print(f"Saved {args.api_output} from {args.summary_results}")
    if args.api_only:
        return
    text = args.report.read_text(encoding="utf-8")
    all_results = parse_results(report_section(text, "All LLM comparisons"))
    sol_results = [
        result
        for result in all_results
        if result.name in SOL_EXPECTED
        and result.games > 0
        and result.moves > 0
        and result.cost_per_move > 0
    ]
    plot_sol(sol_results, args.sol_output)
    print(
        f"Saved {args.sol_output} "
        f"({sum(result.name.endswith('-api') for result in sol_results)} API, "
        f"{sum(not result.name.endswith('-api') for result in sol_results)} agentic)"
    )


if __name__ == "__main__":
    main()
