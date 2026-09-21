# GoBench
paper: https://rolandgao.com/gobench.pdf

Active leaderboard: https://rolandgao.com/blog/gobench/
<img width="1211" height="616" alt="Screenshot 2026-09-20 at 5 14 20 PM" src="https://github.com/user-attachments/assets/91745e05-56b6-4a1b-a3b0-a44cb6724cd9" />



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
The summary is here:
https://github.com/RolandGao/gobench/blob/main/log/summary/report.txt

## Citation
```
@misc{gao2026gobench,
  title = {{GoBench}: Evaluating {LLMs} on the Game of {Go}},
  author = {Gao, Roland},
  year = {2026},
  url = {https://rolandgao.com/gobench.pdf}
}
```

## License

[MIT License](LICENSE)
