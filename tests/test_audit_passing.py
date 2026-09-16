import unittest

from analysis.passing_common import area_score, result_score
from analysis.audit_superko import ReplayBoard


class PassingAuditTests(unittest.TestCase):
    def test_dead_stone_changes_neutral_region_to_territory(self):
        board = ReplayBoard(3)
        board.board = tuple("BBBBW.B..")
        original = board.board
        self.assertEqual(area_score(board, 0), 4)
        self.assertEqual(area_score(board, 7, ["B2"]), 2)
        self.assertEqual(board.board, original)

    def test_empty_board_and_mixed_boundary_remain_neutral(self):
        board = ReplayBoard(3)
        self.assertEqual(area_score(board, 7), -7)
        board.board = tuple("B.......W")
        self.assertEqual(area_score(board, 7), -7)
        with self.assertRaisesRegex(ValueError, "is empty"):
            area_score(board, 7, ["B2"])

    def test_result_sign_and_draw(self):
        self.assertEqual(result_score("B+3.0"), 3)
        self.assertEqual(result_score("W+1.5"), -1.5)
        self.assertEqual(result_score("0"), 0)


if __name__ == "__main__":
    unittest.main()
