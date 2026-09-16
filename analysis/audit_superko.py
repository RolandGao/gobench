#!/usr/bin/env python3
"""Replay canonical LLM games under positional superko, without GTP.

Passes are exempt. Captures precede removal of a suicidal friendly group.
Continue along the recorded sequence after a violation to inventory subsequent
violations; only the first violation has an entirely legal preceding history.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import tempfile
from collections import Counter
from pathlib import Path

from gobench.paths import ROOT
from analysis.historical_fixtures import load_historical_games


COLS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"


class ReplayBoard:
    def __init__(self, size=9):
        self.size = size
        self.board = (".",) * (size * size)
        self.history = [self.board]
        self.seen = {self.board: [0]}
        self.neighbors = [
            tuple(
                yy * size + xx
                for xx, yy in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                if 0 <= xx < size and 0 <= yy < size
            )
            for y in range(size)
            for x in range(size)
        ]

    def group(self, board, point):
        stones, liberties, todo = {point}, set(), [point]
        while todo:
            for neighbor in self.neighbors[todo.pop()]:
                if board[neighbor] == ".":
                    liberties.add(neighbor)
                elif board[neighbor] == board[point] and neighbor not in stones:
                    stones.add(neighbor)
                    todo.append(neighbor)
        return stones, liberties

    def candidate(self, color, move):
        if color not in {"B", "W"}:
            raise ValueError(f"invalid color: {color}")
        if move == "pass":
            return self.board, 0, 0
        x, y = COLS.index(move[0]), int(move[1:]) - 1
        if not (0 <= x < self.size and 0 <= y < self.size):
            raise ValueError(f"off-board move: {move}")
        point = y * self.size + x
        if self.board[point] != ".":
            raise ValueError(f"occupied point: {move}")
        board = list(self.board)
        board[point] = color
        captured = 0
        for neighbor in self.neighbors[point]:
            if board[neighbor] not in {".", color}:
                group, liberties = self.group(board, neighbor)
                if not liberties:
                    captured += len(group)
                    for stone in group:
                        board[stone] = "."
        group, liberties = self.group(board, point)
        suicide = 0
        if not liberties:
            suicide = len(group)
            for stone in group:
                board[stone] = "."
        return tuple(board), captured, suicide

    def play(self, color, move):
        """Return violation details, while always advancing the recorded board."""
        board, captured, suicide = self.candidate(color, move)
        violation = None
        if move != "pass" and board in self.seen:
            simple_ko = (
                len(self.history) >= 2
                and board == self.history[-2]
                and board != self.board
                and captured == 1
                and suicide == 0
            )
            violation = {
                "kind": "simple_ko" if simple_ko else "other_positional_superko",
                "repeats_positions_after_moves": list(self.seen[board]),
                "captured_stones": captured,
                "suicide_stones": suicide,
            }
        self.board = board
        self.history.append(board)
        self.seen.setdefault(board, []).append(len(self.history) - 1)
        return violation


def audit(root):
    games, violations, errors, coverage_errors = [], [], [], []
    for run in sorted(root.glob("*/run.json")):
        config = json.loads(run.read_text())
        path = run.parent / "llm_games.jsonl"
        records = (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists() else []
        )
        results_path = run.parent / "results.csv"
        if results_path.exists():
            with results_path.open(newline="") as handle:
                results = {
                    int(row["game"]): row for row in csv.DictReader(handle)
                    if row["source"] not in {"katago_match", "uniform_random"}
                }
        else:
            results = {}
        if set(results) != {record["game"] for record in records}:
            coverage_errors.append(str(run.parent))
        for line, record in enumerate(records, 1):
            if sum(record[c].startswith("kata") for c in ("black", "white")) != 1:
                coverage_errors.append(f"unexpected matchup: {path}:{line}")
                continue
            if config.get("rules") != "tromp-taylor":
                raise ValueError(f"unsupported rules: {run}")
            llm_color = "W" if record["black"].startswith("kata") else "B"
            llm = record["white" if llm_color == "W" else "black"]
            info = {
                "run": run.parent.name, "game": record["game"],
                "log": str(path), "line": line, "llm": llm,
                "llm_color": llm_color, "result": record["result"],
            }
            board = ReplayBoard(config["board_size"])
            found = []
            for number, action in enumerate(record["moves"], 1):
                color, move = action["color"], action["move"]
                if (
                    color != ("B" if number % 2 else "W")
                    or action.get("number", number) != number
                ):
                    errors.append({
                        **info, "move_number": number, "error": "invalid turn/number"
                    })
                    break
                if move == "resign":
                    if number != len(record["moves"]):
                        errors.append({**info, "error": "moves after resignation"})
                    break
                try:
                    violation = board.play(color, move)
                except ValueError as exc:
                    errors.append({**info, "move_number": number, "error": str(exc)})
                    break
                if violation:
                    found.append({
                        **info, "move_number": number, "color": color, "move": move,
                        "actor": "llm" if color == llm_color else "katago",
                        "first_violation_in_game": not found, **violation,
                    })
            violations.extend(found)
            games.append({
                **info, "moves": len(record["moves"]), "violations": len(found)
            })
    first_violations = [v for v in violations if v["first_violation_in_game"]]
    summary = {
        "games": len(games), "runs": len({g["run"] for g in games}),
        "recorded_actions": sum(g["moves"] for g in games),
        "affected_games": sum(bool(g["violations"]) for g in games),
        "violations": len(violations),
        "violations_by_kind": dict(Counter(v["kind"] for v in violations)),
        "violations_by_actor": dict(Counter(v["actor"] for v in violations)),
        "first_violations_by_kind": dict(Counter(v["kind"] for v in first_violations)),
        "first_violations_by_actor": dict(Counter(v["actor"] for v in first_violations)),
        "games_with_simple_ko": len({
            (v["run"], v["game"]) for v in violations if v["kind"] == "simple_ko"
        }),
        "games_with_other_superko": len({
            (v["run"], v["game"]) for v in violations if v["kind"] != "simple_ko"
        }),
        "replay_errors": errors, "coverage_errors": coverage_errors,
    }
    return {"summary": summary, "games": games, "violations": violations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", type=Path, default=(ROOT / "log"))
    parser.add_argument("--output", type=Path, default=(ROOT / "data/audits/superko/superko_audit.json"))
    parser.add_argument(
        "--verify-katago", action="store_true",
        help="Cross-check boards and violations with local KataGo "
             "(KATAGO_BINARY/MODEL/CONFIG)",
    )
    args = parser.parse_args()
    report = audit(args.log_dir)
    if args.verify_katago:
        report["verification"] = verify_katago(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))
    if report["summary"]["replay_errors"] or report["summary"]["coverage_errors"]:
        raise SystemExit(1)


def verify_katago(report):
    """Check captures independently and compare superko with the NN legal mask.

    This deliberately uses raw GTP play to replay even the illegal continuations.
    The policy mask is inspected before play; play acceptance is NOT a legality
    check. At the first violation, also demonstrate that raw GTP play accepts
    the move. Bypass the production referee to inspect illegal continuations.
    """
    from gobench.game_engine import KataGoGameEngine, _parse_board

    checked = Counter()
    archived_games = None
    with tempfile.TemporaryDirectory(prefix="superko-audit-") as directory:
        with KataGoGameEngine(komi=7.0, log_dir=directory) as engine:
            version = engine._command("version")
            rules = json.loads(engine._command("kata-get-rules"))
            assert rules["ko"] == "POSITIONAL" and rules["suicide"] is True
            for info in report["games"]:
                path = ROOT / info["log"]
                if path.exists():
                    lines = path.read_text().splitlines()
                    record = json.loads(lines[info["line"] - 1])
                else:
                    if archived_games is None:
                        _, archived_games = load_historical_games()
                    record = archived_games[info["run"], info["game"]]
                engine._command("clear_board")
                board = ReplayBoard()
                first = True
                for action in record["moves"]:
                    color, move = action["color"], action["move"]
                    if move == "resign":
                        break
                    violation = board.play(color, move)
                    if violation:
                        raw = engine._command("kata-raw-nn 0").split()
                        offset = raw.index("policy") + 1
                        index = (9 - int(move[1:])) * 9 + COLS.index(move[0])
                        value = float(raw[offset + index])
                        assert math.isnan(value) or value < 0, (info, action, value)
                        checked["violations_masked_by_katago"] += 1
                        if first:
                            engine._command(f"play {color} {move}")
                            engine._command("undo")
                            checked["first_violations_accepted_by_gtp"] += 1
                            first = False
                    engine._command(f"play {color} {move}")
                    rows = _parse_board(engine._command("showboard"), 9)
                    actual = tuple(cell for row in reversed(rows) for cell in row)
                    assert actual == board.board, (info, action)
                    checked["boards_checked"] += 1
                checked["games_checked"] += 1
    return {"katago_version": version, "rules": rules, **checked}


if __name__ == "__main__":
    main()
