"""Search for book moves that make the student proxy beat a stronger KataGo bot.

Every game is an arena game between the proxy (a KataGo bot rated like the
student) and the opponent, both at one visit. The search keeps a tree of the
positions where the student is to move, keyed by the move history up to the
eight board symmetries. A position visited --expand times gets candidate moves:
the top policy moves of each teacher network and of the proxy itself. The first
teacher's value network then judges the position after each candidate. If the
proxy's own top move is about as good as the best candidate, nothing is forked:
that move alone carries the line deeper. If the teacher calls it a mistake, the
candidates the teacher rates near the best are tested against each other. From
then on a game that reaches the position either

  * forces one candidate and goes on down the tree (the book as it would be
    played: the student follows the book, only the opponent's replies vary), or
  * hands the rest of the game to the proxy (a "natural" rollout), which
    measures what the position is worth without a book.

Candidates and the natural rollout are chosen by Thompson sampling, so games
concentrate on the moves that win most against this opponent and on the
positions the opponent actually steers into. A move of the proxy's own that
wins more than the position's average joins the candidates as well. STATE_DIR/tree.json holds the
statistics; rollout_book_render.py ranks the fixes and writes the tutorial.

Rerun with the same STATE_DIR to continue a search.
"""
import argparse
import json
import os
import queue
import random
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rollout_book_lib as L

parser = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("state_dir")
parser.add_argument("--student", default=L.STUDENT_PROXY)
parser.add_argument("--opponent", default=L.OPPONENT)
parser.add_argument("--teachers", nargs="+", default=list(L.TEACHERS),
                    help="networks proposing candidates; the first also judges mistakes")
parser.add_argument("--hours", type=float, default=1.0)
parser.add_argument("--workers", type=int, default=16)
parser.add_argument("--expanders", type=int, default=2)
parser.add_argument("--expand", type=int, default=16,
                    help="visits before a position gets candidate moves")
parser.add_argument("--top", type=int, default=2,
                    help="candidate moves taken from each network")
parser.add_argument("--min-prior", type=float, default=0.10,
                    help="policy a network's second and later candidates need")
parser.add_argument("--fork-margin", type=float, default=0.05,
                    help="a position is forked only if the first teacher's win rate "
                         "after the proxy's top move is this far below the best candidate's")
parser.add_argument("--keep-margin", type=float, default=0.10,
                    help="at a fork, drop candidates whose teacher win rate is this far "
                         "below the best; negative tests every candidate everywhere")
parser.add_argument("--natural", type=float, default=0.10,
                    help="share of visits to an expanded position forced to be natural")
parser.add_argument("--first-visits", type=int, default=4,
                    help="visits every candidate gets before Thompson sampling")
parser.add_argument("--promote", type=int, default=8,
                    help="natural rollouts after which a move of the proxy's own that "
                         "scores above the position's average becomes a candidate")
parser.add_argument("--checkpoint-minutes", type=float, default=10.0)
args = parser.parse_args()

STATE = Path(args.state_dir)
STATE.mkdir(parents=True, exist_ok=True)
TREE_PATH = STATE / "tree.json"
LOGS = STATE / "katago-logs"
# A node: n visits, nn/nw natural rollouts and their score, nm the proxy's own
# first move in those rollouts {move: [n, score]}, x 0 new / 1 queued / 2 expanded,
# v each network's win rate for the side to move, drop how far the teacher's win
# rate after the proxy's top move is below the best candidate's, fork whether
# that makes it a mistake, a the candidates {move: {n, w, src {network: [rank,
# prior]}, tv the teacher's win rate after it, r {opponent reply: n}}}.
if TREE_PATH.exists():
    tree = json.load(open(TREE_PATH))
    for node in tree["nodes"].values():
        if node["x"] == 1:
            node["x"] = 0
else:
    tree = {"student": args.student, "opponent": args.opponent,
            "teachers": args.teachers, "games": 0, "seconds": 0.0,
            "white_first": {}, "nodes": {}}
if (tree["student"], tree["opponent"]) != (args.student, args.opponent):
    sys.exit(f"{TREE_PATH} was built with other players")
