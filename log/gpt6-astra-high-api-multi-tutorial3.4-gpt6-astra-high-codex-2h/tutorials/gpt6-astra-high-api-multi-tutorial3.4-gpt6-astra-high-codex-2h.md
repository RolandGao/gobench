# 9×9 Go: a practical playing method

Your goal is to win the actual position, not to produce Go commentary. Think privately; output exactly one entry from the current Legal moves. Never resign: even in a bad position, keep seeking chances. The current board and legal list override remembered variations.

## 1. See the position accurately

Columns are A B C D E F G H J (no I); rows increase upward. Only orthogonal neighbors connect. A diagonal pair is NOT a connected group. Edges reduce liberties, not increase them.

Before choosing a move, identify the unsettled groups and count their **distinct empty neighboring intersections**, not empty directions per stone. Two stones sharing a liberty contribute only one liberty. For each relevant group, remember its stones, liberties, and whether it has two secure eyes or a reliable connection to life. A long chain may still have only two liberties.

In tactical reading, actually update the board: place the move, merge orthogonally adjacent friendly chains, remove all adjacent enemy chains with zero liberties, then remove any friendly zero-liberty chain. Captures can create liberties or break connections. Recount after every move; don't infer survival from the old liberty count. Legal does not mean sensible: suicide is permitted here but usually terrible.

Use a small local ledger when necessary. For example, on an otherwise empty board, stones at D4, E4, and D5 form one chain with liberties {C4,D3,F4,E3,E5,C5,D6}: seven, not eight, because E5 is shared and counts only once. Concentrate exact bookkeeping on the fight, not every settled stone. At a new turn, verify previous conclusions against the displayed board rather than continuing an imagined sequence.

## 2. Move selection: tactics, then whole-board value

On every turn:
1. **Emergency scan:** Which of either player's chains have one or two liberties? Are there immediate captures, double ataris, cuts, or threats to a large group's eyes? What did the opponent's last move actually threaten? Check all the board, not only the last move.
2. **Find 3–5 serious candidates:** an urgent defense/counterattack, a forcing attack, the best connection/cut or eye-making move, and the largest territorial move. Sometimes playing elsewhere (tenuki) is best. Avoid spending all your thought on the first plausible move.
3. **Read the opponent's strongest reply**, not the reply you hope for. For a critical fight, explicitly consider “my move → their best reply → my answer → their next forcing move.” A move is not safe merely because it survives the first reply. Test ataris, captures, cuts, connections, and vital eye points. Continue forcing lines until chains escape, connect to life, die, or reach a stable position. Usually a short accurate variation is worth more than a long speculative story.
4. **Compare the resulting positions:** survival of essential groups, secure area, weak groups, initiative, and remaining threats. Reject a move whose only justification is that the opponent overlooks a direct refutation.
5. **Final blunder check:** Is the coordinate empty and legal? After my move, exactly how many liberties does my affected chain have? Can it be captured immediately? Can the opponent save the target by capturing a different chain? Did I leave another important chain in atari? Then output the move alone.

**Do not let small forcing moves distract you from life-and-death.** An enemy stone in atari may already be doomed and can be captured later. Capturing it now can be a blunder if a much larger enemy group then makes its second eye or escapes. Compare the value of each group and ask what becomes irreversible if you postpone the vital move. Likewise, a safe capture is not automatically better than a quiet move that prevents a huge loss.

A chain in atari is not automatically worth saving. Small expendable stones may be sacrificed for a larger gain. Conversely, saving one stone that connects two large groups can be decisive. Evaluate consequences, not just stone counts. Capture threatened enemy stones before mechanically extending your own ataried chain if the capture solves the problem better.

## 3. Read fights rather than obeying slogans

**Atari:** A chain with one liberty can be captured there. Before attacking, ask where it runs and whether your atari helps it connect or gain tempo. Nonforcing containment, a net, or occupying its escape route can be stronger than chasing. Before defending, consider extending, connecting, capturing the attacking stones, counter-atari, and sacrificing.

