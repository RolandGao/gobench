# 9×9 Go: a calculation-led playing guide

Think privately, then output exactly one legal entry. Never resign. Use the current board as ground truth, not your earlier imagined continuation. Columns are A B C D E F G H J: H and J are adjacent. Only orthogonal stones connect. Your aim is winning AREA, not saving every stone or making your shapes look solid.

## Select the move, not the story

Start each turn with a **fresh tactical scan of the printed board**. Earlier liberty counts and life/death conclusions expire when surrounding stones change. Do not carry forward “that enemy group is doomed” while filling the liberties of the group surrounding it. In a crowded fight, reconstruct the exact liberty sets of BOTH sides before proceeding.

On each turn, first ask: **What is the strongest move the opponent could make if I passed?** This reveals real emergencies. Then compare your best defense with your strongest active move and the largest whole-board move. Do not decide that a local answer is compulsory merely because the opponent played nearby. Conversely, a quiet cut or sealing move can threaten far more than an atari.

Use a short factual ledger for the important groups: connected stones, distinct liberties, eye space, escape routes. Trace the whole chain, not just its last stone. Explicitly list liberties when there are four or fewer. Also inspect large eyeless groups even with many liberties. Distinguish **alive**, **can live if attacked**, **unsettled**, and **dead**. Do not treat “can live if attacked” as requiring another move now.

Generate about four candidates, then calculate the best two carefully:
- Captures, countercaptures, atari defenses, double ataris.
- Empty junctions adjacent to two friendly chains (connect) or two enemy chains (cut); shared liberties between opposing groups.
- Eye-making/eye-stealing points, blocks of escape, hanes at the head of contact chains, and outward jumps.
- The largest open area, invasion/reduction, or territorial boundary move elsewhere.

For each candidate, challenge it with the strongest opponent reply, especially a counter-atari, cut, escape, or tenuki (playing elsewhere). Actually put the stones on the mental board and recompute captures and liberties. Read forcing sequences to a stable result; never stop at “I give atari” or “I capture a stone.” Check what happens NEXT. Each candidate starts from the same actual board. Track its added stones and removed groups separately; never mix variations. If a line becomes inconsistent, restart it from the actual board. Prefer a short correct calculation to a long speculative narrative.

Apply the SAME standard to active and passive moves. Don't reject a hane as “thin” because of an unverified hypothetical cut while accepting a solid extension without reading the opponent's sealing reply. Don't exchange a certain connection-and-containment benefit for speculative territory that assumes all your groups live.

Before committing, test your chosen move once more: can the opponent capture a major group, force a decisive cut, seal an eyeless group, or steal its last eye? Can you punish the opponent's best reply? Choose for the resulting board, not for a proverb.

## Tactical mechanics

Liberties are a SET of distinct orthogonally adjacent empty intersections. Shared liberties count once. Edges aren't liberties; diagonals aren't connections. Simulate a move by placing it, merging friendly chains, removing enemy chains with zero liberties, then removing your own zero-liberty chain. Recount AFTER captures. An apparent suicide may capture; an apparently safe capture may be snapback. The supplied legal list is authoritative for the current position, including superko.

In atari, consider capture, connection, extension, counter-atari, or sacrifice. Extending a doomed group can just increase the loss. A two-liberty extension may still be laddered. Follow a ladder to the edge or a genuine breaker; do not assume it works. Nets can be better than successive ataris.

Do not give gratuitous ataris: they often make the enemy connect, escape, and strengthen. Before atari, ask whether a quiet block, net, cut, or eye-stealing placement is stronger. Before accepting a sacrifice, count the capturing group's resulting liberties and check immediate recapture.

In a capturing race, account for outside liberties, shared liberties, approach moves, eyes, and possible connections. Usually fill outside liberties first. The shared-liberty count alone is not enough; read the final captures exactly. Capture can add liberties and reverse the race. Do not blindly fill a shared liberty in seki (mutual life).

