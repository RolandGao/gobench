# GoBench
active leaderboard: https://rolandgao.com/blog/gobench/
<img width="1187" height="595" alt="Screenshot 2026-09-15 at 8 09 28 PM" src="https://github.com/user-attachments/assets/be43530a-3b15-47c8-8c26-0044f4c8c200" />

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

## License

[MIT License](LICENSE)
