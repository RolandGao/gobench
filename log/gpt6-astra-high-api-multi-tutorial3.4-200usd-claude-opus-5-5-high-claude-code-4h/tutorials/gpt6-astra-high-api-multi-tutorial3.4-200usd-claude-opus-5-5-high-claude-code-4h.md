# How to beat KataGo bots at 9x9 Go

Your opponents are neural-net bots that play by instinct with no reading. They make shape mistakes and miss tactics, but punish you hard if you leave a group weak or blunder liberties. Most of your past losses came from (1) a group getting cut off and dying, (2) missing that an enemy cutting stone could be captured, (3) playing small moves (crawling on the 1st/2nd line) while big areas were still open. Fix these and you win.

## 1. Rules that matter here
- Tromp-Taylor AREA scoring with NO dead-stone removal: final score = your stones on the board + empty points enclosed only by your stones. An enemy "dead" stone left in your area still counts for the enemy and spoils your territory. Before the game ends you must actually CAPTURE every enemy stone inside your area.
- Komi 7: Black needs 45+ of the 81 points (44 = draw). White needs 38+.
- Prisoners count nothing. A move inside your own territory costs nothing (only filling your own last eyes is harmful), so when unsure, a defensive move at home is free.
- "Legal moves" includes SUICIDE moves (self-capture is legal). Legal does not mean safe: never play a point where your stone(s) would have 0 liberties unless it captures.
- Never resign.

## 2. Procedure for EVERY move
Coordinates: columns A B C D E F G H J (no I), rows 9 (top) to 1 (bottom). Neighbors are only up/down/left/right. Read each row carefully; a misread board is the worst mistake.
1. Look at the opponent's last move. Which of your groups and which enemy groups touch it? Count their liberties (name each liberty point).
2. Emergency scan, in order:
   a. Can you capture enemy stones that are cutting your groups apart, or are in atari? Do it (capturing cutting stones is usually the biggest move on the board).
   b. Is any of your groups in atari, or at 2 liberties with an enemy move that would atari it? Save it: add liberties (extend toward open space), connect to a strong group, or capture an adjacent enemy group that has few liberties. If extending only leads to 2 liberties again, the stones are probably lost: ladder check (Section 5) and give them up rather than add more stones.
   c. Does the last move cut your stones, threaten to seal a group with no eyes, or threaten to enter your area? Answer it.
3. If nothing is urgent: play the biggest move (Section 4).
4. Verify your chosen move before answering:
   - Count the liberties of the group your new stone joins. 1 liberty = self-atari: reject (unless it captures, or is a deliberate sacrifice). 2 liberties in a fight: check that the opponent can't atari and ladder/net it.
   - Imagine the opponent's best reply (atari? cut? hane?). If it hurts you badly, choose another move.
   - Don't fill your own eye. Don't add stones to a group that is already dead.

## 3. Opening (moves 1-12)
- Black: play E5 first (the best move on 9x9).
- White vs E5: approach on the 3rd/4th line from the side, e.g. C4, G4, D3, F7, C6. Make shape quickly; on 9x9 you need one solid living group plus territory.
- Good: 3rd/4th-line stones, diagonal moves, one-point jumps, knight's moves; hane at the head of enemy stones; blocking the enemy from the open side.
- Bad: stones on the 1st/2nd line early; crawling along the 2nd line (each crawl gains 1 point while the opponent gains a wall); empty triangles; separating your own stones into two weak groups.
- Keep your stones connected. Two weak groups usually means one dies. If the opponent cuts, the usual answer is to make one side strong and attack the cutting stone.

## 4. Choosing the biggest move (middle game)
Priority list:
1. Life-and-death and capturing cutting stones (Section 2).
2. Make your weakest group safe before it is sealed in: extend to open space or secure eye space. A group needs TWO separate real eyes. A group with no eye space surrounded on all sides is dead.
3. Attack the opponent's weakest group so that while it runs you build territory. Attack from the side that pushes it toward your strong stones or the edge you don't need.
4. Big boundary moves: the point where both players' areas meet and the open area is largest. Typical big moves: extending a wall into an open side, blocking the enemy's extension into your side, hane on the 2nd/3rd line at the edge of territories, the "1-2-3 point" that reduces an opponent area by many points.
5. Not big: moves inside your own secure area, moves far inside enemy area that can't live, 1st-line moves while 3rd-line boundaries are open.
Estimate the score every few moves: count points each side surely controls. If you are well ahead, play safe and solid (connect, defend). If behind, look for invasions, cuts and attacks on weak groups.

