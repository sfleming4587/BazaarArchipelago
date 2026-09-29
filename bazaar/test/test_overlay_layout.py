import unittest

from ..overlay import fit_columns, letter_columns


class TestLetterColumns(unittest.TestCase):
    def test_small_letters_stack(self) -> None:
        self.assertEqual(letter_columns(["Bass", "amp", "Cymbal"], rows=7), [["A", "amp", "B", "Bass", "C", "Cymbal"]])

    def test_letter_moves_to_next_column_when_full(self) -> None:
        names = ["Anchor", "Apple", "Axe", "Bolas", "Brick", "Bugle"]
        self.assertEqual(letter_columns(names, rows=5),
                         [["A", "Anchor", "Apple", "Axe"], ["B", "Bolas", "Brick", "Bugle"]])

    def test_many_letters_share_a_column_up_to_the_height(self) -> None:
        names = ["Amp", "Bass", "Cymbal", "Drum", "Echo"]
        self.assertEqual(letter_columns(names, rows=6), [["A", "Amp", "B", "Bass", "C", "Cymbal"],
                                                         ["D", "Drum", "E", "Echo"]])

    def test_letter_longer_than_a_column_carries_on_under_its_heading(self) -> None:
        names = [f"S{i}" for i in range(9)] + ["Tail"]
        columns = letter_columns(names, rows=5)
        self.assertTrue(all(len(c) <= 5 for c in columns))
        self.assertEqual([c[0] for c in columns], ["S", "S", "S"])
        self.assertEqual(columns[2], ["S", "S8", "T", "Tail"])  # T shares the leftover room
        self.assertEqual(sum(len(c) - c.count("S") - c.count("T") for c in columns), 10)


class TestFitColumns(unittest.TestCase):
    width = staticmethod(lambda column: 10 * max(len(line) for line in column))  # 10 px per character

    def test_fills_the_first_area_then_the_next(self) -> None:
        names = ["Amp", "Bass", "Cymbal", "Drum"]
        placed, missing = fit_columns(names, [(70, 40), (70, 40)], self.width, line_height=10)
        self.assertEqual(missing, 0)
        self.assertEqual(placed, [[["A", "Amp", "B", "Bass"]], [["C", "Cymbal", "D", "Drum"]]])

    def test_never_wider_or_taller_than_an_area(self) -> None:
        names = [f"Card{i:03}" for i in range(200)]
        placed, missing = fit_columns(names, [(300, 100), (200, 50)], self.width, line_height=10)
        for (w, h), columns in zip([(300, 100), (200, 50)], placed):
            self.assertLessEqual(sum(self.width(c) for c in columns), w)
            self.assertTrue(all(len(c) * 10 <= h for c in columns))
        shown = sum(1 for area in placed for c in area for line in c if len(line) > 1)
        self.assertEqual(shown + missing, 200)
        self.assertGreater(missing, 0)

    def test_every_shop_fits_the_side_strips_at_1080p(self) -> None:
        """The biggest shop (269 locked cards) fits beside the board on a 1920x1080 screen at 10 px text (the
        smallest the overlay uses), measured with the real font, with the Shop Guide closed and no alert box."""
        import tkinter as tk
        import tkinter.font as tkfont
        from ..client import HEROES, MERCHANT_DATA
        from ..data import CARDS
        from ..merchants import possible_stock
        from ..overlay import GAP, INDENT, LEFT_AREA, RIGHT_AREA, area_pixels
        shop = [c for c in CARDS if c.shop]
        names = max(({c.name for c in possible_stock(m["stock"], h, shop)}
                     for m in MERCHANT_DATA.values() for h in HEROES), key=len)
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        self.addCleanup(root.destroy)
        font = tkfont.Font(root=root, family="Segoe UI", size=-10)
        bold = tkfont.Font(root=root, family="Segoe UI", size=-10, weight="bold")
        width = lambda column: max(bold.measure(line) if len(line) == 1 else font.measure(line) + INDENT
                                   for line in column) + GAP
        right, left = area_pixels(RIGHT_AREA, 1920, 1080), area_pixels(LEFT_AREA, 1920, 1080)
        _, missing = fit_columns(sorted(names), [(left[2] - 24, left[3] - 80), (right[2] - 24, right[3] - 24)],
                                 width, font.metrics("linespace"))
        self.assertGreater(len(names), 250)
        self.assertEqual(missing, 0)


class TestShopGuideWithoutPillow(unittest.TestCase):
    def test_guide_turns_itself_off(self) -> None:
        """Archipelago's Windows installer leaves Pillow out: no pictures means no Shop Guide, alerts still work."""
        import sys
        import tempfile
        import time
        from unittest import mock
        from ..overlay import Overlay
        with mock.patch.dict(sys.modules, {"PIL": None}), tempfile.TemporaryDirectory() as tmp:
            overlay = Overlay(art_cache_dir=tmp)
            for _ in range(40):
                if overlay.shop_guide_unavailable:
                    break
                time.sleep(0.05)
            self.assertTrue(overlay.available)
            self.assertTrue(overlay.shop_guide_unavailable)
            overlay.close()
            overlay.thread.join(timeout=5)
