# 9x9 opening book (Tromp-Taylor, komi 7)

A bot of your strength played a stronger opponent many thousands of times; these are the moves that won most often. While your game is in the book, play the book move even if another looks more natural.

Notation: a point is two letters, column then row, with a b c d e f g h j = 1..9, so `ee` is E5 and `gc` is G3. Answer the game in its own coordinates (E5), never in this notation.

Reading: one book per color. A line lists moves from the empty board, Black first. The number starting a line is the move number of its first move; a line starting after move 1 keeps the earlier moves of the line above it (itself completed the same way). Your moves are the book's choice and the opponent's moves are the replies it knows; when the opponent plays anything else or the line ends, the book is over. Write your game in this notation, find the line matching it move for move, and play the next move.

Symmetry: the book shows one orientation of each position. A map T changes every point the same way: optionally swap the two letters, then optionally mirror the first letter, then optionally mirror the second (mirroring exchanges a-j, b-h, c-g, d-f and keeps e). Find the T that turns your game's moves, in order, into the start of a book line. Then undo T on the book's next move: mirror the same letters, then swap if T swapped.

After the book: scoring is strict area scoring with no dead-stone removal. Before passing, capture every dead enemy stone in your area, and never pass while the opponent can still do this to you. With every point owned, Black wins with 45 or more of the 81 points and White with 38 or more.

## Book when you are Black
1 de fe fd gd gc fc ed ec ge hd dc gf gb he cg eb db ea da ee dd df cf dg dh eh ch eg hc
22 hc fa hb eg
20 hc hb
12 gb eb hc ff he gf hf dg
14 fb ff db he
8 ge hc ec dc fb db gb hb hd ga ha ja
16 ha ga fa ea
12 db cb fb gb
10 fb ec eb db gb hb hd ga
8 gb hc ge ec fb hb
8 fb gb ge eb
6 ge ee fc ed gb hc hb ff gf fg
10 fb gb
6 ee ed ge df hc dd gb fg gg gh
4 ge gd ee ed df cf ce dd cg bf bg be dg he hf hd gf jf jg je
14 be dg ef bg ch bh dh cd bd bc hd hc he jc
22 hd hc he jc
10 cg dg ef dd dh he hf bg
10 dd ce dc ec db eb hd hc he dg ef cd
10 dg cg
8 dd df cd he
6 hd ee he eg gc fc
8 ff ef fg hc
4 ee ed ge df gd gc hc dd gb fg gg gh
14 fc ec
6 df ge dd ce cd cf
4 ff gd df cf
2 fd fe ge gf ff ee gg hf
8 fg he gd gg gh hd hc gc
12 fh hd
8 gd fg hf gg hg dc
6 gd ed ff fg ef ee eg gg eh cg ec dc
4 gd dc ge fg ff ef gf eg gg eb
8 gg gf
8 gf dg gg eb fh eh
8 ee df
6 ed dd ee ef ff fg gf gg
4 ed ee dd ce cd ge gd hd
2 ed dd ec ff dc cc cb ee fd bc
8 ee ef df cf dg cg dh ch fh gg
10 cb df bc gd gc hc
14 cd bf
6 ee ef dc df cc ge
4 ee ef ec ff dc cc cb df bc gd gc hc
14 cd bf gc hd
10 df cf dg cg dh ch ce cd be cb
16 fh gg gh hh
6 ff ec eg df dg cg fc fg
12 ch fe
8 df eg dg fg fe gg fc dc dh ge
8 fc fg
4 dc cc ec ff ee ef cb bd
6 ee ec db eb
4 fd ee fe ff gf gg
2 ee ed ef df eg fd dg cg ch dd bg gf gg hg gh cf
16 hh hf
14 cf be gg ge hg hf ce cd
16 ce cd gg hf hg jg
6 fd fc eg gd fe dd
6 dg fd eg gf
4 df fe ef ff cf fc
2 dd ed cd ce ec fc fd ee gc fb eb gb gd dc
10 gd gc
6 bd fe
6 ee fd
4 ee df
4 ce cd dc cf
2 ge ed ff eg fg eh fh gc ef cg
6 ef df fg eh
4 fd fc gc fe gd ff
4 fe gc ee df dd ec
4 gd eg gg fc gc gb
4 gc fc gd ff gf fg
2 fc ef fe gg ff fg dd cd
8 dc cc
4 ed cc
4 gd dc gf gg
2 ec ee fd gf fe ff cc be bd cd
4 dc gd
4 fc gd gc gf cc ce
4 cc fc
2 dc ee fc cc
4 ec fe fc cd
2 gd ff gf gg ge dc
4 fe gf ee ef dd cd
4 fc dc gf gg
4 fd dc
4 ed cc
2 ce cd cf df cg dc dg eg eh fg fh gg gh gd
2 cd ce dd ed ec fc fd ee gc fb eb gb gd dc

