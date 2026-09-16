#!/usr/bin/env python3
"""A small, strategy-agnostic Go game interface backed by KataGo.

Python enforces Tromp–Taylor legality and positional superko. KataGo executes
accepted moves and scores games; every resulting board is checked against the
local referee because GTP play itself tolerates ko/superko violations.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, TextIO

from gobench.go_rules import COLS, LEGALITY_ENFORCEMENT_VERSION, TrompTaylorRules

from gobench.paths import ROOT

Color = Literal["B", "W"]


class GoEngineError(RuntimeError):
    """Base exception for engine startup and communication failures."""


class GTPError(GoEngineError):
    """A command that KataGo rejected at the GTP protocol level."""

    def __init__(self, command: str, response: str) -> None:
        super().__init__(f"GTP command failed: {command}: {response}")
        self.command = command
        self.response = response


@dataclass(frozen=True)
class MoveResult:
    """The result of attempting one game action."""

    success: bool
    color: Color
    move: str
    reason: str | None = None

    @property
    def legal(self) -> bool:
        return self.success

    def __bool__(self) -> bool:
        return self.success


@dataclass(frozen=True)
class GameResult:
    """Current game-ending state and, when ended, KataGo's score."""

    ended: bool
    winner: Color | None = None
    score: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class BoardState:
    """A snapshot of the board, with rows ordered top-to-bottom.

    Intersections contain ``"B"``, ``"W"``, or ``"."``. Coordinates use
    normal Go notation: A1 is the lower-left point and column I is skipped.
    """

    size: int
    rows: tuple[tuple[str, ...], ...]
    to_move: Color
    move_number: int
    raw: str

    def at(self, coordinate: str) -> str:
        move = normalize_move(coordinate, self.size)
        if move in {"pass", "resign"}:
            raise ValueError(f"{coordinate!r} is not a board coordinate")
        x = COLS.index(move[0])
        row = int(move[1:])
        return self.rows[self.size - row][x]

    def as_dict(self) -> dict[str, str]:
        return {
            f"{COLS[x]}{self.size - y}": value
            for y, row in enumerate(self.rows)
            for x, value in enumerate(row)
        }


class GoGameInterface(ABC):
    """The interface strategies use to interact with a Go game."""

    @abstractmethod
    def do_action(self, move: str, color: str | None = None) -> MoveResult:
        """Try to play one move without raising for ordinary illegal moves."""

    @abstractmethod
    def get_game_result(self) -> GameResult:
        """Return whether the game ended and, if so, who won."""

    @abstractmethod
    def get_board_state(self) -> BoardState:
        """Return an immutable snapshot of the current board."""

    @abstractmethod
    def get_possible_moves(
        self, color: str | None = None
    ) -> tuple[list[str], list[str]]:
        """Return ``(legal moves, illegal ko/superko moves)``."""

    def get_move_history(self) -> tuple[tuple[Color, str], ...]:
        """Return accepted moves in play order for stateful strategies."""
        raise NotImplementedError


