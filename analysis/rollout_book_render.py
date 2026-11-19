"""Rank the fixes a rollout book search found and write the tutorial file.

A fix is a book move at a position where the student is to move. The student
follows the book with certainty, so a position is reached with the product of
the opponent's reply frequencies on the way to it (halved, because the student
plays each color half the time). Its gain is the win rate after the book move,
with the proxy playing on alone, minus the win rate of the proxy alone from the
position. The win rate of a whole book is then the proxy's own win rate plus
the sum over its fixes of reach x gain, whatever fixes lie above or below.

Fixes share prefixes, so they are not picked one by one. A fix costs only the
tokens it adds to the file, and for a price per token the best book is the set
of fixes, closed under "the moves before it are in the book", that maximizes
total reach x gain minus price x tokens. The price is lowered until the file
fills the token cap. A fix with no gain of its own is kept when the fixes below
it pay for it, so a line that needs several fixes is judged as a whole.

The book move at a position is the candidate the search played most: Thompson
sampling sends the games to the move that wins most with the book below it.

The proxy's win rate from a position is measured by natural rollouts, which
are few at rarely reached positions. They are combined with a prediction from
the teacher's win rate there, fitted on all positions' natural rollouts, with
the weight the rollouts themselves say the prediction deserves.

Writes OUT (the tutorial), and OUT with .fixes.tsv (every fix in it, ranked).
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rollout_book_lib as L
from gobench import opening_book
from gobench.tutorial import count_tokens

parser = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("tree_json")
parser.add_argument("out")
parser.add_argument("--tokens", type=int, default=5000, help="token cap of the file")
parser.add_argument("--moves", type=int, default=None,
                    help="write a Track 3.5 book (gobench/opening_book.py) of at most this "
                         "many moves instead of a tutorial")
parser.add_argument("--header", default="data/tutorials/rollout_book_header.md")
parser.add_argument("--judge", default=L.TEACHERS[0],
                    help="teacher whose win rate predicts the proxy's")
parser.add_argument("--min-rollouts", type=int, default=8,
                    help="rollouts a book move needs")
parser.add_argument("--prior-sd", type=float, default=None,
                    help="spread of true gains used to shrink noisy ones "
                         "(default: estimated from the tree)")
args = parser.parse_args()

tree = json.load(open(args.tree_json))
nodes = tree["nodes"]
header = open(args.header).read().rstrip() + "\n"


def rate(wins, n):
    """(mean, variance of the mean) of n scores summing to wins."""
    smooth = (wins + 0.5) / (n + 1.0)
    return wins / n, smooth * (1.0 - smooth) / n


def features(key, node):
    value = min(max(node["v"][args.judge], 0.005), 0.995)
    return [1.0, math.log(value / (1.0 - value)), len(key.split()) / 20.0]


# Predict the proxy's win rate from the teacher's: a logistic fit on every
# searched position's natural rollouts.
judged = [(key, node) for key, node in nodes.items()
          if node["x"] == 2 and args.judge in node.get("v", {}) and node["nn"]]
X = numpy.array([features(key, node) for key, node in judged])
wins = numpy.array([node["nw"] for _, node in judged])
trials = numpy.array([float(node["nn"]) for _, node in judged])
beta = numpy.zeros(X.shape[1])
for _ in range(50):
    mean = 1.0 / (1.0 + numpy.exp(-X @ beta))
    hessian = (X * (trials * mean * (1.0 - mean))[:, None]).T @ X + 1e-6 * numpy.eye(len(beta))
    beta = beta + numpy.linalg.solve(hessian, X.T @ (wins - trials * mean))
predicted = dict(zip((key for key, _ in judged), 1.0 / (1.0 + numpy.exp(-X @ beta))))


def likelihood(strength):
    """Log likelihood of the natural rollouts if the prediction is worth strength rollouts."""
    total = 0.0
    for key, node in judged:
        a, b = strength * predicted[key], strength * (1.0 - predicted[key])
        total += (math.lgamma(a + node["nw"]) + math.lgamma(b + node["nn"] - node["nw"])
                  - math.lgamma(strength + node["nn"])
                  + math.lgamma(strength) - math.lgamma(a) - math.lgamma(b))
    return total


STRENGTH = max((2.0 ** (k / 2.0) for k in range(4, 21)), key=likelihood)


def natural(key):
    """(mean, variance) of the proxy's win rate from key without a book."""
    node = nodes[key]
    if key not in predicted:
        return rate(node["nw"], node["nn"])
    mean = (node["nw"] + STRENGTH * predicted[key]) / (node["nn"] + STRENGTH)
    return mean, mean * (1.0 - mean) / (node["nn"] + STRENGTH + 1.0)


