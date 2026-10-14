"""Backfill Codex learner usage lost before commit 6797ec1.

The ChatGPT Codex backend began streaming responses without a Content-Type,
so the workspace proxy wrote no ``openai-proxy.usage.jsonl`` and tutorial
checkpoints reported ``training_cost_usd: 0``. The proxy exchange log still
holds every response body, so this rebuilds the usage log from it and
recomputes the manifest's training cost fields (and ``learning_cost_usd`` for
tutorial checkpoints), then refreshes the copy in ``log/<run>/run.json``.

It also strips the per-item ``attribution`` maps that Codex responses add to
usage (dropped by the proxy since a later commit), which otherwise bloat each
manifest's ``training_usage.request_usages`` to megabytes.

Usage: python analysis/backfill_codex_learner_usage.py [--write] RUN [RUN...]
Without --write it only prints what would change.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import arena  # noqa: E402

API_NAME = arena._CodexGameClient.api_name
PROXY_LOG = arena._CodexGameClient.proxy_log_name
CHECKPOINT_KINDS = {"tutorial-checkpoints": "tutorial_checkpoints"}


def completed_usage(entry):
    body = entry.get("response_body")
    text = body if isinstance(body, str) else (body or {}).get("raw", "")
    for line in reversed(text.splitlines()):
        if not line.startswith("data:"):
            continue
        try:
            value = json.loads(line[5:])
        except ValueError:
            continue
        response = value.get("response") if isinstance(value, dict) else None
        if isinstance(response, dict) and isinstance(response.get("usage"), dict):
            return response
    return None


def without_attribution(usage):
    return {name: value for name, value in usage.items() if name != "attribution"}


def strip_attribution(checkpoint_root, manifest, write):
    """Drop attribution maps from an already-recorded checkpoint, if any."""
    requests = manifest.get("training_usage", {}).get("request_usages", [])
    if not any("attribution" in request for request in requests):
        print(f"{checkpoint_root.name}: usage already recorded; skipped")
        return None
    updated = dict(manifest)
    updated["training_usage"] = arena._sum_response_usages(
        [without_attribution(request) for request in requests]
    )
    print(f"{checkpoint_root.name}: stripped attribution from {len(requests)} request usages")
    if write:
        usage_path = checkpoint_root / "preparation" / f"{PROXY_LOG}.usage.jsonl"
        if usage_path.exists():
            entries = arena._read_jsonl_objects(usage_path, "training usage")
            usage_path.write_text("".join(
                json.dumps(entry | {"usage": without_attribution(entry["usage"])},
                           separators=(",", ":")) + "\n"
                for entry in entries
            ))
    return updated


def rebuilt_usages(preparation, model):
    usages = []
    for entry in arena._read_jsonl_objects(preparation / f"{PROXY_LOG}.jsonl", "exchanges"):
        if entry.get("method") != "POST":
            continue
        response = completed_usage(entry)
        if response is not None:
            usages.append({
                "exchange_id": entry["exchange_id"],
                "started_at": entry["started_at"],
                "model": response.get("model") or model,
                "usage": without_attribution(response["usage"]),
            })
    return usages


def backfill(checkpoint_root, write):
    manifest_path = checkpoint_root / "checkpoint" / "manifest.json"
    preparation = checkpoint_root / "preparation"
    usage_path = preparation / f"{PROXY_LOG}.usage.jsonl"
    manifest = json.loads(manifest_path.read_text())
    if usage_path.exists() or manifest.get("training_model_requests"):
        updated = strip_attribution(checkpoint_root, manifest, write)
        if updated is not None and write:
            write_manifest(manifest_path, updated)
        return updated
    model = manifest["specification"]["model"]
    usages = rebuilt_usages(preparation, model)
    accounted = {entry["exchange_id"] for entry in usages}
    exchanges = arena._read_jsonl_objects(preparation / f"{PROXY_LOG}.jsonl", "exchanges")
    cost = sum(arena._llm_call_cost(entry["usage"], API_NAME, model,
                                    started_at=entry["started_at"]) for entry in usages)
    updated = dict(manifest)
    updated.update(
        training_model_requests=len(usages),
        training_cost_usd=cost,
        training_requests_without_reported_usage=sum(
            entry.get("method") == "POST" and entry.get("exchange_id") not in accounted
            for entry in exchanges
        ),
        training_usage=arena._sum_response_usages([entry["usage"] for entry in usages]),
        training_usage_backfilled_from_proxy_log=True,
    )
    if "student_cost_usd" in manifest:
        updated["learning_cost_usd"] = cost + manifest["student_cost_usd"]
    print(f"{checkpoint_root.name}: {len(usages)} learner requests, "
          f"training_cost_usd {manifest.get('training_cost_usd')} -> {cost:.6f}, "
          f"learning_cost_usd {manifest.get('learning_cost_usd')} -> "
          f"{updated.get('learning_cost_usd')}")
    if write:
        for entry in usages:
            arena._append_jsonl(usage_path, entry)
        write_manifest(manifest_path, updated)
    return updated


def write_manifest(path, value):
    mode = path.stat().st_mode & 0o777
    arena._workspace_atomic_json(path, value)
    path.chmod(mode)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", metavar="RUN")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    for run in args.runs:
        run_json = ROOT / "log" / run / "run.json"
        meta = json.loads(run_json.read_text()) if run_json.exists() else None
        changed = False
        for dirname, meta_key in CHECKPOINT_KINDS.items():
            for root in sorted((ROOT / "untracked_log" / run / dirname).glob("*")):
                if not (root / "checkpoint" / "manifest.json").exists():
                    continue
                updated = backfill(root, args.write)
                if updated is not None and meta is not None and root.name in meta.get(meta_key, {}):
                    meta[meta_key][root.name] = updated
                    changed = True
        if changed and args.write:
            arena._write_json(run_json, meta)
            print(f"{run}: updated {run_json.relative_to(ROOT)}")
    if not args.write:
        print("dry run; pass --write to apply")


if __name__ == "__main__":
    main()