**Two-liberty chains:** Examine both liberties, especially when a move threatens two chains simultaneously. A move can look safe but leave a new combined chain with one liberty. Do not join a healthy chain to doomed stones without recomputing the combined liberties.

**Cutting:** A cut is valuable only if the cutting stones can survive or obtain sufficient compensation. Check both sides' ataris before cutting. When two friendly groups need to connect, prefer a connection that also gains liberties or prevents a decisive enemy connection. A solid connection is slower but reliable; a diagonal or jump is only tactically connected.

**Ladders:** Read the actual alternating ataris to an edge or a friendly stone. Track the escaping chain's liberties at each step. A distant stone can break the ladder; do not assume the familiar zigzag works. If a ladder fails, look for a net or abandon the capture. Do not play out a failed ladder and hand over a huge chain.

**Nets:** Block the escape route a little ahead of the stones instead of forcing them outward with atari. Read every immediate breakout and capture before declaring the net successful.

**Snapback:** An apparently capturable stone may be bait: after the opponent captures it, their merged group can have just one liberty, allowing a larger recapture. Always inspect the position AFTER capture. A single-stone recapture may be ko instead, depending on the resulting liberties and repetition.

**Capturing races:** Count external liberties, shared liberties, approach moves needed to fill safely, and eyes for BOTH sides. Simple “I have four, they have three” is reliable only when the liberties can be filled directly and no captures, connections, or eyes intervene. In ordinary eyeless races, fill the opponent's outside liberties before shared liberties. Filling a shared liberty also reduces your liberties. A move that adds your liberty while removing theirs is especially powerful. One genuine eye can radically change a race; read rather than applying the simple count. A mutual inability to capture may be seki: don't destroy it by filling shared liberties.

**Ko:** The current legal list is authoritative. When recapture is forbidden, find a real threat whose ignored consequence matters at least as much as losing the ko; after the answer, recheck whether recapture is legal. If the ko is too costly, settle it or take compensation. Don't assume every atari is an adequate threat. Positional superko forbids recreating ANY earlier board, not merely the last one.

## 4. Life, death, and useful shape

**Scan for eye-critical groups even when they have many liberties.** For every enclosed or nearly enclosed large group, locate its existing eyes and its possible second eye. Identify the intersection that would either make or destroy that second eye. A five-liberty group with one eye and a single vulnerable eye-making junction can be more urgent than a two-liberty disposable stone. Do this for the opponent as well as yourself; taking the vital eye point often wins the whole fight without a long atari chase.

A group is unconditionally alive when it has two separate genuine eyes that the opponent cannot remove. Two empty points in one connected cavity are not automatically two eyes. A large open region is potential eye space, not proof of life. A group with many liberties but no eyes can die after being surrounded; a two-eyed group needs no defensive moves unless its eye boundaries can be captured.

**Two ways to succeed:** If you can either connect out or make eyes, preserve that flexibility. Threatening two independent ways to live is often better than prematurely committing to one. Conversely, attacking requires closing both the escape route and the eye-making possibility; surrounding only one side does not prove a kill.

An eye must be enclosed by a boundary that survives. Check diagonals and cutting points: a supposed eye can be false if its surrounding stones can be put in atari and captured. Capturing an intruder inside a single eye does not by itself produce a second eye. Ask: “If the opponent plays the vital point first, can I still make two separate eyes?”

When defending a weak group, compare:
- connect to an already safe group;
- make two eyes or secure enough space to do so;
- escape toward open center with useful liberties;
- counterattack an equally weak enemy;
- sacrifice part to save the important part.

Don't merely run a huge eyeless chain across the board. Give it a base/eyes while there is still room. Do not connect two weak groups if that creates one large group with no eyes and no escape.

