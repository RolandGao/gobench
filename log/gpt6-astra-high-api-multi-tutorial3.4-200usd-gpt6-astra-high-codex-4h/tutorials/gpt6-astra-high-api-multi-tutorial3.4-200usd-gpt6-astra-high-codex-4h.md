# Playing 9×9 Go accurately

Your objective is to win the actual game, not to display Go vocabulary. Think privately; your final answer must be exactly one listed legal move. Never resign. Use the current board as ground truth, not an imagined continuation from an earlier turn. Coordinates skip I: H is adjacent to J. Rows increase upwards. Only orthogonal adjacency connects stones or supplies liberties.

## The reliable move-selection loop

Use this loop every turn, including apparently quiet turns:

1. **Reconstruct the tactical facts.** Locate the opponent's last move. Identify the connected chains it touched and their distinct empty liberties. Scan the whole board, not just that neighborhood, for chains in atari (one liberty), two-liberty chains, cuts, and groups lacking a secure route to life. Label each important group: alive / unsettled / tactically dead. For “alive,” identify the actual eyes or secure connection; lots of outside liberties alone is not proof. A chain is a maximal orthogonally connected set, not all nearby stones of one color.
2. **Identify what matters globally.** Which large groups are unsettled? Where is the largest open region? Who is likely ahead after komi? What does the opponent threaten if you ignore their last move? Do not automatically answer it.
3. **Generate a small meaningful candidate set:** urgent captures/saves; connections or cuts; moves securing life or denying life; the largest territorial move; a forcing move that accomplishes one of these. Include at least one candidate away from the last move unless a genuinely forced emergency rules it out. Usually compare 3–5 candidates rather than narrating every empty point.
4. **Read adversarially.** For each serious candidate, play it on the mental board, remove captures, then ask for the opponent's strongest reply—not the most cooperative reply. Include a cut, counter-atari, capture, connection, escape, or tenuki when relevant. Read forcing sequences until the immediate tactical issue is resolved; a ladder may require following it all the way across this small board. At each branch restore the actual starting position.
5. **Compare the resulting positions**, not just the attractiveness of the first move. Favor survival and connection of important stones, secure area, useful outside strength, and retained initiative. Do not save disposable stones at the expense of a large group or half the board.
6. **Final blunder check:** Is this move on the legal list? What is the resulting chain's liberty set? Can the opponent capture it or cut something important immediately? Did a capture open liberties that invalidate your calculation? Does your move really stop the threat? Then output only the coordinate or `pass`.

Use a **compact private tactical ledger**, not just an intuitive picture, when stones are in contact: for each relevant chain record its member coordinates (or trace them), its distinct liberty coordinates, and its connection/eye status. Especially mark all chains with 1, 2, or 3 liberties. For a proposed move, update only the affected chains and captured neighbors; do not carry liberties from the real board into the hypothetical board. This prevents imaginary connections and missed counter-captures.

For a weak group, make a concrete survival plan: name two prospective eye points or the route to a live group. Then let the enemy play first at the best point to spoil that plan. If your plan fails, the group is urgent even without an atari. Conversely, if the enemy cannot spoil it, do not spend moves on redundant defense. Strong candidates often occupy the point that would be most troublesome if the *opponent* played there first.

Spend thought where it changes the decision. Exact local calculations beat long speculative strategic stories. If your analysis calls a move “forced,” explicitly test at least the strongest alternative, including counter-capture.

## Mechanics: count actual liberties

A chain's liberties are the **union of adjacent empty points**, each counted once. Two stones sharing a liberty do not have two separate liberties there. Diagonal friendly stones are not connected. The board edge is not a liberty. A chain containing many stones can have only one or two liberties.

To simulate a move:
- Put down the stone.
- Remove **all adjacent opposing chains whose last liberty was filled**.
- Merge the new stone with all orthogonally adjacent friendly chains; compute the merged chain's remaining liberties, including newly emptied captured points.
- If the friendly chain still has zero liberties, it self-captures under these rules. Such a move may be legal, but is usually bad. Check superko via the supplied legal list.

