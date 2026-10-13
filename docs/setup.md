# Setup and Codex resources


Use Python 3.12 or newer. From the repository root, create an environment and
install the checkout with its pinned dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
```

GPT `-api` and `-api-multi` players use your ChatGPT/Codex subscription OAuth
login: run `codex login` first. Arena reads `$CODEX_HOME/auth.json` (default
`~/.codex/auth.json`) and calls `https://chatgpt.com/backend-api/codex/responses`
directly, following [examples/simple_agent.py](../examples/simple_agent.py). It uses the OpenAI SDK for HTTP and
stream decoding only; it does not launch a Codex agent or enable tools. These
players never fall back to `OPENAI_API_KEY`. Credentials are reread each request
so a renewed login takes effect without restarting the run. Reported GPT costs
are API-equivalent token estimates, not subscription charges; manifests record
this cost basis and the OAuth endpoint.

Claude players use `opus-5-high-api` and `opus-5-high-api-multi` (including
numbered runs such as `opus-5-high-api-multi2`). These players use the Claude Code
subscription login and never fall back to `ANTHROPIC_API_KEY`.
The subscription login is read from `~/.claude/.credentials.json`
(`claudeAiOauth`). `CLAUDE_CONFIG_DIR`
changes the configuration directory; `ARENA_ANTHROPIC_AUTH_PATH` overrides the
credential file directly. Arena rereads credentials before each request and
refreshes tokens shortly before expiry, sharing Claude Code's refresh locks and saving
rotated credentials atomically with mode 0600. Subscription metadata and other
stored fields are preserved. Alternatively, set
`CLAUDE_CODE_OAUTH_TOKEN` to an existing subscription access token; this takes
precedence and must be renewed externally.

Missing or rejected credentials pause the current move, including at startup.
Arena rereads the login every 60 seconds and continues automatically once it
recovers. Run `/login` in Claude Code if a new login is needed; leave arena
running. An explicit `CLAUDE_CODE_OAUTH_TOKEN` cannot be changed in an already
running process from another shell: replace or unset it and restart with
`--resume`. A positive `ARENA_LLM_API_MAX_ATTEMPTS` still limits retries.

Arena records refresh attempts in a private `*.arena-refresh.json` file beside
the credentials, containing a refresh-token hash and fixed status fields, not
tokens. Workers share cooldowns for temporary endpoint errors. Rejected or
interrupted refreshes wait for renewed credentials rather than resubmitting a
possibly consumed token. This includes a lost network response or a process
killed before saving rotated credentials. Do not delete the record to force a
retry; renew the login instead. A failed early refresh can continue using the
old access token until shortly before it expires. A Messages API 401 triggers
one coordinated refresh per consecutive rejection episode; a 403 waits for
credentials to change or periodically rechecks access without forcing refresh.

Token refresh requests identify the client as `gobench/0.1.0`. The token
endpoint rejects Python urllib's default user-agent with Cloudflare error 1010
(HTTP 403), before validating the refresh token. This differs from an OAuth
`invalid_grant` response. Workers started before this fix need a restart with
`--resume` to load it; renewing the login alone does not update their code.