In small enclosed eye spaces the vital point is often the center or the junction that splits the space. A straight three-point or bent three-point eye space generally hinges on playing its middle first; four points arranged as a square do not automatically live. Larger shapes depend on surrounding liberties and boundary defects. Read local placement, responses, captures, and resulting eyes; don't rely on shape names alone. Attack by reducing eye space from outside or occupying its vital point; defend by dividing it into two independent eyes. Avoid repeatedly playing doomed stones inside a secure two-eyed group.

Useful shape gives liberties, connections, and eyes with few stones. One-space jumps and knight moves can develop efficiently in open space but are cuttable under pressure. A diagonal connection with both intermediate points available is often tactically sound because either can connect; if one is occupied or threatened, verify the remaining connection. On contact, extending can increase liberties; a hane (a diagonal bend around an enemy stone) can constrain the opponent but invites a cut. “Hane at the head” is a candidate, not a law. Avoid empty triangles unless they solve a concrete tactical problem.

## 5. 9×9 strategy: every fight is whole-board

The board is small: central stones influence several sides, and one lost group can decide the game. The practical opening aim is efficient development with connected influence, a base, and room for eyes—not memorizing 19×19 joseki.

On an empty board, E5 is a sound Black opening; central fourth-line points and 3–3/4–4 corner development are also possible. As White against E5, C4 (or a symmetric 3–4 point) is a flexible starting point; C5/E3 and C3 are also playable. After that, react to the position rather than following a fixed sequence. Prefer third/fourth-line development, useful central extensions, approaches, enclosures, and separating weak opponents over early first/second-line crawls. Low plays are excellent when they secure life, undercut a base, or capture; poor when they surrender the whole center for a few points.

A few sound opening seeds, **only for these exact positions from an empty board** (moves alternate Black, White; symmetry-equivalent versions also apply):
- `E5, C5` → Black `G6` (or `G4`): develop the other side efficiently.
- `E5, D5` → Black `D6` (or `D4`): hane around the attachment; read the subsequent cut.
- `E5, C3` → Black `E3` (or `C5`): approach the low corner.
- `E5, C4` → Black `D3`: approach from below.
- `E5, C4, D5` → White `D3`: strengthen the lower base rather than automatically contacting every central stone.
- `E5, C4, D5, D4, E4` → White `B6`: expand on the open side instead of another crowded contact.
These seeds are not a script for later turns. Once the position differs, use tactical reading and whole-board judgment.

Corners need fewer stones to enclose territory than sides, and sides fewer than center. However, on 9×9 you cannot simply take several low corners while the opponent surrounds your groups. Balance territory with central access and connectivity. Do not scatter isolated stones in all four corners. Build a coherent position and keep the number of weak groups manageable.

**Attack to profit, not necessarily kill.** Against a weak group, take its base, limit its eyes, separate it from help, or push it toward your strength while making territory and strengthening yourself. Chasing it toward YOUR weak stones may help the opponent. If you cannot prove a kill, don't spend many moves trying: gain secure points or initiative. Stop attacking once it lives; turn to the next valuable area.

**Weak groups before big points.** An urgent move that prevents a large loss outranks an ordinary corner extension. But don't defend a safe group just because the opponent played nearby. Ask what happens if you ignore the move. A harmless invasion may be best contained or allowed a small life while you secure more elsewhere.

**Do not answer automatically.** In a sequence of parallel enemy and friendly extensions, stop and ask whether the next enemy push actually threatens a cut, capture, or loss of life. If not, a jump ahead, a base, or taking the open side may dwarf another obedient extension. Likewise, saving a peripheral stone can be much smaller than securing an entire side. The last move is evidence, not a command.

**Influence is not territory.** Count an open framework conservatively. Invade early enough to have room for two eyes or a route out; reduce from outside when a deep invasion would simply die. Avoid attaching to a strong enemy unless you have a concrete life-making or forcing sequence. Against a lone stone, an approach at a distance often preserves flexibility better than immediate contact. Contact tends to strengthen both players.

