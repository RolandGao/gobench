# 9×9 Go: win the board, not the last exchange

You have time to think. Use concrete reading rather than a plausible Go proverb. Your main advantages are exact liberty accounting, checking the opponent's strongest reply, and correct area-score endgame. Your final answer must be only one legal move coordinate (or `pass`). Never resign: playing on cannot score worse than resigning.

## 1. Reconstruct the current position

The displayed board is authoritative; do not carry forward an imagined board from earlier turns. Columns are **A B C D E F G H J**, with no I. H and J are adjacent. Rows increase upward. Only orthogonal neighbors connect stones or supply liberties; diagonals do neither. Z is empty.

Before choosing a move:
1. Locate the last move and what it actually changed: ataris, cuts, connections, eye space, territory boundaries.
2. Scan the WHOLE board, not just near the last move. Silently identify every chain on BOTH sides with only 1–3 liberties, especially large chains far from the latest action. For each endangered chain, enumerate its **distinct empty neighboring coordinates**, not the number of empty edges. Two stones sharing a liberty have only one liberty there. Prioritize chains with 1–3 liberties, and unsettled large groups. Also scan enclosed groups with more liberties: many liberties buy time but do not provide life. A large chain on the edge may have five liberties in a single narrow eye space and still be killable.
3. Distinguish a **chain** (physically connected stones) from a strategic group (several chains hoping to connect). A diagonal or one-space jump can be cut. Never count an unverified connection as a liberty or an eye.

For a hypothetical move, place its stone, remove all adjacent opposing chains whose final liberty was filled, then recompute friendly connections and liberties. Capturing can make an apparently suicidal move safe. Conversely an extension may add no liberties because all its neighbors are occupied. Self-capture is legal here but almost always bad; legality is not safety. The supplied legal list decides ko/superko legality in the real position.

## 2. A reliable decision loop on EVERY turn

**A. Tactical triage.** Look for both sides' immediate captures, threatened important groups, double ataris, cuts, connections, and life-and-death vital points. If a large group can be captured next move, settle that before an ordinary territorial move. Do not mechanically save every ataried stone: a disposable stone may be less valuable than initiative, territory, or a larger capture. An enemy chain in atari may already be unable to escape, so its capture need not be urgent. Before reflexively saving one ataried stone, check whether a vital point kills or saves a much larger neighboring group. A decisive life-and-death move often is NOT an atari and may be far from the last move.

**B. Generate a small serious candidate set.** Do not stop after finding one plausible reply to the last move. Name your largest unsettled group and theirs; check whether attacking theirs is bigger than saving a small piece of yours. Usually 3–5 moves: the best defensive move, the strongest forcing/cutting move, and the biggest territorial/development move. In a fight, include connecting, extending, capturing an adjacent attacker, and counter-atari; the obvious extension is not necessarily best. Consider playing elsewhere if the opponent's threat is small or ineffective.

**C. Read adversarially.** For each candidate, explicitly test the opponent's strongest reply, not just the reply you hope for. Check their capture, atari, cut, connection, eye-stealing move, and counterattack. Continue forcing sequences until both sides are stable enough to evaluate; three plies are a minimum sanity check, not a limit. Recount liberties after every capture or connection. If a variation fails, discard it rather than repeatedly rediscovering it. Compare final resulting positions, not how attractive the first move looks.

**D. Evaluate globally.** Prefer a move that accomplishes two things: protects your group while attacking theirs; takes territory while reducing theirs; connects while cutting. Value actual secure area and viable groups over vague influence or stone count. A wall has value only if it makes territory, supports an attack, or prevents an invasion. Keep your important groups connected and hard to attack.

**E. Final blunder check.** After placing the chosen move mentally, ask: “What is the most damaging legal move they can play now? Can they capture or cut me? Did I leave another group in atari? Am I strengthening an already safe group while losing an unsettled one?” Re-read the chosen point's orthogonal neighbors and resulting chain liberties on the actual board; verify legality. Then output only that entry.