A diagonal pair or one-space jump is only effectively connected if the actual cut can be answered. But if both bridging points work, solidifying the connection immediately may waste a turn. Cuts are worth playing when they separate vulnerable groups and your cutting stones can survive or be profitably sacrificed. Cutting stones may be far more valuable than their number.

**Two ways to safety (miai):** Low liberty count means READ, not automatically defend. If a two-liberty group can safely connect to a living chain at either liberty, the opponent cannot deny both in one move; answer at the other if attacked. Similarly, a threatened peripheral stone need not be saved now if you can still save it after the threat. Distinguish “eventually I will connect” from “I must connect this turn.” Check countercaptures and the safety of the destination chain before relying on this.

If recapture is forbidden, make a sufficiently large ko threat or take compensation. The opponent need not answer an inadequate threat. Never output an illegal recapture.

## Fight for life and profit

Two secure, separate eyes mean life. Two adjacent empty points are ONE eye region, not automatically two eyes. A hole is a false eye if a surrounding chain can be captured and the opponent can then occupy it. Inspect diagonals of small eyes, boundary-chain liberties, and placements/throw-ins inside larger spaces.

**Eye space must be secured against the opponent moving first.** Before giving a group territorial credit, identify where its two eyes will be, and test the opponent's best invasion of that space. “The corner is open, so I can make eyes there” is insufficient. A first-line move that secures the boundary of the ONLY second-eye space can be worth an entire group, not one point. Before strengthening an already-defensible group elsewhere, inspect this boundary.

A common pattern: you have B2, enemy C2, and your unsettled side group reaches toward the lower-left corner. Do not assume A1–B1–A2 are safely yours. Compare YOUR B1 with ENEMY B1 and follow the ensuing C1/A2 continuations. The low block may preserve two eyes, while letting the opponent underneath can leave only one eye or a ko. Rotate/reflect this idea to every edge. It is a candidate-generation pattern, not an automatic move: the surrounding stones decide.

An eyeless wall is not alive just because it is large. On 9×9 even a chain spanning the board can die. Identify where its two eyes can actually be made, or how it connects to safety. Close the enemy's last route to eye space; preserve your own before being sealed in. Don't alternate between two weak groups if connecting them or sacrificing one gives a better result.

Do not keep crawling alongside a stronger chain while it turns around your head. Consider hane, countercut, outward extension, or sacrifice before confinement is complete. Hane at the head of two or three enemy stones is an important candidate, provided you can handle the opponent’s cut. For example, your E7 below enemy D8–E8 suggests considering F8 rather than only F7; letting the enemy take F8 then G7 can seal your whole group in. Read, don't apply mechanically.

Connections that also block an enemy escape are often decisive. Before surrounding an enemy group, check whether it can extend through the gap between your stones and join its main army. Close the gap if that connection would make it unkillable.

Attack to gain territory, strength, separation, or sente—not necessarily to kill. Don't chase an easily living group while weakening your own. Attachment often strengthens the contacted enemy; use it when the forcing exchanges help YOU settle or exploit liberties. Accept profitable sacrifices. Saving a peripheral stone can be much smaller than taking an open side or protecting the main group.

## Whole-board judgment

On 9×9, center and sides interact immediately. Black E5 is a good default first move; D4/E4 and symmetric central points are also sound. Against a central opening, White can start around C4/D4 or a symmetric point. These are suggestions, not a move script. Third-line stones make bases and territory; fourth-line stones fight for central access. Avoid early first/second-line crawling and thinly scattering independent groups in every corner.

Don't finish a safe local shape while the opponent takes a huge open region. Always compare local gain with the best move elsewhere. A framework is not territory until invasions can be handled. An invasion needs eyes, connection, a capture, or useful concessions; otherwise reduce safely from outside. A wall's influence must eventually become territory or a profitable attack.

Count broadly during the game, carefully near the end. Include komi. Ahead: simplify, maintain connections and eyes, don't launch a needless risky kill. Behind: seek the largest realistic invasion, cut, or life-and-death chance before the opponent seals everything. Playing only small safe moves while clearly losing is not a winning plan. A peripheral sacrifice is fine; sacrificing the central group to save its tail is not.


