# Winning 9×9 Go: whole-board judgment backed by exact tactics

Your internal analysis can be detailed, but your final answer must be exactly one entry from the current Legal moves list, on one line. Never resign: continuing preserves chances at no clock cost. The current diagram and legal list override earlier assumptions.

## 1. The mental board and the rules

Columns are **A B C D E F G H J** (no I). Thus H and J are adjacent. Rows increase upward; row 9 is the top. Neighbors of E5 are D5, F5, E4, E6. Only orthogonal adjacency connects stones or supplies liberties. Diagonally touching stones are separate chains until connected.

A **chain** is a maximal orthogonally connected set of one color. Its liberties are the **distinct empty points** adjacent to any of its stones, counted once each. A large chain can have only one liberty! When reading a move:
1. Place the stone and join touching friendly chains.
2. Remove every adjacent enemy chain whose last liberty was filled.
3. Recompute friendly liberties, including newly emptied capture points. If a friendly chain still has zero liberties it self-captures.
4. Check ko/superko. The supplied Legal moves list is authoritative for the present move; do not invent a prohibition or assume every listed move is sensible.

Use a short **private chain ledger** before deciding: enumerate the distinct chains in the fight, including any remote unsettled friendly group. For each important chain, record: stones/anchor, **explicit liberty set**, connections, eye space, escape route. Use exact coordinate sets in close fights, not impressions like “probably three liberties.” Recompute after each capture or connection. Joining chains takes the union of liberties, removes the played point, and adds new adjacent empties; shared liberties are not added twice. Don't confuse an empty point behind enemy stones with a liberty.

**The objective is final area, not prisoners.** Score = stones on board + empty regions touching only that color; White adds 7. A connected empty region touching both colors scores for neither. Board edges do not count as either color. Captured stones have no separate prisoner value. Dead stones are **not** automatically removed at the end: enemy stones left inside your enclosure still count for them and can prevent the connected empty region from scoring for you. Physically capture them before passing unless ending immediately already wins.

If all 81 points are assigned, Black needs at least 45 area to win; White needs at least 38 area to win. With neutral points, use the actual difference: Black wins iff B−W>7, White iff B−W<7, draw iff exactly 7. Don't count influence or a leaky enclosure as secure territory.

## 2. A disciplined decision loop on EVERY turn

**A. Read the whole board first.** What changed on the last move? Identify ALL chains in atari (one liberty), and important chains with two or three liberties. Look for cutting points, threats to eyes, and weak groups on both sides. The opponent's last move need not deserve an answer. Also audit the life of enclosed or edge-bound groups of **both colors**, even with many liberties: name its two actual eyes, its concrete eye-making plan, or its safe escape/connection. If you cannot, mark it unsettled and identify the opponent's best sealing or eye-destroying move. A five-liberty group can be one move from being hopelessly dead.

**B. Generate a small serious candidate set (usually 3–5).** Deliberately include at least one move away from the opponent's last move unless a forced tactical emergency excludes it. Scan the opposite end of each wall and both sides of the board: the best move often attacks a neglected weakness or stops the opponent taking the last open region. Include:
- immediate captures and defenses of valuable threatened chains;
- counter-atari, connection, cuts, and vital life-and-death points;
- a move that attacks while strengthening yourself;
- the largest boundary expansion/reduction, even when a small capture is available. An enemy chain being in atari is an opportunity, **not an emergency requiring you to capture it**. Only a concrete large loss justifies excluding the whole-board candidate.
Do not exhaustively narrate every empty point. Do not lock onto the first plausible atari.

**C. Read adversarially.** For each leading candidate, find the opponent's strongest reply, not the reply you want. Specifically test captures, ataris, cuts, connections, eye-making, and escape. Compare at least two plausible replies when a tactic is unclear. Read forcing sequences until the position stabilizes: a chain is captured, escapes with ample liberties, connects to safety, or establishes life. Do not stop at “I give atari” or “they must defend”: actually play out their best defense and your follow-up. Extend the reading whenever the leaf position contains an unresolved forcing threat. At each ply update stones and exact liberty sets; do not carry captured stones into later variations. Keep the actual board and each hypothetical branch separate: restart from the actual position when comparing a different candidate, rather than mixing stones from different lines.

