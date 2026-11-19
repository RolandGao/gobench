"""Play the student proxy against KataGo opponents with and without tutorial books.

Each BOOK is a tutorial file written by rollout_book_render.py, or "none" for
the proxy alone. The proxy plays the book's move whenever the game, up to
symmetry, is in the book, and its own move otherwise; the book is read back
from the tutorial text, so this tests the file the student will be given.
Games are fresh: none of them took part in the search.
"""
import argparse
import json
import math
import queue
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rollout_book_lib as L

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("books", nargs="+", help='tutorial files, or "none"')
parser.add_argument("--student", default=L.STUDENT_PROXY)
parser.add_argument("--opponents", nargs="+", default=[L.OPPONENT])
parser.add_argument("--games", type=int, default=2000, help="games per book and opponent")
parser.add_argument("--workers", type=int, default=16)
parser.add_argument("--log-dir", default="untracked_log/rollout_book/eval-logs")
parser.add_argument("--out", help="append one JSON line per book and opponent")
args = parser.parse_args()

books = {name: {} if name == "none" else L.parse_book(open(name).read())
         for name in args.books}
lock = threading.Lock()


def worker(opponent_name, jobs, results):
    student = L.GTPBot(args.student, args.log_dir)
    opponent = L.GTPBot(opponent_name, args.log_dir)
    while True:
        try:
            name, color = jobs.get_nowait()
        except queue.Empty:
            break
        book, used, illegal = books[name], [0], [0]

        def forced(history, rejected=None):
            if rejected is not None:  # The referee refused the book's move.
                used[0] -= 1
                illegal[0] += 1
                return None
            move = L.book_move(book, history)
            if move is not None:
                used[0] += 1
            return move

        try:
            history, score, reason = L.play_game(student, opponent, color, forced)
        except Exception as exc:  # Count nothing for a broken game; restart the engines.
            print(f"{type(exc).__name__}: {exc}", flush=True)
            student.close()
            opponent.close()
            student = L.GTPBot(args.student, args.log_dir)
            opponent = L.GTPBot(opponent_name, args.log_dir)
            jobs.put((name, color))
            continue
        with lock:
            results[name].append((color, score, used[0], illegal[0], len(history)))
    student.close()
    opponent.close()


print(f"{'opponent':38} {'book':44} {'games':>5} {'score':>6} {'95% CI':>13} "
      f"{'Black':>6} {'White':>6} {'book moves':>10} {'illegal':>7}")
for opponent_name in args.opponents:
    jobs = queue.Queue()
    # Interleave the books so they share any drift in machine load.
    for game in range(args.games):
        for name in books:
            jobs.put((name, "BW"[game % 2]))
    results = {name: [] for name in books}
    threads = [threading.Thread(target=worker, args=(opponent_name, jobs, results))
               for _ in range(args.workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for name, games in results.items():
        scores = [score for _, score, *_ in games]
        mean = sum(scores) / len(scores)
        deviation = math.sqrt(sum((s - mean) ** 2 for s in scores) / (len(scores) - 1))
        half = 1.96 * deviation / math.sqrt(len(scores))
        by_color = {color: [s for c, s, *_ in games if c == color] for color in "BW"}
        row = {
            "student": args.student, "opponent": opponent_name, "book": name,
            "games": len(games), "score": mean, "ci95": half,
            "black": sum(by_color["B"]) / len(by_color["B"]),
            "white": sum(by_color["W"]) / len(by_color["W"]),
            "book_moves_per_game": sum(g[2] for g in games) / len(games),
            "illegal_book_moves": sum(g[3] for g in games),
            "book_positions": len(books[name]),
        }
        print(f"{opponent_name:38} {Path(name).name:44} {row['games']:5d} {mean:6.3f} "
              f"{mean - half:6.3f}-{mean + half:5.3f} {row['black']:6.3f} {row['white']:6.3f} "
              f"{row['book_moves_per_game']:10.2f} {row['illegal_book_moves']:7d}", flush=True)
        if args.out:
            with open(args.out, "a") as sink:
                sink.write(json.dumps(row) + "\n")
