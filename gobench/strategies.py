#!/usr/bin/env python3
"""Example strategies and a random-vs-random game runner."""

from __future__ import annotations

import hashlib
import random
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from gobench.katago_networks import BINARY_NETWORK_NAMES, KATAGO_NETWORK_MANIFEST
from gobench.game_engine import (
    GTPProcess,
    GameResult,
    GoEngineError,
    GoGameInterface,
    KataGoGameEngine,
    normalize_move,
)

from gobench.paths import ROOT


# Edit these values to configure the random-vs-random game.
BOARD_SIZE = 9
RANDOM_SEED: int | None = None
KATAGO_VERSION = "1.16.5"
KATAGO_HOME = ROOT / f".venv/katago/v{KATAGO_VERSION}-eigenavx2"
KATAGO_APPIMAGE = KATAGO_HOME / "katago"
KATAGO_BINARY = KATAGO_HOME / "squashfs-root/AppRun"
KATAGO_MODEL = KATAGO_HOME / "lionffen_b6c64_3x3_v10.txt.gz"
KATAGO_CONFIG = KATAGO_HOME / "default_gtp.cfg"
KATAGO_CUDA_RELEASE = "cuda12.8-cudnn9.8.0"
KATAGO_CUDA_HOME = ROOT / f".venv/katago/v{KATAGO_VERSION}-{KATAGO_CUDA_RELEASE}"
KATAGO_CUDA_APPIMAGE = KATAGO_CUDA_HOME / "katago"
KATAGO_CUDA_BINARY = KATAGO_CUDA_HOME / "squashfs-root/AppRun"
LOG_DIR = ROOT / "gtp_logs"
MAX_MOVES: int | None = None
NETWORK_MAX_VISITS = 1
NETWORK_NUM_SEARCH_THREADS = 1
NETWORK_DELAY_MOVE_SCALE = 0
NETWORK_DELAY_MOVE_MAX = 0

# Pinned official downloads used when the files above are not installed yet.
KATAGO_ARCHIVE = (
    KATAGO_HOME / f"katago-v{KATAGO_VERSION}-eigenavx2-linux-x64.zip"
)
KATAGO_ARCHIVE_URL = (
    f"https://github.com/lightvector/KataGo/releases/download/v{KATAGO_VERSION}/"
    f"katago-v{KATAGO_VERSION}-eigenavx2-linux-x64.zip"
)
KATAGO_ARCHIVE_SHA256 = (
    "ffb39c5af6eb9d4f344f058649bcec2069a26c44d26dea5b3a00f785f3437468"
)
KATAGO_CUDA_ARCHIVE = KATAGO_CUDA_HOME / (
    f"katago-v{KATAGO_VERSION}-{KATAGO_CUDA_RELEASE}-linux-x64.zip"
)
KATAGO_CUDA_ARCHIVE_URL = (
    f"https://github.com/lightvector/KataGo/releases/download/v{KATAGO_VERSION}/"
    f"katago-v{KATAGO_VERSION}-{KATAGO_CUDA_RELEASE}-linux-x64.zip"
)
KATAGO_CUDA_ARCHIVE_SHA256 = (
    "a9269f5fe4203eab4e70db3a00b180c29696ddde37f5deec94b952f9e9acdd47"
)
KATAGO_MODEL_URL = (
    "https://media.katagotraining.org/uploaded/networks/models_extra/"
    "lionffen_b6c64_3x3_v10.txt.gz"
)
KATAGO_MODEL_SHA256 = (
    "2d728ee0ae1fbeab264e682d60d3c6665aa566db559c28ef6d63dabb92ed56dc"
)
KATAGO_NETWORKS_DIR = ROOT / ".venv/katago/networks/kata1"
KATAGO_NETWORK_BASE_URL = (
    "https://media.katagotraining.org/uploaded/networks/models/kata1"
)


@dataclass(frozen=True)
class NetworkSpec:
    name: str
    rating: float
    sha256: str | None
    file_size: int
    download_url: str | None = None
    file_name: str | None = None

    @property
    def suffix(self) -> str:
        return ".bin.gz" if self.name in BINARY_NETWORK_NAMES else ".txt.gz"

    @property
    def path(self) -> Path:
        file_name = (
            self.file_name
            if self.file_name is not None
            else f"{self.name}{self.suffix}"
        )
        return KATAGO_NETWORKS_DIR / file_name

    @property
    def url(self) -> str:
        return (
            self.download_url
            if self.download_url is not None
            else f"{KATAGO_NETWORK_BASE_URL}/{self.name}{self.suffix}"
        )


