#!/usr/bin/env python3
"""Compare GoBench API LLM Elo with the current SimpleBench leaderboard.

The script intentionally uses only the Python standard library. It downloads
SimpleBench's public leaderboard JavaScript unless --simplebench-js is given,
then joins it to paper_results.json using an explicit, auditable model map.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
import statistics
import urllib.request
from pathlib import Path


from typing import Sequence

from gobench.paths import ROOT


SIMPLEBENCH_URL = "https://simple-bench.com/static/js/leaderboard-data.js"

# `effort_mismatch` is true only when both leaderboards explicitly name
# different settings. A missing SimpleBench effort label is treated as unknown,
# not as proof that the settings match.
MODEL_MATCHES = (
    {
        "gobench": "opus-5-high",
        "simplebench": "Claude Opus 5",
        "effort_mismatch": False,
        "note": "SimpleBench effort not stated",
    },
    {
        "gobench": "gemini-3.1-pro-high",
        "simplebench": "Gemini 3.1 Pro Preview",
        "effort_mismatch": False,
        "note": "SimpleBench effort not stated",
    },
    {
        "gobench": "DeepSeek-V4-Flash-0731-high",
        "simplebench": "DeepSeek V4 Flash",
        "effort_mismatch": False,
        "note": "same 2026-07-31 model; SimpleBench effort not stated",
    },
    {
        "gobench": "kimi-k3-high",
        "simplebench": "Kimi K3 (max)",
        "effort_mismatch": True,
        "note": "high versus max",
    },
    {
        "gobench": "gpt5.6-sol-high",
        "simplebench": "GPT-5.6 Sol (xhigh)",
        "effort_mismatch": True,
        "note": "high versus xhigh",
    },
    {
        "gobench": "muse-spark-1.2-openrouter-high",
        "simplebench": "Muse Spark 1.2",
        "effort_mismatch": False,
        "note": "SimpleBench effort not stated",
    },
    {
        "gobench": "grok-4.5-high",
        "simplebench": "Grok 4.5",
        "effort_mismatch": False,
        "note": "SimpleBench effort not stated",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gobench",
        type=Path,
        default=(ROOT / "data/paper_results.json"),
        help="GoBench paper-results JSON (default: data/paper_results.json in the checkout)",
    )
    parser.add_argument(
        "--simplebench-js",
        type=Path,
        help="optional downloaded leaderboard-data.js instead of the live URL",
    )
    return parser.parse_args()


def load_simplebench(path: Path | None) -> tuple[str, str]:
    if path is not None:
        return path.read_text(encoding="utf-8"), str(path)
    request = urllib.request.Request(
        SIMPLEBENCH_URL,
        headers={"User-Agent": "GoBench-SimpleBench-correlation/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8"), SIMPLEBENCH_URL


def parse_simplebench_scores(source: str) -> dict[str, float]:
    try:
        leaderboard = source.split("const leaderboardData = [", 1)[1].split(
            "];", 1
        )[0]
    except IndexError as exc:
        raise ValueError("could not locate leaderboardData in SimpleBench JS") from exc

    pairs = re.findall(
        r'model:\s*"([^"]+)"\s*,\s*score:\s*"([0-9]+(?:\.[0-9]+)?)%"',
        leaderboard,
    )
    scores = {model: float(score) for model, score in pairs}
    if len(scores) < 5:
        raise ValueError(f"parsed only {len(scores)} SimpleBench model scores")
    return scores


def load_gobench_scores(path: Path) -> dict[str, dict[str, float]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = payload["datasets"]["llm_players"]
    return {row["display_name"]: row for row in rows}


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("correlation requires equal-length samples of size >= 2")
    x_mean = statistics.fmean(x)
    y_mean = statistics.fmean(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
    x_ss = sum((a - x_mean) ** 2 for a in x)
    y_ss = sum((b - y_mean) ** 2 for b in y)
    if x_ss == 0 or y_ss == 0:
        raise ValueError("correlation is undefined for a constant sample")
    return numerator / math.sqrt(x_ss * y_ss)


def ranks(values: Sequence[float]) -> list[float]:
    """Return average ranks starting at one, including correct tie handling."""
    result = [0.0] * len(values)
    ordered = sorted(range(len(values)), key=values.__getitem__)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        average_rank = ((start + 1) + end) / 2
        for index in ordered[start:end]:
            result[index] = average_rank
        start = end
    return result


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    return pearson(ranks(x), ranks(y))


def exact_permutation_p(
    x: Sequence[float], y: Sequence[float], statistic
) -> float:
    """Two-sided exact permutation p-value for small matched samples."""
    observed = abs(statistic(x, y))
    extreme = 0
    total = 0
    for permuted in itertools.permutations(y):
        total += 1
        if abs(statistic(x, permuted)) + 1e-12 >= observed:
            extreme += 1
    return extreme / total


def fisher_interval(
    r: float, n: int, z_critical: float = 1.959964
) -> tuple[float, float]:
    """Approximate 95% Fisher-z interval for Pearson's r."""
    if n <= 3:
        return float("nan"), float("nan")
    clipped = max(-1 + 1e-15, min(1 - 1e-15, r))
    center = math.atanh(clipped)
    half_width = z_critical / math.sqrt(n - 3)
    return math.tanh(center - half_width), math.tanh(center + half_width)