def child_key(key, move, reply):
    return f"{key} {move} {reply}".strip()


def replies(key, move):
    """[(reply, frequency, child node or None)] for a candidate, most frequent first."""
    counts = nodes[key]["a"][move]["r"]
    total = sum(counts.values())
    ordered = sorted(counts.items(), key=lambda item: -item[1])
    return [(reply, n / total, nodes.get(child_key(key, move, reply)))
            for reply, n in ordered]


def forced_value(key, move):
    """Win rate after forcing move at key and letting the proxy play on alone.

    Two independent estimates are pooled: the natural win rates of the positions
    after each opponent reply, weighted by the reply's frequency, and the
    natural rollouts from key in which the proxy happened to choose the move.
    Replies whose positions were never searched are measured together: all
    their visits were natural rollouts, in proportion to the replies' frequency.
    """
    node = nodes[key]
    arm = node["a"][move]
    mean = variance = 0.0
    rest_share = rest_wins = rest_n = 0.0
    for reply, share, child in replies(key, move):
        if reply == "resign":
            mean += share
        elif child is not None and child_key(key, move, reply) in predicted:
            value, spread = natural(child_key(key, move, reply))
            mean += share * value
            variance += share * share * spread
        else:
            rest_share += share
            if child is not None:
                rest_wins += child["nw"]
                rest_n += child["nn"]
    if rest_share:
        value, spread = rate(rest_wins, rest_n) if rest_n else (arm["w"] / arm["n"], 0.25)
        mean += rest_share * value
        variance += rest_share * rest_share * spread
    own = node["nm"].get(move)
    if own and own[0] and variance > 0:
        direct, direct_variance = rate(own[1], own[0])
        weight = variance / (variance + direct_variance)
        mean = (1 - weight) * mean + weight * direct
        variance = variance * direct_variance / (variance + direct_variance)
    return mean, variance


# The book move of every searched position, and its raw gain with its noise.
book_move, gains = {}, {}
for key, node in nodes.items():
    if node["x"] != 2 or not node["nn"]:
        continue
    eligible = [move for move, arm in node["a"].items() if arm["n"] >= args.min_rollouts]
    if not eligible:
        continue
    move = max(eligible, key=lambda m: (node["a"][m]["n"], node["a"][m]["w"]))
    base, base_variance = natural(key)
    value, variance = forced_value(key, move)
    book_move[key] = move
    gains[key] = (value - base, variance + base_variance)

# A book move only matters when the proxy would have played something else, and
# matters more the further the teacher's win rate drops after the proxy's own
# move. Fit the average gain as a function of both, then pull each noisy gain
# toward that expectation by as much as its noise warrants.
def expectation_terms(key):
    node = nodes[key]
    own = node["nm"].get(book_move[key], [0, 0.0])[0]
    deviates = 1.0 - (own + 0.5) / (node["nn"] + 1.0)
    if "drop" in node:
        return [deviates, deviates * node["drop"], 0.0]
    return [0.0, 0.0, deviates]  # searched before the teacher's drop was recorded


keys = list(gains)
terms = numpy.array([expectation_terms(key) for key in keys])
observed = numpy.array([gains[key][0] for key in keys])
noise = numpy.array([gains[key][1] for key in keys])
weights = 1.0 / noise
theta = numpy.linalg.solve((terms * weights[:, None]).T @ terms + 1e-9 * numpy.eye(3),
                           terms.T @ (weights * observed))
