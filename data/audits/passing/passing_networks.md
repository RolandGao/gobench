# Different KataGo networks on historical passing-loss positions — 2026-09-05

At one visit, the 3293- and 4148-Elo players passed **0/260 times each** across the 13 valid-history positions. The 1011-Elo player passed 26/260 times; the 2002-Elo player passed 116/260 times. All players received the same board and full move history immediately before the original KataGo pass.

## Historical cases

The existing audit covers all 438 current canonical LLM–KataGo records. It identified 18 losses where two judging networks agreed that removing estimated dead stones changes the loser into the winner. All 13 cases with entirely legal histories were tested here. The other five are listed below and excluded because of earlier positional-superko violations. The experiment uses the original board size, komi, color to move, and full legal history.

## Calibrated players: original temperatures

Every player was tested 20 times on each of 13 positions, for 260 trials per player and 1,040 decisions in this main comparison. All measured root visit counts were exactly one.

| Calibrated Elo | Network | Early / late temperature | Passes / 260 | Pass rate on these positions | Positions with a pass / 13 |
| ---: | --- | --- | ---: | ---: | ---: |
| 1011 | `kata1-b6c96-s8080640-d1961030` | 0.7 / 0.7 | 26 | 10.0% | 7 |
| 2002 | `kata1-b6c96-s13733120-d2631546` | 0.5 / 0.3 | 116 | 44.6% | 12 |
| 3293 | `kata1-b6c96-s103950080-d15368530` | 0.5 / 0.1 | 0 | 0.0% | 0 |
| 4148 | `kata1-b18c384nbt-s9761732864-d4253420187` | 0.5 / 0.1 | 0 | 0.0% | 0 |

Elo labels come from [the retained native calibration](../../../log/arena_20260805_040447_246130_2072c54f/run.json), matching the exact temperature variant. The 4148-Elo network is now a one-visit player in this experiment; its prior role as a stronger judge does not add any search visits here.

## Same-temperature control

To separate network differences from the temperature difference, the first two networks were also tested at early temperature 0.5 and late temperature 0.1, matching the stronger players. These variants have their own calibrated Elos. This adds 520 one-visit decisions.

| Calibrated Elo at this temperature | Network checkpoint | Passes / 260 | Positions with a pass / 13 |
| ---: | --- | ---: | ---: |
| 1539 | `kata1-b6c96-s8080640-d1961030` | 82 | 6 |
| 1997 | `kata1-b6c96-s13733120-d2631546` | 143 | 11 |
| 3293 | `kata1-b6c96-s103950080-d15368530` | 0 | 0 |
| 4148 | `kata1-b18c384nbt-s9761732864-d4253420187` | 0 | 0 |

The middle network still passed more often than the earlier network at the same temperature. The observed relationship is therefore not monotonically decreasing across these particular checkpoints. Both stronger networks avoided passing in every sampled trial. This controls for reaching the same positions, unlike full self-matches, where the levels had very different resignation and automatic-ending frequencies.

## Per-position pass counts

Each cell is passes out of 20 trials. Click a case to open its SGF ending **before** the historical bad pass; all original moves needed to reconstruct history are included. Dates below are UTC in 2026.

