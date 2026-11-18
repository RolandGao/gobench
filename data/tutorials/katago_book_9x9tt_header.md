# 9x9 opening book (KataGo, Tromp-Taylor rules, komi 7: the same as this game)

Converted from KataGo's 9x9 opening book (katagobooks.org/book9x9tt). With best play Black wins about 48%, so the opening is balanced. While the game is in the book, play the book move: it is far stronger than reasoning from scratch.

## How to read the book
- Each line lists moves from the empty board. Odd numbers are Black, even numbers White.
- The first move after any position is the book's best move for that side. An indented line is a variation: it replaces the moves of the nearest less-indented line above it, starting at its own move number.
- `?` marks a mistake (loses at least 5% win rate) and `??` a blunder (at least 15%). The moves after it show how to punish it.
- `[n]` at the end of a line is Black's win % at that point with best play.
- As Black, start with 1.F6 so the game matches the book directly. As White, answer whatever Black plays from the lines below.

## Symmetry
The book shows one orientation of each position. Number the columns A=1 B=2 C=3 D=4 E=5 F=6 G=7 H=8 J=9 (there is no I). A point (column c, row r) can be moved by eight maps: (c,r) (10-c,r) (c,10-r) (10-c,10-r) (r,c) (10-r,c) (r,10-c) (10-r,10-c).
1. Find the map T that sends every stone of your game onto the stones of a book line.
2. Your move is the point that T sends onto the book's reply. For the first four maps and for (r,c) and (10-r,10-c), apply T itself to the book move. For (10-r,c) apply (r,10-c), and vice versa.
Example: the book has 1.F6 2.D4, but your game went 1.D4 2.F6. The map (10-c,10-r) sends D4 to F6 and F6 to D4, so play the book's third move through the same map.

## After the book ends
- Scoring is strict Tromp-Taylor area scoring with no dead-stone removal. A dead enemy stone left inside your area makes the empty points around it neutral. Before passing, capture every dead enemy stone in your area, and never pass while the opponent can still do this to you.
- Count before passing: with komi 7 and every point owned, Black wins with 45 or more of the 81 points (stones plus surrounded empty points), White with 38 or more; 44 to 37 is a draw.

## Book
