#!/usr/bin/env python3
"""Plot GoBench Elo against ARC-AGI-1 and ARC-AGI-2 semi-private scores.

Run from the repository root: python -m analysis.plot_arc_agi_correlation

ARC scores come from the ARC Prize leaderboard data file, snapshotted in
data/arc_agi/evaluations.json. Pass --download to refresh the snapshot first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import urllib.request
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter

from analysis.analyze_simplebench_correlation import fisher_interval, pearson, spearman
from analysis.plot_report_llm_costs import API_EFFORT_MARKERS, API_MODEL_LABELS
from analysis.plot_summary_details import style
from gobench.paths import ROOT


ARC_URL = "https://arcprize.org/media/data/evaluations.json"
DATASETS = {"ARC-AGI-1": "v1_Semi_Private", "ARC-AGI-2": "v2_Semi_Private"}
PLAYER = re.compile(r"(.+)-(high|xhigh|max)-api-multi\d*")

# GoBench multi-turn API player -> ARC Prize model id. DeepSeek V4.1 Flash,
# Gemini 3.8 Flash, and Muse Spark 1.3 have no ARC Prize entry and are omitted.
MODEL_MATCHES = {
    "gpt6-astra-max-api-multi": "openai-gpt-6-astra-max",
    "gpt6-astra-high-api-multi": "openai-gpt-6-astra-high",
    "opus-5-high-api-multi2": "anthropic-claude-opus-5-high",
    "gpt5.6-sol-max-api-multi": "openai-gpt-5-6-sol-max",
    "gpt5.6-sol-high-api-multi4": "openai-gpt-5-6-sol-high",
    # ARC Prize does not state the reasoning effort for Gemini 3.1 Pro (Preview).
    "gemini-3.1-pro-high-api-multi": "gemini-3-1-pro-preview",
    "DeepSeek-V4-Flash-0731-max-api-multi": "deepseek-v4-flash-0731-max",
    "DeepSeek-V4-Flash-0731-high-api-multi2": "deepseek-v4-flash-0731-high",
    "gemini-3.6-flash-high-api-multi": "gemini-3-6-flash-high",
    # GoBench called the undated gpt-5.6-luna alias, so use ARC Prize's original
    # Luna entry rather than its 2026-07-30 snapshot.
    "gpt5.6-luna-high-api-multi": "openai-gpt-5-6-luna-high",
    "gpt5.6-luna-max-api-multi": "openai-gpt-5-6-luna-max",
    "grok-4.6-xhigh-api-multi": "xai-grok-4-6-xhigh",
    "grok-4.6-high-api-multi2": "xai-grok-4-6-high",
}


def download(path: Path) -> None:
    request = urllib.request.Request(
        ARC_URL, headers={"User-Agent": "GoBench-ARC-correlation/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def load_arc_scores(path: Path) -> dict[tuple[str, str], float]:
    """Return ARC scores in percent, keyed by (model id, dataset id)."""
    return {
        (row["modelId"], row["datasetId"]): 100 * float(row["score"])
        for row in json.loads(path.read_text(encoding="utf-8"))
        if row["datasetId"] in DATASETS.values()
    }


def matched_rows(summary: dict, arc: dict[tuple[str, str], float]) -> list[dict]:
    players = {row["player"]: row for row in summary["datasets"]["llm_players"]}
    rows = []
    for player, arc_id in MODEL_MATCHES.items():
        base, effort = PLAYER.fullmatch(player).groups()
        rows.append({
            "player": player, "arc_id": arc_id, "base": base, "effort": effort,
            "elo": players[player]["elo"], "ci": players[player]["elo_ci_95"],
            **{label: arc[(arc_id, dataset)] for label, dataset in DATASETS.items()},
        })
    return sorted(rows, key=lambda row: -row["elo"])


def permutation_p(x, y, statistic, samples: int = 100_000, seed: int = 0) -> float:
    """Two-sided Monte Carlo permutation p-value; exact enumeration is too slow."""
    rng = random.Random(seed)
    observed = abs(statistic(x, y))
    shuffled = list(y)
    extreme = 0
    for _ in range(samples):
        rng.shuffle(shuffled)
        extreme += abs(statistic(x, shuffled)) + 1e-12 >= observed
    return (extreme + 1) / (samples + 1)


def correlations(rows: list[dict]) -> dict[str, dict[str, float]]:
    x = [row["elo"] for row in rows]
    stats = {}
    for label in DATASETS:
        y = [row[label] for row in rows]
        r = pearson(x, y)
        low, high = fisher_interval(r, len(rows))
        stats[label] = {
            "pearson": r, "pearson_ci_low": low, "pearson_ci_high": high,
            "pearson_p": permutation_p(x, y, pearson),
            "spearman": spearman(x, y), "spearman_p": permutation_p(x, y, spearman),
        }
    return stats


def plot(rows: list[dict], stats: dict[str, dict[str, float]], output: Path) -> None:
    plt.rcParams.update({"font.size": 8, "font.family": "DejaVu Sans",
                         "pdf.fonttype": 42, "axes.labelsize": 8})
    fig, axes = plt.subplots(1, 2, figsize=(5.5, 2.9), sharey=True)
    for ax, label in zip(axes, DATASETS):
        style(ax)
        for row in rows:
            ax.errorbar(row[label], row["elo"], yerr=row["ci"],
                        fmt=API_EFFORT_MARKERS[row["effort"]],
                        color=API_MODEL_LABELS[row["base"]][1], markersize=4.8,
                        capsize=2.5, elinewidth=.9, capthick=.9,
                        markeredgecolor="white", markeredgewidth=.65, zorder=3)
        ax.text(.04, .96, f"Pearson $r$ = {stats[label]['pearson']:.2f}\n"
                          f"Spearman $\\rho$ = {stats[label]['spearman']:.2f}",
                transform=ax.transAxes, va="top", fontsize=7)
        ax.set_title(f"{label} (semi-private)", fontsize=8)
        ax.set_xlabel(f"{label} score")
        ax.xaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
    axes[0].set_ylabel("GoBench Elo")
    present = {row["base"] for row in rows}
    fig.legend(handles=[Line2D([], [], color=color, marker="o", linestyle="none",
                               markersize=4, label=name)
                        for base, (name, color) in API_MODEL_LABELS.items()
                        if base in present],
               loc="lower center", ncol=4, frameon=False, fontsize=6.5,
               bbox_to_anchor=(.5, .005), columnspacing=1.4, handletextpad=.4)
    fig.legend(handles=[Line2D([], [], marker=marker, linestyle="none",
                               color="#56616D", label=effort, markersize=5)
                        for effort, marker in API_EFFORT_MARKERS.items()],
               loc="lower center", ncol=3, frameon=False, fontsize=7,
               bbox_to_anchor=(.5, .135))
    fig.subplots_adjust(left=.12, right=.98, bottom=.4, top=.91, wspace=.1)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-results", type=Path,
                        default=ROOT / "log/summary/results.json")
    parser.add_argument("--arc-evaluations", type=Path,
                        default=ROOT / "data/arc_agi/evaluations.json")
    parser.add_argument("--download", action="store_true",
                        help="refresh the ARC Prize snapshot before plotting")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "paper/arc_agi_correlation.pdf")
    args = parser.parse_args()
    if args.download:
        download(args.arc_evaluations)

    rows = matched_rows(json.loads(args.summary_results.read_text()),
                        load_arc_scores(args.arc_evaluations))
    stats = correlations(rows)
    digest = hashlib.sha256(args.arc_evaluations.read_bytes()).hexdigest()
    print(f"ARC source: {args.arc_evaluations} (SHA-256 {digest})")
    print(f"{'GoBench player':<40} {'Elo':>5} {'ARC-AGI-1':>10} {'ARC-AGI-2':>10}")
    for row in rows:
        print(f"{row['player']:<40} {row['elo']:5.0f} "
              f"{row['ARC-AGI-1']:9.1f}% {row['ARC-AGI-2']:9.1f}%")
    for label, s in stats.items():
        print(f"\n{label} (n={len(rows)})\n"
              f"  Pearson r = {s['pearson']:+.3f}, permutation p = {s['pearson_p']:.4f}, "
              f"approx. 95% CI [{s['pearson_ci_low']:+.3f}, {s['pearson_ci_high']:+.3f}]\n"
              f"  Spearman rho = {s['spearman']:+.3f}, permutation p = {s['spearman_p']:.4f}")
    plot(rows, stats, args.output)
    print(f"\nSaved {args.output}")


if __name__ == "__main__":
    main()
