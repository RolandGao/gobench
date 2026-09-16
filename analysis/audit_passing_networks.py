#!/usr/bin/env python3
"""Compare calibrated one-visit players on the same historical passing errors.

Run from the repository root:
    .venv/bin/python -m analysis.audit_passing_networks --all-b6c96
Append --resume to continue an interrupted run, or --dry-run to list players.
Default: 20 trials on each of 13 positions, with two concurrent GTP processes.
Missing weights are downloaded and verified against the pinned manifest.

Outputs: passing_b6c96_temp01.md (table), *_summary.csv (same table),
*.csv (per-position counts), and *.json (resumable checkpoint and raw trials).
Temperature 0.1 refers to the calibrated late temperature; early remains 0.5.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import subprocess
from pathlib import Path


from analysis.passing_common import cases, probe, write_report
from gobench.strategies import (
    KATAGO_BINARY,
    KATAGO_CONFIG,
    KATAGO_NETWORKS,
    ensure_arena_networks,
)

from gobench.paths import ROOT

CALIBRATION = (ROOT / "log/arena_20260805_040447_246130_2072c54f/run.json")
PLAYERS = (
    "kata1-b6c96-s8080640-d1961030-temp-0.7",
    "kata1-b6c96-s13733120-d2631546-temp-0.3",
    "kata1-b6c96-s103950080-d15368530",
    "kata1-b18c384nbt-s9761732864-d4253420187",
)


def b6c96_players():
    """Select exactly one calibrated temperature-0.1 player per b6c96 network."""
    calibration = json.loads(CALIBRATION.read_text())
    ratings = {r["player"]: r for r in calibration["ratings"]}
    names = []
    for network in KATAGO_NETWORKS:
        if not network.name.startswith("kata1-b6c96-"):
            continue
        matches = [
            b["name"]
            for b in calibration["bots"]
            if b.get("network_name") == network.name
            and b.get("max_visits") == 1
            and b.get("chosen_move_temperature") == 0.1
            and b.get("chosen_move_temperature_early") == 0.5
            and b["name"] in ratings
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one calibrated player for {network.name}")
        names.extend(matches)
    if not names:
        raise ValueError("No b6c96 networks found")
    return sorted(names, key=lambda name: ratings[name]["elo"])


def players(names=PLAYERS):
    calibration = json.loads(CALIBRATION.read_text())
    bots = {b["name"]: b for b in calibration["bots"]}
    ratings = {r["player"]: r for r in calibration["ratings"]}
    networks = {s.name: s for s in KATAGO_NETWORKS}
    selected = []
    for name in names:
        bot = bots[name]
        assert bot["max_visits"] == 1
        network = networks[bot["network_name"]]
        ensure_arena_networks([network])
        digest = hashlib.sha256(network.path.read_bytes()).hexdigest()
        assert digest == network.sha256, network.path
        selected.append(
            dict(
                bot=bot,
                rating=ratings[name],
                model=str(network.path),
                model_sha256=digest,
            )
        )
    return selected


def run_probe(case, player, repeats):
    modified = case | dict(
        original_bot=case["bot"],
        bot=player["bot"],
        model=player["model"],
        model_sha256=player["model_sha256"],
    )
    # Retain the historical LLM game's GTP pass behavior. Only the player
    # network and its calibrated temperature settings change between columns.
    result = probe(modified, [1], repeats, conservative=True, full_budget=False)
    assert all(t["actual_visits"] == 1 for t in result["budgets"][0]["trials"])
    return result | dict(
        tested_player=player["bot"]["name"], calibrated_elo=player["rating"]["elo"]
    )


def write_tables(report, output):
    rows = []
    for result in report["results"]:
        info = result["info"]
        trials = result["budgets"][0]["trials"]
        rows.append(
            dict(
                run=info["run"],
                game=info["game"],
                llm=info["llm"],
                color=info["katago_color"],
                pass_move=info["katago_pass_move"],
                original_player=info["katago_player"],
                tested_player=result["tested_player"],
                elo=result["calibrated_elo"],
                trials=len(trials),
                passes=sum(t["move"].lower() == "pass" for t in trials),
                resignations=sum(t["move"].lower() == "resign" for t in trials),
                choices=json.dumps(result["budgets"][0]["choices"], sort_keys=True),
            )
        )
    if rows:
        with output.with_suffix(".csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    report["summary"] = []
    for player in report["players"]:
        subset = [r for r in rows if r["tested_player"] == player["bot"]["name"]]
        report["summary"].append(
            dict(
                player=player["bot"]["name"],
                elo=player["rating"]["elo"],
                positions=len(subset),
                trials=sum(r["trials"] for r in subset),
                passes=sum(r["passes"] for r in subset),
                positions_passing=sum(r["passes"] > 0 for r in subset),
                resignations=sum(r["resignations"] for r in subset),
            )
        )
    summary_rows = [
        {
            "network": r["player"],
            "elo": r["elo"],
            "num_passes/total": f"{r['passes']}/{r['trials']}",
        }
        for r in sorted(report["summary"], key=lambda r: r["elo"])
    ]
    summary_path = output.with_name(output.stem + "_summary.csv")
    with summary_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["network", "elo", "num_passes/total"]
        )
        writer.writeheader()
        writer.writerows(summary_rows)
    lines = [
        "Complete."
        if report["complete"]
        else "IN PROGRESS: denominators include completed positions only.",
        "",
        f"One visit; {report['repeats']} trials per position; 13 historical positions.",
        report["temperature_policy"] + ".",
        f"Elo source: {report['calibration_source']}.",
        "Passing rates apply to these selected positions, not full games.",
        "",
        "| Network | Elo | num_passes/total |",
        "| --- | ---: | ---: |",
    ]
    lines.extend(
        f"| {r['network']} | {r['elo']:.1f} | {r['num_passes/total']} |"
        for r in summary_rows
    )
    output.with_suffix(".md").write_text("\n".join(lines) + "\n")


def save_report(report, output):
    """Keep a complete JSON checkpoint even if interrupted during a write."""
    output.parent.mkdir(parents=True, exist_ok=True)
    write_tables(report, output)
    write_report(report, output)


def result_key(result):
    return result["tested_player"], result["info"]["run"], result["info"]["game"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--workers", type=int, default=2)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--players", nargs="+", default=PLAYERS)
    selection.add_argument(
        "--all-b6c96",
        action="store_true",
        help="All b6c96 networks, calibrated early temperature 0.5 / late 0.1",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON checkpoint; also writes Markdown and CSV tables",
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume the existing JSON checkpoint"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List players and trial count without downloading or searching",
    )
    args = parser.parse_args()
    if min(args.repeats, args.workers) < 1:
        parser.error("repeats and workers must be positive")
    names = b6c96_players() if args.all_b6c96 else args.players
    if args.dry_run:
        print(
            f"{len(names)} players × 13 positions × {args.repeats} trials = "
            f"{len(names) * 13 * args.repeats} decisions"
        )
        print("\n".join(names))
        return
    args.output = args.output or ROOT / "data/audits/passing" / (
        "passing_b6c96_temp01.json" if args.all_b6c96 else "passing_networks.json"
    )
    if args.output.suffix != ".json":
        parser.error("--output must end in .json")
    if args.resume and not args.output.exists():
        parser.error("--resume requires an existing checkpoint")
    if args.output.exists() and not args.resume:
        parser.error("Output exists; use --resume or choose another --output")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    audit_path = (ROOT / "data/audits/passing/passing_audit.json")
    audit = json.loads(audit_path.read_text())
    selected = cases((ROOT / "log"), audit)
    if len(selected) != 13:
        raise ValueError(f"Expected the 13 historical positions, got {len(selected)}")
    agreed = {tuple(p) for p in audit["agreement"]["all_judges_flip"]}
    excluded = [
        c
        for c in audit["judges"][0]["candidates"]
        if (c["run"], c["game"]) in agreed and c["superko_violation_moves"]
    ]
    report = dict(
        complete=False,
        calibration_source=str(CALIBRATION),
        calibration_sha256=hashlib.sha256(CALIBRATION.read_bytes()).hexdigest(),
        source_audit=str(audit_path),
        source_audit_sha256=hashlib.sha256(audit_path.read_bytes()).hexdigest(),
        engine_version=subprocess.check_output(
            [str(KATAGO_BINARY), "version"], text=True
        ).strip(),
        config_sha256=hashlib.sha256(KATAGO_CONFIG.read_bytes()).hexdigest(),
        visits=1,
        repeats=args.repeats,
        conservative_pass=True,
        temperature_policy=(
            "Calibrated temperature 0.1 variants: early 0.5, late 0.1"
            if args.all_b6c96
            else "Each player's original calibrated early and late temperatures"
        ),
        method=(
            "Fresh legal full-history replay immediately before the historical "
            "KataGo pass, clear search/NN caches and GTP recent-value history "
            "before each kata-search"
        ),
        limitations=(
            "These are conditional pass decisions on selected failure positions, "
            "not complete game outcomes. Original search trees/RNG states are "
            "not reconstructed. The five illegal-history cases are listed but "
            "not probed."
        ),
        players=players(names),
        positions=selected,
        excluded_illegal_history=excluded,
        results=[],
    )
    if args.resume:
        previous = json.loads(args.output.read_text())
        for key, value in report.items():
            if key not in {"complete", "results"} and previous.get(key) != value:
                raise ValueError(f"Checkpoint settings differ: {key}")
        report["results"] = previous["results"]
    expected = {
        (player["bot"]["name"], case["info"]["run"], case["info"]["game"])
        for player in report["players"]
        for case in selected
    }
    finished = {result_key(result) for result in report["results"]}
    if not finished <= expected or len(finished) != len(report["results"]):
        raise ValueError("Checkpoint contains unexpected or duplicate results")
    for result in report["results"]:
        trials = result["budgets"][0]["trials"]
        if len(trials) != args.repeats or any(t["actual_visits"] != 1 for t in trials):
            raise ValueError("Checkpoint contains incomplete or non-one-visit trials")
    save_report(report, args.output)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(run_probe, case, player, args.repeats)
            for player in report["players"]
            for case in selected
            if (player["bot"]["name"], case["info"]["run"], case["info"]["game"])
            not in finished
        ]
        for future in concurrent.futures.as_completed(futures):
            report["results"].append(future.result())
            report["results"].sort(
                key=lambda r: (r["calibrated_elo"], r["info"]["run"], r["info"]["game"])
            )
            save_report(report, args.output)
            print(
                f"Saved {len(report['results'])}/{len(expected)} position probes "
                f"to {args.output}",
                flush=True,
            )
    assert len(report["results"]) == len(report["players"]) * len(selected)
    report["complete"] = True
    save_report(report, args.output)
    print(json.dumps(report["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
