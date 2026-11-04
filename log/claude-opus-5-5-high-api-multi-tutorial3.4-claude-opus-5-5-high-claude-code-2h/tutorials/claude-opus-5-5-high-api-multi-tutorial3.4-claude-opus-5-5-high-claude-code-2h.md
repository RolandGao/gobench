# How to win 9x9 Go against these bots

Your opponent is a KataGo network playing instantly by intuition (no reading). It has good shape and a good sense of direction, but it misses tactics: it leaves stones in atari, misjudges ladders and capturing races, and overextends. You beat it by (1) playing SOLID, connected shapes, (2) never leaving a weak group or blundering into atari, (3) punishing its weak stones, and (4) finishing correctly under Tromp-Taylor scoring.

Lessons from past games (these lost games):
- Messy contact fights and cuts that left MY stones split into 2-3 weak groups. On 9x9 one dead group = lost game.
- Pushing/crawling along the opponent's wall (parallel lines of stones). My pushing stones ended up with no eye space and died, while the opponent's wall became territory.
- As White, answering Black's first stone with a contact play (attaching) and fighting in the center. Play the opposite point instead (see §4).
- Missing that a group with 2-3 liberties was about to be captured.
- As Black with a big lead, letting a White invasion inside my area live, while my own scattered attacking stones got cut. Against an invasion: first block it from the open space with moves connected to my wall, then take its eye space; keep my attackers connected.

## 0. How to think (mandatory, every move, in your private reasoning)

There is no clock and careful reading is what wins. Quick intuitive moves lost past games. This tutorial is shown only once, but apply it on EVERY later turn too (later messages contain only the board): do the full procedure fresh each time, even if the move seems obvious. Do all of it silently in your private thinking, never in the visible reply. Every move, work out:
A. **Board list**: each row's stones with coordinates.
B. **Groups**: every group (both colors) with ≤3 liberties: its stones and its liberties listed.
C. **Threats**: what the opponent's last move threatens; what I can threaten.
D. **Candidates**: 3 moves. For each, the opponent's best reply and what follows (read ataris/cuts 3+ moves deep).
E. **Choice**: re-verify the coordinate letter and row, and that it is not self-atari.

## 1. Reading the board without mistakes

