# Research commands

Install the repository with `python3 -m pip install -e .`. Run commands from the
repository root using `python3 -m analysis.<module>`; every command supports
`--help`. Default paths resolve to this checkout. Explicit relative paths are
relative to your working directory.

| Module | Purpose | Default data/output location |
| --- | --- | --- |
| `audit_superko` | Replay historical legality and optional native verification | `data/audits/superko/` |
| `audit_passing` | Judge passing losses with supplied KataGo models | `data/audits/passing/` |
| `audit_passing_visits` | Fresh-search budget sweeps at selected positions | `data/audits/passing/` |
| `audit_passing_networks` | Compare networks at passing-loss positions | `data/audits/passing/` |
| `audit_native_selfmatches` | Generate and audit native self-matches | `untracked_log/` |
| `benchmark_katago_selfplay` | Measure native self-play timing | `log/katago_selfplay_benchmark.json` |
| `katago_book_crawl`, `katago_book_render` | Convert an extracted KataGo 9x9 book into a Track 3 tutorial | `data/tutorials/` |
| `katago_book_student`, `katago_book_evaluate` | Build a Track 3 book tutorial from logged opponent moves and probes of the student's own moves, with KataGo losses for moves the book does not list | `data/tutorials/` |
| `matchmaking_ablation` | Replay matchmaking variants | CSV paths supplied through CLI |
| `color_advantage_model` | Fit and compare color-advantage models | `data/color_advantage/` |
| `color_advantage_all_models_player_split_experiment` | Compare models on player splits | Output path supplied through CLI |
| `plot_black_advantage_top_models` | Plot fitted Black advantage | `paper/` |
| `extract_paper_results` | Export a portable paper dataset | `data/paper_results.json` |
| `plot_elo_comparison` | Plot Elo and efficiency comparisons | `paper/` |
| `plot_report_llm_costs` | Plot LLM cost/rating comparisons | `paper/` |
| `plot_summary_details` | Plot Astra/Sol learning-time results and the color function | `data/paper_learning_results.json`, `log/summary/results.json` → `paper/` |
| `analyze_simplebench_correlation` | Compare GoBench with SimpleBench results | Console |
| `rollout_book_search` | Search for book moves that make a student-strength KataGo bot beat a stronger one | State directory supplied through CLI (`untracked_log/rollout_book/`) |
| `rollout_book_render` | Rank the search's fixes and write a tutorial file under a token cap, or a Track 3.5 book under a move limit | `data/tutorials/` |
| `rollout_book_eval` | Play the proxy with and without tutorial books in fresh games | Console, optional JSON lines |
| `rollout_book_teachers` | Compare the networks that proposed the book moves | Console |
| `book_to_tutorial` | Write a Track 3.5 opening book as a tutorial file for a language model | Output path supplied through CLI |

Inspect a command before running an experiment:

```bash
python3 -m analysis.audit_superko --help
python3 -m analysis.audit_passing_networks --all-b6c96 --dry-run
python3 -m analysis.matchmaking_ablation --help
python3 -m analysis.extract_paper_results --help
```

Native studies need installed KataGo assets and may run substantial searches.
The SimpleBench comparison reads external results. Use `--output` where
available to keep a fresh experiment separate
from a published artifact. The network passing audit requires `--resume` to
continue an existing output.

`passing_common.py` contains shared area scoring, historical case selection,
full-history replay, fresh-search probing, and atomic JSON checkpoint writing.
The distinct studies retain their own command-line interfaces and reports.

`historical_fixtures.py` reads the retired games and bot settings in
[tests/fixtures/](../tests/fixtures/README.md) for historical passing sweeps
and native verification of the published superko audit. Fresh audits of `log/`
cover only the run directories still present there.
