"""Portable historical results, using the extract_paper_results dataset schema."""

import csv
import contextlib
import hashlib
import json
import re
import shutil
import tempfile
from itertools import islice
from pathlib import Path


CPU_COST_USD_PER_HOUR = 0.071


@contextlib.contextmanager
def history_snapshot(past_dirs, root, log_root):
    """Freeze each committed prefix before fitting or exporting a live run.

    Writers replace results and move records before publishing run.json. Reading
    metadata first therefore gives a prefix present in every subsequent copy,
    even if another batch commits while we copy or fit the ratings.
    """
    with tempfile.TemporaryDirectory(prefix="arena-summary-inputs-") as temporary:
        snapshot_root = Path(temporary)
        snapshot_log = snapshot_root / log_root.relative_to(root)
        snapshot_log.mkdir(parents=True)
        snapshot_dirs = []
        for run in past_dirs:
            target = snapshot_root / run.relative_to(root)
            target.mkdir(parents=True)
            snapshot_dirs.append(target)
            # Freeze the commit boundary before any of its data files.
            shutil.copyfile(run / "run.json", target / "run.json")
            shutil.copyfile(run / "results.csv", target / "results.csv")
            for name in ("llm_games.jsonl", "llm_calls.jsonl"):
                source = run / name
                if not source.exists():
                    continue
                data = source.read_bytes()
                if name == "llm_calls.jsonl" and data and not data.endswith(b"\n"):
                    # The call ledger is appended during live games. Exclude
                    # only an incomplete final line caught during its write.
                    prefix, separator, tail = data.rpartition(b"\n")
                    try:
                        json.loads(tail)
                    except (ValueError, UnicodeDecodeError):
                        data = prefix + separator
                (target / name).write_bytes(data)
        benchmark = "katago_selfplay_benchmark.json"
        shutil.copyfile(log_root / benchmark, snapshot_log / benchmark)
        yield snapshot_root, snapshot_log, snapshot_dirs


def _source(path, root, data):
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "data": data,
    }


def katago_players(ratings, benchmark):
    timed = {row["player"]: row for row in benchmark["results"]}
    players = []
    for rating in ratings:
        name = rating["player"]
        base = re.sub(r"-temp-[0-9.]+$", "", name)
        row = timed.get(base)
        result = {
            **rating,
            "elo_ci_95": (rating["ci_high"] - rating["ci_low"]) / 2,
            "seconds_per_move": None,
            "cost_usd_per_move": None,
            "timing_estimated": None,
        }
        if row is None:
            if name != "kata1-random":
                raise ValueError(f"No KataGo timing benchmark for {name}")
            result["timing_note"] = "Random rating anchor; no benchmark timing."
        else:
            estimate = row.get("cpu_estimate")
            measured = timed[estimate["base_player"]] if estimate else row
            multiplier = float(estimate["playout_multiplier"]) if estimate else 1.0
            moves = sum(int(game["moves"]) for game in measured["game_timings"])
            if moves <= 0:
                raise ValueError(f"No timed moves for {name}")
            seconds = sum(float(game["total_genmove_seconds"])
                          for game in measured["game_timings"])
            seconds_per_move = seconds / moves * multiplier
            result.update(
                seconds_per_move=seconds_per_move,
                cost_usd_per_move=seconds_per_move * CPU_COST_USD_PER_HOUR / 3600,
                timing_estimated=bool(row.get("timing_estimated", False)),
                timing_backend=measured.get("timing_backend"),
            )
            if base != name:
                result["timing_inherited_from"] = base
            if estimate:
                result["cpu_estimate"] = estimate
        players.append(result)
    return players