The Claude OAuth adapter calls the Messages API directly through the Anthropic
SDK's HTTP/streaming transport, without launching an agent runtime. It
uses Claude Code compatibility headers and an identity system preamble;
the preamble is recorded in requests and manifests. Single-turn players start
fresh per move; multi-turn players retain message/thinking history per game.
Quota failures wait for the subscription reset or the provider's `Retry-After`;
unknown reset times are rechecked every five minutes. The same multi-turn
conversation is retained while waiting, including thinking signatures. Each call
records `auth_mode: oauth`, and failed-call usage remains in the cost ledger.
OAuth costs are API-equivalent estimates. Old `-oauth` names remain readable as legacy
aliases, but are no longer advertised as separate players.
See the [Anthropic error reference](https://platform.claude.com/docs/en/api/errors)
and [rate-limit reference](https://platform.claude.com/docs/en/api/rate-limits).

Set the relevant provider key for other LLMs: `MODEL_API_KEY`, `XAI_API_KEY`,
`DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`,
`GEMINI_API_KEY`. KataGo binaries and pinned networks
are downloaded automatically when required.

The Codex profiles use an existing Codex subscription login rather than an API
key when available; run `codex login` once first. The writable workspace modes
need Linux, bubblewrap support, and `libseccomp.so.2`. Networking and host
access are blocked except for the OpenAI-only authentication proxy.

Codex player names must include their training duration; for example,
`gpt6-astra-high-codex-0h` or `gpt6-astra-high-codex-4h`.

| Harness suffix | Autonomous training time |
| --- | --- |
| `codex-0h` | None |
| `codex-1h` | 1 hour |
| `codex-2h` | 2 hours |
| `codex-4h` | 4 hours |
| `codex-8h` | 8 hours |

The suffix sets the training budget, overriding the shared
`WorkspaceSettings.training_seconds` default. Numbered replicas such as
`gpt6-astra-high-codex-4h2` keep the same four-hour budget. Bare `-codex` and
`-codex-continual` names and run profiles are no longer accepted.

The nonzero-duration harnesses first give the agent the named amount of
autonomous preparation, with Python, C++, its workspace, and persistent Codex state.
It can write programs, run its own self-play, and experiment, but cannot play
against or query KataGo, access another Go engine, or use the internet. At the
deadline the arena stops the runtime and publishes an immutable checkpoint.
Code and notes should be saved incrementally; there is no extra cleanup turn.

Every evaluation game starts from an independent writable copy of that
checkpoint, including its workspace, Codex home, and conversation. Changes
from evaluation never reach another game or the training checkpoint.
`codex-0h` uses exactly the same protocol with **zero preparation
time**. Existing information-gain matchmaking selects evaluation opponents;
only evaluation results contribute to checkpoint Elo. Previous runs' results
for the same active workspace player are excluded from its new checkpoint's
rating evidence.

Each evaluation game has a **30-minute cumulative agent clock**, freely
allocated across moves, model response time, compilation, and other tool use.
There is no per-move time limit. The clock pauses and the entire agent cgroup
is frozen while the opponent plays. Invalid responses consume clock time;
retries and process restarts do not replenish it. Clock expiry is a timeout
loss, and reaching the arena move cap is a forfeit rather than a fresh attempt.
A kernel OOM termination during evaluation is a memory-limit forfeit.
The agent can read `/arena/clock.json` for its active deadline and remaining
time. Host filesystem setup and checkpoint copying are outside the clock;
Codex startup is counted so startup hooks cannot obtain free computation. Retry backoff is
outside the evaluation clock while the sandbox is frozen; preparation uses
one continuous active clock, including its retry overhead.

Training and evaluation share these default resource limits: one exclusive
physical CPU core with all its SMT siblings, 4096 MiB RAM, no swap, 2048 MiB writable filesystem capacity
(less filesystem metadata), 256 processes/threads combined, and no GPU.
All subagents share the allocation. The lowest numbered physical core and all
its siblings stay available to the OS and ordinary processes. Each training or
evaluation holds one of the other cores; an N-core host supports N-1 concurrent
allocations. A one-core host fails with an `only 1 core` error. Color-swapped
evaluations can run concurrently, and each starts as soon as one core is free.
Waiting for a core does not consume agent time. Training checkpoint publication
is locked so concurrent evaluations train only once.

Linux cgroup v2 [cpuset partitions](https://docs.kernel.org/admin-guide/cgroup-v2.html#cpuset)
exclude other host processes from each leased core; both SMT siblings remain
available without a CPU quota. CPU-local kernel threads and interrupts still
exist. System services run the sandbox as the invoking user and enforce RAM
and task limits. Root helpers hold host-wide leases, stop abandoned services,
and return cores to the host when an allocation ends or its arena process dies.
The host needs cpuset partition support, `systemd-run`, `mkfs.ext4`, `fallocate`,
`fstrim`, and noninteractive sudo for the Python lease helper, `systemctl`,
`systemd-run`, `tee`, `mount`, `umount`, `fstrim`, and `chown`.
Resource startup fails if the configured limits cannot be enforced.

The ext4 image has a logical capacity of 2 GiB. Sparse allocation, online discard,
and trimming on close keep physical disk usage near filesystem metadata plus
content, including after files are deleted. `ls -l` shows logical image length;
`du` shows allocated disk space.

Install the Python dependencies from [requirements.txt](../requirements.txt); both
`openai-codex` and `openai-codex-cli-bin` are pinned to **0.162.1** (the latest
stable Python SDK release verified on 2026-10-13). On Ubuntu 24.04 the C++/make
toolchain can be installed with:

```sh
sudo apt-get install --no-install-recommends g++=4:13.2.0-7ubuntu1 make=4.3-4.1build2
```

Compiler/interpreter versions and binary hashes, SDK version, CPU model,
architecture, and kernel are recorded in the checkpoint. Evaluation/resumption
rejects a changed checkpoint configuration or runtime identity.

Select training time through the player suffix or matching `--run-type` profile.
Other limits are source configuration, just like the other arena settings. Set
the `workspace` field of `CONFIG` or a `RUN_TYPES` entry; for example:

```python
workspace=WorkspaceSettings(
    evaluation_seconds=1800,
    cpu_cores=1,  # Exactly one physical core, including all SMT siblings.
    memory_mib=4096,
    storage_mib=2048,
    max_tasks=256,
)
```

`--resume` restores these settings from `run.json`. Use a new run/player name
for a different training budget, resource allocation, or independent replicate;
old continual directories are not imported automatically. Legacy workspace
runs cannot be resumed into this new protocol.

Checkpoints and training logs live under
`untracked_log/<run>/codex-checkpoints/<player>/`. Each checkpoint contains
`disk.img`, its thread pointer when present, and `manifest.json`, including
training time, request usage, and estimated training cost. Each evaluation
game has its own disk image, clock, turn journal, usage log, and summary under
`batch-*/agent-workspaces/game-*/`. Training images are retained permanently.
Per player within each arena run, only the most recently completed evaluation
image is retained, along with every incomplete evaluation image. Completion
order determines retention, regardless of game number. Older evaluation logs,
summaries, and journals remain. These rules apply to new protocol runs only;
existing runs are not migrated or pruned. Per-game workspace links at the run root
are usable while that game's image is mounted; after close, inspect the image
by mounting a **copy**. Do not mount the immutable checkpoint itself writable.
Run metadata references the checkpoint and records training cost separately
from evaluation cost. Learning curves now use preparation time/cost, rather
than a prescribed number of training games.
Interrupted requests that never report usage are counted separately in the
checkpoint manifest; their unreported token cost cannot be reconstructed.

Local resource integration tests exercise cgroups, disk limits, checkpoint
isolation, and the real SDK against fake model responses:

```sh
GOBENCH_RESOURCE_TESTS=1 .venv/bin/python -m unittest tests.test_workspace_runtime
```

## Track 2 with Claude Code

Claude Code players run the same Track 2 protocol as the Codex harnesses:
the same preparation durations, immutable checkpoint, independent evaluation
copies, 30-minute cumulative clock, exclusive physical core, RAM/disk/task
limits, frozen cgroup during the opponent's turn, and bubblewrap sandbox. Only
the agent runtime differs.

| Harness suffix | Autonomous training time |
| --- | --- |
| `claude-code-0h` | None |
| `claude-code-1h` | 1 hour |
| `claude-code-2h` | 2 hours |
| `claude-code-4h` | 4 hours |
| `claude-code-8h` | 8 hours |

Players are named like `claude-opus-5-5-high-claude-code-4h` (efforts `low`
through `max`; numbered replicas such as `...-claude-code-4h2` keep the
budget). Select them in `CONFIG` or with `python3 arena.py --run-type
claude-code-4h`, which evaluates `claude-opus-5-5-high-claude-code-4h`.

Requirements, in addition to the Codex workspace host requirements above:

- The **native** Claude Code executable for Linux (the self-contained ELF
  build, not the npm package), pinned to **2.1.296**
  (`CLAUDE_CODE_VERSION` in `gobench/workspace_runtime.py`):

  ```sh
  curl -fsSL https://claude.ai/install.sh | bash -s 2.1.296
  ```

  Arena uses `ARENA_CLAUDE_CODE_BIN` when set, otherwise
  `~/.local/share/claude/versions/2.1.296`, otherwise `claude` on `PATH`; any
  other version is rejected. Because the versioned file is used directly, a
  later auto-update of `claude` on `PATH` does not affect runs. The binary's
  SHA-256 is also recorded in the checkpoint specification.
- A host Claude subscription login (`~/.claude/.credentials.json`, see
  above). The sandbox never sees it.

Inside the sandbox, one persistent `claude -p --input-format stream-json
--output-format stream-json` process holds the session; its configuration
and transcripts live in `/harness-home` on the workspace disk image, so they
are part of the checkpoint. The CLI runs with `--dangerously-skip-permissions`,
`--strict-mcp-config` (no MCP servers), `--model` and `--effort` from the
player name, and with `WebSearch` and `WebFetch` disallowed. Every model alias,
subagent, and background request is pinned to the player's model, and Claude
Code's own retries are disabled so the arena retries with the evaluation clock
paused. Claude Code believes it uses a subscription OAuth login (a placeholder
token); the host-side proxy accepts only `POST /v1/messages` (and
`count_tokens`) for the configured model while the agent clock runs, removes
Anthropic-defined server tools (web search, web fetch, code execution), and
re-signs each request with the host login. Missing or rejected host
credentials pause the move, as for the Claude API players.

Every exchange is logged to `anthropic-proxy.jsonl` beside the phase's clock,
with streamed tool calls checked for internet use. Per-request usage goes to
`anthropic-proxy.usage.jsonl` and is priced at API-equivalent rates, including
one-hour cache writes at twice the base input rate. Checkpoints live under
`untracked_log/<run>/claude-code-checkpoints/<player>/`; turn results and
CLI stderr are in `claude-code-events.jsonl` and `claude-code-stderr.log`.

## Track 3: tutorial distillation

Track 3 measures whether a model can compress what it learns into a portable
text artifact. A learning agent runs in the Track 2 sandbox, with the same
runtimes (Codex or Claude Code), core, RAM/disk/task limits and wall clock,
but with **subagents disabled** (Claude Code's `Agent`/`Task` tools; Codex's
`multi_agent` feature). Its only output is `/workspace/tutorial.md`. At the
deadline the file is cut to its first **5,000 tokens** of tiktoken
`o200k_base` (the same tokenizer for every model) and frozen. No other
workspace state reaches evaluation.

Evaluation uses a Track 1 **multi-turn** API player, the *target*, with the
tutorial at the start of the first user message of every conversation
session: at game start and again after a 250,000-token history reset. Later
turns are unchanged Track 1 prompts. The target can be a different model
from the learner.

Players are named `<target>-tutorial<subtrack>-<learner>-<hours>h`, for example
`claude-sonnet-5-5-high-api-multi-tutorial3.3-claude-opus-5-5-high-claude-code-4h`.
The target must be an `-api-multi` player. The learner is a Track 2 workspace
model, effort and runtime without its duration, and hours are 1, 2, 4 or 8
(the "0h" baseline is the target itself, with no tutorial). Numbered replicas
(`...-4h2`) are independent learning runs. Profiles such as
`python3 arena.py --run-type gpt6-astra-tutorial3.3-2h` evaluate
`gpt6-astra-high-api-multi-tutorial3.3-gpt6-astra-high-codex-2h` (14 games).

| Subtrack | KataGo in the sandbox | Student tool |
| --- | --- | --- |
| `tutorial3.1` | No | No |
| `tutorial3.2` | Yes | No |
| `tutorial3.3` | Yes | Yes |

With KataGo, the pinned CPU build is mounted read-only at `/opt/katago`
(`/arena/bin/katago`), and every network of the configured opponent ladder at
`/opt/katago-networks`. `/arena/ladder.tsv` gives each ladder player's network,
Elo and speed (from `data/katago_network_speed_elo.txt`, measured on the
benchmark host, not in the sandbox) and how its temperature and playouts are
configured. All subtracks have `/arena/bin/tutorial-tokens` to count the
tutorial with the fixed tokenizer. `/arena/instructions.md` repeats the
learning instructions.

In 3.3, `/arena/bin/student TUTORIAL POSITIONS.json` runs the target in the
exact Track 1 harness (same prompt, effort and no tools), with the tutorial
cut to 5,000 tokens. Each call is one multi-turn conversation: every position
(a move list from the empty board, Black first; positions need not share a
game) becomes one turn, so the tutorial is sent once. It returns each visible
reply, the parsed move, legality, and cost. Illegal replies are asked again
with the same prompt, up to 5 attempts, and a call has at most 200 positions.
At most 4 calls run at once; more wait for a slot. The host runs these calls
through a Unix socket while the learning clock runs, and wall time continues
during them. When the clock stops, running calls end after their current
request. There is no spending cap.

Learning runs once per arena run and player, before that player's first
game, and is reused by every later game. The checkpoint lives under
`untracked_log/<run>/tutorial-checkpoints/<player>/`: `checkpoint/tutorial.md`
(read-only) and `manifest.json` with the tutorial hash, token counts, whether
the source was truncated or missing (a missing file yields an empty tutorial),
and costs. `learning_cost_usd` is the agent's API-equivalent cost plus every
student request (`student/call-*.jsonl` and `calls.jsonl` under
`preparation/`). The learning disk image and the untruncated source are kept
for audit. `run.json` copies the manifests under `tutorial_checkpoints`.
Evaluation game costs are reported separately, as for the target player.

The host needs the Track 2 workspace requirements (and the Claude Code binary
or Codex SDK for the learner), the target's API login, and `tiktoken`, which
downloads the `o200k_base` file once from OpenAI's public blob storage.
