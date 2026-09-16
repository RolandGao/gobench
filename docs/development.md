# Development

Install the checkout with `python3 -m pip install -e .` from the repository root.
`requirements.txt` is the single source of pinned Python dependencies;
`pyproject.toml` supplies package metadata and the `gobench` command.

Run the standard suite without live provider calls:

```bash
python3 -m unittest discover -s tests -t .
```

Historical legality tests use the frozen corpus in
[tests/fixtures/](../tests/fixtures/README.md), independently of current arena
logs and regenerated research audits.

Optional tests use local installed components:

```bash
RUN_KATAGO_TESTS=1 python3 -m unittest tests.test_game_engine.NativeKataGoTests
GOBENCH_RESOURCE_TESTS=1 python3 -m unittest tests.test_workspace_runtime
```

The second command exercises real disk images, cgroups, exclusive CPU leases,
and the installed Codex SDK with fake model responses. It needs the host
prerequisites and noninteractive sudo described in [setup](setup.md).

## Code boundaries

`arena.py` remains the arena entry point and contains its existing implementation.
Supporting runtime modules live in `gobench/`; research commands live in
`analysis/` and run as `python3 -m analysis.<module>`. Shared passing-audit
helpers belong in `analysis/passing_common.py`. Default asset and data paths
use `gobench/paths.py` so moving modules does not move the runtime's data roots.
`gobench/workspace_runtime.py` must also work as a directly executed root helper.

Keep generated engine transcripts and checkpoints under `untracked_log/`.
Keep compact published records under `log/` and selected research outputs under
`data/`. Do not rename archived run directories or rewrite recorded paths and
hashes merely to match the current source tree; these are provenance.

## Recovery and correctness invariants

These notes consolidate the still-relevant findings from the retired
`arena_review/` diagnostics. The maintained regression coverage is in
`tests/test_arena_review_fixes.py`, alongside the recovery, conversation,
pricing, game-engine, and workspace-runtime suites.

- Publish complete batch schedules before executing games. Publish native
  completion markers atomically and ignore unfinished retry attempts.
- Repair a torn final JSONL append, including split UTF-8, before replay or
  appending. Reject corruption in complete records.
- Replace result CSVs atomically. Historical loaders read only the prefix
  committed by run metadata.
- Preserve failed Codex request usage and typed HTTP failures. Price individual
  requests before aggregating totals; record proxy usage before forwarding a
  terminal response event.
- Preserve and journal empty multi-turn responses so retry and recovery follow
  the ordinary response path. Replay must not duplicate completed requests.
- Keep Elo fitting numerically stable, check optimizer convergence, and include
  both color contributions so self-play cancels correctly in the strength terms.
- Parse SGF nodes and escaped values, including comments and the first variation;
  do not extract moves with an unrestricted text pattern.
- Forward available SSE bytes promptly. Support standard and Codex-prefixed
  model catalog routes.
- Defer configuration until command-line selection or explicit arena use.
  Parse temperature modifiers before optional playout suffixes.
- Preserve lexical checkpoint paths through external-storage symlinks during
  recovery; do not replace saved locators with host-specific resolved paths.

The removed `test_arena_clean*` files compared against an absent `arena_clean.py`
snapshot. Configuration, manifests, usage accounting, execution, and resumption
remain covered by the supported tests. Historical diagnostic console dumps are
not included in the public release.
