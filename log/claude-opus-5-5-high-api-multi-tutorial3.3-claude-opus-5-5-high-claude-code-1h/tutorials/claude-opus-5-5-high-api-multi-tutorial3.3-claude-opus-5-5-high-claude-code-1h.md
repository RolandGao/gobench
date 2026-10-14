# How to win at 9x9 Go against a bot (Tromp-Taylor area scoring, komi 7)

Read this once, then run the CHECKLIST (silently, in your thinking) every move. Your visible answer is always just one move, e.g. `D4`. Your opponents are neural-network bots with good shape that sometimes blunder. Games against them are lost mainly by (1) overlooking an atari against your group, (2) self-atari, (3) letting a weak group get cut off and killed, (4) throwing stones into the opponent's solid area where they die, (5) passing too early under strict scoring. Avoid those and you win.

## 1. Reading the board correctly
- Columns A B C D E F G H J (no I!). Rows: 9 at top, 1 at bottom. The 1st character after the row number is column A, the 5th is E, the 8th is H, the 9th is J.
- Neighbours are only up/down/left/right (never diagonal). E5's neighbours: E6, E4, D5, F5.
- Group = same-colour stones connected through neighbours. Liberties = distinct empty points adjacent to the group.
- Mis-reading coordinates is the most common error. Before deciding, privately write out the rows near the action as coordinate lists (e.g. "row 4: C4=W D4=B E4=B"), find the opponent's last move (from "Recent moves") and list every group touching it with its exact liberties.

## 2. CHECKLIST (every move, in order)
1. **My groups in atari (1 liberty)?** Save the important ones: extend only if the result has 3+ liberties, or capture an adjacent enemy stone to gain liberties. If extending leaves ≤2 liberties and the chase continues (ladder), it is dead - do not run; take compensation elsewhere.
2. **Enemy groups in atari?** Capture them, especially cutting stones or stones whose capture saves or connects my groups.
3. **My groups with 2 liberties** in contact with the enemy: fix them now (connect, extend, make eye space).
4. **Opponent's threat**: what does their last move want next (cut, atari, invade, enclose)? If it threatens a group or a big area, answer it.
5. **Attack**: atari a weak enemy group toward the edge/my strong stones; cut apart two weak enemy groups.
6. **Self-check my candidate**: count liberties of the group my stone joins. 1 liberty = self-atari: never, unless it captures or is a deliberate sacrifice. 2 liberties: make sure the opponent cannot atari into a ladder/net. Also check: does it leave a cutting point the opponent can use immediately?
7. **Read one step deeper**: for my top 2-3 candidates, imagine the opponent's most annoying reply (cut, atari, hane, invasion) and check I still have a good answer. Pick the candidate that survives this test.
8. Otherwise play the biggest strategic move (section 4).

## 3. Tactics and shape
- **Ladder**: chasing a 2-liberty-after-atari group diagonally; it works unless a stone of the chased side lies in the path. Don't run out a working ladder.
- **Net (geta)**: a loose move that encloses a stone; often better than chasing.
- **Snapback / throw-in**: sacrificing one stone so the capturing group is left in atari.
- **Liberty race (semeai)**: when two groups without eyes touch, count liberties. Fill the opponent's OUTSIDE liberties first; the group with more liberties wins. One eye beats no eye.
- **Cutting**: diagonal stones with both connecting points empty can be cut. Close your cutting points before they hurt (solid connection, or a "tiger's mouth" hanging connection). Cut the opponent when both resulting pieces are weaker than yours.
- **Good shape**: hane at the head of two stones; extend from a contact; bamboo joint (two parallel pairs) is uncuttable; avoid empty triangles and pushing the opponent from behind along their wall.
- **Ko**: you cannot retake immediately; play a threat elsewhere first. The "Currently illegal" line shows the banned point.
- **Life and death**: a group needs two separate real eyes. Eyes on the edge/corner are cheap; centre eyes are expensive. Eye-space shapes: straight three or bent three in a row of empty points = kill by playing the middle point; straight four, bent four (L-shape not in corner), and larger spaces = alive. To kill: reduce eye space from outside, then take the vital point. To live: widen eye space, take the vital point yourself. A false eye (diagonal points controlled by the enemy) is not an eye.

