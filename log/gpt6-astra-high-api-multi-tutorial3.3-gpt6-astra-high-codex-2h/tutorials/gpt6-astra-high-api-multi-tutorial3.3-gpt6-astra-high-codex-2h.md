# Playing strong 9×9 Go

Your task each turn is to choose the best legal move, not to explain it. Think privately, then output exactly one entry from the supplied Legal moves. Never resign. The displayed board and legal list are authoritative; reconstruct the position afresh rather than trusting an earlier imagined variation.

## 1. Know what wins

This is **area scoring**, with White receiving 7 points. Your score is your stones still on the board plus empty points whose entire connected empty region touches only your color. Captured prisoners do not themselves score. Empty regions touching both colors are neutral. **There is no automatic dead-stone removal.** A surrounded enemy stone still counts for its owner and contaminates any empty region it touches until you actually capture it. Two passes finish immediately.

An 81-point board with no neutral points is won by Black with at least 45 points (45–36–7 = +2); 44–37–7 is a draw. White wins with at least 38 points in that case. If N points are neutral, use B+W=81−N and compare B−W−7. Do not assume 45 is the threshold when there is neutral space.

Filling your own secure territory usually changes an empty point into a stone and costs no area, but wastes a turn and may remove a vital liberty or eye. Occupying safe neutral space gains a point; giving the opponent the last neutral moves can lose a close game. Removing enemy stones can be valuable because it also makes the surrounding empty region count for you. But distinguish future strategic value from literal score if passing now: an enemy stone already doomed to capture can usually be removed later. Its contamination of a large empty region does NOT mean capturing it immediately is a huge urgent gain. Take larger moves first if its escape and counterplay are controlled.

## 2. A reliable move-selection loop

**Mandatory tactical audit before choosing:** privately enumerate enemy chains in atari and their capture coordinates, then your chains in atari and their possible rescues. Do this even when an extension looks obvious. An endangered chain can be saved by capturing an adjacent enemy somewhere other than its own last liberty. Inspect EACH adjacent enemy chain for this countercapture; do not visually merge diagonal stones. A single missed countercapture can reverse an entire fight.

Example (other points locally empty): Black C3, D2, D4; White B3, C4, D3. Black C3 has only C2 as a liberty. But White D3 has only E3! Black E3 captures D3, giving C3 a new liberty at D3. Extending at C2 is NOT the only defense. This is a reading pattern, not a move to copy onto a different board.

Spend your effort on reading actual moves, not on repeating general principles. There is no move clock: do not stop at the first plausible move. Before committing a nonforced move, compare at least TWO concrete variations, each including the opponent's best reply and your continuation. For fighting moves test both a normal defense and a counterattack. If the result depends on one liberty, explicitly enumerate that liberty set again. Think carefully enough to find the refutation of your favorite move, not merely a line that supports it.

**Triage, not atari reflex:** Order priorities by the consequence of neglecting them, not by how forcing they look:
- Saving or capturing an essential group, securing its life, or preventing a decisive cut.
- Controlling the largest contested boundary or open area; attacking while strengthening yourself.
- Small local gains: an unimportant one-stone capture, polishing an already safe shape, routine cleanup.
An ataried stone may belong in the LAST category. Before rescuing it, ask whether the extension actually leads to life or connection, and whether the stone matters. Before capturing a small stone, ask whether it can really escape profitably and what major move the opponent gets elsewhere. Capturing now is often unnecessary when you can capture later. Do not trade an entire side for a small capture or for saving a doomed isolated stone.

For a strategic comparison, imagine the opponent immediately occupying the biggest point you are neglecting. Could they invade a wide region, sever an anchor stone, or seal your group in? If so, compare preventing that with your tempting local move. “This gains a stone” is not a sufficient justification.


