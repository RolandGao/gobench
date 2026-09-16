"""Deterministic Tromp–Taylor legality, independent of KataGo and its GTP API.

Positions are exact byte strings in top-to-bottom row order. History includes
the empty board and compares only stones, never the player to move.
"""

from __future__ import annotations

from dataclasses import dataclass

COLS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
LEGALITY_ENFORCEMENT_VERSION = 1


@dataclass(frozen=True)
class MoveEvaluation:
    position: bytes
    reason: str | None = None

    @property
    def legal(self) -> bool:
        return self.reason is None


class TrompTaylorRules:
    """Evaluate without mutation; commit only after the engine confirms a move."""

    def __init__(self, size: int):
        if not 2 <= size <= len(COLS):
            raise ValueError(f"unsupported board size: {size}")
        self.size = size
        self.position = bytes(size * size)
        self.seen_positions = {self.position}
        self._neighbors = tuple(
            tuple(
                yy * size + xx
                for xx, yy in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                if 0 <= xx < size and 0 <= yy < size
            )
            for y in range(size)
            for x in range(size)
        )

    def _group(self, board: bytearray, start: int) -> tuple[set[int], bool]:
        stones, pending, has_liberty = {start}, [start], False
        while pending:
            for point in self._neighbors[pending.pop()]:
                if board[point] == 0:
                    has_liberty = True
                elif board[point] == board[start] and point not in stones:
                    stones.add(point)
                    pending.append(point)
        return stones, has_liberty

    def evaluate(self, color: str, move: str) -> MoveEvaluation:
        """Evaluate a normalized B/W color and coordinate (or pass).

        Resignation and turn order belong to the game controller. Captures are
        resolved before suicide. A suicide is allowed only if its resulting
        position has never occurred; single-stone suicide therefore repeats.
        """
        if color not in {"B", "W"}:
            raise ValueError(f"invalid color: {color}")
        if move == "pass":
            return MoveEvaluation(self.position)
        if (
            len(move) < 2 or move[0] not in COLS[:self.size]
            or not move[1:].isdigit() or not 1 <= int(move[1:]) <= self.size
        ):
            raise ValueError(f"invalid board coordinate: {move}")
        point = (self.size - int(move[1:])) * self.size + COLS.index(move[0])
        if self.position[point]:
            return MoveEvaluation(self.position, "intersection is occupied")
        board = bytearray(self.position)
        player = 1 if color == "B" else 2
        board[point] = player
        for neighbor in self._neighbors[point]:
            if board[neighbor] == 3 - player:
                stones, has_liberty = self._group(board, neighbor)
                if not has_liberty:
                    for stone in stones:
                        board[stone] = 0
        stones, has_liberty = self._group(board, point)
        if not has_liberty:
            for stone in stones:
                board[stone] = 0
        position = bytes(board)
        if position in self.seen_positions:
            return MoveEvaluation(
                position, "positional superko: repeated board position"
            )
        return MoveEvaluation(position)

    def commit(self, evaluation: MoveEvaluation) -> None:
        if not evaluation.legal:
            raise ValueError("cannot commit an illegal move")
        self.position = evaluation.position
        self.seen_positions.add(self.position)

    def possible_moves(self, color: str) -> tuple[list[str], list[str]]:
        legal, superko = [], []
        for row in range(1, self.size + 1):
            for x in range(self.size):
                if self.position[(self.size - row) * self.size + x]:
                    continue
                move = f"{COLS[x]}{row}"
                (legal if self.evaluate(color, move).legal else superko).append(move)
        legal.append("pass")
        return legal, superko
