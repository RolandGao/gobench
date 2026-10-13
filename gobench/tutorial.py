"""Track 3 tutorial distillation: names, the token cap, prompts and student positions.

A learning agent writes one tutorial in a Track 2 style sandbox. Evaluation
prepends that fixed text to a Track 1 multi-turn player's conversation. This
module holds the provider-neutral pieces; arena.py runs the agents and calls.
"""

from __future__ import annotations

import errno
import functools
import os
import re
import stat
from dataclasses import dataclass

from gobench.go_rules import COLS, TrompTaylorRules

PROTOCOL_VERSION = "tutorial-distillation-v1"
TOKEN_LIMIT = 5000
TOKENIZER = "o200k_base"
HOURS = (1, 2, 4, 8)
STUDENT_MAX_CONCURRENCY = 4
STUDENT_MAX_ATTEMPTS = 5
# Bounds one batch call; a 250k-token conversation reset already bounds context.
STUDENT_MAX_POSITIONS = 200
# Read at most this much of the agent's file; the cap keeps only 5,000 tokens.
MAX_SOURCE_BYTES = 1024 * 1024
SANDBOX_TUTORIAL_PATH = "/workspace/tutorial.md"
SANDBOX_TOOL_SOCKET = "/runtime/arena-tools.sock"
SANDBOX_KATAGO_DIR = "/opt/katago"
SANDBOX_NETWORK_DIR = "/opt/katago-networks"


@dataclass(frozen=True)
class Subtrack:
    katago: bool
    student: bool


SUBTRACKS = {
    "3.1": Subtrack(katago=False, student=False),
    "3.2": Subtrack(katago=True, student=False),
    "3.3": Subtrack(katago=True, student=True),
}

_NAME = re.compile(
    r"(?P<target>.+-api-multi)-tutorial(?P<subtrack>3\.[0-9]+)-"
    r"(?P<learner>.+-(?:codex|claude-code))-(?P<hours>[1-9][0-9]*)h(?P<replica>[0-9]*)"
)


@dataclass(frozen=True)
class TutorialPlayer:
    """`<target>-tutorial<subtrack>-<learner>-<hours>h[replica]`.

    The target is the Track 1 multi-turn player that reads the tutorial during
    evaluation and answers student calls. The learner is a Track 2 workspace
    model/effort/runtime without its duration, e.g. `claude-opus-5-5-high-claude-code`.
    """

    name: str
    target: str
    subtrack: str
    learner: str
    hours: int
    replica: str

    @property
    def canonical(self):
        return self.name.removesuffix(self.replica) if self.replica else self.name

    @property
    def learner_player(self):
        """The Track 2 player name whose model, effort and runtime do the learning."""
        return f"{self.learner}-{self.hours}h"

    @property
    def training_seconds(self):
        return self.hours * 3600

    @property
    def katago(self):
        return SUBTRACKS[self.subtrack].katago

    @property
    def student(self):
        return SUBTRACKS[self.subtrack].student


def parse_player(name):
    """Parse a tutorial player name, or return None for any other player."""
    if not isinstance(name, str):
        return None
    match = _NAME.fullmatch(name)
    if match is None:
        return None
    hours = int(match.group("hours"))
    if match.group("subtrack") not in SUBTRACKS or hours not in HOURS:
        return None
    if match.group("replica").startswith("0"):
        return None
    return TutorialPlayer(name, match.group("target"), match.group("subtrack"),
                          match.group("learner"), hours, match.group("replica"))


@functools.cache
def _encoding():
    import tiktoken

    return tiktoken.get_encoding(TOKENIZER)


def count_tokens(text):
    return len(_encoding().encode(text, disallowed_special=()))


def truncate(text):
    """Return (tutorial, source token count). Hard truncation at TOKEN_LIMIT tokens."""
    encoding = _encoding()
    tokens = encoding.encode(text, disallowed_special=())
    if len(tokens) <= TOKEN_LIMIT:
        return text, len(tokens)
    keep = TOKEN_LIMIT
    while True:
        # A cut inside a multibyte character decodes to U+FFFD, which can
        # re-encode as more tokens. Shorten until the published text fits.
        kept = encoding.decode(tokens[:keep])
        if len(encoding.encode(kept, disallowed_special=())) <= TOKEN_LIMIT:
            return kept, len(tokens)
        keep -= 1


