# Codex preparation and evaluation audit

Snapshot: September 15, 2026. Sol's 4-hour evaluation has 10 completed games of 20 planned. The other nine model/budget combinations have 20 games each.

## Evidence and scope

I inspected the saved preparation disk images with read-only `debugfs`, reading the agents' C++ engines, Python/shell wrappers, and development/play notes. I also inspected the actual model-emitted tool calls in the first evaluation game's API proxy transcript for each of the ten configurations. Evaluation descriptions below are observations from those sampled games, not claims that every game followed the same workflow. Termination counts cover **all completed games** in the frozen snapshot.

For a player named `PLAYER`, the local evidence paths are:

- Preparation image: `untracked_log/PLAYER/codex-checkpoints/PLAYER/checkpoint/disk.img`; agent artifacts are inside `/workspace`.
- Training event log, where present: `untracked_log/PLAYER/codex-checkpoints/PLAYER/preparation/training-events.jsonl`.
- Sampled evaluation transcript: `untracked_log/PLAYER/batch-001/agent-workspaces/game-000001/openai-proxy.jsonl`.
- Recorded game outcomes: `log/PLAYER/llm_games.jsonl`.

These raw workspace images and transcripts are local ignored artifacts. The portable numerical snapshot is [paper_learning_results.json](../data/paper_learning_results.json), which records source run hashes, rating sources, sample sizes, and termination counts. Astra ratings retain the paper's summary fit; Sol ratings come from each run's own report on the shared KataGo ladder. These are separately prepared workspaces, not a single engine observed at successive checkpoints.

## What the agents implemented

The prepared agents built their own small Go programs. Their central technique was Monte Carlo tree search: explore candidate moves, simulate or estimate their continuations, and give more computation to promising branches. RAVE shares information about moves encountered later in simulations; policy priors guide exploration toward moves judged promising before extensive search. Tactical code handles captures, liberties, ladders, and eye shapes. Opening books/cache files save preparation-time computation for use during evaluation.

### GPT-5.6 Sol

| Preparation | Saved implementation | Observed evaluation behavior, game 1 |
| --- | --- | --- |
| 0h | Empty preparation workspace. | Listed the workspace and checked the clock; no engine construction or search invocation appeared in this game. It selected moves directly. |
| 1h | `go9.cpp`: C++ UCT/RAVE engine with tactical playouts, two independent search trees, subtree reuse, and an E5 first-move shortcut. `choose.py`, `replay.py`, and `PLAY_NOTES.md` provide the interface and instructions. | Repeatedly called `choose.py` with the complete move history, often with 30–32-second search budgets. The wrapper pools two searches; the sampled workflow starts a new process per recommendation. |
| 2h | `go9.cpp`: C++ UCT/RAVE engine, rule tests, persistent GTP search, and three large serialized opening trees (`opening.tree`, `after_E5.tree`, `after_E5_F4.tree`, approximately 1.13 GB combined). | Started a persistent engine, recovered an initial session problem by restarting with a PTY, then sent `play` and `analyze` commands. |
| 4h | `go_engine.cpp`: policy-guided search with RAVE, move-average rollout statistics (MAST), last-good-reply heuristics, symmetry handling, and persistent GTP subtree reuse. `recommend.py` combines two independent searches. `PLAYBOOK.md` records tuned settings and opening continuations. | Used the two-search wrapper, then additional standalone searches to resolve uncertainty. For example, after `E5 D5`, it requested a 45-second ensemble and then a 100-second single search. |
| 8h | `go9.cpp`: policy-guided search with a learned local-pattern **value evaluator**, replacing full random continuations at search leaves by default. Saved `value.bin`, separate rollout mode, two-root/deep-search wrappers, and a symmetry-aware 13-ply opening line. Learned move-pattern experiments exist but are disabled by default; RAVE is also disabled in the default learned-value configuration. | Compared learned-value searches with rollout searches, then ran batches of complete self-play continuations for competing candidate moves during the timed game. Wrote results into `GAME1.md`. |

The 8h value evaluator is a small table of weights over local 3×3 board patterns plus global features, not an updated LLM. Its development notes report initial fitting on generated playout positions and subsequent tuning on search-guided self-play. Source code implements both training and inference, and the checkpoint contains the resulting model files. The notes also document weaknesses such as unrealistic preference for second-line openings and rejected later model variants. Their internal match wins are development evidence, not independent benchmark measurements.

