import unittest

from rules import Game, IllegalMove


def play(game, *moves):
    for move in moves:
        game.play(move)


class RulesTest(unittest.TestCase):
    def test_capture(self):
        game = Game()
        play(game, "E5", "E6", "D6", "A1", "F6", "A2", "E7")
        self.assertEqual(game.board[game.point("E6")], 0)
        self.assertEqual(game.captures(), {"B": 1, "W": 0})

    def test_ko_recapture_forbidden(self):
        game = Game()
        # Classic ko shape around D5/E5.
        play(game, "D4", "E4", "C5", "F5", "D6", "E6", "J9", "D5", "E5")
        self.assertEqual(game.board[game.point("D5")], 0)  # Black captured D5.
        with self.assertRaises(IllegalMove):
            game.play("D5")  # Immediate recapture repeats the position.
        play(game, "A9", "A8", "D5")  # After ko threats the recapture is fine.

    def test_multi_stone_suicide_allowed(self):
        game = Game()
        # White surrounds a two-point eye-less region at A1/B1.
        play(game, "A1", "A2", "J9", "B2", "J8", "C1")
        game.play("B1")  # Black A1+B1 have no liberties: suicide.
        self.assertEqual(game.board[game.point("A1")], 0)
        self.assertEqual(game.board[game.point("B1")], 0)

    def test_single_stone_suicide_is_illegal(self):
        game = Game()
        play(game, "J9", "A2", "J8", "B1")
        with self.assertRaises(IllegalMove):
            game.play("A1")

    def test_area_scoring_and_end(self):
        game = Game(komi=7.5)
        play(game, "pass", "pass")
        self.assertTrue(game.over)
        self.assertEqual(game.score(), -7.5)
        game = Game(komi=7.5)
        play(game, "E5", "pass", "pass")
        self.assertEqual(game.score(), 81 - 7.5)

    def test_legal_moves_excludes_occupied(self):
        game = Game()
        play(game, "E5")
        legal = game.legal_moves()
        self.assertNotIn("E5", legal)
        self.assertIn("pass", legal)
        self.assertEqual(len(legal), 81)


if __name__ == "__main__":
    unittest.main()
