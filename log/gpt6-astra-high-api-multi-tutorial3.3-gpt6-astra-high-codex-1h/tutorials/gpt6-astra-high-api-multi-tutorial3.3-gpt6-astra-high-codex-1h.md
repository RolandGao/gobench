# Winning 9×9 Go: exact tactics, connected strength, and area

Your objective is to win the actual position, not to demonstrate Go vocabulary. There is no need to rush: spend your reasoning on concrete refutations, not just plausible descriptions. Think privately, then output exactly one entry from the current Legal moves list. Never resign: even a lost position may offer a recovery. Treat each new board as authoritative; earlier variations were hypothetical, not played moves. Opponents can make mistakes, but evaluate your move against their strongest reply.

## 1. Read the board accurately

Columns are A B C D E F G H J (no I); rows increase upward. Orthogonal neighbors only: H5 neighbors G5, J5, H4, H6. Diagonal stones are NOT connected. The edge is a boundary, not a liberty. Z is empty.

A **chain** is an orthogonally connected set of one color. Its liberties are the SET of distinct adjacent empty points, not a sum per stone. Adjacent friendly chains merge on connection. When analyzing a move: place the stone, merge friendly chains, remove every enemy chain with zero liberties, then remove any friendly chain with zero liberties. Captured points become liberties. This order allows a capturing move that initially appears surrounded. Self-capture is legal here but usually worthless; the supplied legal list already enforces superko.

For a critical chain, actually list its stones and unique liberties. An anchor coordinate plus stone count and a liberty set is a useful compact label. Inventory every chain with three or fewer liberties, including large connected chains whose far end is easy to overlook. Do not say “about three liberties” in a life-or-death fight. Recount after captures and connections. An extension does not necessarily gain a liberty; on the edge or into a net it can simply make the eventual capture larger.

## 2. A reliable move-selection loop

On EVERY turn, before strategic ideas (if the opponent just passed, first check whether passing now locks in a win under the exact scoring rule in §6):

1. **Tactical census.** Locate both sides' chains in atari (one liberty), chains with two liberties, cuts between friendly chains, and unsettled large groups. Inspect what the last move changed, but scan the rest of the board too.
2. **Generate 3–5 serious candidates.** Urgent saves/captures, a connecting or cutting move, a life/escape move, and the biggest territorial move. In quiet openings do not invent tactical emergencies. In fights do not distract yourself with tiny endgame gains. For any proposed defense, identify the concrete threat if you omit it; if the opponent’s supposed cut simply dies, that defense is not urgent.
3. **Read adversarially.** For each candidate ask: what is the opponent's strongest capture, atari, cut, connection, eye move, or counterattack? Examine at least the immediate reply and your answer. Extend forced lines until the tactical result is clear. A line ending with a threatened group still in atari is not a result. Include the opponent ignoring your supposed threat.
4. **Evaluate the resulting board**, not just the first move: survival of important groups, secure area, who remains weak, and who has the initiative. Reject a pretty move with a concrete refutation.
5. **Final blunder check.** After placing the chosen stone mentally, list liberties of every affected friendly chain. Can the opponent capture it, snap back, cut off a larger group, or destroy its only eye? Is a larger group elsewhere left to die? Verify the coordinate is in Legal moves.

Use a compact local ledger for complicated reading: candidate; affected chains; their liberty sets; opponent's best reply; result. Keep different branches separate and reset to the supplied board between them. Accurate short reading beats a long invented sequence. If two plausible choices remain, prefer the one that safely connects, makes eyes, or limits the opponent's forcing moves over a speculative attack requiring cooperation.

## 3. Tactical priorities and common traps

**Atari is a warning, not an automatic instruction.** To save a valuable chain consider: (a) capturing the attacking chain, (b) connecting to a stronger chain, (c) extending into genuine liberties, (d) a counter-atari that truly forces a response. Saving by capture or connection is often stronger than running. Count the liberties of the WHOLE resulting chain. If the chain cannot escape and has little strategic value, sacrifice it rather than add stones and lose turns. Do not save one expendable stone at the cost of a big group. But stone count is NOT strategic value: before abandoning even one cutting or surrounding stone, remove it mentally. Does the hole let the enemy connect, escape, gain an eye, or gain liberties that defeat your attack? If so, that single stone may be the most important chain on the board.

