#!/usr/bin/env python3
"""A minimal, resumable agent over the Codex OAuth Responses endpoint."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
import uuid


API_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_CONTEXT_WINDOW = 272_000
DEFAULT_EFFECTIVE_PERCENT = 95
MAX_TOOL_OUTPUT_BYTES = 1_000_000
TOOL = {
    "type": "function",
    "name": "bash_command",
    "description": "Run a Bash command in the workspace directory.",
    "parameters": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
        "additionalProperties": False,
    },
    "strict": True,
}


class AgentError(RuntimeError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def append_jsonl(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(value, separators=(",", ":")) + "\n")
        out.flush()
        os.fsync(out.fileno())


def codex_limits(model: str) -> tuple[int, int]:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    try:
        catalog = json.loads((codex_home / "models_cache.json").read_text())
        info = next(item for item in catalog["models"] if item["slug"] == model)
        window = int(info["context_window"])
        config = {}
        with contextlib.suppress(OSError, tomllib.TOMLDecodeError):
            with (codex_home / "config.toml").open("rb") as src:
                config = tomllib.load(src)
            if config.get("model_context_window") is not None:
                window = int(config["model_context_window"])
                if info.get("max_context_window") is not None:
                    window = min(window, int(info["max_context_window"]))
        percent = int(info.get("effective_context_window_percent", 100))
        token_limit = window * percent // 100
        configured_compact = info.get("auto_compact_token_limit")
        if config.get("model_auto_compact_token_limit") is not None:
            configured_compact = int(config["model_auto_compact_token_limit"])
        codex_default = window * 9 // 10
        compact = (
            min(int(configured_compact), codex_default)
            if configured_compact
            else codex_default
        )
        return token_limit, compact
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        StopIteration,
        json.JSONDecodeError,
    ):
        token_limit = DEFAULT_CONTEXT_WINDOW * DEFAULT_EFFECTIVE_PERCENT // 100
        compact = DEFAULT_CONTEXT_WINDOW * 9 // 10
        return token_limit, compact


def oauth() -> tuple[str, str]:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    path = codex_home / "auth.json"
    try:
        auth = json.loads(path.read_text(encoding="utf-8"))
        if auth.get("auth_mode") != "chatgpt":
            raise KeyError("auth_mode")
        token = auth["tokens"]["access_token"]
        account = auth["tokens"]["account_id"]
        if not token or not account:
            raise KeyError("empty token")
        return token, account
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AgentError(
            f"invalid Codex OAuth login at {path}; run `codex login`"
        ) from exc


def read_limited(path: Path) -> tuple[str, bool]:
    with path.open("rb") as src:
        data = src.read(MAX_TOOL_OUTPUT_BYTES + 1)
    truncated = len(data) > MAX_TOOL_OUTPUT_BYTES
    return data[:MAX_TOOL_OUTPUT_BYTES].decode("utf-8", errors="replace"), truncated


def run_tool_job(job_dir: Path) -> int:
    status_path = job_dir / "status.json"
    with (job_dir / "lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if status_path.exists():
            return 0
        request = json.loads((job_dir / "request.json").read_text(encoding="utf-8"))
        try:
            with (job_dir / "stdout").open("wb") as stdout, (
                job_dir / "stderr"
            ).open("wb") as stderr:
                result = subprocess.run(
                    ["/bin/bash", "-lc", request["command"]],
                    cwd=request["workspace"],
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                )
            status = {"finished_at": now(), "returncode": result.returncode}
        except BaseException as exc:
            status = {"finished_at": now(), "error": f"{type(exc).__name__}: {exc}"}
        write_json(status_path, status)
    return 0


class SimpleAgent:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir.resolve()
        self.meta = json.loads((self.session_dir / "session.json").read_text())
        self.workspace = Path(self.meta["workspace"])
        self.trajectory = self.session_dir / "trajectory.jsonl"
        self.jobs = self.session_dir / "jobs"
        self.lock = (self.session_dir / "lock").open("a+b")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AgentError(f"session is already running: {self.session_dir}") from exc
        self.context, self.tool_starts, self.tool_results = self._load()

    @classmethod
    def create(
        cls, root: Path, workspace: Path, model: str, effort: str
    ) -> "SimpleAgent":
        workspace = workspace.expanduser().resolve()
        if not workspace.is_dir():
            raise AgentError(f"workspace is not a directory: {workspace}")
        session_id = str(uuid.uuid4())
        session_dir = root.expanduser().resolve() / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "jobs").mkdir()
        token_limit, compact_threshold = codex_limits(model)
        meta = {
            "version": 1,
            "id": session_id,
            "created_at": now(),
            "workspace": str(workspace),
            "model": model,
            "effort": effort,
            "token_limit": token_limit,
            "compact_threshold": compact_threshold,
        }
        write_json(session_dir / "session.json", meta)
        append_jsonl(session_dir / "trajectory.jsonl", {"type": "session", **meta})
        return cls(session_dir)

    def _events(self) -> list[dict]:
        events = []
        with self.trajectory.open(encoding="utf-8") as src:
            for number, line in enumerate(src, 1):
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise AgentError(f"invalid trajectory line {number}") from exc
        return events

    def _load(self) -> tuple[list[dict], dict[str, dict], set[str]]:
        context: list[dict] = []
        starts: dict[str, dict] = {}
        results: set[str] = set()
        for event in self._events():
            kind = event.get("type")
            if kind == "user":
                context.append(event["item"])
            elif kind == "response":
                context.extend(event["response"].get("output", []))
            elif kind == "tool_started":
                starts[event["call_id"]] = event
            elif kind == "tool_result":
                results.add(event["call_id"])
                context.append(event["item"])
        positions = [
            index
            for index, item in enumerate(context)
            if item.get("type") == "compaction"
        ]
        if positions:
            context = context[positions[-1] :]
        return context, starts, results

    def record(self, kind: str, **values: object) -> None:
        append_jsonl(self.trajectory, {"type": kind, "at": now(), **values})

    def add_user(self, text: str) -> None:
        item = {"type": "message", "role": "user", "content": text}
        self.record("user", item=item)
        self.context.append(item)

    def _body(self) -> dict:
        return {
            "model": self.meta["model"],
            "store": False,
            "stream": True,
            "input": self.context,
            "tools": [TOOL],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "include": ["reasoning.encrypted_content"],
            "reasoning": {
                "effort": self.meta["effort"],
                "summary": "auto",
                "context": "all_turns",
            },
            "context_management": [
                {
                    "type": "compaction",
                    "compact_threshold": self.meta["compact_threshold"],
                }
            ],
            "prompt_cache_key": self.meta["id"],
        }

    def request(self) -> dict:
        request_id = str(uuid.uuid4())
        body = self._body()
        self.record("request_started", request_id=request_id)
        token, account = oauth()
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(body, separators=(",", ":")).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "ChatGPT-Account-Id": account,
                "originator": "codex_cli_rs",
                "User-Agent": "simple_agent/1",
                "OpenAI-Beta": "responses=experimental",
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
                "session_id": self.meta["id"],
                "x-client-request-id": request_id,
            },
            method="POST",
        )
        response = None
        output_items = {}
        streamed_text = False
        try:
            with urllib.request.urlopen(request, timeout=900) as stream:
                for raw in stream:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    event = json.loads(data)
                    if event.get("type") == "response.output_text.delta":
                        print(event.get("delta", ""), end="", flush=True)
                        streamed_text = True
                    if event.get("type") == "response.output_item.done":
                        index = event.get("output_index")
                        item = event.get("item")
                        if isinstance(index, int) and isinstance(item, dict):
                            output_items[index] = item
                    if event.get("type") in {
                        "response.completed",
                        "response.incomplete",
                        "response.failed",
                    }:
                        response = event.get("response")
        except KeyboardInterrupt:
            self.record("request_interrupted", request_id=request_id)
            raise
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            detail = ""
            if isinstance(exc, urllib.error.HTTPError):
                with contextlib.suppress(Exception):
                    detail = ": " + exc.read().decode("utf-8", errors="replace")[:2000]
            self.record("request_failed", request_id=request_id, error=f"{exc}{detail}")
            raise AgentError(f"Responses request failed: {exc}{detail}") from exc
        if not isinstance(response, dict):
            self.record(
                "request_failed", request_id=request_id, error="missing final response"
            )
            raise AgentError("Responses stream ended without a final response")
        if output_items:
            response["output"] = [output_items[index] for index in sorted(output_items)]
        self.record("response", request_id=request_id, response=response)
        self.context.extend(response.get("output", []))
        positions = [
            i for i, item in enumerate(self.context) if item.get("type") == "compaction"
        ]
        if positions:
            self.context = self.context[positions[-1] :]
        if streamed_text:
            print()
        else:
            text = response_text(response)
            if text:
                print(text)
        if response.get("status") != "completed":
            raise AgentError(f"response ended with status {response.get('status')}")
        return response

    def _pending_calls(self) -> list[dict]:
        return [
            item
            for item in self.context
            if item.get("type") == "function_call"
            and item.get("call_id") not in self.tool_results
        ]

    def _start_tool(self, call: dict, command: str) -> dict:
        digest = hashlib.sha256(call["call_id"].encode()).hexdigest()[:24]
        job_dir = self.jobs / digest
        job_dir.mkdir(exist_ok=True)
        write_json(
            job_dir / "request.json",
            {"workspace": str(self.workspace), "command": command},
        )
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--_tool-job",
                str(job_dir),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        event = {
            "call_id": call["call_id"],
            "command": command,
            "job_dir": str(job_dir),
            "pid": process.pid,
            "pid_start": self._pid_start(process.pid),
        }
        self.record("tool_started", **event)
        self.tool_starts[call["call_id"]] = event
        return event

    @staticmethod
    def _pid_start(pid: int) -> str | None:
        try:
            return Path(f"/proc/{pid}/stat").read_text().split()[21]
        except (OSError, IndexError):
            return None

    @classmethod
    def _pid_alive(cls, pid: int, start: str | None) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return start is None or cls._pid_start(pid) == start

    def _finish_tool(self, call: dict) -> None:
        if call.get("name") != "bash_command":
            raise AgentError(f"unknown tool: {call.get('name')}")
        try:
            command = json.loads(call["arguments"])["command"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AgentError("invalid bash_command arguments") from exc
        if not isinstance(command, str):
            raise AgentError("bash_command.command must be a string")
        print(f"$ {command}")
        started = self.tool_starts.get(call["call_id"]) or self._start_tool(
            call, command
        )
        job_dir = Path(started["job_dir"])
        status_path = job_dir / "status.json"
        try:
            while not status_path.exists() and self._pid_alive(
                started["pid"], started.get("pid_start")
            ):
                time.sleep(0.2)
        except KeyboardInterrupt:
            print(f"\ncommand continues in background; resume {self.session_dir}")
            raise
        if status_path.exists():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            stdout, stdout_cut = read_limited(job_dir / "stdout")
            stderr, stderr_cut = read_limited(job_dir / "stderr")
            parts = [f"exit_code: {status.get('returncode', 'unknown')}"]
            if status.get("error"):
                parts.append(f"error: {status['error']}")
            parts += [f"stdout:\n{stdout}", f"stderr:\n{stderr}"]
            if stdout_cut or stderr_cut:
                parts.append(f"output truncated; full output is in {job_dir}")
            output = "\n".join(parts)
        else:
            output = (
                "bash_command stopped before recording an exit status; it was not rerun"
            )
        item = {
            "type": "function_call_output",
            "call_id": call["call_id"],
            "output": output,
        }
        self.record("tool_result", call_id=call["call_id"], item=item)
        self.tool_results.add(call["call_id"])
        self.context.append(item)
        print(output)

    def continue_turn(self) -> None:
        while True:
            pending = self._pending_calls()
            if pending:
                for call in pending:
                    self._finish_tool(call)
                continue
            if not self.context or self.context[-1].get("type") not in {
                "message",
                "function_call_output",
                "compaction",
            }:
                return
            last = self.context[-1]
            if last.get("type") == "message" and last.get("role") != "user":
                return
            response = self.request()
            if not any(
                item.get("type") == "function_call"
                for item in response.get("output", [])
            ):
                return


def response_text(response: dict) -> str:
    chunks = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(content.get("text", ""))
    return "".join(chunks)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("workspace", nargs="?", type=Path)
    result.add_argument("--resume", type=Path, metavar="SESSION_DIR")
    result.add_argument(
        "--sessions-dir",
        type=Path,
        default=Path.home() / ".simple_agent" / "sessions",
    )
    result.add_argument("--model", default=DEFAULT_MODEL)
    result.add_argument(
        "--effort",
        choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
        default="high",
    )
    result.add_argument("--prompt")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.resume:
            if args.workspace:
                raise AgentError("workspace cannot be supplied with --resume")
            agent = SimpleAgent(args.resume)
        else:
            if not args.workspace:
                raise AgentError("workspace is required for a new session")
            agent = SimpleAgent.create(
                args.sessions_dir, args.workspace, args.model, args.effort
            )
        print(f"session: {agent.session_dir}")
        agent.continue_turn()
        if args.prompt:
            agent.add_user(args.prompt)
            agent.continue_turn()
        if not sys.stdin.isatty():
            return 0
        while True:
            try:
                text = input("you> ")
            except EOFError:
                print()
                return 0
            if not text.strip():
                continue
            agent.add_user(text)
            agent.continue_turn()
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except AgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--_tool-job":
        raise SystemExit(run_tool_job(Path(sys.argv[2])))
    raise SystemExit(main())
