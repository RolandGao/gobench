"""No-tool API history, reset between turns, recovered from the raw call ledger."""

from __future__ import annotations

import copy
import hashlib
import json


CONTEXT_RESET_TOKENS = 250_000
CONVERSATION_VERSION = 1


def json_value(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def byte_estimate(value):
    # Conservative fallback, not an exact tokenizer for every provider.
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8")) + 256


def qwen_cache_messages(messages):
    """Mark recent user prefixes without changing stored reasoning or signatures."""
    messages = copy.deepcopy(messages)
    blocks = []
    for message in messages:
        if message.get("role") != "user":
            continue
        if isinstance(message.get("content"), str):
            message["content"] = [{"type": "text", "text": message["content"]}]
        for block in message.get("content", []):
            if isinstance(block, dict):
                block.pop("cache_control", None)
                if block.get("type") == "text":
                    blocks.append(block)
    # Bound explicit markers as the conversation grows. Each prefix includes
    # preceding assistant reasoning; none of that content is stripped.
    for block in blocks[-4:]:
        block["cache_control"] = {"type": "ephemeral"}
    return messages


def cap_output_to_context(request, context_window, max_tokens_field, input_estimate=None):
    if context_window is None or max_tokens_field is None:
        return
    # These providers share one window between input and output. Reserve input
    # headroom instead of requesting a maximum that cannot fit a later turn.
    if input_estimate is None:
        input_estimate = byte_estimate(request.get("messages", request.get("input", "")))
    options = request
    path = max_tokens_field.split(".")
    for key in path[:-1]:
        options = options[key]
    options[path[-1]] = min(options[path[-1]], max(1, context_window - input_estimate))


def context_length_error(exc):
    body = getattr(exc, "body", {})
    message = (str(exc) + " " + json.dumps(body, default=str)).lower()
    return any(marker in message for marker in (
        "context_length_exceeded", "maximum context length", "context window exceeded",
        "exceeds the context window", "input token count exceeds", "prompt is too long",
        "too many input tokens",
    ))


class APIConversation:
    def __init__(self, provider, model, player, game, wire_format, *, limit=CONTEXT_RESET_TOKENS,
                 context_window=None, max_tokens_field=None):
        self.identity = dict(version=CONVERSATION_VERSION, provider=provider,
                             model=model, player=player, game=game, limit=limit)
        self.wire_format = wire_format
        self.context_window = context_window
        self.max_tokens_field = max_tokens_field
        self.limit = limit
        self.game_attempt = 1
        self.loaded = False
        self.history = []
        self.observed_tokens = 0
        self.session = 1
        self.reset_reason = "game_start"
        self.replies = {}
        self.last_reused = False

    def set_game_attempt(self, attempt):
        self.game_attempt = attempt
        self.loaded = False
        self.history = []
        self.replies = {}
        self.observed_tokens = 0
        self.session = 1
        self.reset_reason = "game_start"

    def reset_game(self):
        self.set_game_attempt(self.game_attempt + 1)

    def load(self, path):
        if self.loaded:
            return
        if path.exists():
            with path.open(encoding="utf-8") as source:
                for line in source:
                    entry = json.loads(line)
                    if (entry.get("game") != self.identity["game"]
                            or entry.get("player") != self.identity["player"]
                            or not entry.get("ok")):
                        continue
                    event = entry.get("conversation")
                    if event is None or event.get("identity") != self.identity:
                        raise ValueError("saved API conversation policy does not match this player")
                    if event["game_attempt"] != self.game_attempt:
                        continue
                    self.accept(event, entry["output"], entry["move"], entry["attempt"])
        self.loaded = True

    def cached_reply(self, prompt, move, attempt):
        self.last_reused = False
        saved = self.replies.get((move, attempt))
        if saved is None:
            return None
        if saved[0] != digest(prompt):
            raise ValueError("saved API reply does not match the recovered move prompt")
        self.last_reused = True
        return saved[1]

    def reset(self, reason):
        self.history = []
        self.observed_tokens = 0
        self.session += 1
        self.reset_reason = reason

    def user_items(self, prompt):
        if self.wire_format == "google":
            return [{"type": "user_input", "content": [{"type": "text", "text": prompt}]}]
        return [{"role": "user", "content": prompt}]

    def prepare(self, request, prompt):
        current = self.user_items(prompt)
        estimate = (self.observed_tokens or (byte_estimate(self.history) if self.history else 0))
        estimate += byte_estimate(current)
        if self.history and estimate >= self.limit:
            self.reset("context_limit")
            estimate = byte_estimate(current)
        if estimate >= self.limit:
            raise ValueError("current move prompt alone exceeds the context reset budget")
        request = copy.deepcopy(request)
        field = "input" if self.wire_format in {"responses", "google"} else "messages"
        request[field] = copy.deepcopy(self.history + current)
        if self.identity["provider"] == "openrouter" and self.identity["model"].startswith("qwen/"):
            request[field] = qwen_cache_messages(request[field])
        cap_output_to_context(request, self.context_window, self.max_tokens_field, estimate)
        if (self.wire_format == "responses"
                and self.identity["provider"] in {"openai", "meta", "xai"}):
            request["include"] = ["reasoning.encrypted_content"]
            if (self.identity["provider"] == "openai"
                    and self.identity["model"].startswith(("gpt-5.6", "gpt-6-astra"))):
                request["reasoning"]["context"] = "all_turns"
        self.pending = dict(identity=self.identity, game_attempt=self.game_attempt,
                            session=self.session, reset_reason=self.reset_reason,
                            estimated_input_tokens=estimate, prompt_digest=digest(prompt),
                            request_digest=digest(request), user_items=current)
        return request

    def response_items(self, response):
        if self.wire_format == "responses":
            items = json_value(response.output)
        elif self.wire_format == "google":
            # Interactions' stateless input accepts the native returned steps.
            items = json_value(response.steps)
        elif self.wire_format == "anthropic":
            items = [{"role": "assistant", "content": json_value(response.content)}]
        else:
            if not response.choices or response.choices[0].message is None:
                return []
            message = json_value(response.choices[0].message)
            # Preserve native reasoning, but omit output-only finish/usage fields.
            items = [{k: v for k, v in message.items() if k in {
                "role", "content", "reasoning", "reasoning_content", "reasoning_details",
            }}]
        if not isinstance(items, list):
            raise ValueError("provider did not return replayable conversation items")
        return items

    def completed_event(self, response, observed_tokens):
        return dict(self.pending, assistant_items=self.response_items(response),
                    observed_tokens=observed_tokens)

    def accept(self, event, output, move, attempt):
        if event["session"] != self.session:
            self.history = []
        self.session = event["session"]
        self.history.extend(event["user_items"] + event["assistant_items"])
        self.observed_tokens = event["observed_tokens"]
        self.reset_reason = None
        self.replies[(move, attempt)] = (event["prompt_digest"], output)


class ConversationClient:
    """One wrapper per game; SDK transports remain unchanged."""

    def __init__(self, client, conversation):
        self.client = client
        self.conversation = conversation

    def __getattr__(self, name):
        return getattr(self.client, name)

    def reset_game(self):
        self.conversation.reset_game()
