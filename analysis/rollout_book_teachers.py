"""Compare the networks that propose book moves in a rollout book search.

At every searched position each network (the teachers and the student proxy)
proposed its top policy move. Where two networks disagree, both moves were
forced many times, and the difference of their win rates says whose suggestion
the proxy turns into wins against this opponent. Positions are weighted by how
well both moves were sampled.
"""
import argparse
import itertools
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rollout_book_lib as L

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("tree_json")
parser.add_argument("--min-rollouts", type=int, default=20,
                    help="rollouts both moves need for a position to count")
args = parser.parse_args()

tree = json.load(open(args.tree_json))
elo = dict(line.rstrip("\n").split("\t")[::2]
           for line in open(L.ROOT / "data/katago_network_speed_elo.txt"))
networks = [*tree["teachers"], tree["student"]]
label = {name: f"{elo[name]} Elo" for name in networks}
label[tree["student"]] += " (proxy)"

top = {}  # node key -> {network: its top move}
for key, node in tree["nodes"].items():
    if node["x"] != 2:
        continue
    for move, arm in node["a"].items():
        for name, (rank, _) in arm["src"].items():
            if rank == 0 and name in label:
                top.setdefault(key, {})[name] = move

print(f"{tree['games']} games, {len(top)} searched positions; a position counts when "
      f"both moves have {args.min_rollouts}+ rollouts\n")
print(f"{'first':18} {'second':18} {'positions':>9} {'they agree':>10} {'compared':>8} "
      f"{'first minus second':>18} {'95% CI':>15} {'first better':>12}")
for first, second in itertools.combinations(networks, 2):
    agree = both = compared = wins = 0
    weight_sum = weighted = variance = 0.0
    for key, moves in top.items():
        if first not in moves or second not in moves:
            continue
        both += 1
        if moves[first] == moves[second]:
            agree += 1
            continue
        a, b = (tree["nodes"][key]["a"][moves[name]] for name in (first, second))
        if min(a["n"], b["n"]) < args.min_rollouts:
            continue
        pa, pb = a["w"] / a["n"], b["w"] / b["n"]
        noise = ((a["w"] + 0.5) / (a["n"] + 1) * (1 - (a["w"] + 0.5) / (a["n"] + 1)) / a["n"]
                 + (b["w"] + 0.5) / (b["n"] + 1) * (1 - (b["w"] + 0.5) / (b["n"] + 1)) / b["n"])
        weight = 1.0 / (1.0 / a["n"] + 1.0 / b["n"])
        weight_sum += weight
        weighted += weight * (pa - pb)
        variance += weight * weight * noise
        compared += 1
        wins += pa > pb
    if not weight_sum:
        continue
    mean, half = weighted / weight_sum, 1.96 * math.sqrt(variance) / weight_sum
    print(f"{label[first]:18} {label[second]:18} {both:9d} {agree / both:10.0%} {compared:8d} "
          f"{mean:+18.3f} {mean - half:+7.3f}..{mean + half:+.3f} {wins / compared:12.0%}")