def correlations(rows: Sequence[dict[str, object]]) -> dict[str, float]:
    x = [float(row["elo"]) for row in rows]
    y = [float(row["simplebench_score"]) for row in rows]
    r = pearson(x, y)
    rho = spearman(x, y)
    low, high = fisher_interval(r, len(rows))
    return {
        "n": float(len(rows)),
        "pearson": r,
        "pearson_p": exact_permutation_p(x, y, pearson),
        "pearson_ci_low": low,
        "pearson_ci_high": high,
        "spearman": rho,
        "spearman_p": exact_permutation_p(x, y, spearman),
    }


def leave_one_out_range(
    rows: Sequence[dict[str, object]], statistic
) -> tuple[float, float]:
    values = []
    for omitted in range(len(rows)):
        kept = [row for index, row in enumerate(rows) if index != omitted]
        x = [float(row["elo"]) for row in kept]
        y = [float(row["simplebench_score"]) for row in kept]
        values.append(statistic(x, y))
    return min(values), max(values)


def assemble_rows(
    gobench: dict[str, dict[str, float]], simplebench: dict[str, float]
) -> list[dict[str, object]]:
    rows = []
    for match in MODEL_MATCHES:
        gobench_name = str(match["gobench"])
        simplebench_name = str(match["simplebench"])
        if gobench_name not in gobench:
            raise KeyError(f"GoBench model not found: {gobench_name}")
        if simplebench_name not in simplebench:
            raise KeyError(f"SimpleBench model not found: {simplebench_name}")
        rows.append(
            {
                **match,
                "elo": float(gobench[gobench_name]["elo"]),
                "elo_ci_95": float(gobench[gobench_name]["elo_ci_95"]),
                "games": int(gobench[gobench_name]["games"]),
                "simplebench_score": simplebench[simplebench_name],
            }
        )
    return rows


def print_results(label: str, rows: Sequence[dict[str, object]]) -> None:
    stats = correlations(rows)
    pearson_loo = leave_one_out_range(rows, pearson)
    spearman_loo = leave_one_out_range(rows, spearman)
    print(f"\n{label} (n={int(stats['n'])})")
    print(
        "  Pearson r = "
        f"{stats['pearson']:+.3f}, exact permutation p={stats['pearson_p']:.3f}, "
        f"approx. 95% CI [{stats['pearson_ci_low']:+.3f}, "
        f"{stats['pearson_ci_high']:+.3f}]"
    )
    print(
        "  Spearman rho = "
        f"{stats['spearman']:+.3f}, exact permutation p={stats['spearman_p']:.3f}"
    )
    print(
        f"  Leave-one-out range: Pearson [{pearson_loo[0]:+.3f}, "
        f"{pearson_loo[1]:+.3f}], Spearman [{spearman_loo[0]:+.3f}, "
        f"{spearman_loo[1]:+.3f}]"
    )


def main() -> None:
    args = parse_args()
    js, simplebench_source = load_simplebench(args.simplebench_js)
    simplebench = parse_simplebench_scores(js)
    gobench = load_gobench_scores(args.gobench)
    rows = assemble_rows(gobench, simplebench)

    print(f"GoBench source: {args.gobench}")
    print(f"SimpleBench source: {simplebench_source}")
    print(f"SimpleBench source SHA-256: {hashlib.sha256(js.encode()).hexdigest()}")
    print("\nMatched models (ordered by GoBench Elo):")
    print(
        "GoBench model                                 Elo +/-95%CI  "
        "SimpleBench model              Score  Settings"
    )
    for row in rows:
        print(
            f"{str(row['gobench']):<44} "
            f"{float(row['elo']):7.1f} +/-{float(row['elo_ci_95']):5.1f}  "
            f"{str(row['simplebench']):<29} "
            f"{float(row['simplebench_score']):5.1f}%  {row['note']}"
        )

    matched_names = {str(row["gobench"]) for row in rows}
    unmatched = sorted(set(gobench) - matched_names)
    print("\nUnmatched GoBench API models: " + ", ".join(unmatched))

    print_results("All same-version model matches", rows)
    comparable = [row for row in rows if not bool(row["effort_mismatch"])]
    print_results("Excluding explicit reasoning-effort mismatches", comparable)


if __name__ == "__main__":
    main()
