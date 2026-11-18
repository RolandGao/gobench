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

1.E5 G5 G6 F6 F5 G7 H6 G4 F3 H7 F7 E6 D6 E7 D7 F8 E8 F7 C5 G3 E2 F4 E4 F2 E3 E9
 2.F6?? F5 G6 G5 D7 D6 C7 H6 C6 C3 H7 E6 E7 C5 D3? H4 C2 B3
  4.E6 D6 G6? G5 D7 C7 D8 D5 E2 C2 C3 D2 D3 E3
   6.D7? C7 G5 G6 G7 H6 G4 F3
    8.C6 D5 C8 B7 G6 G5 E2 D8
    8.G6 G5 D8 D5 E2 C2
    10.D5 C6 G7 H6 G4 F3
    12.D5 C6 G4 F3
   6.G5 G4 G6 D5 H4 G3 C4 D2
   10.C6 D5 C8 B7 E2 D8
   14.H3? C8
  4.G5 E6 G6 F3
   6.G4 F7 G6? F3
   6.F7? G4
  4.D7 G6 G7? E6 F7 E7 E8 F8 G8 D8 F9 C7 D3 E2 C5 D2
  6.E6? D6 D7 C7 D8 D5 E2 C2 C3 D2 D3 E3
   10.C6 D5 C8 B7 E2 D8 E7 H6
   10.D5? C6 D4 D8 H5 H4 H6 E3
   14.H3? C8
  6.D6?? E6 E7 D7 D8 C7 F8 C3
  8.E7 C3 D3? C4
  10.H7 E7 H5? H4
  12.E2 E3 H7 H5
  12.D4? C4
 2.F5?? F6 F4 G6 E4 D5 D4 C5 E7 C7 C8 B8 G8 H4
  4.G5? G6 E4 D4 D3 E3
   6.E6 D5 E7 H5 H4 H6 G3 C7
    10.G3 F8
   8.E3 D3
  4.E4 F4 G5 G6 G4 F3 G3 F2 D4 D5
   8.D5 E6 D4 F3
  4.E6 E4 F7 G6 G7 D6 E7 H6 D7 F3
   8.D6 G7
  4.G6 G7 E4 G5
   6.F4 E4
  6.D3 C4 H5 E4 E3 H6 E7 F3 G3 F2 H4 D4 E6 F8 F7 G7 E8 G5
   18.C7 G2 H2 J3
  8.C3 H4 D7 C4 B3 B6
   10.E7 C7
  10.C4 B5 E7 E6
  12.C4 H4
  12.G8 C4 C3 H5 H7 G3
  14.H5 H6 C4 G5
 2.G6 G4 E7 C5 E3 C3 C2 F7 F6 E6 F8 D7
  4.E6?? D6 E7 D5 D7 C7 C8 G5
   8.D3? E2 C4 B5 C5 C6
   8.C3? D2
   10.D3? E2
  4.D7 E7 E6 F6 D6 F7 D5 D4
   6.F7?? E8 E6 D6 F6 C7 D5 D8 C6 B6 D7 E3 B5 D6 C5 B7
   10.F5?? F4 G5 D5 C5 C4
  4.F7 C4 D7 F6 G5 G7
  4.D6?? E6 E7 F7 D7 D5 F6 G7 H7 H8
  4.C6 E7 D4 E4
  6.C7 F7 F6 E6 E8 F5 H6 G7 H7 B5 H4 H3
  6.E2 C3 C2 D3 D2 E8
   8.F3 F7 F6 E6
  6.C4 D4 C3 B5 E2 F3 F2 G2
  8.G3 F7
 2.G7 E7 G4 C4 F3 D3 F6 F5 G5 E6 F8 F7 G8 G6 H6 E8
  4.G5 C4 C5 D5 F3 E3
  4.F4 E4 G5 F3
 2.H5?? C5
 2.H6?? F3
 2.H7?? D3
 3.F7 C6 C4 G3 D7?? B4 B5 C5 B3 E6 F5 F6 D6 G6 D5 E7 E8 F8 D8 C3 D4? B2 A4 D3
  5.G4?? D4 F4 E3 D7 G7 H4 G2
   7.D7? H4 G3 H3 G6 H6 F5 H5 H7 G2 F2 F4 F3 H2
    9.D5 C5 G3 H3
    11.E4 H7
    11.D5 C5
   9.F2? G7 G8 F6 E7 E6
   9.C7? D6 D7 E6
   9.D5? C5
   11.D5? C5
  5.F3 C4 F5 D7 D6 D5 E6 G3 G2 G4 C7 B7
   9.G4?? H4 H3 D3 E2 F8 E8 G8
   9.G6 D3 E2 H6
   13.C7 B7 G2 G4
  5.D4?? G3 B5 E7 E8 F6 E6 D7 F8 D8 H6 H5 B6 H7
   7.D7 B5 B4 C4 C3 C5 F3 F2
  5.D7?? C4 F3 G3 G2 F4
  5.C5?? B5 D5 G3 B4 D7 B6 B7 A5 E8
  5.G3?? F4
  7.F4 D4 D5 C5 G4 C3 F3 D7 E8 G7
  7.F3?? D7 E7 F4
  9.C3 C7 B5 C5 B3 D8 E8 E6 F6 D6 E7 F5 E4 B6 H6 F2
   13.B6 B3
 3.F5?? G4 G6? H6 G7 F3 C5 H7 E3 E2 H8 B5
  5.F3 C5 F7 G7 G8 G6 G3? F6 E6 F8
  7.F3 G7 F6 C4 F7 H7 B5 D3 E3 D6
  7.F7 G7 F6 F3
  7.H7? G7 F6 H8
  9.C6 B6 B5 H7 E3 C7 B7 E2
 3.C6 D3 F4 C4 E2 G7 F7 D6 E6 F8 E8 F6 B5 E7 D7 D2 G4 B4 F7 H5
  5.G6 F4 F5 G4 H6 C4 B5 D6
   7.H6 C4
  5.F3 C4 G6 H6 G7 H7 E3 D6
  7.F7 G7 E2 D6 E6 F8 E8 B6 G8 H8
  7.F6? G7 F7 D6 D5 G8
   9.E2 D6 D5 C5 C7 D2
  7.G4 F7 E2 D2
  9.B5 E3 F3 D2
  9.G4?? D6
  11.D7 B6
 3.F6? F3 C4?? D3 F4 G4 G3 H3
  5.G6? C7 E2 E3 F2 C3 G3 D4
   9.D3 F2
  5.F4? G3 G4 H4 E3 D4 E4 C6
  5.E3?? E2
  7.C3 D7
 3.E7 C4 D3 C6 G3 G7 C3 B5 G8 H3 H2 F3 H4 G4 G2 H8
  7.C3 B5
  13.H4 G4 H2 F3 G2 H8
 3.C5 F3 F7 D3 G6 H6 E4 E3
  5.G6 H6 G4 F4 F5 H5 G7 H7 E3 F2
  7.G4 F4 F5 G6 G7 H4
 3.E6?? C5
 3.D6?? G7
 4.H6 F6 H7?? G4 H4 F5 H5 G3 C4 B5 E3 C5
  6.F3 C4 H7 F8 C3 D3 C2 B4 D2 E3 E2 H5 G4 H4 H3 H8 G7 G8 C6 F7
   8.C7 H5 H4 G4 J5 G3 F4 F5 G2 H3
    16.H5? E8
   10.C2?? F4 G3 C3
   10.D3 C3 C2 B2
   10.D2?? C2
  6.C5 D4 C4?? H7 D3 E3 D2 C7 D6 D7
   8.C7 G3 C4 H7 D3 E3 D2 C3 C2 D6
   8.G3 C7 C4?? D2
  6.F4?? H7 C6? D3 F2 B5
   8.C7 B6
  6.C6 C5 B5 C4 G3 C7 D6 B7
  8.H5 F4
  12.C3 G8 G7 F8
  12.D4 C6
 4.F5?? F6 E4 D4 D3 E3
  6.E6 D5 E7 H5 H4 H6 G3 C7 G8 H8 C8 E8 C6 D6 D7 B7 E4 D4
   10.G3 F8 E8 F7
  8.E3 D3
 4.C6 C4 F6 E6 H6 F3
  6.H6 F6 G3 D8 B4 B5 C5 B3
 4.G4?? F6 F3 C6 C7 B7
 4.C4 F5 D6 D3
 8.H7 F3 G4 F7 E6 D6 E7 D7 F8 E8 F7 C5 G3 E2 F4 E4 F2 E3 G2 D9
  10.H5? C6 E6? D6 D3 E2 D5 E3 C5 B5
  20.F4 E4 G3 G2 F2 E3 H2 D9
  22.F2 F4 G2 D9 E1 D2
  22.G2 D9
  22.D8 C8
  24.G2 D9 F2 E3 E1 D1
 8.H5?? H7 F7 H8 G3 D7 D8 C7
 9.H7?? F7 H8 D7 F3 G3
  11.F3 G3 H8 D7 D6 C7
  11.D7? H8 F3 G3
  13.C6? C7 F3 G3
  13.D6 C7 F3 G3
 9.F7?? E6 D5 E7 F8 H7 D7 E8 D8 E9
 10.F7 G3 H5 H7 H8 F4 H3 C6
  12.H7 C6 B5 C3 C7 B6
  12.D6 C4
  12.C4 C6
 10.G3 F7 E6 D5
 19.D3?? G3 F2 C3
 19.C3 G3
 20.F4 E4 G3 G2 F2 E3 H2 D9
 20.D8?? G3
 22.F2 F4
 22.G2 D9 F4 E4 F2 E3 E1 D1
  24.F2 E3
 22.D8 C8 F4 E4 F2 E3
 24.G2 D9 F2 E3 E1 D1
 26.G2 D9 E1 D1
 26.G1 E9
