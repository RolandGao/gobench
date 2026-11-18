"""Build a Track 3 tutorial from the KataGo 9x9 book, aimed at one student's mistakes.

Opponent moves come from logged arena games against KataGo bots, smoothed
toward the book's policy where the logs are thin. At each of our likely
decisions the student (a Track 1 multi-turn player, no tutorial) is asked
for its move once with the exact Track 1 prompt. A move within --tolerance
win rate of the book's best is kept, and lines follow it; otherwise the
book's best move is taught. Tokens go to the student's mistakes in order of
reach probability times win rate lost, until the tutorial reaches the limit.
Probe answers are cached in --probes, so reruns make no new calls.

Most student moves deep in the book are not among the book's few listed
candidates. --export-unlisted writes them for katago_book_evaluate, whose
output (--evals) gives their losses on the next run.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import heapq
import json
import re
import sys
import threading
from collections import Counter, defaultdict
from pathlib import Path

N = 9
COLS = "ABCDEFGHJ"
ROOT = Path(__file__).resolve().parents[1]
# A move outside the book's candidate list that KataGo has not evaluated
# (--evals) has no value; count it as this loss.
UNLISTED_LOSS = 30.0
# Pseudo-games of the book's policy added to each position's logged opponent moves.
PRIOR_GAMES = 3.0


def js_value(text, name):
    m = re.search(r"const %s = (.*?);\n" % name, text, re.S)
    v = m.group(1).replace("'", '"')
    v = re.sub(r",\s*([}\]])", r"\1", v)
    v = re.sub(r"([{,])(\d+):", r'\1"\2":', v)
    return json.loads(v)


SYMS = []
for _s in range(8):
    def _f(x, y, s=_s):
        if s & 4:
            x, y = y, x
        if s & 1:
            x = N - 1 - x
        if s & 2:
            y = N - 1 - y
        return x, y
    SYMS.append(_f)


def idx(mv):
    return (N - int(mv[1:])) * N + COLS.index(mv[0])


def coord(i):
    return f"{COLS[i % N]}{N - i // N}"


def map_point(f, i):
    x, y = f(i % N, i // N)
    return y * N + x


def apply(f, board):
    out = ["."] * (N * N)
    for i, c in enumerate(board):
        out[map_point(f, i)] = c
    return "".join(out)


def neighbors(i):
    x, y = i % N, i // N
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if 0 <= x + dx < N and 0 <= y + dy < N:
            yield (y + dy) * N + x + dx


def play(board, i, stone):
    b = list(board)
    b[i] = stone
    for side in ("O" if stone == "X" else "X", stone):
        for j in range(N * N):
            if b[j] != side:
                continue
            group, stack, libs = {j}, [j], False
            while stack:
                k = stack.pop()
                for n in neighbors(k):
                    if b[n] == ".":
                        libs = True
                    elif b[n] == side and n not in group:
                        group.add(n)
                        stack.append(n)
            if not libs:
                for k in group:
                    b[k] = "."
    return "".join(b)


def bwin(group):
    return 50.0 * (1.0 - group["wl"])


class Book:
    """Book positions by move path in one fixed orientation, loaded on demand."""

    def __init__(self, html_dir):
        self.html = Path(html_dir)
        self.nodes = {}
        self.lock = threading.Lock()

    def _load(self, rel, board):
        text = (self.html / rel.replace("../", "")).read_text()
        page_board = js_value(text, "board")
        f = next((f for f in SYMS if apply(f, "".join(".XO"[c] for c in page_board)) == board),
                 None)
        if f is None:
            raise ValueError(f"book page {rel} does not match the expected board")
        links = {int(k): v for k, v in js_value(text, "links").items()}
        groups = []
        for m in js_value(text, "moves"):
            if "xy" not in m:
                continue
            coords = [coord(map_point(f, y * N + x)) for x, y in m["xy"]]
            x0, y0 = m["xy"][0]
            groups.append({"coords": coords, "p": m["p"], "wl": m["wl"],
                           "link": links.get(y0 * N + x0)})
        to_move = "B" if js_value(text, "nextPla") == 1 else "W"
        return {"board": board, "to_move": to_move, "groups": groups,
                "by_coord": {c: g for g in groups for c in g["coords"]}}

    def get(self, path):
        path = tuple(path)
        with self.lock:
            if path in self.nodes:
                return self.nodes[path]
        if not path:
            node = self._load("root/root.html", "." * (N * N))
        else:
            parent = self.get(path[:-1])
            group = parent and parent["by_coord"].get(path[-1])
            if group is None or group["coords"][0] != path[-1] or not group["link"]:
                node = None
            else:
                stone = "X" if parent["to_move"] == "B" else "O"
                node = self._load(group["link"], play(parent["board"], idx(path[-1]), stone))
        with self.lock:
            self.nodes[path] = node
        return node

    def best_loss(self, node, rep):
        """Win rate the mover loses by playing group rep instead of the best (UNLISTED if None)."""
        group = node["by_coord"].get(rep) if rep else None
        if group is None:
            return UNLISTED_LOSS
        best = node["groups"][0]
        loss = bwin(best) - bwin(group) if node["to_move"] == "B" else bwin(group) - bwin(best)
        return max(0.0, loss)


def opponent_counts(book, log_dirs):
    """{path: Counter(rep or None -> times a KataGo bot played it)} from logged games."""
    counts = defaultdict(Counter)
    games = 0
    for log_dir in log_dirs:
        path = Path(log_dir) / "llm_games.jsonl"
        if not path.exists():
            continue
        for line in path.open():
            g = json.loads(line)
            moves = g.get("moves")
            if not isinstance(moves, list):
                continue
            bot_colors = {c for c, name in (("B", g["black"]), ("W", g["white"]))
                          if name.startswith("kata1-")}
            if len(bot_colors) != 1:
                continue
            games += 1
            book_path, f, board = (), SYMS[0], "." * (N * N)
            for m in moves:
                node = book.get(book_path)
                if node is None or m["move"] in ("pass", "resign"):
                    break
                group = node["by_coord"].get(coord(map_point(f, idx(m["move"]))))
                rep = group["coords"][0] if group else None
                if m["color"] in bot_colors:
                    counts[book_path][rep] += 1
                if rep is None or not group["link"]:
                    break
                board = play(board, idx(m["move"]), "X" if m["color"] == "B" else "O")
                book_path += (rep,)
                child = book.get(book_path)
                if child is None:
                    break
                f = next((f for f in SYMS if apply(f, board) == child["board"]), None)
                if f is None:
                    break
    return counts, games


def opponent_probs(node, observed):
    """Probability of each listed group rep; the remainder leaves the book."""
    prior = {g["coords"][0]: g["p"] * len(g["coords"]) for g in node["groups"]}
    total_prior = sum(prior.values()) or 1.0
    n = sum(observed.values())
    return {rep: (observed.get(rep, 0) + PRIOR_GAMES * p / total_prior) / (n + PRIOR_GAMES)
            for rep, p in prior.items()}


class Student:
    """Ask the Track 1 player for one move per position; answers are cached on disk."""

    def __init__(self, player, cache_path, work_dir, dry_run=False):
        self.player = player
        self.cache_path = Path(cache_path)
        self.work_dir = Path(work_dir)
        self.dry_run = dry_run
        self.lock = threading.Lock()
        self.cache = {}
        if self.cache_path.exists():
            for line in self.cache_path.open():
                row = json.loads(line)
                if row["player"] == player:
                    self.cache[tuple(row["path"])] = row
        self.new_calls = 0
        self.cost = 0.0

    def ask(self, path):
        path = tuple(path)
        if path in self.cache:
            return self.cache[path]
        if self.dry_run:
            return {"path": list(path), "move": None, "dry_run": True}
        import arena
        from gobench import tutorial

        position = tutorial.replay_position(list(path))
        prompt = arena._llm_move_prompt(position, list(position.legal_moves),
                                        list(position.ko_illegal_moves), position.recent_moves)
        with self.lock:
            self.new_calls += 1
            number = len(self.cache) + self.new_calls
        self.work_dir.mkdir(parents=True, exist_ok=True)
        client = arena._llm_client(self.player, work_dir=self.work_dir, game_number=number)
        row = {"player": self.player, "path": list(path), "move": None, "outputs": [],
               "cost_usd": 0.0}
        try:
            for attempt in range(1, 6):
                raw, _, cost = arena._call_llm_move(
                    client, prompt, player_name=self.player,
                    log_path=self.work_dir / "calls.jsonl", game_number=number,
                    move_number=len(path) + 1, attempt=attempt,
                )
                row["outputs"].append(raw)
                row["cost_usd"] += cost
                if raw.strip() in position.legal_moves:
                    row["move"] = raw.strip()
                    break
        finally:
            client.close()
        with self.lock:
            self.cost += row["cost_usd"]
            self.cache[path] = row
            with self.cache_path.open("a") as out:
                out.write(json.dumps(row) + "\n")
        return row


def explore(book, counts, student, *, max_probes, probe_min, expand_min, tolerance, workers,
            unlisted_losses=None, max_positions=50000):
    """Reach weights and our chosen move for each explored position.

    wB/wW: probability the position arises when we are Black/White. Our move is
    the student's if it is within tolerance, otherwise the book's best.
    """
    info = {}
    heap = [(-2.0, 0, (), 1.0, 1.0)]
    counter = 0
    probes = 0
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    while heap and len(info) < max_positions:
        batch, in_batch = [], set()
        while heap and len(batch) < workers * 2:
            item = heapq.heappop(heap)
            if item[2] not in info and item[2] not in in_batch:
                batch.append(item)
                in_batch.add(item[2])
        needs = [(p, wb, ww) for _, _, p, wb, ww in batch
                 if (node := book.get(p)) is not None
                 and (wb if node["to_move"] == "B" else ww) >= probe_min]
        futures = {}
        for p, _, _ in needs:
            if tuple(p) not in student.cache and probes >= max_probes:
                continue
            if tuple(p) not in student.cache:
                probes += 1
            futures[tuple(p)] = pool.submit(student.ask, p)
        answers = {p: fut.result() for p, fut in futures.items()}
        for _, _, path, wb, ww in batch:
            node = book.get(path)
            if node is None or not node["groups"]:
                continue
            ours = wb if node["to_move"] == "B" else ww
            theirs = ww if node["to_move"] == "B" else wb
            entry = {"wB": wb, "wW": ww, "to_move": node["to_move"]}
            our_rep = None
            if tuple(path) in answers:
                answer = answers[tuple(path)]
                move = answer.get("move")
                best = node["groups"][0]["coords"][0]
                if answer.get("dry_run"):
                    group, loss = node["groups"][0], 0.0
                else:
                    group = node["by_coord"].get(move) if move else None
                    loss = (book.best_loss(node, group["coords"][0]) if group
                            else (unlisted_losses or {}).get(tuple(path), UNLISTED_LOSS))
                entry.update(student=move, student_loss=loss)
                if loss > tolerance:
                    our_rep = best
                else:
                    # A sound move the book does not list ends the book here.
                    our_rep = group["coords"][0] if group else None
                entry["ours"] = our_rep
            info[tuple(path)] = entry
            probs = opponent_probs(node, counts.get(tuple(path), {}))
            for rep in set(probs) | ({our_rep} if our_rep else set()):
                w_ours = ours if rep == our_rep else 0.0
                w_theirs = theirs * probs.get(rep, 0.0)
                if w_ours < probe_min and w_theirs < expand_min:
                    continue
                cb, cw = (w_ours, w_theirs) if node["to_move"] == "B" else (w_theirs, w_ours)
                counter += 1
                heapq.heappush(heap, (-(cb + cw), counter, tuple(path) + (rep,), cb, cw))
    pool.shutdown()
    return info, probes


def select_and_render(book, info, header, *, tolerance, token_limit):
    import tiktoken

    enc = tiktoken.get_encoding("o200k_base")
    # A taught decision: the student's move loses more than tolerance there.
    candidates = []
    for path, e in info.items():
        if "student_loss" in e and e["student_loss"] > tolerance:
            weight = e["wB"] if e["to_move"] == "B" else e["wW"]
            candidates.append((weight * e["student_loss"], path))
    candidates.sort(reverse=True)

    def mover_loss(path):
        return book.best_loss(book.get(path[:-1]), path[-1])

    def render(chosen):
        prefixes = {p[:k] for p in chosen for k in range(len(p) + 1)}
        children = defaultdict(list)
        for p in prefixes:
            if p:
                children[p[:-1]].append(p)
        weight = {p: info[p]["wB"] + info[p]["wW"] for p in prefixes}
        for kids in children.values():
            kids.sort(key=lambda c: -weight[c])
        lines = []

        def move_text(p, first):
            # Taught moves are the book's best, so only mistakes are marked.
            loss = mover_loss(p)
            mark = "??" if loss >= 15 else "?" if loss >= 5 else ""
            # Only a line's first move is numbered; the rest count on from it.
            return f"{len(p)}.{p[-1]}{mark}" if first else f"{p[-1]}{mark}"

        def line_from(p, depth):
            seq, branches = [p], []
            while children.get(seq[-1]):
                kids = children[seq[-1]]
                branches.append(kids[1:])
                seq.append(kids[0])
            lines.append(" " * depth + " ".join(move_text(q, i == 0) for i, q in enumerate(seq)))
            for alts in branches:
                for alt in alts:
                    line_from(alt, depth + 1)

        for top in children.get((), []):
            line_from(top, 0)
        return header + "\n".join(lines) + "\n"

    # The taught move itself is the child: path + book best.
    chosen = []
    text = render(chosen)
    for value, path in candidates:
        target = path + (book.get(path)["groups"][0]["coords"][0],)
        if target not in info:
            info[target] = {"wB": info[path]["wB"] if info[path]["to_move"] == "B" else 0.0,
                            "wW": info[path]["wW"] if info[path]["to_move"] == "W" else 0.0,
                            "to_move": "W" if info[path]["to_move"] == "B" else "B"}
        trial = render(chosen + [target])
        if len(enc.encode(trial)) <= token_limit:
            chosen.append(target)
            text = trial
    return text, chosen, candidates


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book_html_dir", type=Path)
    parser.add_argument("--student", default="gpt6-astra-high-api-multi")
    parser.add_argument("--probes", type=Path,
                        default=ROOT / "data/tutorials/katago_book_9x9tt_v2_probes.jsonl")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "untracked_log/katago_book_probes")
    parser.add_argument("--header", type=Path,
                        default=ROOT / "data/tutorials/katago_book_9x9tt_v2_header.md")
    parser.add_argument("--out", type=Path, default=ROOT / "data/tutorials/katago_book_9x9tt_v2.md")
    parser.add_argument("--evals", type=Path,
                        default=ROOT / "data/tutorials/katago_book_9x9tt_v2_evals.jsonl",
                        help="KataGo losses for student moves the book does not list")
    parser.add_argument("--max-probes", type=int, default=500)
    parser.add_argument("--probe-min", type=float, default=0.002,
                        help="minimum reach probability for asking the student")
    parser.add_argument("--expand-min", type=float, default=0.001)
    parser.add_argument("--tolerance", type=float, default=2.0,
                        help="win rate %% a student move may lose and still be kept")
    parser.add_argument("--token-limit", type=int, default=5000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--export-unlisted", type=Path,
                        help="write probed student moves the book does not list, for "
                             "katago_book_evaluate")
    parser.add_argument("--dry-run", action="store_true",
                        help="make no student calls; treat unasked positions as solved")
    args = parser.parse_args(argv)

    book = Book(args.book_html_dir)
    logs = sorted(p.parent for p in (ROOT / "log").glob("*/llm_games.jsonl"))
    counts, games = opponent_counts(book, logs)
    print(f"opponent moves from {games} logged games in {len(counts)} book positions", flush=True)
    student = Student(args.student, args.probes, args.work_dir, dry_run=args.dry_run)
    unlisted = {}
    if args.evals.exists():
        for line in args.evals.open():
            row = json.loads(line)
            if row["loss"] is not None:
                unlisted[tuple(row["path"])] = row["loss"]
    info, probes = explore(book, counts, student, max_probes=args.max_probes,
                           probe_min=args.probe_min, expand_min=args.expand_min,
                           tolerance=args.tolerance, workers=args.workers,
                           unlisted_losses=unlisted)
    if args.export_unlisted:
        rows = []
        for path, row in student.cache.items():
            node = book.get(path)
            if node and row.get("move") and row["move"] not in node["by_coord"]:
                rows.append({"path": list(path), "student": row["move"],
                             "best": node["groups"][0]["coords"][0], "to_move": node["to_move"]})
        args.export_unlisted.write_text(json.dumps(rows))
        print(f"wrote {len(rows)} unlisted student moves -> {args.export_unlisted}")
    asked = [e for e in info.values() if "student_loss" in e]
    print(f"explored {len(info)} positions; student answers {len(asked)} "
          f"({student.new_calls} new calls, ${student.cost:.2f})", flush=True)
    text, chosen, candidates = select_and_render(
        book, info, args.header.read_text().rstrip() + "\n\n",
        tolerance=args.tolerance, token_limit=args.token_limit)
    args.out.write_text(text)
    from gobench import tutorial
    total = sum(v for v, _ in candidates)
    covered = sum(v for v, p in candidates
                  if p + (book.get(p)["groups"][0]["coords"][0],) in set(chosen))
    print(f"student mistakes: {len(candidates)}; taught {len(chosen)} covering "
          f"{covered / max(total, 1e-12):.0%} of expected loss; "
          f"{tutorial.count_tokens(text)} tokens -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