1. **Orient and parse.** Columns are A B C D E F G H J (no I); J is adjacent to H. Rows increase upward. Only orthogonal neighbors connect; diagonals do not. Identify the last move and all groups it affects.
2. **Tactical scan of BOTH colors.** Find every chain with one or two liberties, contact-fighting chains with three liberties, important cutting points, and large groups without secure life. For critical chains use a compact private ledger: color, member stones, distinct liberty coordinates. Trace orthogonal connections rather than guessing from the visual cluster. Explicitly list exact liberty coordinates for the groups involved in a fight. Check the whole board, not just the latest move.
3. **Generate a short candidate list.** Usually 3–5 serious moves: emergency defense/capture, attack/cut, connection or life-making move, and the largest strategic alternative. Include a counterattack or sacrifice instead of assuming you must extend an ataried stone.
4. **Read adversarially.** For each candidate ask: “What is the opponent's strongest reply, including a capture, cut, counter-atari, or refusal to answer?” Continue forcing lines until the groups are stable or the tactical result is clear. A good-looking first move is not enough. Verify the best candidate against at least one different defense.
5. **Compare the resulting positions.** First avoid losing a crucial group. Then maximize secure area, viable groups, useful connections and initiative. Do not prefer a small capture to saving or attacking a much larger group. Count roughly if the game is dividing into territories.
6. **Final blunder check.** After the proposed move, what exactly are the new chain's liberties? Also recheck nearby friendly chains NOT joined to your move; an individually safe move can abandon a neighboring chain to counter-atari. Can the opponent capture it, cut your major groups apart, or destroy their eyes? Is the intended move in Legal moves? Output only that move.

Require a concrete line before declaring a group dead, a ladder successful, or a defense necessary. Mark uncertain judgments as uncertain and prefer moves robust to that uncertainty. Use the current board for every candidate; do not accidentally carry stones or captures from one branch into another. After a quiet move, you need not deeply read every remote group, but before a contact move or capture exact liberty accounting is essential. Never let “I am in atari” substitute for comparing capture, connection and extension. Never let “this move threatens something” substitute for checking what happens if the opponent ignores it.

## 3. How to read captures accurately

A **chain** is the maximal orthogonally connected set of same-color stones. Its liberties are the **distinct empty** orthogonal neighbors of ANY of its stones. Count a shared liberty once. Friendly stones are not liberties; joining a friendly chain gives access to its other liberties. The edge provides no liberties.

For a hypothetical move:
- Place the stone and merge adjacent friendly chains.
- Remove ALL adjacent enemy chains whose last liberty was filled.
- Only then compute the liberties of the resulting friendly chain. Captured intersections may provide new liberties. If the friendly chain still has none, it self-captures under these rules; this is almost never useful and may be forbidden by superko.
- Update liberties of every neighboring chain. A capture may revive a different group or expose a snapback. Do not continue reading with captured stones still present.

**Atari:** a chain with one liberty can be captured there immediately. If your chain is in atari, compare (a) extending, (b) capturing an adjacent enemy, (c) connecting to safety, and (d) abandoning it for more value. Extending blindly can turn a one-stone sacrifice into the loss of five stones. If an enemy is in atari, capturing is a candidate, not an obligation: a strategically useless stone may be less urgent than your own life.

**Two liberties:** Often the real tactical danger starts here. When attacking a two-liberty chain, compare playing at BOTH liberties: one direction may force it toward your strength while the other pushes it into the open region it wanted to enter. An atari which leaves only a dead-end extension can force capture. A move that puts two separate chains in atari may win one (double atari). Before giving atari, check whether the forced extension strengthens the opponent and makes your position worse. Keep pressure by enclosing or cutting when that is stronger.

**Ladder:** Alternate ataris and forced extensions, explicitly following the path until the edge, capture, or a friendly assisting stone changes the liberty count. A ladder does not work merely because its first three moves do. Existing stones anywhere along its path matter. If the ladder fails, use a net or defend the cut instead.

**Net:** Before enclosing an enemy, check the liberties of each surrounding friendly chain. The enemy may counter-atari one of your loose stones and escape by capturing it. Apply countercapture reading to the OPPONENT, not just yourself. Sometimes a loose surrounding move traps a two-liberty group better than direct atari. Read all escape directions. Keep your surrounding stones connected or tactically protected.