**Captures are not automatically best either.** A small dead chain may be captured later; a large threatened group cannot wait. A capture is urgent when it saves your group, breaks a connection, removes an eye, wins a race, or gains substantial area. Capturing one stone that leaves your own chain in atari may be a snapback: the enemy recaptures the entire chain. Calculate the board after the capture and recapture.

**A threatened capture is not necessarily forcing.** Always test the opponent capturing one of YOUR surrounding stones instead of extending their threatened chain. Example: their large chain has liberties {p,q}; your blocking chain is in atari at r. Playing p seems to force q, but their r may capture your blocker and open new liberties for the target. You have NOT won the race. Saving/connecting the blocker at r can be more urgent than reducing the enemy to atari. Recount the enemy target’s liberties after their countercapture.

**Double threats.** A move that puts two distinct chains in atari can be decisive, but check whether one reply connects both, captures your attacking stone, or counter-ataris a bigger chain. A cut is powerful when both resulting enemy groups become weak AND your cutting stones survive. Cutting with an isolated stone between strong groups often sacrifices it for nothing.

**Atari direction matters.** Do not reflexively atari: it may force the enemy to connect, gain liberties, and become strong while your own shape worsens. Choose the direction that blocks escape or separates groups. A quiet net can be stronger than a forcing atari that pushes the target to safety. Attack toward your strength, not toward open space or an enemy ally.

**Ladders and nets.** Before starting a ladder, trace alternating atari and forced extension to the edge or a friendly ladder-breaker, including countercaptures. “It looks like a ladder” is not enough. If the target can connect to help or create two escape routes, do not play it. A net surrounds without immediate atari; test each exit. Use a solid containment move when chasing only strengthens the opponent.

**Liberty races.** Identify exactly which two chains are racing and whether either can connect out or make eyes. Count outside liberties, shared liberties, and moves needed to fill protected liberties. Compare actual alternating sequences; raw counts can fail because filling a liberty requires an approach move or allows capture. In a simple eyeless race, fill the opponent's OUTSIDE liberties before shared liberties: filling shared points also reduces your own liberties. An eye changes the race radically. Recount after every capture; taking a small chain may supply the liberties that win. When possible, connect to life rather than gamble on a close race.

**Sacrifice deliberately.** Give up stones if doing so gets a larger capture, secure outside wall, life for the main group, or enough area elsewhere. But “influence” is not adequate compensation unless you can identify what it will secure. Do not keep feeding an already trapped chain.

## 4. Life, eyes, connection, and invasion

A group with two independent true eyes normally cannot be captured. Two adjacent empty points are generally one eye SPACE, not automatically two eyes: the enemy may occupy one and leave only a single eye. A large eye space must have a way to divide into two eyes against the opponent's best first move. Connection to an already living group also gives life.

A one-point eye needs orthogonal enclosure by friendly stones/edges AND stable surrounding connections. Enemy-controlled diagonals can make a false eye. For an ordinary interior one-point eye, two hostile diagonals are a major false-eye warning; on the edge or corner, one may suffice. Empty diagonals may be contested, not safely yours. Verify the surrounding chains cannot be forced to fill the apparent eye to avoid capture. Geometric enclosure alone is not unconditional life. Many outside liberties buy time but are NOT eyes: a surrounded eyeless group with five liberties can be more urgent than a dispensable single stone in atari.

Small enclosed spaces have vital points: the middle of a three-point line or bent three, or the center of a T-shaped four. But outside liberties, cuts, captures, and ko can change the result: test the opponent's intrusion and your capture. A one-eyed group may still survive by escaping, connecting, capturing its surround, or seki.

**Defend before enclosing more.** If your only substantial group is weak, its eye-making or connecting move is usually bigger than an empty corner. If an enemy invasion threatens to split your army or erase your only eyes, address it immediately. Conversely, a disconnected enemy stone inside your solid living territory need not be chased urgently if it cannot live or cut; first protect any actual weakness.

