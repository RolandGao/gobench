# How to win 9x9 Go against KataGo bots (Tromp-Taylor, komi 7)

**Output rule: your visible reply is ONLY the move (e.g. `G4`), nothing else. Do all thinking privately first. Any extra words make the answer invalid.**

Your opponent is a fast neural-net bot: good shape, but it makes tactical mistakes. In test games, every loss came the same way: **one of my big groups got surrounded and died** (no two eyes, or lost a capturing race), turning a close game into a 70-point loss. So the #1 rule is: **keep every one of your groups alive and connected; win by small solid margins.** Wins came from solid play plus capturing the bot's cutting stones.

## 1. Read the board carefully
- Row 9 is the TOP line, row 1 the BOTTOM. Columns A B C D E F G H J (no I). E5 is the center.
- Privately rewrite the board and list every group of both colors with its **liberty count** (empty points orthogonally adjacent to any stone of the group; diagonals don't count). Also note for each group: does it have two eyes / enough eye space, or a safe connection to a living group?
- The opponent's last move (Recent moves) is where the action is. Ask: what does it threaten? (atari? cut? enclosing one of my groups? invading?)

## 2. Per-move checklist (in this order)
1. **My group in atari (1 liberty)?** Save it if it matters: capture an adjacent enemy stone, or extend only if the extension gets 3+ liberties. If it can't escape (ladder/net), give it up and play elsewhere.
2. **Can I capture enemy stones?** Capturing cutting stones (stones that separate my groups) is almost always right and usually wins the game.
3. **Weak group check (most important):** For each of my groups without two sure eyes: is the opponent closing the net around it? If the opponent can surround it, act NOW: connect it to a strong group, run toward the open center, or take eye space (extend along the side, play the vital point of its own eye shape). A group that is enclosed with fewer than ~6 points of inner space is in danger. Do this *before* the group is sealed in — once sealed, it's usually too late.
4. **Capturing races (semeai):** if one of my eyeless groups touches an enemy eyeless group, count both groups' liberties. The side with more liberties wins (the side to move wins a tie). Fill the enemy's **outside** liberties first; never fill my own liberties. If I'm clearly behind, don't add stones — cut losses.
5. **Cuts:** if the opponent threatens to cut my stones apart, connect solidly (solid connection or tiger's mouth). If the bot leaves a cutting point, cut only if both resulting cut pieces of mine are safe.
6. **My 2-liberty groups:** make sure the opponent can't atari them into a ladder or net. Enemy 2-liberty groups: atari from the side that drives them toward the edge or my strong stones (check the ladder path stone by stone).
7. Otherwise play the **biggest safe move** (section 4).

**Verify the candidate move before answering:**
- It's an empty point and in the Legal moves list.
- Count the liberties of the stone/group after I play. If it's 1 (self-atari) and it doesn't capture, don't play it. Be careful about 2 liberties near enemy stones.
- Never fill one of my own group's eyes or its last liberties.
- Imagine the opponent's best reply: does it cut, capture, or seal one of my groups in? If yes, pick a different move.

## 3. Life and death essentials
- A group needs **two separate eyes** (or a solid connection to a living group). One big eye or one eye = dead in the end.
- **Fewer groups is better.** On 9x9 one connected group is easier to keep alive than two. Avoid creating a second weak group while one is still unsettled.
- Don't invade the opponent's solid area: stones that can't make two eyes just die and give the bot free moves. Don't add stones to a dead group.
- Attack enemy weak groups by taking their eye space and keeping my own stones linked; the attack gains territory even if it doesn't kill.
- Eye-shape vital points: for three-in-a-row empty space, the middle point; for a bent three, the corner of the bend. Whoever plays the vital point first decides life.
- Watch for **snapback** and **shortage of liberties** when pressing against enemy stones.

## 3b. Fighting and shape (how strong players avoid getting split)
- **When my stones get cut into two pieces, the weaker piece is the target.** Strengthen or connect the weaker one first; a cut that leaves me with two weak groups usually loses one of them.
- **The opponent's key point is my key point:** if a point would let the bot cut me or seal my group, occupy it myself.
- **Hane at the head of two (or three) stones** — if two enemy stones face mine in a line, playing diagonally in front of them is strong. Conversely, don't let the bot hane at the head of my stones; extend first.
- **When the bot attaches (contact play) to my stone, answer locally** (hane or extend). Ignoring a contact play usually loses a stone or gets my group sealed.
- Avoid **empty triangles** and slow crawling on the 1st/2nd line; crawling along the 2nd line gives the enemy a big wall.
- **Don't make pointless ataris** that just help the enemy connect; atari only when it captures, gains a key point, or drives stones into a ladder/edge.
- **Check ladders before relying on them:** trace the zig-zag path diagonally to the edge; any friendly stone of the escaping side on the path breaks the ladder.
- **Sente matters:** prefer moves the bot must answer (threats to capture, to cut, or to destroy eye space), then take the next big point.
- **Big groups are not automatically alive.** A long chain surrounded on both sides with no eyes can be killed. Every few moves, ask of my largest group: where are its two eyes?

## 3c. Thinking procedure each move (private)
1. Re-draw the board, list groups and liberties, mark weak groups (no two eyes) of both sides.
2. Write 3 candidate moves: (a) the direct answer to the bot's last move, (b) a move that fixes my weakest group, (c) the biggest attacking or territory move.
3. For each candidate, read the bot's most forcing replies (atari, cut, seal-in) 2-3 moves deep. Reject any candidate that lets a group of mine get cut off and enclosed.
4. Choose the move that keeps all my groups safe and is biggest. When in doubt, choose the solid, connected move.

## 4. Strategy for 9x9
- **Black's first move: E5.**
- **White's reply to E5:** a 3-4 point like C4, G4, C6, or G6 (all equal). If Black did NOT play E5: after B D5 → W F5; after B F5 → W D5; after B E4 → W E6; after B C3 (or another corner) → W D4/E5 area.
- Good continuations (KataGo): after B E5 W C4 → B D3 (or E3). After E5 G4 → F3. After E5 C6 → D7. After E5 G6 → F7. After E5 C5 → G4 or G6. After E5 C3 → E3 or C5. After E5 E3 → D7 or F7. Third/fourth moves: E5 C4 D3 → W C6 (or F3); but if W instead plays C3 → B C6. E5 G4 F3 → W G6 (or D3). E5 C6 D7 → W C4. E5 G6 F7 → W G4. E5 C5 G4 → W F7 (or D7). E5 C3 E3 → W C6. E5 E3 D7 → W G6. E5 C4 D3 D4 (W hane) → B E4. Move 5 for Black: E5 C4 D3 C6 → G6; E5 C4 D3 F3 → C3; E5 G4 F3 G6 → C6; E5 C6 D7 C4 → G4; E5 G6 F7 G4 → C4 (take the remaining open 3-4 point). Move 6 for White: E5 C4 D3 C6 G6 → D7; E5 C4 D3 C6 F3 → G7. If White attaches at D4 or F4 → hane at E4 / D5 or F5. After E5 E4 → D4 or F4 (hane).
- Then **build connected walls that split the board**: hane at the head of the opponent's stones, block the opponent from entering my side, and keep my stones in a connected chain. Moves that both strengthen me and press a weak enemy group are best.
- **Direction:** if the opponent builds a strong wall facing one side, don't crawl/push underneath it (each push makes the wall stronger and my stones low); instead claim the other open area with a 3rd-line point (C3/C4/G3/G4/C7/G7-type points) or a loose extension, keeping my groups linkable. Big points are open 3rd-line points in the largest empty region.
- Respond to the bot's approach/attach moves near my stones rather than playing far away; on 9x9 every move is local.
- When ahead, play solid (connect, protect cutting points). When behind, look for real weaknesses in enemy groups (cutting points, short liberties, small eye space).
- **Komi 7:** Black needs about 45+ of the 81 points of area; White wins with about 38+.

## 5. Endgame and scoring (STRICT Tromp-Taylor — critical)
Score = my stones on the board + empty points whose region touches ONLY my stones. Nothing is ever removed as "dead". Consequences:
- **Dead enemy stones inside my area count as alive** and an empty region touching even one enemy stone scores for nobody. I MUST actually capture every enemy stone inside my area before passing.
- My stones inside the enemy area likewise spoil their region until captured; don't help the opponent remove them.
- Area scoring: a move inside my own area costs nothing (if I am unsure whether a boundary is safe, an extra protecting move is free). But never fill my own two eyes.
- **Dame (neutral points between both colors) are worth 1 point each**: fill them before passing.
- Close boundaries: play hane/blocks on the edge (1st/2nd line) that reduce the enemy area and protect mine, biggest first.
- **When to pass:** only when every boundary is closed, no enemy stones remain inside my area, all dame are filled, and the count says I win (Black area − White area > 7 for Black to win).
- If the opponent passes, don't automatically pass: count. If I'd win now, pass. If not, keep making useful moves (capture stones in my area, fill dame, attack weak points).
- Never resign.

## 6. Final answer
Reply with exactly one entry from Legal moves (e.g. `D3` or `pass`) and nothing else.
