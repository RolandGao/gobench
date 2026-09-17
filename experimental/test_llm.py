"""Offline contract tests; optional real-provider smoke tests require explicit opt-in."""
import contextlib
import copy
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

import httpx

from experimental import llm


def openai_response(text="answer", *, identity="resp-1", usage=True, status="completed"):
    result = {
        "id": identity, "status": status,
        "output": [
            {"type": "reasoning", "id": "rs-1", "summary": [], "encrypted_content": "opaque-state"},
            {"type": "message", "role": "assistant", "id": "msg-1", "status": "completed",
             "content": [{"type": "output_text", "text": text, "annotations": []}]},
        ],
    }
    if usage:
        result["usage"] = {"input_tokens": 10, "output_tokens": 5,
                           "output_tokens_details": {"reasoning_tokens": 3}}
    return result


def anthropic_response(text="answer", reason="end_turn"):
    return {"id": "msg-1", "type": "message", "role": "assistant", "model": "claude-opus-5",
            "content": [{"type": "thinking", "thinking": "reason", "signature": "signed-state"},
                        {"type": "text", "text": text}], "stop_reason": reason,
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 2}}


def sse(events):
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events))


def crash_worker(path, stage):
    """Real process death releases the lock without running cleanup code."""
    os.environ["OPENAI_API_KEY"] = "fake-api-key"
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=openai_response("survived")))
    if stage == "prepared":
        llm.LLM._perform = lambda *args: os._exit(41)
    elif stage == "dispatched":
        transport = httpx.MockTransport(lambda _: os._exit(42))
    elif stage == "received":
        llm.LLM._complete = lambda *args: os._exit(43)
    elif stage == "committed":
        complete = llm.LLM._complete
        def complete_and_crash(*args):
            complete(*args)
            os._exit(46)
        llm.LLM._complete = complete_and_crash
    elif stage == "initialized":
        def connect(*args, **kwargs):
            os._exit(44)
        sqlite3.connect = connect
    with llm.LLM(name="gpt-5.6-sol", auth="api_key", mode="multi_turn",
                 session_dir=path, transport=transport) as model:
        model.input("question", turn_id="durable-id")


def probe_lock(path, result):
    try:
        with llm.LLM(session_dir=path):
            result.put("opened")
    except llm.SessionBusy:
        result.put("busy")


def refresh_worker(path, attempts, crash, result):
    def send(request):
        with open(attempts, "a") as out:
            out.write("refresh\n")
        if crash:
            os._exit(45)
        return httpx.Response(200, json={"access_token": "process-token", "refresh_token": "rotated",
                                        "expires_in": 3600})
    credentials = llm._Credentials({"auth": "oauth", "provider": "openai", "credential_file": path},
                                   httpx.MockTransport(send))
    try:
        token, _ = credentials.get()
        result.put(token == "process-token")
    except llm.AuthenticationError:
        result.put(False)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.path = self.root / "session"
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "fake-api-key", "ANTHROPIC_API_KEY": "fake-anthropic-key",
        }))
        self.requests = []
        self.reply = lambda request: httpx.Response(200, json=openai_response())
        def handler(request):
            self.requests.append(request)
            return self.reply(request)
        self.transport = httpx.MockTransport(handler)

    def model(self, **kwargs):
        defaults = dict(name="gpt-5.6-sol", auth="api_key", mode="multi_turn",
                        session_dir=self.path, transport=self.transport)
        defaults.update(kwargs)
        model = llm.LLM(**defaults)
        self.stack.callback(model.close)
        return model

    def reopen(self, **kwargs):
        model = llm.LLM(session_dir=self.path, transport=self.transport, **kwargs)
        self.stack.callback(model.close)
        return model

    def body(self, index=-1):
        return json.loads(self.requests[index].content)

    def assert_no_secrets(self, *secrets):
        for path in self.path.iterdir():
            data = path.read_bytes()
            for secret in secrets:
                self.assertNotIn(secret.encode(), data)

    def run_in_thread(self, model, prompt="hello", turn_id="one"):
        results = []
        def run():
            try:
                results.append(model.input(prompt, turn_id=turn_id))
            except Exception as exc:
                results.append(exc)
        thread = threading.Thread(target=run)
        thread.start()
        self.stack.callback(lambda: thread.join(3))
        return thread, results

    def blocking_reply(self):
        started, release = threading.Event(), threading.Event()
        self.stack.callback(release.set)
        def reply(request):
            started.set()
            if not release.wait(5):
                raise TimeoutError
            return httpx.Response(200, json=openai_response("late"))
        self.reply = reply
        return started, release

    @staticmethod
    def wait_for(predicate):
        deadline = time.monotonic() + 3
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError("condition did not become true")
            time.sleep(0.01)