Do not reject a capture as suicide merely because the placement point has no empty neighbor before capture. Conversely, an extension from atari is not necessarily a rescue: the extended chain may still have only one liberty and be chased to capture. Count its *post-move* liberties and the escape route.

When your important chain is in atari, candidates are: extend at its last liberty; capture the attacking chain; connect through a capture; make a stronger counter-threat if the sacrifice is justified; or abandon it. When the opponent is in atari, capture is often excellent but not mandatory: a worthless stone can be bait. Count the value of what is saved or lost, including territory and cutting stones.

A two-liberty chain may already be tactically lost. Before playing elsewhere, ask what happens if the enemy occupies either liberty. Likewise, your attack on a two-liberty chain works only if its extension, counter-capture, connection and escape all fail.

## Reading patterns that decide games

**Double atari:** a move threatens two chains; the opponent can usually save only one. Check whether connecting or capturing the attacking stone saves both. Search for these for both sides, especially at cutting points.

**Cut and connect:** separating the opponent's weak groups is often more valuable than chasing a few stones. Look especially at enemy diagonal pairs: if one of their two connecting points is already yours, the other may be a powerful cut. A cut is useful only if the cutting stones can survive, connect, or force a worthwhile sacrifice. Before making a loose connection, play the opponent's cut mentally. Two diagonal stones can be linked through either of two shared adjacent points only if those connecting moves are tactically sound; a one-space jump also has a cutting point. When under pressure, a solid connection is often worth more than an ambitious jump. But connecting already safe groups is small. A bamboo joint has two independent solid connecting options; do not fill it without a concrete tactical need. Distinguish a real cutting threat from a cut whose stone you can simply capture.

**Atari is not automatically sente.** It may force the opponent to make the connection or extension they wanted, strengthening them while leaving you weak. Choose the direction of atari by its outcome. Avoid driving a weak enemy toward their strong stones or into your own weak group. Sometimes the quiet move that removes escape routes is stronger than immediate atari.

**Ladder:** alternate ataris so the escaping chain stays at one or two liberties. Follow the actual zigzag, counting at every turn. Stop when it is captured, reaches friendly help, captures the attacker, or gains enough liberties to escape. Do not assume a ladder works from its local appearance; on 9×9 it soon encounters another stone or an edge. Never start a ladder that fails unless the forcing moves serve another clear purpose.

**Net:** instead of chasing with atari, play ahead of the escaping stones and close their routes. Test every exit and cut. A net can catch a chain even when a ladder fails.

**Snapback:** a small capture can leave the capturing chain in atari, allowing immediate recapture of a larger chain. Simulate both captures before declaring a sequence won. Distinguish snapback from ko: a recapture that removes more stones may not repeat the board.

**Throw-in:** sacrificing a stone inside the opponent's eye or capture shape can force them to fill their own liberties and create a false eye or snapback. Check the position *after they capture*, not just before. Similarly, do not reflexively capture a sacrifice if doing so destroys your eye or loses a liberty race.

**Capturing race:** first check eyes, escape and connections. With no eyes and no escape, fill the opponent's exclusive outside liberties before shared liberties; occupying a shared liberty also removes one of your own. Count approach moves needed to fill protected liberties. Recalculate after every move. Raw liberty counts are not sufficient when eyes, ko, captures, or approach moves intervene. A group with an eye can have a decisive advantage over one without. Do not reduce shared liberties in a stable seki and kill your own group.

**Ko:** trust the current legal list about recapture. If recapture is forbidden, seek a genuine threat elsewhere whose loss would be larger than the ko; the opponent can ignore a small threat and finish it. Conversely, compare the size of their ko threat with finishing the ko before answering automatically. Read whether your threat really forces a reply. Never count on an illegal immediate recapture or on a long cycle repeating the board under positional superko.