**Snapback:** A seemingly capturable stone may be bait: after you take it, your merged chain may have just one liberty, enabling immediate recapture of many stones. Check the post-capture board. Conversely, a sacrifice on a cutting point can create such a recapture for you.

**Capturing race:** Determine each chain's outside liberties, shared liberties, eyes, approach moves, and possible captures. More stones do not imply more liberties. Normally take outside liberties before shared ones; filling a shared liberty also reduces your own. An eye can change which liberties can be filled first. Read the actual alternating sequence, including countercaptures, rather than relying on a raw count alone. Do not start a losing race when you can connect or make eyes.

## 4. Life, death, and connection

A connected group with **two independent true eyes** cannot normally be captured. One large empty region is not automatically two eyes: the opponent may occupy its vital dividing point. Two groups each with one eye are not one living group unless their connection is secure. Escape to the center is useful access to liberties, but is not itself proof of life.

For a one-point eye, all orthogonal boundaries must be your stones or the board edge, and those surrounding stones must survive. Enemy control of two diagonals in the interior, or one diagonal on the edge/corner, can make a false eye. Verify the actual capture possibilities rather than relying only on the diagram. A point surrounded by several separate ataried chains is particularly suspect.

**Life-making priorities:** connect to an already living group; widen the eye space; occupy the vital point that divides it into two eyes; or escape while retaining enough liberties. Do this before being sealed in, not after the opponent has reduced your eyes to one. Corners and sides make eyes cheaply, but also make escape easier to block.

**Killing priorities:** prevent connection and escape, reduce eye space from outside, then occupy the vital point. Do not fill the opponent's eye space at random and donate stones which can be captured to make eyes. A compact three-point straight or bent eye space can often be killed by occupying its middle, while four-point shapes differ: a square four is not automatically alive; straight four usually can form two eyes. Edge defects and outside liberties can alter these patterns. Read rather than merely naming a shape.

If an enemy surrounded group has no chance to live or escape, you need not spend every move filling its liberties immediately. First close escape/cutting defects and take larger moves elsewhere. But under the final scoring rules you MUST capture it before agreeing to finish, unless a literal score count already wins without doing so.

**Connections are strategic assets.** Solid orthogonal connections are reliable. Diagonal contacts and one-space jumps can be cut; they are not already one chain. For diagonal stones, inspect both intervening cutting points. A connection is tactically secure only if the opponent cannot occupy the cut effectively, or you can answer either cut by connecting/capturing. A one-space jump often develops faster than crawling, but near opposing stones a solid connection can be urgent. A cut which separates two weak groups can outweigh several points of territory.

Do not insist on connecting every stone. Sacrifice a few light stones if rescuing them endangers a large group or gives away the whole board. Conversely, a single cutting stone may be strategically worth much more than its one point.

## 5. 9×9 strategy: compact, connected, efficient

On this small board there is little separation between opening and fighting. One weak group or lost cutting battle often decides the game. Aim for two or three coordinated, viable groups rather than scattered isolated stones. Build territory while keeping influence directed toward still-open space.

On an empty board, **E5 is a sound Black opening**: it influences all four quarters. Third- and fourth-line points are also reasonable; do not memorize a long fixed sequence. Against a central stone, White can take a solid corner or a nearby fourth-line foothold rather than immediately attach without a plan. After the first few moves, the board's urgent needs matter much more than an opening template.

The third line (C/G columns, 3/7 rows) balances territory with development; the fourth line emphasizes influence and central access. First- and second-line moves are usually too small in the opening unless required by fighting or securing a base. But do not blindly apply 19×19 “corners before center”: on 9×9, the center and cutting relationships become urgent very quickly.

Prefer moves with **two jobs**: secure a base while expanding territory; connect while attacking; defend a cut while reducing the opponent; gain liberties while threatening capture. Avoid building a thick wall pointing at territory you already own, or adding stones to a group that is already completely safe while the opponent takes the rest of the board.