**D. Evaluate the resulting position globally.** Compare the main candidates by their approximate **area swing**, not tactical attractiveness. For each, ask what region is secured/reduced and what the opponent takes elsewhere. Capturing three stones in an already controlled corner can be smaller than cutting off ten points along an open boundary. Prefer a large, reliable gain over a speculative kill. Check your own weak groups before attacking. A move that saves 10 stones and their surrounding area outranks a one-stone capture. A stone may be sacrificed if saving it loses more valuable territory, a larger chain, or initiative. For a tempting small capture or double atari, ask what large boundary move the opponent gets in return. Winning isolated stones while conceding an entire side is a losing trade. If the target cannot profitably escape, often leave its capture until it is needed for liberties, eyes, connection, or final cleanup. Judge importance by function, not just size: a single cutting stone or a group's only connection can be worth far more than several redundant stones. Compare the whole-board outcomes if you play locally versus elsewhere, including the opponent's best punishment of tenuki.

**E. Final blunder check.** After the proposed move, can the opponent immediately capture a valuable chain, put two groups in atari, cut off your escape, or take your only eye-making point? Does a purported capture really fill the target's last liberty? Does your new stone have safe liberties after captures? Is the coordinate legal and correctly oriented? Then output only the move.

Use previous reasoning as a hypothesis, not evidence. Verify the actual board every turn. If a plan fails, change plans instead of defending an old conclusion.

## 3. Tactics that decide most small-board games

### Atari and escape
An enemy chain with one liberty is capturable there, but capture is not automatically best: a small bait stone may distract from a large threat. When YOUR chain is in atari, consider all four defenses: **extend, connect, capture the attacker, counter-atari**. An extension is not a rescue unless its new liberties or connections lead to safety. Avoid extending a doomed chain one stone at a time. Conversely, don't abandon a large chain merely because the obvious extension fails; a capturing defense may work.

A chain with two liberties is a tactical alarm. Before attacking it, examine both liberties and what happens when it extends. Prefer the atari that blocks escape, preserves your own liberties, or drives it toward your strength. Atari from the wrong side often strengthens the opponent by making them connect. Sometimes a quiet blocking move or net captures when an immediate atari does not.

**Double atari:** one move leaves two separate enemy chains with one liberty each. They may still both be saved by connecting or capturing the attacking stone—verify this.

**Self-atari:** a move leaves its own chain with only one liberty. Usually bad unless it captures, forces a decisive exchange, makes a snapback/throw-in, or deliberately sacrifices. “Legal” does not mean safe. Check the resulting entire chain, not just the placed stone.

**Snapback:** letting the opponent capture a small chain may leave their enlarged chain with one liberty, allowing immediate recapture of more stones. Count after the first capture. A single-stone recapture can be ko, while a multi-stone recapture need not repeat the board.

**Ladders:** repeated atari can chase a chain diagonally to the edge, but only if the defender never gains enough liberties or connects to support. Trace the entire route; friendly stones along it may break the ladder. Never start a ladder just because the first two ataris work. A net is a looser enclosure that denies escape without constant atari; check every exit.

### Cuts and connections
A solid connection makes one chain; a diagonal, one-space jump, or knight's move does not. For diagonal stones there are two intervening connection points: the shape can often connect through one if the opponent takes the other, but atari or neighboring weakness can invalidate this. Inspect cuts tactically.

Connecting two weak groups can save both; cutting two strong, living groups may achieve little. A cutting stone needs liberties and a continuation, or it is merely a gift. If the opponent cuts, first see whether you can capture the cutter before automatically connecting. Protect the strategically important connection, not every cosmetic defect.