## Life, death, and the value of weak groups

A **chain** is mechanically connected; a **group** is a larger formation whose pieces may be connectable. Do not confuse influence, a prospective connection, or empty space with guaranteed life.

Two separate real eyes make a connected group unconditionally alive: the opponent cannot fill either eye while the other remains a liberty. One large empty pocket is not automatically two eyes. Ask whether you can partition it into two eyes despite the opponent moving first at its vital point. False eyes, cuts, and throw-ins can destroy apparent life. A sufficient test for a real one-point eye: every on-board orthogonal neighbor belongs to the **same connected friendly chain**. Two such eyes of that same chain certify life. Merely having same-color stones around a point is not enough if they are separate chains: a boundary chain might be captured, making a false eye. Enemy diagonals are a warning, particularly near edges. Verify the boundary connections and capture threats rather than counting eyes by appearance.

For small enclosed eye spaces, the vital point is often the center or junction: center of a straight or bent three, center of a T/pyramid four, the junction of a bulky five. A straight four can normally divide into two eyes; a compact square four cannot simply be assumed alive. These are shape cues, not a substitute for checking surrounding liberties, connections and ko. As defender, occupy the dividing point; as attacker, deny the division. Reducing eye space from outside may be stronger than plunging inside it.

A group is safe if it has two eyes, can force two eyes, or has a genuinely secure connection to a live group. A group with ample room and liberties is promising, not proven alive. Eye space is the empty region a group can preserve and divide, not the number of its outside liberties. In a cramped corner, an edge extension can preserve two eye-making areas while a connection inside your own space fills one of them. Read first-line and second-line vital points here; opening advice against low moves does not apply to life-and-death. If an enemy stone has entered your eye space, compare surrounding it from outside (restricting its liberties) with directly pushing against it (which may help it connect and fill your eyes). Explicitly consider a first-line placement behind the invader: a vital stone need not connect immediately if later captures or forcing moves make it work. Groups without eyes near enemy strength need attention before they are surrounded. Before leaving such a group, give the opponent one free move to seal its escape or reduce its eye space. If that kills it or leaves only a hopeless run, settle it now—even if it has many liberties and is not in atari.

When a group is almost enclosed, **expand the life-and-death search**. List the empty points in its prospective eye space and the points completing that space's boundary. Consider vital placements there, including first-line moves and moves not immediately adjacent to your own stones. Do not restrict candidates to obvious extensions or ataris. For each plausible living move, test the opponent's best intrusion, eye-stealing move, cut, and throw-in. Read until you can identify two separate eyes, a secure connection to an already living group, a genuine escape, or a forced capture. A vague statement that the group “has room” is insufficient when the perimeter is nearly closed.

Connecting two eyeless groups does **not** make them alive: they may simply die together. A move inside your prospective eye space can shrink it; a move along its outside boundary can enlarge or secure it. To choose between them, test what happens if the opponent takes the other point first. A small endgame move or capture must not distract you from saving or killing a large group. Use substantial private calculation in such critical positions; there is no game clock.

Prefer **one healthy connected formation over several weak groups**. When a group is endangered, look for a move that simultaneously connects, gains liberties, opens eye space, or runs toward open center. Running straight along the second line may merely postpone death; an escape should lead somewhere. Do not keep attaching rescue stones to a chain that cannot survive. Sacrifice a few stones to settle the rest when necessary.

Attack for profit, not only for capture. A successful attack may gain territory, connect your stones, split the enemy, or force them low while your group becomes strong. Do not chase a group already alive. Do not launch an invasion from a weak position and create a second endangered group. Before starting a fight, identify which surrounding stones are strong and which side benefits from contact.

## Strategy specific to a 9×9 board

The entire board is one interacting fight. A large capture or split can decide the game; standard 19×19 corner sequences are not automatically appropriate. Center influence reaches every side, but it must eventually become living stones and controlled area.

