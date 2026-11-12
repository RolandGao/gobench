# 9x9 Go versus KataGo bots: engine opening book, then corrections of your usual mistakes

## Opening book (computed with a strong engine against these very bots — follow it exactly)
**Code.** To save space every point is written as two lowercase letters: the column letter, then the ROW as a letter with 1=a 2=b 3=c 4=d 5=e 6=f 7=g 8=h 9=j. So E5 = ee, D6 = df, G3 = gc, C9 = cj, F5 = fe, H1 = ha.
**Reading.** On each line the words alternate: his move, your reply, his next move, your reply, … (every line begins with a move of his). Lines indented one space deeper are his possible next moves after the END of the line above. Start at the unindented lines with his first move. Each turn: encode his new move, find it as the next word of your current line (or as the first word of one of the lines directly beneath its end), and play the word after it, decoded back to a coordinate. Keep the full move list of the game in mind every turn (earlier turns of this conversation show it). As soon as his move is not found there, the book is over for the rest of the game — also if a context reset leaves you with a board you cannot trace from the start. Then use the sections below. Book replies are tactically checked; play them even when they look odd.

**You are Black.** Play F5 first. The book assumes the first stone placed off row 5 is on rows 6–9, or is yours. If instead White's first off-row-5 stone is on rows 1–4, the game is the book upside down: for the whole game convert every move with row → 10 − row, same column (D3 ↔ D7), before looking it up, and convert the book reply the same way before playing it.
```
ef ee
 df de
  ff gf
   ce cd
    cf gg bd cc bc ec cb db bb eh
     dh eg fg fh
     fg fh dh dg
     gc hd hc gd fc da
    gg cf be cg ge hf gd hg
   cf gg ce dc
    cd ec cc eh cb db
    cc cb cd eb bb eh
   gg cf
    ge hf he hg
    cg ge ce bf
  ce cd
   ff cf be cg ge gd gf dc
    bd bc hd gc
    hd gc
   cf ff
    fg gg bd cc bc db
    bd cc fg gg
  cf ff
   ce cd
    fg gg bd cc
    bd cc fg gg
   fg gg ce dc
 de dd
  df ff
   cd cc
    dc ed
     bc cb
      fg gg
       eg bd ce bb gh hf
       ec ce bd fc
       bb ce bd fh
      db bd ce bb fg gg gh be
     cb bc bd db ec bb fc fg
    fg gg dc ed bc cb
   fg gg cd cc dc ed
    bc cb
    cb bc
  ff df ce dg
   ge cd be bd
   cd gf
  ce ff
   cd dc
   eg fg
 ff df
  gf dg ge ec
   gc cc
   gd de fc eb fb eh
  dg cg gf ge
  ge gd gf de
de eg
 ee ff fd gd
  gc fc ed gb hc hd ec fb
   eb hb dg dh cg ch
   dg eb
  fc gc
   fb dc
   gb be
  ed gc dg dh cg eb
 ed fd
  fc gc ec cf
   df dg
    gb ce cd bd
    ce bf
   ce df
   gb ce
  ec cf
   fc gc df dg
   df dg
 dc cf
  df dg ce bf be gd
  ce bf df dg
 dd cf
  df dg fd gd
   gc ge fc bd
   fc gf
  fd gd
 cf ec
  dg cd
  dc db
 cd cg
  ed fd
  fc gc
 df dg cg ch
 fd gd
  ed gc
  ee ff
 dg dh
  df ch
  ef ff
 ec ed dd fc dc cg
 ce ec ee ff
 fc ed dd ec dc eb
 ef ff dg dh
ee ef
 de df
  ce fd cf ff
   cg dc
    cc cb
     cd eb bb dh
      ch ba bc eh dg eg
      dg eg ch ba
     bb eb
      eh fh
      dg fh
     bc eb bb dh ch eh
    dg eh cc cb
   ec ed dc cg
   dc cg bg eb ch dg
  fd gd
   ce fc ed ge cf ec
    dc db
     cb cc bc dd
     dg eg
    dg eg eh dh cg fh
   ge ff
    gc hd ce fc ed gb cf cg bg ch
    ce fc ed gc
   ff ge
    cf cg
    ce cf
   cf ff
  cf cg ce fd
   ff fg gf gg hf hg eg dg
   bg ff ch dc
 df fd
  eg ff
   de dc fg gg
    gh cd hg gf
    dg cd
   fg gg
    de dg
    dg dc
  de dg eg ff cg dh
  ff eg
df dd
 de ed
  cd cc
   ce fg bc gc cb eh dc cg dg dh ec fc
   ff gf fg gg
   bd fg
   bc bd ce bb ff gf
  ff gf
 ff gf
  ef gg
   ee ed fd ge fc be
   ge gd he fd hd hc
   ce fc
  ee ed ge fd gg hf
  gg ge
  fg gg ee ed
 eg gg
  de ed cd cc
  cd cc
  ee ed ff gf
  ff gf
  ce cd
 ef ff fg gg
  eg ec gh ce cf hf be bd bf hh fh ad
  gh fc
  fh fc
 ce cd ff gf ee ed
 fg gg ff gf ee ed
  ge fd
  fd ge fc cf
 ee ed ff gf ge fd gg hf
 cf eg ef ff cd cc
 cd cc
 dg fg
 cg fg
ff ef
 fg eg
  ge gd
   fd ee
    gc hd he fc ed hc dd gf gg hf
    fc gc gb he gf hf fh hb fb hg
    hd gc
   ee fd de cf
    ce bf eh dh fh be
    df dg ce bg
  ee fd de eh fh cg
  fh ee ge gd
 eg dg
  fg df ge gd fd ee gc hd he fc ed hc dd hg gb gf
  ee df fd ge
  df ee
 ee fd df eg
ce df
 cf dg
  cg dd
   cd fc dh eh ch fg
   de ee cd dc cc he dh eh ch cb
  de ee cg dc dh eh ch fc cc gh
 de cf ee ef fd gd
  ge ff gc hd
  ff ge fg be
cf de
 ce dc
  df ef
   eg fg
    dd ec ee ff cc cb
    fh eh dg gh
   dd ed cd fc
  cd dg df ef
 df fg
  ce dd cd dc cc gd db eb cb eh ef fc ff gf
  ef ff
dg df
 cf ce
  de ef cd be dd cg
  ef de ee ed
 ef ee cf de
 eg cf
eg df
 dg cf
  ef ee cg dc bf be bg gf gg hg
  cg ec ef ee bf be bg gf
 ef ee dg cf cg bg
fg dd
 ff ge ee ed
 dg gg
 ef cf ee ed
 gf ge
gf ff
 fg eg
  gg eh ge fd gd cd fc ec gc eb
  ge fd
 ge gd gg fd fg cf
 gg fg
ge gf
 gd fd gc fc
 fd ed
```
**You are White.** Black's first move fixes a conversion for the whole game. Convert each of his moves before looking it up and each book reply before playing it; every rule is its own inverse.
- E5; or row 5 left of centre (D5, C5); or D4: no conversion.
- Row 5 right of centre (F5, G5), or F4: mirror columns A↔J B↔H C↔G D↔F, E stays; rows unchanged.
- D6: mirror rows, row → 10 − row. F6: mirror both columns and rows.
- Column E below centre (E4, E3): swap column and row, i.e. swap the two code letters (E4 = ed → de = D5; C7 ↔ G3; F2 ↔ B6).
- Column E above centre (E6, E7): swap column and row, then mirror both (E6 → D5; G6 ↔ D3; C4 ↔ F7).
- any other first move: no book.
```
de ff
 ef fe
  fg gg
   eg fc
    dc be
     gh cg
      hg cd dd he cc cf gf ge
      ee bc fd gd ed he hg fb
     ee bg fd gd ed gc
      gh ch ge he gf hf hg eb
      ge gf
     ec fb
    ee dc fd gd ed gc ec eb gh cd ce be
    ed fd
     ec be
      fb gb eb bg gh hf hg gf hh hc
      gh bg
     gh cd ec ce
    gh cc
     dc db dd eb
     cd dc
    dd db gh cc
   ee fd eg dc
   gh dd
  ee fd
   fg gg
    eg ec
     dc db cc gh cb fh eh eb
     gh cc
    gh ec
   ed fc
  eg fg
   ed gc
   ee fc fh gh eh dc
   fh gh eh ed dd ec dc db cb eb
  ed fd fg gg
   fc gc eg ec
   eg cd
  fd gd ed gc fg gg
 fe ee
  ed ef
   df dg
    gf dd cd fd
     dc ge cg fc eg fg dh fh
     ge ec
    fd dd cd dc cc cg ce gc gf eb
    cg dd
    dd cg
   fd dd
    ce dc gf gg df ge hf gd
    cd dc df gf
   ge dd
  ef ed
   fd fc
    gf fg
     ec dd
      df gc ge cd
      eg eh
      dc cd eg gc
     dd ec eg gg
    ec dd dc cd
    dd ec
   gf fg fd ec eg gg fc fb
   fg gf
   ge df eg dg ce gf eh he
 fd dg
  fe gf
   ef eg
    cf cd cg db ge he
    df cg ge be hf hg he cc
    ge cc
   cf cg
   cg cc
   df cg
  df cg eg fg
   eh ef fh gh
   ef eh fe be
  ge cc
  ee eb
  ef eg
  gf gg
 ed dg
  fe gf
   ge dc ef eg hf hg he eb cf cd cg gh
   ef eg ge cc hf hg he be cf eb cg gh
  gd ge fd cf
  df cg eg fg
  ef eg fe gf ge cc hf hg he eb
 ee gd fe ge
  ef fg eg ec fh gh eh cc gf gg hf hg
  gf gg hf fg hg hh gc fd
  fg gf
  eg fg
  fd gc
 df fc fe ge
 dd eg
 dg fc
ee cd
 dd ce
  cc dc ec db
   cb eb
    fb fc ed gb
     fd gc
     df cf cg bg dg bh
     cf df
    ed fb cf bf
    de fc cf bc
    fc fb
   eb cb
    bc bb cf gf
    df gf
   de eb cf bc
   bc eb
  de cg cc gd cf bf df gf dg ch dh bc
   dc bd
    bb ab cb dj bg bh
    gc hd
   bb bd
  dc gf
   de cg
   ef dg eg gd
   df gd
  df cf cg dc ec db
 ce be
  dd cf de cc dc cb db he df cg dg gg ch bh dh gc bf bg
  de bf dd cc dc he cb bb db gg
  cf bf dd cc
 ed cf
  ef ge eg gc
  df cg dg he ce be de bc ch gg
  eg gd
 df ec
  ed fc dc dd db cc
  ce gf dd dc
  fd fc gc gb gd eh
  dd dc
  fc fb
 de dc ce gg
  ec eb fc fb gc eg
  ge eg
  fe eg
 ec df ef dg eg he
  de ce dh ch eh gc cc bc
  dh ch eh gc de ce
 fd df
  ef dg eg hd de ce
  de ce
 ef ec ed dc fc fb gc eh
 ff dc
 cf ec ed dc fc fb
 fe df de ce
dd fd
 ed fe
  fc gc
   ec ef
    df dg
     cf cg
     cg eh
    gb dg
   gb ef
   fb ef df dg
   ee fb ec ff ef fg eg cc
  ee ff
   ef eg dg fg fc gc
   fc gc
  ef ff
  df fg fc gc
  ff ee
 ee gf
  fe ge
   gd gc hd fc hc hb
    gg ff ef fg eg fh
    he fg hf hg
    ff gg
   eg dc
    ec ed fc gd
    ed cc ec be
   ed fc
   fc eg gd hd gc cg
   ff gc
  ff gg
  ed fc
 fe ge
  ee gf
   gd gc hd fc hc hb
   eg cc
  ed ff ee gd ef fg eg cc fh gh eh be
  ff gf
 ff ee ef de
  ce df cf dg cg hd
  df ce cf bf fe ed gd gc
 df ff ef fg
 de fg fe ge
 ef ge ed be
 ec fg fc cf
ce ff
 ee gd
  fe ge ef fg eg ec fh gh eh cc
  ef fg
 df fd
 fd ed fe ee
 dd fd
 ef fe
 ed dg
```
Before playing a book reply check it is in Legal moves; if not, you made a decoding or conversion slip — redo it.

