"""9x9 Go trainer: play a KataGo network while a teacher network grades moves.

Run `python3 trainer.py` and a browser tab opens on http://127.0.0.1:8765.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import engines
import install_katago
from rules import Game, IllegalMove, other, result_text

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
SETTINGS_PATH = APP_DIR / "settings.json"
TEACHER = "kata1-b18c384nbt-s9761732864-d4253420187"
DEFAULT_OPPONENT = "kata1-b6c96-s4136960-d1510003"
DEFAULT_KOMI = 7.5


class Trainer:
    def __init__(self, teacher: engines.Analyzer) -> None:
        self.teacher = teacher
        self.networks = {n["name"]: n for n in engines.load_networks()}
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.version = 0
        self.generation = 0
        self.settings = {
            "opponent": DEFAULT_OPPONENT,
            "color": "B",
            "komi": DEFAULT_KOMI,
        }
        try:
            self.settings.update(json.loads(SETTINGS_PATH.read_text()))
        except (OSError, ValueError):
            pass
        if self.settings["opponent"] not in self.networks:
            self.settings["opponent"] = DEFAULT_OPPONENT
        self.game = Game(komi=float(self.settings["komi"]))
        self.human = "B"
        self.opponent = self.settings["opponent"]
        self.thinking_for: int | None = None
        self.status = ""
        self.error = ""
        self.downloads: dict[str, dict] = {}
        self.cache: dict[tuple, dict] = {}
        self.bot: engines.GtpBot | None = None
        self.bot_lock = threading.Lock()
        threading.Thread(target=self._analysis_loop, daemon=True).start()

    # -- state ---------------------------------------------------------------

    def _bump(self) -> None:
        self.version += 1
        self.changed.notify_all()

    def state(self) -> dict:
        game = self.game
        analyses = [
            self.cache.get((game.komi, tuple(game.moves[:ply])))
            for ply in range(len(game.moves) + 1)
        ]
        over = game.over
        network = self.networks[self.opponent]
        return {
            "version": self.version,
            "size": game.size,
            "komi": game.komi,
            "human": self.human,
            "to_move": game.to_move,
            "board": list(game.board),
            "moves": game.moves,
            "over": over,
            "area_score": game.score(),
            "result": result_text(game.score()) if over else None,
            "captures": game.captures(),
            "legal": game.legal_moves() if game.to_move == self.human else [],
            "thinking": self.thinking_for == self.generation,
            "opponent": {"name": self.opponent, "elo": network["elo"]},
            "teacher": TEACHER,
            "status": self.status,
            "error": self.error,
            "downloads": self.downloads,
            "analyses": analyses,
            "settings": self.settings,
        }

    def wait_state(self, since: int, timeout: float = 25) -> dict:
        with self.lock:
            self.changed.wait_for(lambda: self.version != since, timeout)
            return self.state()

    def network_list(self) -> list[dict]:
        return [
            {
                "name": n["name"],
                "elo": n["elo"],
                "size": n["size"],
                "downloaded": engines.is_downloaded(n),
            }
            for n in self.networks.values()
        ]

    # -- actions -------------------------------------------------------------

    def _save_settings(self) -> None:
        try:
            SETTINGS_PATH.write_text(json.dumps(self.settings, indent=1))
        except OSError:
            pass

    @staticmethod
    def _check_komi(komi: float) -> None:
        if not -150 <= komi <= 150 or komi * 2 != int(komi * 2):
            raise ValueError("komi must be a multiple of 0.5 between -150 and 150")

    def new_game(self, opponent: str, color: str, komi: float) -> None:
        if opponent not in self.networks:
            raise ValueError(f"unknown network {opponent}")
        if color not in ("B", "W", "random"):
            raise ValueError("color must be B, W or random")
        self._check_komi(komi)
        with self.lock:
            self.settings = {"opponent": opponent, "color": color, "komi": komi}
            self._save_settings()
            self.generation += 1
            self.game = Game(komi=komi)
            self.human = random.choice("BW") if color == "random" else color
            self.opponent = opponent
            self.error = ""
            self.status = ""
            network = self.networks[opponent]
            if engines.is_downloaded(network):
                self._start_bot_turn()
            else:
                self._start_download(network)
            self._bump()

    def play(self, move: str) -> None:
        with self.lock:
            if self.thinking_for == self.generation:
                raise IllegalMove("wait for the opponent to move")
            if self.game.to_move != self.human:
                raise IllegalMove("it is not your turn")
            if self.status.startswith("Downloading"):
                raise IllegalMove("wait for the opponent network to download")
            self.game.play(move)
            self.error = ""
            self.generation += 1
            self._start_bot_turn()
            self._bump()

    def set_komi(self, komi: float) -> None:
        """Change komi mid-game; the teacher and opponent both use it."""
        self._check_komi(komi)
        with self.lock:
            if komi == self.game.komi:
                return
            self.settings["komi"] = komi
            self._save_settings()
            self.game.komi = komi
            # Restart a pending opponent move so it is chosen with the new komi.
            self.generation += 1
            self._start_bot_turn()
            self._bump()

    def undo(self) -> None:
        """Take back your last move (and the opponent's reply to it)."""
        with self.lock:
            if not any(color == self.human for color, _ in self.game.moves):
                return
            self.generation += 1
            while self.game.moves:
                color, _ = self.game.moves[-1]
                self.game.undo()
                if color == self.human:
                    break
            self.error = ""
            self._bump()

    # -- opponent ------------------------------------------------------------

    def _start_bot_turn(self) -> None:
        if self.game.over or self.game.to_move == self.human:
            return
        self.thinking_for = self.generation
        threading.Thread(
            target=self._bot_turn,
            args=(self.generation, list(self.game.moves), self.game.komi, self.opponent),
            daemon=True,
        ).start()

    def _bot_turn(self, generation: int, moves: list, komi: float, opponent: str) -> None:
        color = "B" if len(moves) % 2 == 0 else "W"
        try:
            with self.bot_lock:
                path = engines.network_path(self.networks[opponent])
                if self.bot is None or self.bot.model != path:
                    if self.bot:
                        self.bot.close()
                        self.bot = None
                    with self.lock:
                        self.status = "Loading opponent network..."
                        self._bump()
                    self.bot = engines.GtpBot(path)
                    with self.lock:
                        self.status = ""
                        self._bump()
                bot = self.bot
            move = bot.genmove(moves, komi, color)
        except engines.EngineError as exc:
            with self.lock:
                if self.thinking_for == generation:
                    self.thinking_for = None
                self.status = ""
                self.error = str(exc)
                self._bump()
            return
        with self.lock:
            if generation == self.generation and self.game.moves == moves:
                try:
                    self.game.play(move)
                except IllegalMove as exc:
                    self.error = f"opponent played an illegal move {move}: {exc}"
            if self.thinking_for == generation:
                self.thinking_for = None
            self._bump()

    def _start_download(self, network: dict) -> None:
        name = network["name"]
        self.status = f"Downloading {name}..."
        if name in self.downloads and not self.downloads[name].get("error"):
            return  # Already downloading.
        self.downloads[name] = {"done": 0, "total": network["size"], "error": ""}

        def progress(done: int, total: int) -> None:
            with self.lock:
                entry = self.downloads[name]
                if done * 100 // total != entry["done"] * 100 // total:
                    entry["done"] = done
                    self._bump()

        def run() -> None:
            try:
                engines.download_network(network, progress)
            except engines.EngineError as exc:
                with self.lock:
                    self.downloads[name]["error"] = str(exc)
                    self.status = ""
                    self.error = str(exc)
                    self._bump()
                return
            with self.lock:
                del self.downloads[name]
                if self.opponent == name:
                    self.status = ""
                    self._start_bot_turn()
                self._bump()

        threading.Thread(target=run, daemon=True).start()

    # -- teacher -------------------------------------------------------------

    def _next_job(self) -> tuple | None:
        """The current position first, then earlier ones (for move grades)."""
        moves = self.game.moves
        for ply in range(len(moves), -1, -1):
            key = (self.game.komi, tuple(moves[:ply]))
            if key not in self.cache:
                return key
        return None

    def _analysis_loop(self) -> None:
        while True:
            with self.lock:
                job = self.changed.wait_for(self._next_job)
            komi, moves = job
            try:
                result = self._analyze(list(moves), komi)
            except engines.EngineError as exc:
                result = {"error": str(exc)}
            with self.lock:
                self.cache[job] = result
                self._bump()

    def _analyze(self, moves: list, komi: float) -> dict:
        game = Game(komi=komi)
        for _, move in moves:
            game.play(move)
        root = self.teacher.evaluate([moves], komi, policy=True)[0]
        if root is None:
            return {"error": "the teacher could not evaluate this position"}
        player = game.to_move
        sign = 1 if player == "B" else -1
        candidates = game.legal_moves()
        children = self.teacher.evaluate(
            [moves + [(player, move)] for move in candidates], komi
        )
        policy = root.get("policy") or []
        size = game.size
        graded = {}
        for move, child in zip(candidates, children):
            if child is None:
                continue
            index = size * size if move == "pass" else game.point(move)
            graded[move] = {
                "score": sign * child["scoreLead"],
                "win": child["winrate"] if player == "B" else 1 - child["winrate"],
                "policy": max(policy[index], 0) if index < len(policy) else 0,
            }
        # Losses are measured against the teacher's value of the position
        # itself. Single-visit child values are noisy, so comparing against
        # the luckiest child would penalise perfectly good moves.
        root_score = sign * root["scoreLead"]
        root_win = root["winrate"] if player == "B" else 1 - root["winrate"]
        for entry in graded.values():
            entry["loss"] = round(max(0.0, root_score - entry["score"]), 2)
            entry["win_loss"] = round(max(0.0, root_win - entry["win"]), 4)
            entry["score"] = round(entry["score"], 2)
            entry["win"] = round(entry["win"], 4)
            entry["policy"] = round(entry["policy"], 4)
        best = max(graded, key=lambda m: (graded[m]["score"], graded[m]["policy"]), default=None)
        top_policy = max(graded, key=lambda m: graded[m]["policy"], default=None)
        return {
            "to_move": player,
            "winrate": round(root["winrate"], 4),
            "score": round(root["scoreLead"], 2),
            "best": best,
            "top_policy": top_policy,
            "moves": graded,
        }


def make_handler(trainer: Trainer) -> type[BaseHTTPRequestHandler]:
    content_types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status: int = 200) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/api/state":
                since = int(parse_qs(url.query).get("since", ["-1"])[0])
                self._json(trainer.wait_state(since))
            elif url.path == "/api/networks":
                self._json(trainer.network_list())
            else:
                name = "index.html" if url.path == "/" else url.path.lstrip("/")
                path = (STATIC_DIR / name).resolve()
                if path.parent != STATIC_DIR or not path.is_file():
                    self._send(404, b"not found", "text/plain")
                    return
                self._send(200, path.read_bytes(), content_types.get(path.suffix, "text/plain"))

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/new":
                    trainer.new_game(
                        str(body["opponent"]), str(body["color"]), float(body["komi"])
                    )
                elif self.path == "/api/play":
                    trainer.play(str(body["move"]))
                elif self.path == "/api/komi":
                    trainer.set_komi(float(body["komi"]))
                elif self.path == "/api/undo":
                    trainer.undo()
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                    return
            except (IllegalMove, ValueError, KeyError, TypeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            with trainer.lock:
                self._json(trainer.state())

    return Handler


def _print_progress(label: str):
    shown = [-1]

    def progress(done: int, total: int) -> None:
        percent = done * 100 // total
        if percent != shown[0]:
            shown[0] = percent
            print(f"\r{label}: {percent}% of {total / 1e6:.0f} MB", end="", flush=True)
            if done == total:
                print()

    return progress


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not install_katago.katago_works():
        print("First run: installing KataGo into ./engine (one-time, ~370 MB download).")
        try:
            install_katago.install()
        except install_katago.InstallError as exc:
            sys.exit(f"KataGo install failed: {exc}")
    teacher_network = {n["name"]: n for n in engines.load_networks()}[TEACHER]
    if not engines.is_downloaded(teacher_network):
        engines.download_network(teacher_network, _print_progress("Teacher network"))

    print("Starting the teacher...")
    teacher = engines.Analyzer(engines.network_path(teacher_network))
    teacher.evaluate([[]], DEFAULT_KOMI)  # Fail fast and warm up the GPU.
    trainer = Trainer(teacher)
    trainer.new_game(
        trainer.settings["opponent"],
        trainer.settings["color"],
        float(trainer.settings["komi"]),
    )

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(trainer))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Go trainer running at {url}  (Ctrl+C to quit)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        teacher.close()
        if trainer.bot:
            trainer.bot.close()


if __name__ == "__main__":
    main()
