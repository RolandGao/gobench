"""Write a Track 3.5 opening book as a tutorial file for a language model.

BOOK is a book in the format of gobench/opening_book.py, for example the frozen
log/<run>/books/<player>.txt of a Track 3.5 run. The tutorial uses the header
and the one-token-per-move notation of rollout_book_render.py, and is checked
to read back as the same book. Prints the tutorial's token count.
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rollout_book_lib as L
from gobench import opening_book
from gobench.tutorial import BOOK_MOVE_LIMIT, count_tokens

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("book")
parser.add_argument("out")
parser.add_argument("--header", default="data/tutorials/rollout_book_header.md")
parser.add_argument("--moves", type=int, default=BOOK_MOVE_LIMIT,
                    help="keep only the book's first this many moves")
args = parser.parse_args()

book = opening_book.parse(open(args.book).read(), args.moves)
header = open(args.header).read().rstrip() + "\n"
following = defaultdict(list)  # (color, moves so far) -> next moves, in book order
for color, moves in book.nodes:
    following[color, moves[:-1]].append(moves[-1])


def lines_from(color, prefix, line, out):
    """Continue line with the first move after prefix; open a line for each other."""
    for index, move in enumerate(following.get((color, prefix), ())):
        if index:
            line = [str(len(prefix) + 1)]
            out.append(line)
        line.append(L.to_notation(move))
        lines_from(color, prefix + (move,), line, out)


parts = []
for color, title in L.BOOK_TITLES.items():
    out = [["1"]]
    lines_from(color, (), out[0], out)
    parts.append(title + "\n" + "\n".join(" ".join(line) for line in out if len(line) > 1))
text = header + "\n" + "\n\n".join(parts) + "\n"

wanted = {" ".join(moves): move for (_, moves), move in book.replies.items()}
if L.parse_book(text) != wanted:
    sys.exit("the tutorial does not read back as the book")
Path(args.out).write_text(text)
lines = sum(len(part.splitlines()) - 1 for part in parts)
print(f"{args.out}: {count_tokens(text)} tokens (header {count_tokens(header)}) for "
      f"{book.size} moves, {len(book.replies)} of them the student's, in {lines} lines")
