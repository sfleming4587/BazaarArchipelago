import unittest

from ..overlay import below, fit_columns, fit_names, letter_columns, strips
from ..data import CARDS


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
        from ..overlay import GAP, INDENT, strips
        shop = [c for c in CARDS if c.shop]
        names = max(({c.name for c in possible_stock(m["stock"], h, shop)}
                     for m in MERCHANT_DATA.values() if not m["name"].startswith("[DEBUG]")  # never in real play
                     for h in HEROES), key=len)
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        self.addCleanup(root.destroy)
        font = tkfont.Font(root=root, family="Segoe UI", size=-10)
        bold = tkfont.Font(root=root, family="Segoe UI", size=-10, weight="bold")
        width = lambda column: max(bold.measure(line) if len(line) == 1 else font.measure(line) + INDENT
                                   for line in column) + GAP
        left, right, _ = strips(0, 0, 1920, 1080)
        _, missing = fit_columns(sorted(names), [(left[2] - 24, left[3] - 80), (right[2] - 24, right[3] - 24)],
                                 width, font.metrics("linespace"))
        self.assertGreater(len(names), 250)
        self.assertEqual(missing, 0)


class TestStrips(unittest.TestCase):
    """The overlay's strips follow the game window: any resolution, windowed or fullscreen, never on the board."""
    BOARD_1080 = (378, 1550)  # the board's left and right edge in the 1080p screenshot

    def board(self, x, y, w, h) -> tuple:
        k = min(h / 1080, w / 1920)
        centre = x + w / 2
        return centre - (960 - self.BOARD_1080[0]) * k, centre + (self.BOARD_1080[1] - 960) * k

    def check(self, x, y, w, h) -> tuple:
        left, right, _ = strips(x, y, w, h)
        board_left, board_right = self.board(x, y, w, h)
        for strip in (left, right):
            self.assertGreater(strip[2], 0)
            self.assertGreaterEqual(strip[0], x)  # inside the game window
            self.assertLessEqual(strip[0] + strip[2], x + w)
            self.assertLessEqual(strip[1] + strip[3], y + h)
        self.assertLessEqual(left[0] + left[2], board_left)  # never on the board
        self.assertGreaterEqual(right[0], board_right)
        return left, right

    def test_1080p_matches_the_screenshot(self) -> None:
        self.assertEqual(self.check(0, 0, 1920, 1080), ((14, 0, 349, 1056), (1565, 0, 341, 950)))

    def test_4k_is_1080p_doubled(self) -> None:
        self.assertEqual(self.check(0, 0, 3840, 2160), ((28, 0, 698, 2112), (3130, 0, 682, 1900)))

    def test_other_sizes_and_windows(self) -> None:
        for window in [(0, 0, 1280, 720), (0, 0, 2560, 1440), (0, 0, 3440, 1440), (0, 0, 5120, 1440),
                       (0, 0, 1920, 1200), (0, 0, 1600, 1200), (300, 200, 1280, 720), (-1920, 0, 1920, 1080),
                       (1920, 0, 2560, 1080)]:
            with self.subTest(window=window):
                self.check(*window)


class TestShopGuideWithoutPillow(unittest.TestCase):
    """Archipelago's Windows installer leaves Pillow out (the v0.6.0 logs showed the guide never opening)."""

    def test_guide_opens_with_placeholders_then_swaps_pictures_in(self) -> None:
        import sys
        import tempfile
        import tkinter
        from unittest import mock
        from .. import cardart
        from ..shop_guide import ShopGuide
        small, large = (next(c for c in CARDS if c.shop and c.size == size) for size in ("Small", "Large"))
        with mock.patch.dict(sys.modules, {"PIL": None}), tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(cardart, "Decoder", side_effect=OSError("no SDL2 in this test")):
            root = tkinter.Tk()
            try:
                guide = ShopGuide.create(tkinter, root, tmp, None, (0, 0, 300, 600), on_art=lambda guid: None,
                                         on_closed=lambda: None)
                self.assertIsNotNone(guide)
                guide.render(("Test merchant", [small], [large]))
                root.update()
                self.assertEqual(sorted((f.winfo_reqwidth(), f.winfo_reqheight()) for f in _placeholders(guide)),
                                 [(48, 96), (144, 96)])  # the cards' in-game shapes, border included
                names = {w.cget("text") for w in _all_widgets(guide.inner) if isinstance(w, tkinter.Label)}
                self.assertLessEqual({small.name, large.name}, names)

                # the Small card's pictures arrive: only its cell changes, the Large card keeps its placeholder
                for is_locked in (False, True):
                    with open(guide.art.path(small, is_locked), "wb") as f:
                        f.write(cardart.png((48, 96, bytes(48 * 96 * 3))))
                untouched = guide.cells[(large.guid, True)].winfo_children()
                guide.refresh(small.guid)
                root.update()
                self.assertEqual([(f.winfo_reqwidth(), f.winfo_reqheight()) for f in _placeholders(guide)],
                                 [(144, 96)])
                self.assertEqual(guide.cells[(large.guid, True)].winfo_children(), untouched)
                guide.shutdown()
            finally:
                root.destroy()


def _all_widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _all_widgets(child)


def _placeholders(guide) -> list:
    return [w for w in _all_widgets(guide.inner) if w.winfo_class() == "Frame" and w.cget("highlightthickness") == 3]