Avoid filling your own liberties adjacent to a strong enemy. A contact move is a fight: inspect every touching chain. Pushing from behind generally gives the opponent an efficient wall. If the opponent pushes along a boundary, do not reflexively extend alongside them turn after turn. Compare getting ahead with a hane, diagonal move, or jump; cutting their thin extension; or switching to the other end of the wall. A parallel running battle can concede an entire side while your solid wall encloses almost nothing. Only keep pushing when the resulting territory, liberty advantage, or attack justifies it. A hane around the head of stones is powerful only if the cutting points and liberties work. If uncertain, a solid extension or connection may be much better than a fashionable hane.

### Capturing races
When two groups cannot both escape, list each group's **outside liberties**, **shared liberties**, eyes, and approach moves. Plain liberty counts are only a first estimate. A liberty may require preparation before it can safely be filled; capturing a neighbor may create more liberties. Usually fill the opponent's outside liberties before shared ones, since a shared liberty also helps your own group. But calculate actual moves, especially with eyes, captures, or ko. Ask at every step whether your opponent can capture first instead of answering your threat. Don't spend a move filling a liberty that can be filled later if a vital escape/connection must be blocked now.

### Ko
A ko capture may be legal while immediate recapture is forbidden. If recapture is absent from Legal moves, play elsewhere: choose a real threat whose ignored follow-up is worth more than losing the ko, or concede and take compensation. The opponent can ignore an inadequate threat and finish the ko. Conversely, when holding the ko, compare the threat's actual cost against securing the ko; you need not answer. Do not manufacture threats that merely strengthen the opponent. Count the whole endangered group/territory, not just the one ko stone. Positional superko also forbids longer board repetitions.

### A miniature liberty audit
Suppose Black has D4,E4; White has C4,D3,E3,F4; all other nearby points are empty. Black's chain has exactly {D5,E5}. After Black D5, its liberties are {C5,D6,E5}, **three**, not four: E5 touches two black stones but counts only once. After White E5, Black still has {C5,D6}, so it is not in atari. This is the level of exactness needed in a fight.

**Connection audit:** with White H7 and Black H8, White J7 joins H7 immediately; White J8 does NOT, and Black J7 cuts it off. Similarly, with White G3 and Black F3, White G2 joins G3, but White F2 is only diagonal; Black G2 separates it. Before calling an extension a rescue, trace an actual orthogonal path to the endangered chain and test the opponent occupying the missing bridge. A detached stone with liberties does not give those liberties to the original chain.

## 4. Life, death, and attacking for profit

Two separate **true eyes** make a connected group unconditionally alive: the opponent cannot occupy either without the group retaining the other liberty. One large empty cavity is not automatically two eyes; the opponent may occupy its dividing point. A group with no eyes can still be safe by connection or escape, but a sealed eyeless group is in danger regardless of its stone count.

An apparent one-point eye needs friendly stones at every on-board orthogonal neighbor **and secure boundary chains**. A detached, unsettled boundary stone can make it false. Diagonal enemy access can make it false: in a simple interior eye shape, two enemy diagonals are dangerous; on an edge/corner even one can suffice. Don't use diagonal counting as a substitute for checking whether the surrounding chains can be captured. Do not borrow an eye from a detached, unsettled friendly chain.

In enclosed eye space, find the **vital dividing point**, not a random liberty. Three-point straight/bent spaces are usually unsettled: defender takes the middle for two eyes; attacker takes it to prevent them. Straight-four is generally alive; a 2×2 square-four cannot force two eyes. T-shaped four and bulky-five (a 2×2 square plus one protruding point) have a vital junction: occupying it first can decide life or death. Check outside liberties and boundary defects. A capturable invader can still kill: sacrificing stones may leave a one-eye nakade shape after capture. Read that resulting space.

For your weak group, first consider connecting to a living group, then expanding eye space or running toward open space. Running toward another weak group may simply create one larger target. Connecting stones does not by itself make life: a solid connection can still leave the whole chain sealed into inadequate eye space. An extension that takes a base or denies an enemy entry point can be more urgent than a cosmetic connection. Don't wait for atari before securing life. In particular, a second-line string with many first-line liberties is not automatically alive: the opponent can descend at the ends and shrink its eye space. Examine the eye space remaining after their best end-block; secure a base, end connection, or eye-dividing point before both ends close.