## Book when you are White
1 ee cd dd dc ec ce cc db cb eb fb fc ed gb fa ga cf df cg ef ff fe fd gc
17 gc fd
17 fd gc gd dg hc cf
17 df cf cg dg eg bg
15 fd gc gd cf hc hb hd ef da fa ca ff ea hf fb eb
23 fa ga jb ea ca bc
17 cf df cg dg de bf
15 cf df cg ef ff fe fd gc
15 df cf cg dg eg bg dh bc
11 fc de ed ef ff eg fg fb
9 eb cb bc bb df gf cf fd
9 bc eb fc fb gc gb
11 ed fc cf df
7 db gf cc dg eg fg ef eh df cg
7 df cc cf eb fc gg
7 de cf
7 ed dg cc fg bc gf
5 ed ec fc ce
5 cc ce ec db cb eb fb fc ed gb
3 ce de df dd ed ef ff eg dg fg gg dh cf bd
9 cf eg
5 dd df cf cg dg ef eg ff fg gf
3 ed ce ef cc ec gf eg gc
7 cf bf cg he bg gg
5 df cf cg dg
7 dg gd cg gg
5 cf df cg dg dh eh
5 ec gf ef cg
5 dg fg
3 de ec ce gf ge he gd hd gc hc gb bd
9 fe gc
7 fe eg
7 fd fc gd eg gc bd
3 df cf ce be de cg dg gd ch ec dc dd ed fc cc bd bc bh
13 ge dd
5 cg ce dg fc
7 ed dg
3 fd gg
3 ec gf ef cf eg gd
3 ef ec ed fc
3 ff ec
1 de dd ed ee ef fe fd gd ge ff gf fg gg ce df fh cd dc gc cf cg dg dh eg
13 dc cd ce be bd cc
9 dc cd ge ff
7 ff ge
7 ec df ce cf eg be cd dc
5 df fd ec fc dc ef eg cd cc bd bc dg cg dh
9 eb fe cd eg dg dh
5 cd dc ec eb
7 fd ef df cc eg ge
3 ee ce ed cf cd dc cc db cb fc ec eb fb gb gc fd fe gd ge hc
7 dc cd cc bc bb ec eb fc fb gc gb ge
5 cf ed fe cd fd fc gc bf cg bg ch gg fb eg
17 bh ec
7 cd fd fe gd
5 cd cc bd be bc dc bb fd fe ge
3 cd cc dc ed ec fd fc ce bd df gd ge
5 ce dc ee gd
3 ce ee ef ff
5 ed fd ec fc
1 dd ef ee df ff fe fd ge gf hf he gd hg hd jf de ed cd cc bc gc dc hc cb
11 fg gd gc hg fh dh
11 gg hg gh gd gc hc
9 fg gd ed eh
7 ge fd gd gf fg fc gc fb gb de
7 gf ge he fc
5 fe ff gf de cd ge gd he hf hd hc gc fd hb fc gb
13 gg hd fd gc fc gb
7 ge gf hf hg he cd cc ce bc bd
3 df de ce ee ed fd fc cd
3 ed cf fe gg
5 ff fe
5 cd ge
3 de fd df dg eg fg eh fh
3 fd gf gd ce cd be
3 ce ed ec fc
1 ce ed dd ee ec fc dc fd fb gb eb eg cg ef
9 df fg
9 eg df dg cf cg be
9 de fg fb gb
7 eb cf df de
7 fb cf
5 dc ec eb fb db fg
3 ee fe ef ff eg fd fg cd
5 dd ef
3 df ff dd dc
3 de ff ee fe fd gd fc gc ec dg
3 ef cd
1 cd fe de eg dg dh cg fc ef ff fg gg
5 fd gd fc ee gc ed
1 cc ff dd df fd he