# A continued search may use other teachers; earlier candidates keep their source.
tree["teachers"] += [name for name in args.teachers if name not in tree["teachers"]]
nodes = tree["nodes"]
lock = threading.Lock()
stop = threading.Event()
expand_queue = queue.Queue()
games_log = open(STATE / "games.txt", "a")
recent = {"B": [], "W": []}
errors = [0]


def select(node, rng):
    """Return the candidate to force, or None for a natural rollout."""
    if rng.random() < args.natural:
        return None
    arms = node["a"]
    fewest = min(arms, key=lambda move: arms[move]["n"])
    if arms[fewest]["n"] < args.first_visits:
        return fewest
    best, best_draw = None, rng.betavariate(1 + node["nw"], 1 + node["nn"] - node["nw"])
    for move, arm in arms.items():
        draw = rng.betavariate(1 + arm["w"], 1 + arm["n"] - arm["w"])
        if draw > best_draw:
            best, best_draw = move, draw
    return best


def play_one(student, opponent, color, rng):
    path = []  # (node key, candidate, ply the candidate was played at)
    natural = []  # (node key, ply) where the proxy took over

    def forced(history, rejected=None):
        if rejected is not None:
            key, move, _ = path.pop()
            with lock:
                nodes[key]["a"].pop(move, None)
                errors[0] += 1
            print(f"referee rejected {rejected} after {' '.join(history)}", flush=True)
            natural.append((key, len(history)))
            return None
        if natural:
            return None
        image, symmetry = L.canonical(history)
        key = " ".join(image)
        with lock:
            node = nodes.get(key)
            if node is None:
                node = nodes[key] = {"n": 0, "nn": 0, "nw": 0.0, "nm": {}, "x": 0, "a": {}}
            node["n"] += 1
            if node["x"] == 0 and node["n"] >= args.expand:
                node["x"] = 1
                expand_queue.put(list(history))
            choice = select(node, rng) if node["x"] == 2 and node["a"] else None
        if choice is None:
            natural.append((key, len(history)))
            return None
        path.append((key, choice, len(history)))
        return L.INVERSES[symmetry][choice]

    history, score, reason = L.play_game(student, opponent, color, forced)

    def canonical_move(ply):
        """The move played at this ply, in the orientation of the canonical history."""
        if ply < len(history):
            return L.canonical(history[:ply + 1])[0][-1]
        return "resign" if reason == "resignation" else "end"

    with lock:
        tree["games"] += 1
        if color == "W" and history:
            first = L.canonical(history[:1])[0][0]
            tree["white_first"][first] = tree["white_first"].get(first, 0) + 1
        for key, move, ply in path:
            arm = nodes[key]["a"].get(move)
            if arm is None:
                continue
            arm["n"] += 1
            arm["w"] += score
            reply = canonical_move(ply + 1)
            arm["r"][reply] = arm["r"].get(reply, 0) + 1
        for key, ply in natural:
            node = nodes[key]
            node["nn"] += 1
            node["nw"] += score
            move = canonical_move(ply)
            entry = node["nm"].setdefault(move, [0, 0.0])
            entry[0] += 1
            entry[1] += score
            # A move of the proxy's own that wins more than its average becomes a
            # candidate too: the opponent may fail to punish what a teacher would.
            if (node["x"] == 2 and entry[0] == args.promote and move not in node["a"]
                    and move not in ("resign", "end")
                    and entry[1] / entry[0] > node["nw"] / node["nn"]):
                node["a"][move] = {"n": 0, "w": 0.0, "src": {"natural": [0, 0.0]}, "r": {}}
        recent[color].append(score)
        del recent[color][:-2000]
        start = natural[0][1] if natural else len(history)
        games_log.write(f"{color} {score:g} {start} {reason} {' '.join(history)}\n")


def worker(index):
    rng = random.Random()
    student = opponent = None
    color = "BW"[index % 2]
    while not stop.is_set():
        try:
            if student is None:
                student = L.GTPBot(args.student, LOGS)
                opponent = L.GTPBot(args.opponent, LOGS)
            play_one(student, opponent, color, rng)
            color = "W" if color == "B" else "B"
        except Exception as exc:  # A dead engine or an illegal move: restart both.
            with lock:
                errors[0] += 1
            print(f"worker {index}: {type(exc).__name__}: {exc}", flush=True)
            for bot in (student, opponent):
                if bot is not None:
                    bot.close()
            student = opponent = None
    for bot in (student, opponent):
        if bot is not None:
            bot.close()


