Reasoning retention audit — 2026-09-07

The current registry has 94 player configurations, including 29 API multi-turn
configurations across nine provider entries. Retaining a returned reasoning item
in our history and having the provider use it in a later sample are separate
properties. This audit checks both the local implementation and documented
provider behavior. It does not claim to observe a model's internal use.

The initial audit made no production changes. A requested follow-up fixed the
Grok encrypted-reasoning request and explicitly enabled Astra's `all_turns`
policy. Historical samples below describe the configuration before those fixes.

| Models and provider | API multi-turn result | Evidence and remaining limits |
| --- | --- | --- |
| GPT-5.4, GPT-5.5 — OpenAI OAuth Responses | Response items replayed, but earlier-turn reasoning is not rendered by default | The code requests encrypted reasoning and replays it. OpenAI documents `current_turn` behavior for models preceding GPT-5.6; this is insufficient for carrying reasoning between Go moves. |
| GPT-5.6 Sol — OpenAI OAuth Responses | Configured for retention | Explicit `reasoning.context=all_turns`, encrypted reasoning requested, complete output items replayed. All 24 sampled successful records contain encrypted reasoning. |
| GPT-6 Astra — OpenAI OAuth Responses | Retention configured and live-verified | Explicit `reasoning.context=all_turns`. A two-turn check through the actual OAuth transport returned effective `all_turns` on both turns; turn two replayed the encrypted reasoning item from turn one, with 11 input tokens attributed to that item. |
| Muse Spark 1.2 and 1.3 Contributor — Meta Responses | Replay configured; live retention unverified | The preceding fix requests `reasoning.encrypted_content` for multi-turn Meta calls. All returned output items are saved and replayed. No successful Meta multi-turn records were found in the sample; the latest access check did not establish access. |
| Grok 4.5 and 4.6 — xAI Responses | Missing request option fixed; live verification pending | Multi-turn requests now include `reasoning.encrypted_content`, and returned reasoning items survive moves and resume in tests. `XAI_API_KEY` is absent here. All 24 historical sampled records per model predate the fix and contain summaries but no encrypted reasoning. |
| DeepSeek V4 Flash — direct Responses | Configured for retention; native reasoning observed | Full reasoning `content` is replayed with the adjacent assistant message. All 24 sampled records contain a native reasoning item. The placeholder `tools` entry is present and `tool_choice=none`. |
| DeepSeek V4 Pro — direct Chat Completions | Configured according to provider documentation; live retention unverified | `reasoning_content` is replayed. The placeholder `tools` entry enables the provider's prior-turn reasoning retention rule, even without actual tool calls. No successful multi-turn records were found in the sample. |
| Gemini 3.1 Pro, 3.6 Flash, 3.8 Flash — Google Interactions | Signed state replay configured | Complete native `steps` are saved and replayed, including thought signatures. All 24 sampled records for each Flash model contain signatures. No successful 3.1 Pro multi-turn records were found in the sample. |
| Claude Opus 5 — Anthropic API and OAuth | Signed thinking replay configured; provider keeps prior turns | Complete content blocks are replayed, including thinking, signatures, and redacted thinking. Opus 5 belongs to the documented keep-all-prior-turns group. All 24 sampled API records contain signatures. OAuth uses the SDK streaming accumulator; no successful OAuth multi-turn records were found in the sample. |
| Qwen3.8 Max — OpenRouter, pinned to Alibaba | Replay configured; gateway behavior not live-verified | OpenRouter reasoning fields are preserved. Alibaba documents `preserve_thinking=true` by default for Qwen3.8 Max. The arena relies on OpenRouter translating its reasoning fields to Alibaba's native history format. |
| Kimi K3 — OpenRouter, pinned to Moonshot | Replay configured; gateway behavior not live-verified | OpenRouter reasoning fields are preserved. Kimi instructs callers to return the complete assistant message. No successful multi-turn records were found in the sample to verify the gateway path. |
| Muse Spark 1.2 — OpenRouter, pinned to Meta | Replay configured; live retention unverified | Returned `reasoning_details`, `reasoning`, and `reasoning_content` are preserved. No successful multi-turn records were found in the sample. |