**Shape, without overdefending.** Solid connections are reliable. Diagonal connections, one-space jumps, and knights' moves are useful but can be cut; verify the opponent's wedge or peep. A one-space jump is not a literal connection. Keep important chains mutually supported. Avoid unnecessary empty triangles, but an ugly solid move that saves a group is better than elegant death. Do not create several weak groups on a tiny board.

**Do not fill an empty point orthogonally surrounded by your own stones just to “connect.”** If all neighboring friendly chains have other liberties, an enemy stone there cannot survive or cut them now. Filling it often gains zero area and wastes the initiative while an important fight is elsewhere. Likewise, do not solidify a bamboo joint or already-safe connection without a concrete reason. Read the opponent’s alleged cutting sequence before defending it; “more connected” is not automatically “better.” Necessary shortage-of-liberties repairs are exceptions.

A **tiger's mouth** (an empty point with friendly stones on three orthogonal sides and the fourth neighbor empty) also usually needs no reinforcement: an enemy cut there would have only the fourth neighbor as its liberty, and you can capture by filling that liberty. Verify this reply is safe and your surrounding chains are not themselves in atari. Do not spend a tempo connecting already-tactically-connected stones while the opponent claims the sides.

**Contact fighting.** Compare hane, extension, cut, and atari. A supported hane can block expansion and build territory better than a passive central connection; verify its cutting points. After a crosscut, extending a cutting stone to gain liberties often beats atari that helps the enemy extend. Don't peep unless forcing their connection benefits you. These are candidates, not unconditional proverbs.

**Attack for profit, not revenge.** The best attack often gains secure territory, splits the enemy, or connects your own stones while the enemy runs. Do not force a kill if the opponent has a route to two eyes: take the profit and stay strong. Surround broadly from strong stones; attaching to a weak target often gives it forcing moves and shape. Attach when you specifically need forcing contact to settle your own weak stones or when a concrete tactic works.

**Contain before chasing.** To attack an eyeless group, consider a cap or net one step away, not only adjacent ataris. Identify where it intends to escape or make its second eye; occupy that route before squeezing its liberties. Direct contact can push it through the very gap you needed to close. A central eyeless group surrounded on three sides may be a decisive target even with four or five liberties. Verify that your net's cutting/blocking stones survive; then examine the target's alternate exits and counterattacks. Killing a surrounding chain can rescue several of your own groups simultaneously.

**Invasion versus reduction.** A framework is not territory while it is open. Invade if you can outline a route to two eyes, an escape, or a forcing connection. Deep invasion without a base is especially dangerous on 9×9. A shallow reduction from outside is safer when already ahead. Before treating a region as yours, test the opponent's most plausible invasion and boundary cuts. Before treating a group as captured, check its best escape and eye move.

When attacking a confined eyeless group with three liberties, compare its extension at EACH remaining liberty. Block the route to a base or friendly connection, not simply the nearest liberty. A big quiet containment move can outrank an atari elsewhere.

### Two tactical illustrations (coordinates apply only to these boards)

**1. White to move: contain before pushing.**
```
  ABCDEFGHJ
9 ZZZZZZZZZ
8 ZZZZBBZZZ
7 ZZZWWBZZZ
6 ZZZWBBWZZ
5 ZZZWBWWZZ
4 ZZWWWBZZZ
3 ZZBBBBZZZ
2 ZZZZZZZZZ
1 ZZZZZZZZZ
```
Black's central chain E8–F8–F7–E6–F6–E5 has five liberties but no eyes. White **H8** is a powerful cap; simply pressing at D8 lets Black develop on the right. One main line is White H8, Black H7, White G7, Black G8, White H6. White strengthens the right-hand chain while containing Black; if Black then runs at D8, White C8 blocks from outside. The lesson is to occupy an escape route and maintain a net, not blindly subtract one adjacent liberty at a time.

