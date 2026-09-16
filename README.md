# GoBench

[MIT License](LICENSE)

## Setup

Use Python 3.12 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Run

Edit the `CONFIG = ArenaConfig(...)` block near the top of [arena.py](arena.py), then run:

```bash
python arena.py
```

## Summary

Generate a summary of the configured historical runs:

```bash
python arena.py --summary
```