class _GTPProcess:
    """A minimal synchronous GTP subprocess with a raw protocol log."""

    def __init__(
        self,
        args: list[str],
        protocol_log_path: Path,
        stderr_log_path: Path,
    ) -> None:
        protocol_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._protocol_log: TextIO = protocol_log_path.open(
            "a", encoding="utf-8"
        )
        self._stderr_log: TextIO = stderr_log_path.open("a", encoding="utf-8")
        try:
            self._process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_log,
                text=True,
                bufsize=1,
            )
        except OSError:
            self._protocol_log.close()
            self._stderr_log.close()
            raise
        self._sequence = 0
        self._lock = threading.Lock()
        self._closed = False

    def command(self, command: str) -> str:
        with self._lock:
            if self._closed:
                raise GoEngineError("KataGo process is closed")
            stdin = self._process.stdin
            stdout = self._process.stdout
            if stdin is None or stdout is None:
                raise GoEngineError("KataGo was not started with GTP pipes")

            self._sequence += 1
            sequence = str(self._sequence)
            request = f"{sequence} {command}"
            self._protocol_log.write(f"> {request}\n")
            self._protocol_log.flush()
            try:
                stdin.write(request + "\n")
                stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise GoEngineError(f"KataGo exited while sending: {command}") from exc

            first = self._response_start(stdout, command)
            ok = first.startswith("=")
            payload_start = first[1:].lstrip()
            if payload_start == sequence:
                payload_start = ""
            elif payload_start.startswith(sequence + " "):
                payload_start = payload_start[len(sequence) :].lstrip()

            lines = [payload_start] if payload_start else []
            while True:
                line = stdout.readline()
                if line == "":
                    raise GoEngineError(f"KataGo exited while reading: {command}")
                stripped = line.rstrip("\r\n")
                self._protocol_log.write(f"< {stripped}\n")
                if not stripped:
                    break
                lines.append(stripped)
            self._protocol_log.write("\n")
            self._protocol_log.flush()

            response = "\n".join(lines)
            if not ok:
                raise GTPError(command, response)
            return response

    def _response_start(self, stdout: TextIO, command: str) -> str:
        while True:
            line = stdout.readline()
            if line == "":
                raise GoEngineError(f"KataGo exited while waiting for: {command}")
            stripped = line.rstrip("\r\n")
            self._protocol_log.write(f"< {stripped}\n")
            if stripped.startswith(("=", "?")):
                return stripped

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            # command() also takes the lock, so perform a best-effort raw quit.
            try:
                if self._process.poll() is None and self._process.stdin is not None:
                    self._process.stdin.write("quit\n")
                    self._process.stdin.flush()
                    try:
                        self._process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self._process.terminate()
                        try:
                            self._process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            self._process.kill()
                            self._process.wait()
            except (BrokenPipeError, OSError):
                pass
            finally:
                self._closed = True
                for pipe in (self._process.stdin, self._process.stdout):
                    if pipe is not None:
                        try:
                            pipe.close()
                        except OSError:
                            pass
                self._protocol_log.close()
                self._stderr_log.close()


# Public name used by KataGo-backed strategies.
GTPProcess = _GTPProcess


