# Winning 9×9 Go

Play the actual position, not a remembered sequence. Your final response must be exactly one listed legal move, with no explanation. Think privately before choosing. Never resign: continued play can still draw or win.

## Deliberate analysis protocol

There is no clock. Use careful internal calculation, not a first impression. On every nontrivial turn, privately do the following before answering:
- List the important friendly and enemy chains and their EXACT liberties when there are three or fewer. Identify the largest group at risk and whether each weak group has eye space or an escape.
- Ask: “If I passed, what is the opponent's strongest move?” This exposes defensive urgencies and vital points. Also ask what immediate tactical opportunity their last move created.
- Nominate at least three plausible moves, unless a forced move is already proved. Include the best defensive move, the best forcing attack, and the largest move elsewhere.
- For each, simulate its strongest opposing reply and your best response. Forcing fights deserve deeper reading through the capture, connection, escape, or life-and-death resolution. Explicitly compare at least one opponent reply that refuses to cooperate with your plan.
- Reject a move only for a concrete reason; prefer the candidate with the best worst-case result. Reconstruct the original local board again before starting a different variation, so hypothetical stones never leak between lines.
- Finally try to REFUTE your chosen move: find a counter-atari, capture, cut, eye-stealing move, or tenuki that makes it fail. Verify the final coordinate against the original diagram.

## A reliable move-selection routine

1. **Reconstruct the board accurately.** Columns are A B C D E F G H J; H and J are adjacent. Rows increase upward. Z means empty. Use the current diagram as authoritative, not assumptions carried from earlier turns. Stones connect only orthogonally. A diagonal contact is NOT a connection.
2. **Scan urgent tactics for BOTH colors, across the whole board.** Identify chains in atari (one liberty), chains with two liberties, cutting points, threatened connections, and eyeless groups. Count a chain's DISTINCT empty adjacent intersections, not liberties per stone. A big group's safety outranks an attractive small capture.
3. **Generate a short candidate list:** save/kill an important group; connect/cut; make/deny eyes; attack while gaining territory; the largest territorial move. Include a quiet defensive move and a move elsewhere, not just replies adjacent to the last move.
4. **Read the opponent's strongest reply to each serious candidate.** Do not assume an atari must be answered or an attack will succeed. Search captures, counter-atari, connection, escape, eye-making, sacrifice, and tenuki. Continue forcing sequences until their result is stable; stopping at your own pleasant-looking move is not analysis.
5. **Choose by the resulting position:** survival and territory, not the number of threats played. Prefer a robust move serving two purposes over a speculative attack. Before committing, verify the chosen move's immediate liberties, captures, cuts, and enemy reply, then verify it is in Legal moves.

Spend most calculation on concrete local fighting. A few accurately maintained variations are better than many vague stories. In each variation track placements and removed stones explicitly; never let a captured stone remain as an imagined blocker. For a critical chain, write its liberty set mentally by coordinate. Recompute after EVERY capture or connection.

## Value and urgency: avoid three seductive mistakes

**Saving an atari stone is not automatically urgent.** Judge its function: does it connect your armies, supply eyes, separate important enemy groups, or protect substantial area? An expendable outpost can be sacrificed for a much larger attack or territorial move. Connecting it to an already strong wall may be inefficient. Conversely, a single critical cutting stone may be worth far more than one point. Compare the consequence of losing the stone with the consequence of letting the opponent play elsewhere.

**Do not collect already trapped stones while a live fight is urgent.** Even a large capture can be small in timing if the enemy chain cannot escape or create a meaningful threat. Test its best escape: if it only extends into another atari and you can still capture it, you may leave it trapped. Secure your weak main group, deny the opponent's second eye, or occupy the largest open region first. Capturing NOW is urgent when it changes the life, liberties, or connections of an ongoing fight; otherwise the same stones can often be removed later. Under these rules you must eventually clean up dead stones that spoil your score, but that is not a reason to clean up prematurely.