| Case | Historical run / game | KataGo color, proposed move number | Elo 1011 | Elo 2002 | Elo 3293 | Elo 4148 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| [1](positions/case_01_arena_20260723_173702_334483_0c232340_game_5.sgf) | 07-23 17:37, game 5 | W, move 78 | 4 | 19 | 0 | 0 |
| [2](positions/case_02_arena_20260723_205921_431630_42e71474_game_13.sgf) | 07-23 20:59, game 13 | W, move 88 | 6 | 15 | 0 | 0 |
| [3](positions/case_03_arena_20260731_044901_270838_7068701f_game_11.sgf) | 07-31 04:49, game 11 | W, move 84 | 3 | 11 | 0 | 0 |
| [4](positions/case_04_arena_20260807_184513_963568_b2aa1679_game_6.sgf) | 08-07 18:45, game 6 | B, move 85 | 0 | 9 | 0 | 0 |
| [5](positions/case_05_arena_20260807_184513_963568_b2aa1679_game_13.sgf) | 08-07 18:45, game 13 | W, move 60 | 1 | 4 | 0 | 0 |
| [6](positions/case_06_arena_20260807_223534_789082_9ae5a490_game_10.sgf) | 08-07 22:35, game 10 | B, move 57 | 0 | 2 | 0 | 0 |
| [7](positions/case_07_arena_20260807_223534_789082_9ae5a490_game_19.sgf) | 08-07 22:35, game 19 | W, move 74 | 2 | 12 | 0 | 0 |
| [8](positions/case_08_arena_20260807_223534_789082_9ae5a490_game_21.sgf) | 08-07 22:35, game 21 | W, move 74 | 8 | 15 | 0 | 0 |
| [9](positions/case_09_arena_20260817_065559_213696_f822d790_game_5.sgf) | 08-17 06:55, game 5 | W, move 68 | 0 | 0 | 0 | 0 |
| [10](positions/case_10_arena_20260826_054944_814746_52d18cc7_game_27.sgf) | 08-26 05:49, game 27 | W, move 58 | 0 | 1 | 0 | 0 |
| [11](positions/case_11_arena_20260827_231719_610088_eb49a7a4_game_5.sgf) | 08-27 23:17, game 5 | W, move 80 | 2 | 16 | 0 | 0 |
| [12](positions/case_12_arena_20260827_231719_610088_eb49a7a4_game_11.sgf) | 08-27 23:17, game 11 | W, move 56 | 0 | 5 | 0 | 0 |
| [13](positions/case_13_arena_20260827_231719_610088_eb49a7a4_game_12.sgf) | 08-27 23:17, game 12 | B, move 59 | 0 | 7 | 0 | 0 |

## Source games and alternative moves

Historical result and dead-stone counterfactual come from the prior audit. Alternative moves below are the most frequent choices of the 3293- and 4148-Elo players; selecting them does not demonstrate a winning continuation.

| Case | LLM opponent | Original KataGo player | Recorded result | Most frequent move at Elo 3293 | Most frequent move at Elo 4148 |
| ---: | --- | --- | --- | --- | --- |
| 1 | [gemini-3.1-pro-high-api](../../../log/arena_20260723_173702_334483_0c232340/llm_games.jsonl) | `kata1-b6c96-s16525312-d2925067` | B+7.0 | G1 (20/20) | G1 (19/20) |
| 2 | [gpt5.6-sol-low-api](../../../log/arena_20260723_205921_431630_42e71474/llm_games.jsonl) | `kata1-b6c96-s8982784-d2082583-temp-0.3` | B+3.0 | B8 (17/20) | A7 (18/20) |
| 3 | [grok-4.5-high-api](../../../log/arena_20260731_044901_270838_7068701f/llm_games.jsonl) | `kata1-b6c96-s6127360-d1754797` | B+2.0 | C2 (16/20) | A8 (18/20) |
| 4 | [DeepSeek-V4-Flash-0731-high-api](../../../log/arena_20260807_184513_963568_b2aa1679/llm_games.jsonl) | `kata1-b6c96-s11888896-d2416753-temp-0.5` | W+8.0 | E1 (20/20) | G1 (18/20) |
| 5 | [DeepSeek-V4-Flash-0731-high-api](../../../log/arena_20260807_184513_963568_b2aa1679/llm_games.jsonl) | `kata1-b6c96-s12849664-d2510774` | B+4.0 | A9 (15/20) | A9 (15/20) |
| 6 | [kimi-k3-high-api](../../../log/arena_20260807_223534_789082_9ae5a490/llm_games.jsonl) | `kata1-b6c96-s11888896-d2416753-temp-0.5` | W+13.0 | A7 (17/20) | J7 (15/20) |
| 7 | [muse-spark-1.2-openrouter-high-api](../../../log/arena_20260807_223534_789082_9ae5a490/llm_games.jsonl) | `kata1-b6c96-s8080640-d1961030-temp-0.3` | B+3.0 | J7 (11/20) | G9 (9/20) |
| 8 | [kimi-k3-high-api](../../../log/arena_20260807_223534_789082_9ae5a490/llm_games.jsonl) | `kata1-b6c96-s8982784-d2082583` | B+1.0 | H2 (20/20) | H2 (18/20) |
| 9 | [gpt5.6-luna-high-codex-workspace](../../../log/arena_20260817_065559_213696_f822d790/llm_games.jsonl) | `kata1-b6c96-s6127360-d1754797-temp-0.9` | B+10.0 | H1 (20/20) | H1 (20/20) |
| 10 | [gpt5.6-sol-high-codex-workspace](../../../log/arena_20260826_054944_814746_52d18cc7/llm_games.jsonl) | `kata1-b6c96-s13733120-d2631546-temp-0.3` | B+6.0 | D3 (19/20) | C3 (13/20) |
| 11 | [gpt5.6-sol-max-codex-workspace-continual](../../../log/arena_20260827_231719_610088_eb49a7a4/llm_games.jsonl) | `kata1-b6c96-s18429184-d3197121` | B+3.0 | C6 (20/20) | C6 (20/20) |
| 12 | [gpt5.6-sol-max-codex-workspace-continual](../../../log/arena_20260827_231719_610088_eb49a7a4/llm_games.jsonl) | `kata1-b6c96-s14649344-d2727367-temp-0.3` | B+5.0 | B5 (19/20) | B5 (20/20) |
| 13 | [gpt5.6-sol-max-codex-workspace-continual](../../../log/arena_20260827_231719_610088_eb49a7a4/llm_games.jsonl) | `kata1-b6c96-s14649344-d2727367-temp-0.3` | W+4.0 | J9 (13/20) | J9 (17/20) |