**Do not confuse safety with overconcentration.** If your group already has a safe route to life, additional nearby stones may be worth almost nothing. Include a move in the largest still-open region among your candidates; the opponent can take that region while you keep polishing a safe group. A small local gain is not automatically better than developing several points of secure area.

**Find the important boundary, not just the nearest fight.** Ask where the opponent would play to split your position or enter your largest prospective territory. Defend that relationship before you are forced into a cramped rescue. A stone with three liberties may be strategically urgent because it anchors an entire side. Conversely, capturing an unimportant isolated stone often gains only a couple of points and can wait.

**Urgent before big.** Save an important weak group or resolve a critical cut before claiming an empty corner. Conversely, do not answer every contact: ask what concrete damage ignoring it allows. Sente means the opponent must answer to avoid a sufficiently large loss, not merely that your move touches their stones. A pointless atari may help them connect for free.

**Attack for profit.** Drive a weak enemy toward your strength, keep it separated from its allies, and take territory or strengthen your own group while it runs. Do not chase from behind and force it to become stronger in the direction it wanted to go. Do not try to kill a group already alive with two eyes. A successful attack need not capture: making secure points while the enemy makes none can win.

**Defend efficiently.** Give a weak group a base on the side, connect it, or run toward friendly strength. Do not begin a second risky fight while your first group is unsettled. If running merely leads into another enemy wall, seek eyes or a sacrifice instead.

**Contact fighting:** Attachment usually strengthens both sides and is useful when you need stabilization or a concrete forcing tactic. Hane can block an opponent's expansion but creates cutting points. “Hane at the head of two stones” is a candidate, not a command; check the cut and ladder. Extend from a crosscut when it gives your stones liberties; do not mindlessly atari all four directions. Avoid empty triangles when a more efficient connection works, but an ugly shape which wins a liberty race is correct.

**Invasion vs reduction:** Invade a large loose region only if you can identify a plausible route to two eyes or an escape/connection. An unsupported stone placed deep inside a sealed enemy region is usually lost. A shoulder hit or boundary reduction often takes enough points with much less risk. If you are behind, you may need a sharper invasion; if ahead, choose reliable reductions and connections over speculative killing.

**Ko:** The current legal list already excludes forbidden recaptures. In hypothetical variations do not assume immediate recapture is allowed. If fighting a ko, find a threat whose ignored consequence is larger than the ko's loss, read the opponent's answer, then recapture only when legal. The opponent can ignore a small threat and finish the ko. Prefer connecting and settling a favorable position to starting an unnecessary ko; a ko may be your best chance when behind. Positional superko can prohibit longer repetitions as well.

## 6. Counting and finishing correctly

Periodically sketch the likely final division. Territorial WIDTH matters, not just the length of your wall. Four full rows or columns contain only 36 points; five contain 45. Even White with komi loses a clean 36–45 division. Do not keep pushing along a parallel boundary that gives you an insufficient strip: seek a wider boundary, a base in another region, or a useful reduction. This is a rough geometric check, not permission to count an invadable framework as secure. Count secure corners/sides, living stones, and enclosed empty points; do not count a wide open framework as guaranteed territory. Estimate unsettled regions conservatively and compare both players' claims. White's 7 points are large on 9×9, but not a reason for Black to make desperate early attacks. Win by efficient territory and sound fights.

When ahead, simplify: protect cutting points and eyes, let irrelevant small stones go, avoid unnecessary ko and races, and deny a large invasion. When behind, look for the biggest plausible swing—cut, unsettled group, invasion, ko—not a series of safe one-point moves that guarantees defeat. Never resign: opponents can err.

In the endgame, compare the **swing** between you taking a boundary move and the opponent taking it. A move that saves three of your points and takes three of theirs is more important than a one-point occupation. Prefer large forcing boundary moves before small nonforcing moves, but do not call a move forcing unless you have checked the threat. Preserve your groups' liberties while filling neutral points; the last dame can expose an atari or a cut.

