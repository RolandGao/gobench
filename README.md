# GoBench

GoBench runs reproducible 9×9 Go arenas between KataGo networks and LLMs, then
fits regularized Bradley–Terry Elo ratings with a jointly estimated Black-color
advantage. Compact run records are stored in `log/`; large engine transcripts
and recovery checkpoints are stored in the Git-ignored `untracked_log/` tree.

Python enforces Tromp–Taylor move legality and positional superko using complete
board history. The prompt's legal and ko/superko lists use the same referee as
move acceptance. KataGo executes accepted moves and scores games; its resulting
board is checked against the referee after every move. GTP `play` acceptance is
not used as a legality test.

## Quick start

Use Python 3.12 or newer, from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
python3 arena.py --help
```

Follow [setup and authentication](docs/setup.md) for provider credentials and
Codex's Linux resource requirements. KataGo binaries and pinned networks are
downloaded when needed. LLM profiles make provider requests.

Edit `CONFIG` near the top of [arena.py](arena.py), then run:

```bash
python3 arena.py
```

Historical runs (`_FINAL_RUNS`) are listed just above `CONFIG` in `arena.py`.
Shared player pools, report exclusions, and named profiles live in
[gobench/arena_config.py](gobench/arena_config.py).

The installed `gobench` command accepts the same arguments as `python3 arena.py`.
Use an editable installation: runtime assets and experiment records live in the
source checkout. See [running and recovery](docs/running.md) and
[methodology](docs/methodology.md) for details.

## Run profiles

Each profile selects an explicit `ArenaConfig` from `RUN_TYPES`, built by
[gobench/arena_config.py](gobench/arena_config.py) using `_FINAL_RUNS` from `arena.py`.
The `api_multi` profile is
populated from the provider registry in `arena.py`.
Codex suffixes set autonomous preparation to 0, 1, 2, 4, or 8 hours;
`codex-0h` has no training. Bare `-codex` and `-codex-continual` are invalid.

```bash
python3 arena.py --run-type katago_only
python3 arena.py --run-type katago_cheap_only
python3 arena.py --run-type katago_cheap_and_medium
python3 arena.py --run-type one_llm
python3 arena.py --run-type many_llm
python3 arena.py --run-type api_multi
python3 arena.py --run-type codex-0h
python3 arena.py --run-type codex-1h
python3 arena.py --run-type codex-2h
python3 arena.py --run-type codex-4h
python3 arena.py --run-type codex-8h
python3 arena.py --run-type 60_and_600_playouts_katago
python3 arena.py --run-type result_aggregation
```

Resume a run using its saved configuration, or aggregate configured history:

```bash
python3 arena.py --resume log/<run-name>
python3 arena.py --summary
```

Keep both `log/<run-name>/` and `untracked_log/<run-name>/` for recovery.
Summary generation makes no engine or provider calls.

## Repository layout

| Path | Contents |
| --- | --- |
| `arena.py` | Arena configuration, execution, recovery, matchmaking, and ratings |
| `gobench/` | Go referee, engine support, providers, conversations, and workspace runtime |
| `tests/` | Unit and opt-in local integration tests |
| `analysis/` | Research commands, audits, ablations, and plotting |
| `data/` | Published audit outputs, experiment tables, and paper dataset |
| `log/` | Compact historical arena records and aggregate reports |
| `paper/` | Manuscript, bibliography, and figures |
| `docs/` | Setup, operation, methodology, and development notes |
| `examples/` | Standalone agent example |

Start with the [analysis guide](analysis/README.md) to reproduce research outputs
and the [data index](data/README.md) to locate published artifacts. Large raw
journals, downloaded engines, credentials, and workspace images are ignored.

## Development

```bash
python3 -m unittest discover -s tests -t .
```

See [development notes](docs/development.md) for optional native KataGo and
Linux resource tests, and the recovery guarantees covered by regressions.

## License

This project is available under the [MIT License](LICENSE).