def llm_games(past_dirs, comparisons, root):
    """Join full move records to the committed results prefix of each source."""
    expected = {row["player"]: row for row in comparisons}
    counts = {name: [0, 0] for name in expected}
    games, sources = [], []
    for run in past_dirs:
        metadata_path, csv_path = run / "run.json", run / "results.csv"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        sources.extend((
            _source(metadata_path, root, "historical run provenance and commit boundary"),
            _source(csv_path, root, "committed rating results and LLM statistics"),
        ))
        with csv_path.open(encoding="utf-8", newline="") as stream:
            committed = list(islice(csv.DictReader(stream), metadata["completed_games"]))
        if len(committed) != metadata["completed_games"]:
            raise ValueError(f"Missing committed results in {run}")
        selected = {
            int(row["game"]): row for row in committed
            if {row["black"], row["white"]} & expected.keys()
        }
        if not selected:
            continue
        path = run / "llm_games.jsonl"
        sources.append(_source(path, root, "complete committed LLM-vs-KataGo games"))
        found = set()
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                number = int(row["game"])
                if number not in selected:
                    continue
                if number in found:
                    raise ValueError(f"Duplicate game {number} in {path}")
                found.add(number)
                result = selected[number]
                if any(str(row[key]) != str(result[key])
                       for key in ("black", "white", "result")):
                    raise ValueError(f"Game {number} disagrees with results in {path}")
                llms = {row["black"], row["white"]} & expected.keys()
                if len(llms) != 1:
                    raise ValueError(f"Expected one LLM in {path} game {number}")
                llm = next(iter(llms))
                color = "B" if row["black"] == llm else "W"
                moves = [{"number": int(move["number"]), "color": str(move["color"]),
                          "move": str(move["move"])} for move in row["moves"]]
                if len(moves) != int(result["moves"]) or any(
                    move["number"] != index or not move["move"]
                    or move["color"] != ("B" if index % 2 else "W")
                    for index, move in enumerate(moves, 1)
                ):
                    raise ValueError(f"Incomplete move sequence in {path} game {number}")
                counts[llm][0] += 1
                counts[llm][1] += sum(move["color"] == color for move in moves)
                games.append({
                    "id": f"{run.name}:{number}", "source_run": run.name,
                    "source_game": number, "batch": int(row["batch"]),
                    "black": row["black"], "white": row["white"],
                    "llm_player": llm, "source_llm_player": llm,
                    "katago_player": row["white"] if color == "B" else row["black"],
                    "llm_color": color, "result": row["result"],
                    "winner_color": row.get("winner_color"), "winner": row.get("winner"),
                    "score_black": float(row["score_black"]), "reason": row["reason"],
                    "api_source": row.get("source"),
                    "llm_illegal_moves": int(row.get("llm_illegal_moves", row.get("openai_illegal_moves", 0))),
                    "llm_api_problems": int(row.get("llm_api_problems", 0)),
                    "llm_api_seconds": float(row.get("llm_api_seconds", row.get("openai_api_seconds", 0))),
                    "llm_cost_usd": float(row.get("llm_cost_usd", row.get("openai_cost_usd", 0))),
                    "moves": moves,
                })
        if found != selected.keys():
            raise ValueError(f"Missing complete games in {path}: {sorted(selected.keys() - found)}")
    for name, (game_count, move_count) in counts.items():
        if (game_count, move_count) != (expected[name]["games"], expected[name]["moves"]):
            raise ValueError(f"Historical game/move counts disagree with comparison for {name}")
    return games, sources


def build_results(*, root, log_root, past_dirs, ratings, comparisons, settings,
                  rating_games, color_advantage_curve):
    benchmark_path = log_root / "katago_selfplay_benchmark.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    rating_by_name = {row["player"]: row for row in ratings}
    llms = [{**rating_by_name[row["player"]], **row,
             "source_player": row["player"], "display_name": row["player"]}
            for row in comparisons]
    llm_names = {row["player"] for row in llms}
    katago = katago_players([row for row in ratings if row["player"] not in llm_names], benchmark)
    games, sources = llm_games(past_dirs, comparisons, root)
    return {
        "schema_version": 4,
        "title": "GoBench historical summary results",
        "sources": [_source(benchmark_path, root, "KataGo timing benchmark"), *sources],
        "derivation": {
            "canonical_player_names": "Original run player names are preserved; no paper aliases or model filters.",
            "rank": "Confidence-interval-overlap ranks across the included LLM comparison rows.",
            "ratings": "Elo and 95% confidence intervals use the same historical fit as report.txt.",
            "katago_seconds_per_move": "sum(total_genmove_seconds) / sum(moves); estimated playout players multiply base timing by the playout count.",
            "katago_cpu_cost_usd_per_hour": CPU_COST_USD_PER_HOUR,
            "katago_cost_usd_per_move": "seconds_per_move * katago_cpu_cost_usd_per_hour / 3600",
            "katago_temperature_timing": "Temperature variants inherit timing and cost from their base player.",
            "game_records": "Complete move records joined to each source run's committed results prefix; uncommitted games are excluded.",
        },
        "rating_games": rating_games,
        "color_advantage_curve": color_advantage_curve,
        "datasets": {
            "llm_players": llms,
            "katago_players": katago,
            "llm_vs_katago_games": games,
        },
        "games": {
            "records": "#/datasets/llm_vs_katago_games", "count": len(games),
            "move_count": sum(len(game["moves"]) for game in games),
            "model_count": len(llms), "included_players": sorted(llm_names),
            "result_datasets": ["#/datasets/llm_players"], **settings,
            "moves_note": "Complete board-move sequences for both colors; llm_players.moves counts only LLM moves.",
        },
    }