KATAGO_NETWORKS = tuple(
    NetworkSpec(name, rating, sha256, file_size)
    for name, rating, sha256, file_size in KATAGO_NETWORK_MANIFEST
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(
    url: str,
    destination: Path,
    expected_sha256: str | None,
    expected_size: int | None = None,
) -> None:
    if destination.is_file():
        size_matches = (
            expected_size is None or destination.stat().st_size == expected_size
        )
        if size_matches and (
            expected_sha256 is None or _sha256(destination) == expected_sha256
        ):
            return

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    print(f"Downloading {destination.name}...", flush=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "GoBench/1.0"}
    )
    try:
        with urllib.request.urlopen(request) as response, temporary.open("wb") as out:
            shutil.copyfileobj(response, out)
    except (OSError, urllib.error.URLError) as exc:
        temporary.unlink(missing_ok=True)
        raise GoEngineError(f"could not download {url}: {exc}") from exc

    actual_size = temporary.stat().st_size
    if expected_size is not None and actual_size != expected_size:
        temporary.unlink(missing_ok=True)
        raise GoEngineError(
            f"size mismatch for {destination.name}: "
            f"expected {expected_size}, got {actual_size}"
        )
    if expected_sha256 is not None:
        actual_sha256 = _sha256(temporary)
        if actual_sha256 != expected_sha256:
            temporary.unlink(missing_ok=True)
            raise GoEngineError(
                f"checksum mismatch for {destination.name}: {actual_sha256}"
            )
    temporary.replace(destination)


