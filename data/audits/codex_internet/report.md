# Codex internet-access audit

**Finding: no recorded attempts to access the external internet were found.**

Audited September 15, 2026. This is a snapshot of the locally available reverse-proxy logs, including the ongoing Sol 4h evaluation.

## Coverage

- 202 `openai-proxy.jsonl` files: 8 preparation logs and 194 evaluation logs.
- All ten Astra/Sol configurations at 0, 1, 2, 4, and 8 hours of preparation. The 0h configurations have no training API calls.
- 16.41 GB of logs, containing 22,968 model-API exchanges.
- 14,467 distinct tool-call payloads, deduplicated across responses and replayed conversation history.
- Each file was read only through its size at scan start, so an ongoing evaluation could not continually extend the audit. No malformed or partial JSONL records occurred within those boundaries.

| Player | Training logs | Evaluation logs | API exchanges | Confirmed internet attempts |
| --- | ---: | ---: | ---: | ---: |
| Sol 0h | 0 | 20 | 1,016 | 0 |
| Sol 1h | 1 | 20 | 2,309 | 0 |
| Sol 2h | 1 | 20 | 2,403 | 0 |
| Sol 4h | 1 | 14 | 1,645 | 0 |
| Sol 8h | 1 | 20 | 3,906 | 0 |
| Astra 0h | 0 | 20 | 1,199 | 0 |
| Astra 1h | 1 | 20 | 2,390 | 0 |
| Astra 2h | 1 | 20 | 3,054 | 0 |
| Astra 4h | 1 | 20 | 2,147 | 0 |
| Astra 8h | 1 | 20 | 2,899 | 0 |

Evaluation-log counts include started games and should not be interpreted as completed-game counts.

## Checks performed

1. Inspected every recorded proxy request path and the existing `potential_internet_tool_calls` flags.
2. Extracted completed model tool calls from streamed/non-streamed responses and tool calls carried in request histories. Ignored tool descriptions and system prompts when deciding whether a tool was actually called.
3. Independently searched tool-call payloads for hosted browsing/search calls, external URLs, command-line network utilities, package/repository downloads, Python/JavaScript networking, sockets/DNS, and encoded-command indicators.
4. Reviewed the matched contexts and made a second pass for broader network/internet/download/proxy/browser/package keywords.

Every logged proxy request used **`/v1/responses`**. There were no requests to another proxy path, no recorded hosted web-search/browser calls, and no external URLs or download/network commands in the extracted tool calls. Normal model inference through the permitted reverse proxy is not counted as an internet-access attempt by the player.

## Why the automatic flags are misleading

11,867 exchanges had at least one built-in flag, but many repeatedly carried the same earlier command in their conversation histories. Deduplicating the built-in flag reason/excerpt yielded 255 entries. The independent broader scan produced 257 distinct candidate tool payloads; all were false positives:

- **252 payloads:** an escaped newline followed by the local `cat` command contains the characters `\ncat`. The regular expression matches `ncat`, incorrectly identifying a network utility.
- **10 payloads:** `nc` is a C++ counter/member, or an escaped newline immediately precedes a Python assignment to `c`. These are not invocations of netcat.
- **1 payload:** “requests” is an ordinary verb in generated README text, not an import or call to Python's networking package.

These categories overlap. The broader keyword pass matched 12 payloads: local documentation discussing the lack of network dependencies or the no-internet rule, plus the same ordinary use of “requests.”

Representative raw evidence:

- [Sol 4h evaluation, line 2](../../../untracked_log/gpt5.6-sol-high-codex-4h/batch-001/agent-workspaces/game-000001/openai-proxy.jsonl#L2): inherited training patches use `int nc=0` and `cand[nc++]` to count candidate moves.
- [Astra 8h preparation, line 5](../../../untracked_log/gpt6-astra-high-codex-8h/codex-checkpoints/gpt6-astra-high-codex-8h/preparation/openai-proxy.jsonl#L5): C++ `Info::nc` counts captured groups.
- [Astra 2h evaluation, line 2](../../../untracked_log/gpt6-astra-high-codex-2h/batch-001/agent-workspaces/game-000001/openai-proxy.jsonl#L2): an inherited local build/documentation command contains `\ncat >> Makefile` and the README phrase “explicitly requests the preceding non-learned UCT/LGR policy.”

The raw logs are ignored local artifacts. [summary.json](summary.json) preserves the file/byte boundaries, per-run counts, payload hashes, classifications, and source line references without copying request headers or credentials.

## Limits of the conclusion

This establishes **no observed attempts in the available reverse-proxy logs**, not a proof that no subprocess ever emitted a network packet. These logs capture model/API exchanges and tool instructions, not all system network traffic. Some API response streams were interrupted; inspecting subsequent request histories supplies additional evidence but cannot guarantee recovery of every truncated response. The unfinished Sol 4h run can generate additional logs after this snapshot.
