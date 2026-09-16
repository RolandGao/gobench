# Running and recovering arenas

Run commands from the repository root. See [setup](setup.md) first.

See [prompt caching](prompt-caching.md) for provider defaults, Anthropic API-key
and OAuth caching, and historical cache-usage observations.


Run `arena.py` without arguments using the editable `CONFIG` block near the
top of the file:

```bash
python3 arena.py
```

Each LLM writes to `log/<full-player-name>/`, for example
`log/gpt5.6-sol-high-api-multi/`, with raw journals under the matching
`untracked_log/<full-player-name>/`. The effort, mode, and numbered experiment
suffix are part of the name. Multi-player profiles launch independent processes
and give each LLM its own directory and report. KataGo-only runs use
`arena_katago_YYYYMMDD_HHMMSS_microseconds_id` directory names.

When launching from source configuration, an existing LLM directory must be an
**active, uncommented entry in `_FINAL_RUNS`** before the arena will reuse it.
An explicit `--resume` also permits reuse, without editing `_FINAL_RUNS`.
The arena then recovers
its games and pending batches, updates its reports, and continues toward
`total_games` as a cumulative target. For example, raise 14 to 28 to add 14 games
to a completed 14-game evaluation. Keeping 14 refreshes reports without replaying
those games. Game rules and player settings must remain compatible. Its own
records are excluded from historical inputs to avoid counting them twice.
Concurrent writers to the same LLM directory are rejected. Completed API runs
can start additional games using their tracked results alone: if the local
journal was removed, it is rebuilt from `llm_games.jsonl` after checking it
against `results.csv` and the committed batch metadata. Each new game starts a
fresh conversation. Interrupted games still require their original untracked
logs, and workspace runs require their checkpoint. Historical directories are
not renamed.

The retained `_FINAL_RUNS` KataGo baselines are:

| Run | KataGo vs KataGo games |
|---|---:|
| `arena_20260717_215813_957127_3b740750` | 100,000 |
| `arena_20260722_210708_427338_47435160` | 100,000 |
| `arena_20260723_055601_438304_148a54e8` | 100,000 |
| `arena_20260805_040447_246130_2072c54f` | 20,000 |

The other 23 former entries contain LLM games and are commented out for the
rerun. Their files remain available. Classification was checked against every
game row in each run's `results.csv`.

Resume interrupted runs by passing names under `log/` or tracked directory
paths, separated by commas. Each run uses its own saved `run.json` configuration;
source-code defaults do not alter a resumed run:

```bash
python3 arena.py --resume log/arena_YYYYMMDD_HHMMSS_microseconds_id
python3 arena.py --resume gpt5.6-sol-high-api-multi3,gpt5.6-sol-max-api-multi,gpt5.6-luna-high-api-multi,gpt5.6-luna-max-api-multi
```

Multiple runs resume in separate processes. A failed run is reported immediately
while the others continue; the command exits with a nonzero status if any fail.
Empty entries and duplicate directories are rejected before starting work.

Transient API failures (including proxy 502s, disconnects, timeouts, and rate
limits) retry automatically at the current move. Retries use exponential backoff
capped at 60 seconds plus jitter, or the provider's longer `Retry-After` delay.
`ARENA_LLM_API_MAX_ATTEMPTS=0` is the default: keep retrying until recovery or
interruption. Set a positive value to stop after that many attempts. Saved game
state, failed-call costs, and agent time limits are retained; preparation retries
continue consuming the preparation clock.

Codex workspace HTTP 404 failures also restart the runtime and retry the same
move with retained state. These retries stop after five HTTP 404 failures per
move (or preparation turn), even when general retries are unlimited. A lower
`ARENA_LLM_API_MAX_ATTEMPTS` still applies. Other providers' HTTP 404 errors
remain terminal.

The workspace proxy rereads the host OAuth login on every request, so credentials
renewed by the host CLI take effect during a game. An expired or rejected login
that the provider will not refresh still needs human action: sign in with
`codex login` or Claude Code, then use `--resume`. Failure records include the HTTP
status when available and a `recovery_action` explaining why retries stopped.
Killed processes, host restarts, invalid settings, and incompatible or damaged
saved state also require explicit recovery; the process cannot restart itself
after it has exited.

New runs and game journals record `legality_enforcement_version: 1`. Runs from
the earlier GTP-only protocol cannot be resumed into this version; start a new
run instead. Recovery rebuilds board history by replaying accepted moves and
reports incompatible saved actions explicitly. Historical records are preserved;
the audit and affected-game inventory are in [superko audit](../data/audits/superko/superko_audit.md).

Run the referee regressions with `python3 -m unittest tests.test_game_engine`. For
the native KataGo comparison (using the installed CPU binary and b6c96 network),
run `RUN_KATAGO_TESTS=1 python3 -m unittest tests.test_game_engine.NativeKataGoTests`.

`--resume`, `--run-type`, and `--summary` select recovery, a profile, or reporting. To define a
new experiment, edit `CONFIG`; fixed engine details and derived state are kept
out of that user-facing configuration.

## Aggregate reports

Generate an aggregate report from `CONFIG.past_run_names` without playing any
new games:

```bash
python3 arena.py --summary
```

This creates or refreshes `log/summary/`, containing `report.txt`, run metadata
in `run.json`, and a portable `results.json` following the paper export's dataset
format. The JSON includes LLM comparisons, complete committed LLM game moves,
and KataGo ratings, timing, and cost. Timing comes from
`log/katago_selfplay_benchmark.json`; costs use the paper's $0.071/hour CPU rate.
The random anchor has no measured timing, so its timing and cost are null.
It includes the configured active player's past results, starts
no engines or API calls, and leaves the source run directories unchanged.
Each source's committed prefix is snapshotted before fitting ratings, so runs
can keep playing while the summary is generated. Later commits appear on the
next `--summary` refresh.
Summary directories are reports, not resumable game runs.
