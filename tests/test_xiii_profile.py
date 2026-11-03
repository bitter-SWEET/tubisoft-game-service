import unittest

from ubisoft.games.xiii import GameDescription, HostDescription


class GameDescriptionTests(unittest.TestCase):
    def test_game_script_order_and_privacy(self):
        description = GameDescription.parse("2?17?20?10?Y")
        self.assertEqual((description.game_type_index, description.map_index,
                          description.frag_limit, description.time_limit),
                         ("2", "17", "20", "10"))
        self.assertTrue(description.is_private)
        self.assertEqual(description.encode(), "2?17?20?10?Y")
        self.assertFalse(GameDescription.parse("0?0?0?0?N").is_private)

    def test_rejects_ambiguous_structure(self):
        for text in ("1?2?3?4", "1?2?3?4?Y?extra"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                GameDescription.parse(text)
        with self.assertRaises(ValueError):
            GameDescription("1", "2?3", "4", "5", "Y").encode()

    def test_registration_wrapper(self):
        text = "2?17?20?10?Y?8:7777"
        host = HostDescription.parse(text)
        self.assertEqual(host.description, GameDescription("2", "17", "20", "10", "Y"))
        self.assertEqual((host.requested_max_players, host.port), (8, 7777))
        self.assertEqual(host.encode(), text)
        for bad in ("2?17?20?10?Y?8", "2?17?20?10?Y?8:0", "2?17?20?10?Y?bad:7777"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                HostDescription.parse(bad)


if __name__ == "__main__":
    unittest.main()
