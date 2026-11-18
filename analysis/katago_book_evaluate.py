"""Evaluate student moves the book does not list, against the book's best, with KataGo.

IN_JSON lists {path, student, best, to_move} in book orientation. The positions
after the student's move and after the book's best move are each searched for
--visits; the loss is their win rate difference for the mover. The output is
the --evals input of katago_book_student. Results already in OUT_JSONL are kept.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("katago", help="KataGo binary")
parser.add_argument("model", help="network file, e.g. kata1-b18c384nbt-s9761732864-d4253420187")
parser.add_argument("in_json")
parser.add_argument("out_jsonl")
parser.add_argument("--visits", type=int, default=150)
args = parser.parse_args()
katago, model, src, out, visits = args.katago, args.model, args.in_json, args.out_jsonl, args.visits
rows = json.load(open(src))
done = ({tuple(json.loads(l)["path"]) for l in open(out)}
        if Path(out).exists() else set())

cfg = tempfile.NamedTemporaryFile("w", suffix=".cfg", delete=False)
cfg.write("""logToStderr = false
logDir = /tmp/katago-eval-logs
numAnalysisThreads = 4
numSearchThreadsPerAnalysisThread = 4
nnMaxBatchSize = 32
nnCacheSizePowerOfTwo = 20
reportAnalysisWinratesAs = SIDETOMOVE
""")
cfg.close()
proc = subprocess.Popen([katago, "analysis", "-config", cfg.name, "-model", model],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
pending = 0
colors = "BW"
for i, r in enumerate(rows):
    if tuple(r["path"]) in done:
        continue
    # Search the position after each move with equal effort.
    for which in ("student", "best"):
        moves = [[colors[k % 2], mv] for k, mv in enumerate(r["path"])]
        moves.append([r["to_move"], r[which]])
        query = {"id": f"{i}:{which}", "rules": "tromp-taylor", "komi": 7,
                 "boardXSize": 9, "boardYSize": 9, "moves": moves, "maxVisits": visits}
        proc.stdin.write(json.dumps(query) + "\n")
        pending += 1
proc.stdin.flush()
partial = {}
with open(out, "a") as sink:
    while pending:
        reply = json.loads(proc.stdout.readline())
        pending -= 1
        if "error" in reply:
            print("error", reply, file=sys.stderr)
            continue
        i, which = reply["id"].split(":")
        i = int(i)
        # The child's winrate is for the opponent, who moves next.
        partial.setdefault(i, {})[which] = 1.0 - reply["rootInfo"]["winrate"]
        if len(partial[i]) == 2:
            r = rows[i]
            wr = partial.pop(i)
            sink.write(json.dumps({
                "id": i, "path": r["path"], "student": r["student"], "best": r["best"],
                "best_winrate": wr["best"], "student_winrate": wr["student"],
                "loss": max(0.0, 100.0 * (wr["best"] - wr["student"])), "visits": visits,
            }) + "\n")
            sink.flush()
proc.stdin.close()
proc.wait()
