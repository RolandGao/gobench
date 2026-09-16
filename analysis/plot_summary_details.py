#!/usr/bin/env python3
"""Regenerate the paper's learning-time and color-function plots from the summary.

Run from the repository root: python -m analysis.plot_summary_details
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter

from gobench.paths import ROOT


def style(ax: plt.Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#9AA3AD")
        ax.spines[side].set_linewidth(.65)
    ax.grid(axis="y", color="#DEE3E8", linewidth=.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=3, width=.6)
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))


def plot(snapshot: dict, output: Path, learning_results: dict) -> None:
    plt.rcParams.update({"font.size": 8, "font.family": "DejaVu Sans",
                         "pdf.fonttype": 42, "axes.labelsize": 8})
    output.mkdir(parents=True, exist_ok=True)
    hours = [0, 1, 2, 4, 8]
    baselines = {r["player"]: r for r in learning_results["baselines"]}
    fig, ax = plt.subplots(figsize=(5.5, 2.9), layout="constrained")
    style(ax)
    for model, prefix, color in zip(
        ["GPT-6 Astra", "GPT-5.6 Sol"], ["gpt6-astra", "gpt5.6-sol"],
        ["#007C91", "#C56828"],
    ):
        learning = sorted(
            (r for r in learning_results["rows"] if r["model"] == model),
            key=lambda r: r["learning_hours"],
        )
        baseline = baselines[f"{prefix}-max-api-multi"]
        ax.axhspan(baseline["ci_low"], baseline["ci_high"], color=color, alpha=.10)
        ax.axhline(baseline["elo"], color=color, ls="--", lw=1,
                   label=f"{model}: Track 1 max")
        ax.errorbar([r["learning_hours"] for r in learning],
                    [r["elo"] for r in learning],
                    yerr=[r["elo_ci_95"] for r in learning], fmt="o-",
                    color=color, capsize=3, lw=1.3, markersize=5,
                    label=f"{model}: Codex high")
        for row in learning:
            first = row["learning_hours"] == 0
            ax.annotate(f'{row["elo"]:,.0f}',
                        (row["learning_hours"], row["ci_low"] if first else row["ci_high"]),
                        xytext=(0, -7 if first else 5), textcoords="offset points",
                        ha="left" if first else "center", va="top" if first else "bottom",
                        fontsize=6.5, color=color)
    ax.set(xlim=(-.45, 8.55), ylim=(700, 4000), xticks=hours,
           xlabel="Continual learning time (hours)", ylabel="Elo (95% CI)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1), ncol=2,
              frameon=False, fontsize=7)
    fig.savefig(output / "codex_learning_time.pdf")
    plt.close(fig)

    curve = snapshot["color_advantage_curve"]
    x = [r["average_elo"] for r in curve]
    fig, ax = plt.subplots(figsize=(4.85, 1.95), layout="constrained")
    style(ax)
    ax.fill_between(x, [r["black_advantage_95_ci"][0] for r in curve],
                     [r["black_advantage_95_ci"][1] for r in curve],
                     color="#9CCFEA", alpha=.65, label="95% CI")
    ax.plot(x, [r["black_advantage_elo"] for r in curve], color="#007C91", lw=1.5)
    ax.axhline(0, color="#717C88", ls="--", lw=.7)
    ax.set(xlim=(0, 4500), ylim=(-140, 15), xticks=[0, 1500, 3000, 4500],
           yticks=[-120, -80, -40, 0], xlabel="Average baseline Elo",
           ylabel="Black advantage (Elo)")
    ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.legend(loc="lower right", frameon=False, fontsize=7)
    fig.savefig(output / "black_advantage_summary.pdf")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-results", type=Path,
                        default=ROOT / "log/summary/results.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "paper")
    parser.add_argument("--learning-results", type=Path,
                        default=ROOT / "data/paper_learning_results.json")
    args = parser.parse_args()
    plot(json.loads(args.summary_results.read_text()), args.output_dir,
         json.loads(args.learning_results.read_text()))


if __name__ == "__main__":
    main()
