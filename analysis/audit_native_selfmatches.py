#!/usr/bin/env python3
"""Measure passing losses in native one-visit matches of identical players."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path


from arena import _sgf_property, _sgf_to_gtp, _split_sgf_collection, _unescape_sgf
from analysis.audit_passing import judge
from analysis.passing_common import area_score, result_score
from analysis.audit_superko import ReplayBoard
from gobench.game_engine import GTPProcess
from gobench.strategies import (
    KATAGO_BINARY,
    KATAGO_CONFIG,
    KATAGO_NETWORKS,
    KATAGO_NETWORKS_DIR,
)

from gobench.paths import ROOT

CALIBRATION = (ROOT / "log/arena_20260805_040447_246130_2072c54f/run.json")
TARGETS = (1000, 2000, 3300)
JUDGES = (
    KATAGO_NETWORKS_DIR / "kata1-b10c128-s501483520-d110698189.txt.gz",
    KATAGO_NETWORKS_DIR / "kata1-b18c384nbt-s9761732864-d4253420187.bin.gz",
)


def select_players():
    calibration = json.loads(CALIBRATION.read_text())
    bots = {b["name"]: b for b in calibration["bots"]}
    networks = {s.name: s for s in KATAGO_NETWORKS}
    eligible = [
        r
        for r in calibration["ratings"]
        if bots.get(r["player"], {}).get("max_visits") == 1
    ]
    players = []
    for target in TARGETS:
        rating = min(eligible, key=lambda r: abs(r["elo"] - target))
        bot = bots[rating["player"]]
        network = networks[bot["network_name"]]
        digest = hashlib.sha256(network.path.read_bytes()).hexdigest()
        if network.sha256 and digest != network.sha256:
            raise ValueError(f"Network hash mismatch: {network.path}")
        players.append(
            dict(
                target=target,
                rating=rating,
                bot=bot,
                model=str(network.path),
                model_sha256=digest,
            )
        )
    return players


def match_config(player, games):
    """Same settings as arena native calibration, two identical bot entries."""
    bot = player["bot"]
    return f"""logSearchInfo = false
