"""Render a crawled book tree as a variation outline that fits the tutorial budget.

Reads the katago_book_crawl output and prepends data/tutorials/katago_book_9x9tt_header.md.
"""
import argparse
import json

import tiktoken

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("tree_json")
parser.add_argument("--header", default="data/tutorials/katago_book_9x9tt_header.md")
parser.add_argument("--out", default="data/tutorials/katago_book_9x9tt.md")
parser.add_argument("--token-limit", type=int, default=5000)
# Each ply lowers the chance that a real game is still exactly in the book.
parser.add_argument("--decay", type=float, default=0.9)
args = parser.parse_args()
TREE, HEADER, OUT = args.tree_json, args.header, args.out
LIMIT, DECAY = args.token_limit, args.decay
enc = tiktoken.get_encoding("o200k_base")
tree = json.load(open(TREE))
header = open(HEADER).read().rstrip() + "\n\n"


def bwin(m):
    return 50.0 * (1.0 - m["wl"])


def children(path):
    """(move, loss for the mover, child path, weight) for crawled children, best first."""
    node = tree[path]
    best = bwin(node["moves"][0])
    out = []
    for m in node["moves"]:
        mv = m["moves"][0]
        child = f"{path} {mv}".strip()
        if child not in tree:
            continue
        loss = best - bwin(m) if node["to_move"] == "B" else bwin(m) - best
        weight = (tree[child]["wB"] + tree[child]["wW"]) * DECAY ** len(child.split())
        out.append((mv, loss, child, weight))
    return out


def mark(loss):
    return "??" if loss >= 15 else "?" if loss >= 5 else ""


def render(tau):
    lines = []
    shown = set()

    def line_from(path, depth, first_move, first_loss):
        """Emit one line starting with first_move at path; recurse into variations."""
        moves = [(first_move, first_loss)]
        cur = f"{path} {first_move}".strip()
        branches = []
        transposed = False
        while True:
            if tree[cur]["board"] in shown:
                transposed = True
                break
            shown.add(tree[cur]["board"])
            kids = [k for k in children(cur) if k[3] >= tau]
            if not kids:
                break
            main = kids[0]
            branches.append((cur, kids[1:]))
            moves.append((main[0], main[1]))
            cur = main[2]
        n0 = len(path.split()) if path else 0
        node = tree[cur]
        text = " ".join(f"{n0 + i + 1}.{mv}{mark(loss)}" for i, (mv, loss) in enumerate(moves))
        tail = " = transposes" if transposed else ""
        lines.append(" " * depth + f"{text} [{bwin(node['moves'][0]):.0f}]{tail}")
        for at, alts in branches:
            for mv, loss, child, w in alts:
                line_from(at, depth + 1, mv, loss)

    roots = [k for k in children("") if k[3] >= tau]
    for mv, loss, child, w in roots:
        line_from("", 0, mv, loss)
    return header + "\n".join(lines) + "\n"


lo, hi = 1e-6, 1.0
best_text = render(hi)
for _ in range(40):
    mid = (lo * hi) ** 0.5
    text = render(mid)
    if len(enc.encode(text)) <= LIMIT:
        best_text, hi = text, mid
    else:
        lo = mid
open(OUT, "w").write(best_text)
print("tau %.2e tokens %d lines %d" % (hi, len(enc.encode(best_text)), best_text.count("\n")))