## After the book: corrections from engine review of your own games
You already play sensible Go. A strong engine reviewed many games you played against these bots; you lost points in the same few ways. Apply these corrections on every turn (later prompts will not repeat this text, so keep doing it all game). There is no clock: take the time to do it properly.

1. **Go where the board is empty.** Your commonest big error (moves 8–35): you keep adding stones where the fighting has just been — pushing along his wall, connecting, answering his last move — while a wide empty area is untouched. In 70% of your errors the engine's move was in an emptier part of the board than yours. Every turn, first find the largest empty area and the place on its edge where your stones and his meet. The right move there is usually on the SECOND or third line, not the fourth or the centre: a move that extends your border and at the same time stops him sliding under it — a hane or block on the end stone of his wall, or a diagonal/knight step down from your own wall end.
2. **Do not answer his last move by reflex.** Answer only if he really threatens to capture or cut off stones that matter, or to break into your area. Otherwise play your own biggest move (rule 1).
3. **Lines 1–2 decide 9x9 games.** Wherever the border between the two areas runs out to the board edge and is still open, the first player there gains 3–8 points, usually in sente: second-line hane or block, later first-line hane and connect. Play all such moves that he must answer before quiet moves.
4. **Bend round, do not crawl beside.** When your line of stones runs next to his (yours E6 F6, his E7 F7), play in front of his line's head (G7), not the parallel extension (G6). If instead he threatens to bend round your head, extend first.
5. **Settle the biggest unsettled group first.** A large group (yours or his) that has no two eyes, is not connected to a living group and is nearly enclosed is worth more than anything else: for yours, connect out or make the second eye now; for his, take the vital point (the middle of his eye space or the point that seals his exit). Such points often stay on the board for several moves — look for them every turn. After the book your lead usually IS a weak group of his: find his group with the least eye space and take its base (typically a second-line move under or beside it) before he fixes it.
6. **No reckless contact.** You threw away won games with a cut or "double atari" whose stone could be captured at once, and by starting fights at the cutting points of your own thin shape. A cut, hane or atari is only good when your stone survives his best reply.