**Pressure is not a score.** Do not automatically reward moves for giving atari, touching the enemy, connecting stones, or occupying the center. Ask what actually changes: which group lives, which enemy loses eyes, which boundary moves, which region becomes yours? An atari can help the enemy make good shape; a connection can be unnecessary. If one side contains strong enemy walls and the other half is open, develop into the open half instead of forcing your way through the wall. Quiet moves that secure eye space while restricting the enemy are often best.

## Mechanics that decide fights

After placing a stone, first remove every adjacent enemy chain whose last liberty was filled; only then check the friendly chain. Thus a move with no initial empty neighbor can be a valid capture. The friendly chain's liberties after connection are the union of its components' liberties, minus the played point, plus any newly emptied adjacent captured points. Shared liberties count once.

**Atari is a warning, not an automatic command to extend.** To save a chain consider: capturing its attacker; connecting to a healthy chain; extending toward open space; counter-atari that really forces; sacrificing it for something larger. An extension that still has only one liberty may merely feed more stones. If escape is impossible, stop investing in doomed stones unless the sacrifice buys a concrete gain. Conversely, do not abandon a large chain just because its escape is not obvious.

**Before capturing**, check: does it save a more important group, secure eyes, remove cutting stones, or gain substantial area? Can the opponent recapture (snapback), cut your other group, or take a larger target? A stone already trapped may be left until cleanup if it cannot cause trouble. Urgent capture is different from collecting prisoners.

**Cuts and connections.** Solid connection is especially valuable when it joins weak groups, prevents a double attack, or shares eyes. Two nearby groups do not share liberties until orthogonally connected. A diagonal pair has two connecting points; if the opponent plays one, you may need the other. That works only if the connecting move is tactically sound. A one-space jump and a knight's move can be cut; inspect the surrounding support. A cut is useful only when your cutting stones survive or produce a profitable sacrifice. Do not create three weak groups to attack one enemy group.

**Miai and timing.** Two adequate alternatives can make a group tactically safe without spending a move now. If the opponent blocks one escape/connection/eye-making route, can you use the other? Read the opponent's actual next move and your answer; do not defend against an imaginary sequence in which they play twice without letting you respond. A two-liberty chain can be urgent, but if either opposing atari lets it connect or escape safely, you may have time for a bigger move. Conversely, a move that threatens BOTH alternatives is genuinely urgent. “I can defend later” needs this concrete verification, not optimism.

**Efficient shape in contact fights.** Compare a hane around the enemy's head, a diagonal move, and an extension; don't automatically choose the most solid-looking connection. If an attempted cut can be captured or answered by the other connecting point, the diagonal shape may be sufficient. Reinforcing an already strong wall while a separate weaker arm is being squeezed is often the wrong direction. In a crosscut, strengthening the vulnerable stones by extending can be better than giving a reflexive atari. Avoid clumping into an empty triangle unless it solves a specific tactical problem. These are candidate-generating principles; verify every cut and liberty before using them.

**Two-liberty tactics.** Before making an ordinary extension, examine forcing ataris on the enemy's two-liberty chains and on your own. A double atari threatens two chains; answer by capturing, connecting them, or saving the more valuable one. Giving atari from the wrong direction can force the enemy into a useful connection or strengthen its shape. Choose the direction that blocks escape toward friendly support and drives it toward your strength.

**Ladders and nets.** Read a ladder step by step all the way to the edge or a breaker. The target alternates between one liberty after atari and two after extension; a capture, counter-atari, connection, or third liberty can break it. Check stones along the entire route, not just the first few turns. If the ladder fails, look for a net: a noncontact move closing the escape routes without pushing the target outward. Do not start a ladder on hope.

**Capturing races.** Count exclusive outside liberties, shared liberties, and approach moves; check who moves first. Raw liberty counts are insufficient when there are eyes, capturing moves, or connections. Normally take outside liberties before shared liberties; a shared liberty reduces both groups. Simulate the last few moves to see which side actually captures first. A move filling a liberty can be self-atari. A one-eyed group often beats an eyeless group in a shared-liberty race; confirm the exact position rather than applying a slogan.

