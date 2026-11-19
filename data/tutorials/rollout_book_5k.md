# 9x9 opening book (Tromp-Taylor, komi 7)

A bot of your strength played a stronger opponent many thousands of times; these are the moves that won most often. While your game is in the book, play the book move even if another looks more natural.

Notation: a point is two letters, column then row, with a b c d e f g h j = 1..9, so `ee` is E5 and `gc` is G3. Answer the game in its own coordinates (E5), never in this notation.

Reading: one book per color. A line lists moves from the empty board, Black first. The number starting a line is the move number of its first move; a line starting after move 1 keeps the earlier moves of the line above it (itself completed the same way). Your moves are the book's choice and the opponent's moves are the replies it knows; when the opponent plays anything else or the line ends, the book is over. Write your game in this notation, find the line matching it move for move, and play the next move.

Symmetry: the book shows one orientation of each position. A map T changes every point the same way: optionally swap the two letters, then optionally mirror the first letter, then optionally mirror the second (mirroring exchanges a-j, b-h, c-g, d-f and keeps e). Find the T that turns your game's moves, in order, into the start of a book line. Then undo T on the book's next move: mirror the same letters, then swap if T swapped.

After the book: scoring is strict area scoring with no dead-stone removal. Before passing, capture every dead enemy stone in your area, and never pass while the opponent can still do this to you. With every point owned, Black wins with 45 or more of the 81 points and White with 38 or more.