## 4. Strategy for 9x9
- The board is tiny: one dead group decides the game. Connected strong stones beat greedy territory.
- **Black**: open E5. Then either block White's 3rd-line stone on the side where it wants to expand, or claim the opposite side (see book below); keep your stones connected to E5.
- **White**: after Black E5, play a 3rd-line point like C4, D3, F7 or G6 (the 3-4 points), or C5/E3. Follow up by building a base along one side and invading/reducing Black's weaker side. If the centre is free, E5 is best.
- Engine-checked opening book (all about even): B E5; W C5 or E3 (3rd-line side middle) or C4/D3. After W C4, Black D3 (blocks the bottom; C6 also fine). After W D3, Black C4. After W C5, Black G4 or G6 (take the opposite side). After W E3, Black E7. Use the same patterns rotated/mirrored.
- Opening moves belong on lines 3-5. First/second-line moves are small unless they save/kill a group or secure a corner eye.
- Black needs **45+** of 81 points (stones + own empty area) to win; White needs **38+**. Black 44 = draw. Count every ~10 moves: who owns which areas, and is my lead safe?
- Ahead: play safe (close cutting points, secure eyes, solid borders). Behind: attack the weakest enemy group, cut, or invade where the enemy is thin (not where they have a wall). An invasion with no room for two eyes and no escape route just adds dead stones; reducing from outside is usually better.
- **Do not invade inside a solid enemy area** (surrounded on 3 sides by strong walls with less than ~6x3 space) — those stones just die and give the opponent free captures.
- Answer contact moves (hane, cut, atari) locally; tenuki only when locally settled and there is something bigger.
- Don't crawl along the 2nd line under the opponent's wall (each crawl gains 1 point while they gain a wall); instead block, hane, or play the biggest open corner/side first. The first player to claim an empty corner (3-3/3-4 area) usually owns it.
- When the opponent plays inside or at the edge of my area, answer it: block on the side that protects my larger area, and try to cut the invader off from its friends so it must live small. Killing an invasion usually wins the game outright.
- Best moves do two jobs: defend my weakness while attacking theirs, or enlarge my area while reducing theirs.
- Boundary moves (late middle game): a hane on the 2nd line that pushes the border into the opponent's side is worth several points; play the biggest boundary first, and the ones that threaten something (sente) first.

## 5. Endgame and passing (strict Tromp-Taylor, no dead-stone removal)
Score = your stones on the board + empty points that touch only your colour. A dead enemy stone left inside your area still counts for the enemy AND makes all empty points around it neutral (worth 0 for you).
- Before passing: **capture every dead enemy stone inside your area** (adding stones inside your own territory costs nothing under area scoring).
- Fill every neutral point (dame) between the colours: each is +1 for whoever fills it.
- Seal borders: no empty point of my area may touch an enemy stone.
- Keep two separate eyes in every group: never fill your own last eyes.
- When filling dame, never fill a point that leaves my own group with 1-2 liberties the opponent can exploit (shortage of liberties); connect first.
- When the opponent passes: count the score literally as the board stands right now (every stone counts where it sits, even 'dead' ones; empty regions touching both colours count for nobody). If I win with that count, pass. If not, continue with useful moves (capture dead stones, fill dame).
- Never pass while: a dame point remains, a dead enemy stone sits in my area, a border has a gap, or any of my groups is in atari. Never resign.
- Do not play inside the opponent's living territory at the end: those stones are just captured (and if left there, they still don't score for you once the opponent removes them).

## 6. Output format (critical)
Do all the checklist thinking silently in your private reasoning. Your visible reply must be ONLY the move itself, e.g. `E5` - no explanation, no words, no punctuation. Any extra visible text makes the reply unparseable and the turn can be lost as a pass.
