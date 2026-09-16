# KataGo visit-budget experiment — 2026-09-05

Increasing visits substantially reduces the observed problem, but **5 and 10 do not solve it, and 200 still produced losing passes**. A focused 1,000-visit check produced no passes in 20 trials on the one position that still failed at 200. This does not establish a generally sufficient budget.

## Main experiment

Replay each of the 13 legal-history, consensus passing-loss cases immediately before KataGo’s historical pass, using its original network, original temperature settings, board size 9, komi 7, and Tromp–Taylor rules. Exclude the five cases with earlier superko violations. At each budget, make 20 fresh search trials per position: **260 decisions per budget, 1,820 total**.

| Configured maxVisits | Losing passes / trials | Frequency at these positions | Positions with at least one pass |
| ---: | ---: | ---: | ---: |
| 1 | 118 / 260 | 45.4% | 12 / 13 |
| 5 | 107 / 260 | 41.2% | 7 / 13 |
| 10 | 70 / 260 | 26.9% | 6 / 13 |
| 20 | 41 / 260 | 15.8% | 5 / 13 |
| 50 | 27 / 260 | 10.4% | 4 / 13 |
| 100 | 11 / 260 | 4.2% | 2 / 13 |
| 200 | 2 / 260 | 0.8% | 1 / 13 |

These are repeated decisions at selected historical failure positions, **not full-game loss rates**. A returned pass recreates the original losing terminal board if the opponent passes back (or immediately if responding to a pass). A non-pass is not counted as a demonstrated cleanup or win. All proposed board moves passed the local legality check.

## Configured versus actual visits

The main sweep retains the current GTP behavior: `conservativePass=true` and the existing search-budget reductions. Eleven positions received the full configured visit count. In the two positions following an opponent pass, configured budgets 5, 10, 20, 50, 100, 200 produced actual root visits 3, 5, 10, 25, 50, 100. The two remaining failures at 200 both used a full 200 actual visits.

A separate control disabled all search-budget reductions for the two second-pass positions while retaining `conservativePass=true`. With a full **5 actual visits**, there were **12/40** losing passes; with a full **10 actual visits**, **1/40**. Thus after-pass budget reduction is not the entire explanation. These are separate random samples, not paired trials. [KataGo search-limit configuration](https://github.com/lightvector/KataGo/blob/v1.16.5/cpp/configs/gtp_example.cfg).

## Larger-budget follow-up

The only case still passing at 200 was `arena_20260723_205921_431630_42e71474`, game 13: the `s8982784` network at temperature 0.3, with historical arena Elo 1536. It passed 16/20 times at one visit, 20/20 at five, 18/20 at ten, 10/20 at 100, and 2/20 at 200. At **1,000 actual visits it passed 0/20 times**. The other 12 positions were not tested at 1,000. No complete continuations or new native calibration games were played.

## Per-position results

Each entry is the number of passes out of 20 trials. Elo identifies the original one-visit player; it is not an Elo estimate at the larger budgets.

| Run (UTC, 2026) | Game | Checkpoint | Late temperature | Original Elo | 1 | 5 | 10 | 20 | 50 | 100 | 200 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 07-23 17:37 | 5 | s16525312 | 0.1 | 2262 | 20 | 0 | 0 | 0 | 0 | 0 | 0 |
| 07-23 20:59 | 13 | s8982784 | 0.3 | 1536 | 16 | 20 | 18 | 13 | 9 | 10 | 2 |
| 07-31 04:49 | 11 | s6127360 | 0.1 | 1262 | 19 | 20 | 16 | 7 | 0 | 0 | 0 |
| 08-07 18:45 | 6 | s11888896 | 0.5 | 1743 | 6 | 18 | 14 | 2 | 1 | 0 | 0 |
| 08-07 18:45 | 13 | s12849664 | 0.1 | 1945 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| 08-07 22:35 | 10 | s11888896 | 0.5 | 1743 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| 08-07 22:35 | 19 | s8080640 | 0.3 | 1413 | 6 | 16 | 19 | 18 | 12 | 0 | 0 |
| 08-07 22:35 | 21 | s8982784 | 0.1 | 1574 | 20 | 16 | 2 | 1 | 5 | 1 | 0 |
| 08-17 06:55 | 5 | s6127360 | 0.9 | 640 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 08-26 05:49 | 27 | s13733120 | 0.3 | 1986 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| 08-27 23:17 | 5 | s18429184 | 0.1 | 2387 | 16 | 0 | 0 | 0 | 0 | 0 | 0 |
| 08-27 23:17 | 11 | s14649344 | 0.3 | 2085 | 6 | 2 | 0 | 0 | 0 | 0 | 0 |
| 08-27 23:17 | 12 | s14649344 | 0.3 | 2085 | 4 | 15 | 1 | 0 | 0 | 0 | 0 |

## Interpretation and recommendation

- A small increase is not reliably monotonic. For example, the Muse game (08-07 22:35, game 19) passed 6/20 times at one visit, 19/20 at ten, and 0/20 at 100.
- 100–200 visits are a useful mitigation on this selected set. The 1,000-visit result is encouraging for one difficult position, but does not demonstrate that a particular budget solves the problem across players or complete games.
- To retain the intended low-search strength and cost, continue evaluating extra search specifically when a proposed pass would lose under the exact terminal scorer. The previously suggested 64-visit retry remains an unvalidated parameter; this experiment did not test that complete policy, and a fixed retry budget is not a guarantee.
- A larger constant budget or an adaptive pass check changes the player. Apply the same complete decision/scoring policy in native calibration and LLM games, and recalibrate those variants. Matching maxVisits alone does not align their existing pass-processing differences.

## Reproducibility and limitations

KataGo v1.16.5, revision `ba938676d7f42d70950b3a535af2466fb642008c`, Eigen AVX2 CPU backend, one search thread and one Eigen thread per engine. Each case uses fixed recorded search and NN seeds, randomized NN symmetry, and SHA-256-verified original weights. Before every trial, clear the board and caches and replay the complete history; compare the initial replayed board against Python. Query `kata-search`, which uses the move-generation path without committing the selected move. Capture actual root visits from the engine diagnostics. [GTP command documentation](https://github.com/lightvector/KataGo/blob/v1.16.5/docs/GTP_Extensions.md).

The original search trees, RNG states, and recent search win/loss estimates cannot be reconstructed from move records. In particular, fresh replay clears GTP’s recent-value history, affecting winning-position reductions and resignation eligibility. Clearing only the NN/search cache would not isolate repeated trials because GTP also records values from noncommitting searches. These are controlled fresh-state probes, not exact reproductions of historical RNG outcomes. The dead-stone classifications remain the stronger engines’ estimates from the original audit, not life-and-death proofs. Native historical passing frequency remains unknown because the native SGFs are unavailable.

Code: [audit_passing_visits.py](../../../analysis/audit_passing_visits.py). Raw decisions and configuration: [main sweep](passing_visits.json), [full-budget control](passing_visits_full_budget.json), [1,000-visit follow-up](passing_visits_1000.json). Existing arena settings, results, and ratings were not changed.

```bash
.venv/bin/python audit_passing_visits.py
.venv/bin/python audit_passing_visits.py --full-budget \
  --case arena_20260807_184513_963568_b2aa1679:6 \
  --case arena_20260827_231719_610088_eb49a7a4:12 \
  --budgets 5 10 --output passing_visits_full_budget.json
.venv/bin/python audit_passing_visits.py \
  --case arena_20260723_205921_431630_42e71474:13 \
  --budgets 1000 --output passing_visits_1000.json
```