## Book when you are Black
1 de fe fd gd gc fc ed ec ge hd dc gf gb he cg eb db ea da ee dd df cf dg dh eh ch eg hc
28 hc hb
22 hc fa hb eg
22 eg dg
20 hc hb ee dd
18 ee dd
16 db eb cc dd
16 ee dd df cf dg dh
14 ee dd df cf cg ef dg ff
16 he df
14 eb db he dg ea da
16 ee dd df cf
14 df ef
14 ef cg df cf
12 gb eb hc ff he gf hf dg gg fg
20 hg ee
16 gf ee gg fg gh fh he fe
14 fb ff db he
8 ge hc ec dc fb db gb hb ee dd df cf cg dg
16 hd ga ha ja fa ea
16 ha ga fa ea
12 db cb fb gb
14 eb cc gb hb
12 eb db gb hb ee dd
12 ee dd
10 fb ec eb db gb hb dc cc
16 ee dd df cf
16 hd ga
8 gb hc hd fb ec hb
10 ge ec fb hb
8 hc gb fb ge hd ff
8 fb gb ge eb
10 hd ec
6 ge ee fc ed gb hc hb ff gf fg
10 ec dc gb hc
10 fb gb
8 hc fc
6 ed fc ee dd ec dc
6 ee ed ge df hc dd gb fg gg gh
10 dd dc
8 dd df dc ge
8 df cf
6 hd ed
4 ge gd ee ed df cf ce dd cg bf bg be dg he hf hd gf jf jg je
22 hg cd
16 hd hc he dg
14 be dg ef bg ch bh dh cd bd bc hd hc he jc gc gb
28 bj ae
22 hd hc he jc
14 dg he
12 bf cg dg ch dh be
12 cd dg ef cg
10 cg dg ef dd dh he hf bg
14 bf ce dh bg
10 dd ce dc ec db eb hd hc he dg ef cd
16 dg cg
16 cg dg
12 cd dg
10 dg cg ce dd cd cc
14 be dh
12 dd ce dc eb
12 dh ce
8 dd df cd he hf hd
10 dc he hf hd
8 hd df
8 he df
6 hd ee he eg gc fc
10 gg cc
8 gc ed
8 ff ef fg hc
8 fg hc
8 hc ff
6 ed ee ec he
6 he ed hd eg
6 df ee
4 ee ed ge df gd gc hc dd gb fg gg gh
14 fc ec
12 fc gb
10 dd dc cd cc bd bf
10 fc ec
6 df ge dd ce cd cf ef cg gd gc
10 dc cf ef gd
8 gf gd dd ce
6 gd df ge dd
6 dd df
4 ed ee gd fc ec fb
8 gc ff
8 ff eg
6 fc gd ge gc
8 ff gc
6 ec ff ge gf
6 ff fc
6 ge ec
4 ff gd df cf dg ce cg ee ef ge
8 cg ce
6 ed ee
6 dg cd
4 gf ed gd gc
4 ef ee
4 fg ee
2 fd fe ge gf ff ee gg hf he fg
10 gd fg fh ef
8 fg he gd gg gh hd hc gc fc gb
12 fh hd
8 gd fg hf gg hg dc
8 hf gg fg gh fh he
6 gd ed ff fg ef ee eg gg eh cg ec dc
12 df cf dg cg
10 ee ef fe dd eg df
8 ec dc ff ee gg hf
8 hf ff
6 ed ee dd ce
6 he ff ed dd dc cc
4 gd dc ge fg ff ef gf eg gg eb
8 gg gf hf ff hg fh
8 gf dg gg eb fh eh
8 ee df ff eg
8 ed dd
6 ed dd ee ef ff fg gf gg
6 ee ef
6 gf ge he ff
6 ff ef
4 ed ee dd ce cd ge gd hd hc he
12 be bf
8 ge gf gd cd cc hf
12 hf gg
10 cd gd he hd hf hg
8 gd ge cd bd
6 gd dd ge gf dc cc cb db
10 hf gg hg hh
8 dc cc
6 ge gf gd dd hf gg
8 dd gd he hd
4 ee ed ef ff
4 fc ge dc cg
4 gc ee
4 ec ge
2 ed dd ec ff dc cc cb ee cd bc bd bb db ce
10 gd ge
10 fd bc
8 ee ef df cf dg cg dh ch ce cd
16 fh gg
10 cb df bc gd gc hc gb cd
14 cd bf
6 ee ef dc df cc ge
4 ee ef ec ff dc cc cb df bc gd gc hc
14 cd bf gc hd
10 df cf dg cg dh ch ce cd be cb
16 fh gg gh hh
10 cd ce bd be
8 df dc
6 ff ec eg df dg cg fg fd fe fc
12 fc fg fh gg
12 ch fe
10 fc fg gg fh
8 df eg dg fg fe gg fc dc dh ge
14 dc cc
10 cf fg fe dc gg ch
8 fc fg dc eb
10 eg df
8 fe fc
8 fd fc
6 dc ff
6 df ff
4 dc cc ec ff ee ef df cf
10 cb bd
6 ee ec db eb
4 fd ee fe ff gf gg
4 fe eg dc ec fc eb
4 fc ff dc cc cb db
4 gd ff
4 ff ee
2 ee ed ef df eg fd dg cg ch dd bg gf gg hg gh cf
16 hh hf
14 cf be gg ge hg hf ce cd
16 ce cd gg hf hg jg
12 cf bg bf bh dh be
12 ge gd he fe
12 gf ge
10 dd cd dc cc db cb ce cf
16 fb gd
10 cf ce bf be
8 gf dg
6 fd fc ec dd gc fb eb gb
8 eg gd fe dd
8 gd ec eg dg dh ch
8 dd ec
6 dg fd eg gf
8 cg gf
6 dd fd
4 df fe ef ff dd ce cd be
8 cf fc
8 fg gg
4 dd df fe fd
6 fd ec
6 ec fd
4 ff fd df cf
2 dd ed cd ce ec fc fd ee gc fb eb gb gd dc
10 gd gc hc eb
10 fe ff gc fb
10 fb gc
8 ee fd ef bd
6 bd fe ec fc eb fb
6 ee fd ef bd dc ec db eb
6 be ec
4 ee df fd ec
6 fe fd
6 ec fd
4 ce cd dc cf be ee
2 ge ed ff eg fg eh fh gc ef cg df cf
8 ef df
6 ef df fg eh
6 fd ec fc ef
4 fd fc gc fe gd ff
4 fe gc ee df dd ec
4 gd eg gg fc gc gb hb fb
6 fc ec eb db
6 gf fc
4 gc fc gd ff gf fg
4 ef df eg dg
4 gf dg
4 fg dg
4 gg ff
4 fc ff
2 fc ef fe gg ff fg dd cd
8 dc cc
6 dc cd
4 dc fe cd ce be bf
4 ed cc fe ff
4 gd dc gf gg hg fg
6 fe ff
4 ge dc
4 fd ge
4 ec gf
4 gf dc
2 ec ee fd gf fe ff cc be bd cd
8 cd ce
8 dc cd
6 cc cd
6 dc hd
6 ge fe
6 gd cc
4 dc gd gc fd fc dg
6 cd ce
4 gc fe dc gd
4 fc gd gc gf cc ce
4 gd ge he gf
4 cc fc fb fd
4 fe ff fd gf
4 ge fd
2 dc ee fc cc ec cd
4 ec fe fc cd
6 gc cd
4 cd ce
4 cc fd
2 gd ff gf gg ge dc fg eg fh eh
6 fe ef hg hf
6 hf fe
4 fe gf ee ef dd cd
4 fc dc gf gg
4 fd dc gf ef
4 ed cc dd cd
4 ge gf hf hg he ec
2 ce cd cf df cg dc dg eg eh fg fh gg gh gd
6 dg cg bg ch
4 df cf be bf bd dd
4 dd cf be ed
4 be df
2 cd ce dd ed ec fc fd ee gc fb eb gb gd dc
10 gd gc hc eb
10 fe ff
8 ee fd ef bd
6 bd ec
6 ee ec
4 dc dd
4 bd dd
2 gc ge ec dg
4 fd fe
2 cc ff dd ce
4 ce cf
2 he fe gd fd
4 ge fd
2 be ed
2 hd ge gd fd
2 fb ff
2 bd cd
2 eb ef
2 db ef

