# Playing strong 9×9 Go

Your task is to win the game, not to collect captures or make attractive shapes. Think privately; output exactly one legal move. The current board and legal-move list are authoritative. Reconstruct from them each turn rather than trusting an earlier variation.

## 1. A reliable move-selection procedure

Do this every turn, with most of your effort spent on the genuinely critical fight:

1. **Orient and scan.** You are the color named in this prompt. Columns are A B C D E F G H J (no I); top is row 9. Orthogonal adjacency only. Identify the opponent's last move, any stones it CAPTURED, and what it threatens; scan the whole board for bigger threats. Removed stones become new liberties and may invalidate your previous plan.
2. **Tactical audit before strategy.** Locate both colors' chains with one or two liberties, cuts between your chains, and groups without secure life. For each enclosed friendly group, identify its actual eyes or the vital move that creates them; size alone does not mean life. Is there an immediate capture, a necessary escape, a cutting stone to capture, or a double threat? A quiet territorial move cannot compensate for losing your main group.
3. **Generate a short candidate list.** Usually 3–5 moves: best defense/counterattack, strongest forcing move, connection or cut, and largest territorial/development move. When a small chain is threatened, explicitly include sacrificing it and improving the more important group. Include a quiet move or tenuki when the opponent's threat is small. Do not enumerate every empty point or pursue twenty shallow variations.
4. **Read the best resistance.** For each serious candidate, simulate the opponent's strongest reply, not the reply you hope for. Prioritize captures, ataris, cuts, connections, eye vital points and escapes. Follow forcing sequences to a stable result; compare alternative defenses before declaring a tactic forced. For a decisive fight, read farther rather than choosing by a proverb.
5. **Compare resulting positions.** First avoid catastrophic loss; then maximize the whole-board result, comparing secure area, group safety, initiative and the opponent's best follow-up. Safety is a constraint, not a reason to choose the most defensive move. Prefer a move that achieves two purposes. Do not treat uncertain influence as secured territory.
6. **Final blunder check.** After placing your proposed move and resolving captures: how many liberties does its resulting chain have? What is the opponent's most damaging immediate move? Did you miss a capture of a different chain, a cut, a ladder, a snapback, or loss of an eye? Confirm the coordinate is in Legal moves. Output only that coordinate (or `pass`).

There is no game clock. Use enough calculation to establish tactical facts, but keep it concrete: exact coordinates and liberty sets, not repeated vague claims that a move “looks strong.”

## 2. Exact board mechanics: the foundation of reading

A **chain** is a maximal set of same-color stones linked orthogonally. Its **liberties** are the SET of distinct empty orthogonal neighbors of all stones in the chain. Diagonal neighbors are neither connections nor liberties. A corner stone has at most two neighbors, an edge stone three, an interior stone four. Two stones sharing a liberty contribute only one liberty there.

For a critical chain, explicitly list its stones or a representative and its liberty coordinates. Recompute after each hypothetical move. On playing at p:
- Put the stone at p; merge all orthogonally adjacent friendly chains.
- Remove every adjacent enemy chain whose final liberty was p.
- Recompute the merged friendly chain's liberties, including points freed by captures. Only afterward remove friendly stones with no liberties.
- Check the resulting board, not just the original local picture. A move at an apparent suicide point can capture and be good; an “extension” can merge into a chain with only one liberty and be terrible.

A legal move is not necessarily a safe move: self-capture is legal here when superko permits. Avoid it except for a concretely verified tactic. A single-stone suicide that merely restores the board is excluded by positional superko. The supplied list settles current legality.

**Atari:** a chain has exactly one liberty. Saving it can mean extending at that liberty, capturing the attacking chain, connecting to safety, or making a stronger counterthreat. Don't automatically extend. Count the resulting liberties and verify that the extension actually escapes. If it again has only two liberties, the reading is not finished: continue until the chase is broken, it connects to safety, or it gains usable room. Merely surviving the next move is not a successful escape. Sometimes abandoning a small chain is best.

**After a cut, audit BOTH sides.** The opponent may atari one stone to distract you from the more important chain. Saving that one stone can let the opponent atari and destroy a different two-liberty chain next. Compare extending the threatened chain with strengthening the OTHER chain and sacrificing the first. Before accepting an escape as successful, simulate the opponent's next forcing move against *any* of your chains, not only the one just extended. Preserve the group that gives you life, connections and territory; do not automatically preserve the one the opponent pointed at.

**Two liberties:** this is a warning, especially for adjacent opposing chains. Before filling one enemy liberty, check whether the move leaves your own chain capturable. Check every adjacent chain separately. An atari that forces the enemy to connect, gain liberties and attack you may help them more than you.

