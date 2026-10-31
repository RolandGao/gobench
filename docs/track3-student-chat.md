# Track 3.4: chatting with the student

Status: implemented and unit-tested; no learning run yet.
[setup.md](setup.md#track-3-tutorial-distillation) describes Track 3 as a whole.

## Why

In 3.3 the learner (the teacher) can only send batches of positions to
`/arena/bin/student` and gets back one move per position. Most of the student's
output is hidden reasoning, so the teacher pays for it but sees only a
coordinate. It cannot ask why a move was chosen, which part of the tutorial was
used, or what was unclear. Learning is slow per dollar: student calls were
50-90% of the learning cost in the gpt6-astra runs ($192 of $214 at 8h).

Subtrack `tutorial3.4` replaces the batch tool with a chat: the teacher talks to the student the
way a person talks to an assistant, and builds batching itself if it wants it.
Everything else is as in 3.3, including KataGo in the sandbox: the only output is
`/workspace/tutorial.md`, cut to 5,000 `o200k_base` tokens, and evaluation is
the same.

## Interface

A Python module in the sandbox, importable by `/usr/bin/python3`:

```python
from student import Student, move_prompt

s = Student("ladders")   # create, or reattach to an existing student by name
s = Student()            # create with a generated name
s.name                   # its name
s.send(text)             # send one message; returns immediately
s.reply()                # never blocks: the reply to the latest send, or None
s.close()                # end the student
move_prompt(moves)       # the exact Track 1 move prompt for a position
```

### Students

- A student is the evaluation model (the target) at its evaluation effort, with
  no tools and no system prompt, in the Track 1 **multi-turn** harness: one
  conversation, with the model's own reasoning kept between turns as in Track 1.
  It sees only what the teacher sends. Nothing frames it as a student or names
  the teacher.
- Students live on the host for the whole learning period, not in the
  teacher's process. `Student(name)` from any later process reattaches to the
  same conversation. If the host's learning process is interrupted and
  resumed, earlier students have ended: their names stay taken and their cost
  still counts.
- There is no limit on how many students exist or reply at once. The only
  limit is the $50 student cost limit (see [Cost and limits](#cost-and-limits)).
- Names are unique for the run and match `[A-Za-z0-9_-]{1,64}`. Reattaching to
  a finished student works (for `reply()` and its transcript). Using its name
  for a new student does not.

### Messages

- `send(text)` hands the message to the host and returns. The host makes the
  model call in its own thread, so the teacher keeps working.
- A student holds one message at a time. Sending while its reply is pending
  raises an error. For parallel work, use several students.
- `reply()` returns the visible text of the reply to the most recent `send`.
  It returns `None` before the first send and while that reply is pending, even
  if an older reply exists. It raises if that send failed: an API error the
  Track 1 harness's retries could not get past, closing, the cost limit, or the
  learning deadline. A failed send leaves the conversation as it was before
  that send.
- No retry happens for illegal moves or replies that are not moves. A reply is
  whatever the model wrote.
- `send` raises once the student cost limit is reached (see
  [Cost and limits](#cost-and-limits)).

### Context limit

The context limit is Track 1's 250,000 tokens, measured the same way Track 1
decides a history reset, but students are never reset. A `send` whose message
would take the conversation to the limit is refused and finishes the student.
If a reply takes the conversation past the limit anyway, the reply is delivered
and the student is finished. Either way, `send` then raises "context limit
reached", and the teacher starts a new student.

### Closing

`close()` finishes the student. A pending reply is discarded.
Its request still runs to completion on the host and its cost counts.

### `move_prompt(moves)`

`moves` is a move list from the empty board, Black first, in the 3.3 position
format (`["B E5", "W C3"]` or `["E5", "C3", "pass"]`). It returns exactly the
move prompt Track 1 sends for that position, with the referee's legal move and
ko lists. The host referee computes it over the tool socket; it makes no model
call and costs nothing. It raises for an illegal move list or a finished game.
An evaluation session's first message is the tutorial wrapper shown in
`/arena/instructions.md` followed by this prompt; the teacher builds that
itself.

### Batching

The primitives are enough to rebuild the 3.3 batch tool. For example, `n`
students side by side, each answering a list of positions in one conversation:

```python
import time
from student import Student, move_prompt

# wrapper() is the teacher's copy of the tutorial wrapper from /arena/instructions.md.
n = 8
suites = [positions[i::n] for i in range(n)]
students = [Student() for _ in suites]
answers = [[] for _ in suites]
next_index = [0] * n
for s, suite in zip(students, suites):
    s.send(wrapper(tutorial) + move_prompt(suite[0]))
while any(k < len(suite) for k, suite in zip(next_index, suites)):
    for i, s in enumerate(students):
        if next_index[i] < len(suites[i]) and (text := s.reply()) is not None:
            answers[i].append(text)
            next_index[i] += 1
            if next_index[i] < len(suites[i]):
                s.send(move_prompt(suites[i][next_index[i]]))
    time.sleep(2)
```

Checking legality, retrying, and comparing against KataGo are the teacher's own
code.

## Sandbox files

- `/arena/students/<name>.md`: one read-only transcript per student, updated by
  the host on every send and reply. Each turn shows the teacher's message, the
  student's visible reply (or that it is pending or failed), and its cost. The
  header says whether the student is open, closed or past the context limit.
- `/arena/students/cost.json`: student spending so far, the $50 limit, what
  remains, whether the limit was reached, and how many replies are pending,
  updated by the host on every send and reply.
- `/arena/python/student.py`: the module. `PYTHONPATH` points at
  `/arena/python` in the sandbox.
- `/arena/bin/tutorial-tokens`, `/arena/ladder.tsv`, KataGo and
  `/arena/instructions.md` are as in 3.3.
- There is no `/arena/bin/student` batch tool.

## Cost and limits

- Student requests are limited to **$50 per learning run**, the same for every
  hour setting. A request cannot be stopped once it is sent, so the host
  checks after each request finishes:
  - The reply whose request takes spending to $50 or more is delivered.
  - Replies still pending at that point finish on the host and their cost is
    recorded, but they are discarded: `reply()` raises "student cost limit
    reached". They make no further API retries.
  - `send` raises "student cost limit reached" from then on.

  The total can therefore pass $50 by the cost of the requests in progress at
  that moment. Every student request counts toward `learning_cost_usd`, as in
  3.3.
- The teacher's own model cost has no limit.
- The learning wall clock keeps running while replies are pending. At the
  deadline, pending replies end after their current request and still count.

## Teacher instructions

`/arena/instructions.md` (and the learning prompt) describe the `Student`
interface, the context limit, and `cost.json`. They add:

> Student messages cost at most $50 in total for this learning period. After
> that, `send` fails, so plan how to spend it. You can create as many students
> as you like and have them reply at the same time. A student is a multi-turn
> conversation: earlier turns are cached, so sending several messages to one
> student is usually faster and cheaper than sending each message to a new
> student.
>
> If it helps, you can build batching from these primitives. For example, test
> many positions by giving each of several students a share of them and, from a
> script, polling each student's `reply()` and sending it its next
> `move_prompt` when the reply arrives. This is only an option; use the
> students however you like.

## Logging and checkpoint

In the checkpoint's `preparation/` directory, each student keeps:

- `public/students/<name>.md`: the transcript the teacher saw, and
  `public/students/cost.json`;
- `student/chats/<name>.jsonl`: every request in the Track 1 call log format.

They take the place of 3.3's `student/call-*.jsonl` and `calls.jsonl`. The
manifest keeps `student_requests`, `student_failed_requests`, `student_tokens`
and `student_cost_usd`, and adds `students` (the number that sent at least one
message). The protocol is `tutorial-distillation-v2` (3.1-3.3 stay on v1). The
3.4 specification records `student_interface` ("chat"),
`student_cost_limit_usd` (50) and `student_context_limit_tokens` instead of
`student_max_concurrency`, `student_max_positions` and `student_max_attempts`.

## Subtrack

3.4 is a new subtrack, so the published 3.3 results keep their meaning. 3.3
and its batch tool stay unchanged.

| Subtrack | KataGo in the sandbox | Student |
| --- | --- | --- |
| `tutorial3.3` | Yes | Batch tool |
| `tutorial3.4` | Yes | Chat |

Players are named as before, e.g.
`gpt6-astra-high-api-multi-tutorial3.4-gpt6-astra-high-codex-2h`, and the
profiles `gpt6-astra-tutorial3.4-<hours>h` and
`claude-opus-5-5-tutorial3.4-<hours>h` run them.