## Routine for every move after the book
**Effort rule.** Book moves need no thought. When the book ends you are normally ahead, often in the middle of a fight the engine was winning: first finish that job (capture what is in atari, keep your cutting stones and thin groups safe). From then on every move needs real work: these bots out-read a quick intuitive answer, and one careless move loses a whole group. On each such turn actually write out in your reasoning the census (A), the emergency test (B), three or more candidates with his best reply (C) and the neighbour/liberty check (D) — a few hundred words of reasoning per move. If you are about to answer after a sentence or two of thought, stop and do the routine. Do not let the speed of the book moves or of your own earlier turns set the pace. Every move prompt ends with "Write that entry on a single line, then end the response immediately": treat that sentence as your cue to run A–D first, on every turn until the game ends, however long the conversation gets.

**A. Census — never skip it.** Rows are printed 9 (top) to 1 (bottom); characters 1–9 of a row are columns A B C D E F G H J (no I; H is next to J). Note his last move. Then list every group of either colour that has 3 or fewer liberties — however large — with its liberties by name, and the liberty count of your own largest groups. A big group with 3 liberties and no two eyes is in danger even if nothing looks wrong.
**B. Emergency?**
- His group in atari: capture it if it is 2+ stones or the stones cut yours.
- Your group in atari or capturable in a ladder/net: save it if it matters (best by capturing the attackers), otherwise abandon it and play big.
- Capturing race: a group of yours with 3 or fewer liberties touches a group of his with few liberties and neither has two eyes. Now only liberties count. If he has fewer than you, or the same number and it is your move, fill HIS liberties (outside ones first, shared ones last), making sure each filling stone is not itself captured. Otherwise add liberties or connect to a stronger group. One wrong move here loses the whole group — you have lost 70-point groups this way.
- Never play on a liberty of your own group (a point inside or beside your own stones that makes no eye, captures nothing and connects nothing): it only shortens your own liberties.
- Sealing in: if he can close the last opening of one of your groups (4+ stones) with one move and it has no two sure eyes, act NOW — extend through the opening toward your other stones or the open edge, or connect. Once sealed, make eyes with the centre point of the inside space, not with first-line crawls. Likewise a cut that would leave a big group of yours without eyes: defend. Rule 5 groups count as emergencies.
**C. Otherwise** pick candidates from rules 1, 3, 4, 5 (at least three, in different parts of the board), imagine his best reply to each, and choose the one that gains the most area; among similar ones prefer the move he must answer.
**D. Check the chosen move — never skip.** Name its four neighbours and what is on them. Count the liberties of your stone's group after the move: it needs at least 2, and at least 3 if the group is 4+ stones without two eyes, and it must not be fewer than that group had before (unless the move captures). Can he capture the stone or cut behind it with his very next move? Does any group of yours stay in atari? If something fails, take the next candidate. Then copy the coordinate from Legal moves.