Allocate thinking to decisive uncertainties. Do not spend all your effort listing the whole board or narrating easy opening choices; spend it reading the relevant fight precisely.

### Worked triage: don't cash in a small capture while a large kill disappears

White to move (`.` is empty):
```
  ABCDEFGHJ
9 ..BW.W.W.
8 ..BWW.WBB
7 ..BBWWB..
6 .BBWBBBW.
5 .BWWB.WBW
4 BWWBBWBB.
3 .W.WBWWW.
2 ..WBBW.W.
1 ....BBW..
```
Black G4–H4–H5 has just one liberty, J4: an obvious three-stone capture. But Black's much larger chain D2/D4/E1/E2/E3/E4/E5/E6/F1/F6/G6/G7 has exactly **{D1, F5, H7}** as its liberty set. **H7** blocks this chain's escape/connection to the upper-right Black stones. Capturing at J4 first lets Black H7 rescue that much larger chain.

Read capture effects carefully: after White H7, Black F5 captures White G5, so the large Black chain's liberties become {D1,G5}, not merely {D1}. White J4 then attacks the other Black chain, whose last liberty is now G5. Black G5 joins both chains but leaves only D1, where White captures them all. Black D1 instead is met by G5, capturing the small chain while keeping the large one trapped. The lesson is to audit the WHOLE large chain and close its crucial escape before taking an already trapped smaller target.

## 3. Avoid the solid-looking bad move

A frequent mistake is to make a locally safe connection or extension that answers no serious threat, while missing a large active move. **Require a concrete reason for defensive moves.** Before connecting at a gap, simulate the opponent cutting there. Can the cutting stone survive? Does it actually endanger either side, or are both friendly chains independently safe? If the cut is ineffective, leave the gap and take territory or initiative. Do not connect merely because it looks tidy.

When several groups need attention, distinguish:
- **Important unsettled group:** several stones, meaningful territory, or essential cutting/connecting function. Give it eyes, a base, or a genuine escape route.
- **Light/disposable stones:** an isolated probing stone or a few stones without territory. Don't let saving them dictate the whole game. Compare abandoning them with using the move to secure a larger group or attack.
- **Already safe group:** two eyes, a secure connection, or abundant uncontestable eye space. Additional strength here is low priority.
- **Already dead group:** cannot make two eyes or escape even with another move. Don't keep investing without a specific tactical payoff.

For an unsettled group, extending toward space for eyes is often better than tightening its connection in the center. For attack, include **hane, attachment, blocking escape, and eye-space reduction**, not just atari. Compare which direction of play develops YOUR territory and restricts THEIR space. Do not push repeatedly against a strong enemy wall from behind; extend into open space instead.

Two examples (all unshown points empty; colors and shapes matter, not these particular coordinates):

**Don't save the small stone at the expense of the main group.** White to move:
```
  ABCDEFGHJ
7 .........
6 ...B.B...
5 ...WBW...
4 ....BWW..
3 ....B....
```
White D5 has two liberties and is separated from White F5/F4/G4. Automatically extending D5 to C5 saves a small stone but lets Black G6 restrict the important right-hand group. White **G6** instead develops the main group while leaning on Black F6; White can afford to leave D5 light. A stone being attacked does not make its defense the largest move.

**Don't hug the enemy wall when you can take the open side.** Black to move:
```
  ABCDEFGHJ
7 .....W...
6 ....BWB..
5 .....WB..
4 .....WW..
3 .....B...
2 ...B.....
```
Black E6 faces the strong White F-file chain. Black **C6** develops the vast open left side and gives E6 room; E5 is a cramped extension along the enemy wall. The center coordinate is not a goal in itself. The value of a move is the space and options it creates.

**Use your strength to claim area, rather than endlessly reinforcing it.** Start a rough score estimate in the middlegame, not only after the board is full. If your stones form a large solid central blob but the opponent is taking the edges, you are not necessarily winning. Identify where your wall can gain territory NOW. In every non-emergency position include a candidate on the largest still-open boundary, even if it is unrelated to the last move. Do not award the opponent an entire side merely because they have a few stones there.

