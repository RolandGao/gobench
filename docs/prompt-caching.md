# Prompt caching

Provider paths audited on 2026-09-10. Caching eligibility does not guarantee a
hit: the prefix, minimum length, cache lifetime, and provider routing still matter.

## Anthropic API-key and OAuth requests

All registered Anthropic models and efforts now send top-level
`cache_control: {"type": "ephemeral"}`. This enables automatic caching with the
default five-minute lifetime. The service moves the cache boundary forward as
the conversation grows. See [Anthropic's caching documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

The setting lives in `_AnthropicMessagesProtocol` in `arena.py` and is recorded
in each new bot manifest. `_AnthropicOAuthProtocol` inherits it, adding the
Claude Code identity and streaming setting. `AnthropicOAuthClient.create()`
removes only the `stream` argument before forwarding the rest to the SDK's
streaming method, so `cache_control` reaches the Messages endpoint unchanged.
The OAuth path keeps bearer authentication and does not fall back to an API key.

Multi-turn requests retain native thinking blocks and append the next user
message. Both paths record cache reads and writes, account for them separately
from Anthropic's uncached `input_tokens`, and include all three input categories
in the conversation's context estimate. OAuth costs remain API-equivalent
estimates. Mock HTTP tests exercise the installed SDK's serialized request
bodies, streaming usage, history replay, recovery, and context resets; they do
not claim a live provider cache hit.

Historical uncached costs are unchanged. Because the bot manifest now includes
the caching setting, the existing settings-compatibility check will reject
extending an old run with a different manifest. Use a new numbered experiment
name for the cached run rather than rewriting the old manifest.

## Other registered providers

| Provider / registered models | Request-path status | Recorded evidence |
| --- | --- | --- |
| OpenAI OAuth: GPT-5.4, GPT-5.5, Sol, Luna, Astra | No setting disables caching; OpenAI documents default caching. | Sol, Luna, and Astra have cache hits. Older GPT-5.4 logs have zero hits; no claim that every individual model/run has hit the cache. |
| Codex workspace: Sol, Luna, Astra | SDK-managed requests; provider usage is retained for pricing. | Sol and Astra workspace logs have hits; archived Luna Codex logs also have hits. |
| Meta direct: Muse 1.2, Muse 1.3 contributor | No explicit opt-in in the request builder. | Muse 1.3 receives hits without one. Direct Muse 1.2 logs contain no recorded input usage, so that model's caching is unverified. |
| xAI: Grok 4.5, 4.6 | Automatic caching; no opt-in needed. | Both models have hits. Optional cache-routing hints are not configured. |
| DeepSeek Responses: V4 Flash; Chat: V4 Pro | Provider caching enabled by default. | Flash has hits. No compact direct-Pro call ledger was found in this checkout. |
| Google Interactions: Gemini 3.1 Pro, 3.6 Flash, 3.8 Flash | Implicit caching supports stateless requests, including the current `store: false` path. | Both Flash models have hits. Archived Pro logs have zero hits; this does not establish that caching is disabled. |
| OpenRouter: Kimi K3, pinned to Moonshot | Automatic provider caching. | Recorded cache hits. |
| OpenRouter: Muse 1.2, pinned to Meta | No explicit cache marker in the request path. | Recorded cache hits. |
| OpenRouter: Qwen3.8 Max, pinned to Alibaba | **Explicit caching is not enabled:** the request contains no content-block cache markers. | 314 compact calls, 125,188 input tokens, zero reads/writes in the historical ledger. |

Sources: [OpenAI](https://developers.openai.com/api/docs/guides/prompt-caching),
[xAI](https://docs.x.ai/developers/advanced-api-usage/prompt-caching),
[DeepSeek](https://api-docs.deepseek.com/guides/kv_cache/),
[Google Interactions](https://ai.google.dev/gemini-api/docs/interactions-overview),
and [OpenRouter](https://openrouter.ai/docs/guides/best-practices/prompt-caching).
Meta observations above are from the local call ledgers, not an inference from
OpenAI wire-format compatibility.

The Qwen route is a separate remaining configuration gap. OpenRouter documents
explicit content-block cache markers for Alibaba. Its public
[Qwen3.8 Max endpoint metadata](https://openrouter.ai/api/v1/models/qwen/qwen3.8-max/endpoints)
advertises cache-read and cache-write pricing ($0.25 and $2.50 per million
tokens, respectively), although its caching guide's model list does not yet
name Qwen3.8 Max. The arena also lacks a Qwen cache-write price and a mapping
for OpenRouter `prompt_tokens_details.cache_write_tokens`; enabling that path
must handle both markers and accounting. This change enables Anthropic only.

## Observed rates in the summary's multi-turn runs

Token-weighted cache reads divided by input tokens across each run's compact
call ledger at audit time (including any calls not yet committed as games):

| Family | Observed cache fraction |
| --- | ---: |
| Astra | 89.04%-92.52% |
| Sol | 92.18%-93.86% |
| Luna | 95.73%-96.51% |
| Muse 1.3 contributor | 89.53%-92.38% |
| Grok 4.6 | 80.96%-84.77% |
| Gemini Flash | 82.97%-92.19% |
| DeepSeek Flash | 95.48%-97.93% |
| Opus 5, before this change | 0% |

These are historical observations, not projected hit rates after the change.
