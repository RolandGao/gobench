"""Best-first crawl of the KataGo 9x9 Tromp-Taylor book into one fixed orientation.

Reach weights assume our player follows the book's best move and the opponent
samples from the book's policy: wB when we are Black, wW when we are White.
BOOK_HTML_DIR is the html/ directory of an extracted book archive, e.g.
https://katagobooks.org/downloads/book9x9tt-20260226.tar.gz.
"""
import argparse
import heapq
import json
import re
import sys
from pathlib import Path

N = 9
COLS = "ABCDEFGHJ"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("book_html_dir", type=Path)
parser.add_argument("out_json", type=Path)
parser.add_argument("--max-pages", type=int, default=20000)
args = parser.parse_args()
HTML, OUT, MAX_PAGES = args.book_html_dir, args.out_json, args.max_pages


def js_value(text, name):
    m = re.search(r"const %s = (.*?);\n" % name, text, re.S)
    v = m.group(1).replace("'", '"')
    v = re.sub(r",\s*([}\]])", r"\1", v)
    v = re.sub(r"([{,])(\d+):", r'\1"\2":', v)
    return json.loads(v)


def load(rel):
    """rel is a link like '../B0/<hash>.html' or 'root/root.html'."""
    text = (HTML / rel.replace("../", "")).read_text()
    return {
        "board": js_value(text, "board"),
        "next": js_value(text, "nextPla"),
        "links": {int(k): v for k, v in js_value(text, "links").items()},
        "moves": js_value(text, "moves"),
    }


SYMS = []
for s in range(8):
    def f(x, y, s=s):
        if s & 4:
            x, y = y, x
        if s & 1:
            x = N - 1 - x
        if s & 2:
            y = N - 1 - y
        return x, y
    SYMS.append(f)


def apply(f, board):
    out = [0] * (N * N)
    for i, c in enumerate(board):
        x, y = f(i % N, i // N)
        out[y * N + x] = c
    return out


def neighbors(i):
    x, y = i % N, i // N
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if 0 <= x + dx < N and 0 <= y + dy < N:
            yield (y + dy) * N + x + dx


def play(board, i, color):
    b = list(board)
    b[i] = color
    for side in (3 - color, color):
        for j in range(N * N):
            if b[j] != side:
                continue
            group, stack, libs = {j}, [j], False
            while stack:
                k = stack.pop()
                for n in neighbors(k):
                    if b[n] == 0:
                        libs = True
                    elif b[n] == side and n not in group:
                        group.add(n)
                        stack.append(n)
            if not libs:
                for k in group:
                    b[k] = 0
    return b


def coord(i):
    return f"{COLS[i % N]}{N - i // N}"


nodes = {}
heap = [(-2.0, 0, ())]
pending = {(): ("root/root.html", [0] * (N * N), 1.0, 1.0)}
counter = 0
while heap and len(nodes) < MAX_PAGES:
    _, _, path = heapq.heappop(heap)
    if path in nodes:
        continue
    rel, our_board, wB, wW = pending[path]
    page = load(rel)
    sym = next((f for f in SYMS if apply(f, page["board"]) == our_board), None)
    if sym is None:
        print("no symmetry match for", path, file=sys.stderr)
        continue
    color = page["next"]
    moves, total_p = [], 0.0
    for m in page["moves"]:
        if m.get("move") == "pass":
            moves.append({"moves": ["pass"], "idx": [], "p": m["p"], "wl": m["wl"], "ssM": m["ssM"]})
            continue
        if "xy" not in m:  # 'other': aggregate of unlisted moves
            continue
        idx = []
        for x, y in m["xy"]:
            sx, sy = sym(x, y)
            idx.append(sy * N + sx)
        moves.append({"moves": [coord(i) for i in idx], "idx": idx,
                      "link": page["links"].get(m["xy"][0][1] * N + m["xy"][0][0]),
                      "p": m["p"], "wl": m["wl"], "ssM": m["ssM"], "v": m.get("v")})
        total_p += m["p"] * len(idx)
    nodes[path] = {"to_move": "B" if color == 1 else "W", "moves": moves, "wB": wB, "wW": wW,
                   "board": "".join(".XO"[c] for c in our_board)}
    for rank, m in enumerate(moves):
        if not m["idx"] or not m.get("link"):
            continue
        cls_p = m["p"] * len(m["idx"]) / max(total_p, 1e-9)
        # Our own move: only the book's best; the opponent's: policy-weighted.
        if color == 1:
            cB, cW = (wB if rank == 0 else 0.0), wW * cls_p
        else:
            cB, cW = wB * cls_p, (wW if rank == 0 else 0.0)
        if cB + cW < 1e-5:
            continue
        child = path + (coord(m["idx"][0]),)
        if child in pending:
            continue
        pending[child] = (m["link"], play(our_board, m["idx"][0], color), cB, cW)
        counter += 1
        heapq.heappush(heap, (-(cB + cW), counter, child))

for v in nodes.values():
    for m in v["moves"]:
        m.pop("idx", None)
        m.pop("link", None)
OUT.write_text(json.dumps({" ".join(k): v for k, v in nodes.items()}))
print("nodes", len(nodes), "frontier", len(heap))
