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
numbered runs such as `opus-5-high-api-multi2`). Authentication is selected
automatically: prefer a Claude Code subscription, then fall back to
`ANTHROPIC_API_KEY` when login/refresh is unavailable or the subscription returns
401, 403, or 429. Configure the key in the shell that starts the run to enable
paid fallback. Without a key, quota failures keep the existing retry behavior.
The subscription login is read from `~/.claude/.credentials.json`
(`claudeAiOauth`). `CLAUDE_CONFIG_DIR`
changes the configuration directory; `ARENA_ANTHROPIC_AUTH_PATH` overrides the
credential file directly. Arena rereads credentials before each request and
refreshes tokens shortly before expiry, serializing its workers and saving
rotated credentials atomically with mode 0600. Subscription metadata and other
stored fields are preserved. Alternatively, set
`CLAUDE_CODE_OAUTH_TOKEN` to an existing subscription access token; this takes
precedence and must be renewed externally.

The Claude OAuth adapter calls the Messages API directly through the Anthropic
SDK's HTTP/streaming transport, without launching an agent runtime. It
uses Claude Code compatibility headers and an identity system preamble;
the preamble is recorded in requests and manifests. Single-turn players start
fresh per move; multi-turn players retain message/thinking history per game.
On a quota rejection the current move is retried immediately with the API key;
the provider's `Retry-After` controls when OAuth is tried again. Authentication
failures without a reset interval are rechecked after 60 seconds. The same
multi-turn conversation is retained across the switch, including thinking
signatures. Each call records `auth_mode` (`oauth` or `api_key`), and failed-call
usage remains in the cost ledger. OAuth costs are API-equivalent estimates;
API-key requests incur API charges. Old `-oauth` names remain readable as legacy
aliases, but are no longer advertised as separate players.
See the [Anthropic error reference](https://platform.claude.com/docs/en/api/errors)
and [rate-limit reference](https://platform.claude.com/docs/en/api/rate-limits).

Set the relevant provider key for other LLMs: `MODEL_API_KEY`, `XAI_API_KEY`,
`DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`,
`GEMINI_API_KEY`, or `ANTHROPIC_API_KEY`. KataGo binaries and pinned networks
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
`openai-codex` and `openai-codex-cli-bin` are pinned to **0.147.0** (the latest
stable Python SDK release verified on 2026-09-08). On Ubuntu 24.04 the C++/make
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