def read_source(path):
    """Read the agent's tutorial without following links out of its workspace.

    Returns None when no regular file exists. Undecodable bytes are replaced.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return None
        raise
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        return None
    with os.fdopen(descriptor, "rb") as source:
        return source.read(MAX_SOURCE_BYTES).decode("utf-8", errors="replace")


def with_tutorial(tutorial, prompt):
    """The first user message of every evaluation or student conversation session."""
    return (
        "Before the game prompt, here is a tutorial written to help you play this "
        "9x9 Go game.\n\n<tutorial>\n"
        f"{tutorial}\n</tutorial>\n\n{prompt}"
    )


@dataclass(frozen=True)
class Position:
    """A referee-replayed position in the shape the Track 1 prompt expects."""

    size: int
    rows: tuple[tuple[str, ...], ...]
    to_move: str
    move_number: int
    legal_moves: tuple[str, ...]
    ko_illegal_moves: tuple[str, ...]
    recent_moves: tuple[tuple[str, str], ...]


def replay_position(moves, size=9):
    """Replay alternating moves from the empty board, Black first.

    Each move is a coordinate or pass, optionally prefixed by its color
    ("B D5" or "D5"). The position must still be in play.
    """
    if not isinstance(moves, list):
        raise ValueError("a position must be a list of moves")
    rules = TrompTaylorRules(size)
    history, color, passes = [], "B", 0
    for index, item in enumerate(moves, 1):
        if not isinstance(item, str):
            raise ValueError(f"move {index} must be a string")
        parts = item.split()
        if len(parts) == 2:
            stated, move = parts[0].upper(), parts[1]
            if stated not in {"B", "W"}:
                raise ValueError(f"move {index} has an invalid color: {item!r}")
            if stated != color:
                raise ValueError(f"move {index} must be played by {color}: {item!r}")
        elif len(parts) == 1:
            move = parts[0]
        else:
            raise ValueError(f"move {index} is not 'COLOR MOVE' or 'MOVE': {item!r}")
        move = move.upper() if move.lower() != "pass" else "pass"
        if passes >= 2:
            raise ValueError(f"move {index} follows two consecutive passes")
        try:
            evaluation = rules.evaluate(color, move)
        except ValueError as exc:
            raise ValueError(f"move {index}: {exc}") from exc
        if not evaluation.legal:
            raise ValueError(f"move {index} {color} {move} is illegal: {evaluation.reason}")
        rules.commit(evaluation)
        history.append((color, move))
        passes = passes + 1 if move == "pass" else 0
        color = "W" if color == "B" else "B"
    if passes >= 2:
        raise ValueError("the game has ended with two consecutive passes")
    legal, ko_illegal = rules.possible_moves(color)
    stones = {0: ".", 1: "B", 2: "W"}
    rows = tuple(
        tuple(stones[rules.position[row * size + column]] for column in range(size))
        for row in range(size)
    )
    return Position(size, rows, color, len(history), (*legal, "resign"),
                    tuple(ko_illegal), tuple(history[-5:]))


def ladder_text(rows, opponent_notes):
    """Describe the Track 1 ladder networks available inside the sandbox."""
    lines = [
        "Track 1 KataGo ladder: networks available in " + SANDBOX_NETWORK_DIR,
        "",
        "Evaluation opponents are drawn from this ladder by information-gain",
        "matchmaking. Elo is this benchmark's Bradley-Terry rating (the random",
        "anchor is 0). Speed is measured seconds per player per game on the",
        "benchmark's KataGo host, not inside this sandbox; on one CPU core expect",
        "larger networks and searches to be much slower.",
        "",
        *opponent_notes,
        "",
        "player\tnetwork_file\telo\tseconds_per_player_game",
        *("\t".join(map(str, row)) for row in rows),
    ]
    return "\n".join(lines) + "\n"


def coordinate_columns(size=9):
    return " ".join(COLS[:size])


# Sandbox programs. They talk to the host only through SANDBOX_TOOL_SOCKET:
# one JSON request line, one JSON response line. They run with /usr/bin/python3.
_CLIENT = r'''
import json
import socket
import sys

SOCKET = "__SOCKET__"


def call(request):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(SOCKET)
    except OSError as exc:
        sys.exit(f"arena tools are unavailable: {exc}")
    with connection, connection.makefile("rwb") as stream:
        stream.write(json.dumps(request).encode() + b"\n")
        stream.flush()
        line = stream.readline()
    if not line:
        sys.exit("arena tools closed the connection without a response")
    response = json.loads(line)
    if "error" in response:
        sys.exit("error: " + response["error"])
    return response
'''.replace("__SOCKET__", SANDBOX_TOOL_SOCKET)

TOKENS_PROGRAM = "#!/usr/bin/python3\n" + _CLIENT + r'''

USAGE = """usage: tutorial-tokens [FILE]

Count FILE (default /workspace/tutorial.md) with the fixed o200k_base tokenizer.
Only the first 5000 tokens are kept when preparation ends."""

if len(sys.argv) > 2 or sys.argv[1:] in (["-h"], ["--help"]):
    sys.exit(USAGE)
path = sys.argv[1] if len(sys.argv) == 2 else "/workspace/tutorial.md"
with open(path, encoding="utf-8", errors="replace") as source:
    text = source.read()
result = call({"op": "tokens", "text": text})
print(f"{result['tokens']} tokens (limit {result['limit']})"
      + ("; text after the limit will be cut" if result["tokens"] > result["limit"] else ""))
'''

STUDENT_PROGRAM = "#!/usr/bin/python3\n" + _CLIENT + r'''
import argparse

parser = argparse.ArgumentParser(
    prog="student",
    description=(
        "Run one multi-turn student conversation: the evaluation model, in the exact "
        "Track 1 harness, with TUTORIAL prepended. Each position becomes one user turn, "
        "in order, in the same conversation. Blocks until every position is answered. "
        "At most 4 student calls run at once; further calls wait for a free slot."
    ),
)
parser.add_argument("tutorial", help="tutorial file (cut to 5000 o200k_base tokens)")
parser.add_argument(
    "positions",
    help=(
        "JSON file: a list of positions; each position is a list of moves from the "
        "empty board, Black first, such as [\"B E5\", \"W C3\", \"B pass\"] or "
        "[\"E5\", \"C3\", \"pass\"]. Positions need not come from the same game."
    ),
)
parser.add_argument("-o", "--output", help="write the JSON result here instead of stdout")
arguments = parser.parse_args()
with open(arguments.tutorial, encoding="utf-8", errors="replace") as source:
    tutorial = source.read()
with open(arguments.positions, encoding="utf-8") as source:
    positions = json.load(source)
result = call({"op": "student", "tutorial": tutorial, "positions": positions})
text = json.dumps(result, indent=2, ensure_ascii=False)
if arguments.output:
    with open(arguments.output, "w", encoding="utf-8") as destination:
        destination.write(text + "\n")
else:
    print(text)
'''

KATAGO_PROGRAM = (
    "#!/bin/sh\n"
    f'exec {SANDBOX_KATAGO_DIR}/squashfs-root/AppRun "$@"\n'
)
