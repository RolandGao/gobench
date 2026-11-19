"""Shared pieces of the rollout book: GTP bots, a policy oracle, symmetry and games.

The rollout book is built from games between two arena KataGo bots: a proxy for
the student and the opponent the student should beat. Both are started exactly
as arena.py starts a KataGo opponent for an LLM game (GTP, default_gtp.cfg, one
visit, the arena's move temperatures), so a rollout is a sample of an arena game.

Moves are GTP vertices ("E5", "pass"). A history is the list of moves from the
empty board; Black moves first and the colors alternate.
"""
from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
KATAGO_HOME = ROOT / ".venv/katago/v1.16.5-eigenavx2"
KATAGO_BINARY = KATAGO_HOME / "squashfs-root/AppRun"
KATAGO_CONFIG = KATAGO_HOME / "default_gtp.cfg"
NETWORK_DIR = ROOT / ".venv/katago/networks/kata1"

SIZE, KOMI, RULES = 9, 7.0, "tromp-taylor"
COLS = "ABCDEFGHJ"
# arena.py: _Arena.ORIGINAL_TEMPERATURE_EARLY, _Arena.ORIGINAL_TEMPERATURE.
TEMPERATURE_EARLY, TEMPERATURE = 0.5, 0.1

STUDENT_PROXY = "kata1-b6c96-s16525312-d2925067"  # 2241 Elo
OPPONENT = "kata1-b6c96-s22371328-d3612586"  # 2603 Elo
TEACHERS = ("kata1-b6c96-s175395328-d26788732",)  # 3330 Elo


def network_path(name):
    for suffix in (".bin.gz", ".txt.gz"):
        path = NETWORK_DIR / (name + suffix)
        if path.is_file():
            return path
    raise FileNotFoundError(f"no network file for {name} in {NETWORK_DIR}")


# ---------------------------------------------------------------------------
# Symmetry. A point is (column, row), both 1..9; the eight maps are the ones
# the tutorial header lists, in the same order.
_MAPS = (
    lambda c, r: (c, r),
    lambda c, r: (10 - c, r),
    lambda c, r: (c, 10 - r),
    lambda c, r: (10 - c, 10 - r),
    lambda c, r: (r, c),
    lambda c, r: (10 - r, c),
    lambda c, r: (r, 10 - c),
    lambda c, r: (10 - r, 10 - c),
)
POINTS = tuple(f"{COLS[c - 1]}{r}" for c in range(1, 10) for r in range(1, 10))


def _table(fn):
    table = {"pass": "pass"}
    for c in range(1, 10):
        for r in range(1, 10):
            nc, nr = fn(c, r)
            table[f"{COLS[c - 1]}{r}"] = f"{COLS[nc - 1]}{nr}"
    return table


SYMMETRIES = tuple(_table(fn) for fn in _MAPS)
INVERSES = tuple(
    {image: point for point, image in table.items()} for table in SYMMETRIES
)


def canonical(history):
    """Return (canonical history as a tuple, index of a symmetry that produces it).

    The canonical history is the smallest of the eight images. A prefix of a
    canonical history is the canonical history of the prefix.
    """
    best, best_index = None, 0
    for index, table in enumerate(SYMMETRIES):
        image = tuple(table[move] for move in history)
        if best is None or image < best:
            best, best_index = image, index
    return best, best_index


def key_of(history):
    return " ".join(canonical(history)[0])


# ---------------------------------------------------------------------------
class GTPBot:
    """One KataGo GTP process playing one game at a time with arena settings."""

    def __init__(self, network, log_dir, *, temperature_early=TEMPERATURE_EARLY,
                 temperature=TEMPERATURE, max_visits=1):
        self.name = network
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        session = f"{network}-{uuid.uuid4().hex[:8]}"
        # The same command line as gobench.strategies.KataGoNetworkStrategy,
        # with the temperatures arena.py appends to the bot's config.
        args = [
            str(KATAGO_BINARY), "gtp", "-model", str(network_path(network)),
            "-config", str(KATAGO_CONFIG), "-override-config",
            f"logDir={log_dir / (session + '.katago')},logToStderr=false,"
            "logAllGTPCommunication=false,startupPrintMessageToStderr=false,"
            f"maxVisits={max_visits},numSearchThreads=1,delayMoveScale=0,delayMoveMax=0,"
            f"chosenMoveTemperatureEarly={temperature_early:g},"
            f"chosenMoveTemperature={temperature:g}",
        ]
        self._stderr = open(log_dir / f"{session}.stderr.txt", "w")
        self._process = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr,
            text=True, bufsize=1)
        self.new_game()

    def command(self, command):
        self._process.stdin.write(command + "\n")
        self._process.stdin.flush()
        lines = []
        while True:
            line = self._process.stdout.readline()
            if line == "":
                raise RuntimeError(f"{self.name} exited during: {command}")
            line = line.rstrip("\r\n")
            if not line:
                if lines:
                    break
                continue
            lines.append(line)
        if not lines[0].startswith("="):
            raise RuntimeError(f"{self.name} rejected {command!r}: {lines[0]}")
        lines[0] = lines[0][1:].lstrip()
        return "\n".join(lines)

    def new_game(self):
        self.command(f"boardsize {SIZE}")
        self.command("clear_board")
        self.command(f"komi {KOMI:g}")
        self.command(f"kata-set-rules {RULES}")

    def play(self, color, move):
        self.command(f"play {color} {move}")

    def genmove(self, color):
        move = self.command(f"genmove {color}").strip()
        return move.lower() if move.lower() in ("pass", "resign") else move.upper()

    def final_score(self):
        return self.command("final_score").strip()

    def raw_policy(self, history, symmetry="0"):
        """Return ({move: prior} over legal moves, win rate for the side to move).

        symmetry is one of 0..7 or "all" (the average of the eight). KataGo
        marks moves its rules forbid, superko included, and they are left out.
        """
        self.new_game()
        for index, move in enumerate(history):
            self.play("BW"[index % 2], move)
        prior, white_win, blocks = {}, 0.0, 0
        # One command per symmetry: the reply to "all" has blank lines inside it.
        for one in (range(8) if symmetry == "all" else [symmetry]):
            lines = self.command(f"kata-raw-nn {one}").split("\n")
            for index, line in enumerate(lines):
                words = line.split()
                if not words:
                    continue
                if words[0] == "whiteWin":
                    white_win += float(words[1])
                    blocks += 1
                elif words[0] == "policy":
                    # Rows from the top of the board (row 9) down.
                    for y in range(SIZE):
                        for x, value in enumerate(lines[index + 1 + y].split()):
                            if value.upper() != "NAN":
                                move = f"{COLS[x]}{SIZE - y}"
                                prior[move] = prior.get(move, 0.0) + float(value)
                elif words[0] == "policyPass" and words[1].upper() != "NAN":
                    prior["pass"] = prior.get("pass", 0.0) + float(words[1])
        prior = {move: value / blocks for move, value in prior.items()}
        white_win /= blocks
        return prior, white_win if len(history) % 2 else 1.0 - white_win

    def close(self):
        try:
            self._process.stdin.close()
            self._process.wait(timeout=10)
        except Exception:
            self._process.kill()
        self._stderr.close()


