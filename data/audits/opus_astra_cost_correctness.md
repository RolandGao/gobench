# Opus 5 versus Astra: cost and correctness audit

Audited 2026-09-09 against `log/summary/report.txt`, `results.json`, and the
three source runs below. Historical results and benchmark configuration were
not modified. No paid model requests were made.

The recorded cost arithmetic and game results check out. Opus's high cost is
primarily uncached conversation input. Astra High's higher Elo is uncertain
with only 14 games; Astra Max's lead is supported by the fitted rating model.
The runs also differ in prompt wording and billing basis.

## Exact usage and costs

| Metric | opus-5-high-api-multi | gpt6-astra-high-api-multi | gpt6-astra-max-api-multi |
| --- | ---: | ---: | ---: |
| Games | 14 | 14 | 14 |
| Recorded LLM moves / successful calls | 570 | 484 | 490 |
| All logged API calls, including failures | 571 | 484 | 492 |
| Input tokens, including cache reads | 30,573,072 | 5,857,953 | 20,409,351 |
| Cached input tokens (subset of preceding row) | 0 | 5,216,128 | 18,881,920 |
| Uncached input tokens | 30,573,072 | 641,825 | 1,527,431 |
| Cache write tokens | 0 | 0 | 0 |
| Billed output tokens, including thinking | 934,258 | 86,807 | 875,907 |
| Separately recorded reasoning tokens | unavailable | 83,066 | 872,002 |
| Input + output tokens | 31,507,330 | 5,944,760 | 21,285,258 |
| Input tokens per LLM move | 53,636.97 | 12,103.21 | 41,651.74 |
| Output tokens per LLM move | 1,639.05 | 179.35 | 1,787.57 |
| Input cache hit fraction | 0% | 89.04% | 92.52% |
| Uncached input cost | $152.865360 | $6.418250 | $15.274310 |
| Cached input cost | $0 | $5.216128 | $18.881920 |
| Output cost | $23.356450 | $4.340350 | $43.795350 |
| Total recorded cost | $176.221810 | $15.974728 | $77.951580 |
| Cost per LLM move | $0.30916107 | $0.03300564 | $0.15908486 |