**2. White to move: an atari does not forbid a bigger attack.**
```
  ABCDEFGHJ
9 ZZZZZZZZZ
8 ZZZZZBBBZ
7 ZZZBBWWBZ
6 ZZBWWZBWW
5 ZZZBWWZBZ
4 ZZZBBWZZZ
3 ZZBBWZZZZ
2 ZBWWWZZZZ
1 ZWZZZZZZZ
```
White F7–G7 is in atari at F6, but **C5** is stronger than automatically saving those two stones. The Black D5–D4–E4–D3–C3 chain has liberties {C5,C4,B3}; its base is the important target. If Black takes the small capture with F6, White B4 nets the larger lower-left group: extending at C4 gains no liberty and leaves B3 as its last liberty. Black needs to address the bigger problem rather than collect the two stones. Compare the WHOLE exchange. A rescue that saves small stones and makes an atari can still lose the strategically decisive fight elsewhere.

## 5. Opening and whole-board judgment on 9×9

The center matters more than on 19×19: a strong central chain can influence all four sides, and corners interact almost immediately. Avoid memorized 19×19 joseki played without regard to the opposite side.

A sound Black first move is **E5**; nearby D5 or D4 are also strong. As White, useful initial responses are E5→D3 (or a symmetric 3–4 point such as C4), D5→F5, D4→F6. Against a remote edge opening, occupy the center or a central 4–4 point rather than chasing. These are orientations, not compulsory sequences. Do not play four unrelated corner moves on this tiny board.

Early on, develop on the third or fourth line, secure a base, and coordinate with your existing stones. Opening-point preferences are not later move targets: once contact begins, respond to the position instead of automatically adding another central stone. Do not spend early moves on the first or second line unless a concrete local sequence requires it. Do not encircle a tiny territory with many moves while conceding the rest of the board. Do not count an open central framework as secure points. A central stone is useful influence, not an eye or territory by itself.

Useful strategic ordering (tactics can override):
- Survival/connection of a major group or a decisive capture.
- Separating weak enemies, securing your own base, or preventing an efficient invasion.
- A large two-purpose move: defend while attacking, connect while enclosing, reduce while escaping.
- The largest secure territorial expansion or reduction.
- Small boundary endgame and neutral points.

White has **7 points of komi**. Black needs significantly more board area, not merely an equal split; White can accept an approximately balanced board. Do not overplay because a small local exchange was unfavorable. Estimate the whole board after each major fight. When ahead, simplify, connect, live, and block the opponent's realistic winning chances. When behind, preserve complexity and choose a plausible invasion/cut/ko that could change the score rather than settle for a small certain loss. Do not confuse “safe locally” with “enough points to win.” A thick central wall or one large living group can still enclose far too little area. If the projected split loses on points, challenge the opponent’s boundary or attack an unsettled group BEFORE they consolidate; extra safe moves that cement a losing split are not good defense.

## 6. The scoring rules change the endgame

This is **strict Tromp–Taylor AREA scoring, with no automatic dead-stone removal**. Final score for each color is its stones on the board plus empty points in regions bordered by that color only. An empty region touching both colors is neutral; the edge is just a boundary. White adds 7. Prisoners and captured-stone totals do NOT count separately. A stone's value is the area and tactical effect it produces, not a prisoner bonus.

**Winning-pass exception, checked FIRST:** If the opponent’s last move was `pass`, count the board EXACTLY AS IT STANDS. If your score is already strictly higher, `pass` immediately guarantees victory—even if your groups are theoretically dead, enemy stones remain, or more points are available. Do not give the opponent another chance merely to increase the margin. If the current result is a draw, compare securing that draw with realistic winning continuations. If currently losing, do not end the game while useful plays remain.

**You must physically capture dead enemy stones if their presence costs you points.** “That group is dead, so its space is mine” is NOT the final scoring rule. An uncaptured enemy stone counts for the enemy and can make a large surrounding empty region neutral. Before passing, inspect ALL enemy remnants inside your claimed territory. Capture safely; do not just label them dead. Conversely, invasions can demand cleanup even when they cannot live.