**Watch the ends of walls.** A long wall does not secure the empty region behind it if the opponent can turn around its end, especially along the first line. Before calling a side yours, trace the enemy's entry routes around both ends and through gaps. A block or connection sealing off twenty points may look like a small edge move but outranks an ordinary extension. If an invader needs only one more extension to make eyes, prevent that extension now rather than chasing it afterward.

**Trade intelligently.** Let the opponent take a small corner if the exchange gives a larger secure region, capture, or strong attack. Do not rescue doomed stones because you already invested moves in them. Conversely, do not let a key central chain die for scattered side points. When ahead, simplify and remove defects without giving away the lead; when behind, seek realistic invasions, cuts, ko, and complications, not passive small endgame.

Komi is 7: White can accept an even-looking board; Black needs a real territorial/area advantage. This is not a reason for Black to overplay or White to be passive. First preserve soundness, then find the biggest gains.

## 6. Exact rules and the endgame

This is **strict Tromp–Taylor area scoring**, with **no automatic dead-stone removal**:
- Each stone on the board scores one point for its color.
- Each connected empty region scores for a color only if it touches stones of that color and no opposing stones.
- White adds 7 komi. Captured prisoners do not score separately.
- Stones judged “dead” still remain and count unless actually captured. Enemy stones left inside your territory can make the surrounding connected empties neutral. To claim that area, you must physically capture them; never expect the referee to remove them for you.

Do not confuse a secure territory estimate with the literal score of an unfinished board. For planning, estimate what can be secured with correct play. At the end, flood-fill mentally: trace empty regions and inspect all their bordering colors. A tiny open connection to an opponent stone makes the entire connected empty region neutral, even if it visually looks like your territory. Count stones row by row, then empty regions; black area + white area + neutral points must total 81.

If all 81 intersections ultimately belong to one side or the other, Black needs at least 45 area points to win: 44–37 becomes a draw after komi. With neutral points, use B area minus W area minus 7 directly. For White, reverse the sign.

**Area-scoring implications:**
- Filling a point already securely yours ordinarily replaces one territory point with one stone point: net zero. It is safe cleanup when necessary, but may waste a tempo while valuable points remain.
- Occupying a neutral dame with a surviving stone gains one point. Don't pass while useful dame remain. Check that dame filling doesn't put your group in atari or destroy seki.
- Capturing dead invaders can gain much more than their stone count by reclaiming the surrounding empty region.
- In a truly settled position, extra safe moves inside your own area usually do not cost points; unnecessary eye-filling can still kill you. Preserve two eyes.

**If the opponent just passed and the literal current Tromp–Taylor score is a win for you, pass and take the guaranteed win immediately.** You need not maximize the margin. Verify by counting stones plus exclusively bordered empty regions, with dead stones still present. If ending now would lose or draw and you have a credible improvement, continue.

Otherwise, before pass: (1) every important friendly group is alive, (2) enemy stones that spoil your territory have been captured, (3) no profitable invasion, reduction, boundary play, or safe dame remains, (4) your territory is actually sealed, and (5) if the opponent just passed, ending now is the best available result. An opponent's pass does not certify that their stones are alive or that scoring is settled. If you are behind, check for real improvements before accepting defeat; if none exist, passing is better than destructive self-capture. Never resign.

In endgame, compare the difference between you taking a boundary point and the opponent taking it, not just how many empty points are beside it. Prioritize moves that threaten a large follow-up while gaining points, then larger nonforcing moves, then smaller boundary moves and dame. Sente means the opponent actually must respond to avoid a significant loss; don't imagine every small atari is sente. Secure a dangerous cut before cashing a one-point move if the cut could lose a group. Recount close games after captures and major boundary changes.

## Final discipline

Be concrete: groups, distinct liberties, eyes, forced replies, area. Prefer a robust move with two purposes over a clever move needing cooperation. Spend the most reading on irreversible fights and life-and-death; don't burn effort narrating settled regions. Maintain a tentative plan across turns, but treat it as revisable: the next actual opponent move may invalidate the expected line. Always inspect their best resistance and perform the final one-move blunder check before emitting one legal coordinate or `pass`.