1.F5 D6 D4 F7 G7 C4 C3 C5 D3 F6 G6 G5 E6 E7 E5 H5 D7 D8 C7 C8 G8 F9
 3.E6?? D5 D7 C7 E7 D3 F3 C8 D2 G4 F4 G5 G7 G3
  5.E7 D3 D7 C7 F3 C8 D2 G4
   7.C7 G3 G4 H3 E4 E3 D4 C4 C3 B4 B6 D7
  13.G5 F4
 3.D5 E6 E5 F6 G6 G7 G5 C5 C4 C6 B4 D3 C3 G3 E2 E3 D2?? F2
  7.G5 G6 B5 E2
  9.H7 C5
  13.B5 C3
  13.B3 D4 D3 B4 C3 H7
  15.E2 D4 C2 H7 H6 H4 E3 J6
   17.B2 H7 H6 B5
  15.F3 D4 C2 G3
  17.F2 F3
 3.E4? F7 C4 D3
 3.F7 D4 F3 E7 F8 D2
 3.C4?? D4 D3 E4 C5 F4 F7 C3
 7.D3 C3 D5 C5 C6 C7 E6?? B6 E7 G6
  11.C2 E6 F6 E5 F4 E4 E3 F3
 7.D5 C5 C6?? C7 B6 C3
  9.D3 G6
 7.C5 D5 C3 B4 E4 B3
 13.F8 G4 E8 D7 G2 H5 H8 H6 H7 H2 G3 H3 F4 E5
 13.H5 G4 H4 E5 D5 G3 C6 C7 B6 B7
 13.E5 H5 E6 E7 D7 D8 C7 C8 G8 F9
