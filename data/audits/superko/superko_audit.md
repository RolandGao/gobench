# Historical LLM–KataGo superko audit

Implementation follow-up: the strict Python referee is now implemented in
`go_rules.py` and `game_engine.py`. The diagnosis and prompt examples below
describe the pre-fix implementation. Historical records and the original audit
results are preserved. Regression tests reject all 95 first violations, replay
all 343 clean games, and match KataGo's complete strict legal-move masks on
2,277 historical and generated positions. The audit's optional native check
continues to use raw GTP explicitly so it can inspect illegal continuations.

Audited on 2026-09-04. **95 of 438 completed games (21.69%) violated positional superko.** All first violations were LLM moves.

The canonical directory is `log/` (there is no `logs/`). The audit covers all 438 LLM games in 24 runs, reconciled against `results.csv`, with 43,817 recorded actions. All use 9×9 Tromp–Taylor rules. There are no missing canonical LLM records or replay errors. Aborted/uncommitted games in `untracked_log/` are outside this denominator.

| Measure | Count |
| --- | ---: |
| Games with any violation | 95 |
| Games whose first violation is simple ko | 86 |
| Games whose first violation is other positional superko | 9 |
| All recorded simple-ko violations | 440 |
| All recorded other positional-superko violations | 17 |
| All recorded violations by the LLM | 457 |
| All recorded violations by KataGo | 0 |
| Games containing simple-ko violations anywhere | 88 |
| Games containing other superko violations anywhere | 15 |

The last two game categories overlap: 8 games contain both types. The 457-move inventory follows the recorded continuation even after the first illegal move; it is not 457 independent failures from legal histories. The 95 first violations establish the affected-game count. Of those affected games, the recorded results are 49 LLM wins, 44 LLM losses, and 2 draws; these are the historical outcomes, not corrected outcomes.

## Why the prompt's list is wrong

`arena.py:_choose_llm_move` obtains both lists from `game.get_possible_moves()` and passes them into `_llm_move_prompt`. The prompt describes the legal-move list as authoritative. It also accepts any LLM response contained in that list.

`game_engine.py:KataGoGameEngine.get_possible_moves` probes each empty point with GTP `play COLOR MOVE`, calls `undo` on success, and labels the move legal. Its assumption that rejected empty points account for all ko/superko restrictions is false. `do_action` also uses GTP `play` without a separate repetition check, so the same error affects both advertised legality and move acceptance.

KataGo's GTP `play` tolerates superko violations and, since v1.16.1, simple-ko violations. This repository pins v1.16.5. See the [official KataGo release notes](https://github.com/lightvector/KataGo/releases/tag/v1.16.1). Setting `kata-set-rules tromp-taylor` does not turn the tolerant `play` interface into a strict referee. The rejected-point list can still include single-stone suicide, which leaves the board unchanged, so a nonempty illegal list does not demonstrate correct superko enforcement.

A future production fix must use strict legality for both `get_possible_moves` and `do_action`, using the same complete board history. Passes must remain exempt; captures and legal multi-stone suicide must be resolved before comparing board positions. Merely editing the prompt or retry logic cannot fix this.

## Direct historical evidence

In `log/arena_20260829_075436_193500_7bf0a61a/llm_games.jsonl`, game 5, move 141 is Black A8. It recreates the board after move 139 and is an immediate ko recapture. The saved request in `untracked_log/arena_20260829_075436_193500_7bf0a61a/batch-003/llm-calls.jsonl` explicitly lists `A8` among legal moves, omits it from the ko/superko list, and the LLM responds `A8`.

For an example requiring positional history beyond simple ko: `log/arena_20260724_053334_256504_92b016a9/llm_games.jsonl`, game 11, move 87 is Black C2. It recreates the board after move 84, following Black D2 (a multi-stone suicide) and White pass.

All 16 recovered first-violation prompts advertise the violating move as legal. Details and source locations are in `superko_prompt_evidence.json`. Raw prompts were not recovered for all 95 affected games; the game-replay count does not depend on recovering prompts.

## Validation and reproduction