expected = dict(zip(keys, terms @ theta))
if args.prior_sd is None:
    # The spread of true gains around the expectation that makes the observed
    # gains, each with its own noise, most likely.
    residual = observed - terms @ theta
    prior_variance = max(
        (0.005 * 1.25 ** k for k in range(20)),
        key=lambda sd: -float((numpy.log(sd * sd + noise)
                               + residual ** 2 / (sd * sd + noise)).sum())) ** 2
else:
    prior_variance = args.prior_sd ** 2


def shrunk(key):
    gain, variance = gains[key]
    trust = prior_variance / (prior_variance + variance)
    return expected[key] + trust * (gain - expected[key])


# What a fix adds to the file: the opponent's move and the book's reply, and
# in a tutorial the newline and move number of every line after the first.
MOVE_TOKENS, LINE_TOKENS = (2.0, 0.0) if args.moves else (2.0, 2.0)


def best_book(key, reach, price, chosen):
    """Net value of the best book from key down; records its positions in chosen."""
    if key not in book_move:
        return 0.0
    move = book_move[key]
    value = reach * shrunk(key) - price * MOVE_TOKENS
    children, positive, spare = set(), 0.0, None
    for reply, share, child in replies(key, move):
        if child is None or reply in ("resign", "end"):
            continue
        below = set()
        net = best_book(child_key(key, move, reply), reach * share, price, below)
        if not below:
            continue
        # Every continuation but one starts a new line.
        net -= price * LINE_TOKENS
        if net > 0:
            positive += net
            children |= below
        elif spare is None or net > spare[0]:
            spare = (net, below)
    if children:
        value += positive + price * LINE_TOKENS
    elif spare is not None and spare[0] + price * LINE_TOKENS > 0:
        value += spare[0] + price * LINE_TOKENS
        children = spare[1]
    if value <= 0:
        return 0.0
    chosen.add(key)
    chosen |= children
    return value


white_total = sum(tree["white_first"].values())
ROOTS = {"B": [("", 0.5)],
         "W": [(first, 0.5 * n / white_total)
               for first, n in sorted(tree["white_first"].items(), key=lambda item: -item[1])]}


def select(price):
    chosen = set()
    for roots in ROOTS.values():
        for key, reach in roots:
            best_book(key, reach, price, chosen)
    return chosen


notation = L.to_notation


def render(chosen):
    """Return (text of the two books, fixes in file order)."""
    fixes = []

    def lines_from(key, reach, line, out):
        """Append the book below key to line, opening new lines for other replies."""
        move = book_move[key]
        plies = len(key.split())
        line.append(notation(move))
        fixes.append((key, move, reach))
        first = True
        for reply, share, _ in replies(key, move):
            child = child_key(key, move, reply)
            if child not in chosen:
                continue
            if first:
                first = False
                line.append(notation(reply))
                lines_from(child, reach * share, line, out)
            else:
                branch = [str(plies + 2), notation(reply)]
                out.append(branch)
                lines_from(child, reach * share, branch, out)

    parts = []
    for color, title in L.BOOK_TITLES.items():
        out = []
        for key, reach in ROOTS[color]:
            if key not in chosen:
                continue
            line = ["1"] + [notation(move) for move in key.split()]
            out.append(line)
            lines_from(key, reach, line, out)
        parts.append(title + "\n" + "\n".join(" ".join(line) for line in out))
    return "\n\n".join(parts) + "\n", fixes


def track35(chosen):
    """The chosen fixes as Track 3.5 book lines, most reached first."""
    longer = {" ".join(key.split()[:-2]) for key in chosen if len(key.split()) >= 2}
    ends = [key for key in chosen if key not in longer]
    return "".join(
        f"{'BW'[len(key.split()) % 2]} {key} {book_move[key]}".replace("  ", " ") + "\n"
        for key in sorted(ends, key=lambda key: -nodes[key]["n"])
    )


def output(chosen):
    """Return (the file's text, its size in the unit of the cap)."""
    if args.moves:
        text = track35(chosen)
        return text, opening_book.parse(text, 10 ** 9).size
    text = header + "\n" + render(chosen)[0]
    return text, count_tokens(text)