class SessionTests(Fixture):
    def test_config_is_a_snapshot(self):
        model = self.model()
        model.config["model"] = "another-model"
        model.config["auth"] = "oauth"
        model.input("hello")
        self.assertEqual(self.body()["model"], "gpt-5.6-sol")
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer fake-api-key")

    def test_single_turn_does_not_replay_history(self):
        model = self.model(mode="single_turn")
        first = model.input("same")
        second = model.input("same")
        self.assertNotEqual(first.turn_id, second.turn_id)
        self.assertEqual(self.body()["input"], [{"role": "user", "content": "same"}])
        self.assertEqual(len(model.list_turns()), 2)
        self.assertNotIn("tools", self.body())
        self.assertEqual(self.requests[0].headers["authorization"], "Bearer fake-api-key")
        self.assert_no_secrets("fake-api-key")

    def test_multiturn_replays_native_reasoning_after_reopen(self):
        model = self.model(reasoning_effort="high")
        model.input("first", turn_id="one")
        model.close()
        resumed = self.reopen()
        resumed.input("second", turn_id="two")
        body = self.body()
        self.assertEqual(body["input"], [{"role": "user", "content": "first"}] +
                         openai_response()["output"] + [{"role": "user", "content": "second"}])
        self.assertEqual(body["reasoning"], {"effort": "high", "context": "all_turns"})
        self.assertEqual(body["include"], ["reasoning.encrypted_content"])
        self.assertEqual(body["truncation"], "disabled")
        self.assertFalse(body["store"])

    def test_duplicate_id_returns_committed_response_without_credentials(self):
        model = self.model()
        expected = model.input("hello", turn_id="one")
        model.close()
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            model = self.reopen()
            self.assertEqual(model.input("hello", turn_id="one"), expected)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(model.get_turn("one").response, expected)
        with self.assertRaises(llm.TurnConflict):
            model.input("changed", turn_id="one")

    def test_defaults_and_capability_validation_before_creation(self):
        cases = [dict(name="unknown"), dict(mode="codex"), dict(auth="automatic"),
                 dict(reasoning_effort="ultra"), dict(timeout=0), dict(timeout=float("nan")),
                 dict(max_attempts=True), dict(max_output_tokens=True),
                 dict(max_output_tokens=999999), dict(credential_file="not-for-api-key"),
                 dict(auth="oauth", max_output_tokens=50), dict(api_key_env="not a name")]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(llm.ConfigurationError):
                self.model(**case)
            self.assertFalse(self.path.exists())
        with self.assertRaises(llm.ConfigurationError):
            llm.LLM(session_dir=self.path)

    def test_ambiguous_registry_is_rejected(self):
        with mock.patch.object(llm, "MODEL_REGISTRY", llm.MODEL_REGISTRY + (llm.MODEL_REGISTRY[0],)):
            with self.assertRaises(llm.ConfigurationError):
                llm.resolve_model("gpt-5.4")

    def test_resume_conflicts_and_alias_resolution(self):
        model = self.model(name="gpt5.6-sol", reasoning_effort="high")
        model.close()
        for changed in (dict(name="gpt-5.5"), dict(auth="oauth"), dict(mode="single_turn"),
                        dict(reasoning_effort=None), dict(max_output_tokens=100), dict(timeout=1)):
            with self.subTest(changed=changed), self.assertRaises(llm.ConfigurationError):
                self.reopen(**changed)
        self.assertEqual(self.reopen(name="gpt-5.6-sol").config["reasoning_effort"], "high")

    def test_exclusive_lock_across_instances_and_processes(self):
        first = self.model()
        with self.assertRaises(llm.SessionBusy):
            self.reopen()
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        child = ctx.Process(target=probe_lock, args=(str(self.path), queue))
        child.start()
        child.join(10)
        self.assertFalse(child.is_alive())
        self.assertEqual(child.exitcode, 0)
        self.assertEqual(queue.get(timeout=1), "busy")
        queue.close()
        first.close()
        self.reopen()

    def test_inherited_handle_cannot_write_or_close_the_parent_session(self):
        model = self.model()
        ctx = multiprocessing.get_context("fork")
        queue = ctx.Queue()
        def child():
            outcomes = []
            for action in (model.list_turns, model.close):
                try:
                    action()
                    outcomes.append("unsafe")
                except llm.SessionError:
                    outcomes.append("fenced")
            queue.put(outcomes)
        proc = ctx.Process(target=child)
        proc.start()
        proc.join(5)
        self.assertEqual(proc.exitcode, 0)
        self.assertEqual(queue.get(timeout=1), ["fenced", "fenced"])
        queue.close()
        model.input("parent still owns the session")

    def test_unrecognized_directory_is_untouched(self):
        self.path.mkdir()
        file = self.path / "user.txt"
        file.write_text("retain me")
        with self.assertRaises(llm.SessionError):
            self.model()
        self.assertEqual([p.name for p in self.path.iterdir()], ["user.txt"])
        self.assertEqual(file.read_text(), "retain me")

    def test_missing_usage_and_finish_reasons_are_preserved(self):
        response = openai_response(usage=False, status="incomplete")
        response["incomplete_details"] = {"reason": "max_output_tokens"}
        self.reply = lambda _: httpx.Response(200, json=response)
        model = self.model()
        result = model.input("hello")
        self.assertIsNone(result.usage)
        self.assertIsNone(result.inference_seconds)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.finish_reason, "max_output_tokens")
        self.assertEqual(model.get_turn(result.turn_id).state, "completed")

    def test_terminal_provider_failure_is_cached_without_advancing_history(self):
        raw = openai_response(status="failed")
        raw["error"] = {"code": "server_error", "message": "provider failed"}
        self.reply = lambda _: httpx.Response(200, json=raw)
        model = self.model()
        for _ in range(2):
            with self.assertRaises(llm.RequestFailed):
                model.input("hello", turn_id="failed")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(model.get_turn("failed").response.usage, raw["usage"])
        self.assertEqual(model.get_turn("failed").response.finish_reason, "server_error")
        self.reply = lambda _: httpx.Response(200, json=openai_response())
        model.input("next", turn_id="next", retry_of="failed")
        self.assertEqual(self.body()["input"], [{"role": "user", "content": "next"}])

    def test_failed_commit_rolls_back_history_and_reopens_from_receipt(self):
        model = self.model()
        event = model._event
        def fail_commit(kind, *args, **kwargs):
            if kind == "completed":
                raise sqlite3.OperationalError("simulated disk full")
            return event(kind, *args, **kwargs)
        with mock.patch.object(model, "_event", side_effect=fail_commit):
            with self.assertRaises(llm.SessionError):
                model.input("hello", turn_id="one")
        self.assertEqual(model.get_turn("one").state, "running")
        self.assertEqual(model._meta("history"), [])
        model.close()
        model = self.reopen()
        self.assertEqual(model.input("hello", turn_id="one").text, "answer")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(len(model._meta("history")), 3)

    def test_retry_after_is_respected_and_waiting_can_be_cancelled(self):
        self.reply = lambda _: httpx.Response(429, headers={"retry-after": "60"}, json={"error": "busy"})
        model = self.model(timeout=0.1)
        with self.assertRaises(llm.TurnCancelled):
            model.input("hello", turn_id="one")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(model.get_turn("one").state, "cancelled")

    def test_raw_error_is_saved_without_echoed_credentials(self):
        self.reply = lambda _: httpx.Response(400, json={"error": {
            "message": "echo fake-api-key", "access_token": "private-token"}})
        model = self.model()
        with self.assertRaises(llm.RequestFailed):
            model.input("hello", turn_id="one")
        partial = model.get_turn("one").attempts[0]["partial"]
        self.assertEqual(partial["error"]["message"], "echo [REDACTED]")
        self.assert_no_secrets("fake-api-key", "private-token")

    def test_refusal_is_a_response(self):
        response = openai_response()
        response["output"][-1]["content"] = [{"type": "refusal", "refusal": "Cannot answer"}]
        self.reply = lambda _: httpx.Response(200, json=response)
        result = self.model().input("hello")
        self.assertEqual(result.finish_reason, "refusal")
        self.assertEqual(result.text, "Cannot answer")

    def test_openai_sse_reconstructs_items_and_records_identity(self):
        response = openai_response()
        completed = {**response, "output": []}
        self.reply = lambda _: sse([
            {"type": "response.created", "response": {"id": "resp-1", "status": "in_progress"}},
            *[{"type": "response.output_item.done", "output_index": i, "item": item}
              for i, item in enumerate(response["output"])],
            {"type": "response.completed", "response": completed},
        ])
        model = self.model()
        result = model.input("hello", turn_id="one")
        self.assertEqual(result.text, "answer")
        turn = model.get_turn("one")
        self.assertEqual(turn.attempts[0]["response_id"], "resp-1")
        self.assertEqual(turn.attempts[0]["receipt"]["output"], response["output"])

    def test_incomplete_sse_is_uncertain_and_not_automatically_retried(self):
        self.reply = lambda _: sse([
            {"type": "response.created", "response": {"id": "resp-1"}},
            {"type": "response.output_text.delta", "delta": "partial"},
        ])
        model = self.model()
        with self.assertRaises(llm.RecoveryRequired):
            model.input("hello", turn_id="one")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(model.get_turn("one").attempts[0]["partial"]["partial_text"], "partial")
        model.close()
        model = self.reopen()
        with self.assertRaises(llm.RecoveryRequired):
            model.input("hello", turn_id="one")
        with self.assertRaises(llm.RecoveryRequired):
            model.input("different", turn_id="two")
        model.abandon("one")
        self.reply = lambda _: httpx.Response(200, json=openai_response())
        model.input("new attempt", turn_id="two", retry_of="one")
        self.assertEqual(self.body()["input"], [{"role": "user", "content": "new attempt"}])
        self.assertEqual(model.get_turn("two").retry_of, "one")

    def test_context_error_preserves_history_and_reset_is_explicit(self):
        model = self.model()
        model.input("first", turn_id="one")
        self.reply = lambda _: httpx.Response(400, json={"error": {"code": "context_length_exceeded"}})
        with self.assertRaises(llm.ContextLimitError):
            model.input("too long", turn_id="two")
        self.assertEqual(len(self.requests), 2)
        self.reply = lambda _: httpx.Response(200, json=openai_response())
        model.input("next", turn_id="three")
        self.assertEqual(self.body()["input"][0]["content"], "first")
        self.assertNotIn("too long", json.dumps(self.body()))
        model.reset(reason="new task")
        model.input("fresh", turn_id="four")
        self.assertEqual(self.body()["input"], [{"role": "user", "content": "fresh"}])
        self.assertEqual(len(model.list_turns()), 4)
        self.assertIn("reset", [e["kind"] for e in model.events()])

    def test_known_rejection_and_connection_failure_retry_but_server_error_does_not(self):
        replies = iter([httpx.Response(429, json={"error": "busy"}),
                        httpx.Response(200, json=openai_response())])
        self.reply = lambda _: next(replies)
        model = self.model()
        model.input("hello", turn_id="one")
        self.assertEqual(len(model.get_turn("one").attempts), 2)
        self.reply = lambda _: httpx.Response(503, json={"error": "maybe executed"})
        with self.assertRaises(llm.RecoveryRequired):
            model.input("hello", turn_id="two")
        self.assertEqual(len(self.requests), 3)
        model.abandon("two")
        calls = 0
        def reply(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ConnectError("private transport data")
            return httpx.Response(200, json=openai_response())
        self.reply = reply
        model.input("retry connect", turn_id="three")
        self.assertEqual(len(model.get_turn("three").attempts), 2)

    def test_missing_credentials_fail_without_dispatch_or_fallback(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            model = self.model()
            with self.assertRaises(llm.AuthenticationError):
                model.input("hello", turn_id="one")
        self.assertEqual(self.requests, [])
        self.assertEqual(model.get_turn("one").state, "failed")

    def test_anthropic_api_key_and_signature_replay(self):
        self.reply = lambda _: httpx.Response(200, json=anthropic_response())
        model = self.model(name="opus-5", reasoning_effort="high")
        model.input("first")
        model.close()
        self.reopen().input("second")
        self.assertEqual(self.requests[-1].headers["x-api-key"], "fake-anthropic-key")
        self.assertNotIn("authorization", self.requests[-1].headers)
        self.assertEqual(self.body()["messages"][1]["content"], anthropic_response()["content"])
        self.assertEqual(self.body()["thinking"], {"type": "adaptive"})
        self.assertNotIn("tools", self.body())

    def test_anthropic_sse_accumulates_thinking_and_usage(self):
        self.reply = lambda _: sse([
            {"type": "message_start", "message": {"id": "m", "content": [], "usage": {"input_tokens": 7}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "reason"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "signature"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "answer"}},
            {"type": "content_block_stop", "index": 1},
            {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 9}},
            {"type": "message_stop"},
        ])
        model = self.model(name="opus-5")
        result = model.input("hello")
        self.assertEqual(result.usage, {"input_tokens": 7, "output_tokens": 9})
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.finish_reason, "max_tokens")
        self.assertEqual(model.get_turn(result.turn_id).attempts[0]["receipt"]["content"][0]["signature"], "signature")

    def test_unexpected_tool_output_never_executes_or_enters_history(self):
        raw = openai_response()
        raw["output"].append({"type": "function_call", "name": "execute", "arguments": "{}"})
        self.reply = lambda _: httpx.Response(200, json=raw)
        model = self.model()
        with self.assertRaises(llm.RecoveryRequired):
            model.input("hello")
        self.assertEqual(model.list_turns()[0].state, "uncertain")

    def test_duplicate_inflight_call_joins_without_redispatch(self):
        started, release = self.blocking_reply()
        model = self.model()
        one, result_one = self.run_in_thread(model)
        self.assertTrue(started.wait(2))
        two, result_two = self.run_in_thread(model)
        with self.assertRaises(llm.SessionBusy):
            model.input("other", turn_id="two")
        release.set()
        one.join(3)
        two.join(3)
        self.assertEqual(result_one, result_two)
        self.assertIsInstance(result_one[0], llm.Response)
        self.assertEqual(len(self.requests), 1)

    def test_cancel_abandon_and_late_result_do_not_advance_history(self):
        started, release = self.blocking_reply()
        model = self.model()
        thread, results = self.run_in_thread(model)
        self.assertTrue(started.wait(2))
        self.assertEqual(model.cancel("one").state, "uncertain")
        thread.join(2)
        self.assertIsInstance(results[0], llm.RecoveryRequired)
        model.abandon("one")
        release.set()
        self.wait_for(lambda: any(e["kind"] == "late_response" for e in model.events()))
        self.assertEqual(model.reconcile("one")[0].state, "abandoned")
        self.reply = lambda _: httpx.Response(200, json=openai_response())
        model.input("next", turn_id="two")
        self.assertEqual(self.body()["input"], [{"role": "user", "content": "next"}])

    def test_late_received_response_can_reconcile_uncertainty(self):
        started, release = self.blocking_reply()
        model = self.model()
        thread, results = self.run_in_thread(model)
        self.assertTrue(started.wait(2))
        model.cancel()
        thread.join(2)
        release.set()
        self.wait_for(lambda: any(e["kind"] == "late_response" for e in model.events()))
        self.assertEqual(model.reconcile("one")[0].state, "completed")
        self.assertEqual(model.input("hello", turn_id="one").text, "late")
        self.assertEqual(len(self.requests), 1)

    def test_close_fences_old_handlers_after_reopen(self):
        started, release = self.blocking_reply()
        model = self.model()
        thread, results = self.run_in_thread(model)
        self.assertTrue(started.wait(2))
        model.close()
        thread.join(2)
        model2 = self.reopen()
        self.assertEqual(model2.get_turn("one").state, "uncertain")
        model2.abandon("one")
        before = model2.events()
        release.set()
        time.sleep(0.1)
        self.assertEqual(model2.events(), before)
        self.assertEqual(model2.get_turn("one").state, "abandoned")

    def test_completion_wins_over_late_cancel(self):
        model = self.model()
        answer = model.input("hello", turn_id="one")
        self.assertEqual(model.cancel("one").response, answer)
        self.assertEqual(model.get_turn("one").state, "completed")

    def test_deadline_is_uncertain_after_dispatch(self):
        started, release = self.blocking_reply()
        model = self.model(timeout=0.1)
        before = time.monotonic()
        with self.assertRaises(llm.RecoveryRequired):
            model.input("hello", turn_id="one")
        self.assertLess(time.monotonic() - before, 1)
        self.assertEqual(model.get_turn("one").state, "uncertain")
        release.set()

    def test_cancel_before_dispatch_is_known_cancelled(self):
        model = self.model()
        started, release = threading.Event(), threading.Event()
        self.stack.callback(release.set)
        def credentials(*args):
            started.set()
            release.wait(3)
            return "token", {}
        with mock.patch.object(model._adapter.credentials, "get", side_effect=credentials):
            thread, results = self.run_in_thread(model)
            self.assertTrue(started.wait(2))
            self.assertEqual(model.cancel().state, "cancelled")
            release.set()
            thread.join(2)
        self.assertIsInstance(results[0], llm.TurnCancelled)
        self.assertEqual(self.requests, [])

    def test_actual_process_crashes_at_each_commit_boundary(self):
        for stage, exit_code in (("initialized", 44), ("prepared", 41), ("dispatched", 42),
                                 ("received", 43), ("committed", 46)):
            with self.subTest(stage=stage):
                path = self.root / stage
                proc = multiprocessing.get_context("spawn").Process(target=crash_worker, args=(str(path), stage))
                proc.start()
                proc.join(10)
                if proc.is_alive():
                    proc.kill()
                    proc.join()
                    self.fail("crash worker did not terminate")
                self.assertEqual(proc.exitcode, exit_code)
                with llm.LLM(session_dir=path, transport=self.transport) as model:
                    if stage == "initialized":
                        self.assertEqual(model.list_turns(), [])
                    elif stage == "prepared":
                        self.assertEqual(model.get_turn("durable-id").state, "prepared")
                        model.input("question", turn_id="durable-id")
                    elif stage == "dispatched":
                        self.assertEqual(model.get_turn("durable-id").state, "uncertain")
                        before = len(self.requests)
                        with self.assertRaises(llm.RecoveryRequired):
                            model.input("question", turn_id="durable-id")
                        self.assertEqual(len(self.requests), before)
                    else:
                        self.assertEqual(model.get_turn("durable-id").state, "completed")
                        self.assertEqual(model.input("question", turn_id="durable-id").text, "survived")
                        model.input("next")
                        self.assertEqual(self.body()["input"][0]["content"], "question")