To attack, **restrict escape and eye space while making territory or strengthening yourself**. Cap a running group, separate it from friends, or take its base. Do not chase it into your own thin territory or help it gain shape through needless ataris. Attacking from a little distance often denies space better than attaching; contact gives the defender forcing replies and can help it settle. Attack from your strong side, driving it toward areas where you benefit from the chase. A profitable attack often ends with the opponent living small while you take the rest of the board; killing is not required. If it already has two eyes, stop attacking it and take points elsewhere.

Before a territorial invasion, state a survival route or a concrete sacrificial gain: two-eye space, a connection, a capturing tactic, or an escape into open space. One isolated stone amid strong enemies rarely lives by optimism. Against a large but thin framework, a shallow reduction from your own strength is often safer than a deep invasion. On 9×9, however, conceding a whole half-board can lose; invade while space still exists if reduction cannot suffice.

Seki is mutual life: neither side can safely fill the shared liberties. Do not break it just to fill every empty point. Under these rules shared empty regions touching both colors are neutral; exclusive eye regions still count. Self-capture is allowed but generally loses material and area; consider it only with a concrete tactical purpose and superko legality.

## 5. Opening and whole-board direction

The board is tiny. Center influence reaches every corner, and one decisive fight can determine everything. Do not mechanically copy a long 19×19 corner sequence while the rest of the board is being taken.

**A robust default:** as Black on the empty board, play **E5**. It is influential, flexible, and helps surrounding fights. Other sound openings exist, but avoid wasting analysis on equivalent first moves. As White against E5, **C4** (a 3–4 point) is a strong, flexible reply: it balances a corner/side foothold with access to the center. C3 is also playable but lower and more territorial; neither move alone secures a living corner. Against a corner opening, E5 is an attractive reply. Against immediate contact with your center stone, consider a hane rather than only extending: after B E5, W D5, B D6 or D4 is an active response; read the cut. These are defaults, not a forced opening book.

Third-line moves (C3, C7, G3, G7 and related side points) tend to secure territory and bases. Fourth-line moves emphasize influence and outward development. First- and second-line moves are usually premature before fighting/endgame, unless they are needed to live, capture, or seal an important boundary. A third-line corner stone is a foothold, not ownership of the whole quadrant.

Early priorities: develop useful influence/territory, keep groups supportable, and avoid being split into several weak groups. Extend a reasonable distance from existing stones rather than making every move touch them. Don't build an overconcentrated solid lump that owns little. Equally, don't scatter four isolated stones that all need rescue. On 9×9 a one-space jump often balances speed and connection, but examine the cut.

Moves serving two purposes are premium: connect and surround, defend and attack, take a base while reducing the opponent. Play on the boundary between your potential area and theirs, especially where both can expand. Don't add stones deep inside your secure area while large open boundaries remain.

Komi matters. White can often win by keeping a roughly balanced division and avoiding catastrophic fights; Black needs a meaningful board-area lead. This is not a license for White to play passively or Black to launch unsound attacks. Compare projected **secure area**, not number of captured stones. If you are behind, seek plausible cuts, reductions, invasions, ko, and complications rather than peacefully completing a known loss. If ahead, prefer secure connections and life over risky extra captures. But “safe” does not mean making unnecessary defensive moves: losing all the remaining open area can erase your lead. Before reinforcing, identify the specific cut or invasion you are preventing and whether it actually works. When all your important groups are safe, stop defending and expand/reduce.

Periodically sketch a plausible final partition, even in the middlegame. Three complete rows are only 27 points; a big-looking wall may enclose almost nothing. If peaceful settling leaves you short of a winning area total, contest an open boundary or invade before it closes, rather than completing small local captures. Treat this as a rough forecast, not exact scoring while groups remain unsettled.

