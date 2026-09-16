#!/usr/bin/env python3
"""Audit recorded passing losses using independently estimated dead-stone lists.

This changes no game results. Death classification is a KataGo estimate, not a
proof. Exact area scoring is applied only after the estimated stones are removed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path


from analysis.audit_superko import ReplayBoard
from analysis.passing_common import area_score, result_score, write_report
from gobench.game_engine import GTPProcess, _parse_board
from gobench.strategies import KATAGO_BINARY, KATAGO_CONFIG

from gobench.paths import ROOT


def inventory(root):
    counts, native, candidates, score_differences = Counter(), Counter(), [], []
    for run in sorted(root.glob("*/run.json")):
        config = json.loads(run.read_text())
        results = run.parent / "results.csv"
        canonical = {}
        if results.exists():
            for row in csv.DictReader(results.open()):
                canonical[int(row["game"])] = row
                if row["source"] == "katago_match":
                    native["games"] += 1
                    native[
                        "resignations" if row["result"].endswith("+R") else "scored"
                    ] += 1
        path = run.parent / "llm_games.jsonl"
        if not path.exists():
            continue
        records = [json.loads(line) for line in path.read_text().splitlines()]
        if set(canonical) != {game["game"] for game in records}:
            raise ValueError(f"canonical result/move coverage mismatch: {run}")
        for game in records:
            counts["games"] += 1
            color = "B" if game["black"].startswith("kata") else "W"
            outcome = (
                "win"
                if game["winner_color"] == color
                else "loss"
                if game["winner_color"]
                else "draw"
            )
            counts[outcome] += 1
            counts[game["reason"]] += 1
            board = ReplayBoard(config["board_size"])
            illegal = []
            for number, move in enumerate(game["moves"], 1):
                if move["move"] == "resign":
                    break
                violation = board.play(move["color"], move["move"])
                if violation:
                    illegal.append(number)
            counts["games_with_superko_violation"] += bool(illegal)
            if not illegal:
                counts["legal_games"] += 1
                counts[f"legal_{outcome}"] += 1
            if game["reason"] != "two_passes":
                continue
            counts[f"two_passes_{outcome}"] += 1
            if [m["move"] for m in game["moves"][-2:]] != ["pass", "pass"]:
                raise ValueError(f"two_passes game has no terminal passes: {path}")
            counts["two_passes_with_superko_violation"] += bool(illegal)
            strict = area_score(board, config["komi"])
            info = {
                "run": run.parent.name,
                "game": game["game"],
                "katago_color": color,
                "katago_player": game["black" if color == "B" else "white"],
                "llm": game["white" if color == "B" else "black"],
                "result": game["result"],
                "strict_black_minus_white": strict,
                "superko_violation_moves": illegal,
                "katago_pass_was_second": game["moves"][-1]["color"] == color,
                "katago_pass_move": len(game["moves"])
                - (game["moves"][-1]["color"] != color),
            }
            if strict != result_score(game["result"]):
                score_differences.append(info)
            if outcome == "loss":
                candidates.append((info, game, config, board))
    return dict(counts), dict(native), candidates, score_differences


def native_coverage(root):
    coverage = []
    for path in sorted(root.glob("*/results.csv")):
        with path.open() as handle:
            games = sum(
                row["source"] == "katago_match" for row in csv.DictReader(handle)
            )
        if games:
            raw = root.parent / "untracked_log" / path.parent.name
            coverage.append(
                {
                    "run": path.parent.name,
                    "games": games,
                    "raw_directory_exists": raw.is_dir(),
                    "sgf_files": sum(1 for _ in raw.rglob("*.sgf"))
                    + sum(1 for _ in raw.rglob("*.sgfs")),
                    "games_journal_exists": (raw / "games.jsonl").is_file(),
                }
            )
    return coverage


def judge(model, candidates):
    results = []
    with tempfile.TemporaryDirectory(prefix="gobench-passing-") as directory:
        root = Path(directory)
        overrides = (
            f"logDir={root}/engine,logAllGTPCommunication=false,logSearchInfo=false,"
            "startupPrintMessageToStderr=false,numSearchThreads=1,"
            "numEigenThreadsPerModel=1,maxVisits=100,nnRandomize=false,"
            "nnCacheSizePowerOfTwo=18,nnMutexPoolSizePowerOfTwo=14,"
            "searchRandSeed=passing-audit,conservativePass=true"
        )
        process = GTPProcess(
            [
                str(KATAGO_BINARY),
                "gtp",
                "-config",
                str(KATAGO_CONFIG),
                "-model",
                str(model),
                "-override-config",
                overrides,
            ],
            root / "gtp.txt",
            root / "stderr.txt",
        )
        try:
            for number, (info, game, config, board) in enumerate(candidates, 1):
                process.command(f"boardsize {board.size}")
                process.command("clear_board")
                process.command(f"komi {config['komi']}")
                process.command("kata-set-rules tromp-taylor")
                for move in game["moves"]:
                    process.command(f"play {move['color']} {move['move']}")
                rows = _parse_board(process.command("showboard"), board.size)
                replayed = tuple(cell for row in reversed(rows) for cell in row)
                if replayed != board.board:
                    raise ValueError(f"replay board mismatch: {info}")
                actual = process.command("final_score")
                if result_score(actual) != result_score(game["result"]):
                    raise ValueError(f"recorded score mismatch: {info}, {actual}")
                # Only switch the *audit's* status estimator to human-friendly mode.
                # Ko, suicide, komi, final position and full history are unchanged.
                process.command("kata-set-rule friendlyPassOk true")
                dead = sorted(process.command("final_status_list dead").split())
                score = area_score(board, config["komi"], dead)
                margin = score if info["katago_color"] == "B" else -score
                results.append(
                    info
                    | {
                        "dead_stones": dead,
                        "cleaned_black_minus_white": score,
                        "cleaned_katago_margin": margin,
                        "flips_to_katago_win": margin > 0,
                        "changes_to_draw": margin == 0,
                    }
                )
                if number % 10 == 0 or number == len(candidates):
                    print(
                        f"{model.stem}: {number}/{len(candidates)}, "
                        f"{sum(r['flips_to_katago_win'] for r in results)} flips",
                        flush=True,
                    )
        finally:
            process.close()
    return {
        "model": model.name,
        "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "status_visits": 100,
        "candidates": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=(ROOT / "log"))
    parser.add_argument("--models", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, default=(ROOT / "data/audits/passing/passing_audit.json"))
    args = parser.parse_args()
    counts, native, candidates, differences = inventory(args.root)
    report = {
        "complete": False,
        "method": "KataGo v1.16.5 human-friendly final_status_list dead at 100 visits; "
        "remove estimated dead stones, then exact area scoring with original komi. "
        "These are engine estimates, not proofs of optimal-play outcomes.",
        "llm_counts": counts,
        "native_counts": native,
        "native_record_coverage": native_coverage(args.root),
        "literal_scoring_differences": differences,
        "judges": [],
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(judge, path.resolve(), candidates) for path in args.models
        ]
        for future in concurrent.futures.as_completed(futures):
            report["judges"].append(future.result())
            write_report(report, args.output)
    report["judges"].sort(key=lambda item: item["model"])
    add_summary(report)
    report["complete"] = True
    write_report(report, args.output)


def add_summary(report):
    sets = []
    for result in report["judges"]:
        flips = [r for r in result["candidates"] if r["flips_to_katago_win"]]
        result["summary"] = {
            "flips": len(flips),
            "flips_without_superko_violation": sum(
                not r["superko_violation_moves"] for r in flips
            ),
            "katago_passed_second": sum(r["katago_pass_was_second"] for r in flips),
            "losses_changed_to_draws": sum(
                r["changes_to_draw"] for r in result["candidates"]
            ),
        }
        sets.append({(r["run"], r["game"]) for r in flips})
    report["agreement"] = {
        "all_judges_flip": sorted(set.intersection(*sets)),
        "any_judge_flips": sorted(set.union(*sets)),
    }


if __name__ == "__main__":
    main()