1.F6 D4 D6?? F4 C4 C3 C5 E8 E3 D3 D7 H4 E4 E5 F5 F3 E2 D5 B3 B2
 3.E5?? D5 D6 C6 E4 D7 E6 D3 E3 C7
  5.E4 D3 D6 C6 D7 H5
   7.E3 D7
  7.C7 D7 E6 B7 C8 E4
 3.C6?? F4 G4 G3 G5 E7 E6 D7 C4 F7 D3 E3 D2 D5 D6 C5 B4 B5 H3 B2 B6 A5
  7.H4 D6 D7 F5 G6 C7
  9.D5 C4 F7 B6
  13.G7 G8 D3 E3
 3.D5 E4 C4 C3 C5 G4 G5 H4 B3 E8 F8 F7 G7 E7 G8 C7 B8 B7 C8 A8
  5.C5 G4 C4 C3 G5 H4 B3 E8 F8 F7 G7 E7 G8 C7 B8 B7 C8 A8
  9.B3 E8 G5 F4 E7 G7 H4 H3
 3.E6?? F4 C6 G5 G6 H6
 5.E2 E3 F2 C3 G4 G3 F3 G5 H4 F5 G6 H5 H3 B6
 5.C5? C4 G4 G3
 9.F7 G5 B3 H7
  11.H6? E7
 9.E7 D8 F8 H5 E3 D3
  13.H6 C7
  13.G4? G5
 9.G7? B3
 11.G7 G5
 13.H5 D5 G5 G4 J4 H7
1.G5 E5 D7? F3
1.G6?? D4 D6 F4
 3.C6 D6
1.G7?? D4
1.H5?? D5
1.H6?? D5
1.H7?? D4