class KataGoGameEngine(GoGameInterface):
    """A strict Python referee with one persistent KataGo execution process.

    The model is only needed because KataGo's GTP executable requires one;
    move choice is entirely delegated to strategies. By default paths are
    read from ``KATAGO_BINARY``, ``KATAGO_MODEL``, and ``KATAGO_CONFIG``, then
    discovered in the repository's historical ``.venv`` layout.
    """

    def __init__(
        self,
        board_size: int = 9,
        komi: float = 7.5,
        rules: str = "tromp-taylor",
        *,
        katago_binary: str | Path | None = None,
        model_path: str | Path | None = None,
        config_path: str | Path | None = None,
        log_dir: str | Path = ROOT / "gtp_logs",
        game_id: str | None = None,
        max_moves: int | None = None,
        _gtp: object | None = None,
    ) -> None:
        if board_size < 2 or board_size > len(COLS):
            raise ValueError(f"unsupported board size: {board_size}")
        if max_moves is not None and max_moves < 1:
            raise ValueError("max_moves must be positive")
        if rules != "tromp-taylor":
            raise ValueError("the strict referee currently supports only tromp-taylor")

        self.board_size = board_size
        self.komi = float(komi)
        self.rules = rules
        self.max_moves = max_moves
        self.game_id = game_id or dt.datetime.now().strftime(
            "%Y%m%d-%H%M%S-"
        ) + uuid.uuid4().hex[:8]
        self.to_move: Color = "B"
        self.moves: list[tuple[Color, str]] = []
        self._consecutive_passes = 0
        self._result = GameResult(False)
        self._closed = False
        self._rules = TrompTaylorRules(board_size)

        log_root = Path(log_dir).expanduser().resolve()
        log_root.mkdir(parents=True, exist_ok=True)
        self.action_log_path = log_root / f"{self.game_id}.actions.jsonl"
        self.gtp_log_path = log_root / f"{self.game_id}.gtp.txt"
        self.stderr_log_path = log_root / f"{self.game_id}.stderr.txt"
        self._action_log = self.action_log_path.open("a", encoding="utf-8")

        try:
            if _gtp is None:
                binary = _resolve_katago_binary(katago_binary)
                model = _resolve_katago_file(
                    model_path,
                    "KATAGO_MODEL",
                    "a KataGo model",
                    [
                        ".venv/katago/**/share/katago/*.bin.gz",
                        ".venv/katago/**/*.bin.gz",
                    ],
                )
                config = _resolve_katago_file(
                    config_path,
                    "KATAGO_CONFIG",
                    "a KataGo GTP config",
                    [".venv/katago/**/share/katago/configs/gtp_example.cfg"],
                )
                args = [
                    str(binary),
                    "gtp",
                    "-model",
                    str(model),
                    "-config",
                    str(config),
                    "-override-config",
                    f"logDir={log_root / (self.game_id + '.katago')},"
                    "logToStderr=false,logAllGTPCommunication=false,"
                    "startupPrintMessageToStderr=false,maxVisits=1,"
                    "numSearchThreads=1",
                ]
                self._gtp = _GTPProcess(args, self.gtp_log_path, self.stderr_log_path)
            else:
                # Injection is deliberately private; it keeps protocol tests fast.
                self._gtp = _gtp
        except OSError as exc:
            self._action_log.close()
            raise GoEngineError(f"could not start KataGo: {exc}") from exc
        except Exception:
            self._action_log.close()
            raise

        try:
            self._command(f"boardsize {board_size}")
            self._command("clear_board")
            self._command(f"komi {self.komi:g}")
            self._command(f"kata-set-rules {rules}")
            self._verify_rules()
            self._read_board(self._rules.position)
        except Exception:
            self.close()
            raise
        self._log(
            "game_started",
            board_size=board_size,
            komi=self.komi,
            rules=rules,
            max_moves=max_moves,
            legality_enforcement_version=LEGALITY_ENFORCEMENT_VERSION,
        )

    def _verify_rules(self) -> None:
        try:
            rules = json.loads(self._command("kata-get-rules"))
        except ValueError as exc:
            raise GoEngineError("invalid KataGo rules response") from exc
        if (
            not isinstance(rules, dict) or rules.get("ko") != "POSITIONAL"
            or rules.get("suicide") is not True
        ):
            raise GoEngineError("KataGo rules disagree with the Tromp–Taylor referee")

    def _ensure_open(self) -> None:
        if self._closed:
            raise GoEngineError("game engine is closed")

    def _read_board(self, expected: bytes) -> tuple[str, tuple[tuple[str, ...], ...]]:
        raw = self._command("showboard")
        rows = _parse_board(raw, self.board_size)
        actual = bytes({".": 0, "B": 1, "W": 2}[v] for row in rows for v in row)
        if actual != expected:
            raise GoEngineError("KataGo board disagrees with the strict referee")
        return raw, rows

    def _command(self, command: str) -> str:
        if self._closed:
            raise GoEngineError("game engine is closed")
        command_method = getattr(self._gtp, "command", None)
        if not callable(command_method):
            raise GoEngineError("invalid GTP transport")
        return str(command_method(command))

    def _log(self, event: str, **fields: object) -> None:
        entry = {
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "game_id": self.game_id,
            "event": event,
            **fields,
        }
        self._action_log.write(json.dumps(entry, sort_keys=True) + "\n")
        self._action_log.flush()

    def do_action(self, move: str, color: str | None = None) -> MoveResult:
        self._ensure_open()
        attempted_color: Color
        try:
            attempted_color = normalize_color(color or self.to_move)
        except ValueError as exc:
            # MoveResult is meant to capture normal bad strategy output.
            result = MoveResult(False, self.to_move, str(move), str(exc))
            self._log("move_rejected", **asdict(result))
            return result

        try:
            normalized = normalize_move(move, self.board_size)
        except (TypeError, ValueError) as exc:
            result = MoveResult(False, attempted_color, str(move), str(exc))
            self._log("move_rejected", **asdict(result))
            return result

        if self._result.ended:
            return self._reject(attempted_color, normalized, "game has already ended")
        if attempted_color != self.to_move:
            return self._reject(
                attempted_color,
                normalized,
                f"it is {self.to_move}'s turn",
            )

        if normalized == "resign":
            winner = other_color(attempted_color)
            self._result = GameResult(True, winner, f"{winner}+R", "resignation")
        else:
            evaluation = self._rules.evaluate(attempted_color, normalized)
            if not evaluation.legal:
                return self._reject(attempted_color, normalized, evaluation.reason)
            try:
                self._command(f"play {attempted_color} {normalized}")
                self._read_board(evaluation.position)
            except GTPError as exc:
                self.close()
                raise GoEngineError(
                    f"KataGo rejected referee-legal move {attempted_color} {normalized}"
                ) from exc
            except Exception:
                self.close()
                raise

            self._rules.commit(evaluation)
            self.moves.append((attempted_color, normalized))
            self._consecutive_passes = (
                self._consecutive_passes + 1 if normalized == "pass" else 0
            )
            self.to_move = other_color(attempted_color)

            ending_reason: str | None = None
            if self._consecutive_passes >= 2:
                ending_reason = "two_passes"
            elif self.max_moves is not None and len(self.moves) >= self.max_moves:
                ending_reason = "max_moves"
            if ending_reason:
                self._finish_by_score(ending_reason)

        result = MoveResult(True, attempted_color, normalized)
        self._log(
            "move_played",
            **asdict(result),
            move_number=len(self.moves),
            game_result=asdict(self._result),
        )
        if self._result.ended:
            self._log("game_ended", **asdict(self._result))
        return result

    # Familiar alternate name for callers that prefer it.
    play_move = do_action

    def play(self, color: str, move: str) -> MoveResult:
        """GTP-style color-first convenience wrapper around :meth:`do_action`."""
        return self.do_action(move, color)

    def _reject(self, color: Color, move: str, reason: str) -> MoveResult:
        result = MoveResult(False, color, move, reason)
        self._log("move_rejected", **asdict(result))
        return result

    def _finish_by_score(self, reason: str) -> None:
        score = self._command("final_score").strip()
        winner: Color | None
        if score.upper().startswith("B+"):
            winner = "B"
        elif score.upper().startswith("W+"):
            winner = "W"
        else:
            winner = None
        self._result = GameResult(True, winner, score, reason)

    def get_game_result(self) -> GameResult:
        return self._result

    def get_move_history(self) -> tuple[tuple[Color, str], ...]:
        return tuple(self.moves)

    def check_game_end(self) -> tuple[bool, Color | None]:
        """Convenience form of :meth:`get_game_result`."""
        return self._result.ended, self._result.winner

    def is_game_over(self) -> bool:
        return self._result.ended

    def get_board_state(self) -> BoardState:
        try:
            raw, rows = self._read_board(self._rules.position)
        except Exception:
            self.close()
            raise
        return BoardState(
            size=self.board_size,
            rows=rows,
            to_move=self.to_move,
            move_number=len(self.moves),
            raw=raw,
        )

    def get_possible_moves(
        self, color: str | None = None
    ) -> tuple[list[str], list[str]]:
        """Return exact legal and superko lists without mutating either board."""
        self._ensure_open()
        if self._result.ended:
            return [], []
        query_color = normalize_color(color or self.to_move)
        return self._rules.possible_moves(query_color)

    def get_legal_moves(self, color: str | None = None) -> list[str]:
        return self.get_possible_moves(color)[0]

    def get_ko_illegal_moves(self, color: str | None = None) -> list[str]:
        return self.get_possible_moves(color)[1]

    get_illegal_ko_moves = get_ko_illegal_moves

    def reset_for_game(
        self,
        *,
        game_id: str,
        log_dir: str | Path,
    ) -> None:
        """Reset the board and Python state while retaining the GTP process."""
        if self._closed:
            raise GoEngineError("game engine is closed")
        if not self._action_log.closed:
            self._action_log.close()

        self.game_id = game_id
        self.to_move = "B"
        self.moves = []
        self._consecutive_passes = 0
        self._result = GameResult(False)
        self._rules = TrompTaylorRules(self.board_size)

        log_root = Path(log_dir).expanduser().resolve()
        log_root.mkdir(parents=True, exist_ok=True)
        self.action_log_path = log_root / f"{self.game_id}.actions.jsonl"
        self._action_log = self.action_log_path.open("a", encoding="utf-8")
        try:
            self._command(f"boardsize {self.board_size}")
            self._command("clear_board")
            self._command(f"komi {self.komi:g}")
            self._command(f"kata-set-rules {self.rules}")
            self._verify_rules()
            self._read_board(self._rules.position)
            self._log(
                "game_started",
                board_size=self.board_size,
                komi=self.komi,
                rules=self.rules,
                max_moves=self.max_moves,
                legality_enforcement_version=LEGALITY_ENFORCEMENT_VERSION,
            )
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        close_method = getattr(getattr(self, "_gtp", None), "close", None)
        if callable(close_method):
            close_method()
        self._closed = True
        if not self._action_log.closed:
            self._action_log.close()

    def __enter__(self) -> "KataGoGameEngine":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