**Prove captures, don't assume them.** Before selecting a capture at p, verify that the ENTIRE target chain's liberty set on the current board is exactly {p}. Check particularly for a new liberty where the opponent just captured one of your stones. After your proposed move, explicitly enumerate the new friendly chain's liberties. If it has only one and the opponent can capture it, reject the move unless you have proved a worthwhile sacrifice, snapback or countercapture. A visually enclosing move may be self-atari rather than capture.

**Captures are not always urgent.** A dead stone that cannot escape can wait while you take a larger move. Conversely, a capture that joins chains, removes a cut, creates an eye or wins a race can be the largest move on the board.

## 3. Tactical tools and how to verify them

- **Double atari / double threat:** attack two important chains or two vital points at once. Verify the opponent cannot save both by connecting, capturing your attacking stone, or counter-atari.
- **Cut and connect:** separating two weak enemy groups is powerful; connecting your own weak groups is often urgent. A cutting stone must itself survive or gain compensation. Before cutting, read the enemy's ataris against it. Before pushing between enemy chains, ask whether you are just building a heavy, doomed chain.
- **Ladder:** repeatedly atari a two-liberty chain so each forced extension again has only two liberties. Trace the actual zigzag to the edge or an intervening stone. A friendly ladder breaker can change everything. Never assume a ladder works from its first two moves. If it fails, do not keep chasing and donating stones.
- **Net:** when direct ataris drive the target toward help, a noncontact enclosing move can remove its escape routes. Verify all exits, including cuts and countercaptures.
- **Snapback:** after you capture, the opponent may recapture your entire newly joined chain. Always count liberties after a small capture in a tight shape. Conversely, a sacrifice can force an enemy capture and leave the capturer in atari.
- **Throw-in:** a sacrificial stone inside a small eye space can force a capture that reduces liberties or creates a false eye. Calculate the board AFTER capture; merely placing an isolated stone inside territory is not an attack.
- **Capturing race:** list each group's outside liberties, shared liberties and eyes. Count how many moves each side truly needs to capture, accounting for approach moves, forced captures and newly freed liberties. In ordinary no-eye races, fill outside liberties before shared ones; filling a shared liberty reduces both groups' liberties and can lose. Eyes, approach-move liberties and ko can overturn simple counts. Direct simulation is safer than a memorized formula.
- **Ko:** a ko capture is not unconditional life or death. Find a real threat elsewhere whose unanswered loss is comparable to the ko. If the opponent ignores it, take the promised profit. Do not waste tiny threats in a huge ko. The current illegal list covers superko now; hypothetical repetitions must also be considered.

Read the opponent's counterplay even during “forcing” sequences. An atari on a disposable stone need not be answered. Don't count on a cooperative opponent.

## 4. Life, eyes and weak groups

Two **independent true eyes** make a connected group unconditionally alive: the opponent cannot fill either without failing to capture. A large empty region is not automatically two eyes. Ask whether it can be divided into two separate eyes against the opponent moving first, and whether all surrounding chains are safe and connected.

For a one-point eye, all existing orthogonal neighbors must be friendly. Diagonal enemy access can make it false: an interior point generally needs at least three of its four diagonals controlled; an edge/corner eye generally needs all its existing diagonals controlled. These are shape diagnostics, not a substitute for reading capture of the surrounding chains. An empty diagonal contested by the opponent is not safely controlled. Two apparent eyes whose boundary stones can be captured separately do not guarantee life.

Small enclosed eye spaces have vital points. A straight three-point space depends on who occupies its middle; a compact bent three likewise has a dividing vital point. Straight four can normally form two eyes; other four-point shapes may have a killing point. Do not simply count empty spaces. Test “opponent plays the best eye-killing point; can I still make two eyes?” Include throw-ins and false-eye possibilities. Seki is mutual life: filling a critical shared liberty lets the opponent capture you. Don't break a seki just to fill every empty point.

**A crucial life pattern:** suppose your connected boundary encloses exactly three empty points in a row, G5–H5–J5, with no other eye space or escape. H5 is urgent: playing there separates G5 and J5 into two eyes. If the opponent occupies H5 first, the space cannot make two eyes, even if your surrounding chain contains twenty stones. Do not play a distant invasion or a tiny capture instead! Recheck the eye space of your largest group whenever an invasion closes its exits. A huge chain can die while still having several liberties; “not in atari” is not the same as “safe.”

For an unsettled group, choose among:
- make a base/two-eye potential along a side;
- connect to an already safe group;
- run toward open space and friendly support;
- attack a weaker neighboring group to gain life;
- sacrifice the group if saving it costs more than it is worth.

**Urgent before big:** prevent confinement before the last escape point disappears. A group with many current liberties but no eye space can still be strategically weak. Running blindly through the center without a destination is not life. Conversely, don't waste moves making a third eye or defending a group already safely alive.

