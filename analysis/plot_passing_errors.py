#!/usr/bin/env python3
"""Plot the saved passing audit, matching checkpoints to current summary Elo.

Run from the repository root: python -m analysis.plot_passing_errors
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter, StrMethodFormatter

from analysis.plot_summary_details import style
from gobench.paths import ROOT


def plot(audit_path: Path, summary_path: Path, output: Path) -> None:
    audit = json.loads(audit_path.read_text())
    summary = json.loads(summary_path.read_text())
    if not audit["complete"]:
        raise ValueError("The passing audit is incomplete")
    ratings = {r["player"]: r["elo"] for r in summary["datasets"]["katago_players"]}
    rows = sorted(audit["summary"], key=lambda r: ratings[r["player"]])
    for row in rows:
        if row["positions"] != 13 or row["trials"] != 260:
            raise ValueError(f"Unexpected trial count for {row['player']}")
    plt.rcParams.update({"font.size": 8, "font.family": "DejaVu Sans",
                         "pdf.fonttype": 42, "axes.labelsize": 8})
    fig, ax = plt.subplots(figsize=(5, 2.25), layout="constrained")
    style(ax)
    x = [ratings[r["player"]] for r in rows]
    y = [100 * r["passes"] / r["trials"] for r in rows]
    ax.axvspan(3200, 3400, color="#DCEFE9", zorder=0)
    ax.plot(x, y, "o-", color="#007C91", markersize=3, linewidth=.8)
    peak = max(range(len(rows)), key=lambda i: y[i])
    ax.annotate(f"{y[peak]:.1f}% ({rows[peak]['passes']}/260)",
                (x[peak], y[peak]), xytext=(-8, 8), textcoords="offset points",
                ha="right", fontsize=7, color="#005F70")
    ax.annotate("14 checkpoints:\n0/260 each", (3275, 0), xytext=(2700, 35),
                fontsize=7, ha="center", color="#386C5B",
                arrowprops={"arrowstyle": "-", "color": "#739889", "lw": .7})
    ax.set(xlim=(0, 3400), ylim=(-2, 73), xticks=[0, 1000, 2000, 3000],
           yticks=[0, 20, 40, 60], xlabel="KataGo Elo",
           ylabel="Pass rate on selected positions")
    ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path,
                        default=ROOT / "data/audits/passing/passing_b6c96_temp01.json")
    parser.add_argument("--summary-results", type=Path,
                        default=ROOT / "log/summary/results.json")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "paper/katago_passing_errors.pdf")
    args = parser.parse_args()
    plot(args.audit, args.summary_results, args.output)


if __name__ == "__main__":
    main()