**A practical scoring try when behind:** First take guaranteed scoring gains, especially cleanup captures. When behind in a settled position, especially if the opponent is passing, a legal intrusion into an exclusively enemy empty region—even a two-point eye—can make its remaining empties neutral immediately, even if the intruder cannot ultimately live. Under these rules the opponent must actually capture it to restore ownership. If they pass again and the exact current score now favors you, pass and win. Do not pass first into a certain loss while these scoring tries remain. Prefer a legal move that neutralizes a large currently enemy-owned empty component; once a region is mixed, another exclusively enemy region usually offers a larger swing. If still behind and they keep passing, try another region rather than ending the game. If they correctly capture, try a different scoring opportunity; do not mistake their theoretical ownership for the strict score. Example: inserting one legal Black stone into a two-point White eye adds one Black stone and makes the remaining empty point neutral, removing two White area points: a THREE-point margin swing until captured. Black previously behind by two is now ahead by one; if White passes, Black should pass to win. This is not guaranteed profit against correct cleanup, but do not dismiss it merely because the stone is conventionally “dead.” Prefer such a real scoring chance to accepting a certain loss; never endanger your own living groups for it.

**Playing in your own secure territory usually does not lose area:** one own empty point becomes one own stone. Thus defensive connections and necessary cleanup are cheap once larger moves are gone. But they spend a turn, can destroy eyes, and can change seki or ko; do not fill your last eye or allow your own chain to be captured. Prefer useful moves to meaningless self-filling.

**Neutral points (dame) are worth points under area scoring.** A safe move on a genuinely neutral empty point generally adds one to your score. Do not pass while there are safe neutral points to claim. Watch “neutral” points that actually put a group in atari or break mutual life. In a settled position, taking a contested neutral point instead of allowing the opponent to take it changes the score margin by two relative to that alternative; prioritize larger unresolved territory before dame.

**Count concrete area.** At the end, flood-fill empty regions mentally: which colors do they touch? Follow all orthogonal empty paths through gaps; an imaginary territorial boundary does not split a region. One enemy stone touching a connected empty region makes that entire region neutral if it also touches your stones. Count stones plus exclusively owned empties, then add komi. For planning earlier, count conservatively secured regions and treat contested regions as uncertain, not as guaranteed territory. Don't count territory and its occupying stones twice. If all 81 intersections ultimately belong to one side or the other, Black wins at 45+ area; Black 44 versus White 37 plus 7 is a draw. With neutral intersections, use the actual difference: Black area − White area − 7.

**Endgame:** Compare the swing between both sides' best local outcomes. Boundary blocks and cuts can be worth several points. Genuine sente can outrank larger gote, but test whether the opponent can ignore it. Never give away a group for a small gain.

**Seki:** Some opposed groups survive because either side initiating the capture loses. Don't fill shared liberties merely to claim dame. Here stones still score, and exclusively bordered eye points score; shared empty regions remain neutral. Read before disturbing mutual life.

**Ko:** The legal list forbids current superko moves. If recapture is forbidden, find a real threat elsewhere whose cost exceeds the ko; the opponent is allowed to ignore it and finish the ko. Compare the actual whole-board consequences. Do not sacrifice a big living group for a tiny ko. Do not assume a move becomes legal just because one intervening move occurred: positional superko prohibits any repeated board.

**Except when accepting an immediate win as above, pass only after an audit:** no profitable safe boundary move, no needed defense, no enemy stones to remove for a better score, and no safely claimable neutral points. An opponent's pass is not evidence that the board is finished. If they pass, use the chance to claim points, finish captures, or repair weaknesses. If everything is settled and no useful scoring try remains, pass rather than destroy your own eyes. Two consecutive passes score the board exactly as it stands.

## Final checklist

My color and komi? Current board, not an old variation? Any important atari? Does abandoning a cutting/blocking stone open an escape? Is this defense really needed, or can I attack a confined weak group instead? Exact liberties after my move and their strongest reply? Are both eyes real or is there an escape? Am I needlessly strengthening the opponent? Does this improve my winning chances on the whole board? If passing, have I checked strict area scoring and cleanup? Finally output ONLY the selected legal coordinate or `pass`.
