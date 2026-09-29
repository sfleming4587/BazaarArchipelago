import unittest

from ..screens import clamp, monitor_for
from ..tracker import square_status
from .test_client import LOCKED, ClientTestBase
from ..data import CARDS
from ..items import BASE_ID
from ..locations import day_location, location_name_to_id


class TestNeverOffScreen(unittest.TestCase):
    """User 2026-09-29: an overlay window must NEVER go off screen - every position goes through clamp()."""
    SCREEN = (0, 0, 2560, 1440)

    def test_inside_stays_put(self) -> None:
        self.assertEqual(clamp((100, 100, 300, 200), self.SCREEN), (100, 100, 300, 200))

    def test_every_side_is_pulled_back(self) -> None:
        for rect in [(-500, 10, 300, 200), (2500, 10, 300, 200), (10, -80, 300, 200), (10, 1400, 300, 200),
                     (-9999, -9999, 300, 200), (9999, 9999, 300, 200)]:
            with self.subTest(rect=rect):
                x, y, w, h = clamp(rect, self.SCREEN)
                self.assertTrue(0 <= x and x + w <= 2560 and 0 <= y and y + h <= 1440)

    def test_too_big_is_shrunk(self) -> None:
        self.assertEqual(clamp((0, 0, 4000, 3000), self.SCREEN), (0, 0, 2560, 1440))

    def test_second_monitor_left_of_the_main_one(self) -> None:
        self.assertEqual(clamp((-2000, 50, 300, 200), (-1920, 0, 1920, 1080)), (-1920, 50, 300, 200))

    def test_game_on_no_monitor_is_not_trusted(self) -> None:
        self.assertIsNone(monitor_for((5000, 5000, 1920, 1080), [self.SCREEN]))
        self.assertEqual(monitor_for((2000, 0, 1920, 1080), [self.SCREEN, (2560, 0, 1920, 1080)]),
                         (2560, 0, 1920, 1080))


class TestSquareColour(unittest.TestCase):
    def test_best_check_left_wins(self) -> None:  # user: "Best check left"
        self.assertEqual(square_status(["red", "yellow", "done"]), "yellow")
        self.assertEqual(square_status(["red", "green"]), "green")
        self.assertEqual(square_status(["done", "done"]), "done")
        self.assertIsNone(square_status([]))


class TestTrackerData(ClientTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.ctx.slot_data["logic"] = {"day_10": 15, "diamond": 10, "legendary": 20}
        vanessa = [BASE_ID + c.ap_id for c in CARDS if c.hero == "Vanessa" and c.shop][:20]
        self.ctx.slot_data["lock_items"] = vanessa

    def status(self, hero: str, kind: str, day: int) -> str:
        return next(c[4] for c in self.ctx.tracker_data()[hero]["checks"] if c[0] == kind and c[1] == day)

    def test_colours(self) -> None:
        self.ctx.checked_locations = {location_name_to_id[day_location("Vanessa", 1)]}
        self.assertEqual(self.status("Vanessa", "day", 1), "done")
        self.assertEqual(self.status("Vanessa", "day", 2), "green")  # days 1-7 need no cards
        self.assertEqual(self.status("Vanessa", "day", 9), "yellow")  # needs cards Vanessa doesn't have yet
        self.assertEqual(self.status("Dooley", "day", 1), "red")  # Dooley is locked in this test seed

    def test_heroes_outside_the_seed(self) -> None:
        data = self.ctx.tracker_data()
        self.assertEqual(len(data), 8)
        self.assertFalse(data["Karnok"]["in_seed"])
        self.assertTrue(data["Vanessa"]["in_seed"])