**Low opposing stones are targets, not established territory.** White to move; all unshown points empty:
```
  ABCDEFGHJ
9 B.B......
8 ..B..B..B
7 ...W.W...
6 ...W.....
5 ...BW....
4 ......W..
3 ..W......
2 .....B...
```
White **G8** uses the nearby F7 stone to pressure Black F8 and expand into the loose top-right position. Simply joining D7 and F7 with E7 is safe-looking but unnecessary: it adds strength without making comparable territory or exploiting Black's weak stones. Early second-line moves are usually small on an EMPTY board, but a contact or wedge on the second line can be enormous once there are nearby stones. Look for these opportunities instead of treating every low enemy stone as a finished boundary.

## 4. Capturing tactics: liberties are the currency

**Atari is one liberty, not two.** Capturing an enemy chain requires filling its last liberty. For your chain in atari, consider (i) extending, (ii) capturing an adjacent enemy chain, (iii) connecting to another friendly chain, (iv) counter-atari with a genuinely forcing continuation, and (v) sacrificing. A move that merely postpones capture one turn while adding stones to the doomed chain is usually worse than letting it go.

**Self-atari check:** if your candidate leaves the newly formed friendly chain with one liberty, assume the opponent captures it. Accept this only if you have verified a favorable sacrifice, snapback, or other concrete payoff. A move can atari the opponent and still lose immediately to their capture of your attacking chain. Never omit this check for a tempting cut or eye invasion.

**Two liberties demand reading.** For a target with liberties x,y, test x → their y and y → their x. After the extension, count the new chain's liberties including every friendly chain it joins. Often only one order works; sometimes neither works, because the target escapes or captures an attacker. Also check a net or a move that blocks its escape without giving atari. Don't chase a chain into open space one atari at a time and give it a strong wall for free.

**Cutting stones matter more than isolated stones.** A single stone separating two large groups can be worth more than several harmless edge stones. Before cutting, verify your cutting stone can survive or gain compensation. Before connecting, ask what happens if the opponent actually cuts: sometimes each side is safe and defending is unnecessary.

**Ladders:** alternate the forced ataris and escapes all the way to the edge or a ladder breaker. Read the actual coordinates; do not assume a ladder works from its initial shape. A friendly stone near the path can let the chased group connect or gain extra liberties. If uncertain, prefer a solid net or another plan over starting a disastrous ladder.

**Nets:** restrict escape liberties from a distance. A net can capture without immediate atari. Test both exits and any cutting/countercapture resource. **Snapback:** after you capture a small chain, the capturing chain may have only one liberty and be immediately recaptured. Conversely, sacrificing one stone can arrange such a recapture. Always inspect the liberties of the capturing chain.

**Semeai/capturing race:** count distinct outside liberties of the relevant chains, shared liberties, eyes, and approach moves. Do not simply compare stone counts. Filling an outside liberty usually beats filling a shared liberty, since a shared liberty also belongs to your chain. But captures, eyes and required approach moves can reverse the simple count: verify the move sequence. Don't start filling shared liberties in a stable seki unless you have proved you win the race.

**Atari is not automatically sente.** The opponent can ignore a threat to a small/dead chain, capture your attacking chain, or make a larger threat. Avoid gratuitous ataris that force useful enemy connections. An attack should profit even if the target lives: territory, separation, or a strong attacking position. Don't sacrifice your own safety trying to kill everything.

## 5. Life, eyes, and invasions

A group is unconditionally safe if it has two separate true eyes that the opponent cannot eliminate. An empty point is not an eye merely because friendly stones are nearby: its orthogonal boundary must be secure, and the surrounding chains must not be capturable. For a simple one-point eye, hostile diagonals are warning signs: two hostile diagonals inside the board, or even one at an edge/corner, can make a false eye. Inspect the actual capture possibilities rather than treating this as an unconditional formula.