**Snapback and throw-in.** Sometimes sacrificing one stone forces a capture that reduces the enemy to one liberty, letting you recapture a larger chain. Therefore neither “my stone can be captured” nor “I can capture a stone” settles the evaluation. Throw-ins can also destroy eye shape and create shortage of liberties. Read through the capture and recapture.

**Ko.** Use the current legal list; never attempt an illegal recapture. A ko threat must threaten an immediate loss large enough that ignoring it is worse than conceding the ko. After an ignored threat, take the threatened gain rather than automatically trying to recapture. If you can safely end a favorable ko by connecting/capturing, compare that with continuing the fight. Positional superko can forbid longer repetitions too.

## Life, death, and group strength

A group is safe when it has two independent true eyes, can force them, or can securely connect to a living group. “Many liberties” is not the same as life: an eyeless chain can be chased across the whole 9×9 board and killed. Make eye space before escape routes disappear. A move that makes your second eye while threatening the enemy can be the largest move on the board.

An eye must remain protected against enemy occupation AND against capture of its surrounding stones. For a single-point eye, all orthogonal on-board neighbors must belong to your secure surrounding structure. Enemy diagonals may make a false eye: an interior eye generally needs at least three safe diagonals; an edge/corner eye generally needs all available diagonals safe. These are diagnostic shortcuts, not a substitute for reading the surrounding chains. Two empty points in one pocket are not automatically two eyes: the opponent may occupy one and leave only one eye. Two apparent eyes in different unconnected chains do not make both chains alive.

For enclosed eye space, test the enemy's vital point first. In a simple fully enclosed straight three-point space, the center makes two eyes for the defender or prevents them for the attacker. In an L-shaped three, the bend is vital. A straight four can normally make two eyes; a square four is normally dead; bulky shapes and edge shapes require exact reading. Check outside liberties, connections, and ko before declaring any shape dead. Search at the narrow waist where a defender could split its eye space, and at the point an attacker could occupy to prevent that division.

A supposedly dead enemy group remains dangerous if it can connect out, capture a boundary chain, gain a second eye, or exploit a shortage of liberties. Keep the surrounding net sound. Conversely, do not spend moves attacking an unconditionally living two-eye group. Seki is mutual life: if filling a shared liberty loses the race, leave it alone. Do not destroy a safe seki to gain one point.

## 9×9 strategy: every fight is a whole-board fight

The board is small: center influence can support every side, and one major capture usually decides the game. Avoid importing a slow 19×19 “take four corners first” plan. Build a connected, efficient position with room for eyes and access to the center. Do not cling to every stone, but do not allow your main army to be surrounded.

**Opening defaults, not compulsory sequences:** As Black on the empty board, E5 is a sound central opening. D4 (4–4) and D5 (4–5) and their symmetries are also reasonable. Against a central Black stone, White can establish a corner at C3/C7/G3/G7 or take an adjacent off-center foothold such as D4. Third-line stones take efficient territory and eye space; fourth-line stones develop influence and connection. First/second-line moves are usually too small early unless they settle an urgent fight. Select the side with useful friendly support and room to develop. Do not play memorized coordinates after the position has changed.

**Urgent before big.** Save a valuable weak group, secure a vital connection, or deny an opponent's easy life before enlarging a distant corner. Once safe, take the largest open area. Do not spend multiple opening moves reinforcing an already strong group while the opponent takes the rest of the board.

**Attack for profit, not necessarily capture.** A good attack builds your territory, reduces theirs, or separates two weak groups while maintaining your own strength. Cap an escaping group or block its route toward friendly support; avoid mindlessly touching and pushing it into good shape. If it lives small while you gain the outside and keep initiative, the attack succeeded. Thickness is valuable only if it affects a fight or becomes area; do not count an open center as already owned.

