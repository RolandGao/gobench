# 9x9 opening book (Tromp-Taylor, komi 7)

A bot of your strength played a stronger opponent many thousands of times; these are the moves that won most often. While your game is in the book, play the book move even if another looks more natural.

Notation: a point is two letters, column then row, with a b c d e f g h j = 1..9, so `ee` is E5 and `gc` is G3. Answer the game in its own coordinates (E5), never in this notation.

Reading: one book per color. A line lists moves from the empty board, Black first. The number starting a line is the move number of its first move; a line starting after move 1 keeps the earlier moves of the line above it (itself completed the same way). Your moves are the book's choice and the opponent's moves are the replies it knows; when the opponent plays anything else or the line ends, the book is over. Write your game in this notation, find the line matching it move for move, and play the next move.

Symmetry: the book shows one orientation of each position. A map T changes every point the same way: optionally swap the two letters, then optionally mirror the first letter, then optionally mirror the second (mirroring exchanges a-j, b-h, c-g, d-f and keeps e). Find the T that turns your game's moves, in order, into the start of a book line. Then undo T on the book's next move: mirror the same letters, then swap if T swapped.

After the book: scoring is strict area scoring with no dead-stone removal. Before passing, capture every dead enemy stone in your area, and never pass while the opponent can still do this to you. With every point owned, Black wins with 45 or more of the 81 points and White with 38 or more.
