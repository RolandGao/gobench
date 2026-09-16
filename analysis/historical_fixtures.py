"""Read archived audit inputs retained with the referee regression corpus."""

import json

from gobench.paths import ROOT


def load_historical_games():
    path = ROOT / "tests/fixtures/historical_games.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    games = {(game["run"], game["game"]): game for game in fixture["games"]}
    return fixture["runs"], games