class TestPanelsStack(unittest.TestCase):
    """The locked-card list sits right under the alert box (review 2026-09-29: its height used to subtract a screen
    position from a height, so it was wrong whenever the game window didn't start at the top of the screen)."""

    def test_list_fills_the_strip_under_the_alerts_wherever_the_window_is(self) -> None:
        for window in [(0, 0, 1920, 1080), (300, 200, 1280, 720), (0, -1080, 1920, 1080)]:
            with self.subTest(window=window):
                left = strips(*window)[0]
                x, y, width, height = below(left, 150)
                self.assertEqual(y, left[1] + 154)  # under the alert box and the gap
                self.assertEqual(y + height, left[1] + left[3])  # down to the strip's bottom, not past or short

    def test_nothing_above_means_the_whole_strip(self) -> None:
        self.assertEqual(below((10, 20, 300, 900), 0), (10, 20, 300, 900))


class TestFitNames(unittest.TestCase):
    def test_biggest_size_that_fits_else_the_smallest(self) -> None:
        names = [f"Card{i:02}" for i in range(40)]
        measurer = lambda size: ((lambda line: size * len(line)), size + 2)  # noqa: E731
        size, placed, missing, _, _ = fit_names(names, [(400, 400)], [13, 11, 10], measurer)
        self.assertEqual((size, missing), (13, 0))  # fits at the biggest size already
        size, _, missing, _, _ = fit_names(names, [(50, 40)], [13, 10], measurer)
        self.assertEqual(size, 10)
        self.assertGreater(missing, 0)



class TestAlertBoxWithManyHeldCards(unittest.TestCase):
    """Review 2026-09-30: 8+ held locked cards pushed the alert box past its share, cutting off its buttons; and on
    a 720p game window text went down to 9 px (user rule: never under 10)."""

    def test_rows_are_capped_and_text_stays_readable(self) -> None:
        import queue
        import tkinter
        import types
        from ..overlay import MAX_ALERT_LINES, _Screen
        root = tkinter.Tk()
        try:
            fake = types.SimpleNamespace(only_over_game=False, game_window=(0, 0, 1280, 720), art_cache_dir=None,
                                         guide_file=None, commands=queue.Queue(), on_bypass=None)
            screen = _Screen(fake, tkinter, root)
            screen.relayout((0, 0, 1280, 720))
            lines = [(f"Card {i} (Vanessa) - SELL OR USE BYPASS", f"g{i}") for i in range(12)]
            screen.state["locked"] = ("CHECKS ARE BLOCKED", lines, True)
            screen.state["status"] = ("Vanessa: day 4/13", False, False)
            screen.render()
            root.update()
            buttons = [w for w in _all_widgets(screen.alert_box) if isinstance(w, tkinter.Button)]
            labels = [w.cget("text") for w in _all_widgets(screen.alert_box) if isinstance(w, tkinter.Label)]
            self.assertEqual(sum(b.cget("text") == "Use Bypass" for b in buttons), MAX_ALERT_LINES - 1)
            self.assertIn("+ 7 more", labels)
            self.assertLessEqual(screen.alert_box.winfo_reqheight(), screen.layout["left"][3] // 2)
            self.assertGreaterEqual(-screen.font(8)[1], 10)  # the smallest font the overlay asks for
        finally:
            root.destroy()


class TestCardCentres(unittest.TestCase):
    def test_row_is_centred_and_cards_follow_their_sizes(self) -> None:
        from ..overlay import SHOP_ROW_Y, SLOT_WIDTH, card_centres
        centres = card_centres(0, 0, 1920, 1080, ["Small", "Large", "Medium"])
        self.assertEqual([y for _, y in centres], [round(1080 * SHOP_ROW_Y)] * 3)
        # Small(1) Large(3) Medium(2) = 6 slots centred on 960: the Large card's centre is 0.5 slot left of it
        self.assertAlmostEqual(centres[1][0], 960 - SLOT_WIDTH / 2, delta=1)

    def test_scales_with_the_window_and_follows_it_on_screen(self) -> None:
        from ..overlay import card_centres
        small = card_centres(0, 0, 1920, 1080, ["Medium", "Medium"])
        big = card_centres(100, 50, 2560, 1440, ["Medium", "Medium"])
        for (x1, y1), (x2, y2) in zip(small, big):
            self.assertAlmostEqual(x2 - 100, x1 * 4 / 3, delta=1)
            self.assertAlmostEqual(y2 - 50, y1 * 4 / 3, delta=1)

    def test_an_unknown_size_means_no_padlocks(self) -> None:
        from ..overlay import card_centres
        self.assertIsNone(card_centres(0, 0, 1920, 1080, ["Small", None]))
        self.assertIsNone(card_centres(0, 0, 1920, 1080, []))


class TestPadlockHoverArea(unittest.TestCase):
    def test_only_the_cards_count_not_the_empty_board_around_them(self) -> None:
        from ..overlay import card_centres, card_rects
        sizes = ["Medium", "Medium", "Small"]
        rects = card_rects(0, 0, 1920, 1080, sizes)
        inside = lambda x, y: any(r[0] <= x < r[2] and r[1] <= y < r[3] for r in rects)
        for x, y in card_centres(0, 0, 1920, 1080, sizes):
            self.assertTrue(inside(x, y))
        self.assertFalse(inside(500, 430))  # the shop row's empty space, left of the cards
        self.assertFalse(inside(960, 300))  # the merchant above
        self.assertTrue(inside(960, 650))  # your own board's row
        strip_left, strip_right, _ = strips(0, 0, 1920, 1080)
        self.assertTrue(all(r[0] >= strip_left[0] + strip_left[2] and r[2] <= strip_right[0] for r in rects))
