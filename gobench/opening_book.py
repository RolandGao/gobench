"""Track 3.5 opening books: the file format, its size, and the lookup.

A book is text. A line is the student's color, B or W, then moves from the
empty board, Black first, as vertices (E5) or "pass":

    B E5 C4 D4 C3 C5
    W E5 C5 E3 E7

On a B line the odd moves are the student's: the book plays them. The even
moves are opponent moves the book has an answer to. A W line is the reverse.
Text after # is a comment.

A game is in the book while some symmetry of the board maps its moves, in
order, onto the start of a line of the student's color; the book's next move
is mapped back to the game. So one line also stands for its seven mirror
images and rotations.

The size of a book is the number of distinct moves in its two prefix trees,
one per color: every move of every line counts, the opponent's too, but a
prefix shared by several lines counts once, and so do lines that are mirror
images of each other. A book over the limit keeps the moves that come first
in the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gobench.go_rules import COLS, TrompTaylorRules

SIZE = 9
COLORS = "BW"
_COLUMNS = COLS[:SIZE]
_MAPS = (
    lambda c, r: (c, r),
    lambda c, r: (SIZE + 1 - c, r),
    lambda c, r: (c, SIZE + 1 - r),
    lambda c, r: (SIZE + 1 - c, SIZE + 1 - r),
    lambda c, r: (r, c),
    lambda c, r: (SIZE + 1 - r, c),
    lambda c, r: (r, SIZE + 1 - c),
    lambda c, r: (SIZE + 1 - r, SIZE + 1 - c),
)


def _table(mapping):
    table = {"pass": "pass"}
    for c in range(1, SIZE + 1):
        for r in range(1, SIZE + 1):
            image_c, image_r = mapping(c, r)
            table[f"{_COLUMNS[c - 1]}{r}"] = f"{_COLUMNS[image_c - 1]}{image_r}"
    return table


SYMMETRIES = tuple(_table(mapping) for mapping in _MAPS)
_INVERSES = tuple({image: point for point, image in table.items()} for table in SYMMETRIES)


def canonical(moves):
    """Return (the smallest of the eight images of moves, the symmetry giving it).

    A prefix of a canonical sequence is the canonical sequence of the prefix,
    so a prefix tree of canonical lines is a prefix tree of positions.
    """
    best, best_index = None, 0
    for index, table in enumerate(SYMMETRIES):
        image = tuple(table[move] for move in moves)
        if best is None or image < best:
            best, best_index = image, index
    return best, best_index


@dataclass
class Book:
    """A parsed book cut to its size limit."""

    limit: int
    # (student color, canonical moves so far) -> the student's canonical move.
    replies: dict = field(default_factory=dict)
    # Every kept move: (student color, canonical moves up to and including it).
    nodes: dict = field(default_factory=dict)
    lines: int = 0
    dropped_moves: int = 0
    problems: list = field(default_factory=list)

    @property
    def size(self):
        return len(self.nodes)

    def move(self, color, history):
        """The book's move for the student of this color after history, or None."""
        image, symmetry = canonical(tuple(history))
        reply = self.replies.get((color, image))
        return None if reply is None else _INVERSES[symmetry][reply]

    def text(self):
        """The kept book, one line per longest line, in the order moves were kept.

        Parsing this text with the same limit gives the same book.
        """
        prefixes = {(color, moves[:-1]) for color, moves in self.nodes}
        return "".join(
            f"{color} {' '.join(moves)}\n"
            for color, moves in self.nodes if (color, moves) not in prefixes
        )

    def summary(self):
        return {
            "size": self.size,
            "limit": self.limit,
            "book_moves": len(self.replies),
            "lines": self.lines,
            "dropped_moves": self.dropped_moves,
            "problems": [list(problem) for problem in self.problems],
        }


def _read_line(number, line, book):
    """Return (color, the legal moves of one line), recording what is wrong with it."""
    words = line.split("#", 1)[0].split()
    if not words:
        return None, ()
    book.lines += 1
    color = words[0].upper()
    if color not in COLORS:
        book.problems.append((number, f"starts with {words[0]!r}, not B or W"))
        return None, ()
    rules, moves = TrompTaylorRules(SIZE), []
    for index, word in enumerate(words[1:], start=1):
        move = word.lower() if word.lower() == "pass" else word.upper()
        mover = COLORS[(index - 1) % 2]
        if move not in SYMMETRIES[0]:
            book.problems.append((number, f"move {index} {word!r} is not a point or pass"))
            break
        evaluation = rules.evaluate(mover, move)
        if not evaluation.legal:
            book.problems.append((number, f"move {index} {move} is illegal: {evaluation.reason}"))
            break
        rules.commit(evaluation)
        moves.append(move)
    return color, tuple(moves)


def parse(text, limit):
    """Read book text and keep its first `limit` distinct moves.

    A line is kept up to its first problem: an unreadable or illegal move, or
    a student move where an earlier line already chose a different one.
    """
    book = Book(limit)
    dropped = set()
    for number, line in enumerate(text.splitlines(), start=1):
        color, moves = _read_line(number, line, book)
        image = canonical(moves)[0] if moves else ()
        for length in range(1, len(image) + 1):
            node = color, image[:length]
            if node in book.nodes:
                continue
            ours = COLORS[(length - 1) % 2] == color
            earlier = book.replies.get((color, image[:length - 1]))
            if ours and earlier is not None:
                book.problems.append(
                    (number, f"move {length}: the book already plays another move here")
                )
                break
            if node in dropped or len(book.nodes) >= limit or (
                    length > 1 and (color, image[:length - 1]) not in book.nodes):
                dropped.add(node)
                continue
            book.nodes[node] = None
            if ours:
                book.replies[color, image[:length - 1]] = image[length - 1]
    book.dropped_moves = len(dropped)
    return book