**Opening:** Black can start at E5, the center; D5/E4 and equivalent central points are also viable. White should contest space rather than passively concede a huge center, often with a near-center or third-line move that leaves room for a base. Against an empty-board E5, C5/E3/E7/G5, or a move such as C4 (and symmetric equivalents) is a reasonable starting plan. There is no compulsory sequence: adapt to the opponent's stones. Prefer third/fourth-line development and efficient central connections to first/second-line crawling. Do not occupy all four corners independently and leave four disconnected weak groups. Avoid early moves deep inside territory you already control.

The first priority is not mechanically “corners, sides, center.” On 9×9, a central move that connects you and divides the opponent can outweigh an empty corner. Conversely, taking real side/corner territory while the enemy overconcentrates in the center can be excellent. Balance territory with strength.

**Bases and extensions:** a base is space along a side to make eyes, usually developed around the third line. An extension should be far enough to gain space but close enough to remain tactically connected. Under enemy pressure, shorten it. A stone placed on the second line secures little space unless it is a necessary life, death or endgame move. The first line is usually tactical/endgame only.

**Contact:** attaching to stronger enemy stones often strengthens them while creating a weak chain for you. Attach when the forcing exchanges help you settle or gain a concrete tactical result, not merely because an enemy stone is nearby. The hane at the head of two stones, extension, and solid connection are candidates, not commandments; check cuts and liberties before choosing a hane. If you have weak stones on both sides of a cut, connection is urgent.

**Efficiency:** do not equate “solid” with “good.” A connection that adds no necessary safety, liberties, eye space, or territory can waste the initiative. Ask what the opponent could really do if you did not connect. When friendly stones are diagonally linked and you can answer either cut, develop outward instead of filling the shared point. When parallel chains are running alongside one another, look for a hane or extension at their leading edge rather than a backward connection that lets the enemy get ahead. A developing move should normally claim new space or constrain the opponent, not merely thicken your rear.

**Direction:** play toward the larger open area and away from enemy thickness. Use your strong stones to support fighting; avoid building a second wall next to an already strong wall. Do not push the enemy into your desired territory while gaining nothing. Block on the side where allowing penetration would cost more, provided your blocking stones survive.

**Moyo versus territory:** an open region loosely outlined by stones is not owned. If the opponent can enter and make a base or connect out, discount it. Invade while there is enough room to live if you need substantial territory; reduce from outside when your stones are weak or a shallow reduction suffices. Do not wait until a huge framework is completely sealed before noticing you are behind. On the other hand, do not invade a secure, cramped region just to be captured.

After each major exchange, reset your judgment. A former attacking group may now be weak; an enemy group you planned to kill may now be alive. Do not continue an obsolete plan just because it was your plan last turn.

## Scoring and finishing: these exact rules matter

This is **strict Tromp–Taylor area scoring with no automatic dead-stone removal**. Black gets black stones on the board plus empty points in empty regions touching only black stones. White gets the analogous total plus 7 komi. Prisoners have no separate value. Empty regions touching both colors are neutral. Boundary contact is orthogonal and applies to the whole connected empty region, not just each point individually.

For an exact final count:
1. Count the stones of each color.
2. Flood-fill each connected empty region mentally; record its size and which colors border it.
3. Add a region only if its bordering stones are exclusively one color. Add 7 to White. Compare.

If every point belongs to one side and none is neutral, Black needs at least 45 of the 81 points to win: B45–W36 gives B a 2-point win after komi, while B44–W37 is a draw. Neutral points alter this threshold, so use the actual difference **Black area − White area − 7**. An approximate count during play should distinguish secure area from uncertain potential, and not double-count stones plus their occupied points as territory.

**Dead enemy stones must actually be captured.** An enemy stone still on the board counts for the enemy and can make a large surrounding empty region neutral, even if ordinary Go would label it dead. Thus cleanup can be enormous, not a one-point afterthought. Fill its liberties safely until it disappears, unless passing now already wins and ends the game. Likewise your own uncaptured “dead” stones may still prevent enemy territory from scoring. Do not remove them voluntarily without benefit.

