# Published research data

| Path | Contents |
| --- | --- |
| `audits/passing/` | Passing-loss judgments, budget/network sweeps, tables, and SGF positions |
| `audits/superko/` | Historical legality audit, prompt evidence, and violation inventory |
| `audits/native_selfmatches/` | Native self-match passing reports and case tables |
| `audits/reasoning_retention/` | Provider reasoning-retention audit |
| `audits/codex_internet/` | Reverse-proxy audit of Codex internet-access attempts, coverage, and false-positive classifications |
| `ablations/` | Matchmaking ablation tables |
| `color_advantage/` | Color-advantage experiment tables |
| `paper_results.json` | Portable paper dataset snapshot |
| `paper_learning_results.json` | Frozen Section 3.2 Astra/Sol Codex results, including the preliminary 10-game Sol 4h evaluation, source hashes, and termination counts |
| `katago_network_speed_elo.txt` | Recorded network speed and Elo comparison |

Compact arena records remain in [log/](../log/). The
[analysis commands](../analysis/README.md) read these records and generate
research outputs. Manuscript sources and figures are in [paper/](../paper/).

The 24 retired runs behind the historical superko audit are preserved as a
[test fixture](../tests/fixtures/README.md), including moves, expected first
violations, and bot settings. Historical passing sweeps and native superko
verification can read that fixture after removal of the original log directories.

Published measurement values and paper files are preserved. Personal absolute
paths into the original checkout were normalized to repository-relative paths;
references to changed source-file hashes were updated. Other embedded paths,
source hashes, commands, dates, and old player names describe
the original experiments. A historical path such as `passing_audit.json` now
refers to `data/audits/passing/passing_audit.json`; `paper_writing/` is now
`paper/`. These strings are provenance, not current invocation instructions.
Raw recovery logs and workspace images are local, ignored data and are not
included in these published snapshots. Fresh exports may differ if source
records or analysis code have changed.