The independent Python replay compares exact board tuples (not probabilistic hashes), includes the initial empty board in history, resolves opponent captures before friendly suicide, and exempts pass and resignation from repetition checks. Six unit tests cover immediate ko, a legal recapture after a threat and answer, pass, single-stone suicide, multi-stone suicide followed by illegal recreation, and occupied points.

Cross-checked all 438 games and 43,685 non-resignation board transitions against KataGo 1.16.5+b6c96-s8080K, with no mismatches. KataGo's strict neural-policy mask marks all 457 detected violating moves illegal, while GTP `play` accepts them. Re-running the current `get_possible_moves` before each of the 95 first violations incorrectly lists that move as legal. The NN mask was used for verification, not to calculate the independent replay count.

```bash
python3 -m unittest test_audit_superko -v
python3 audit_superko.py

# Optional cross-check with the installed CPU KataGo:
KATAGO_BINARY=.venv/katago/v1.16.5-eigenavx2/squashfs-root/AppRun \
KATAGO_MODEL=.venv/katago/networks/kata1/kata1-b6c96-s8080640-d1961030.txt.gz \
KATAGO_CONFIG=.venv/katago/v1.16.5-eigenavx2/default_gtp.cfg \
python3 audit_superko.py --verify-katago
```

`superko_audit.json` contains the summary, full game inventory, and every violation with the repeated position's move number. `superko_violations.csv` is the spreadsheet-friendly violation inventory. The audit adds no changes to arena/game-engine behavior or historical records.

## Per-player breakdown

| LLM player | Games | Affected | Simple-ko moves | Other superko moves |
| --- | ---: | ---: | ---: | ---: |
| gpt-5.4-low-api | 46 | 18 | 48 | 4 |
| gpt5.6-luna-high-codex-multi | 14 | 9 | 117 | 1 |
| gpt5.6-sol-low-codex-single | 14 | 6 | 36 | 0 |
| gpt5.6-sol-low-api | 20 | 5 | 18 | 0 |
| grok-4.5-high-api | 14 | 5 | 5 | 2 |
| gpt5.6-luna-high-codex-workspace | 14 | 4 | 33 | 0 |
| gpt5.6-luna-low-codex-single | 14 | 4 | 8 | 0 |
| gpt5.6-sol-max-codex-workspace | 14 | 4 | 18 | 1 |
| gpt5.6-luna-high-codex-single | 14 | 3 | 6 | 0 |
| gpt5.6-luna-max-codex-multi | 14 | 3 | 21 | 0 |
| gpt5.6-sol-high-api | 14 | 3 | 4 | 1 |
| gpt5.6-sol-high-codex-workspace-continual2 | 14 | 3 | 22 | 1 |
| gpt5.6-sol-max-codex-multi | 14 | 3 | 26 | 0 |
| kimi-k3-high-api | 14 | 3 | 7 | 0 |
| muse-spark-1.2-openrouter-high-api | 14 | 3 | 5 | 2 |
| gemini-3.6-flash-high-api | 20 | 2 | 5 | 3 |
| gpt5.6-luna-max-codex-single | 10 | 2 | 7 | 0 |
| gpt5.6-sol-high-codex-multi | 14 | 2 | 3 | 0 |
| gpt5.6-sol-high-codex-workspace-continual3 | 10 | 2 | 22 | 0 |
| gpt5.6-sol-max-codex-workspace-continual | 14 | 2 | 3 | 1 |
| opus-5-high-api | 14 | 2 | 17 | 0 |
| DeepSeek-V4-Flash-0731-high-api | 14 | 1 | 2 | 0 |
| gemini-3.1-pro-high-api | 20 | 1 | 2 | 0 |
| gpt5.6-sol-high-codex-workspace | 14 | 1 | 1 | 0 |
| gpt5.6-sol-high-prime-isolated | 14 | 1 | 1 | 0 |
| gpt5.6-sol-low-codex-multi | 14 | 1 | 1 | 0 |
| gpt5.6-sol-low-codex-workspace | 14 | 1 | 1 | 0 |
| gpt5.6-sol-low-codex-workspace-continual2 | 14 | 1 | 1 | 1 |
| qwen3.8-max-high-api | 4 | 0 | 0 | 0 |
