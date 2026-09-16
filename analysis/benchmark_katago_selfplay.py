#!/usr/bin/env python3
"""Benchmark KataGo networks in sequential self-play.

The reported time is the sum of the network's ``genmove`` calls for both
colors. Referee/game-engine work, model startup, board synchronization,
scoring, and logging are deliberately outside the timer.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import statistics
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from gobench.game_engine import (
    GoEngineError,
    GoGameInterface,
    KataGoGameEngine,
    normalize_move,
)
from gobench.strategies import (
    KATAGO_BINARY,
    KATAGO_CONFIG,
    KATAGO_MODEL,
    KATAGO_NETWORKS_DIR,
    KataGoNetworkStrategy,
)

from gobench.paths import ROOT


DEFAULT_NETWORKS = (
    "kata1-b6c96-s175395328-d26788732",
    "kata1-b6c96-s4136960-d1510003",
    "kata1-b18c384nbt-s9761732864-d4253420187",
    "kata1-b28c512nbt-s8566598912-d4691918754",
)
DEFAULT_RATINGS = (
    ROOT
    / "log"
    / "arena_20260805_183049_592918_47e467f1"
    / "run.json"
)
RATING_ROW = re.compile(
    r"^(?P<player>kata1-\S+)\s+"
    r"(?P<elo>-?\d+)\s+±\s+(?P<ci>\d+)\s+"
    r"\S+\s+(?P<games>\d+)\s*$"
)
@dataclass(frozen=True)
class GameTiming:
    game: int
    moves: int
    black_genmove_seconds: float
    white_genmove_seconds: float
    total_genmove_seconds: float
    seconds_per_move: float
    result: str | None


class GenmoveTimedStrategy(KataGoNetworkStrategy):
    """Time only the network's GTP ``genmove`` command."""

    last_genmove_seconds = 0.0

    def choose_move(self, game: GoGameInterface) -> str:
        if self._process is None:
            self._start(game)
        assert self._process is not None

        history = list(game.get_move_history())
        if history[: len(self._synced_moves)] != self._synced_moves:
            raise GoEngineError(f"{self.name} is out of sync with the game")
        for color, move in history[len(self._synced_moves) :]:
            self._process.command(f"play {color} {move}")
            self._synced_moves.append((color, move))

        state = game.get_board_state()
        color = state.to_move
        started = time.perf_counter()
        response = self._process.command(f"genmove {color}")
        self.last_genmove_seconds = time.perf_counter() - started
        move = normalize_move(response, state.size)
        self._synced_moves.append((color, move))
        return move

    def clear_nn_cache(self) -> None:
        """Clear results from prior games without restarting the model."""
        if self._process is None:
            raise GoEngineError(f"{self.name} has not been started")
        self._process.command("clear_cache")


def _network_path(name_or_path: str) -> Path:
    supplied = Path(name_or_path).expanduser()
    if supplied.is_file():
        return supplied.resolve()
    for suffix in (".bin.gz", ".txt.gz"):
        candidate = KATAGO_NETWORKS_DIR / f"{name_or_path}{suffix}"
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"KataGo network not found: {name_or_path}")


def _network_name(path: Path) -> str:
    for suffix in (".bin.gz", ".txt.gz", ".gz"):
        if path.name.endswith(suffix):
            return path.name.removesuffix(suffix)
    return path.name


def _all_network_names() -> tuple[str, ...]:
    """Return every locally installed KataGo network checkpoint."""
    names = {
        _network_name(path)
        for pattern in ("*.bin.gz", "*.txt.gz")
        for path in KATAGO_NETWORKS_DIR.glob(pattern)
    }
    if not names:
        raise ValueError(f"No KataGo networks found in {KATAGO_NETWORKS_DIR}")
    return tuple(sorted(names))


def _benchmark_config(destination: Path) -> None:
    base = KATAGO_CONFIG.read_text(encoding="utf-8")
    base, replacements = re.subn(
        r"(?m)^resignThreshold\s*=\s*[-.\d]+\s*$",
        "resignThreshold = -0.95",
        base,
    )
    if replacements != 1:
        raise RuntimeError("could not set the arena resignation threshold")
    destination.write_text(
        base.rstrip()
        + "\n\n# Isolated benchmark settings matching the native arena.\n"
        + "chosenMoveTemperatureEarly = 0.5\n"
        + "chosenMoveTemperature = 0.1\n"
        + "nnMaxBatchSize = 32\n"
        + "nnRandomize = true\n"
        + "numEigenThreadsPerModel = 1\n",
        encoding="utf-8",
    )


