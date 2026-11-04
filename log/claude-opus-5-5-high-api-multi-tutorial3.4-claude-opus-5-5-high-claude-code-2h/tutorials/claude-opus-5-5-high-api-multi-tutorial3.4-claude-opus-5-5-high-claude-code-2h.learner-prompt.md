# Track 3.4: tutorial distillation

Write a tutorial that makes another language model play 9x9 Go as strongly as possible. Your only output is /workspace/tutorial.md. When this learning period ends, its contents are cut to the first 5000 tokens of the tiktoken o200k_base tokenizer and frozen. Nothing else in your workspace is kept or seen by the reader.

## Evaluation
The reader is claude-opus-5-5 at high effort, without tools. It plays complete games against a ladder of KataGo opponents, one move per turn, with no game clock. Each game is one multi-turn conversation. Your tutorial is placed at the start of the conversation's first user message:

```
Before the game prompt, here is a tutorial written to help you play this 9x9 Go game.

<tutorial>
<your tutorial>
</tutorial>

<move prompt>
```

Later turns contain only the move prompt. If the conversation grows past 250,000 tokens, it is cleared and the next turn again starts with the tutorial. An example move prompt:

```
You are playing Black in an ongoing 9x9 Go game against another bot. It is Black to move.

Rules: White komi 7.0, positional superko, passing allowed, self-capture of stones legal. Resolve captures by first removing opposing groups with no liberties, then removing any friendly groups with no liberties. Self-capture remains subject to positional superko. Resigning loses immediately. Two consecutive passes end the game. A draw is worth 0.5 points. Scoring uses strict Tromp-Taylor area scoring with no dead stone removal.

Coordinates: columns A B C D E F G H J from left to right (I is skipped); rows 9 through 1 from top to bottom. B = Black, W = White, Z = empty.

ABCDEFGHJ
9 ZZZZZZZZZ
8 ZZZZZZZZZ
7 ZZZZZZZZZ
6 ZZZZZZZZZ
5 ZZZZBZZZZ
4 ZZZZZZZZZ
3 ZZWZZZZZZ
2 ZZZZZZZZZ
1 ZZZZZZZZZ

Recent 5 moves (oldest to newest): B E5, W C3

Currently illegal because of ko/superko: none

Legal moves: A1, B1, C1, D1, E1, F1, G1, H1, J1, A2, B2, C2, D2, E2, F2, G2, H2, J2, A3, B3, D3, E3, F3, G3, H3, J3, A4, B4, C4, D4, E4, F4, G4, H4, J4, A5, B5, C5, D5, F5, G5, H5, J5, A6, B6, C6, D6, E6, F6, G6, H6, J6, A7, B7, C7, D7, E7, F7, G7, H7, J7, A8, B8, C8, D8, E8, F8, G8, H8, J8, A9, B9, C9, D9, E9, F9, G9, H9, J9, pass, resign

Legal moves is authoritative for the current position and already accounts for ko and positional superko.

Your entire final answer must be one entry copied exactly from Legal moves.
Write that entry on a single line, then end the response immediately.
```

## Your environment
You have 7200 seconds of wall time. Read /arena/clock.json for a live deadline. The runtime stops at the deadline with no extra time, so save the tutorial early and keep it updated. Python3, g++, and make are available; build tools in /workspace. There is no internet access. Your agent has exclusive use of 1 physical CPU core with 2 logical CPUs, 4096 MiB RAM, 2048 MiB writable storage and 256 processes/threads; there is no GPU or swap. Subagents are disabled.

- `/arena/bin/tutorial-tokens [FILE]` counts FILE (default /workspace/tutorial.md) with the fixed tokenizer.
- KataGo and every network of the evaluation ladder are available read-only. /arena/ladder.tsv lists each ladder player with its network file, Elo and speed, and explains how each opponent is configured.
- Students: in Python, `from student import Student, move_prompt` (the module is /arena/python/student.py, already on PYTHONPATH). A student is the evaluation model (claude-opus-5-5, high effort) in the exact evaluation harness: one multi-turn conversation that keeps its own reasoning between turns, with no tools and no system prompt. It sees only the messages you send, exactly as written. Nothing is prepended or cut, so to test your tutorial as evaluation will, send the tutorial wrapper shown above with a move prompt, and keep the tutorial within the token limit yourself.
  - `Student(name)` creates a student or reattaches to an existing one by name (1-64 letters, digits, `_` or `-`); `Student()` picks a name, available as `s.name`. Students live on the arena host for the whole learning period, so any later process can reattach.
  - `s.send(text)` sends one message and returns at once. A student holds one message at a time: sending while its reply is pending raises `StudentError`.
  - `s.reply()` never blocks. It returns the reply to the latest send, or None while that reply is pending, and raises `StudentError` if the send failed. Replies are not checked or retried: a reply is whatever the model wrote.
  - `s.close()` ends a student; a pending reply is discarded.
  - `move_prompt(moves)` returns the exact move prompt evaluation sends after `moves`, a list from the empty board, Black first, such as ["E5", "C3"] or ["B E5", "W pass"]. The referee computes it; it costs nothing.
  - A student ends when its conversation reaches 250,000 tokens. The reply that reaches the limit is delivered; after that `send` raises and you need a new student. Students are never reset.
  - Transcripts are in /arena/students/<name>.md, updated as messages are sent and answered. /arena/students/cost.json shows student spending.
  - Student messages cost at most $50 in total for this learning period. When spending reaches $50, replies still pending are discarded (their cost still counts) and `send` fails, so plan how to spend it. You can create as many students as you like and have them reply at the same time. A student is a multi-turn conversation: earlier turns are cached, so sending several messages to one student is usually faster and cheaper than sending each message to a new student.
  - If it helps, you can build batching from these primitives. For example, test many positions by giving each of several students a share of them and, from a script, polling each student's `reply()` and sending it its next `move_prompt` when the reply arrives. This is only an option; use the students however you like.
  - Student replies use your wall time, and their cost counts as learning cost.

These instructions are also in /arena/instructions.md.