Token totals count processing on every request, including repeated history;
they are not counts of unique text. Cached tokens must not be added a second
time. Anthropic's normalized `reasoning_tokens: 0` is a missing breakdown, not
evidence that thinking was disabled. Its adapter maps total output but no
separate reasoning field. Thinking is included in billed output according to
[Anthropic's thinking documentation](https://platform.claude.com/docs/en/build-with-claude/thinking).

Every call was independently repriced using the run's recorded rates:

- Opus: `(input * 5 + cached * 0.5 + writes * 6.25 + output * 25) / 1e6`.
- Astra: `((input - cached) * 10 + cached * 1 + output * 50) / 1e6`;
  all recorded cache writes are zero and inputs remain below the long-context tier.

Maximum discrepancy between recomputed and logged cost: zero. Per-game call
sums equal all 42 CSV game costs; aggregate totals equal the summary.

## Why Opus is expensive

Opus costs 9.37 times Astra High per move and 1.94 times Astra Max per move.
Input processing accounts for 86.75% of Opus's total. The configured Opus
input/output rates are half Astra's, so higher unit prices do not explain this.
Anthropic's published Opus 5 rates agree with the recorded rates.

`APIConversation.prepare()` in `gobench/llm_conversation.py` resends each game's
growing history, and `response_items()` retains native assistant content,
including thinking blocks. All three runs remained in session 1 for every
game: no context reset or capped-game retry inflated these totals. Opus input
reached 194,793 tokens in one request. Its output per move was about 9.14 times
Astra High's, increasing generation cost and the history available for replay.
The compact logs do not preserve enough content to quantify each component of
the retained input independently.

The Anthropic request builder in `arena.py` has no `cache_control`, and Opus's
ledger records neither cache writes nor reads. Astra received extensive cache
discounts. Anthropic documents enabling automatic caching with top-level
`cache_control={"type": "ephemeral"}` for growing conversations; it is not
enabled merely by retaining message history. See
[prompt caching and current Opus pricing](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

For scale only, repricing Astra's same recorded token counts with no cache
discount gives $62.919880 for High and $247.888860 for Max. This arithmetic
counterfactual shows how strongly caching affects the comparison; it is not a
prediction of a new run or a corrected historical bill.

## Correctness and playing strength

- Independently replayed all 42 games using `analysis.audit_superko.ReplayBoard`:
  3,096 recorded actions, including 21 resignations; no illegal placements,
  self-capture-rule violations, or positional-superko violations.
- Matched every one of the 1,544 LLM moves to exactly one successful logged API
  response at the same game and move number.
- Recomputed strict Tromp-Taylor area scores with komi 7 for all 21 games
  ending in two passes. All match. Verified the terminal side and winner in
  the 21 resignations; this does not judge whether resignation was strategically wise.
- Checked CSV and JSON game results, winners, numeric outcome scores, turn
  order, and game termination. All agree.
- Verified the summary's recorded SHA-256 hashes for the three runs' metadata,
  CSV results, and full game records: all nine match current source files.
- Reloaded all 320,208 committed rating games and repeated the color-adjusted
  regularized Bradley-Terry fit. All three Elo values reproduce exactly.

| Model | Recomputed Elo | 95% half-width | W-L-D |
| --- | ---: | ---: | --- |
| Opus High | 1939.926092 | 224.302048 | 8-6-0 |
| Astra High | 2176.437666 | 219.633082 | 8-5-1 |
| Astra Max | 2475.366606 | 227.047828 | 8-5-1 |

Using the full fitted covariance, including shared rating/color uncertainty:

- Astra High minus Opus: +236.511573 Elo; approximate 95% interval
  **[-75.695310, +548.718457]**. The evidence does not establish this lead at 95%.
- Astra Max minus Opus: +535.440513 Elo; approximate 95% interval
  **[+217.980564, +852.900462]**. The fitted model supports this lead.

These are model-based Laplace intervals, not results of direct head-to-head
matches. Opponent schedules differ. For one shared opponent,
`kata1-b6c96-s14649344-d2727367-temp-0.3` (about 2084 Elo), Opus went 0-2 and
Astra High went 2-0. Opus went 4-2 against an approximately 1856-Elo opponent,
while Astra High also scored points against opponents around 2160-2246 Elo.
This explains the fitted ordering despite similar overall win counts.

## Reporting and comparison caveats

1. **Astra costs are API-equivalent estimates.** Its source `run.json` bot
   entries specify `auth_mode: chatgpt_oauth`, the ChatGPT Codex backend, and
   `cost_basis: api_equivalent_estimate`. Opus uses Anthropic API-key access and
   token-usage cost tracking. Neither ledger is an independently reconciled
   provider invoice; the summary's generic "Total cost" label hides the distinction.
2. **Prompts differ.** Opus's `prompt.txt` has the older rules wording and
   "Output exactly one item" instruction. Both Astra runs use expanded
   capture/self-capture instructions and a stricter single-line final-answer
   instruction. The experiment therefore compares these complete run setups,
   not model identity under an identical prompt. No causal explanation for
   the remaining strength difference is established by this audit.
3. **"API problem rate" is narrower than its label suggests.**
   `_choose_llm_move()` increments it for empty successful responses, and
   `_recovered_llm_stats()` skips failed calls when counting this metric.
   Opus actually logged one failed call (`BadRequestError`), Astra High zero,
   and Astra Max two (`InternalServerError`, `RemoteProtocolError`), despite
   all three reporting zero API problems. All failed calls have zero recorded
   usage/cost, and every final move has a successful response; these failures
   do not explain the cost or outcome gap. Zero recorded usage on a failed
   request cannot independently prove zero provider billing.
4. **Raw response verification is limited.** The three corresponding raw
   `untracked_log` directories are absent locally. Usage can be reconciled
   against the compact call ledger, costs, source metadata, and game records,
   but not against original provider response bodies or invoices. Opus's
   separate thinking-token count cannot be reconstructed from these files.

For a future controlled comparison: enable Anthropic caching, use the same
prompt version, explicitly label estimated costs, and report transport
failures separately from empty model responses. More games are needed to
resolve the Astra High versus Opus difference. Historical costs should retain
their observed cache behavior rather than be replaced with hypothetical savings.