Provider sources: [OpenAI reasoning context](https://developers.openai.com/api/docs/guides/reasoning#persisted-reasoning),
[Astra capabilities](https://developers.openai.com/api/docs/guides/latest-model),
[xAI encrypted reasoning](https://docs.x.ai/developers/model-capabilities/text/generate-text),
[DeepSeek thinking rules](https://api-docs.deepseek.com/guides/thinking_mode/),
[DeepSeek Responses compatibility](https://api-docs.deepseek.com/guides/responses_api/),
[Google thought signatures](https://ai.google.dev/gemini-api/docs/thought-signatures),
[Claude preservation by model](https://platform.claude.com/docs/en/build-with-claude/thinking),
[Qwen preserve_thinking](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions),
[Kimi K3 conversation history](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart),
and [OpenRouter reasoning replay](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).

**Execution modes and retention boundaries**

- Every ordinary `api` player, including the single-turn Claude OAuth player,
  starts each move with a fresh prompt. It does not carry reasoning from earlier
  moves. A board position or move list in that prompt is not previous reasoning.
- Every `api-multi` player stores native assistant items in the raw call ledger,
  replays them on later moves, and restores them on resume. These histories reset
  per game, per restarted game attempt, at the 250,000-token context threshold,
  or on a provider context-length error. No compaction is used for these modes.
- GPT-5.6 Sol and Luna in `codex-single` start a fresh ephemeral thread per move.
  Earlier moves' reasoning is not retained.
- Sol and Luna in `codex-multi` and `codex-workspace-isolated` reuse a thread
  within a game. `codex-workspace-continual` retains its thread across games.
  Saved thread IDs are resumed. A sampled Codex proxy sequence shows encrypted
  reasoning items increasing from zero to four across five requests. Runtime
  compaction or pruning means this is not a promise of indefinite verbatim retention.
- Sol and Luna in `prime-isolated` retain a session within a game;
  `prime-continual` retains a session across games. A sampled Prime proxy sequence
  includes encrypted reasoning items on later requests. Prime explicitly enables
  automatic compaction and auto-refinement, so older reasoning can be replaced
  by compacted context. Neither harness overrides GPT-5.6's documented default
  `all_turns` behavior in the sampled requests.
- Labels in `FINAL_RUN_LLM_PLAYERS` are historical, non-executable records.
  Current configuration does not establish the behavior of those earlier runs.

**Verification**

The initial conversation, configuration, recovery, Codex, and Prime test groups
passed: 86 tests. After the fixes, 49 relevant conversation/configuration/recovery
tests passed, including seven replay-and-resume cases covering Meta, Grok 4.5,
all four registered Grok 4.6 efforts, and Astra. In addition, all 29 API multi-turn configurations passed a
synthetic native-item replay test through ledger serialization and resume.
[Machine-readable configuration checks](reasoning_retention_audit.json) record
each tested player and its request flags. Synthetic checks validate our code;
they do not validate remote endpoints.

Historical sampling inspected up to the first 24 lines of each available
`untracked_log/*/batch-*/llm-calls.jsonl` file, retaining at most 24 successful
conversation records per provider/model. This is a bounded sample, not a full
historical census. Representative files were:

| Model | Sample path | Observed reusable field |
| --- | --- | --- |
| GPT-5.6 Sol | `untracked_log/gpt5.6-sol-high-api-multi3/batch-003/llm-calls.jsonl` | Encrypted reasoning, 24/24 |
| Gemini 3.6 Flash | `untracked_log/gemini-3.6-flash-high-api-multi/batch-007/llm-calls.jsonl` | Thought signatures, 24/24 |
| Gemini 3.8 Flash | `untracked_log/gemini-3.8-flash-high-api-multi/batch-005/llm-calls.jsonl` | Thought signatures, 24/24 |
| Claude Opus 5 | `untracked_log/opus-5-high-api-multi/batch-007/llm-calls.jsonl` | Thinking signatures, 24/24 |
| DeepSeek V4 Flash | `untracked_log/DeepSeek-V4-Flash-0731-high-api-multi2/batch-006/llm-calls.jsonl` | Native reasoning items, 24/24; inspected item includes `content` |
| Grok 4.5 | `untracked_log/grok-4.5-high-api-multi/batch-005/llm-calls.jsonl` | Summaries only, no encrypted reasoning, 24/24 |
| Grok 4.6 | `untracked_log/grok-4.6-xhigh-api-multi/batch-001/llm-calls.jsonl` | Summaries only, no encrypted reasoning, 24/24 |

Codex proxy sample:
`untracked_log/arena_20260827_010420_508031_f49d0c92/batch-001/agent-workspaces/game-000001/openai-proxy.jsonl`.
Prime proxy sample:
`untracked_log/arena_20260826_203011_683803_51de85ca/batch-001/agent-workspaces/game-000002/openai-proxy.jsonl`.
Only field presence and counts were used in this report; it includes no raw
reasoning traces or credentials. The initial audit made no new API calls. The
follow-up made two successful tiny Astra requests after two HTTP 400 attempts
established that the OAuth endpoint rejects the test's `max_output_tokens`
parameter. The successful requests used the arena's normal request shape.

**Fixes and remaining verification**

Grok multi-turn requests now set `include=["reasoning.encrypted_content"]`.
This cannot recover reasoning missing from old records. Live Grok output and
replay still need verification with credentials available. Astra now sets
`reasoning.context=all_turns`, with effective mode and prior-reasoning input
attribution verified live. The other unverified paths need checks using the
exact registered model, provider, and effort; acceptance alone does not prove
internal use.