## 5. Tactics checklist
- Atari direction: give atari from the side that drives the enemy toward the edge or your strong stones, not toward open space.
- Ladder: a stone with 2 liberties, chased with ataris in a zigzag. It works only if the zigzag path toward the edge contains no stone of the runner. If the ladder fails, don't start it (it leaves you full of cutting points).
- Net (geta): instead of atari, play loosely one point diagonally ahead so the 2-liberty stone cannot escape.
- Snapback: if the opponent captures one stone and you can immediately recapture several, allow it.
- Cutting point: a diagonal pair (e.g. your C3, D4 with C4 and D3 empty) can be cut if the opponent gets both points; when the opponent plays one of them, play the other. Two-point jumps and knight's moves can be cut; solidify them when the enemy pushes in.
- Capturing race (semeai): count liberties of both groups. More liberties wins; if equal, whoever plays first wins. Fill outside liberties first, shared liberties last. A group with an eye beats a group without one.
- Throw-in: sacrificing a stone inside the enemy's eye to make it false or to reduce liberties.
- Ko: if retaking is illegal, play a threat the opponent must answer (an atari on a valuable group), then retake.
- Edge groups: a group on the edge can be killed by hane+placement; a 3rd-line group with 6+ points along the edge usually lives.

## 5b. Life and death
- Real eye: an empty point (or a captured-stone point) whose 4 neighbors are all your stones or the board edge, and whose diagonal points are mostly yours: in the center at least 3 of 4 diagonals; on the edge both diagonals; in the corner the single diagonal. Otherwise it is a false eye and does not count.
- One small enclosed eye space is never life by itself. Small single spaces have a vital point: whoever plays it first decides.
  - 3 points (straight or bent): middle point. 4 points: straight four and bent four are alive; square four (2x2) is dead; T-shape four: the center of the T is vital.
  - 5 points: bulky five (2x2 plus one) and cross-five: the central point is vital. 6 points: rectangular six is alive in the open, but in the corner or with few outside liberties it can be killed; "flower six" has a central vital point.
  - The vital point is usually the empty point that touches the most other points of the space.
- Corner and edge spaces are smaller than they look: the 2-2 point (B2, H2, B8, H8) and the 2-1 / 1-2 points are typical vital points. An 8-point corner space can still die if the opponent plays its center first while your outside liberties are short.
- Shortage of liberties: when your group's outside liberties are filled, moves inside its eye space become atari. A group with only 2-3 outside liberties and one eye space needs a defensive move.
- Rule: whenever the opponent plays inside or next to the eye space of one of your groups that is not yet clearly two-eyed, respond there (usually the vital point). Before passing or making a small move elsewhere, make sure each big group of yours has two separate real eyes, or one space so big (8+ points, not in a narrow corner) that it surely makes two.
- To kill: reduce the eye space from outside first (hane, block its extension), then play the vital point. Don't push from inside where it gives the group eyes.
- A group in the center with no base and surrounded on 3 sides must run or make eyes NOW, before the 4th side is closed.

## 6. Endgame and passing
- After borders are settled, play remaining boundary moves biggest first: moves that also threaten something (atari, cut) first, then 2nd-line hanes, then 1st-line moves.
- Fill every neutral point (dame) between your stones and enemy stones: each is worth 1 point under area scoring.
- Check your groups' liberties while filling dame: shortage of liberties can let the enemy atari you. Connect weak points if needed.
- Capture every enemy stone inside your area (even "dead" ones) before passing, unless you already win by the exact count. Then check the enemy area: if the opponent left one of your stones inside it, that's their problem.
- Passing: when the opponent passes, count exactly: your stones + empty regions touching only your color. Black needs > W+7. If you win by that count, pass. If not, keep making useful moves (fill dame, capture dead stones, reduce). If the opponent has not passed, don't pass while one of your groups is in atari, a dame is open, or a dead enemy stone sits in your area.
