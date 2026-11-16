import unittest

from ..overlay import below, overlaps, strips
from ..data import CARDS, CARDS_BY_GUID


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
                guide.cards = [small, large]
                guide.set_context(None, {large.guid})
                root.update()
                self.assertEqual(sorted(_placeholders(guide)), [(48, 96), (144, 96)])  # the cards' in-game shapes
                self.assertLessEqual({small.name, large.name}, _guide_texts(guide))

                # the Small card's pictures arrive: only its cell changes, the Large card keeps its placeholder
                for is_locked in (False, True):
                    with open(guide.art.path(small, is_locked), "wb") as f:
                        f.write(cardart.png((48, 96, bytes(48 * 96 * 3))))
                large_tag = guide.cells[(large.guid, True)][0][0]
                untouched = guide.canvas.find_withtag(large_tag)
                guide.refresh(small.guid)
                root.update()
                self.assertEqual(_placeholders(guide), [(144, 96)])
                self.assertEqual(guide.canvas.find_withtag(large_tag), untouched)
                small_tag = guide.cells[(small.guid, False)][0][0]
                self.assertIn("image", [guide.canvas.type(i) for i in guide.canvas.find_withtag(small_tag)])
                guide.shutdown()
            finally:
                root.destroy()


def _all_widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _all_widgets(child)


def _placeholders(guide) -> list:
    """(width, height) of each "no picture" box the Item Guide draws."""
    out = []
    for item in guide.canvas.find_withtag("placeholder"):
        x0, y0, x1, y1 = guide.canvas.coords(item)
        out.append((round(x1 - x0 + 3), round(y1 - y0 + 3)))  # drawn 1 px in, 2 px short: its 3 px outline inside
    return out