class OAuthTests(Fixture):
    def write_oauth(self, provider="openai", *, expired=False):
        path = self.root / (provider + "-auth.json")
        if provider == "openai":
            data = {"auth_mode": "chatgpt", "tokens": {"access_token": "oauth-old", "refresh_token": "refresh-old",
                    "account_id": "account-1", "expires_at": time.time() + (-10 if expired else 3600)}}
        else:
            data = {"claudeAiOauth": {"accessToken": "sk-ant-oat-old", "refreshToken": "refresh-old",
                                     "expiresAt": (time.time() + (-10 if expired else 3600)) * 1000}}
        path.write_text(json.dumps(data))
        return path

    def test_oauth_is_explicit_and_reloads_renewed_login(self):
        path = self.write_oauth()
        model = self.model(auth="oauth", credential_file=path)
        model.input("first")
        self.assertEqual(str(self.requests[-1].url), "https://chatgpt.com/backend-api/codex/responses")
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer oauth-old")
        self.assertNotIn("max_output_tokens", self.body())
        data = json.loads(path.read_text())
        data["tokens"]["access_token"] = "oauth-new"
        path.write_text(json.dumps(data))
        model.input("second")
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer oauth-new")
        self.assert_no_secrets("oauth-old", "oauth-new", "refresh-old", "fake-api-key", "account-1")

    def test_missing_oauth_file_does_not_fall_back_to_environment_api_key(self):
        model = self.model(auth="oauth", credential_file=self.root / "missing.json")
        with self.assertRaises(llm.AuthenticationError):
            model.input("hello")
        self.assertEqual(self.requests, [])

    def test_processes_share_refresh_and_crashed_refresh_is_not_replayed(self):
        ctx = multiprocessing.get_context("spawn")
        for crash in (False, True):
            with self.subTest(crash=crash):
                path = self.write_oauth(expired=True)
                attempts = self.root / ("attempts-crash" if crash else "attempts-success")
                queue = ctx.Queue()
                processes = [ctx.Process(target=refresh_worker,
                    args=(str(path), str(attempts), crash, queue)) for _ in range(3)]
                for proc in processes:
                    proc.start()
                for proc in processes:
                    proc.join(10)
                    if proc.is_alive():
                        proc.kill()
                        proc.join()
                        self.fail("refresh process did not exit")
                self.assertEqual(attempts.read_text().splitlines(), ["refresh"])
                if crash:
                    self.assertEqual(sorted(p.exitcode for p in processes), [0, 0, 45])
                    self.assertEqual([queue.get(timeout=1) for _ in range(2)], [False, False])
                else:
                    self.assertEqual([p.exitcode for p in processes], [0, 0, 0])
                    self.assertEqual([queue.get(timeout=1) for _ in range(3)], [True, True, True])
                queue.close()

    def test_expired_oauth_refreshes_and_persists_rotation(self):
        path = self.write_oauth(expired=True)
        def reply(request):
            if request.url.path == "/oauth/token":
                self.assertEqual(json.loads(request.content)["refresh_token"], "refresh-old")
                return httpx.Response(200, json={"access_token": "oauth-renewed", "refresh_token": "refresh-new", "expires_in": 3600})
            return httpx.Response(200, json=openai_response())
        self.reply = reply
        model = self.model(auth="oauth", credential_file=path)
        model.input("one")
        model.input("two")
        self.assertEqual(len([r for r in self.requests if r.url.path == "/oauth/token"]), 1)
        self.assertEqual(json.loads(path.read_text())["tokens"]["refresh_token"], "refresh-new")
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer oauth-renewed")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assert_no_secrets("oauth-renewed", "refresh-new", "refresh-old")

    def test_401_refreshes_once_and_tracks_both_attempts(self):
        path = self.write_oauth()
        def reply(request):
            if request.url.path == "/oauth/token":
                return httpx.Response(200, json={"access_token": "oauth-renewed", "refresh_token": "refresh-new", "expires_in": 3600})
            if request.headers["authorization"] == "Bearer oauth-old":
                return httpx.Response(401, json={"error": "rejected"})
            return httpx.Response(200, json=openai_response())
        self.reply = reply
        model = self.model(auth="oauth", credential_file=path)
        result = model.input("hello", turn_id="one")
        self.assertEqual(result.text, "answer")
        self.assertEqual(len(model.get_turn("one").attempts), 2)
        self.assertEqual(len(self.requests), 3)

    def test_refresh_failure_never_replays_a_possibly_consumed_token(self):
        path = self.write_oauth(expired=True)
        def fail(request):
            raise httpx.ReadTimeout("refresh-old private details")
        self.reply = fail
        model = self.model(auth="oauth", credential_file=path)
        for turn_id in ("one", "two"):
            with self.assertRaises(llm.AuthenticationError) as raised:
                model.input("hello", turn_id=turn_id)
            self.assertNotIn("private", str(raised.exception))
        self.assertEqual(len(self.requests), 1)
        self.assert_no_secrets("refresh-old", "private details")
        self.assertTrue(path.with_name(path.name + ".llm-refresh.json").exists())

    def test_anthropic_oauth_authenticates_without_api_key(self):
        path = self.write_oauth("anthropic", expired=True)
        def reply(request):
            if request.url.path == "/v1/oauth/token":
                return httpx.Response(200, json={"access_token": "sk-ant-oat-new", "refresh_token": "rotated", "expires_in": 3600})
            return httpx.Response(200, json=anthropic_response())
        self.reply = reply
        model = self.model(name="opus-5", auth="oauth", credential_file=path)
        model.input("hello")
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer sk-ant-oat-new")
        self.assertNotIn("x-api-key", self.requests[-1].headers)
        self.assertIn("oauth-2025-04-20", self.requests[-1].headers["anthropic-beta"])
        self.assertIn("system", self.body())
        self.assert_no_secrets("sk-ant-oat-new", "rotated", "fake-anthropic-key")

    def test_concurrent_sessions_share_oauth_refresh(self):
        path = self.write_oauth(expired=True)
        started, release = threading.Event(), threading.Event()
        def reply(request):
            if request.url.path == "/oauth/token":
                started.set()
                release.wait(3)
                return httpx.Response(200, json={"access_token": "renewed", "refresh_token": "rotated", "expires_in": 3600})
            return httpx.Response(200, json=openai_response())
        self.reply = reply
        one = self.model(auth="oauth", credential_file=path)
        two = self.model(auth="oauth", credential_file=path, session_dir=self.root / "two")
        thread_one, results_one = self.run_in_thread(one)
        self.assertTrue(started.wait(2))
        thread_two, results_two = self.run_in_thread(two)
        release.set()
        thread_one.join(3)
        thread_two.join(3)
        self.assertIsInstance(results_one[0], llm.Response)
        self.assertIsInstance(results_two[0], llm.Response)
        self.assertEqual(len([r for r in self.requests if r.url.path == "/oauth/token"]), 1)

    def test_secret_echoes_in_provider_output_are_redacted(self):
        path = self.write_oauth()
        response = openai_response("echo oauth-old")
        response["access_token"] = "another-secret"
        self.reply = lambda _: httpx.Response(200, json=response)
        model = self.model(auth="oauth", credential_file=path)
        model.input("hello")
        self.assert_no_secrets("oauth-old", "another-secret")


@unittest.skipUnless(os.environ.get("EXPERIMENTAL_LLM_LIVE") == "1", "opt-in live provider test")
class LiveTests(unittest.TestCase):
    def test_two_turns_and_reopen(self):
        name = os.environ.get("EXPERIMENTAL_LLM_MODEL", "gpt-5.6-sol")
        auth = os.environ.get("EXPERIMENTAL_LLM_AUTH", "api_key")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "session"
            with llm.LLM(name=name, auth=auth, mode="multi_turn", session_dir=path) as model:
                first = model.input("Remember the word peach. Reply OK.", turn_id="one")
                self.assertIsInstance(first.text, str)
            with llm.LLM(session_dir=path) as model:
                second = model.input("What word did I ask you to remember?", turn_id="two")
                self.assertIn("peach", second.text.lower())
                self.assertEqual(model.input("Remember the word peach. Reply OK.", turn_id="one"), first)


if __name__ == "__main__":
    unittest.main()