class Referee:
    """The arena's own Tromp-Taylor legality check, tracked alongside a game."""

    def __init__(self, history=()):
        from gobench.go_rules import TrompTaylorRules

        self._rules = TrompTaylorRules(SIZE)
        self.plies = 0
        for move in history:
            if not self.play(move):
                raise ValueError(f"illegal move {move} at ply {self.plies + 1}")

    def legal(self, move):
        return self._rules.evaluate("BW"[self.plies % 2], move).legal

    def play(self, move):
        evaluation = self._rules.evaluate("BW"[self.plies % 2], move)
        if not evaluation.legal:
            return False
        self._rules.commit(evaluation)
        self.plies += 1
        return True


class IllegalMove(RuntimeError):
    pass


def play_game(student, opponent, student_color, forced_move=None):
    """Play one game and return (history, student score, reason).

    student and opponent are GTPBots. forced_move(history) may return a move
    the student must play in that position, or None to let the student choose;
    a forced move the referee rejects is not played and the student chooses.
    The student's score is 1 for a win, 0.5 for a draw and 0 for a loss.
    """
    student.new_game()
    opponent.new_game()
    referee = Referee()
    history = []
    passes = 0
    while True:
        color = "BW"[len(history) % 2]
        ours = color == student_color
        mover, other = (student, opponent) if ours else (opponent, student)
        move = forced_move(history) if ours and forced_move is not None else None
        if move is not None and not referee.legal(move):
            forced_move(history, rejected=move)
            move = None
        if move is None:
            move = mover.genmove(color)
        else:
            mover.play(color, move)
        if move == "resign":
            return history, 0.0 if ours else 1.0, "resignation"
        if not referee.play(move):
            raise IllegalMove(f"{mover.name} played illegal {move} after {history}")
        other.play(color, move)
        history.append(move)
        passes = passes + 1 if move == "pass" else 0
        if passes >= 2:
            score = opponent.final_score().upper()
            if score.startswith("B+") or score.startswith("W+"):
                return history, 1.0 if score[0] == student_color else 0.0, score
            return history, 0.5, score


# ---------------------------------------------------------------------------
# The tutorial's notation: two letters, column then row, a..h and j for 1..9.
# Each point is one token of the o200k_base tokenizer, where "E5" is two.
LETTERS = "abcdefghj"
BOOK_TITLES = {"B": "## Book when you are Black", "W": "## Book when you are White"}


def to_notation(move):
    return move if move == "pass" else move[0].lower() + LETTERS[int(move[1]) - 1]


def from_notation(text):
    if text == "pass":
        return text
    if len(text) != 2 or text[0] not in LETTERS or text[1] not in LETTERS:
        raise ValueError(f"not a book move: {text!r}")
    return f"{text[0].upper()}{LETTERS.index(text[1]) + 1}"


def parse_book(text):
    """Read a tutorial's two books into {canonical history key: canonical move}.

    A line is a move number and the moves from it on; the moves before that
    number are those of the line above. The student's moves are the entries.
    """
    book, color, path = {}, None, []
    for line in text.splitlines():
        if line.startswith("#"):
            color = next((c for c, title in BOOK_TITLES.items() if line.strip() == title), None)
            path = []
            continue
        words = line.split()
        if color is None or not words:
            continue
        start = int(words[0]) - 1
        if start > len(path):
            raise ValueError(f"line starts after the line above ends: {line!r}")
        path = path[:start] + [from_notation(word) for word in words[1:]]
        for ply in range(start, len(path)):
            if "BW"[ply % 2] != color:
                continue
            image, symmetry = canonical(path[:ply])
            key, move = " ".join(image), SYMMETRIES[symmetry][path[ply]]
            if book.setdefault(key, move) != move:
                raise ValueError(f"two book moves after {key!r}")
    return book


def book_move(book, history):
    """The book's move for the side to move after history, or None."""
    image, symmetry = canonical(history)
    move = book.get(" ".join(image))
    return None if move is None else INVERSES[symmetry][move]
