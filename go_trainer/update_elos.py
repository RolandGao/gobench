"""Copy Elo ratings from an arena report.txt into networks.json.

Usage: python3 update_elos.py path/to/report.txt

Only rows whose player name exactly matches a network are used, i.e. the
1-visit ratings, not the -playoutsN or -temp-T variants.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

NETWORKS_PATH = Path(__file__).resolve().parent / "networks.json"
ROW = re.compile(r"^(\S+)\s+(-?\d+(?:\.\d+)?)\s+±")


def read_elos(report: Path) -> dict[str, float]:
    lines = report.read_text().splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("Player "))
    except StopIteration:
        sys.exit(f"no Elo table found in {report}")
    elos = {}
    for line in lines[start + 2:]:
        match = ROW.match(line)
        if not match:
            break
        elos[match.group(1)] = float(match.group(2))
    return elos


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    elos = read_elos(Path(sys.argv[1]))
    networks = json.loads(NETWORKS_PATH.read_text())
    missing = [n["name"] for n in networks if n["name"] not in elos]
    if missing:
        sys.exit(f"report has no rating for: {', '.join(missing)}")
    for network in networks:
        network["elo"] = elos[network["name"]]
    networks.sort(key=lambda n: -n["elo"])
    NETWORKS_PATH.write_text(json.dumps(networks, indent=1) + "\n")
    print(f"Updated {len(networks)} Elo ratings")


if __name__ == "__main__":
    main()