- Columns A B C D E F G H J (no I). Row 9 is the TOP line, row 1 the BOTTOM. In a row string like `4 ZBWBZBBBZ`, the chars after the label are A,B,C,D,E,F,G,H,J in order: A4=Z, B4=B, C4=W, D4=B, E4=Z, F4=B, G4=B, H4=B, J4=Z.
- Start each turn by listing (in private thinking) every stone by coordinate, row by row. Work only from this list. Re-verify the coordinate of the move you output against the row string.
- Neighbors are up/down/left/right only (D5's neighbors: D6, D4, C5, E5). A *group* = same-color stones connected orthogonally; *liberties* = distinct empty neighbors of the whole group. List them explicitly; don't estimate.
- Keep a short note of each group's status (strong / weak / dead) in your reasoning and update it each turn.

## 2. Procedure every move (in this order)

0. **Opponent just passed?** Then do the exact count of §6 now and follow the "opponent passed" rule there - do not pass unless the count shows I win.
1. **Opponent's last move**: what does it touch? Recount liberties of every group next to it, mine and theirs. What does it threaten next (atari, cut, enclosing my group, entering my area)?
2. **My group in atari (1 liberty)**: save it if extending reaches ≥3 liberties or capturing an adjacent enemy stone saves it. If it can only reach 2 liberties and keeps getting chased (ladder, §5), don't run; let it go and play elsewhere (or use it as a sacrifice).
3. **Capture**: enemy stones in atari, especially cutting stones that separate my groups - capture now.
4. **My groups with 2 liberties, cutting points, or no eyes**: fix them before the opponent attacks (connect, extend into open space, make eye shape).
5. **Check my candidate move**: count my stone's liberties after it is played (and after captures). If it has 0 liberties (self-capture: legal here, but it just removes my own stones) or 1 liberty (self-atari) or leaves a cut the opponent can use immediately, reject it. Also check: after my move, can the opponent atari something of mine with no escape?
6. Otherwise choose the biggest move by §3.

## 3. Strategy that works

- **Solid shape.** Prefer moves that keep my stones in ONE group: solid extension, diagonal (kosumi), bamboo joint (two parallel one-point jumps), tiger's mouth. Avoid empty triangles and loose shapes the opponent can cut. When in doubt, connect.
- **Cut only when** both of my resulting pieces are strong (≥3 liberties, room to live) and the enemy pieces are weaker.
- **Don't push from behind.** Pushing my stone against an enemy wall gives them territory. After at most 1-2 pushes: hane at the head of their stones (the empty point directly in front of their line), or turn away and take territory elsewhere. "Hane at the head of two stones" is usually strong.
- **Answer contact**: when the opponent attaches to my stone, usually hane on the side facing the edge/my area, or extend solidly. When they hane at me, block (if it's safe — check cutting points) or extend. Don't leave a cutting point behind a hane: if their atari/cut would work, fix it now.
- **Territory on 9x9 is on the 2nd-3rd lines and corners.** Build walls that face open space; keep the opponent's groups separated and small. A simple safe split where my area ≥ needed points (§6) wins.
- **Every group needs two eyes or a big secure edge area.** Never let a group of mine get enclosed in the center. Before tenuki, make sure every group of mine can live.
- **Attack enemy weak groups from the side that also builds my area**, but don't over-chase: securing points while attacking is the goal.
- **Sente first**: moves that force a reply (atari, threats to cut/capture, hane on the 1st/2nd line), then the biggest boundary move. Reply to the opponent's threats when they are real.

## 4. Opening book (strong-engine choices)

**As Black**: play E5. Then answer White's approach:
- W C4 → D3. W G4 → F3. W C6 → D7. W G6 → F7. (Diagonal contact that blocks the approach stone from extending toward the open side.)
- W C5 → G4 or G6. W G5 → C4 or C6. W D3 → C4. W F3 → G4. W D7 → C6. W F7 → G6. W E3 → D7 or F7. W E7 → D3 or F3. W C3 → C5 or E3.
- W attaches (E4, D5, F5, E6): hane around it, e.g. W E4 → D4 or F4; W D5 → D4 or D6; W F4 → E4 or F5; W D4 → D5 or E4; W D6 → D5 or E6.
- Bots often attach right away; main lines: E5 E6 D6, then W F6 → F5 (then W G6 → D7) or W E7 → F5. E5 F5 F4, then W F6 → E6 or W G5 → E6. E5 D5 D4, then W D6 → E6 (then W D7 → C4). E5 F6 E6, then W F5 → F4. Keep my center stones connected and solid; the attaching White stones become a weak group to attack.
- Next: E5 C4 D3 C6 → B G6. E5 C6 D7 C4 → B G4. E5 G4 F3 G6 → B C6. Principle: after White settles one side, Black takes the largest open side.

**As White**:
- vs B E5: play C6 (C4/G4/G6 are equivalent by symmetry). E5 C6 D7 → W C4. E5 C6 D4 → W D7. E5 C6 E6 → W C4 (then B E4 → W H5). E5 C6 C5 → W B5. E5 C4 D3 → W C6.
- If Black attaches to my approach stone, hane underneath toward the edge and keep a low, connected base; never answer by pushing into the center: E5 C4 D4 → W C3 (then B D3 → W C6; B C5 → W B5, then B C6 → W B6, then B C7 → W H5). E5 C4 C5 → W B5. E5 C4 D5 → W D3. E5 C6 D6 → W C7 (then B D7 → W C4; B C5 → W B5).
- Other lines: E5 G4 F3 → W G6. Then: E5 C4 D3 C6 G6 → W D7; E5 C6 D7 C4 G4 → W D3; E5 G4 F3 G6 C6 → W F7. Live solidly on one side; don't fight in the center.
- White's plan: one small secure group on one side, then EARLY start a second group on the opposite open side (3rd-4th line, e.g. H5/G7 area, before Black walls it off) and settle it quickly with a base on the 3rd line. Two small living groups + 7 komi wins; one group that gets enclosed loses.
- vs other first moves, take the diagonally-opposite point, NOT a contact play: B F4 → W D6; B D6 → W F4; B D4 → W F6; B F6 → W D4; B C4 → W F6; B E4 → W E6; B E6 → W E4; B F5 → W D5; B D5 → W F5; B C5 → W F5; B G5 → W D5; B E3 → W E6; B E7 → W E4; B C3 → W D4.
- After that: B F4 W D6 B E6 → W E7; B F4 W D6 B D5 → W C5. B D4 W F6 B F4 → W D6. B F6 W D4 B D5 → W C5; B F6 W D4 B E4 → W E3. B E6 W E4 B D4 → W D3. B E3 W E6 B E5 → W D5 or F5. B E4 W E6 B D6 → W D7; B E4 W E6 B F6 → W F7. (Hane on the edge side of an attaching stone.)

## 5. Tactics checklist

- **Ladder**: a group with 2 liberties after my atari, where each escape gives it only 2 liberties again, zig-zags diagonally. Trace the zig-zag path on the board: if it hits the edge with no friendly stone of the runner in the path, the ladder works (runner dies). If a runner's stone sits on the path (ladder breaker), the ladder fails and the attacker is left full of cutting points.
- **Net (geta)**: if the ladder fails, a loose diagonal enclosing move one point away often captures.
- **Snapback / throw-in**: capturing one stone can be answered by recapturing several if my capturing group then has 1 liberty. Check liberties after capture.
- **Capturing race**: count liberties of both groups (outside liberties first, shared ones last). More liberties wins; with equal outside liberties, the side to move wins. Don't start a race you lose; add liberties or make an eye first.
- **Atari direction**: atari from the side that drives the enemy toward my strong stones or the edge. Don't play pointless ataris that just make the opponent connect solidly; they waste my potential.
- **Eye shapes**: 3 empty points in a row inside a group: the middle point decides life (play it to live / to kill). 4 in a row, or 4 bent in an L: alive. 4 in a 2x2 square: dead. Corner and edge groups need more room than you think; the opponent's 1st-line hane reduces eye space.

## 5b. Standard local answers

- **Opponent hanes at my stone**: if blocking leaves a cutting point they can use with atari, extend or connect instead; otherwise block.
- **Opponent peeps (threatens to cut)**: connect. A cut that splits my stones costs far more than any gain elsewhere.
- **Opponent cuts**: atari the cutting stone only if it then cannot escape (ladder/net works) or it drives it into my strength; otherwise make the weaker of my two pieces strong (extend toward open space) and treat the other as light.
- **Opponent crawls on the 2nd line or pushes into my area**: block in front of it with a connected stone.
- **Opponent invades my area** (the most common way I lost won games): the invader is weak, my job is to keep it from escaping or connecting out while keeping MY stones connected. First block on the side toward its friends/open space (seal it in), with a stone that touches or is diagonal to my own stones. Then reduce eye space from the outside (1st-line hane, vital point). Never play loose attacking stones that the invader can cut off and turn into a second weak group; letting it live small is fine, losing my stones is not.
- **Prevent invasions**: when the boundaries are settled and I have a wide area 4+ rows deep (or an open corner), spend one move reinforcing it on the 3rd line before the bot invades; that's often bigger than another boundary move.
- **Count regularly**: roughly count the points each side surely controls (Black needs 45 of 81, White 38). If I'm ahead, play the safest moves; if behind, I need a fight.
- **Ahead**: simplify - connect cuts, secure weak groups, answer threats. **Behind**: attack the opponent's weak group or cutting point.

## 5c. Endgame order

1. Moves that save or kill a group; cuts and connections. 2. Blocking/hane on the 2nd line at boundaries (the biggest). 3. 1st-line hanes and descents. 4. Fill every neutral point between colors (each is worth 1 under area scoring). 5. Capture all enemy stones remaining in my area. Before any boundary move, check that it does not leave a cutting point or self-atari.

## 6. Scoring and ending (CRITICAL - strict Tromp-Taylor)

- Score = my stones on the board + empty points enclosed ONLY by my color. White gets +7. With no neutral points, Black needs 45 of 81 points to win (44 = draw); White needs 38.
- **NO dead-stone removal.** Enemy stones left inside my area count for the enemy and make the surrounding empty points neutral. Before the game ends, I must capture every enemy stone inside my area (they are free for the bot to play, so expect invasions late in the game; answer them until they are captured or clearly cannot live).
- Playing inside my own territory costs nothing (area scoring). In the endgame, capture dead stones and fill every neutral point (dame) between the colors rather than passing. Never fill my group's last two eyes.
- **Passing**: pass only when all boundary points are filled, no enemy stones remain in my area, and all my groups have two eyes. If the opponent passes, count the board exactly as it is now (stones + one-color-only empty regions); if I win now, pass to end the game.
- **Exact count**: go row by row (privately); for each row tally (Black stones + empty points in Black-only regions) and (White stones + empty points in White-only regions); sum, add 7 to White. An empty region touching both colors counts for nobody.
- **If the opponent passes and I'm NOT winning, don't pass back while a useful move exists.** Under area scoring, stones I play inside the opponent's area cost me nothing even if captured (prisoners don't count). The bot sometimes passes without capturing them: each surviving stone of mine counts +1 for me and turns the empty points next to it neutral (they no longer count for the opponent). So keep placing stones inside its biggest empty regions (where they have the most liberties, not self-atari), and keep doing it while it passes. Fill any neutral points first. If no neutral points remain and every move inside its area would be self-capture, then the result can't change: pass (never fill my own eyes). Same danger in reverse: always capture enemy stones in my area before passing.

## 7. Output (strict)

Your visible reply must be EXACTLY one entry from Legal moves (e.g. E5) and nothing else: no explanation, no reasoning, no markdown, no extra lines. Any extra text can make the answer unreadable and count as an illegal move, which loses the game. All analysis stays in private thinking. This applies to every turn.