One large eye space is not automatically two eyes. Ask: “If they play the vital point first, can I still form two independent eyes?” If both players want the same point, it is urgent. In standard fully enclosed shapes, straight/bent three and the T-shaped four have a killing central point; a square four cannot make two eyes by itself; straight four normally lives. External liberties, incomplete boundaries, ko and adjacent weak chains can change these results. **Read the shape you actually have.**

For an unsettled friendly group, prefer a move that makes two eyes or connects to a truly safe group. If it has no room for eyes, escape toward open space before being sealed in. An attack often works by denying the enemy a base and sealing it against the edge. Yet when your own groups are weak, strengthen them before extending an attack.

An invasion must have a realistic route to **two eyes, escape, connection, or a profitable sacrifice**. Don't place a lone stone deep inside solid enemy territory merely because the point is empty. First find the weakest boundary or narrowest surrounding group. Reduction from outside is usually safer than an unsupported deep invasion. Conversely, don't accept a huge enemy framework as finished territory: invade or reduce while there is room, not after every entrance closes.

When an opponent invades your area, contain it and keep your boundary strong. If it can live small, taking a strong outside wall and the remaining territory may be best; don't ruin your position with an impossible kill. If it truly cannot make two eyes or escape, avoid unnecessary chasing while there are larger moves, but eventually physically capture it before scoring.

## 6. 9×9 strategy and opening

This is not 19×19: the center is close to every corner, fights interact immediately, and a large group dying usually decides the game. Start with efficient influence and territory; don't scatter four disconnected corner groups. Solid connections, bases, and central access are valuable. Third-line moves tend toward territory and bases; fourth-line moves toward influence. First- and second-line opening moves are generally too small unless tactically justified.

On an empty board as Black, **E5** is an excellent default: it supports every direction. Alternatives such as D4 can work, but there is no need to improvise a weak edge opening. Against Black E5, White **C4** (or its symmetric equivalents) is a strong default, developing a side with central access. Against Black D4, White **F6** is a sound response. If the opening is Black E5, White C3, Black **E3** or C5 develops a connected central framework while limiting White; don't automatically scatter to G3. Rotate or reflect these patterns as needed. These are initial defaults, not a fixed sequence. After contact, read the position. Do not follow a memorized joseki through a changed surrounding position.

Develop toward the largest open area while keeping existing groups viable. Corners and sides are easiest to enclose; the center ties them together. One-space jumps and small knight's moves are efficient in open positions, but become cutting targets under pressure. When weak, choose a solid connection over a thin expansion. When strong, don't overconcentrate by adding stones that secure nothing new.

When opposing chains run side by side, examine BOTH open ends. Turning around an end with a hane or extension can claim a whole side and deny the opponent a base; reinforcing the middle of an already strong wall often gains nothing. First- and second-line contacts or extensions can be large boundary moves once stones are nearby, even early in the game.

Useful positional questions:
- Which important group is weakest on each side? Can I attack theirs while strengthening mine?
- Where is the largest boundary that either player can claim?
- If I play elsewhere, can they really take or kill what they threaten?
- Can I force them low while building useful outside strength, rather than crawling on the second line myself?
- Does my move establish a base, deny a base, divide their stones, or secure a meaningful region?

Komi is **7 points**. Black needs more than a nominal half-board; White can win with less area. Don't use this to force reckless Black attacks or passive White play: take the largest sound moves. Once comfortably ahead, reduce variance by connecting, living, and blocking realistic invasions. If behind, seek real weaknesses, complications, cuts or ko—not a sequence of harmless moves in your own territory.

## 7. Area scoring, cleanup, and passing: essential in this ruleset

The final score is **Black area − White area − 7**. Area = stones on board + empty regions bordered exclusively by that color. Board edges help enclose a region. An empty region touching both colors counts for neither. Prisoners are NOT separately counted. Dead stones are NOT automatically removed.

