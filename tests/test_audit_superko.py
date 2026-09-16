import unittest

from analysis.audit_superko import ReplayBoard


class SuperkoReplayTests(unittest.TestCase):
    def ko_position(self):
        board = ReplayBoard(5)
        moves = "B3 C3 D3 B2 C4 D2 A5 C1 C2".split()
        for index, move in enumerate(moves):
            self.assertIsNone(board.play("B" if index % 2 == 0 else "W", move))
        return board

    def position(self, rows):
        board = ReplayBoard(len(rows))
        board.board = tuple("".join(reversed(rows)))
        board.history = [board.board]
        board.seen = {board.board: [0]}
        return board

    def test_immediate_ko_returns_to_position_two_plies_earlier(self):
        board = self.ko_position()
        violation = board.play("W", "C3")
        self.assertEqual(violation["kind"], "simple_ko")
        self.assertEqual(violation["repeats_positions_after_moves"], [8])
        self.assertEqual(violation["captured_stones"], 1)
        self.assertEqual(board.board, board.history[8])

    def test_ko_threat_and_answer_allow_recapture(self):
        board = self.ko_position()
        self.assertIsNone(board.play("W", "E5"))
        self.assertIsNone(board.play("B", "E4"))
        self.assertIsNone(board.play("W", "C3"))

    def test_passes_are_exempt(self):
        board = ReplayBoard(3)
        self.assertIsNone(board.play("B", "pass"))
        self.assertIsNone(board.play("W", "pass"))
        self.assertEqual(board.seen[board.board], [0, 1, 2])

    def test_single_stone_suicide_is_positional_repetition(self):
        board = self.position(["...", "W..", ".W."])
        violation = board.play("B", "A1")
        self.assertEqual(violation["kind"], "other_positional_superko")
        self.assertEqual(violation["suicide_stones"], 1)
        self.assertEqual(violation["repeats_positions_after_moves"], [0])

    def test_legal_multi_stone_suicide_then_illegal_recreation(self):
        board = self.position(["WW..", "WBW.", "W.W.", ".W.."])
        # B3 connects to B2, and the two stones have no liberties.
        self.assertIsNone(board.play("B", "B2"))
        self.assertEqual(board.board[2 * 4 + 1], ".")
        self.assertIsNone(board.play("W", "pass"))
        violation = board.play("B", "B3")
        self.assertEqual(violation["kind"], "other_positional_superko")
        self.assertEqual(violation["repeats_positions_after_moves"], [0])
        self.assertEqual(violation["captured_stones"], 0)

    def test_occupied_point_does_not_advance_history(self):
        board = ReplayBoard(3)
        board.play("B", "B2")
        with self.assertRaisesRegex(ValueError, "occupied"):
            board.play("W", "B2")
        self.assertEqual(len(board.history), 2)


if __name__ == "__main__":
    unittest.main()