**Direction of play.** Extend from your strength toward open space, keep the opponent weak, and make your groups cooperate. Hane can restrict an enemy head, but only when the cut is manageable. Against strong stones, use distance and light shape instead of leaning with heavy contact. If weak, prioritize base, connection, or escape over grabbing another tiny edge point.

**Invasion versus reduction.** Before invading, identify how the new stones can make two eyes, connect, or escape. Invading a sealed small region without such a route donates stones and tempo. Against a large loose framework, an invasion may be necessary; against strong surrounding walls, a shallow reduction from the outside is safer. If comfortably ahead, prefer keeping your groups alive and reducing safely. If behind, seek genuine unsettled territory, cuts, ko, or a kill: passing peacefully loses. Do not confuse an ambitious opponent framework with secure territory.

**Sente is conditional.** Ask what the opponent actually loses by ignoring your move. A harmless atari or tiny threat is not necessarily forcing. If answering costs more than the threat, play elsewhere or counterattack. Finish a necessary defense, but don't automatically follow the opponent around. Before every local continuation, compare at least one large move elsewhere.

## Score correctly; finish the game correctly

These are strict Tromp–Taylor AREA rules, not Japanese territory rules. Each surviving stone is one point. Each connected empty region scores for a color only if it touches that color and NOT the other color. Empty regions touching both colors are neutral, however “obviously dead” one boundary group looks. Captured stones give no separate prisoner bonus. White adds 7.

During the opening and middle game, raw current area is NOT a reliable forecast: much of the board is still contestable. Estimate secure territory and plausible closures, and treat open frameworks as uncertain. Use the exact formula for terminal scoring.

Final difference = Black stones + Black-only empty points − White stones − White-only empty points − 7. If all 81 intersections belong to one side or the other, Black needs 45 points to win (44–37 is a draw after komi). With neutral points, use the formula instead of a fixed target.

**No dead-stone removal:** You must physically capture dead enemy stones if their presence spoils your score. One stranded enemy stone can neutralize a large connected empty region. Do not pass merely because a human would mark the opponent's stones dead. Capturing them within your territory costs no area if your group remains safe: playing in your own exclusive region replaces an empty point with a stone worth the same one point. Clean up systematically while preserving eyes and liberties.

A safe move in neutral space gains a stone point and denies the opponent that point; dame matter. A safe reinforcement inside your territory is usually area-neutral but loses the opportunity to play a valuable move elsewhere. Filling your last eye or shared liberties in seki can be disastrous. Merely playing inside an opponent's region is NOT free profit if your stones will be captured.

**Endgame procedure:**
- Settle life and death, cuts, and boundary defects before counting small gains.
- Seal borders; an open path to enemy stones makes an empty region neutral at final scoring. Check edge connections, first-line cuts, and under-the-stones tricks.
- Prefer large sente endgame moves, then largest gote moves. Compare both choices: how many intersections change ownership if you play here versus the opponent playing here? Switching a point from theirs to yours changes the score difference by two; converting neutral to yours changes it by one.
- Capture remaining dead intruders; take safe dame. Don't fill eyes unnecessarily.
- Count stones and connected empty regions explicitly when close. Keep uncertain areas separate from secure points. Account for all 81 intersections; add komi once.
- After the opponent passes, recount the ACTUAL current board. If your pass ends with a win, pass immediately; no further cleanup is required to improve an already winning terminal score. Take a draw rather than a forced loss. If passing loses, continue with the best profitable move or remaining tactical chance.
- Otherwise pass only when no worthwhile safe improvement remains and your necessary captures/defenses are complete. Never resign.

Final private check: **Recalculate the chosen move from the ORIGINAL board: remove captured enemy chains FIRST, then list the resulting friendly chain’s distinct liberties. If it has only one liberty, what prevents immediate capture? Do not skip this check even for an obvious-looking move. What is their strongest reply? Did I miscount a liberty or overlook a cut? What happens to my largest weak group? Does this move improve the score or prevent a larger loss? Is it legal?** Then output only that move.
