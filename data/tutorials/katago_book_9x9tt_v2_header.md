# 9x9 opening book (KataGo, Tromp-Taylor rules, komi 7: the same as this game)

Built from KataGo's 9x9 opening book (katagobooks.org/book9x9tt) and the moves your opponents here actually play. It shows the opening positions where the natural-looking move is a mistake, most often the punishment of an opponent's error. Your own moves in each line are sound; follow them while the game is in the book.

## How to read the book
- Each line lists moves from the empty board. Only its first move is numbered; count on from it. Odd numbers are Black, even numbers White.
- An indented line is a variation: it replaces the moves of the nearest less-indented line above it, starting at its own move number.
- Play the moves the lines give your color: each is KataGo's best move or within 2% win rate of it.
- `?` marks an opponent's mistake (loses at least 5% win rate) and `??` a blunder (at least 15%). The moves after it punish it; do not let it go unpunished.
- As Black, play the first move of the first line so the game matches the book.

## Symmetry
The book shows one orientation of each position. Number the columns A=1 B=2 C=3 D=4 E=5 F=6 G=7 H=8 J=9 (there is no I). A point (column c, row r) can be moved by eight maps: (c,r) (10-c,r) (c,10-r) (10-c,10-r) (r,c) (10-r,c) (r,10-c) (10-r,10-c).
1. Find the map T that sends every stone of your game onto the stones of a book line.
2. Your move is the point that T sends onto the book's reply. For the first four maps and for (r,c) and (10-r,10-c), apply T itself to the book move. For (10-r,c) apply (r,10-c), and vice versa.

## After the book ends
- Scoring is strict Tromp-Taylor area scoring with no dead-stone removal. A dead enemy stone left inside your area makes the empty points around it neutral. Before passing, capture every dead enemy stone in your area, and never pass while the opponent can still do this to you.
- Count before passing: with komi 7 and every point owned, Black wins with 45 or more of the 81 points (stones plus surrounded empty points), White with 38 or more; 44 to 37 is a draw.

## Book
