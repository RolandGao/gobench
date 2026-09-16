#!/usr/bin/env python3
"""Plot the three leading Black-advantage models for the paper."""

from __future__ import annotations

import argparse
from pathlib import Path


import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import StrMethodFormatter

from analysis import color_advantage_model as models

from gobench.paths import ROOT


DEFAULT_OUTPUT = ROOT / "paper" / "black_advantage_average_elo2.pdf"
DEFAULT_PNG_OUTPUT = ROOT / "paper" / "black_advantage_average_elo2.png"
TOP_MODELS = (
    ("average_elo_piecewise_linear_1500", "Piecewise linear\n(1,500 Elo)"),
    ("average_elo_quadratic", "Quadratic\n "),
    ("average_elo_piecewise_constant_500", "Piecewise constant\n(500 Elo)"),
)


def _current_dataset() -> models.Dataset:
    observations = models._read_paired_observations(models.DEFAULT_INPUTS)
    players = tuple(
        sorted(
            {
                player
                for observation in observations
                for player in (observation.black, observation.white)
            }
        )
    )
    sources = tuple(sorted({observation.source for observation in observations}))
    return models._dataset_from_observations(
        observations,
        ROOT / "log/current_bot_pool/results.csv",
        players=players,
        sources=sources,
    )


def plot(output_path: Path, png_output_path: Path, *, dpi: int) -> None:
    dataset = _current_dataset()
    results, covariates = models._analyse_dataset(dataset)
    by_name = {result.name: result for result in results}

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": [
                "Times New Roman",
                "Times",
                "Nimbus Roman",
                "DejaVu Serif",
            ],
            "font.size": 7.5,
            "axes.titlesize": 8.2,
            "axes.labelsize": 8.2,
            "xtick.labelsize": 6.8,
            "ytick.labelsize": 6.8,
            "legend.fontsize": 7.2,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )

    curve_color = "#0878B8"
    band_color = "#9CCFEA"
    axis_color = "#29384A"
    grid_color = "#D9DEE5"
    fig, axes = plt.subplots(1, 3, figsize=(5.5, 2.15), sharex=True, sharey=True)
    fig.subplots_adjust(
        left=0.085,
        right=0.995,
        bottom=0.24,
        top=0.70,
        wspace=0.10,
    )

    for index, (axis, (model_name, title)) in enumerate(zip(axes, TOP_MODELS)):
        result = by_name[model_name]
        x, estimate, lower, upper = models._color_curve(dataset, result, covariates)
        axis.fill_between(
            x,
            lower,
            upper,
            color=band_color,
            alpha=0.55,
            linewidth=0,
            zorder=1,
        )
        axis.plot(x, estimate, color=curve_color, linewidth=1.35, zorder=3)
        axis.axhline(
            0,
            color="#7B8794",
            linestyle=(0, (4, 3)),
            linewidth=0.65,
            zorder=2,
        )
        axis.set_title(
            f"({chr(ord('a') + index)}) {title}",
            pad=5,
            fontweight="semibold",
        )
        axis.set_xlim(0, 4500)
        axis.set_ylim(-160, 15)
        axis.set_xticks((0, 1500, 3000, 4500))
        axis.set_yticks((-150, -100, -50, 0))
        axis.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
        axis.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
        axis.grid(axis="y", color=grid_color, linewidth=0.45)
        axis.set_axisbelow(True)
        axis.tick_params(
            axis="both",
            colors=axis_color,
            length=2.3,
            width=0.55,
            pad=2,
        )
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        for side in ("left", "bottom"):
            axis.spines[side].set_color(axis_color)
            axis.spines[side].set_linewidth(0.65)

    fig.supxlabel("Average baseline Elo", fontsize=8.2, y=0.045, color=axis_color)
    fig.supylabel("Black advantage (Elo)", fontsize=8.2, x=0.012, color=axis_color)
    legend_handles = (
        plt.Line2D([], [], color=curve_color, linewidth=1.35, label="Estimate"),
        Patch(facecolor=band_color, edgecolor="none", alpha=0.55, label="95% CI"),
    )
    fig.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.985),
        ncol=2,
        frameon=False,
        handlelength=2.3,
        columnspacing=1.8,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    png_output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format="pdf", bbox_inches="tight", pad_inches=0.02)
    fig.savefig(
        png_output_path,
        format="png",
        dpi=dpi,
        bbox_inches="tight",
        pad_inches=0.02,
    )
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG_OUTPUT)
    parser.add_argument("--dpi", type=int, default=1200)
    args = parser.parse_args()
    if args.dpi <= 0:
        parser.error("--dpi must be positive")
    plot(args.output, args.png_output, dpi=args.dpi)
    print(f"Saved vector figure to {args.output}")
    print(f"Saved {args.dpi}-DPI preview to {args.png_output}")


if __name__ == "__main__":
    main()