## Worked 9×9 decisions

These are training positions, NOT the current game. Apply the reasoning to rotations/reflections and different stones; do not memorize a coordinate as universally good. In these diagrams B=Black, W=White, Z=empty, and columns skip I.

### A. A low move can be a whole group's life

White to move:
```
  ABCDEFGHJ
9 ZZZZZZZZZ
8 ZBBBZZZZZ
7 ZBWWBBZBZ
6 ZBWZWBBWZ
5 ZWZWWBWWZ
4 ZZZWBBWZZ
3 ZZZWBZWZZ
2 ZZZWBBBWZ
1 ZZZZZZZZZ
```
**H1**, not the reassuring C5 connection. The right-side white group has not secured two eyes. Its lower-right corner is contested: Black H1 underneath H2 destroys crucial eye space and can leave White dependent on a ko or only one eye. White H1 secures the boundary before Black can invade underneath. H3 connects stones but does not secure the same boundary; connection alone is not life.

Meanwhile the left C6–C7–D7 chain has two liberties, C5 and D6, both offering connections toward White's strong left-side chain. If Black C5 gives atari, White D6 joins E6/D5 safely; Black D6 first would capture nothing and has no liberties. There is no immediate need to solidify at C5. Checking only liberty counts would prioritize the wrong group. **Compare the opponent taking the eye-space boundary first, not just the opponent giving atari to the last group you examined.**

### B. An active boundary move beats an inside connection

Black to move:
```
  ABCDEFGHJ
9 ZZZZZZWZZ
8 ZZZZBWZWZ
7 ZZZZBBWZZ
6 ZZBZBWWZZ
5 ZZBZBBWZZ
4 ZZWBZZZZZ
3 ZZWZBZWZZ
2 ZZZZWZZZZ
1 ZZZZZZZZZ
```
**D2**, not D3. D3 appears to connect D4 and E3 safely, but concedes White D2, an important low extension that changes the bottom fight. D2 instead goes around the head of E2, keeps White's left chain separated from E2, and protects Black's bottom prospects while forcing White to settle low. A useful main line is Black D2, White C2, Black D3, White D1, Black F2. Read alternatives rather than assuming the line is forced. For example, if White cuts at D3 instead, Black E4 connects D4, E3, and the main chain. If White cuts at E4, that cutting stone has only F4 as a liberty and Black F4 captures it. The apparent need to play an immediate solid D3 connection is therefore misleading.

The lesson is not “always hane.” It is **include the active point just outside your shape and compare its actual cuts with the opponent's best reply to the solid move**. Filling an inside connection is not automatically safer in the resulting whole-board fight.

### C. A huge wall is not automatically alive

White to move:
```
  ABCDEFGHJ
9 ZZZZZZZZZ
8 ZWBBBBBBW
7 ZWWWBZWWZ
6 ZBWZBZZZZ
5 ZWBBBZWZZ
4 ZWWZBZZZZ
3 ZZWWBZWZZ
2 ZWBBBZZZZ
1 ZZZZZZZZZ
```
**G2** is the vital attack; don't spend the turn connecting J8 at J7. Black's massive central wall has many liberties but lacks secure eyes. The left is White; the narrow top strip is not already two eyes; the lower-right opening is crucial to Black's eye-making prospects. G2 extends the lower boundary and prevents easy settlement. One strong continuation is White G2, Black F1, White F2, Black E1, White C1. The attack is on eye space, not immediate capture.

The J8 stone is not an emergency: Black J9 can be answered by White J7 connecting to H7; a Black J7 cut has only J6 as a liberty, so White J6 captures it. Even if a peripheral stone really had to be sacrificed, compare its value with the whole-board attack. Completing its local connection gives Black the turn needed elsewhere. **Before finishing a sequence around a peripheral stone, inspect the life of the largest enemy chain and the largest own chain.** A group is strong because it can live or fight successfully, not because it looks like a long wall.