Playing inside your own completely secure territory generally replaces one territory point with one stone: it does **not** cost a point under area scoring. It does cost a turn and can endanger eyes. Use this fact to connect safely, resolve cuts, or capture dead stones when needed. Filling your last two eyes carelessly can kill the whole group. Capturing n opponent stones is not a Japanese-style prisoner bonus; its value comes from removing their area and controlling the vacated points and surrounding region.

**Dame are valuable:** a safe move in a neutral empty point gains one stone of area; taking a contested point before the opponent can yield a two-point swing relative to them taking it. Fill safe neutral points before passing. Some apparent dame are shared liberties in seki or protected by tactics; read before filling them. Endgame order is generally urgent life/death and captures, then profitable forcing boundary plays, then the largest remaining boundary move, then safe dame and cleanup. Prefer a move useful both offensively and defensively.

Estimate endgame value by comparing the final local area if you play first versus if the opponent plays first. Do not count only the newly placed stone: closing an opening can secure a whole region. A move is sente only if ignoring it really loses enough; do not respond automatically to a tiny threat when a larger move is available. Do not waste a turn defending secure territory from an invasion that cannot live or escape.

**Passing:** two consecutive passes end the game immediately. An opponent's pass is an opportunity to finish a win, not proof that all stones are settled. If they just passed, count the *current literal board*. If a second pass wins, take the guaranteed win. If it draws and no realistic improvement exists, a draw is better than losing. If it loses, do not pass while useful play remains. Otherwise pass only when no beneficial capture, defense, boundary play, or safe neutral point remains. Never resign: even when behind, the opponent can err, and a useful move or pass is at least as good.

## Three concrete reading lessons

These are examples, not sequences to repeat regardless of position. All unlisted nearby points are empty unless specified.

**A loose link can conceal a decisive cut.** Suppose Black has a chain E3–E4–F4 and a separate stone G5, with White at D3, D4, E5, F5 and G6. The diagonal F4/G5 is not a connection: F5 is already White, so G4 is the only bridge. White should seriously examine G4. It cuts and puts G5 in atari (its other liberty is H5). If Black H5 connects toward friendly H6, White can continue G3 against the southern chain. Black cannot necessarily save both sides. The lesson is to inspect *both* chains a cut separates, not just the stone immediately in atari. Merely playing an unrelated boundary move can miss a huge attack.

**More connection can mean less life.** With your G7 and H6 stones near enemy G6 and H5, H7 connects them, but may leave a cramped group without eye space. H8 can instead enlarge the upper-right space while preserving alternative links through G8/H7. Do not choose H7 just because it visibly joins stones. Compare the opponent's best cut against H8 with their best eye-space reduction after H7. A living connection is what matters, not a visually solid dead group. If pressure later seals the left side, a move toward J6/J7 or the top edge may be urgently needed to build eyes even while another group is being approached.

**Contact does not require a contact answer.** If Black has F4–F5 and E6 while White has D4 and F3, White need not play E4 merely to draw D4 and F3 closer. G3 extends F3 toward open right-side space and gives it a base; E3 is another useful extension. E4 may make a heavy, cramped central formation and let Black take G3. Always compare settling outward with connecting inward. The value of a move is what it makes possible next, not its immediate appearance.

## Final discipline

Choose moves for concrete consequences. Be skeptical of “this looks connected,” “this should live,” “that group is dead,” and “surely they must answer.” Replace each with a short variation or explicit liberty/eye/area check. Avoid both timid overdefense and unsupported aggression. When ahead, simplify safely and secure the score; when behind, seek a genuine invasion, cut, ko or tactical complication rather than quietly accepting a losing boundary. The board, legal list, and scoring rules—not remembered Go conventions—decide the result.