Keep weak groups few. One manageable weak group is a task; two separated weak groups let the opponent attack both. Prefer a solid connection when a loose connection can actually be cut with severe consequences; do not fill every potential cutting point preemptively. Adjacent stones are connected; diagonal contact, a one-space jump or a knight's move are only potential connections. Check both cutting points, especially near enemy strength. A diagonal connection is secure only when the opponent's cut can be answered successfully.

### Avoid defensive autopilot: miai and timing

A low liberty count, an empty connection point, or an enemy stone nearby is a **reason to read**, not an automatic order to defend. Ask the **tenuki test**: if I play elsewhere, what exact move can the opponent make, what will I answer, and what do I really lose? If you cannot name a damaging sequence, do not invent urgency. Quietly connecting two already safe chains can lose several points by letting the opponent take the active boundary.

**Miai** means two alternatives that achieve the needed result: if the enemy takes one, take the other. A chain with two usable escape/connection points may not need immediate protection. A diagonal pair may connect by either intervening point; if the opponent cuts at one and you safely connect at the other, spending a move to connect first is unnecessary. Verify the opponent cannot disable both alternatives with an atari or double attack.

In contact fights, compare **hane/turn, extension, and solid connection**, not just “connect or abandon.” The outward turn often sets the boundary for an entire side. A retreat or connection behind your front line may let the enemy turn first and gain many points. If an enemy atari merely forces a connection you can safely make later, consider taking the key outward point FIRST and answering the atari afterward. Read this exchange; do not assume all ataris must be prevented. Likewise, after extending once beside an enemy wall, look for a turn around its end rather than repeatedly pushing from behind.

**Move-order example (otherwise empty board):** Black has D4, E4, E5, F6; White has D5, D6, E6, F7; Black to play. F6 has two liberties, F5 and G6, but immediately connecting at F5 is passive. The active extension G6 and hane G7 are both worth reading. For example, after G7, if White ataris F6 with G6, Black can NOW connect at F5, having gained G7 first. If Black connects first, White gets G7 and a much better boundary. This illustrates why “my stone has two liberties” does not automatically mean “defend now.” Rotate/reflect the pattern, but verify tactics when extra stones are present.

Distinguish **necessary defense** from **premature consolidation**. Secure life when threatened; don't spend extra moves perfecting a secure half-board while the opponent expands on both ends. Small invaders inside strong territory can often be contained later. The right response may be to take the last big open boundary first. At each stage ask which move I would most hate the opponent to take: that shared vital point often matters more than a comfortable connection.

## 5. 9×9 strategy: the board is one fight

The small board magnifies tactics and central connections. Corner/side territory is efficient, but a 19×19-style tour of four distant corners can leave every stone weak. Do not mechanically play an opening sequence regardless of replies.

**Opening defaults:** As Black, prefer **D4 on the empty board**: establish a compact foothold, then develop toward the center and open sides. E5 is playable, but D4 is the practical default here. As White, develop a compact position with room along a side/corner while contesting Black's influence; do not scatter isolated stones. The third line is good for a territorial base, the fourth for influence and connection. Avoid early first/second-line crawling unless a concrete tactical or territorial reason justifies it. Respond to contact fights before starting unrelated development if your stones would otherwise be cut apart.

**Small opening reference, only for matching positions:** after Black D4, useful replies to White's first stone are: D6→F5; E6→F4; F6→F5 or E6; E5→E4; E4→E5; C4→D5; F4→E6; C6→D6; D5→E5. These are alternatives for different positions, not a sequence. Apply whole-board rotations/reflections correctly. Once extra stones are present, read the actual position. As White against Black E5, prefer **C5**, a third-line foothold that leaves room on both ends; direct attachment D5 gives Black a useful hane. For example, B E5, W C5, B D5: extend C6 (or C4), rather than hane D6 into Black's nearby strength. With exactly E5, C5, D5, C6 played, useful White replies are: after Black D7, play D3; after Black D3, play D7; after Black C4, play B4. Develop the other end instead of answering every approach locally. Against a fourth-line opening such as F6, D4 is sound.

After the first few moves, ask: where will each color get roughly half the board, which boundary is unsettled, and which group can be attacked? Develop toward your own stones and the largest open region. A central stone is useful for connecting and attacking but is not itself territory. Do not surrender both sides while building an empty center.

**Shape and efficiency:** extend from a weak chain toward room; reinforce the head of stones being pushed down. Hane can be powerful at the head of two stones, but check the cut and ladder first. Don't attach casually to a strong enemy chain: they can gain forcing moves while you become weak. Attaching to a weak enemy can help them settle, so distant pressure is often better. A one-space jump is efficient in open space; near contact fighting, a solid extension may be essential.

**Attack for profit, not fantasies of killing.** Reduce the opponent's eye space or separate their groups while securing your own area. If they live small and you get a strong outside wall plus territory, the attack succeeded. Once they have two eyes, stop chasing them. Don't push them into your weak group. Don't make contact ataris that strengthen them for no return.

