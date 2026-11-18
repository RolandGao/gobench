"""Tromp-Taylor Go rules: area scoring, positional superko, suicide allowed.

Moves use GTP coordinates ("E5", "pass"). Columns skip the letter I.
"""

from __future__ import annotations

from typing import Iterator

COLUMNS = "ABCDEFGHJKLMNOPQRST"
EMPTY, BLACK, WHITE = 0, 1, 2
COLOR_OF = {"B": BLACK, "W": WHITE}


def other(color: str) -> str:
    return "W" if color == "B" else "B"


class IllegalMove(ValueError):
    pass


class Game:
    def __init__(self, size: int = 9, komi: float = 7.5) -> None:
        self.size = size
        self.komi = komi
        self.moves: list[tuple[str, str]] = []
        self.boards: list[tuple[int, ...]] = [tuple([EMPTY] * size * size)]

    @property
    def board(self) -> tuple[int, ...]:
        return self.boards[-1]

    @property
    def to_move(self) -> str:
        return "B" if len(self.moves) % 2 == 0 else "W"

    @property
    def over(self) -> bool:
        return (
            len(self.moves) >= 2
            and self.moves[-1][1] == "pass"
            and self.moves[-2][1] == "pass"
        )

    def point(self, move: str) -> int:
        move = move.strip().upper()
        column = COLUMNS.find(move[:1])
        try:
            row = int(move[1:])
        except ValueError:
            raise IllegalMove(f"bad coordinate {move!r}") from None
        if not (0 <= column < self.size and 1 <= row <= self.size):
            raise IllegalMove(f"bad coordinate {move!r}")
        return (self.size - row) * self.size + column

    def name(self, point: int) -> str:
        return f"{COLUMNS[point % self.size]}{self.size - point // self.size}"

    def neighbors(self, point: int) -> Iterator[int]:
        row, column = divmod(point, self.size)
        if row > 0:
            yield point - self.size
        if row < self.size - 1:
            yield point + self.size
        if column > 0:
            yield point - 1
        if column < self.size - 1:
            yield point + 1

    def _group(self, board: list[int], start: int) -> tuple[set[int], bool]:
        """Return the chain containing start and whether it has a liberty."""
        color = board[start]
        chain, frontier, free = {start}, [start], False
        while frontier:
            for neighbor in self.neighbors(frontier.pop()):
                if board[neighbor] == EMPTY:
                    free = True
                elif board[neighbor] == color and neighbor not in chain:
                    chain.add(neighbor)
                    frontier.append(neighbor)
        return chain, free

    def _after(self, color: str, move: str) -> tuple[int, ...]:
        """The board after color plays move, or IllegalMove."""
        if self.over:
            raise IllegalMove("the game is over")
        if move.lower() == "pass":
            return self.board
        point = self.point(move)
        board = list(self.board)
        if board[point] != EMPTY:
            raise IllegalMove(f"{move} is occupied")
        board[point] = COLOR_OF[color]
        enemy = COLOR_OF[other(color)]
        for neighbor in self.neighbors(point):
            if board[neighbor] == enemy:
                chain, free = self._group(board, neighbor)
                if not free:
                    for stone in chain:
                        board[stone] = EMPTY
        chain, free = self._group(board, point)
        if not free:  # Suicide is legal; the chain is removed.
            for stone in chain:
                board[stone] = EMPTY
        result = tuple(board)
        if result in self.boards:
            raise IllegalMove(f"{move} repeats an earlier position (superko)")
        return result

    def is_legal(self, move: str) -> bool:
        try:
            self._after(self.to_move, move)
        except IllegalMove:
            return False
        return True

    def legal_moves(self) -> list[str]:
        if self.over:
            return []
        moves = [
            self.name(point)
            for point in range(self.size * self.size)
            if self.board[point] == EMPTY and self.is_legal(self.name(point))
        ]
        return moves + ["pass"]

    def play(self, move: str) -> None:
        move = "pass" if move.lower() == "pass" else move.upper()
        board = self._after(self.to_move, move)
        self.moves.append((self.to_move, move))
        self.boards.append(board)

    def undo(self) -> None:
        if self.moves:
            self.moves.pop()
            self.boards.pop()

    def captures(self) -> dict[str, int]:
        """Stones each color has removed from the board so far."""
        counts = {"B": 0, "W": 0}
        for index, (color, move) in enumerate(self.moves):
            before, after = self.boards[index], self.boards[index + 1]
            for point, stone in enumerate(before):
                if stone != EMPTY and after[point] == EMPTY:
                    taker = color if stone != COLOR_OF[color] else other(color)
                    counts[taker] += 1
        return counts

    def area(self) -> dict[str, int]:
        """Tromp-Taylor area: stones plus empty regions reaching one color."""
        board = self.board
        counts = {"B": 0, "W": 0}
        seen: set[int] = set()
        for point, stone in enumerate(board):
            if stone == BLACK:
                counts["B"] += 1
            elif stone == WHITE:
                counts["W"] += 1
            elif point not in seen:
                region, frontier, borders = {point}, [point], set()
                while frontier:
                    for neighbor in self.neighbors(frontier.pop()):
                        if board[neighbor] == EMPTY:
                            if neighbor not in region:
                                region.add(neighbor)
                                frontier.append(neighbor)
                        else:
                            borders.add(board[neighbor])
                seen |= region
                if borders == {BLACK}:
                    counts["B"] += len(region)
                elif borders == {WHITE}:
                    counts["W"] += len(region)
        return counts

    def score(self) -> float:
        """Black's Tromp-Taylor margin (negative means White leads)."""
        area = self.area()
        return area["B"] - area["W"] - self.komi


def result_text(margin: float) -> str:
    if margin == 0:
        return "Draw"
    return f"{'B' if margin > 0 else 'W'}+{abs(margin):g}"
