# Methodology

GoBench uses 9×9 Tromp–Taylor Go with positional superko. The Python referee
checks complete board history and supplies the prompt's legal-move list.
KataGo executes accepted moves and scores games; its board is checked against
the referee after each move. Raw GTP `play` acceptance is not a legality test.

Ratings use regularized Bradley–Terry fits with jointly estimated Black-color
advantage. Information-gain matchmaking chooses opponents and schedules
color-swapped pairs. Experiment parameters live in `ArenaConfig` and are saved
in each run's `run.json`; see [running arenas](running.md) for recovery semantics.

Hosted model behavior can change even with the same configuration. Recorded
usage and provider pricing determine cost estimates; subscription-backed
players report API-equivalent estimates. Missing usage cannot be reconstructed.
[Setup](setup.md) describes authentication, Codex training budgets, clocks,
resource isolation, checkpoint identity, and evaluation image retention.

Historical legality and passing studies are in [data/audits](../data/audits/).
Passing probes are conditional position studies: they replay legal histories
with fresh search state and cannot reconstruct the original search trees or
establish full-game failure rates. Estimated dead-stone classifications are
engine judgments, not proofs of optimal play.

## API conversation modes

Existing `-api` players use a fresh prompt for each move. Their single-turn
behavior and names are unchanged. Each also has a separate `-api-multi` player,
for example `gpt5.6-sol-high-api-multi`. The `api_multi` profile selects all these
multi-turn API variants, with 14 games per player and batches of 2. Edit that
profile or select individual player names in `CONFIG` to define an experiment.
Separate names keep the modes' Elo ratings and historical results separate.

Multi-turn players retain conversation history within each game, including
native reasoning items/signatures where the provider supports replay. Every
turn still includes the complete current board, rules, recent moves, and legal
move list. No model tools, summaries, or compaction calls are enabled. A new
game (including a replay after the move cap) always starts with empty history.

Before each request, the arena estimates retained history plus the new prompt.
At **250,000 tokens**, it clears the history and sends only the current prompt.
The estimate uses the previous call's reported input and output usage, including
cached input and separately reported reasoning where applicable, plus a
conservative UTF-8 byte estimate of the new prompt. If usage is missing, it
estimates the full payload. This is a reset threshold between turns, not a hard
limit on a single response's reasoning. Provider tokenizers and reasoning
retention differ, so the estimate can reset early. An explicit provider context
overflow with retained history also triggers a fresh-context retry; overflow
of a fresh prompt fails rather than repeatedly resetting.

Run manifests record the mode, policy version, estimator, and threshold. The
ignored raw call ledger stores each new user/assistant exchange once, with
session/reset metadata and a digest of the actual request. Its `request` field
keeps the current turn's prompt for existing audit and recovery consumers;
the wire request also includes the preceding exchanges for that session.
The tracked compact ledger contains the session metadata and digest, excluding
the native conversation contents. Keep the ignored raw logs to resume games:
recovery reconstructs history and reuses completed replies for unfinished moves
without duplicate calls or billing. Provider reasoning that is not returned or
accepted for replay cannot be retained by the arena.