def ensure_katago_installed() -> None:
    """Install and verify the pinned KataGo build and referee model.

    This deliberately uses a versioned release URL and fixed SHA-256 hashes.
    It never queries GitHub's ``latest`` release, so future releases cannot
    change the engine or model used by this benchmark.
    """
    KATAGO_HOME.mkdir(parents=True, exist_ok=True)
    if not KATAGO_BINARY.is_file() or not KATAGO_CONFIG.is_file():
        _download(KATAGO_ARCHIVE_URL, KATAGO_ARCHIVE, KATAGO_ARCHIVE_SHA256)
        try:
            with zipfile.ZipFile(KATAGO_ARCHIVE) as archive:
                archive.extract("katago", KATAGO_HOME)
                archive.extract("default_gtp.cfg", KATAGO_HOME)
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            raise GoEngineError(f"could not extract KataGo: {exc}") from exc
        KATAGO_APPIMAGE.chmod(0o755)
        try:
            subprocess.run(
                [str(KATAGO_APPIMAGE), "--appimage-extract"],
                cwd=KATAGO_HOME,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            raise GoEngineError(f"could not unpack KataGo AppImage: {detail}") from exc
        KATAGO_BINARY.chmod(0o755)
        KATAGO_APPIMAGE.unlink(missing_ok=True)
        KATAGO_ARCHIVE.unlink(missing_ok=True)
    _download(KATAGO_MODEL_URL, KATAGO_MODEL, KATAGO_MODEL_SHA256)

    try:
        version = subprocess.run(
            [str(KATAGO_BINARY), "version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GoEngineError(f"could not verify KataGo version: {exc}") from exc
    if f"KataGo v{KATAGO_VERSION}\n" not in version.replace("\r\n", "\n"):
        raise GoEngineError(
            f"expected KataGo v{KATAGO_VERSION}, got: {version.splitlines()[0]}"
        )


def ensure_katago_cuda_installed() -> None:
    """Install and verify the pinned CUDA 12.8/cuDNN 9.8 KataGo build."""
    KATAGO_CUDA_HOME.mkdir(parents=True, exist_ok=True)
    if not KATAGO_CUDA_BINARY.is_file():
        _download(
            KATAGO_CUDA_ARCHIVE_URL,
            KATAGO_CUDA_ARCHIVE,
            KATAGO_CUDA_ARCHIVE_SHA256,
        )
        try:
            with zipfile.ZipFile(KATAGO_CUDA_ARCHIVE) as archive:
                archive.extract("katago", KATAGO_CUDA_HOME)
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            raise GoEngineError(f"could not extract CUDA KataGo: {exc}") from exc
        KATAGO_CUDA_APPIMAGE.chmod(0o755)
        try:
            subprocess.run(
                [str(KATAGO_CUDA_APPIMAGE), "--appimage-extract"],
                cwd=KATAGO_CUDA_HOME,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            raise GoEngineError(
                f"could not unpack CUDA KataGo AppImage: {detail}"
            ) from exc
        KATAGO_CUDA_BINARY.chmod(0o755)
        KATAGO_CUDA_APPIMAGE.unlink(missing_ok=True)
        KATAGO_CUDA_ARCHIVE.unlink(missing_ok=True)

    try:
        version = subprocess.run(
            [str(KATAGO_CUDA_BINARY), "version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
        ).stdout.replace("\r\n", "\n")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GoEngineError(f"could not verify CUDA KataGo: {exc}") from exc
    if f"KataGo v{KATAGO_VERSION}\n" not in version or "Using CUDA backend\n" not in version:
        raise GoEngineError(
            "expected the pinned CUDA KataGo build, got: "
            + "; ".join(version.splitlines()[:4])
        )


def ensure_arena_networks(
    networks: Sequence[NetworkSpec] = KATAGO_NETWORKS,
) -> None:
    """Download and verify the requested pinned KataGo arena networks."""
    for network in networks:
        _download(
            network.url,
            network.path,
            network.sha256,
            network.file_size,
        )


class Strategy(Protocol):
    """Any move-selection policy can implement this one-method interface."""

    name: str

    def choose_move(self, game: GoGameInterface) -> str:
        """Choose one move without changing the game."""


class RandomStrategy:
    """Uniformly choose among all legal point moves and pass."""

    def __init__(self, seed: int | None = None, name: str = "random") -> None:
        self.name = name
        self._random = random.Random(seed)

    def choose_move(self, game: GoGameInterface) -> str:
        legal_moves, _ko_illegal_moves = game.get_possible_moves()
        if not legal_moves:
            raise RuntimeError("strategy was asked to move after the game ended")
        return self._random.choice(legal_moves)


class KataGoNetworkStrategy:
    """A fixed-search KataGo strategy powered by a specified network file."""

    def __init__(
        self,
        network: str | Path,
        *,
        name: str | None = None,
        katago_binary: str | Path = KATAGO_BINARY,
        config_path: str | Path = KATAGO_CONFIG,
        log_dir: str | Path = LOG_DIR,
        max_visits: int = NETWORK_MAX_VISITS,
        max_playouts: int | None = None,
        num_search_threads: int = NETWORK_NUM_SEARCH_THREADS,
        delay_move_scale: float = NETWORK_DELAY_MOVE_SCALE,
        delay_move_max: float = NETWORK_DELAY_MOVE_MAX,
    ) -> None:
        if max_visits < 1:
            raise ValueError("max_visits must be positive")
        if max_playouts is not None and max_playouts < 1:
            raise ValueError("max_playouts must be positive")
        if num_search_threads < 1:
            raise ValueError("num_search_threads must be positive")
        if delay_move_scale < 0 or delay_move_max < 0:
            raise ValueError("move delay settings cannot be negative")
        self.network_path = Path(network).expanduser().resolve()
        network_name = self.network_path.name
        for suffix in (".txt.gz", ".bin.gz", ".gz"):
            if network_name.endswith(suffix):
                network_name = network_name.removesuffix(suffix)
                break
        self.name = name or network_name
        self.katago_binary = Path(katago_binary).expanduser().resolve()
        self.config_path = Path(config_path).expanduser().resolve()
        self.log_dir = Path(log_dir).expanduser().resolve()
        self.max_visits = max_visits
        self.max_playouts = max_playouts
        self.num_search_threads = num_search_threads
        self.delay_move_scale = delay_move_scale
        self.delay_move_max = delay_move_max
        self._process: GTPProcess | None = None
        self._synced_moves: list[tuple[str, str]] = []

    def _start(self, game: GoGameInterface) -> None:
        if not self.network_path.is_file():
            raise GoEngineError(f"KataGo network does not exist: {self.network_path}")
        state = game.get_board_state()
        komi = float(getattr(game, "komi", 7.5))
        rules = str(getattr(game, "rules", "tromp-taylor"))
        session_id = f"{self.name}-{uuid.uuid4().hex[:8]}"
        internal_log_dir = self.log_dir / f"{session_id}.katago"
        search_limits = f"maxVisits={self.max_visits},"
        if self.max_playouts is not None:
            search_limits += (
                f"maxPlayouts={self.max_playouts},"
                "searchFactorAfterOnePass=1,searchFactorAfterTwoPass=1,"
                "searchFactorWhenWinning=1,"
            )
        args = [
            str(self.katago_binary),
            "gtp",
            "-model",
            str(self.network_path),
            "-config",
            str(self.config_path),
            "-override-config",
            (
                f"logDir={internal_log_dir},logToStderr=false,"
                "logAllGTPCommunication=false,startupPrintMessageToStderr=false,"
                + search_limits
                + f"numSearchThreads={self.num_search_threads},"
                + f"delayMoveScale={self.delay_move_scale},"
                + f"delayMoveMax={self.delay_move_max}"
            ),
        ]
        self._process = GTPProcess(
            args,
            self.log_dir / f"{session_id}.gtp.txt",
            self.log_dir / f"{session_id}.stderr.txt",
        )
        try:
            self._process.command(f"boardsize {state.size}")
            self._process.command("clear_board")
            self._process.command(f"komi {komi:g}")
            self._process.command(f"kata-set-rules {rules}")
        except Exception:
            self.close()
            raise

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
        move = normalize_move(
            self._process.command(f"genmove {color}"), state.size
        )
        self._synced_moves.append((color, move))
        return move

    def reset_for_game(self, game: GoGameInterface) -> None:
        """Clear board state while retaining the loaded network process."""
        self._synced_moves.clear()
        if self._process is None:
            self._start(game)
            return

        state = game.get_board_state()
        komi = float(getattr(game, "komi", 7.5))
        rules = str(getattr(game, "rules", "tromp-taylor"))
        try:
            self._process.command(f"boardsize {state.size}")
            self._process.command("clear_board")
            self._process.command(f"komi {komi:g}")
            self._process.command(f"kata-set-rules {rules}")
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._process is not None:
            self._process.close()
            self._process = None
        self._synced_moves.clear()

    def __enter__(self) -> "KataGoNetworkStrategy":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


@dataclass(frozen=True)
class PlayedGame:
    result: GameResult
    moves: tuple[tuple[str, str], ...]


def play_game(
    game: GoGameInterface,
    black: Strategy,
    white: Strategy,
    on_move: Callable[[str, str, float], None] | None = None,
) -> PlayedGame:
    """Play two arbitrary strategies until the engine declares the game over."""
    strategies = {"B": black, "W": white}
    move_history: list[tuple[str, str]] = []
    while not game.get_game_result().ended:
        board = game.get_board_state()
        color = board.to_move
        strategy = strategies[color]
        move_started = time.perf_counter()
        move = strategy.choose_move(game)
        move_seconds = time.perf_counter() - move_started
        outcome = game.do_action(move, color)
        if not outcome.success:
            # A strategy may be stale or buggy; the engine remains authoritative.
            raise RuntimeError(
                f"{strategy.name} selected illegal move {move}: {outcome.reason}"
            )
        move_history.append((color, move))
        if on_move is not None:
            on_move(color, move, move_seconds)
    return PlayedGame(game.get_game_result(), tuple(move_history))


def run_random_game(
    *,
    board_size: int = 9,
    seed: int | None = None,
    katago_binary: str | Path | None = None,
    model_path: str | Path | None = None,
    config_path: str | Path | None = None,
    log_dir: str | Path = "gtp_logs",
    max_moves: int | None = None,
) -> PlayedGame:
    """Create an engine and play two independently seeded random strategies."""
    if max_moves is None:
        max_moves = board_size * board_size * 3
    seed_source = random.Random(seed)
    black = RandomStrategy(seed_source.randrange(2**63), "random-black")
    white = RandomStrategy(seed_source.randrange(2**63), "random-white")
    with KataGoGameEngine(
        board_size=board_size,
        katago_binary=katago_binary,
        model_path=model_path,
        config_path=config_path,
        log_dir=log_dir,
        max_moves=max_moves,
    ) as game:
        return play_game(game, black, white)


def main() -> int:
    try:
        ensure_katago_installed()
        played = run_random_game(
            board_size=BOARD_SIZE,
            seed=RANDOM_SEED,
            katago_binary=KATAGO_BINARY,
            model_path=KATAGO_MODEL,
            config_path=KATAGO_CONFIG,
            log_dir=LOG_DIR,
            max_moves=MAX_MOVES,
        )
    except GoEngineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    result = played.result
    print(
        f"Game ended after {len(played.moves)} moves: "
        f"{result.score} (winner: {result.winner or 'draw'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