def _reset(
    game: KataGoGameEngine,
    bot: GenmoveTimedStrategy,
    log_dir: Path,
    game_id: str,
) -> None:
    game.reset_for_game(game_id=game_id, log_dir=log_dir)
    bot.reset_for_game(game)
    bot.clear_nn_cache()


def _warm_up(
    game: KataGoGameEngine,
    bot: GenmoveTimedStrategy,
    moves: int,
) -> None:
    for _ in range(moves):
        if game.get_game_result().ended:
            break
        color = game.to_move
        outcome = game.do_action(bot.choose_move(game), color)
        if not outcome.success:
            raise RuntimeError(f"warm-up move was illegal: {outcome.reason}")


def _play_timed_game(
    game: KataGoGameEngine,
    bot: GenmoveTimedStrategy,
    game_number: int,
) -> GameTiming:
    color_seconds = {"B": 0.0, "W": 0.0}
    moves = 0
    while not game.get_game_result().ended:
        color = game.to_move
        move = bot.choose_move(game)
        color_seconds[color] += bot.last_genmove_seconds
        outcome = game.do_action(move, color)
        if not outcome.success:
            raise RuntimeError(f"timed move was illegal: {outcome.reason}")
        moves += 1

    total = color_seconds["B"] + color_seconds["W"]
    result = game.get_game_result()
    return GameTiming(
        game=game_number,
        moves=moves,
        black_genmove_seconds=color_seconds["B"],
        white_genmove_seconds=color_seconds["W"],
        total_genmove_seconds=total,
        seconds_per_move=total / moves,
        result=result.score,
    )


def benchmark_network(
    network: Path,
    *,
    games: int,
    warmup_moves: int,
    katago_binary: Path,
    max_visits: int,
    max_playouts: int | None,
    num_search_threads: int,
    max_game_moves: int,
    config_path: Path,
    log_dir: Path,
) -> dict[str, object]:
    name = _network_name(network)
    timings: list[GameTiming] = []
    with (
        KataGoGameEngine(
            board_size=9,
            komi=7.0,
            rules="tromp-taylor",
            katago_binary=KATAGO_BINARY,
            model_path=KATAGO_MODEL,
            config_path=KATAGO_CONFIG,
            log_dir=log_dir,
            game_id=f"{name}-warmup",
            max_moves=max_game_moves,
        ) as game,
        GenmoveTimedStrategy(
            network,
            name=name,
            katago_binary=katago_binary,
            config_path=config_path,
            log_dir=log_dir,
            max_visits=max_visits,
            max_playouts=max_playouts,
            num_search_threads=num_search_threads,
            delay_move_scale=0,
            delay_move_max=0,
        ) as bot,
    ):
        bot.reset_for_game(game)
        _warm_up(game, bot, warmup_moves)
        for game_number in range(1, games + 1):
            _reset(game, bot, log_dir, f"{name}-game-{game_number:03d}")
            timing = _play_timed_game(game, bot, game_number)
            timings.append(timing)
            print(
                f"{name}: game {game_number}/{games}, {timing.moves} moves, "
                f"{timing.total_genmove_seconds:.4f} genmove seconds",
                flush=True,
            )

    totals = [timing.total_genmove_seconds for timing in timings]
    per_moves = [timing.seconds_per_move for timing in timings]
    measured_game = statistics.mean(totals)
    measured_player = measured_game / 2
    player_name = (
        f"{name}-playouts{max_playouts}"
        if max_playouts is not None
        else name
    )
    return {
        "player": player_name,
        "network": name,
        "games": games,
        "isolated_mean_genmove_seconds_per_game_both_colors": measured_game,
        "isolated_mean_genmove_seconds_per_player_game": measured_player,
        "measured_median_genmove_seconds_per_game": statistics.median(totals),
        "measured_stdev_genmove_seconds_per_game": (
            statistics.stdev(totals) if len(totals) > 1 else 0.0
        ),
        "measured_mean_seconds_per_move": statistics.mean(per_moves),
        "game_timings": [asdict(timing) for timing in timings],
    }