## Tactics reminders
- Before an atari, ask where he extends: an atari that drives him out or lets him connect only helps him.
- Ko: if the recapture is not in Legal moves, play an atari he must answer, then retake.

## Scoring, endgame, passing
- Area scoring with nothing removed at the end: score = your stones + empty regions touching only your colour. Dead enemy stones left inside your area still count for him and spoil the territory around them: really capture them before the game ends. Black needs 45+ of 81 points (44 is a draw), White 38+.
- Stones inside your own area cost nothing. When borders and neutral points are finished, use moves to capture leftovers and fix cutting points — but never fill one of your own last two eyes and never self-atari.
- Fill every neutral point (check first that it does not put you in atari). Answer every stone he plays inside your area so it can neither connect out nor make two eyes.
- Before passing, count the board exactly as it stands, row by row (stones of each colour, plus empty regions that touch only one colour; White adds 7). Pass only if that count gives you the win and all borders are closed, no neutral point remains, no enemy stone inside your area can still be captured and none of your groups can be attacked — whether or not he has just passed. If the count is a draw or a loss, never pass: a stone played inside HIS area costs nothing under area scoring even if it dies, so keep testing him — ataris, cuts, a placement on the vital point of a group with little eye space, an invasion where there is room for two eyes — while never weakening your own groups; these bots blunder whole groups late. Only when no such try is left and nothing but moves inside your own area or self-ataris remains, pass. Never resign.