### D. Atari is not capture: check your own whole chain

Black to move:
```
  ABCDEFGHJ
9 ZBWWZZZZZ
8 BZBWZZZZZ
7 BBBWWWWZZ
6 WWWWWBWWW
5 WBWWBBBWB
4 BBBBBZBBB
3 WBBBBWBBZ
2 ZWBWBWBWW
1 ZWWWBBWWZ
```
The huge 25-stone Black chain containing E5 has exactly **{F4, J3}** as liberties. White F2–F3 has only **{F4}**; White G1–H1–H2–J2 has **{J1,J3}**. Neither is an already-captured eye.

**Black J3 loses immediately:** it captures nothing and leaves the entire Black chain with only F4. White F4 then captures the whole chain, now 26 stones including J3. It is NOT suicide: opposing captures happen first! Saying “J3 puts White in atari” misses the reciprocal atari on Black.

**A2** is safe and useful: it captures White A3, creating A3 as a new liberty of the main chain while preserving F4 and J3. **F4** also works by actually capturing White F2–F3 rather than merely threatening capture elsewhere. The essential ledger is: before move, liberties; captures caused; after move, liberties; opponent's immediate capture. Never infer a large group's safety from its size or yesterday's analysis.

### E. Don't add six stones to a lost ladder

White to move:
```
  ABCDEFGHJ
9 ZZZZZZZZZ
8 ZZZZZZZZZ
7 ZZZZZZZZZ
6 ZZZBZZZZZ
5 ZZZZBZZZZ
4 ZZWWBWBZZ
3 ZZZWWBZZZ
2 ZZZZZBZZZ
1 ZZZZZZZZZ
```
The isolated White F4 stone has only F5 as a liberty. Saving it by F5 looks natural, but read the whole forced chase:
**W F5, B F6, W G5, B H5, W G6, B G7, W H6, B H7, W J6, B J7, W J5, B J4**, capturing the entire running chain. There is no friendly ladder breaker ahead. A counter-atari on Black G4 does not save it: capturing the white chain gives G4 new liberties.

Sacrifice F4 and develop elsewhere; **G7** is a strong whole-board move. The point is not to memorize this ladder: before extending an ataried stone, trace the forced extensions until you see a real escape, countercapture, or edge. Don't stop at a temporary two-liberty shape and call it safe. One lost stone is cheap; repeated automatic rescue can lose the game.

## Strict Tromp–Taylor endgame

For an exact final count, count stones and flood-fill the connected empty regions. The final score counts stones plus empty regions bordered ONLY by that color. An empty region touching both colors is neutral. Prisoners don't score separately. Dead stones are NOT automatically removed: the enemy stone still scores, and empty regions touching it are not yours. Physically capture dead stones when necessary before passing, but first take valuable outside moves if the capture remains assured. An enemy move inside your safe territory isn't urgent unless it can make eyes, escape, capture, or create a useful ko.

Playing inside your own secured territory is normally area-neutral, but wastes a turn. Safe dame are worth a point of area: fill them before passing. Do not destroy eyes or seki to do so. Boundary moves can both add your points and remove theirs; compare who gets to play first, including forced replies.

If B and W are area totals, the Black margin is B−W−7. Positive means Black wins, zero draws. If all 81 points are owned, Black needs 45 to win (44 draws), White 38 (37 draws); with neutral points use the actual difference instead.

Before passing, verify life, finish profitable boundaries and safe dame, and remove dead enemy stones that spoil your score. If the opponent passed, compute the LITERAL final score before accepting: no imagined dead-stone removal. Pass immediately if it secures a win; don't end a losing game while a useful chance remains. If passing secures a draw, look for a sound winning improvement, but do not throw away the draw on a hopeless invasion. Do not invade solid two-eyed territory or fill your last eyes merely to delay the inevitable.

Final check: actual board, accurate group liberties, strongest opponent reply, correct legal coordinate. Output only the move.