**Influence must pay rent.** Use a wall to enclose the adjoining side/center, support a neighboring attack, or prevent an invasion. Do not add stones to the wall while the opponent takes all the points. Avoid playing deep inside an enemy framework without a credible plan to live or connect. Reduce from the open boundary when a full invasion is too risky. But an enormous unopposed framework must be challenged before it solidifies.

**Expansion example:** Black has D2, D7, E2, E3, E7, F4, F6; White has C2, C6, C7, D3, D4, D6; White to play, otherwise empty. White should consider **G5**, contesting the large open right side and the gap between F4/F6, rather than automatically connecting C3. The C2 stone still has B2/C1/C3 as liberties; nothing forces immediate rescue. After G5, one possible continuation is Black F5, White G6, Black H4, White G8. White gains a foothold outside Black's framework. The general lesson: settle only as much as necessary, then take the open vital region before the opponent's wall closes. Do not allow a comfortable connection to consume the last opportunity to contest half the board.

**Sacrifice intelligently.** Stones already played are sunk costs. A small disconnected chain can be abandoned if saving it creates a larger weak group or loses the rest of the board. However, stones that connect groups, prevent an enemy eye, or contain a large territory can be far more valuable than their number. Compare the whole-board consequences of losing them, not just the prisoner count.

**Sente is earned:** a move is forcing only if the opponent loses something larger by ignoring it. Before responding, compare answering with capturing, counterattacking or taking a larger point elsewhere. Before making a threat, consider the opponent simply ignoring it. Cashing every available atari often wastes flexibility and helps the opponent repair their shape.

## 6. Scoring, komi and finishing under these exact rules

This is **strict Tromp–Taylor AREA scoring, no dead-stone removal**. Each stone on the board counts one point. Each connected empty region counts for a color only if it borders stones of that color and no stones of the other color. Empty regions bordering both colors are neutral. Prisoners do NOT separately count. Eyes in seki score if their empty regions border only one color; shared liberties remain neutral. White receives 7 points.

Thus Black wins iff B-area − W-area > 7; equality is a draw. If all 81 points belong to one side or the other, Black needs at least 45 and White needs at least 38 to win. With neutral points, use the actual difference instead of those thresholds. Count secured territory plus stones, not territory alone. Don't assume a visually large region is secured if an enemy group can live inside it or a boundary can be cut.

In the middle game estimate secure area, likely area and unsettled area separately. Avoid false precision. As the boundaries settle, count row-by-row or by disjoint regions, ensuring every point is counted once. Include White's komi. If ahead, prefer robust connections and life over speculative attacks; if behind, seek a real invasion, reduction, ko or tactical complication rather than safe moves that guarantee a loss. Do not resign: opponents can err and there is no benefit to resigning.

**Strict scoring changes cleanup:** supposedly dead enemy stones STILL count for the enemy until actually captured. Worse, their presence makes an adjacent empty region neutral rather than yours. You must physically capture them when this is needed for the score. A group being “obviously dead” is not enough. Don't accept an ordinary human-style scoring agreement by passing early.

Playing inside your own fully secured territory usually changes one territory point into one stone point: no area loss. It still costs a tempo, so take valuable external moves first, but don't refuse a necessary repair or dead-stone capture out of territory-scoring habits. Never fill an essential eye or reduce liberties so far that your group dies.

**Endgame priorities:** secure threatened life/connections; finish profitable boundary moves and captures; take safe neutral points (dame); remove dead invaders as required; then pass. A safe dame adds a stone point where there was no territory and can decide the result. A boundary move can both gain your area and deny theirs, making it more valuable than ordinary dame. Filling liberties may expose a cut or shortage of liberties, so recheck tactical safety even in endgame. Do not fill shared seki liberties automatically.

Before passing:
1. Is there a valuable legal capture, boundary move, invasion/reduction, or safe neutral point?
2. Are all necessary enemy dead stones physically removed? Are my own groups safe against the opponent continuing?
3. What is the actual strict area score if both players stop NOW?

If the opponent just passed and the exact current score wins for you, pass immediately to secure the win, even if unfinished fights remain. Accept a draw rather than an unavoidable loss. If passing would lose, continue looking for genuine chances; filling your own safe territory cannot fix the score. Otherwise pass when no profitable or necessary move remains. An opponent pass is not evidence that the game is safely over.

## Final reminder

The largest improvement comes from **not hallucinating connections/liberties and not losing large groups**. Work from the current diagram. Read captures and ataris exactly. Balance tactical urgency with whole-board area. Before committing to the chosen coordinate, look once more for the opponent's strongest refutation. Then output exactly one entry from Legal moves, with no commentary.
