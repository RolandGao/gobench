#!/usr/bin/env python3
"""Probe historical passing-loss positions at higher search budgets.

This is a conditional position study, not a rerun of the original games. Each
trial starts with empty search state and replays the full legal move history.
No arena settings or archived results are modified.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path


from analysis.passing_common import cases, probe, write_report
from gobench.strategies import KATAGO_BINARY, KATAGO_CONFIG

from gobench.paths import ROOT


def summarize(results, budgets):
    summaries = []
    for budget in budgets:
        rows = [r for c in results for r in c["budgets"] if r["max_visits"] == budget]
        trials = [t for row in rows for t in row["trials"]]
        summaries.append(
            dict(
                max_visits=budget,
                trials=len(trials),
                passes=sum(t["move"].lower() == "pass" for t in trials),
                resignations=sum(t["move"].lower() == "resign" for t in trials),
                positions_passing=sum(
                    any(t["move"].lower() == "pass" for t in r["trials"]) for r in rows
                ),
                actual_visits=dict(Counter(t["actual_visits"] for t in trials)),
            )
        )
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=(ROOT / "log"))
    parser.add_argument("--audit", type=Path, default=(ROOT / "data/audits/passing/passing_audit.json"))
    parser.add_argument("--output", type=Path, default=(ROOT / "data/audits/passing/passing_visits.json"))
    parser.add_argument(
        "--budgets", type=int, nargs="+", default=[1, 5, 10, 20, 50, 100, 200]
    )
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        metavar="RUN:GAME",
        help="Limit to selected cases; repeat this option to select several",
    )
    parser.add_argument("--no-conservative-pass", action="store_true")
    parser.add_argument("--full-budget", action="store_true")
    args = parser.parse_args()
    if min(args.budgets + [args.repeats, args.workers]) < 1:
        parser.error("budgets, repeats and workers must be positive")
    selected = cases(args.root, json.loads(args.audit.read_text()))
    if args.case:
        selected = [
            c
            for c in selected
            if f"{c['info']['run']}:{c['info']['game']}" in args.case
        ]
        if len(selected) != len(set(args.case)):
            parser.error("Each --case must identify a legal-history consensus flip")
    report = dict(
        complete=False,
        method="Fresh full-history replay before each noncommitting kata-search",
        caveat=(
            "Original search trees, RNG states and recent search win/loss estimates "
            "are not reconstructed. This measures repeated decisions at selected "
            "failure positions, not full-game failure rates."
        ),
        engine=str(KATAGO_BINARY),
        engine_version=subprocess.check_output(
            [str(KATAGO_BINARY), "version"], text=True
        ).strip(),
        config=str(KATAGO_CONFIG),
        config_sha256=hashlib.sha256(KATAGO_CONFIG.read_bytes()).hexdigest(),
        conservative_pass=not args.no_conservative_pass,
        full_budget=args.full_budget,
        repeats=args.repeats,
        results=[],
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(
                probe,
                c,
                args.budgets,
                args.repeats,
                not args.no_conservative_pass,
                args.full_budget,
            )
            for c in selected
        ]
        for future in concurrent.futures.as_completed(futures):
            report["results"].append(future.result())
            report["results"].sort(key=lambda c: (c["info"]["run"], c["info"]["game"]))
            write_report(report, args.output)
    report["complete"] = True
    report["summary"] = summarize(report["results"], args.budgets)
    write_report(report, args.output)
    print(json.dumps(report["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