# Lower the price per token until the file fills the cap.
cap = args.moves or args.tokens
low, high = 0.0, 1.0  # high: too expensive, an empty book fits
best = None
for _ in range(60):
    price = math.sqrt(low * high) if low > 0 else high / 4
    chosen = select(price)
    text, size = output(chosen)
    if size <= cap:
        high, best = price, (chosen, text, size)
    else:
        low = price
    if low > 0 and high / low < 1.002 or high < 1e-12:
        break
chosen, text, size = best
body, fixes = render(chosen)

# Every line must be legal under the arena's rules and must read back as written.
wanted = {key: move for key, move, _ in fixes}
if args.moves:
    parsed = opening_book.parse(text, cap)
    book = {" ".join(moves): move for (_, moves), move in parsed.replies.items()}
    if parsed.problems or parsed.dropped_moves:
        sys.exit(f"the rendered book has problems: {parsed.summary()}")
else:
    book = L.parse_book(text)
if book != wanted:
    sys.exit("the rendered book does not parse back to the selected fixes")
for key, move in book.items():
    L.Referee(key.split() + [move])
Path(args.out).write_text(text)

# Name each proposing network by its arena Elo.
elo = dict(line.rstrip("\n").split("\t")[::2]
           for line in open(L.ROOT / "data/katago_network_speed_elo.txt"))
LABELS = {name: f"teacher{elo[name]}" for name in tree["teachers"]}
LABELS[tree["student"]] = "proxy_policy"
LABELS["natural"] = "proxy_rollouts"
changes = 0
with open(str(args.out) + ".fixes.tsv", "w") as sink:
    sink.write("rank\treach\tgain\tshrunk_gain\treach_x_shrunk_gain\tmove_number\t"
               "proxy_top_move\tproxy_plays_it\tproposed_by\tline\n")
    for rank, (key, move, reach) in enumerate(
            sorted(fixes, key=lambda fix: -fix[2] * shrunk(fix[0])), 1):
        node = nodes[key]
        source = node["a"][move]["src"]
        # A change: the proxy's own policy prefers another move here.
        top = source.get(tree["student"], [1])[0] == 0
        changes += not top
        played = node["nm"].get(move, [0, 0.0])[0] / node["nn"]
        sink.write(f"{rank}\t{reach:.5f}\t{gains[key][0]:+.3f}\t{shrunk(key):+.3f}\t"
                   f"{reach * shrunk(key):+.6f}\t{len(key.split()) + 1}\t"
                   f"{'yes' if top else 'no'}\t{played:.2f}\t"
                   f"{','.join(sorted(LABELS.get(name, name) for name in source))}\t"
                   f"{(key + ' ' + move).strip()}\n")

black = natural("")[0]
white = sum(2 * reach * natural(key)[0] for key, reach in ROOTS["W"]
            if key in nodes and nodes[key]["nn"])
baseline = 0.5 * (black + white)
raw = sum(reach * gains[key][0] for key, _, reach in fixes)
kept = sum(reach * shrunk(key) for key, _, reach in fixes)
print(f"{args.out}: "
      + (f"{size} moves (limit {cap}), " if args.moves
         else f"{size} tokens (header {count_tokens(header)}), ")
      + f"{len(fixes)} book moves of {len(book_move)} searched, {changes} of them not the "
      f"proxy's top move, deepest at move {max(len(key.split()) for key in chosen) + 1}")
print(f"  proxy alone {baseline:.3f} (Black {black:.3f}, White {white:.3f}); predicted with "
      f"book {baseline + kept:.3f} after shrinking gains ({baseline + raw:.3f} from raw gains)")
print(f"  proxy win rate from teacher win rate: logit = {beta[0]:+.2f} {beta[1]:+.2f} x "
      f"teacher logit {beta[2]:+.2f} x move/20, worth {STRENGTH:.0f} rollouts")
print(f"  expected gain of a book move the proxy would not play: {theta[0]:+.3f} "
      f"{theta[1]:+.2f} x teacher's drop ({theta[2]:+.3f} where the drop was not recorded); "
      f"spread of true gains around it {math.sqrt(prior_variance):.3f}")
