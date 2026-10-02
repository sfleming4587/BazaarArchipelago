import random
import unittest

from ..data import HEROES as GAME_HEROES
from ..deathlink_lines import EARLY_DAYS, HEROES, LATE_DAYS, SHARED, deathlink_message, situation


class TestDeathLinkLines(unittest.TestCase):
    """Owner, 2026-10-02: per-hero DeathLink messages for different situations."""

    def test_every_hero_has_lines_and_no_unknown_heroes(self) -> None:
        self.assertEqual(set(HEROES), set(GAME_HEROES))
        for hero, kinds in HEROES.items():
            self.assertLessEqual(set(kinds), set(SHARED), hero)

    def test_every_line_fills_in_and_uses_no_pronouns(self) -> None:
        for lines in [*SHARED.values(), *(l for kinds in HEROES.values() for l in kinds.values())]:
            for line in lines:
                text = line.format(player="P", day=3)
                self.assertIn("P", text)
                self.assertFalse({"he", "she", "his", "her", "him"} & set(text.lower().replace(".", " ").split()), line)

    def test_situations(self) -> None:
        self.assertEqual(situation(EARLY_DAYS, False), "early")
        self.assertEqual(situation(EARLY_DAYS + 1, False), "lost")
        self.assertEqual(situation(LATE_DAYS, False), "late")
        self.assertEqual(situation(2, True), "conceded")

    def test_unknown_hero_gets_a_shared_line(self) -> None:
        text = deathlink_message("P", None, 6, False, random.Random(1))
        self.assertIn(text, [l.format(player="P", day=6) for l in SHARED["lost"] + SHARED["any"]])
