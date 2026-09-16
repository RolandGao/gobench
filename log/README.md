# Arena logs

This Git-tracked directory contains compact, durable arena records. Each run
directory may contain:

- `run.json`: configuration, provenance, final structured ratings, and summary;
- `results.csv`: one canonical row per committed game;
- `report.md`: the human-readable ratings and matchup report;
- `prompt.txt`: one exact evaluation-prompt example for LLM runs;
- `llm_calls.jsonl`: compact per-call usage, cost, output, and prompt hashes.
- `llm_games.jsonl`: complete ordered moves for both players in every LLM game.

Tracked JSON records enforce a publication boundary: filesystem paths outside
the repository use `<external-path>`, credential-like fields and raw HTTP
headers/bodies are excluded, provider response IDs are excluded, exception
details are reduced to their class, and arbitrary LLM prose is represented as
`<invalid-output>`. Valid Go moves remain verbatim. Raw ignored journals apply
the credential/header/response-ID exclusions as well.

KataGo-vs-KataGo moves, SGFs, mid-game recovery journals, generated engine
configurations, GTP transcripts, stderr, and progress displays live in the
corresponding `untracked_log/<run-id>/` directory. That directory is
deliberately ignored by Git, but remains visible and persistent inside the
working directory.

Historical arena records were imported into this layout and normalized to the
current privacy schema. Their `run.json` migration entries retain provenance.
Retained run records live under `log/` and `untracked_log/`. The 24 retired
runs used by the historical superko tests were extracted to
[tests/fixtures/](../tests/fixtures/README.md); their full original records
are not included in the public release.
