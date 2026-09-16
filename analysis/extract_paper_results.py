#!/usr/bin/env python3
"""Build the portable data snapshot used by the current paper figures and tables."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import arena

from gobench.paths import ROOT


DEFAULT_RUN_SOURCE = (
    ROOT / "log" / "arena_20260830_062108_941863_ed7548b9" / "run.json"
)
DEFAULT_KATAGO_SOURCE = ROOT / "log" / "katago_selfplay_benchmark.json"
DEFAULT_PAPER_SOURCE = ROOT / "paper" / "gobench2.tex"
DEFAULT_OUTPUT = ROOT / "data" / "paper_results.json"

CPU_COST_USD_PER_HOUR = 0.071
MIN_PAPER_GAMES = 14
PAPER_PLAYER_ALIASES = {
    "gpt5.6-sol-low-codex-workspace-continual2": (
        "gpt5.6-sol-low-codex-workspace-continual"
    ),
    "gpt5.6-sol-high-codex-workspace-continual2": (
        "gpt5.6-sol-high-codex-workspace-continual"
    ),
}
TABLE_KATAGO_REFERENCES = (
    ("KataGo (fastest)", "kata1-b6c96-s175395328-d26788732"),
    (
        "KataGo (highest Elo)",
        "kata1-b28c512nbt-s8566598912-d4691918754-playouts600",
    ),
)
TEMP_PLAYER = re.compile(
    r"^(?P<base>kata1-.+)-temp-(?P<temperature>[0-9.]+)$"
)
SOL_EXECUTION_SUFFIXES = (
    "-api",
    "-codex-multi",
    "-codex-workspace",
    "-codex-workspace-continual",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path, data: str) -> dict[str, str]:
    return {"path": _relative(path), "sha256": _sha256(path), "data": data}


def _canonical_player(player: str) -> str:
    return PAPER_PLAYER_ALIASES.get(player, player)


def _report_ranks(report_source: Path, heading: str) -> dict[str, str]:
    """Read the paper-facing ranks from one comparison table in report.md."""
    text = report_source.read_text(encoding="utf-8")
    marker = f"## {heading}"
    try:
        section = text.split(marker, 1)[1]
    except IndexError as error:
        raise ValueError(f"Missing report section: {heading}") from error
    section = section.split("\n## ", 1)[0]
    ranks: dict[str, str] = {}
    row_pattern = re.compile(r"^\s*(\d+(?:-\d+)?)\s+(\S+)\s+")
    for line in section.splitlines():
        match = row_pattern.match(line)
        if match is not None:
            ranks[match.group(2)] = match.group(1)
    if not ranks:
        raise ValueError(f"No comparison rows in report section: {heading}")
    return ranks


def _rating_games(aggregate: dict[str, Any]) -> list[arena.GameRecord]:
    """Load the cumulative games used by the current arena rating fit."""
    games: list[arena.GameRecord] = []
    for run_dir_name in aggregate["past_run_dirs"]:
        results_path = ROOT / str(run_dir_name) / "results.csv"
        if not results_path.exists():
            raise FileNotFoundError(f"Missing cumulative results: {results_path}")
        with results_path.open(encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                score_black = float(row["score_black"])
                winner = str(row.get("winner") or "") or None
                games.append(
                    arena.GameRecord(
                        number=len(games) + 1,
                        batch=int(row["batch"]),
                        black=str(row["black"]),
                        white=str(row["white"]),
                        result=str(row["result"]),
                        winner_color=(
                            "B"
                            if score_black == 1.0
                            else "W"
                            if score_black == 0.0
                            else None
                        ),
                        winner=winner,
                        score_black=score_black,
                        reason="",
                        moves=(),
                        source=str(row.get("source") or "past_run"),
                        sgf="",
                    )
                )
    expected = int(aggregate["rating_games"])
    if len(games) != expected:
        raise ValueError(f"Expected {expected} rating games; found {len(games)}")
    return games


def _refit_rating_records(aggregate: dict[str, Any]) -> dict[str, Any]:
    """Reproduce the current two-stage arena fit for KataGo ratings."""
    games = _rating_games(aggregate)
    names = tuple(str(name) for name in aggregate["statistical_players"])
    initial = {
        str(row["player"]): float(row["elo"]) for row in aggregate["ratings"]
    }
    llm_names = {
        str(row["player"]) for row in aggregate["llm_comparisons"]
    }
    prior = (
        float(aggregate["active_player_prior_elo_mean"]),
        float(aggregate["active_player_prior_elo_sd"]),
    )
    arena._State.past_player_priors = {name: prior for name in llm_names}
    ratings, color = arena.fit_ratings_and_color_advantage(
        games, names, initial
    )
    records = arena.rating_records(
        games,
        names,
        ratings,
        color_advantage=color,
        include_color_uncertainty=True,
    )
    return {record.player: record for record in records}


def _comparison_row(
    source: dict[str, Any], canonical_player: str, display_name: str
) -> dict[str, Any]:
    return {
        "player": canonical_player,
        "source_player": str(source["player"]),
        "elo": float(source["elo"]),
        "elo_ci_95": float(source["elo_ci_95"]),
        "games": int(source["games"]),
        "moves": int(source["moves"]),
        "illegal_moves": int(source["illegal_moves"]),
        "api_problems": int(source["api_problems"]),
        "api_seconds_per_move": float(source["api_seconds_per_move"]),
        "cost_usd_per_move": float(source["cost_usd_per_move"]),
        "display_name": display_name,
    }


def _sorted_with_ranks(
    rows: list[dict[str, Any]], report_ranks: dict[str, str]
) -> list[dict[str, Any]]:
    rows.sort(key=lambda row: (-float(row["elo"]), str(row["player"])))
    missing = [
        row["source_player"]
        for row in rows
        if row["source_player"] not in report_ranks
    ]
    if missing:
        raise ValueError(f"Players missing from report comparison table: {missing}")
    return [
        {"rank": report_ranks[str(row["source_player"])], **row}
        for row in rows
    ]


def _api_llm_players(
    aggregate: dict[str, Any], report_ranks: dict[str, str]
) -> list[dict[str, Any]]:
    rows = []
    for source in aggregate["llm_comparisons"]:
        player = str(source["player"])
        if not player.endswith("-high-api"):
            continue
        if int(source["games"]) < MIN_PAPER_GAMES:
            continue
        rows.append(
            _comparison_row(source, player, player.removesuffix("-api"))
        )
    return _sorted_with_ranks(rows, report_ranks)


def _sol_harness_players(
    aggregate: dict[str, Any], report_ranks: dict[str, str]
) -> list[dict[str, Any]]:
    rows = []
    for source in aggregate["llm_comparisons"]:
        source_player = str(source["player"])
        player = _canonical_player(source_player)
        if not player.startswith("gpt5.6-sol-"):
            continue
        if int(source["games"]) < MIN_PAPER_GAMES:
            continue
        if not player.endswith(SOL_EXECUTION_SUFFIXES):
            continue
        rows.append(
            _comparison_row(
                source,
                player,
                player.removeprefix("gpt5.6-sol-"),
            )
        )
    if len({str(row["player"]) for row in rows}) != len(rows):
        raise ValueError("Paper aliases produced duplicate Sol harness players")
    return _sorted_with_ranks(rows, report_ranks)


def _measured_seconds_per_move(row: dict[str, Any]) -> float:
    timings = row["game_timings"]
    seconds = sum(float(game["total_genmove_seconds"]) for game in timings)
    moves = sum(int(game["moves"]) for game in timings)
    if moves <= 0:
        raise ValueError(f"No timed moves for {row['player']}")
    return seconds / moves


def _katago_players(
    ratings: dict[str, Any], katago_source: Path
) -> list[dict[str, Any]]:
    """Combine benchmark timings with rated base and temperature players."""
    source_rows = _read_json(katago_source)["results"]
    source_by_player = {str(row["player"]): row for row in source_rows}
    players: list[dict[str, Any]] = []
    base_results: dict[str, dict[str, Any]] = {}

    for row in source_rows:
        name = str(row["player"])
        rating = ratings[name]
        estimate = row.get("cpu_estimate")
        if isinstance(estimate, dict):
            timing_row = source_by_player[str(estimate["base_player"])]
            multiplier = float(estimate["playout_multiplier"])
        else:
            timing_row = row
            multiplier = 1.0
        seconds_per_move = _measured_seconds_per_move(timing_row) * multiplier
        result = {
            "player": name,
            "elo": float(rating.elo),
            "elo_ci_95": float((rating.ci_high - rating.ci_low) / 2),
            "games": int(rating.games),
            "seconds_per_move": seconds_per_move,
            "cost_usd_per_move": (
                seconds_per_move * CPU_COST_USD_PER_HOUR / 3600
            ),
            "timing_estimated": bool(row.get("timing_estimated", False)),
        }
        base_results[name] = result

    temp_by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name, rating in ratings.items():
        match = TEMP_PLAYER.fullmatch(name)
        if match is None:
            continue
        base_name = match.group("base")
        if base_name not in base_results:
            raise ValueError(f"No timed base player for {name}: {base_name}")
        base = base_results[base_name]
        if bool(base["timing_estimated"]):
            raise ValueError(f"Temperature base timing is estimated: {base_name}")
        temp_by_base[base_name].append(
            {
                "player": name,
                "elo": float(rating.elo),
                "elo_ci_95": float((rating.ci_high - rating.ci_low) / 2),
                "games": int(rating.games),
                "seconds_per_move": float(base["seconds_per_move"]),
                "cost_usd_per_move": float(base["cost_usd_per_move"]),
                "timing_estimated": False,
                "timing_inherited_from": base_name,
            }
        )

    for source_row in source_rows:
        name = str(source_row["player"])
        players.append(base_results[name])
        players.extend(
            sorted(
                temp_by_base.get(name, []),
                key=lambda result: float(
                    TEMP_PLAYER.fullmatch(str(result["player"])).group(
                        "temperature"
                    )
                ),
            )
        )
    return players


def _canonical_api_source(source: Any) -> Any:
    return "openai_agent" if source == "openai_codex_agent" else source


def _llm_games(
    aggregate: dict[str, Any], included_players: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Collect complete games for exactly the players represented in the paper."""
    source_llm_players = {
        str(row["player"]) for row in aggregate["llm_comparisons"]
    }
    selected_sources = [
        row
        for row in aggregate["llm_comparisons"]
        if _canonical_player(str(row["player"])) in included_players
    ]
    expected_player_moves = {
        str(row["player"]): int(row["moves"]) for row in selected_sources
    }
    expected_player_games = {
        str(row["player"]): int(row["games"]) for row in selected_sources
    }
    observed_player_games = {player: 0 for player in expected_player_games}
    observed_player_moves = {player: 0 for player in expected_player_moves}
    games: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []

    for run_dir_name in aggregate["past_run_dirs"]:
        run_dir = ROOT / str(run_dir_name)
        games_path = run_dir / "llm_games.jsonl"
        if not games_path.exists():
            continue
        sources.append(_source(games_path, "complete LLM-vs-KataGo games"))
        source_run = run_dir.name
        for line in games_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            game_players = {str(row["black"]), str(row["white"])}
            game_llms = game_players & source_llm_players
            if len(game_llms) != 1:
                raise ValueError(
                    f"Expected one LLM in {source_run} game {row['game']}; "
                    f"found {sorted(game_llms)}"
                )
            source_llm_player = game_llms.pop()
            llm_player = _canonical_player(source_llm_player)
            if llm_player not in included_players:
                continue
            katago_player = (game_players - {source_llm_player}).pop()
            moves = [
                {
                    "number": int(move["number"]),
                    "color": str(move["color"]),
                    "move": str(move["move"]),
                }
                for move in row["moves"]
            ]
            observed_player_games[source_llm_player] += 1
            llm_color = "B" if row["black"] == source_llm_player else "W"
            observed_player_moves[source_llm_player] += sum(
                move["color"] == llm_color for move in moves
            )
            winner = row.get("winner")
            if isinstance(winner, str):
                winner = _canonical_player(winner)
            games.append(
                {
                    "id": f"{source_run}:{int(row['game'])}",
                    "source_run": source_run,
                    "source_game": int(row["game"]),
                    "batch": int(row["batch"]),
                    "black": _canonical_player(str(row["black"])),
                    "white": _canonical_player(str(row["white"])),
                    "llm_player": llm_player,
                    "katago_player": katago_player,
                    "llm_color": llm_color,
                    "result": str(row["result"]),
                    "winner_color": row.get("winner_color"),
                    "winner": winner,
                    "score_black": float(row["score_black"]),
                    "reason": str(row["reason"]),
                    "api_source": _canonical_api_source(row.get("source")),
                    "llm_illegal_moves": int(
                        row.get(
                            "llm_illegal_moves",
                            row.get("openai_illegal_moves", 0),
                        )
                    ),
                    "llm_api_seconds": float(
                        row.get(
                            "llm_api_seconds",
                            row.get("openai_api_seconds", 0.0),
                        )
                    ),
                    "llm_cost_usd": float(
                        row.get(
                            "llm_cost_usd",
                            row.get("openai_cost_usd", 0.0),
                        )
                    ),
                    "moves": moves,
                    "source_llm_player": source_llm_player,
                }
            )

    expected_games = sum(expected_player_games.values())
    if len(games) != expected_games:
        raise ValueError(
            f"Expected {expected_games} cumulative LLM games; found {len(games)}"
        )
    mismatched_moves = {
        player: {
            "expected": expected_player_moves[player],
            "observed": observed_player_moves[player],
        }
        for player in expected_player_moves
        if observed_player_moves[player] != expected_player_moves[player]
    }
    if mismatched_moves:
        raise ValueError(f"LLM move counts do not match: {mismatched_moves}")
    mismatched_games = {
        player: {
            "expected": expected_player_games[player],
            "observed": observed_player_games[player],
        }
        for player in expected_player_games
        if observed_player_games[player] != expected_player_games[player]
    }
    if mismatched_games:
        raise ValueError(f"LLM game counts do not match: {mismatched_games}")
    return games, sources