# Short aliases make the main implementation easy to discover.
GoGameEngine = KataGoGameEngine
GameEngine = KataGoGameEngine


def normalize_color(color: str) -> Color:
    value = str(color).strip().upper()
    names = {"B": "B", "BLACK": "B", "W": "W", "WHITE": "W"}
    try:
        return names[value]  # type: ignore[return-value]
    except KeyError as exc:
        raise ValueError(f"invalid color: {color!r}") from exc


def other_color(color: Color) -> Color:
    return "W" if color == "B" else "B"


def normalize_move(move: str, board_size: int) -> str:
    if not isinstance(move, str):
        raise TypeError("move must be a string")
    value = move.strip()
    if value.lower() in {"pass", "resign"}:
        return value.lower()
    match = re.fullmatch(r"([A-Za-z])([1-9][0-9]*)", value)
    if not match:
        raise ValueError(f"invalid move syntax: {move!r}")
    col = match.group(1).upper()
    row = int(match.group(2))
    if col == "I" or col not in COLS:
        raise ValueError(f"invalid Go column: {col}")
    if COLS.index(col) >= board_size or row > board_size:
        raise ValueError(f"move is outside the {board_size}x{board_size} board: {move}")
    return f"{col}{row}"


def _parse_board(raw: str, size: int) -> tuple[tuple[str, ...], ...]:
    parsed: dict[int, tuple[str, ...]] = {}
    for line in raw.splitlines():
        match = re.match(r"^\s*(\d+)\s+(.*)$", line)
        if not match:
            continue
        row_number = int(match.group(1))
        points = [char for char in match.group(2) if char in ".XO"]
        if 1 <= row_number <= size and len(points) >= size:
            parsed[row_number] = tuple(
                {"X": "B", "O": "W", ".": "."}[char]
                for char in points[:size]
            )
    missing = [row for row in range(1, size + 1) if row not in parsed]
    if missing:
        raise GoEngineError(
            f"could not parse rows {missing} from KataGo showboard response:\n{raw}"
        )
    return tuple(parsed[row] for row in range(size, 0, -1))


def _resolve_katago_binary(value: str | Path | None) -> Path:
    configured = value or os.environ.get("KATAGO_BINARY")
    candidates: list[str | Path] = []
    if configured:
        candidates.append(configured)
    candidates.append(ROOT / ".venv" / "bin" / "katago")
    found = shutil.which("katago")
    if found:
        candidates.append(found)
    for candidate in candidates:
        path = Path(candidate).expanduser().resolve()
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise GoEngineError(
        "KataGo executable not found; pass katago_binary=... or set KATAGO_BINARY"
    )


def _resolve_katago_file(
    value: str | Path | None,
    environment_name: str,
    description: str,
    patterns: list[str],
) -> Path:
    configured = value or os.environ.get(environment_name)
    if configured:
        path = Path(configured).expanduser().resolve()
        if path.is_file():
            return path
        raise GoEngineError(f"{description} does not exist: {path}")
    for pattern in patterns:
        matches = sorted(ROOT.glob(pattern))
        if matches:
            return matches[-1].resolve()
    raise GoEngineError(
        f"Could not find {description}; pass its path or set {environment_name}"
    )