Consequences:
- Filling a safe point already in your territory normally changes one territory point into one stone point: **zero net area**, provided life and boundaries remain intact. Therefore safe defensive/cleanup plays inside your territory do not incur the ordinary Japanese-territory-scoring cost. But they still spend a turn that could take a contested point elsewhere.
- A safe move on neutral dame usually gains one stone point; fill available safe dame before passing. Check that filling it does not put your group in atari or break seki. A dame can also create a shortage-of-liberties tactic, so watch both sides' chains.
- Capturing a dead invader matters! An unremoved opposing stone counts for them and can prevent adjacent empty space from counting for you. Securely surround and **actually capture** dead enemy chains before the game ends. Don't assume “obviously dead” stones will disappear. If they cannot escape, prioritize contested points first, then clean up.
- Don't rescue a hopeless dead chain at the cost of a larger live group. However, while it remains on the board it may still offer ko threats, cuts, or practical resistance.
- Never fill a point whose orthogonal neighbors are all in the SAME friendly chain merely to connect or gain liberties: it does neither. It may be a vital eye. Preserve two eyes; avoid self-capture.

Near the end, estimate the score by counting each secure region once: its living stones plus its enclosed empties. Treat unsettled areas conservatively; don't count a framework as already owned. When all 81 points belong to someone, Black needs at least **45** to win (45−36−7 = 2); 44–37 is a draw. If there are neutral points, use the actual area difference, not that shortcut.

Compare endgame moves by the **swing** between your playing there and the opponent playing there, and whether the sequence retains initiative. A first-line boundary move can be larger than a useless central reinforcement. Block boundary leaks and exploit cuts before filling safe interior territory. Sente means the opponent suffers a real loss by ignoring your move; do not count a harmless atari as a forcing endgame gain.

**Winning-pass exception:** if the opponent just passed, first calculate the exact score of the CURRENT board, with every stone still present. If you are ahead, `pass` wins immediately: take the guaranteed win even if unsettled groups, dead stones, or extra points remain. Do not substitute expected eventual territory or remove dead stones mentally. For this calculation, count your stones and only empty connected regions touching your color but not theirs. Your own unremoved dead stones still count for you and may keep enemy empty space neutral. If the current score is losing, or you cannot verify it, continue with useful moves rather than automatically passing back.

For an ordinary pass (when not taking a verified immediate win), verify:
1. No profitable capture, tactical rescue, invasion/reduction, or boundary move remains.
2. No dead enemy stones still need removal from your territory.
3. No safe neutral points remain worth claiming.
4. Group status and the exact current area count are understood.
An opponent's pass is not proof the board is finished. If they pass prematurely, take the free useful move. If the position is truly finished, pass rather than randomly filling your territory or killing your own group. If behind, try viable complications before accepting the result; if no useful move exists, pass rather than resign.

**Late losing-position mode, especially after an opponent's pass:** if ordinary gains have run out, do not concede merely because your remaining invading stones are strategically dead. Try to improve the exact CURRENT area difference while preserving your living groups:
1. Take profitable physical captures and boundary gains.
2. Put a legal, non-self-capturing stone in the **largest opponent-only empty region**, preferably with several liberties. Your stone counts for you and makes the remaining empty space touching it no longer exclusively theirs. One unremoved stone can therefore invalidate a whole territory region, not just gain one point. They must physically capture it.
3. If those regions are gone, occupying neutral empty points can still add one point each, **including space around your doomed invading groups**. Don't mentally remove your own dead stones or refuse every extension merely because it cannot make two eyes. These are practical last chances in a losing position, not unconditional-life claims.
Recompute after each response. If they capture correctly, try another available scoring move; a changed board may permit a new intrusion. Avoid self-capture, filling your own safe territory for zero gain, or destroying your living groups. If they pass while your exact current score is winning, pass immediately. If you are still behind and a legal move can improve that score, keep trying. Pass when no useful possibility remains.

## Compact reminder

**Read board → check chains/liberties → identify urgent groups → compare a few candidates against strong replies → count resulting secure area → one last capture/cut check → output exactly one legal move.**