logMoves = false
logGamesEvery = 10
logToStdout = false
numBots = 2
botName0 = {bot["name"]}-copy-a
botName1 = {bot["name"]}-copy-b
nnModelFile0 = {player["model"]}
nnModelFile1 = {player["model"]}
chosenMoveTemperatureEarly = {bot["chosen_move_temperature_early"]}
chosenMoveTemperature = {bot["chosen_move_temperature"]}
numGameThreads = 2
numGamesTotal = {games}
maxMovesPerGame = 1000
allowResignation = true
resignThreshold = -0.95
resignConsecTurns = 3
koRules = POSITIONAL
scoringRules = AREA
taxRules = NONE
multiStoneSuicideLegals = true
hasButtons = false
bSizes = 9
bSizeRelProbs = 1
komiAuto = false
komiMean = 7
handicapProb = 0.0
handicapCompensateKomiProb = 1.0
maxVisits = 1
numSearchThreads = 1
nnMaxBatchSize = 32
nnCacheSizePowerOfTwo = 18
nnMutexPoolSizePowerOfTwo = 14
nnRandomize = true
numEigenThreadsPerModel = 1
"""


def run_matches(directory, player, games):
    directory.mkdir(parents=True)
    config = directory / "match.cfg"
    config.write_text(match_config(player, games))
    args = [
        str(KATAGO_BINARY),
        "match",
        "-config",
        str(config),
        "-log-file",
        str(directory / "match.log"),
        "-sgf-output-dir",
        str(directory / "sgf"),
    ]
    (directory / "command.json").write_text(json.dumps(args, indent=2) + "\n")
    with (directory / "process.log").open("w") as log:
        subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=True)
    return collect(directory, player, games)


def collect(directory, player, expected_games):
    records, candidates = [], []
    names = {player["bot"]["name"] + suffix for suffix in ("-copy-a", "-copy-b")}
    for path in sorted((directory / "sgf").glob("*.sgfs")):
        for sgf in _split_sgf_collection(path.read_text()):
            assert {_sgf_property(sgf, p) for p in ("PB", "PW")} == names
            assert int(_sgf_property(sgf, "SZ")) == 9
            assert float(_sgf_property(sgf, "KM")) == 7
            number = len(records) + 1
            moves = [
                dict(
                    number=i,
                    color=m.group(1),
                    move=_sgf_to_gtp(_unescape_sgf(m.group(2))),
                )
                for i, m in enumerate(
                    re.finditer(r";([BW])\[((?:\\.|[^]])*)\]", sgf, re.DOTALL), 1
                )
            ]
            board = ReplayBoard(9)
            for move in moves:
                assert not board.play(move["color"], move["move"]), (path, number, move)
            try:
                result = _sgf_property(sgf, "RE")
            except RuntimeError:
                if len(moves) != 1000:
                    raise
                result = None
            two_passes = len(moves) >= 2 and all(
                m["move"] == "pass" for m in moves[-2:]
            )
            if result is None:
                reason = "move_cap"
            elif result.upper().endswith("+R"):
                reason = "resignation"
            elif result.lower() in {"void", "no result"}:
                reason = "no_result"
            elif two_passes:
                reason = "two_passes"
            else:
                reason = "automatic_end"
            record = dict(
                game=number,
                result=result,
                reason=reason,
                moves=moves,
                sgf_file=str(path),
                sgf=sgf,
            )
            records.append(record)
            if reason != "two_passes" or not result.startswith(("B+", "W+")):
                continue
            loser = "W" if result.startswith("B+") else "B"
            second = moves[-1]["color"] == loser
            info = dict(
                run=directory.name,
                game=number,
                katago_color=loser,
                katago_player=player["bot"]["name"],
                target_elo=player["target"],
                elo=player["rating"]["elo"],
                result=result,
                strict_black_minus_white=area_score(board, 7),
                superko_violation_moves=[],
                katago_pass_was_second=second,
                katago_pass_move=len(moves) - (not second),
            )
            candidates.append((info, record, {"komi": 7}, board))
    if len(records) != expected_games:
        raise ValueError(
            f"Expected {expected_games} games, got {len(records)}: {directory}"
        )
    (directory / "games.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records)
    )
    counts = dict(Counter(r["reason"] for r in records))
    print(
        f"Elo {player['rating']['elo']}: {len(records)} games, {counts}, "
        f"{len(candidates)} passing-loss candidates",
        flush=True,
    )
    return player | dict(
        games=len(records), endings=counts, passing_loss_candidates=len(candidates)
    ), candidates


def rescore_with_native_scorer(report, directory):
    """Retain pass-alive scoring after estimated removal, exactly as in match.

    With these area/no-tax/no-button/no-handicap rules, terminal scoring depends
    only on the board and komi. Verify that by rescoring every original board
    against its saved native result before evaluating either counterfactual.
    """
    boards = {}
    records = {}
    for player in report["players"]:
        level = f"elo_{player['target']}"
        for line in (directory / level / "games.jsonl").read_text().splitlines():
            game = json.loads(line)
            records[level, game["game"]] = game
    overrides = (
        f"logDir={directory}/rescore-engine,logAllGTPCommunication=false,"
        "logSearchInfo=false,startupPrintMessageToStderr=false,maxVisits=1,"
        "numSearchThreads=1,numEigenThreadsPerModel=1,"
        "nnCacheSizePowerOfTwo=18,nnMutexPoolSizePowerOfTwo=14"
    )
    process = GTPProcess(
        [
            str(KATAGO_BINARY),
            "gtp",
            "-config",
            str(KATAGO_CONFIG),
            "-model",
            report["players"][0]["model"],
            "-override-config",
            overrides,
        ],
        directory / "rescore.gtp.txt",
        directory / "rescore.stderr.txt",
    )
    cache = {}

    def score(points):
        if points not in cache:
            placements = " ".join(
                f"{color} {'ABCDEFGHJ'[i % 9]}{i // 9 + 1}"
                for i, color in enumerate(points)
                if color != "."
            )
            process.command(
                f"set_position {placements}" if placements else "clear_board"
            )
            process.command("play B pass")
            process.command("play W pass")
            cache[points] = result_score(process.command("final_score"))
        return cache[points]

    try:
        process.command("boardsize 9")
        process.command("komi 7")
        process.command("kata-set-rules tromp-taylor")
        for j in report["judges"]:
            for c in j["candidates"]:
                key = c["run"], c["game"]
                if key not in boards:
                    board = ReplayBoard(9)
                    for move in records[key]["moves"]:
                        assert not board.play(move["color"], move["move"])
                    boards[key] = board.board
                    assert score(board.board) == result_score(c["result"]), key
                points = list(boards[key])
                for move in c["dead_stones"]:
                    i = (int(move[1:]) - 1) * 9 + "ABCDEFGHJ".index(move[0])
                    assert points[i] != ".", (key, move)
                    points[i] = "."
                cleaned = score(tuple(points))
                margin = cleaned if c["katago_color"] == "B" else -cleaned
                c.setdefault(
                    "literal_cleaned_black_minus_white", c["cleaned_black_minus_white"]
                )
                c["cleaned_black_minus_white"] = cleaned
                c["cleaned_katago_margin"] = margin
                c["flips_to_katago_win"] = margin > 0
                c["changes_to_draw"] = margin == 0
    finally:
        process.close()
    report["counterfactual_scorer"] = (
        "KataGo terminal area scorer including pass-alive removal"
    )
    report["original_terminal_scores_reverified"] = len(boards)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    if args.games < 1:
        parser.error("games must be positive")
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d_%H%M%S_%f")
    directory = (
        args.output or (ROOT / "untracked_log") / f"arena_{stamp}_katago_selfmatches"
    )
    if directory.exists() and not args.audit_only:
        parser.error("Output directory already exists; use --audit-only to analyze it")
    directory.mkdir(parents=True, exist_ok=True)
    players = select_players()
    report = dict(
        complete=False,
        started_at=dt.datetime.now(dt.UTC).isoformat(),
        directory=str(directory),
        calibration_source=str(CALIBRATION),
        engine_version=subprocess.check_output(
            [str(KATAGO_BINARY), "version"], text=True
        ).strip(),
        visits_per_move=1,
        games_per_level=args.games,
        players=players,
        matches=[],
        judges=[],
    )
    output = directory / "audit.json"
    if args.audit_only and output.exists():
        report = json.loads(output.read_text())
        if report["games_per_level"] != args.games:
            parser.error("--games must match the saved experiment")
        players = report["players"]
        report["complete"] = False
        report["matches"] = []
    output.write_text(json.dumps(report, indent=2) + "\n")
    candidates = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        work = collect if args.audit_only else run_matches
        futures = [
            pool.submit(work, directory / f"elo_{p['target']}", p, args.games)
            for p in players
        ]
        for future in concurrent.futures.as_completed(futures):
            match, found = future.result()
            report["matches"].append(match)
            candidates.extend(found)
            output.write_text(json.dumps(report, indent=2) + "\n")
    report["matches"].sort(key=lambda m: m["target"])
    candidates.sort(key=lambda c: (c[0]["target_elo"], c[0]["game"]))
    existing = {j["model"]: j for j in report["judges"]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = []
        for model in JUDGES:
            previous = existing.get(model.name, {}).get("candidates", [])
            done = {(c["run"], c["game"]) for c in previous}
            remaining = [
                c for c in candidates if (c[0]["run"], c[0]["game"]) not in done
            ]
            if not candidates and model.name not in existing:
                empty = dict(
                    model=model.name,
                    sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
                    status_visits=100,
                    candidates=[],
                )
                report["judges"].append(empty)
                existing[model.name] = empty
            # Split each model's audit so both CPUs remain useful after the
            # smaller judging network finishes. Completed chunks are resumable.
            for chunk in (remaining[::2], remaining[1::2]):
                if chunk:
                    futures.append(pool.submit(judge, model, chunk))
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result["model"] in existing:
                existing[result["model"]]["candidates"].extend(result["candidates"])
            else:
                report["judges"].append(result)
                existing[result["model"]] = result
            output.write_text(json.dumps(report, indent=2) + "\n")
    for j in report["judges"]:
        j["candidates"].sort(key=lambda c: (c["target_elo"], c["game"]))
        assert len(j["candidates"]) == len(candidates)
    rescore_with_native_scorer(report, directory)
    flags = [
        {(c["run"], c["game"]) for c in j["candidates"] if c["flips_to_katago_win"]}
        for j in report["judges"]
    ]
    consensus = set.intersection(*flags)
    report["consensus_flips"] = sorted(consensus)
    report["judge_disagreements"] = sorted(set.union(*flags) - consensus)
    for match in report["matches"]:
        match["confirmed_passing_losses"] = sum(
            run == f"elo_{match['target']}" for run, _ in consensus
        )
    report["complete"] = True
    report["finished_at"] = dt.datetime.now(dt.UTC).isoformat()
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["matches"], indent=2), flush=True)
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    main()