def _katago_version(katago_binary: Path) -> str:
    output = subprocess.run(
        [str(katago_binary), "version"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout
    return output.splitlines()[0]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--network",
        action="append",
        dest="networks",
        help="network name or path; repeat for multiple networks",
    )
    parser.add_argument(
        "--all-networks",
        action="store_true",
        help="benchmark every unique network represented in --speed-file",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse compatible completed rows already present in --output",
    )
    parser.add_argument(
        "--finalize-paper",
        action="store_true",
        help=(
            "add ratings and 60/600-playout CPU estimates to an existing "
            "one-visit benchmark instead of running KataGo"
        ),
    )
    parser.add_argument(
        "--ratings",
        type=Path,
        default=DEFAULT_RATINGS,
        help="rating snapshot used by --finalize-paper",
    )
    parser.add_argument("--games", type=int, default=3)
    parser.add_argument("--warmup-moves", type=int, default=2)
    parser.add_argument(
        "--katago-binary",
        type=Path,
        default=KATAGO_BINARY,
        help="KataGo binary used by the timed player",
    )
    parser.add_argument(
        "--backend-label",
        default="default",
        help="descriptive label stored in the output, such as cpu or gpu",
    )
    parser.add_argument(
        "--max-visits",
        type=int,
        help=(
            "visit cap per move; defaults to 1 unless --max-playouts is set, "
            "in which case it defaults to a non-limiting 100000000"
        ),
    )
    parser.add_argument(
        "--max-playouts",
        type=int,
        help="playout cap per move; search reductions are disabled when set",
    )
    parser.add_argument("--num-search-threads", type=int, default=1)
    parser.add_argument(
        "--max-game-moves",
        type=int,
        default=1000,
        help="stop and score each benchmark game after this many moves",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "log" / "katago_selfplay_benchmark.json",
    )
    args = parser.parse_args(argv)
    if args.games < 1:
        parser.error("--games must be positive")
    if args.warmup_moves < 0:
        parser.error("--warmup-moves cannot be negative")
    if args.max_visits is not None and args.max_visits < 1:
        parser.error("--max-visits must be positive")
    if args.max_playouts is not None and args.max_playouts < 1:
        parser.error("--max-playouts must be positive")
    if args.num_search_threads < 1:
        parser.error("--num-search-threads must be positive")
    if args.max_game_moves < 1:
        parser.error("--max-game-moves must be positive")
    if args.all_networks and args.networks:
        parser.error("--all-networks and --network cannot be used together")
    if args.finalize_paper:
        return args
    args.max_visits = args.max_visits or (
        100_000_000 if args.max_playouts is not None else 1
    )
    args.katago_binary = args.katago_binary.expanduser().resolve()
    if not args.katago_binary.is_file():
        parser.error(f"--katago-binary does not exist: {args.katago_binary}")
    return args


def _paper_ratings(path: Path) -> dict[str, dict[str, int]]:
    if path.suffix == ".json":
        document = json.loads(path.read_text(encoding="utf-8"))
        ratings = {
            str(row["player"]): {
                "elo": round(float(row["elo"])),
                "elo_ci_95": round(
                    (float(row["ci_high"]) - float(row["ci_low"])) / 2
                ),
                "arena_games": int(row["games"]),
            }
            for row in document.get("ratings", [])
            if str(row.get("player", "")).startswith("kata1-")
        }
        if not ratings:
            raise ValueError(f"No KataGo ratings found in {path}")
        return ratings
    ratings = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = RATING_ROW.match(line)
        if match:
            ratings[match["player"]] = {
                "elo": int(match["elo"]),
                "elo_ci_95": int(match["ci"]),
                "arena_games": int(match["games"]),
            }
    if not ratings:
        raise ValueError(f"No KataGo ratings found in {path}")
    return ratings


def _clean_paper_base_result(
    result: dict[str, object], ratings: dict[str, dict[str, int]]
) -> dict[str, object]:
    player = str(result.get("player") or result["network"])
    cleaned = {
        "player": player,
        "network": result["network"],
        **ratings[player],
        "max_visits": 1,
        "max_playouts": None,
        "timing_backend": "cpu-eigenavx2",
        "timing_estimated": False,
    }
    cleaned.update(
        (key, value)
        for key, value in result.items()
        if key
        not in {
            "player",
            "network",
            "elo",
            "elo_ci_95",
            "arena_games",
            "max_visits",
            "max_playouts",
            "timing_backend",
            "timing_estimated",
            "speed_md_seconds_per_player_game",
            "speed_md_to_isolated_player_ratio",
        }
    )
    return cleaned


def _paper_playout_result(
    *,
    player: str,
    playouts: int,
    ratings: dict[str, dict[str, int]],
    base_result: dict[str, object],
) -> dict[str, object]:
    base_player = str(base_result["player"])
    base_seconds = float(
        base_result["isolated_mean_genmove_seconds_per_player_game"]
    )
    cpu_full_estimate = playouts * base_seconds
    return {
        "player": player,
        "network": base_result["network"],
        **ratings[player],
        "max_visits": 100_000_000,
        "max_playouts": playouts,
        "games": base_result["games"],
        "isolated_mean_genmove_seconds_per_game_both_colors": 2 * cpu_full_estimate,
        "isolated_mean_genmove_seconds_per_player_game": cpu_full_estimate,
        "timing_backend": "cpu-eigenavx2-estimated",
        "timing_estimated": True,
        "cpu_estimate": {
            "seconds_per_player_game": cpu_full_estimate,
            "method": (
                "same network's measured one-visit CPU time multiplied by "
                "the playout count"
            ),
            "base_player": base_player,
            "base_seconds_per_player_game": base_seconds,
            "playout_multiplier": playouts,
            "base_cpu_games": base_result["games"],
        },
    }


def finalize_paper_benchmark(benchmark: Path, ratings_path: Path) -> None:
    """Add ratings and estimated playout timings to a one-visit benchmark."""
    document = json.loads(benchmark.read_text(encoding="utf-8"))
    ratings = _paper_ratings(ratings_path)
    base_results = [
        _clean_paper_base_result(result, ratings)
        for result in document["results"]
        if result.get("max_playouts") is None
    ]
    base_by_player = {str(result["player"]): result for result in base_results}
    playout_results = []
    for playouts in (60, 600):
        suffix = f"-playouts{playouts}"
        for player in sorted(name for name in ratings if name.endswith(suffix)):
            base_player = player.removesuffix(suffix)
            if base_player not in base_by_player:
                raise ValueError(f"Missing one-visit CPU benchmark for {base_player}")
            playout_results.append(
                _paper_playout_result(
                    player=player,
                    playouts=playouts,
                    ratings=ratings,
                    base_result=base_by_player[base_player],
                )
            )

    document["method"] = (
        "Base players use measured CPU full-game timings from three isolated "
        "one-visit self-play games. Each playout player's CPU time is estimated "
        "as its playout count multiplied by the same network's measured "
        "one-visit CPU time. Timers include genmove calls only and report half "
        "of the two-color self-play total per player-game."
    )
    document["ratings_snapshot"] = {
        "source": str(ratings_path.relative_to(ROOT)),
        "arena_games": 318_148,
        "color_advantage_model": "average_elo_negative_exponential",
    }
    document["playout_benchmark"] = {
        "cpu": "KataGo Eigen/AVX2 build",
        "method": "one_visit_cpu_time_times_playout_count",
        "one_visit_cpu_games_per_network": 3,
        "cpu_full_game_values_are_estimates": True,
        "playout_multipliers": [60, 600],
    }
    document["requested_players"] = len(base_results) + len(playout_results)
    document["completed_players"] = len(base_results) + len(playout_results)
    document["results"] = base_results + playout_results
    _write_output(benchmark, document)
    print(
        f"Wrote {benchmark} with {len(base_results)} base and "
        f"{len(playout_results)} playout players"
    )


def _settings(args: argparse.Namespace) -> dict[str, object]:
    return {
        "board_size": 9,
        "komi": 7.0,
        "rules": "tromp-taylor",
        "backend_label": args.backend_label,
        "katago_binary": str(args.katago_binary),
        "max_visits": args.max_visits,
        "max_playouts": args.max_playouts,
        "num_search_threads": args.num_search_threads,
        "num_eigen_threads_per_model": 1,
        "max_game_moves": args.max_game_moves,
        "games_per_network": args.games,
        "warmup_moves": args.warmup_moves,
    }


def _load_resume_results(
    output_path: Path,
    settings: dict[str, object],
) -> dict[str, dict[str, object]]:
    if not output_path.is_file():
        return {}
    data = json.loads(output_path.read_text(encoding="utf-8"))
    if data.get("settings") != settings:
        raise ValueError(
            f"Cannot resume {output_path}: benchmark settings do not match"
        )
    results = data.get("results")
    if not isinstance(results, list):
        raise ValueError(f"Cannot resume {output_path}: invalid results")
    by_name: dict[str, dict[str, object]] = {}
    for result in results:
        if not isinstance(result, dict) or not isinstance(
            result.get("network"), str
        ):
            raise ValueError(f"Cannot resume {output_path}: invalid result row")
        by_name[str(result["network"])] = result
    return by_name


def _output_document(
    *,
    args: argparse.Namespace,
    results: list[dict[str, object]],
    requested_networks: int,
    katago_version: str,
) -> dict[str, object]:
    search_limit = (
        f"{args.max_playouts} playouts per move"
        if args.max_playouts is not None
        else f"{args.max_visits} visits per move"
    )
    return {
        "method": (
            f"Sequential 9x9 self-play at {search_limit}. Each game is measured "
            "once "
            "as Black genmove time plus White genmove time. Referee/game-engine "
            "time, model startup, synchronization, scoring, and logging excluded. "
            f"Games are scored after at most {args.max_game_moves} moves. "
            "The per-player comparison divides each self-play total by two because "
            "each self-play game contains one Black and one White player-game."
        ),
        "katago": katago_version,
        "machine": {
            "platform": platform.platform(),
            "allowed_cpu_ids": sorted(os.sched_getaffinity(0)),
        },
        "settings": _settings(args),
        "requested_networks": requested_networks,
        "completed_networks": len(results),
        "results": results,
    }


def _write_output(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.finalize_paper:
        finalize_paper_benchmark(args.output, args.ratings)
        return 0
    requested = (
        _all_network_names()
        if args.all_networks
        else tuple(args.networks or DEFAULT_NETWORKS)
    )
    network_paths = tuple(dict.fromkeys(map(_network_path, requested)))
    network_names = tuple(map(_network_name, network_paths))
    settings = _settings(args)
    completed = (
        _load_resume_results(args.output, settings) if args.resume else {}
    )
    completed = {
        name: result for name, result in completed.items() if name in network_names
    }
    katago_version = _katago_version(args.katago_binary)
    print(
        f"Benchmarking {len(network_names)} unique networks; "
        f"resuming {len(completed)} completed rows",
        flush=True,
    )

    with tempfile.TemporaryDirectory(prefix="gobench-selfplay-") as temporary:
        work = Path(temporary)
        config_path = work / "benchmark.cfg"
        _benchmark_config(config_path)
        for index, (name, network_path) in enumerate(
            zip(network_names, network_paths), 1
        ):
            if name in completed:
                continue
            completed[name] = benchmark_network(
                network_path,
                games=args.games,
                warmup_moves=args.warmup_moves,
                katago_binary=args.katago_binary,
                max_visits=args.max_visits,
                max_playouts=args.max_playouts,
                num_search_threads=args.num_search_threads,
                max_game_moves=args.max_game_moves,
                config_path=config_path,
                log_dir=work / "logs",
            )
            results = [completed[item] for item in network_names if item in completed]
            _write_output(
                args.output,
                _output_document(
                    args=args,
                    results=results,
                    requested_networks=len(network_names),
                    katago_version=katago_version,
                ),
            )
            print(
                f"Completed {len(results)}/{len(network_names)} networks "
                f"(schedule position {index})",
                flush=True,
            )

    results = [completed[name] for name in network_names]
    _write_output(
        args.output,
        _output_document(
            args=args,
            results=results,
            requested_networks=len(network_names),
            katago_version=katago_version,
        ),
    )
    print(f"Wrote complete benchmark to {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