Before passing:
1. Can I capture any remaining enemy dead stones or prevent an escape that changes ownership?
2. Are all my important groups safe, with cuts and eyes checked?
3. Are there still profitable boundary moves or safe neutral points?
4. If the opponent already passed, what is the **literal current-board score** if I pass now?

For literal scoring, flood-fill each connected empty region mentally: if its stone boundary has only Black, count it for Black; only White, for White; both, neither. Add occupied stones, then komi. Dead stones left on the board are STILL stones and boundaries. Do not count them as removed. If the opponent passed and passing wins immediately, take the win rather than inviting complications. If the literal score loses, do not pass just because ordinary Go convention says the board is finished—remove dead stones or seek a remaining chance.

Once all valuable moves, cleanup and dame are finished, pass. Do not destroy your eyes or play pointless self-captures to avoid passing. In seki, shared liberties may be neutral and neither group can safely fill them; keep the mutual life intact unless exact reading proves a gain.

## Worked patterns: apply the lesson, not the coordinates

### A small capture versus the whole board
Black to move (Z = empty):
```
  ABCDEFGHJ
9 ZWWWZWWZZ
8 WWBBWZWBZ
7 ZBZBWWBZB
6 ZZBZBBBZW
5 ZWZBZBZBZ
4 ZZZZWZBWB
3 ZZZWZWBZZ
2 ZZZZZZZZZ
1 ZBZZZZZZZ
```
White H4 is in atari at H3. Nevertheless, immediately capturing it is too small. Compare C4, B3, and E2: these contest the large unsettled left/lower area, interfere with White's separated stones, and develop Black's position. After the tempting H3 capture, White C4 takes an important junction and the initiative; winning one stone does not compensate. The lesson is to evaluate the opponent's largest reply elsewhere, not just the stones your move removes. A tactical opportunity is not automatically a tactical emergency.

### Trace the entire chain, then count distinct liberties
Black to move:
```
  ABCDEFGHJ
9 ZWWWZWWZZ
8 WWBBWZWBZ
7 ZBZBWWBZB
6 ZWBBBBBBW
5 ZWBBWBZBZ
4 ZBWWWBBWB
3 ZZBWWWBZZ
2 ZZZBWZWZZ
1 ZBZZZZZZZ
```
White's connected chain {C4,D4,E4,E5,D3,E3,F3,E2} has only TWO liberties: E1 and F2. Trace every stone's orthogonal neighbors to verify this. White G2 is a separate stone; empty F2 separates it from the main chain. Thus Black E1 is a forcing atari of eight stones; H2 is not. Black must also consider the crucial connection B3 for its vulnerable left-side stones. E1's forcing attack or B3's connection is much more valuable than a small move around the right edge. Do not estimate liberties from a group's size or from nearby empty points which are not actually adjacent.

### Protect the stones doing the surrounding
Black to move:
```
  ABCDEFGHJ
9 ZZZZZZZZZ
8 ZWBZZZZZZ
7 ZWWZBZZZZ
6 ZBZZZZZBB
5 ZZZBBBZBW
4 BBBBWBBWW
3 WWWWWWWWZ
2 ZZZZZZZZZ
1 ZZZZZZZZZ
```
Black C8 has only C9 and D8 as liberties. The natural-looking D7 to surround White allows White D8, atari on C8. Trying Black E8 as a counter-atari fails to White C9: White captures C8 and thereby saves D8. Black D8 FIRST protects C8 and prevents this cutting/capturing mechanism. When enclosing a group, verify your enclosing stones' liberties before blocking its apparent escape. A loose net whose supporting stones can be captured is not a net.

## Final reminder

Read chains, not pictures. Count distinct liberties, simulate captures before judging self-atari, and test your move against the opponent's best response. Favor secure, connected area over unsupported ambition. Recheck the current legal list, then answer with the coordinate or `pass` alone.
