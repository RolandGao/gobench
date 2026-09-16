# Historical Go games

`historical_games.json` preserves the frozen superko regression corpus:
438 games from 24 retired runs, with 43,817 recorded actions. Of those games,
343 are clean and 95 have a known first illegal move.

Each game contains its original run and game identifiers, source line, complete
ordered moves, and `first_violation_move` (one-based, or `null` for a clean game).
The expected violations were copied from the published superko audit, not
recomputed by the referee being tested. Source hashes identify the original
audit, move logs, and run metadata.

The `runs` section retains board size, komi, rules, and original bot settings
for the historical passing-analysis tools. Their readers and native superko
verification fall back to this fixture when the retired logs are absent.

The original 24 directories have been removed from `log/`. Full run reports,
usage ledgers, and metadata are not included in the public release. Published audit paths still
describe those original sources; they are provenance, not current file paths.
Auditing `log/` afresh now covers the runs retained there.

Both the ordinary historical referee test and the opt-in native KataGo test
read this fixture directly. Keep its game set and expected outcomes fixed when
adding new runs or regenerating research reports.