def build_snapshot(
    run_source: Path = DEFAULT_RUN_SOURCE,
    katago_source: Path = DEFAULT_KATAGO_SOURCE,
    paper_source: Path = DEFAULT_PAPER_SOURCE,
) -> dict[str, Any]:
    run_source = run_source.resolve()
    katago_source = katago_source.resolve()
    paper_source = paper_source.resolve()
    report_source = run_source.with_name("report.md")
    for source in (run_source, report_source, katago_source, paper_source):
        if not source.exists():
            raise FileNotFoundError(source)

    aggregate = _read_json(run_source)
    ratings = _refit_rating_records(aggregate)
    api_players = _api_llm_players(
        aggregate, _report_ranks(report_source, "API-only LLM comparisons")
    )
    sol_players = _sol_harness_players(
        aggregate, _report_ranks(report_source, "All LLM comparisons")
    )
    katago_players = _katago_players(ratings, katago_source)
    included_players = {
        *(str(row["player"]) for row in api_players),
        *(str(row["player"]) for row in sol_players),
    }
    llm_games, game_sources = _llm_games(aggregate, included_players)
    katago_by_player = {str(row["player"]): row for row in katago_players}

    expected_counts = {
        "API LLM": (len(api_players), 8),
        "Sol harness": (len(sol_players), 11),
        "KataGo": (len(katago_players), 132),
        "complete game": (len(llm_games), 270),
    }
    wrong_counts = {
        label: {"found": found, "expected": expected}
        for label, (found, expected) in expected_counts.items()
        if found != expected
    }
    if wrong_counts:
        raise ValueError(f"Current paper dataset counts changed: {wrong_counts}")

    return {
        "schema_version": 4,
        "title": "GoBench paper results: API and agentic-harness comparisons",
        "sources": [
            _source(
                report_source,
                "current reported Elo ratings and LLM comparisons",
            ),
            _source(
                run_source,
                "current precise LLM comparison values and run provenance",
            ),
            _source(paper_source, "current figure and table definitions"),
            _source(katago_source, "results"),
            *game_sources,
        ],
        "derivation": {
            "canonical_player_names": (
                "Runtime-specific aliases are normalized to the model names "
                "used by the paper."
            ),
            "rank": (
                "Section-specific confidence-interval-overlap ranks are copied "
                "from the current arena report."
            ),
            "katago_ratings": (
                "KataGo ratings and confidence intervals are refit from the "
                "current arena run's cumulative game provenance."
            ),
            "katago_seconds_per_move": (
                "sum(total_genmove_seconds) / sum(moves); estimated playout "
                "players multiply their base network timing by the playout count."
            ),
            "katago_cpu_cost_usd_per_hour": CPU_COST_USD_PER_HOUR,
            "katago_cost_usd_per_move": (
                "seconds_per_move * katago_cpu_cost_usd_per_hour / 3600"
            ),
            "katago_temperature_timing": (
                "KataGo players ending in '-temp-X' use the measured "
                "seconds-per-move and derived cost of the otherwise identical "
                "player without the temperature suffix."
            ),
            "api_llm_selection": (
                "Completed API-only rows whose source player name ends with "
                "'-high-api'; the paper-facing name omits '-api'."
            ),
            "sol_harness_selection": (
                "Completed gpt5.6-sol API and Codex harness rows plotted in "
                "Figure 3; Prime isolated, Luna, single-turn Codex, and zero-game "
                "rows are excluded."
            ),
            "paper_player_aliases": PAPER_PLAYER_ALIASES,
            "comparison_precision": (
                "Unrounded LLM numeric values come from the current run.json; "
                "displayed paper values are rounded in gobench2.tex."
            ),
            "game_records": (
                "Complete past games are collected from the current arena run "
                "provenance for exactly the union of datasets.llm_players and "
                "datasets.sol_harness_players."
            ),
            "game_player_normalization": (
                "Raw continual2 identifiers are preserved in source_llm_player "
                "and normalized to continual in llm_player, black, white, and "
                "winner."
            ),
        },
        "datasets": {
            "llm_players": api_players,
            "katago_players": katago_players,
            "llm_vs_katago_games": llm_games,
            "sol_harness_players": sol_players,
        },
        "games": {
            "records": "#/datasets/llm_vs_katago_games",
            "count": len(llm_games),
            "move_count": sum(len(game["moves"]) for game in llm_games),
            "model_count": len(included_players),
            "board_size": int(aggregate["board_size"]),
            "komi": float(aggregate["komi"]),
            "rules": str(aggregate["rules"]),
            "max_moves": int(aggregate["max_moves"]),
            "included_players": sorted(included_players),
            "result_datasets": [
                "#/datasets/llm_players",
                "#/datasets/sol_harness_players",
            ],
            "inclusion_rule": (
                "Exactly the unique models represented in the current API and "
                "Sol harness figure/table datasets; no other LLM games are included."
            ),
            "moves_note": (
                "Each game's moves array contains the complete alternating "
                "board-move sequence for both players; result-row moves counts "
                "only LLM moves."
            ),
        },
        "figure_2": {
            "file": "paper/api_llm_elo_vs_cost.pdf",
            "caption": (
                "Elo versus cost per move for KataGo and API LLMs with reasoning "
                "effort set to high."
            ),
            "katago_players": "#/datasets/katago_players",
            "llm_players": "#/datasets/llm_players",
            "x": "cost_usd_per_move",
            "x_scale": "log",
            "y": "elo",
            "llm_y_error": "elo_ci_95",
            "reasoning_effort": "high",
            "llm_marker": "diamond",
            "panels": [
                {
                    "label": "a",
                    "selection": (
                        f"{len(katago_players)} KataGo players and "
                        f"{len(api_players)} API LLMs"
                    ),
                    "point_annotations": False,
                },
                {
                    "label": "b",
                    "selection": f"{len(api_players)} API LLMs",
                    "point_annotations": True,
                },
            ],
            "player_id_field": "player",
            "display_name_field": "display_name",
        },
        "table_2": {
            "caption": (
                "API LLM evaluation results with reasoning effort set to high "
                "and KataGo reference players."
            ),
            "llm_players": "#/datasets/llm_players",
            "columns": [
                "rank",
                "player",
                "elo",
                "elo_ci_95",
                "games",
                "moves",
                "illegal_moves",
                "api_problems",
                "api_seconds_per_move",
                "cost_usd_per_move",
            ],
            "katago_reference_players": [
                {"label": label, **katago_by_player[player]}
                for label, player in TABLE_KATAGO_REFERENCES
            ],
            "reference_note": (
                "The paper's 'KataGo (fastest)' row is the strongest b6c96 "
                "reference, not the minimum-time entry in the full dataset."
            ),
            "player_id_field": "player",
            "display_name_field": "display_name",
        },
        "figure_3": {
            "file": "paper/gpt5_6_sol_api_and_harnesses_elo_vs_cost.pdf",
            "caption": (
                "Elo versus measured cost per move for gpt5.6-sol in API mode "
                "and agentic harnesses."
            ),
            "players": "#/datasets/sol_harness_players",
            "x": "cost_usd_per_move",
            "x_scale": "log",
            "y": "elo",
            "y_error": "elo_ci_95",
            "line_and_color_by": "harness_or_execution_mode",
            "marker_by_reasoning_effort": {
                "low": "triangle",
                "high": "diamond",
                "max": "pentagon",
            },
            "point_annotations": False,
            "player_id_field": "player",
            "display_name_field": "display_name",
        },
        "table_3": {
            "caption": "gpt5.6-sol API and agentic-harness evaluation results.",
            "players": "#/datasets/sol_harness_players",
            "columns": [
                "rank",
                "player",
                "elo",
                "elo_ci_95",
                "games",
                "moves",
                "illegal_moves",
                "api_problems",
                "api_seconds_per_move",
                "cost_usd_per_move",
            ],
            "display_name_rule": (
                "Omit the common 'gpt5.6-sol-' prefix; display continual2 as "
                "continual."
            ),
            "player_id_field": "player",
            "display_name_field": "display_name",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        type=Path,
        default=DEFAULT_RUN_SOURCE,
        help="arena run.json used for ratings, comparisons, and game provenance",
    )
    parser.add_argument(
        "--katago-benchmark",
        type=Path,
        default=DEFAULT_KATAGO_SOURCE,
        help="KataGo timing benchmark JSON",
    )
    parser.add_argument(
        "--paper-source",
        type=Path,
        default=DEFAULT_PAPER_SOURCE,
        help="paper source included in snapshot provenance",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="output JSON snapshot",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="write indented JSON instead of the compact checked-in format",
    )
    args = parser.parse_args()

    snapshot = build_snapshot(
        run_source=args.run,
        katago_source=args.katago_benchmark,
        paper_source=args.paper_source,
    )
    if args.pretty:
        text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    else:
        text = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(text + "\n", encoding="utf-8")
    json.loads(temporary.read_text(encoding="utf-8"))
    temporary.replace(args.output)
    print(
        f"Saved {args.output} "
        f"({len(snapshot['datasets']['katago_players'])} KataGo, "
        f"{len(snapshot['datasets']['llm_players'])} API LLM, "
        f"{len(snapshot['datasets']['sol_harness_players'])} Sol harness)"
    )


if __name__ == "__main__":
    main()