## Book when you are White
1 ee cd dd dc ec ce cc db cb eb fb fc ed gb fa ga cf df cg ef ff fe fg fd eg de
25 ge de
25 dg de
23 fd gc ge de
23 ge fd gf de
19 dg ef ff eg fg eh cg de
21 eg ff
19 bf ef
19 ef dg
17 gc fd
17 fd gc gd dg hc cf hb ea ca bc
21 eg df ef dh eh bc
19 cf df
17 df cf cg dg eg bg
17 da ea
15 fd gc gd cf hc hb hd ef da fa ca ff ea hf fb eb
23 fa ga jb ea ca bc fb bb
23 jb fa
19 dg cg ch bh dh bc
19 hd bc bb bd
19 da fa hc hb
19 eg cg hc hb
17 cf df cg dg dh de
21 de bf
19 dg ef ff eg fg eh
19 bf ef ff fg gg gf
17 df cf cg bg
15 cf df cg ef ff fe fg fd eg de
23 dg de
21 ge fd gf de
23 fg de
21 fd gc ge de eg dg
17 dg ef ff eg
17 ef dg eg dh
19 bf eg
17 bf ef ff fe
17 de ef
15 gc fa fd fb gd cf
17 gd fd fe fb
15 df cf cg dg eg bg dh bc
15 bd be
15 gd fa
11 fc de ed ef ff eg fg fb
15 fb ff
11 ed fb cf bf
11 de cf
9 eb cb bc bb cf de ed df ef dg eg eh fh dh
13 df gf cf fd ed fe
13 ed gg cf df
13 de cf
9 bc eb fc fb gc gb de cf df cg
15 cf de
13 gb gc
11 ed fc cf df
13 fd gc
11 de cf df cg
11 cf de
7 db gf cc dg eg fg ef eh df cg
15 cf df
15 dh ch
15 fh dh
11 ff fg ge gg
11 ef eg fg gg
11 fg ff
11 df cg
7 df cc cf eb fc gg
7 de cf cc db cb eb fb fc ea ed
7 ed dg cc fg bc gf
9 eg eh
7 ef dg eg eb
9 cc db
7 cf cc
7 eb fg
7 eg db
5 ed ec fc ce
5 cc ce ec db cb eb fb fc ed gb fd gc
9 bc eb
9 eb cb
5 fd de
3 ce de df dd ed ef ff eg dg fg gg dh cf bd
13 ec be
11 cf fg ec bd
13 dc bd
9 cf eg ec bd dc dg
9 eg ff fg gf ec cf
11 ec cf dg fg
9 dg eg
9 ec cf
7 cf ed
7 ef fc ed ec
5 dd df cf cg dg ef eg ff fg gf
11 ff eg dh bf
11 bd eg
11 ed bf
11 bg ed
9 bd cc dg ef
9 ef dg
7 ed ef cc bd be bc
9 ff cc
9 be ff
9 bd cc
7 ef cf be bf
7 cc bd cf cg
3 ed ce ef cc ec gf eg gc
9 fg gd
7 cf bf cg he bg gg
5 df cf cg dg
7 dg gd cg gg
9 ec gf
5 cf df cg dg dh eh
7 ef cg
7 dg ef
5 eg he
5 ec gf ef cg
5 dc gf
5 dg fg
5 cc dc ec db
5 cg df
5 ff df
3 de ec ce gf ge he gd hd gc hc gb bd
9 fe gc
7 fe eg
7 fd fc gd eg gc bd
7 dd fd
7 dc fd
7 ff ge
7 gd fd
7 bd gd
5 fd ce cf fc
5 fe ce
5 fc fd
5 dd dc
3 df cf ce be de cg dg gd ch ec dc dd ed fc cc bd bc bh
13 dd dc cc bd
13 ge dd
13 bf bc
13 cc dd
13 fd fc
11 dd cc dc gg
9 bd bc dg gd
9 dd cc
5 cg ce dg fc fd ec
7 ed dg eg dh ch eh
7 bg ec
7 ec gf
5 dg ec ce be
5 dd ce
3 fd gg dd ce cc bc
5 eg hd
5 ff fg
5 ce dd
5 df hd
5 ge df
3 ec gf ef cf eg gd
5 ff ge
3 ef ec ed fc dc dd
5 fc fd
5 fd fc
3 ff ec ed fc
5 ce dd
5 fc fb
3 cf ec ed dc
3 dc dd ed df
3 fe df de ce
3 eg ed
3 cc dc
3 ge ec
3 fc df
1 de dd ed ee ef fe fd gd ge ff gf fg gg ce df fh cd dc gc cf cg dg dh eg
19 be fc hd ec
21 gh ec
19 cc fc db ec
17 cf cd gc hd hc fc
19 ec gc
13 df gg hd gc
15 gc hd
13 dc cd ce be bd cc bf fc
17 cf bf cg gc
13 cd dc gc hd
13 gc hd
11 fg gf he hf hd gc
13 dc cd
11 df fg gc hd dc cd
11 gc hd
11 dc cd
9 dc cd ge ff df gf
11 ce be
9 ff ge dc cd
9 ec df
9 fc gc
7 ff ge dc cd ec df ce cf
9 cd dc cc db
9 ec df ce dg
9 gf df
7 ec df ce cf eg be cd dc cc db cb eb
11 ff ge
7 dc cd ce be bd cc bf fd
13 bc cb
9 fd ge gd df
7 df ec cd fd ff cc
9 ff fd
7 cd dc ec db
5 df fd ec fc dc ef eg cd cc bd bc dg cg dh cf fg
19 fg cf
15 dg bc
11 cd eg dg eh dh fb
11 dg eg eh cd cc fh
9 fe ef ff eg fg dg
11 eg ff ge gf
9 eb fe cd eg dg dh
11 fb cd
5 cd dc ec eb fe ef ff df ce cf
9 db cc fb ce
7 fd ef df cc eg ge
9 ce cc
7 fe ef df eg
9 ff df
9 ec eb
7 ef fe fd ge
5 ce ec fd fe gd ge dc cd
9 fc ge
3 ee ce ed cf cd dc cc db cb fc ec eb fb gb fa ga da ea ca df
17 gc fd fe gd ge hc
17 fd gc gd hd
17 df cg dg dh eh ch
17 cg df
15 fd gc
7 dc cd cc bc bb ec eb fc fb gc gb ge
11 ec gf eg gd
7 eg dc
7 df dc
7 ec eg
5 cf ed fe cd fd fc gc bf cg bg ch gg fb eg
17 bh ec
17 gf hf
15 bh gg
9 bf fd gd ge
7 cd fd fe gd
9 be gf
7 fd cd fe fc
9 fc fe
5 cd cc bd be bc dc bb fd fe ge
11 cf bf bg cg df bh
11 ed bb ec gg
9 dc ed bc fd fe cb
11 fd ec
3 cd cc dc ed ec fd fc ce bd df gd ge
7 ee fd
5 ce dc ee gd
5 ee ce
3 ce ee ef ff fe ed ge eg df cd
7 ed fe
7 eg fe fg gg
5 ed fd ec fc eb ef
5 cd ef ed fd
3 dc ed
1 dd ef ee df ff fe fd ge gf hf he gd hg hd jf de ed cd cc bc gc dc hc cb
21 dc bd
11 fg gd gc hg eg dg
15 fh dh
13 ed hg
13 eg de
11 gd he fg de
13 hd fg
11 gg hg gh gd gc hc
9 fg gd ed eh
11 fc gc
11 de cf gc fc
11 gc fc
11 cf de
9 gd gf
7 ge fd gd gf fg fc gc fb gb de
9 gf gd hd hc
11 ed hd
9 fg de
7 fg ge ed eg
9 eg dg
7 gf ge he fc fd gd
5 fe ff gf de cd ge gd he hf hd hc gc fd hb fc gb fb gg
15 fd gc
13 gg hd fd gc fc gb fb fg gh fh
15 gc hc gb hb
13 hd hf
9 ge cd
7 ge gf hf hg he cd cc ce bc bd
13 ce de cc bd
9 he cd ce de
9 ce cf bf bg
9 de cf
5 de ff fe gf
3 df de ce ee ed fd fc cd
7 cf ed
3 ed cf fe gg
5 ff fe gf ee
5 cd ge
5 ce ge
5 gf fe
5 fd gf
5 gd gf
3 de fd df dg eg fg eh fh
7 cg eg ch fe
3 fd gf gd ce cd be
5 ge cf ff fg
5 df dg
5 ee df ff fg fe gg
5 cf cg
5 ce cg
5 ed cf
3 fe ff ee df
5 ge ee
5 gf ee
3 ce ed ec fc fd ee gd dc
3 ff fe ee fd
3 cf fe ed fd
3 ec de
3 eg df
1 ce ed dd ee ec fc dc fd fb gb eb eg cg ef dh eh
9 df fg
9 eg df dg cf cg be bf bg af ag
9 de fg fb gb eb ef
11 ef ff
9 ef df
9 dg df
7 eb cf df de
7 fb cf df ef dg de
9 gc fd
5 dc ec eb fb db fg dg eg
11 df gc
7 db eg
5 df ef
5 de ef
5 ef ff
3 ee fe ef ff eg fd fg cd
7 fg fd gg dd cd cc
9 eg cd
7 fd gd fc ec
7 dd fd
5 de fd ff gf gg fg ef gh
5 dd ef de fd ff gf
5 ff de ef dd df ge
5 fd gd fc ff
3 df ff dd dc cc ec
5 ef fe
5 ee fe
3 de ff ee fe fd gd fc gc fb dg
11 ec dg
3 ef cd de dd
5 dd dc
3 cd ef
3 fe ee
3 dc ec
1 cd fe de eg dg dh ef ff fg eh gg gf hg hf
7 cg fc ef ff fg gg
9 ch eh
7 df fc ch gg
7 ch fc
5 fd gd fc ee gc ed
5 ee ff fd gd gc fc ed gb
5 ed fd fc ee
5 ef ff dg ee
5 fc cf
5 df dg
5 cf fc
5 cg fc
3 ed fd fc ee ec de
5 ee ff
3 ee ef ed ff
5 de ff
3 df eg
3 ef ff
3 fc df
3 dd fc
3 dc df
3 fd ed
3 ff ef
3 cf ed
3 fg df
1 cc ff df ed dd ec
3 dd df fd he
3 de dg
3 ee ef
3 ef ee
1 be cd
1 bd ff
1 bc ff
1 bb ef