## Excluded historical cases

These are the remaining five of the 18 identified losses. They have earlier illegal histories and were not included in this comparison.

| Source run | Game | LLM opponent | Earlier superko violations at moves |
| --- | ---: | --- | --- |
| [arena_20260723_205921_431630_42e71474](../../../log/arena_20260723_205921_431630_42e71474/llm_games.jsonl) | 15 | gpt5.6-sol-low-api | 47 |
| [arena_20260818_021103_083881_b776e37a](../../../log/arena_20260818_021103_083881_b776e37a/llm_games.jsonl) | 25 | gpt5.6-luna-max-codex-multi | 43, 67, 91, 95, 99, 101, 103, 107, 109, 113, 117, 121, 125, 129, 133 |
| [arena_20260818_035858_741335_f255e7e6](../../../log/arena_20260818_035858_741335_f255e7e6/llm_games.jsonl) | 10 | gpt5.6-sol-max-codex-multi | 38, 52, 56, 60, 64, 68, 72, 76, 80, 84, 88, 92, 96, 100, 104, 108, 112 |
| [arena_20260818_035858_741335_f255e7e6](../../../log/arena_20260818_035858_741335_f255e7e6/llm_games.jsonl) | 14 | gpt5.6-sol-max-codex-multi | 58, 62, 70, 74, 78, 82, 86, 90 |
| [arena_20260826_185411_172712_18e992e8](../../../log/arena_20260826_185411_172712_18e992e8/llm_games.jsonl) | 8 | gpt5.6-sol-max-codex-workspace | 66, 72, 76, 80, 84, 88, 92, 96, 100, 104, 108, 110, 114, 118, 122, 126 |

## Method and limits

- Each trial clears the board, search cache, NN cache, and GTP recent-value history, then replays the complete original move prefix. The initial board is checked against the independent Python replay; all returned board moves are checked for legality.
- `kata-search` selects a move without committing it. Settings retain the historical LLM GTP behavior, including `conservativePass=true`. The engine uses one search thread, one Eigen thread, and randomized NN symmetries with recorded fixed seeds. Model hashes and engine/config metadata are saved.
- The original search trees, RNG state, and past search evaluations are not reconstructed. These are fresh-state position probes. No full games or cleanup continuations were played.
- A pass here reproduces the losing terminal board if the opponent passes back, or immediately when it supplies the second pass. The counts are conditional frequencies on selected failure positions, not overall match-loss rates. Zero observed passes does not prove the true pass probability is zero.
- The historical dead-stone classifications are agreement between two KataGo judges, not mathematical life-and-death proofs.

Code: [audit_passing_networks.py](../../../analysis/audit_passing_networks.py). Results: [main JSON](passing_networks.json), [main CSV](passing_networks.csv), [temperature-control JSON](passing_networks_temperature_control.json), [temperature-control CSV](passing_networks_temperature_control.csv).

```bash
.venv/bin/python audit_passing_networks.py
.venv/bin/python audit_passing_networks.py \
  --players kata1-b6c96-s8080640-d1961030 kata1-b6c96-s13733120-d2631546 \
  --output passing_networks_temperature_control.json
```

Existing arena settings, game results, ratings, and `_FINAL_RUNS` were not modified.