def _guide_texts(guide) -> set:
    return {guide.canvas.itemcget(i, "text") for i in guide.canvas.find_all() if guide.canvas.type(i) == "text"}


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
            screen.state["locked"] = ("CHECKS ARE BLOCKED", lines, True, False)
            screen.state["status"] = ("Vanessa: day 4/13", False, False)
            screen.render()
            root.update()
            buttons = [w for w in _all_widgets(screen.notice_box) if isinstance(w, tkinter.Button)]
            labels = [w.cget("text") for w in _all_widgets(screen.notice_box) if isinstance(w, tkinter.Label)]
            self.assertEqual(sum(b.cget("text") == "Use Bypass" for b in buttons), MAX_ALERT_LINES - 1)
            self.assertIn("+ 7 more", labels)
            self.assertLessEqual(screen.notice_box.winfo_reqheight(), screen.layout["right"][3] // 2)
            self.assertGreaterEqual(-screen.font(8)[1], 10)  # the smallest font the overlay asks for
        finally:
            root.destroy()


class TestFlamingPvPWarning(unittest.TestCase):
    """Owner, 2026-11-09: before the PvP fight, the same notice "bolder and surrounded by flames"."""

    def test_flames_above_and_below_and_the_notice_fits_its_share(self) -> None:
        import queue
        import tkinter
        import types
        from ..overlay import _Screen
        root = tkinter.Tk()
        try:
            fake = types.SimpleNamespace(only_over_game=False, game_window=(0, 0, 1280, 720), art_cache_dir=None,
                                         guide_file=None, commands=queue.Queue(), on_bypass=None)
            screen = _Screen(fake, tkinter, root)
            screen.relayout((0, 0, 1280, 720))
            lines = ["SELL IT BEFORE THE PVP FIGHT OR THIS RUN IS LOST", ("Cutlass (Vanessa) - SELL OR USE BYPASS", "g")]
            screen.state["locked"] = ("CHECKS ARE BLOCKED UNTIL CUTLASS IS SOLD", lines, True, False, True)
            screen.render()
            root.update()
            widgets = list(_all_widgets(screen.notice_box))
            canvases = [w for w in widgets if isinstance(w, tkinter.Canvas)]
            self.assertEqual(len(canvases), 2)  # a band of flames above, one below
            self.assertEqual(canvases[0].winfo_y() < canvases[1].winfo_y(), True)
            self.assertLessEqual(screen.notice_box.winfo_reqheight(), screen.layout["right"][3] // 2)
            screen.state["locked"] = ("CHECKS ARE BLOCKED UNTIL CUTLASS IS SOLD", lines[1:], True, False, False)
            screen.render()
            root.update()
            self.assertFalse([w for w in _all_widgets(screen.notice_box) if isinstance(w, tkinter.Canvas)])
        finally:
            root.destroy()


class TestPopUpQueue(unittest.TestCase):
    """Owner, 2026-11-12: one pop-up at a time, queued; 3 s alone down to 1 s with 10 waiting; a rainbow one always
    6 s ("maybe 6 seconds", after seeing 3)."""

    def test_none_is_ever_dropped(self) -> None:
        """Owner, 2026-11-12: show ALL of them - a burst of 100 keeps all 100 (no cap)."""
        import types
        from ..overlay import Toast, _Screen
        screen = types.SimpleNamespace(state={"toasts": []})
        for i in range(100):
            _Screen.new_toast(screen, Toast(f"t{i}"))
        self.assertEqual(len(screen.state["toasts"]), 100)

    def test_timing(self) -> None:
        from ..overlay import toast_seconds
        self.assertEqual(toast_seconds(1, False), 3.0)
        self.assertAlmostEqual(toast_seconds(5, False), 3.0 - 2.0 * 4 / 9)
        self.assertEqual(toast_seconds(10, False), 1.0)
        self.assertEqual(toast_seconds(25, False), 1.0)
        self.assertEqual(toast_seconds(25, True), 6.0)
        self.assertEqual(toast_seconds(1, True), 6.0)

    def test_the_queue_moves_on_and_times_each_as_it_starts(self) -> None:
        """A pop-up's time starts once it's drawn, complete (owner 2026-11-12: "do not display until all UI
        elements are ready"); one whose pictures never come is drawn anyway after TOAST_WAIT."""
        import types
        from ..overlay import TOAST_WAIT, Toast, _Screen, toast_seconds
        screen = types.SimpleNamespace(state={"toasts": [Toast(f"t{i}") for i in range(4)]}, toast_shown=None,
                                       toast_waiting={Toast("t0"): 100.0}, toast_sizes={}, drawn={"toasts": "x"})
        self.assertFalse(_Screen.next_toast(screen, 100.5))  # its pictures are coming: no time runs, nothing shows
        self.assertIsNone(screen.state["toasts"][0].expires)
        self.assertTrue(_Screen.next_toast(screen, 100.0 + TOAST_WAIT))  # waited long enough: drawn anyway
        self.assertIsNone(screen.drawn["toasts"])
        screen.toast_shown = Toast("t0")  # drawn now
        self.assertTrue(_Screen.next_toast(screen, 103.0))
        first = screen.state["toasts"][0]
        self.assertEqual((first.text, first.expires), ("t0", 103.0 + toast_seconds(4, False)))
        self.assertFalse(_Screen.next_toast(screen, 103.5))  # still showing
        screen.game_in_front = False  # you clicked away: the clock stops, nothing runs out unseen
        _Screen.next_toast(screen, 104.0)
        _Screen.next_toast(screen, 110.0)
        self.assertAlmostEqual(screen.state["toasts"][0].expires, first.expires + 6.5)
        first = screen.state["toasts"][0]
        screen.game_in_front = True
        _Screen.next_toast(screen, 110.0)
        # its time is up while the next one's pictures aren't ready: still a change, so it's redrawn - the old
        # drawing stayed on screen otherwise (owner 2026-11-12: the pack's pop-up "not going away")
        self.assertTrue(_Screen.next_toast(screen, first.expires))
        self.assertEqual(screen.state["toasts"][0].text, "t1")
        self.assertIsNone(screen.state["toasts"][0].expires)
        screen.toast_shown = Toast("t1")
        _Screen.next_toast(screen, first.expires)  # drawn: it starts, timed by the 3 left
        self.assertEqual(screen.state["toasts"][0].text, "t1")
        self.assertAlmostEqual(screen.state["toasts"][0].expires, first.expires + toast_seconds(3, False))


class TestPopUpPlace(unittest.TestCase):
    """Owner, 2026-11-12: over your hero portrait and skills (never the chest or the gold), fixed height, wider when
    the pictures need it, out to the game window's edges; the strip is read from the board (recorded 1080p)."""
    STRIP = (622, 920, 1298, 920)
    WINDOW = (0, 0, 1920, 1080)

    def test_its_strip_then_wider_both_ways_then_the_window(self) -> None:
        from ..overlay import toast_place
        self.assertEqual(toast_place(self.STRIP, (1565, 0, 341, 950), self.WINDOW, 170, 300), (622, 835, 676, 170))
        self.assertEqual(toast_place(self.STRIP, (1565, 0, 341, 950), self.WINDOW, 170, 1200), (360, 835, 1200, 170))
        self.assertEqual(toast_place(self.STRIP, (1565, 0, 341, 950), self.WINDOW, 170, 5000), (0, 835, 1920, 170))

    def test_on_the_menu_the_last_strip_from_a_run(self) -> None:
        """Owner, 2026-11-12: "Keep the same EXACT positioning of the popups in run" on the main menu."""
        import types
        from ..overlay import _Screen
        screen = types.SimpleNamespace(board_ui=types.SimpleNamespace(toast_strip=(0.3, 0.85, 0.7, 0.85)))
        self.assertEqual(_Screen.toast_strip(screen), (0.3, 0.85, 0.7, 0.85))
        screen.board_ui = None  # the menu: the game dropped the board
        self.assertEqual(_Screen.toast_strip(screen), (0.3, 0.85, 0.7, 0.85))
        self.assertIsNone(_Screen.toast_strip(types.SimpleNamespace(board_ui=None)))  # no run seen yet

    def test_kept_across_restarts(self) -> None:
        import os
        import tempfile
        import types
        from ..overlay import _Screen, load_strip
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bazaar_overlay.json")
            self.assertIsNone(load_strip(path))  # nothing yet
            screen = types.SimpleNamespace(board_ui=types.SimpleNamespace(toast_strip=(0.3, 0.85, 0.7, 0.85)),
                                           overlay=types.SimpleNamespace(overlay_file=path))
            _Screen.toast_strip(screen)
            self.assertEqual(load_strip(path), (0.3, 0.85, 0.7, 0.85))  # the next session starts with it

    def test_off_the_board_the_bottom_of_the_right_column(self) -> None:
        from ..overlay import toast_place
        self.assertEqual(toast_place(None, (1565, 0, 341, 950), self.WINDOW, 170, 900), (1565, 780, 341, 170))

    def test_pictures_as_big_as_the_box_allows(self) -> None:
        """Owner, 2026-11-12: "cards could've filled more of the overlay" - one row if that's bigger, else two."""
        from ..overlay import toast_fit
        self.assertEqual(toast_fit([1.0], 640, 120, 4), (1, 120))  # one picture: the full height
        rows, tall = toast_fit([0.5, 1.0, 1.5, 1.0] * 2 + [1.0, 0.5], 640, 120, 4)  # a pack of 10
        self.assertEqual(rows, 1)
        self.assertGreater(tall, 60)  # bigger than the smallest
        self.assertEqual(toast_fit([1.0] * 30, 640, 120, 4)[0], 2)  # the resting box: two rows at most
        self.assertEqual(toast_fit([1.0] * 89, 1100, 200, 4, 6)[0], 4)  # the taller box: more rows, bigger
        self.assertEqual(toast_fit([], 640, 120, 4), (0, 0.0))

    def test_never_over_the_side_columns(self) -> None:
        """Owner, 2026-11-12: "no overlay should be able to sit on another overlay" - wider stops at the columns."""
        from ..overlay import toast_place
        self.assertEqual(toast_place(self.STRIP, (1565, 0, 341, 950), self.WINDOW, 170, 5000, (367, 1561)),
                         (367, 835, 1194, 170))

    def test_a_long_header_is_measured_as_it_wraps(self) -> None:
        """2026-11-12: a two-line header pushed the picture off the pop-up's bottom."""
        from ..overlay import text_lines
        measure = lambda text: 10 * len(text)  # noqa: E731
        self.assertEqual(text_lines(measure, "short", 100), 1)
        self.assertEqual(text_lines(measure, "aaaa bbbb cccc dddd", 100), 2)  # "aaaa bbbb" fits, "cccc" doesn't
        self.assertEqual(text_lines(measure, "x " * 40, 100), 8)

    def test_two_even_rows(self) -> None:
        from ..overlay import toast_rows
        rows, span = toast_rows([30] * 12, 4)
        self.assertEqual([len(r) for r in rows], [6, 6])
        self.assertEqual(span, 6 * 30 + 5 * 4)
        self.assertEqual(toast_rows([60], 4), ([[0]], 60))
        self.assertEqual(toast_rows([], 4), ([], 0))
        rows, _span = toast_rows([30] * 12, 4, 4)
        self.assertEqual([len(r) for r in rows], [3, 3, 3, 3])


class TestPopUpShowsAllItsPictures(unittest.TestCase):
    """Owner, 2026-11-12: "This way we can show ALL the card arts that were unlocked" - never "+ N more"."""

    def test_every_picture_once_ready_only_the_first_pop_up(self) -> None:
        import queue
        import sys
        import tempfile
        import tkinter
        import types
        from unittest import mock
        from .. import cardart
        from ..memreader import BoardUI
        from ..overlay import Toast, _Screen
        cards = [c for c in CARDS if c.shop and c.size == "Small"][:12]
        with mock.patch.dict(sys.modules, {"PIL": None}), \
                tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, \
                mock.patch.object(cardart, "Decoder", side_effect=OSError("no SDL2 in this test")):
            root = tkinter.Tk()
            try:
                fake = types.SimpleNamespace(only_over_game=False, game_window=(0, 0, 1920, 1080), art_cache_dir=tmp,
                                             guide_file=None, commands=queue.Queue(), on_bypass=None)
                screen = _Screen(fake, tkinter, root)
                screen.relayout((0, 0, 1920, 1080))
                screen.board_ui = BoardUI(False, False, False, False, False,
                                          toast_strip=(622 / 1920, 920 / 1080, 1298 / 1920, 920 / 1080))
                screen.new_toast(Toast("UNLOCKED: a pack", None, False, False, tuple(c.guid for c in cards)))
                screen.new_toast(Toast("FOUND: something"))
                screen.render()
                root.update()

                def canvas():
                    return next(w for w in _all_widgets(screen.toast_content) if isinstance(w, tkinter.Canvas))

                def kinds(kind):
                    return [i for i in canvas().find_all() if canvas().type(i) == kind]
                self.assertFalse(screen.toast_box.winfo_ismapped() and screen.toast_box.winfo_children()
                                 and any(isinstance(w, tkinter.Canvas) for w in _all_widgets(screen.toast_box)))
                # nothing shows while its pictures are made (owner 2026-11-12: "do not display until all UI elements
                # are ready")
                [(row, art)] = screen.toast_art.items()  # one size for all twelve
                for card in cards:
                    with open(art.path(card, False), "wb") as f:
                        f.write(cardart.png((row // 2, row, bytes(row // 2 * row * 3))))
                self.assertTrue(screen.new_art(cards[0].guid))  # the showing pop-up is redrawn
                self.assertFalse(screen.new_art("not-in-a-pop-up"))
                screen.render()
                root.update()
                self.assertEqual(len(kinds("image")), 12)  # all twelve, in one row as big as fits
                self.assertEqual(len({canvas().coords(i)[1] for i in kinds("image")}), 1)
                self.assertGreater(row, 60)  # bigger than the smallest
                x, y = screen.toast_box.winfo_x(), screen.toast_box.winfo_y()
                self.assertTrue(622 <= x and y + screen.toast_box.winfo_height() <= 1080)  # on its strip
                # ten Medium cards would be 60 px in the resting box: it reaches down to the window's bottom instead,
                # same top, and they're bigger (owner 2026-11-12: "cards could've filled more of the overlay")
                medium = tuple(c.guid for c in CARDS if c.shop and c.size == "Medium")[:10]
                resting_top = screen.toast_box.winfo_y()
                plan = screen.toast_frame(Toast("UNLOCKED: ten", None, False, False, medium))
                self.assertEqual(plan["top"], resting_top)
                self.assertEqual(plan["top"] + plan["height"], 1080)
                self.assertGreater(plan["size"], 60)
                # a long header makes it taller downward only: never onto the health bar (owner 2026-11-12)
                long = screen.toast_frame(Toast("A header long enough to wrap onto more lines than one " * 4))
                self.assertEqual(long["top"], screen.toast_frame(Toast("short"))["top"])
                self.assertGreater(long["height"], screen.toast_frame(Toast("short"))["height"])
                for art in screen.toast_art.values():
                    art.shutdown()
            finally:
                root.destroy()


class TestPadlocksOnReveal(unittest.TestCase):
    """Owner, 2026-10-14: a new card's padlock shows as the card turns face-up - not while it lies face-down (size and
    rarity already show), not after (the player could buy it before noticing). Clips that day: the game's reveal flag
    turns on as the card backs swirl in; the first shop card turns 0.7 s later (3 of 3), the next ~0.12 s apart;
    rewards don't flip and are up when the flag ends (0.55 s); a reroll's old cards dissolve as the deal flag turns
    on, and their padlock lingered on them."""

    def setUp(self) -> None:
        import types
        from unittest import mock
        from .. import overlay
        from ..memreader import BoardUI
        self.overlay, self.now = overlay, [100.0]
        self.flipping, self.still = BoardUI(False, False, False, False, True), BoardUI(False, False, False, False, False)
        self.dealing = BoardUI(False, False, False, False, False, dealing=True)
        self.screen = types.SimpleNamespace(board_ui=None, reveal_began=-overlay.FLIP_EARLY,
                                            reveal_ended=-overlay.FLIP_EARLY, reveal_started=False, stagger_from=0.0,
                                            pending_padlocks=None, state={"padlocks": None})
        self.screen.show_due_padlocks = lambda: overlay._Screen.show_due_padlocks(self.screen)
        # only the overlay's clock, not time.monotonic for everything else running
        patch = mock.patch.object(overlay, "time", types.SimpleNamespace(monotonic=lambda: self.now[0]))
        patch.start()
        self.addCleanup(patch.stop)

    def ui(self, ui) -> bool:
        return self.overlay._Screen.new_board_ui(self.screen, ui)

    def new_cards(self) -> None:
        self.screen.pending_padlocks, self.screen.reveal_started = ("locks", self.now[0], True), False

    def shown(self) -> bool:
        self.screen.show_due_padlocks()
        return self.screen.state["padlocks"] == "locks"

    def test_shop_cards_wait_for_the_first_card_to_turn_then_go_left_to_right(self) -> None:
        self.ui(self.still)
        self.new_cards()
        self.ui(self.flipping)  # the card backs swirl in
        self.now[0] += self.overlay.FLIP_DELAY - 0.05
        self.assertFalse(self.shown())  # still face-down
        self.now[0] += 0.1
        self.assertTrue(self.shown())
        self.assertAlmostEqual(self.screen.stagger_from, 100.0 + self.overlay.FLIP_DELAY)

    def test_items_that_dont_flip_show_when_the_reveal_ends(self) -> None:
        self.ui(self.still)
        self.new_cards()
        self.ui(self.flipping)
        self.now[0] += 0.55
        self.ui(self.still)  # a reward choice's reveal: shorter than FLIP_DELAY
        self.assertTrue(self.shown())
        self.assertEqual(self.screen.stagger_from, 0.0)  # all up at once

    def test_a_reveal_that_began_just_before_the_cards_were_noticed_still_counts(self) -> None:
        """The client reads offers every 0.3 s: a short event reveal can start, even end, before it sees them."""
        self.ui(self.flipping)
        self.now[0] += 0.3
        self.ui(self.still)
        self.now[0] += 0.1
        self.new_cards()
        self.assertTrue(self.shown())

    def test_an_old_reveal_does_not_count_and_no_reveal_waits_flip_seconds(self) -> None:
        self.ui(self.flipping)
        self.ui(self.still)
        self.now[0] += self.overlay.FLIP_EARLY + 0.5
        self.new_cards()
        self.assertFalse(self.shown())
        self.now[0] += self.overlay.FLIP_SECONDS - 0.05
        self.assertFalse(self.shown())
        self.now[0] += 0.1
        self.assertTrue(self.shown())

    def test_unreadable_flags_fall_back_to_flip_seconds(self) -> None:
        self.ui(None)
        self.new_cards()
        self.now[0] += self.overlay.FLIP_SECONDS - 0.05
        self.assertFalse(self.shown())
        self.now[0] += 0.1
        self.assertTrue(self.shown())

    def test_a_reroll_takes_the_old_padlocks_away_as_the_old_cards_dissolve(self) -> None:
        self.ui(self.still)
        self.screen.state["padlocks"] = "old locks"
        self.assertTrue(self.ui(self.dealing))
        self.assertIsNone(self.screen.state["padlocks"])


class TestPadlockCommands(unittest.TestCase):
    def test_padlocks_on_any_screen_and_none_hides_them(self) -> None:
        """Owner, 2026-10-15: every padlock is placed from memory (an event option's too), on any screen."""
        import queue
        from ..overlay import Overlay
        from ..padlocks import Padlock
        overlay = Overlay.__new__(Overlay)  # only the command queue: no windows
        overlay.commands = queue.Queue()
        for lock in (Padlock(card="enc_a", place=0), Padlock(card="itm_a", place=0)):
            overlay.show_padlocks([lock])
            self.assertEqual(overlay.commands.get_nowait()[1][0], (lock,))
        overlay.show_padlocks([])
        self.assertIsNone(overlay.commands.get_nowait()[1][0])


def _plain_merchant() -> int:
    from ..merchants import deals_any_hero
    from ..shop_guide import MERCHANTS
    return min(m for m, stocks in MERCHANTS.items() if not any(deals_any_hero(s) for s in stocks))


def _merchant(guid: str) -> int:
    from ..data import ENCOUNTER_OF
    return ENCOUNTER_OF[guid].ap_id


# merchants by their game guid (the live, non-tutorial template), as Item Guide keys
ANTIQUARIAN = _merchant("e840f7a3-0a04-455d-852c-286dc5011efc")  # The Antiquarian
MITTEL = _merchant("912c8b09-3b76-4aa1-8e21-245e0dfb5046")
CHRONOS = _merchant("b1288f12-2cf9-4473-a43e-4dd521703990")
PRINTER_3D = "723880db-8a97-4833-a9a1-80c75cde4c17"  # 3D Printer, Dooley's


PLAIN_MERCHANT = _plain_merchant()


class TestShopGuideLists(unittest.TestCase):
    """Owner, 2026-10-01: the guide opens any time, with Search, Size, Rarity and Merchant filters."""

    def test_filters_narrow_by_name_size_and_rarity(self) -> None:
        from ..shop_guide import SHOP_CARDS, guide_cards
        card = next(c for c in SHOP_CARDS if c.hero == "Vanessa")
        found = guide_cards(SHOP_CARDS, "Vanessa", None, card.name[1:5].upper(), card.size, card.tier)
        self.assertIn(card, found)
        self.assertTrue(all(c.size == card.size and c.tier == card.tier for c in found))
        self.assertTrue(all(card.name[1:5].lower() in c.name.lower() for c in found))

    def test_any_merchant_means_your_hero_and_common_cards(self) -> None:
        from ..shop_guide import ANY, SHOP_CARDS, guide_cards
        self.assertEqual({c.hero for c in guide_cards(SHOP_CARDS, "Vanessa", None, "", ANY, ANY)},
                         {"Vanessa", "Common"})
        self.assertEqual(len(guide_cards(SHOP_CARDS, None, None, "", ANY, ANY)), len(SHOP_CARDS))

    def test_a_merchant_lists_what_it_could_stock(self) -> None:
        from ..merchants import possible_stock
        from ..shop_guide import ANY, MERCHANTS, SHOP_CARDS, guide_cards
        key, stocks = next((m, s) for m, s in MERCHANTS.items() if len(s) == 1)
        expected = {c.guid for c in possible_stock(stocks[0], "Vanessa", SHOP_CARDS)}
        # Hero on Any: everything it could deal you while playing Vanessa (other heroes' cards included, if it can)
        self.assertEqual({c.guid for c in guide_cards(SHOP_CARDS, ANY, key, "", ANY, ANY, playing="Vanessa")},
                         expected)
        # Hero on Vanessa: only Vanessa's and Common cards of it
        self.assertEqual({c.guid for c in guide_cards(SHOP_CARDS, "Vanessa", key, "", ANY, ANY)},
                         {g for g in expected if CARDS_BY_GUID[g].hero in ("Vanessa", "Common")})
        # the debug merchants (the game never deals them: spawn mode Never) are in no lock, so never listed
        from ..data import ENCOUNTERS, EVENTS, MERCHANT_DATA
        never = {g for g in MERCHANT_DATA if EVENTS[g]["spawns"] == "Never"}
        self.assertTrue(never)
        self.assertFalse(never & {g for e in ENCOUNTERS if e.ap_id in MERCHANTS for g in e.guids})


class TestShopGuideHeroFilter(unittest.TestCase):
    """Owner, 2026-11-13: "I want a hero filter available either way and on merchants with 'Ignore hero' it simply
    just defaults the option to 'Any' hero instead of the usual default of the current hero"."""

    def test_default_is_your_hero_but_any_on_a_merchant_that_deals_any_hero(self) -> None:
        from ..shop_guide import ANY, default_hero
        self.assertEqual(default_hero(ANTIQUARIAN, "Jules"), ANY)  # deals every hero's cards
        # Mittel and Chronos deal other heroes' cards only to a player with a certain skill: never counted (owner,
        # 2026-11-13: "Just pretend the skills dont exist")
        self.assertEqual(default_hero(MITTEL, "Jules"), "Jules")
        self.assertEqual(default_hero(CHRONOS, "Jules"), "Jules")
        self.assertEqual(default_hero(PLAIN_MERCHANT, "Jules"), "Jules")
        self.assertEqual(default_hero(None, "Jules"), "Jules")
        self.assertEqual(default_hero(PLAIN_MERCHANT, None), ANY)  # no hero known (menu, not connected)

    def test_chronos_never_lists_another_heroes_cards(self) -> None:
        """Owner, 2026-11-13: the guide showed 3D Printer and Alpha Ray (Dooley's) at Chronos while playing Jules -
        they came from groups that need a skill. Playing Dooley they're right (Chronos deals Turbo-able items)."""
        from ..shop_guide import ANY, SHOP_CARDS, guide_cards
        jules = {c.guid: c.hero for c in guide_cards(SHOP_CARDS, ANY, CHRONOS, "", ANY, ANY, playing="Jules")}
        self.assertNotIn(PRINTER_3D, jules)
        self.assertLessEqual(set(jules.values()), {"Jules", "Common"})
        dooley = {c.guid for c in guide_cards(SHOP_CARDS, ANY, CHRONOS, "", ANY, ANY, playing="Dooley")}
        self.assertIn(PRINTER_3D, dooley)

    def test_any_hero_merchant_with_any_hero_lists_other_heroes_and_with_your_hero_only_yours(self) -> None:
        from ..shop_guide import ANY, SHOP_CARDS, guide_cards
        anyone = {c.hero for c in guide_cards(SHOP_CARDS, ANY, ANTIQUARIAN, "", ANY, ANY, playing="Jules")}
        self.assertTrue(anyone - {"Jules", "Common"}, anyone)
        mine = {c.hero for c in guide_cards(SHOP_CARDS, "Jules", ANTIQUARIAN, "", ANY, ANY, playing="Jules")}
        self.assertTrue(mine)
        self.assertLessEqual(mine, {"Jules", "Common"})

    def test_walking_into_a_merchant_sets_the_hero_filter_and_a_pick_stays(self) -> None:
        import tempfile
        import tkinter

        from ..shop_guide import ANY, ShopGuide
        root = tkinter.Tk()
        try:
            guide = ShopGuide.create(tkinter, root, tempfile.mkdtemp(), None, (0, 0, 300, 600),
                                     on_art=lambda guid: None, on_closed=lambda: None)
            hero = guide.filters["hero"]
            self.assertEqual(hero.get(), ANY)  # nothing known yet
            guide.set_context("Jules", [])
            self.assertEqual(hero.get(), "Jules")  # your hero by default
            guide.show_offer(("Shop", [], ANTIQUARIAN))
            self.assertEqual(hero.get(), ANY)
            guide.show_offer(("Shop 2", [], PLAIN_MERCHANT))
            self.assertEqual(hero.get(), "Jules")
            hero.set("Vanessa")  # your own pick stays while you're at that merchant
            guide.show_offer(("Shop 2", [], PLAIN_MERCHANT))
            guide.set_context("Jules", ["x"])  # same hero, new locks: no reset
            self.assertEqual(hero.get(), "Vanessa")
            guide.set_context("Karnok", [])  # a new hero: back to the default
            self.assertEqual(hero.get(), "Karnok")
            guide.shutdown()
        finally:
            root.destroy()


class TestShopGuideKeepsOfferedCards(unittest.TestCase):
    def test_a_bought_card_stays_in_the_list_even_past_the_cap(self) -> None:
        """Owner, 2026-10-01: a card bought from "On offer now" "should be in the list at the bottom"."""
        import tempfile
        import tkinter
        from ..shop_guide import MAX_SHOWN, ShopGuide, SHOP_CARDS
        last = sorted(SHOP_CARDS, key=lambda c: c.name.lower())[-1]  # past the cap with Merchant on Any
        root = tkinter.Tk()
        try:
            guide = ShopGuide.create(tkinter, root, tempfile.mkdtemp(), None, (0, 0, 300, 600),
                                     on_art=lambda guid: None, on_closed=lambda: None)
            guide.show_offer(("An event", [last.guid], None))
            root.update()
            texts = _guide_texts(guide)
            self.assertIn(last.name, texts)  # on screen: in the lists, whatever the cap
            self.assertFalse(any(text.startswith("On offer now") for text in texts))  # no section of its own (2026-11-13)
            guide.show_offer(("An event", [], None))  # bought: gone from the offer
            root.update()
            self.assertIn(last.name, _guide_texts(guide))
            self.assertGreater(len(SHOP_CARDS), MAX_SHOWN)
            guide.shutdown()
        finally:
            root.destroy()


class TestTrackerOverMenu(unittest.TestCase):
    """Owner, 2026-10-01: the Tracker and the menu's hero panel shouldn't sit on top of each other."""
    def test_overlap(self) -> None:
        panel = (600, 300, 700, 400)
        self.assertTrue(overlaps(panel, (500, 200, 300, 200)))  # the Tracker's corner on the panel
        self.assertFalse(overlaps(panel, (1300, 300, 400, 400)))  # dragged off to the right: touching isn't covering
        self.assertFalse(overlaps(panel, (0, 0, 200, 200)))


class TestHoverLetsClicksThrough(unittest.TestCase):
    """Owner, 2026-10-15: the concede notice sat on the settings gear - under the mouse an overlay window lets clicks
    reach the game, but for its own buttons (a held card's "Use Bypass")."""

    def test_only_the_windows_own_button_keeps_the_click(self) -> None:
        import tkinter
        from ..overlay import on_a_button
        root = tkinter.Tk()
        try:
            root.geometry("300x200+100+100")
            frame = tkinter.Frame(root)
            frame.pack(fill="x")
            button = tkinter.Button(frame, text="Use Bypass")
            button.pack(side="right")
            tkinter.Label(frame, text="Sharkclaws (Vanessa)").pack(side="left")
            root.update()
            x, y = button.winfo_rootx() + 3, button.winfo_rooty() + 3
            self.assertTrue(on_a_button(root, (x, y)))
            self.assertFalse(on_a_button(root, (root.winfo_rootx() + 3, root.winfo_rooty() + 150)))  # empty part
            button.pack_forget()
            root.update()
            self.assertFalse(on_a_button(root, (x, y)))  # a button that isn't shown can't take the click
        finally:
            root.destroy()

    def test_the_mouse_on_the_settings_gear_padded_finds_it_and_elsewhere_nothing(self) -> None:
        """Owner, 2026-10-15: "once a mouse starts to hover above the position of the settings icon (With some
        padding)" - only then does the window on it get out of the way. The gear's place was measured on the owner's
        recording (centre 1823, 75 at 1080p); at 1440p it's the same spot scaled."""
        from types import SimpleNamespace
        from ..overlay import BUTTON_PAD, _Screen
        screen = SimpleNamespace(layout={"k": 1.0, "window": (0, 0, 1920, 1080)})
        self.assertEqual(_Screen.game_button_at(screen, (1823, 75)), (1791, 43, 1855, 107))
        self.assertIsNotNone(_Screen.game_button_at(screen, (1791 - BUTTON_PAD, 75)))  # in the padding
        self.assertIsNone(_Screen.game_button_at(screen, (1700, 75)))  # the notice, away from the gear
        big = SimpleNamespace(layout={"k": 4 / 3, "window": (100, 50, 2560, 1440)})  # 1440p, moved
        self.assertIsNotNone(_Screen.game_button_at(big, (100 + 2560 - 97 * 4 / 3, 50 + 75 * 4 / 3)))
        self.assertIsNone(_Screen.game_button_at(big, (1823, 75)))

    def test_on_the_board_the_gear_comes_from_memory(self) -> None:
        """The rect read from the owner's open run (2026-10-15), as fractions of the game window: it wins over the
        measured spot, at any window size."""
        from types import SimpleNamespace
        from ..memreader import BoardUI
        from ..overlay import _Screen
        gear = (0.9284, 0.0301, 0.9727, 0.1088)
        ui = BoardUI(False, False, False, False, False, gear=gear)
        screen = SimpleNamespace(layout={"k": 4 / 3, "window": (100, 50, 2560, 1440)}, board_ui=ui)
        point = (100 + 0.95 * 2560, 50 + 0.07 * 1440)
        self.assertEqual(_Screen.game_button_at(screen, point),
                         (100 + gear[0] * 2560, 50 + gear[1] * 1440, 100 + gear[2] * 2560, 50 + gear[3] * 1440))
        moved = SimpleNamespace(layout=screen.layout, board_ui=ui._replace(gear=(0.5, 0.5, 0.55, 0.55)))
        self.assertIsNone(_Screen.game_button_at(moved, point))  # memory wins over the measured spot


class TestDropdownsStayOpen(unittest.TestCase):
    """Owner's video, 2026-11-11: the Item Guide's Merchant/Size/Rarity lists closed at once - the overlay re-claimed
    "always on top" every POLL_MS and lifted the guide over its own open list. Not while you use our windows."""

    def test_no_top_claiming_while_one_of_ours_is_in_front(self) -> None:
        import queue
        import tkinter
        import types
        from unittest import mock
        from ..overlay import _Screen
        root = tkinter.Tk()
        try:
            fake = types.SimpleNamespace(only_over_game=False, game_window=(0, 0, 1280, 720), art_cache_dir=None,
                                         guide_file=None, commands=queue.Queue(), on_bypass=None)
            screen = _Screen(fake, tkinter, root)
            screen.relayout((0, 0, 1280, 720))
            screen.panels[0].deiconify()  # a shown panel (the header)
            root.update()
            shown = [p for p in screen.panels if p.state() == "normal"]
            self.assertTrue(shown)
            with mock.patch.object(type(shown[0]), "attributes") as attributes:
                screen.ours_in_front = True
                screen.keep_on_top()
                self.assertFalse(attributes.called)
                screen.ours_in_front = False  # the game in front: the windows claim the top back, as before
                screen.keep_on_top()
                self.assertTrue(attributes.called)
        finally:
            root.destroy()


class TestPopUpShowsOnlyWhenPainted(unittest.TestCase):
    """Owner, 2026-11-13: the next pop-up's first frame or two showed the previous unlock - "only show the popup if
    it is ready and everything is rendered for display". A pop-up (or any panel) coming on screen stays fully
    see-through for REVEAL_SECONDS, whether its window was hidden in between or not."""

    def test_new_pop_up_is_see_through_until_painted(self) -> None:
        import queue
        import tempfile
        import tkinter
        import types
        from ..overlay import Toast, _Screen
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = tkinter.Tk()
            try:
                fake = types.SimpleNamespace(only_over_game=False, game_window=(0, 0, 1920, 1080), art_cache_dir=tmp,
                                             guide_file=None, commands=queue.Queue(), on_bypass=None)
                screen = _Screen(fake, tkinter, root)
                screen.relayout((0, 0, 1920, 1080))
                windows = (screen.toast_box, screen.toast_content)
                alpha = lambda w: float(w.attributes("-alpha"))  # noqa: E731
                for text in ("FOUND: first", "FOUND: second"):  # the second replaces the first while it shows
                    screen.state["toasts"] = [Toast(text)]
                    screen.drawn["toasts"] = None
                    screen.render()
                    root.update_idletasks()  # no timers: the fade rounds are run by hand below
                    self.assertTrue(all(w.state() == "normal" for w in windows))
                    self.assertEqual([alpha(w) for w in windows], [0.0, 0.0])  # on screen, not seen yet
                    screen.fade_padlocks()  # a fade tick before it's painted keeps it see-through
                    self.assertEqual([alpha(w) for w in windows], [0.0, 0.0])
                    for window in windows:
                        screen.revealing[window] = [0.0, 1]  # its time is up, one fade round to go
                    screen.fade_padlocks()
                    self.assertTrue(all(alpha(w) > 0.5 for w in windows))  # now it shows
                    self.assertFalse(set(windows) & set(screen.revealing))
            finally:
                root.destroy()


class TestUseBypassNeverUnderTheGear(unittest.TestCase):
    """Owner, 2026-11-13: "Use lock bypass can be over the 'gear icon' on the top right for settings AKA impossible to
    click since it goes see through when you hover it" - the notices start below the gear."""

    def test_notices_and_their_buttons_clear_the_gear(self) -> None:
        import queue
        import tkinter
        import types
        from ..overlay import BUTTON_PAD, SETTINGS_GEAR, _Screen
        for window in ((0, 0, 1920, 1080), (0, 0, 1280, 720), (100, 50, 2560, 1440)):
            root = tkinter.Tk()
            try:
                fake = types.SimpleNamespace(only_over_game=False, game_window=window, art_cache_dir=None,
                                             guide_file=None, commands=queue.Queue(), on_bypass=None)
                screen = _Screen(fake, tkinter, root)
                screen.relayout(window)
                screen.state["locked"] = ("CHECKS ARE BLOCKED", [("Cutlass (Vanessa) - SELL OR USE BYPASS", "g1")],
                                          True, False)
                screen.render()
                root.update_idletasks()
                x, y, w, h = window
                k = h / 1080
                gear_bottom = y + (SETTINGS_GEAR[3] + BUTTON_PAD) * k  # the gear and the pad around it
                geometry = screen.notice_box.geometry()  # WxH+X+Y, as placed
                top = int(geometry.split("+")[2])
                self.assertGreaterEqual(top, gear_bottom - 1, (window, geometry))
                buttons = [b for b in _all_widgets(screen.notice_box) if isinstance(b, tkinter.Button)]
                self.assertTrue(any(b.cget("text") == "Use Bypass" for b in buttons))
            finally:
                root.destroy()


class TestPopUpHitBoxStartsBelowThePortraitLine(unittest.TestCase):
    """Owner, 2026-11-13: "sometimes when the cards flip it will blip out the popup ... move the hitbox a little further
    from the top ... probably below the health bar" - only what reaches below the portrait's centre line fades it."""

    def test_a_card_row_brushing_its_top_doesnt_fade_it(self) -> None:
        import types
        from .. import padlocks
        from ..memreader import BoardUI
        from ..overlay import _Screen
        screen = types.SimpleNamespace(layout={"window": (0, 0, 1920, 1080)}, overlay=None,
                                       board_ui=BoardUI(False, False, False, False, False,
                                                        toast_strip=(622 / 1920, 920 / 1080, 1298 / 1920, 920 / 1080)))
        screen.toast_strip = lambda: _Screen.toast_strip(screen)
        popup = (622, 840, 1298, 1000)  # its top above the portrait line (920)
        hit = _Screen.toast_hit_box(screen, popup)
        self.assertAlmostEqual(hit[1], 920)
        row_bottom = [((700, 560, 950, 860), "c1")]  # a flipping card reaching the pop-up's top
        self.assertTrue(padlocks.covered(popup, row_bottom))  # the old box blinked it out
        self.assertFalse(padlocks.covered(hit, row_bottom))
        tooltip = [((800, 700, 1100, 950), "c2")]  # a tooltip reaching well into it still fades it
        self.assertTrue(padlocks.covered(hit, tooltip))
        screen.board_ui, screen.last_toast_strip = None, None  # off the board, no strip: the whole pop-up
        self.assertEqual(_Screen.toast_hit_box(screen, popup), popup)


class TestDialogHidesOnlyWhatIsOverTheGame(unittest.TestCase):
    """Owner 2026-11-16: "Only hide portions of the overlay if it is in front of the bazaar game window, if I have the
    tracker open and it is on a seperate monitor there s no reason to hide it" - for every game dialog (the Esc menu,
    a loading screen, the new-day screen) and every window."""

    GAME = (0, 0, 1920, 1080)  # the game window: x, y, width, height

    class Window:
        def __init__(self, x, y, w=300, h=400, state="normal"):
            self.x, self.y, self.w, self.h, self._state = x, y, w, h, state

        def winfo_exists(self): return True
        def winfo_rootx(self): return self.x
        def winfo_rooty(self): return self.y
        def winfo_width(self): return self.w
        def winfo_height(self): return self.h
        def state(self): return self._state
        def withdraw(self): self._state = "withdrawn"
        def deiconify(self): self._state = "normal"

    def screen(self, dialog: bool):
        import types
        from ..memreader import BoardUI
        from ..overlay import _Screen
        screen = types.SimpleNamespace(layout={"window": self.GAME},
                                       board_ui=BoardUI(False, False, False, dialog, False))
        screen.overlay_factor = lambda: _Screen.overlay_factor(screen)
        return lambda window: _Screen.dialog_hides(screen, window)

    def test_a_window_on_the_game_hides_one_on_another_monitor_stays(self) -> None:
        hides = self.screen(dialog=True)
        self.assertTrue(hides(self.Window(1600, 100)))  # on the game window (a corner of it is enough)
        self.assertTrue(hides(self.Window(1800, 100)))
        self.assertFalse(hides(self.Window(1920, 100)))  # the next monitor, right beside it
        self.assertFalse(hides(self.Window(-1500, 300)))  # a monitor on the left

    def test_nothing_hides_without_a_dialog(self) -> None:
        self.assertFalse(self.screen(dialog=False)(self.Window(100, 100)))

    def test_the_tracker_and_its_list_withdraw_over_the_game_and_come_back_after(self) -> None:
        from ..tracker import Tracker
        tracker = Tracker.__new__(Tracker)
        tracker.win, tracker.popup, tracker.dialog_hid = self.Window(100, 100), self.Window(500, 100), False
        tracker.set_visible(True, self.screen(dialog=True))
        self.assertEqual((tracker.win.state(), tracker.popup.state()), ("withdrawn", "withdrawn"))
        tracker.set_visible(True, self.screen(dialog=False))
        self.assertEqual((tracker.win.state(), tracker.popup.state()), ("normal", "normal"))
        elsewhere = Tracker.__new__(Tracker)
        elsewhere.win, elsewhere.popup, elsewhere.dialog_hid = self.Window(-1500, 100), None, False
        elsewhere.set_visible(True, self.screen(dialog=True))
        self.assertEqual(elsewhere.win.state(), "normal")  # on another monitor: stays

    def test_a_tracker_you_minimised_stays_minimised(self) -> None:
        from ..tracker import Tracker
        tracker = Tracker.__new__(Tracker)
        tracker.win, tracker.popup, tracker.dialog_hid = self.Window(100, 100, state="iconic"), None, False
        tracker.set_visible(True, self.screen(dialog=True))
        tracker.set_visible(True, self.screen(dialog=False))
        self.assertEqual(tracker.win.state(), "iconic")  # the dialog never touched it, so it doesn't bring it back
