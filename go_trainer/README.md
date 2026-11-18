# Go Trainer

Play 9×9 Go (Tromp-Taylor rules) against any kata1 KataGo network on your
Mac, while a teacher network grades every move you could play.

- **Teacher:** `kata1-b18c384nbt-s9761732864-d4253420187`, 1 visit per evaluation.
- **Opponent:** any of 96 kata1 networks from katagotraining.org, 1 visit
  per move. Elo ratings (119 to 4208, anchored at random play = 0) come from
  the gobench arena report. Missing networks are downloaded when you start
  a game against them.
- **Rules:** Tromp-Taylor: area scoring, positional superko, suicide allowed.
  The game ends after two passes. Dead stones are *not* removed, so capture
  them before passing. Komi defaults to 7.5.

This folder is self-contained. It needs only macOS, `python3` (standard
library only) and Apple's command line tools (`xcode-select --install`). It
does not use Homebrew or anything else in this repository.

## Run

```sh
python3 trainer.py          # or double-click "Go Trainer.command"
```

The first run downloads KataGo (~370 MB, of which ~50 MB is kept) into
`engine/` and the teacher network (98 MB) into `networks/`. After that a
browser tab opens at http://127.0.0.1:8765. Use `--port` to change the
port and `--no-browser` to skip opening a tab.

## Using it

- Click a point to play. **Undo** (or `U` / `⌘Z`) takes back your last move
  and the opponent's reply.
- **Hide teacher** (or `H`) hides the board overlay, the evaluation bar and
  the move grades. Use it to play blind and reveal the grades afterwards.
- **Points lost** mode labels every legal point with how many points the
  teacher thinks that move loses: green ≤0.5, light green ≤1.5, yellow ≤3,
  orange ≤6, red >6. **Policy** mode shows the teacher's raw move
  probabilities instead. The blue ring marks the teacher's pick, i.e. the
  move it would play at 1 visit.
- The Pass button shows the cost of passing. The move list grades every move,
  and the teacher card summarises your inaccuracies, mistakes and blunders.

## How the grades work

At 1 visit, KataGo's judgment is one neural-network evaluation. For each
position the teacher evaluates the position itself (win rate, score lead and
policy), then evaluates the position after each legal move, again at 1
visit. A move's "points lost" is the teacher's score for the current position
minus its score after that move, floored at 0. Evaluations are deterministic
(no random board symmetries), so the same position always gets the same
grades.

## Files

| Path | What it is |
| --- | --- |
| `trainer.py` | Local web server, game session, teacher grading |
| `rules.py` | Tromp-Taylor rules (legality, captures, scoring) |
| `engines.py` | KataGo GTP opponent, analysis-engine teacher, network downloads |
| `install_katago.py` | Fetches Homebrew's prebuilt KataGo bottles into `engine/` without Homebrew |
| `configs/` | KataGo configs for the teacher and opponent (both 1 visit) |
| `networks.json` | Networks (name, arena Elo, SHA-256, size) |
| `update_elos.py` | Refreshes Elos from an arena report: `python3 update_elos.py ../log/summary/report.txt` |
| `static/` | Browser UI |
| `test_rules.py` | Rules tests: `python3 -m unittest test_rules` |

`engine/`, `networks/`, `logs/` and `settings.json` are created at runtime.