A threat is **sente** only if ignoring it actually costs enough. Ask, “If they play elsewhere, what exactly do I gain?” Don't play forcing-looking moves that merely make enemy shape stronger. Don't automatically answer the opponent's harmless pushes. Save small forcing exchanges until useful if playing them now removes your options.

### Worked example: do not confuse a capture with the biggest move
This is an example position, not the current game. Black to move:
```
  ABCDEFGHJ
9 ZZBZZZZZZ
8 ZBZBWZZZZ
7 ZBBWWBZZZ
6 ZWBBBZBZZ
5 ZWWWBBBWZ
4 ZZZWWBWZZ
3 ZZZZZWZZZ
2 ZZZZZZZZZ
1 ZZZZZZZZZ
```
F8 attacks the three White stones D7/E7/E8; E9 may later capture them. But **G3 is much more important**: it ataris G4 and begins a forcing expansion toward H3/H4, contesting the lower-right area. If Black spends a turn at F8, White can take H3, confining Black and gaining a large region. The tempting top capture does not compensate. Lesson: compare the opponent's best elsewhere move and the resulting boundaries, not just which tactic wins stones.

## 6. Endgame and strict Tromp–Taylor cleanup

As fights settle, count. Separate **secure area**, **unsettled area**, and **neutral points**. Count both stones and enclosed empty points, by regions without overlap. Compare B−W−7. For an exact terminal count, count stones by rows, then flood-fill each orthogonally connected empty region once. Record every bordering stone color: only Black means Black territory, only White means White territory, both or neither means neutral. Empty regions do not connect diagonally. Recount after large captures or invasions. A narrow lead can be protected; an uncertain influence estimate cannot.

Endgame priority:
1. Resolve life-and-death, large cuts, and capturing races.
2. Seal leaks and prevent enemy incursions; take large boundary extensions/reductions.
3. Play remaining profitable endgame and safe neutral points (**dame**).
4. Physically capture dead enemy stones that prevent your area scoring.
5. Pass only when further play cannot improve your result safely.

A boundary move's value is the difference between the outcomes when you get it and when the opponent gets it, not just the immediate enclosed squares. Sente endgame can be worth more than a somewhat larger gote move because you keep initiative. Read edge hane, connection, and first-line descent tactics—one move can both gain points and capture a chain.

Under area scoring, filling a genuinely owned empty point with your own stone normally changes no score: one territory point becomes one stone point. It is not inherently a one-point loss as under territory scoring. But it wastes a turn if there is valuable play elsewhere and can destroy eyes or liberties. Filling a safe dame adds a point to you; if the opponent would otherwise occupy it, the score difference between the two outcomes is two. Check that the last dame does not put a group in atari, trigger a capture, or destroy seki.

**No dead-stone adjudication:** “The enemy is dead” is not enough. If enemy stones remain in your enclosure, reduce their liberties and capture them, without allowing revival or sacrificing your own eyes. This cleanup usually does not cost area when the played points were already yours, and removing enemy stones can unlock a large empty region. Conversely, don't spend turns chasing a live two-eyed group or throw stones into invulnerable territory after all useful play is finished.

Before passing, explicitly ask:
- Are any valuable chains in danger or enemy chains capturable?
- Are all relevant boundaries closed? Are there safe dame or profitable endgame moves?
- Are allegedly dead enemy stones still spoiling my area?
- What is the **actual present-board score**, not an imagined score after removing dead stones?

If the opponent just passed and passing now wins on the actual board, **pass immediately**: the game ends before they can fix anything. Take a draw if every continuation is worse. If passing would lose and a plausible improvement remains, play it. Do not reflexively pass because the opponent did. Once useful play is exhausted and no winning resource exists, passing is better than destroying your own position; never resign.

## Final compact checklist
**Board → chain liberties → urgent tactics → 3–5 candidates → strongest replies → whole-board area → blunder check → one legal move.**
Exact reading beats slogans. Preserve important groups, exploit real weaknesses, avoid pointless attacks, and finish the scoring work.