Concrete evaluation evidence for Sol 8h: proxy transcript lines 12, 16, and 20 request six batches of eight self-play games each to compare continuations before move 5, at 5,000 simulations per move. Line 24 writes their measured outcomes into `GAME1.md`. This is 48 requested complete continuation games for that decision alone, in addition to direct searches. Similar candidate comparisons recur on later turns. This provides a concrete mechanism for high evaluation cost and time consumption; it does not isolate how much each component caused the final rating.

### GPT-6 Astra

| Preparation | Saved implementation | Observed evaluation behavior, game 1 |
| --- | --- | --- |
| 0h | Empty preparation workspace. | Wrote and compiled `go.cpp` during the game: Monte Carlo search with RAVE-style sharing, tactical move priors, simulated continuations, and area scoring. Later patched its analysis output and recompiled. Supplied board diagrams to the executable for subsequent searches. |
| 1h | `go_engine.cpp`: UCT/RAVE, ladder/tactical priors, reply learning, rule/tactical tests, and large prepared opening trees. `advisor.py` maintains game history and saves the search tree. | Called `advisor.py` to record the opponent's move, search, and record its response, generally using 20–25 seconds for the sampled early searches. |
| 2h | `go9.cpp`: tactical search with a **learned move policy**, PUCT exploration, RAVE, and two threads sharing a tree. `train_patterns.cpp` trains a sparse pattern/feature policy from the agent's own self-play; `pattern_all_weights.bin` is loaded by the default configuration. `play.py` adds opening-book lookup and remaining-time budgeting. | Maintained `current_game.json` and called `play.py --remaining ... --tactics`, using the prepared book and engine. |
| 4h | `board.h`, `engine.cpp`, `play.py`: rule/history implementation, policy-guided search, ladder and small-eye sacrifice logic, tests against an independent rules implementation, and an opening book. Generic learned patterns were tried but left disabled in the chosen configuration. | Called `play.py analyze` with the full colored move history and explicit 25–30-second budgets in the sampled early turns. |
| 8h | `engine/`: C++ search, learned move priors (`policy.bin`), tactical ladder/eye-shape logic, a prepared opening book, and persistent tree caching with history/settings checks. Development notes describe tested alternatives that were deliberately not enabled. | Updated `game.moves` and called `go9 --file game.moves --time 25 --cache game.cache`, reusing prepared knowledge and saved search work. |

The contrast between 0h samples is substantial: Astra used evaluation time to build a search engine, whereas Sol's first 0h game used no such program. This is evidence about those sampled games, not a guarantee of the behavior in every 0h game.

## Resource failures explain much of Sol's observed decline

| Model | Preparation | Elo ± 95% CI | Games | Wins–losses–draws | Time-limit losses | Memory-limit losses |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| Sol | 0h | 1580 ± 178 | 20 | 10–9–1 | 2 | 0 |
| Sol | 1h | 2656 ± 166 | 20 | 13–7–0 | 7 | 0 |
| Sol | 2h | 2073 ± 165 | 20 | 8–12–0 | 12 | 0 |
| Sol | 4h, preliminary | 1759 ± 248 | 10 | 5–5–0 | 4 | 1 |
| Sol | 8h | 1046 ± 194 | 20 | 5–15–0 | 15 | 0 |
| Astra | 0h | 2691 ± 186 | 20 | 14–6–0 | 0 | 0 |
| Astra | 1h | 3149 ± 196 | 20 | 15–5–0 | 1 | 0 |
| Astra | 2h | 3563 ± 181 | 20 | 10–9–1 | 2 | 0 |
| Astra | 4h | 3421 ± 175 | 20 | 12–8–0 | 1 | 0 |
| Astra | 8h | 3436 ± 183 | 20 | 8–10–2 | 0 | 0 |

Every loss in Sol's prepared configurations is a recorded resource-limit forfeit. The Elo decline therefore cannot be interpreted simply as evidence of poorer move selection after longer preparation. The benchmark measures the entire agent under the 30-minute game allowance, including search, model reasoning, orchestration, and memory use. These logs do not establish what its playing strength would be with unlimited time, and timeouts do not establish whether it was winning on the board.

Finally, “fixed weights” here means **fixed base-LLM weights**. Several agents did train numerical parameters for auxiliary Go programs and store them in their filesystem context. Those auxiliary models were then used as tools during evaluation.