def expander():
    networks = [*args.teachers, args.student]
    bots = {name: L.GTPBot(name, LOGS) for name in networks}
    rng = random.Random()
    while not stop.is_set():
        try:
            history = expand_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        arms, values, real = {}, {}, {}
        for name in networks:
            # The small networks are cheap enough to average over the symmetries.
            symmetry = "all" if "b6c96" in name else str(rng.randrange(8))
            prior, values[name] = bots[name].raw_policy(history, symmetry)
            merged = {}
            for move, value in prior.items():
                image = L.canonical(history + [move])[0][-1]
                merged[image] = merged.get(image, 0.0) + value
                real.setdefault(image, move)
            ranked = sorted(merged.items(), key=lambda item: -item[1])[:args.top]
            for rank, (move, value) in enumerate(ranked):
                if rank and value < args.min_prior:
                    break
                arm = arms.setdefault(move, {"n": 0, "w": 0.0, "src": {}, "r": {}})
                arm["src"][name] = [rank, round(value, 4)]
        fork = drop = None
        if args.keep_margin >= 0:
            # The first teacher's win rate for the student after each candidate.
            for move, arm in arms.items():
                judge = args.teachers[0]
                after = bots[judge].raw_policy(
                    history + [real[move]],
                    "all" if "b6c96" in judge else str(rng.randrange(8)))[1]
                arm["tv"] = round(1.0 - after, 4)
            best = max(arm["tv"] for arm in arms.values())
            own = next(move for move, arm in arms.items()
                       if arm["src"].get(args.student, [1])[0] == 0)
            drop = round(best - arms[own]["tv"], 4)
            fork = drop >= args.fork_margin
            if fork:
                # The teacher calls the proxy's move a mistake: test what it prefers.
                arms = {move: arm for move, arm in arms.items()
                        if arm["tv"] >= best - args.keep_margin}
            else:
                # No mistake to fix: the proxy's own move carries the line deeper.
                arms = {own: arms[own]}
        with lock:
            node = nodes[L.key_of(history)]
            node["a"], node["v"], node["x"] = arms, values, 2
            if fork is not None:
                node["fork"], node["drop"] = fork, drop
    for bot in bots.values():
        bot.close()


def checkpoint():
    with lock:
        tree["seconds"] = base_seconds + time.time() - started
        text = json.dumps(tree, separators=(",", ":"))
        games_log.flush()
    temporary = TREE_PATH.with_suffix(".tmp")
    temporary.write_text(text)
    os.replace(temporary, TREE_PATH)


def report():
    with lock:
        expanded = sum(1 for node in nodes.values() if node["x"] == 2)
        rates = {color: sum(scores) / len(scores) if scores else float("nan")
                 for color, scores in recent.items()}
        root = nodes.get("")
        natural_black = root["nw"] / root["nn"] if root and root["nn"] else float("nan")
        games = tree["games"]
    elapsed = time.time() - started
    print(f"{elapsed / 3600:5.2f}h games {games} ({(games - base_games) / elapsed:.1f}/s) "
          f"nodes {len(nodes)} expanded {expanded} queue {expand_queue.qsize()} "
          f"errors {errors[0]} | last 2000 games: Black {rates['B']:.3f} "
          f"White {rates['W']:.3f} | natural Black {natural_black:.3f}", flush=True)


started, base_seconds, base_games = time.time(), tree["seconds"], tree["games"]
signal.signal(signal.SIGTERM, lambda *_: stop.set())
signal.signal(signal.SIGINT, lambda *_: stop.set())
threads = [threading.Thread(target=worker, args=(index,)) for index in range(args.workers)]
threads += [threading.Thread(target=expander) for _ in range(args.expanders)]
for thread in threads:
    thread.start()
next_report = next_checkpoint = time.time()
while not stop.is_set() and time.time() - started < args.hours * 3600:
    time.sleep(1.0)
    if time.time() >= next_report + 60:
        next_report = time.time()
        report()
    if time.time() >= next_checkpoint + args.checkpoint_minutes * 60:
        next_checkpoint = time.time()
        checkpoint()
stop.set()
for thread in threads:
    thread.join()
checkpoint()
report()
games_log.close()
