import random
import unittest

from ..data import HEROES as GAME_HEROES
from ..deathlink_lines import EARLY_WINS, HEROES, LATE_WINS, SHARED, deathlink_message, situation


class TestDeathLinkLines(unittest.TestCase):
    """Owner, 2026-10-02: per-hero DeathLink messages, by how many wins the run got."""

    def test_every_hero_has_lines_and_no_unknown_heroes(self) -> None:
        self.assertEqual(set(HEROES), set(GAME_HEROES))
        for hero, kinds in HEROES.items():
            self.assertLessEqual(set(kinds), set(SHARED), hero)

    def test_every_line_fills_in_and_uses_no_pronouns(self) -> None:
        for lines in [*SHARED.values(), *(l for kinds in HEROES.values() for l in kinds.values())]:
            for line in lines:
                text = line.format(player="P", wins="3 wins")  # a {day} would fail here: wins only (owner)
                self.assertIn("P", text)
                self.assertFalse({"he", "she", "his", "her", "him"} & set(text.lower().replace(".", " ").split()), line)

    def test_situations_go_by_wins(self) -> None:
        self.assertEqual(situation(0, False), "zero")
        self.assertEqual(situation(EARLY_WINS, False), "early")
        self.assertEqual(situation(EARLY_WINS + 1, False), "mid")
        self.assertEqual(situation(LATE_WINS, False), "late")
        self.assertEqual(situation(0, True), "conceded")

    def test_no_wins_is_always_trash(self) -> None:
        for seed in range(20):
            self.assertEqual(deathlink_message("P", "Vanessa", 0, False, random.Random(seed)),
                             "Trash is tragedy... so is P. 0 Wins.")

    def test_unknown_hero_gets_a_shared_line(self) -> None:
        text = deathlink_message("P", None, 5, False, random.Random(1))
        self.assertIn(text, [l.format(player="P", wins="5 wins") for l in SHARED["mid"] + SHARED["any"]])

    def test_one_win_is_singular(self) -> None:
        lines = [deathlink_message("P", "Mak", 1, False, random.Random(seed)) for seed in range(40)]
        self.assertTrue(any("with 1 win." in line for line in lines))
        self.assertFalse(any("1 wins" in line for line in lines))
