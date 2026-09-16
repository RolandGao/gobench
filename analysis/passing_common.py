"""Shared scoring, historical position loading, and fresh-search probes."""

import hashlib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path

from analysis.audit_superko import COLS, ReplayBoard
from analysis.historical_fixtures import load_historical_games
from gobench.game_engine import GTPProcess, _parse_board
from gobench.paths import ROOT
from gobench.strategies import KATAGO_BINARY, KATAGO_CONFIG, KATAGO_NETWORKS


def write_report(report, output):
    """Publish a complete JSON checkpoint, creating its output directory."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(output)


def area_score(board, komi, dead=()):
    """Black minus White, using literal Tromp–Taylor flood-fill scoring."""
    points = list(board.board)
    for move in dead:
        index = (int(move[1:]) - 1) * board.size + COLS.index(move[0])
        if points[index] == ".":
            raise ValueError(f"estimated dead stone {move} is empty")
        points[index] = "."
    counts = Counter(points)
    score = counts["B"] - counts["W"] - komi
    visited = set()
    for index, color in enumerate(points):
        if color != "." or index in visited:
            continue
        region, border, todo = set(), set(), [index]
        visited.add(index)
        while todo:
            point = todo.pop()
            region.add(point)
            for neighbor in board.neighbors[point]:
                if points[neighbor] != ".":
                    border.add(points[neighbor])
                elif neighbor not in visited:
                    visited.add(neighbor)
                    todo.append(neighbor)
        if border == {"B"}:
            score += len(region)
        elif border == {"W"}:
            score -= len(region)
    return score


def result_score(result):
    if result in {"0", "Draw", "Jigo"}:
        return 0.0
    return float(result[2:]) * (1 if result.startswith("B+") else -1)


def cases(root, audit):
    """Select consensus flips with entirely legal histories and original bots."""
    agreed = {tuple(pair) for pair in audit["agreement"]["all_judges_flip"]}
    result = []
    archived = None
    for info in audit["judges"][0]["candidates"]:
        if (info["run"], info["game"]) not in agreed:
            continue
        if info["superko_violation_moves"]:
            continue
        directory = root / info["run"]
        if not directory.exists() and root.resolve() == (ROOT / "log").resolve():
            if archived is None:
                archived = load_historical_games()
            configs, games = archived
            config = configs[info["run"]]
            game = games[info["run"], info["game"]]
        else:
            config = json.loads((directory / "run.json").read_text())
            game = next(
                g
                for line in (directory / "llm_games.jsonl").read_text().splitlines()
                if (g := json.loads(line))["game"] == info["game"]
            )
        bot = next(b for b in config["bots"] if b["name"] == info["katago_player"])
        network = next(s for s in KATAGO_NETWORKS if s.name == bot["network_name"])
        digest = hashlib.sha256(network.path.read_bytes()).hexdigest()
        if network.sha256 and digest != network.sha256:
            raise ValueError(f"Network hash mismatch: {network.path}")
        prefix = game["moves"][: info["katago_pass_move"] - 1]
        original = game["moves"][info["katago_pass_move"] - 1]
        assert original["move"] == "pass"
        assert original["color"] == info["katago_color"]
        result.append(
            dict(
                info=info,
                bot=bot,
                model=str(network.path),
                model_sha256=digest,
                size=config["board_size"],
                komi=config["komi"],
                moves=prefix,
            )
        )
    return result


def replay(process, case):
    # clear_cache alone does not clear GTP's recent win/loss history.
    process.command("clear_board")
    process.command("clear_cache")
    board = ReplayBoard(case["size"])
    for move in case["moves"]:
        if board.play(move["color"], move["move"]):
            raise ValueError("Illegal historical position")
        process.command(f"play {move['color']} {move['move']}")
    return board


def probe(case, budgets, repeats, conservative, full_budget):
    info, bot = case["info"], case["bot"]
    seed = f"passing-visits-{info['run']}-{info['game']}"
    with tempfile.TemporaryDirectory(prefix="gobench-visit-sweep-") as directory:
        root = Path(directory)
        overrides = {
            "logDir": str(root / "engine"),
            "logAllGTPCommunication": "false",
            "logSearchInfo": "false",
            "startupPrintMessageToStderr": "false",
            "numSearchThreads": 1,
            "numEigenThreadsPerModel": 1,
            "maxVisits": 1,
            "nnRandomize": "true",
            "nnRandSeed": seed,
            "searchRandSeed": seed,
            "nnCacheSizePowerOfTwo": 18,
            "nnMutexPoolSizePowerOfTwo": 14,
            "conservativePass": str(conservative).lower(),
            "chosenMoveTemperature": bot["chosen_move_temperature"],
            "chosenMoveTemperatureEarly": bot["chosen_move_temperature_early"],
            "ogsChatToStderr": "true",
        }
        if full_budget:
            overrides.update(
                searchFactorAfterOnePass=1,
                searchFactorAfterTwoPass=1,
                searchFactorWhenWinning=1,
            )
        process = GTPProcess(
            [
                str(KATAGO_BINARY),
                "gtp",
                "-config",
                str(KATAGO_CONFIG),
                "-model",
                case["model"],
                "-override-config",
                ",".join(f"{k}={v}" for k, v in overrides.items()),
            ],
            root / "protocol.txt",
            root / "stderr.txt",
        )
        rows = []
        try:
            process.command(f"boardsize {case['size']}")
            process.command(f"komi {case['komi']}")
            process.command("kata-set-rules tromp-taylor")
            board = replay(process, case)
            actual = _parse_board(process.command("showboard"), case["size"])
            assert tuple(p for row in reversed(actual) for p in row) == board.board
            # Passing leaves the board unchanged; verify this really loses.
            margin = area_score(board, case["komi"])
            margin *= 1 if info["katago_color"] == "B" else -1
            assert margin < 0
            with (root / "stderr.txt").open() as diagnostics:
                diagnostics.read()
                for budget in budgets:
                    process.command(f"kata-set-param maxVisits {budget}")
                    trials = []
                    for trial in range(repeats):
                        board = replay(process, case)
                        move = process.command(f"kata-search {info['katago_color']}")
                        stats = re.findall(
                            r"MALKOVICH:Visits (\d+) Winrate ([\d.]+)% "
                            r"ScoreLead ([-\d.]+)",
                            diagnostics.read(),
                        )
                        if len(stats) != 1:
                            raise ValueError(
                                f"Expected one search diagnostic, got {stats}"
                            )
                        visits, winrate, lead = stats[0]
                        if move.lower() != "resign":
                            assert not board.play(info["katago_color"], move)
                        trials.append(
                            dict(
                                trial=trial,
                                move=move,
                                actual_visits=int(visits),
                                winrate=float(winrate),
                                score_lead=float(lead),
                            )
                        )
                    row = dict(
                        max_visits=budget,
                        choices=dict(Counter(t["move"] for t in trials)),
                        actual_visits=dict(Counter(t["actual_visits"] for t in trials)),
                        trials=trials,
                    )
                    rows.append(row)
                    print(
                        json.dumps(
                            dict(
                                run=info["run"],
                                game=info["game"],
                                **{k: v for k, v in row.items() if k != "trials"},
                            )
                        ),
                        flush=True,
                    )
        finally:
            process.close()
    return case | {"seed": seed, "budgets": rows}
