"""KataGo processes (teacher analysis + GTP opponent) and network downloads."""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import Callable

APP_DIR = Path(__file__).resolve().parent
KATAGO = APP_DIR / "engine" / "katago"
NETWORK_DIR = APP_DIR / "networks"
LOG_DIR = APP_DIR / "logs"
NETWORK_URL = "https://media.katagotraining.org/uploaded/networks/models/kata1/{}"
RULES = "tromp-taylor"
BOARD_SIZE = 9


class EngineError(RuntimeError):
    pass


def load_networks() -> list[dict]:
    """Networks from katagotraining.org: name, elo, sha256, size, file."""
    with (APP_DIR / "networks.json").open() as source:
        return json.load(source)


def network_path(network: dict) -> Path:
    return NETWORK_DIR / network["file"]


def is_downloaded(network: dict) -> bool:
    path = network_path(network)
    return path.is_file() and path.stat().st_size == network["size"]


def download_network(
    network: dict, progress: Callable[[int, int], None] | None = None
) -> Path:
    """Download and verify a network, reporting (bytes_done, bytes_total)."""
    path = network_path(network)
    if is_downloaded(network):
        return path
    NETWORK_DIR.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    request = urllib.request.Request(
        NETWORK_URL.format(network["file"]), headers={"User-Agent": "go-trainer"}
    )
    digest = hashlib.sha256()
    done = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, network["size"])
        if done != network["size"] or digest.hexdigest() != network["sha256"]:
            raise EngineError(f"{network['name']} failed its checksum")
        partial.replace(path)
    except OSError as exc:
        raise EngineError(f"could not download {network['name']}: {exc}") from exc
    finally:
        partial.unlink(missing_ok=True)
    return path


def _launch(mode: str, model: Path, config: str) -> subprocess.Popen:
    if not KATAGO.exists():
        raise EngineError("KataGo is not installed; run install_katago.py")
    LOG_DIR.mkdir(exist_ok=True)
    stderr = (LOG_DIR / f"{mode}-{model.name.split('.')[0]}.stderr.txt").open("w")
    return subprocess.Popen(
        [
            str(KATAGO), mode,
            "-model", str(model),
            "-config", str(APP_DIR / "configs" / config),
            "-override-config", f"logDir={LOG_DIR}",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr,
        text=True,
        bufsize=1,
    )


class GtpBot:
    """An opponent that answers genmove with a one-visit KataGo search."""

    def __init__(self, model: Path) -> None:
        self.model = model
        self._process = _launch("gtp", model, "gtp.cfg")
        self._lock = threading.Lock()
        self._synced: list[tuple[str, str]] | None = None
        self._komi: float | None = None
        self._command(f"boardsize {BOARD_SIZE}")
        self._command(f"kata-set-rules {RULES}")

    def _command(self, command: str) -> str:
        assert self._process.stdin and self._process.stdout
        try:
            self._process.stdin.write(command + "\n")
            self._process.stdin.flush()
        except OSError as exc:
            raise EngineError(f"opponent engine died: {exc}") from exc
        lines = []
        while True:
            line = self._process.stdout.readline()
            if not line:
                raise EngineError(f"opponent engine exited (see logs/) after: {command}")
            line = line.strip()
            if not line:
                if lines:
                    break
                continue
            lines.append(line)
        reply = " ".join(lines)
        if reply.startswith("?"):
            raise EngineError(f"opponent rejected {command!r}: {reply}")
        return reply.lstrip("= ").strip()

    def genmove(self, moves: list[tuple[str, str]], komi: float, color: str) -> str:
        with self._lock:
            synced = self._synced
            if synced is None or komi != self._komi or moves[: len(synced)] != synced:
                self._command("clear_board")
                self._command(f"komi {komi:g}")
                self._komi = komi
                synced = []
            for move_color, move in moves[len(synced):]:
                self._command(f"play {move_color} {move}")
            self._synced = list(moves)
            reply = self._command(f"genmove {color}")
            move = "pass" if reply.lower() == "pass" else reply.upper()
            if move == "RESIGN":
                move = "pass"
            self._synced.append((color, move))
            return move

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.kill()


class Analyzer:
    """The teacher: KataGo's JSON analysis engine at one visit per query."""

    def __init__(self, model: Path) -> None:
        self.model = model
        self._process = _launch("analysis", model, "analysis.cfg")
        self._write_lock = threading.Lock()
        self._pending: dict[str, tuple[threading.Event, list]] = {}
        self._counter = 0
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self._process.stdout
        for line in self._process.stdout:
            try:
                response = json.loads(line)
            except ValueError:
                continue
            if "rootInfo" not in response and "error" not in response:
                continue  # A warning; the real answer follows.
            waiter = self._pending.pop(str(response.get("id")), None)
            if waiter:
                waiter[1].append(response)
                waiter[0].set()
        for event, _ in list(self._pending.values()):
            event.set()

    def evaluate(
        self, positions: list[list[tuple[str, str]]], komi: float, policy: bool = False
    ) -> list[dict | None]:
        """One-visit evaluations of positions given as move lists.

        Returns rootInfo (+ "policy" if requested) per position, or None for
        positions KataGo rejected.
        """
        waiters = []
        with self._write_lock:
            assert self._process.stdin
            for moves in positions:
                self._counter += 1
                query_id = str(self._counter)
                waiter: tuple[threading.Event, list] = (threading.Event(), [])
                self._pending[query_id] = waiter
                waiters.append(waiter)
                query = {
                    "id": query_id,
                    "moves": [list(move) for move in moves],
                    "rules": RULES,
                    "komi": komi,
                    "boardXSize": BOARD_SIZE,
                    "boardYSize": BOARD_SIZE,
                    "maxVisits": 1,
                    "includePolicy": policy,
                }
                try:
                    self._process.stdin.write(json.dumps(query) + "\n")
                except OSError as exc:
                    raise EngineError(f"teacher engine died: {exc}") from exc
            self._process.stdin.flush()
        results: list[dict | None] = []
        for event, box in waiters:
            if not event.wait(120) or not box:
                raise EngineError("teacher engine stopped responding (see logs/)")
            response = box[0]
            if "error" in response or "rootInfo" not in response:
                results.append(None)
                continue
            result = dict(response["rootInfo"])
            if policy:
                result["policy"] = response.get("policy")
            results.append(result)
        return results

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.kill()
