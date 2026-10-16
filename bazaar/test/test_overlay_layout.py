import unittest

from ..overlay import below, overlaps, strips
from ..data import CARDS


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
                self.assertEqual(sorted((f.winfo_reqwidth(), f.winfo_reqheight()) for f in _placeholders(guide)),
                                 [(48, 96), (144, 96)])  # the cards' in-game shapes, border included
                names = {w.cget("text") for w in _all_widgets(guide.inner) if isinstance(w, tkinter.Label)}
                self.assertLessEqual({small.name, large.name}, names)

                # the Small card's pictures arrive: only its cell changes, the Large card keeps its placeholder
                for is_locked in (False, True):
                    with open(guide.art.path(small, is_locked), "wb") as f:
                        f.write(cardart.png((48, 96, bytes(48 * 96 * 3))))
                untouched = guide.cells[(large.guid, True)][0].winfo_children()
                guide.refresh(small.guid)
                root.update()
                self.assertEqual([(f.winfo_reqwidth(), f.winfo_reqheight()) for f in _placeholders(guide)],
                                 [(144, 96)])
                self.assertEqual(guide.cells[(large.guid, True)][0].winfo_children(), untouched)
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


class TestUnlockPopupPictures(unittest.TestCase):
    """Owner, 2026-10-02: an UNLOCKED pop-up shows the unlocked cards' pictures."""

    def test_pictures_show_once_ready_and_the_newest_popup_stays_at_the_bottom(self) -> None:
        import queue
        import sys
        import tempfile
        import tkinter
        import types
        from unittest import mock
        from .. import cardart
        from ..overlay import MAX_TOAST_PICTURES, _Screen
        cards = [c for c in CARDS if c.shop and c.size == "Small"][:MAX_TOAST_PICTURES + 2]
        with mock.patch.dict(sys.modules, {"PIL": None}), \
                tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, \
                mock.patch.object(cardart, "Decoder", side_effect=OSError("no SDL2 in this test")):
            root = tkinter.Tk()
            try:
                fake = types.SimpleNamespace(only_over_game=False, game_window=(0, 0, 1920, 1080), art_cache_dir=tmp,
                                             guide_file=None, commands=queue.Queue(), on_bypass=None)
                screen = _Screen(fake, tkinter, root)
                screen.relayout((0, 0, 1920, 1080))
                guids = tuple(c.guid for c in cards)
                screen.new_toast(("UNLOCKED: a pack", 1e12, False, False, guids))
                screen.new_toast(("FOUND: something", 1e12, False, False, ()))
                screen.render()
                root.update()

                def pictures():
                    return [w for w in _all_widgets(screen.toast_box)
                            if isinstance(w, tkinter.Label) and w.cget("image")]
                self.assertEqual(pictures(), [])  # none made yet: text only, nothing breaks
                for card in cards:
                    with open(screen.guide.art.path(card, False), "wb") as f:
                        f.write(cardart.png((48, 96, bytes(48 * 96 * 3))))
                self.assertTrue(screen.new_art(cards[0].guid))  # the waiting pop-up is redrawn
                self.assertFalse(screen.new_art("not-in-a-pop-up"))
                screen.render()
                root.update()
                self.assertEqual(len(pictures()), MAX_TOAST_PICTURES)
                labels = [w.cget("text") for w in _all_widgets(screen.toast_box) if isinstance(w, tkinter.Label)]
                self.assertIn("+ 2 more", labels)
                rows = sorted((w.winfo_y(), w.winfo_children()[0].cget("text"))
                              for w in screen.toast_box.winfo_children()[0].winfo_children())
                self.assertEqual([text for _, text in rows], ["UNLOCKED: a pack", "FOUND: something"])
                screen.guide.shutdown()
            finally:
                root.destroy()


class TestPopUpsFillTheRoom(unittest.TestCase):
    """Owner, 2026-10-02: show as many pop-ups as fit, never past the top; whole ones go, oldest first."""

    def test_too_many_keep_the_newest_whole_and_stay_under_the_notices(self) -> None:
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
            screen.state["deathlink"] = "Friend fell."
            for i in range(8):
                screen.new_toast((f"RECEIVED: a rather long item name number {i} " + "and more words " * 12,
                                  1e12, False, False, ()))
            screen.render()
            root.update()
            rows = screen.toast_box.winfo_children()[0].winfo_children()
            texts = [r.winfo_children()[0].cget("text") for r in rows]
            self.assertIn("number 7", texts[0])  # the newest is kept
            self.assertLess(len(rows), 8)  # some didn't fit and went whole
            x, y, w, h = screen.layout["right"]
            top = screen.toast_box.winfo_y()
            self.assertGreaterEqual(top, y + screen.drawn["notices_height"])  # under the notices, never over them
            self.assertEqual(screen.toast_box.winfo_height(), screen.toast_box.winfo_reqheight())  # nothing cut off
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
    def test_an_event_layout_that_isnt_measured_still_gets_its_padlocks(self) -> None:
        """Owner, 2026-10-15: event padlocks are placed from memory now, so any option count gets them."""
        import queue
        from ..overlay import Overlay
        from ..padlocks import Padlock
        overlay = Overlay.__new__(Overlay)  # only the command queue: no windows
        overlay.commands = queue.Queue()
        overlay.show_padlocks([Padlock(card="enc_a", option=0)], options="Choice-3")
        self.assertIsNotNone(overlay.commands.get_nowait()[1][0])
        overlay.show_padlocks([Padlock(card="enc_a", option=0)], options="Choice-9")
        self.assertIsNotNone(overlay.commands.get_nowait()[1][0])
        overlay.show_padlocks([Padlock(card="itm_a", place=0)])  # cards: placed from memory, on any screen
        self.assertIsNotNone(overlay.commands.get_nowait()[1][0])


class TestShopGuideLists(unittest.TestCase):
    """Owner, 2026-10-01: the guide opens any time, with Search, Size, Rarity and Merchant filters."""

    def test_filters_narrow_by_name_size_and_rarity(self) -> None:
        from ..shop_guide import ANY, SHOP_CARDS, guide_cards
        card = next(c for c in SHOP_CARDS if c.hero == "Vanessa")
        found = guide_cards(SHOP_CARDS, "Vanessa", ANY, card.name[1:5].upper(), card.size, card.tier)
        self.assertIn(card, found)
        self.assertTrue(all(c.size == card.size and c.tier == card.tier for c in found))
        self.assertTrue(all(card.name[1:5].lower() in c.name.lower() for c in found))

    def test_any_merchant_means_your_hero_and_common_cards(self) -> None:
        from ..shop_guide import ANY, SHOP_CARDS, guide_cards
        self.assertEqual({c.hero for c in guide_cards(SHOP_CARDS, "Vanessa", ANY, "", ANY, ANY)},
                         {"Vanessa", "Common"})
        self.assertEqual(len(guide_cards(SHOP_CARDS, None, ANY, "", ANY, ANY)), len(SHOP_CARDS))

    def test_a_merchant_lists_what_it_could_stock(self) -> None:
        from ..merchants import possible_stock
        from ..shop_guide import ANY, MERCHANTS, SHOP_CARDS, guide_cards
        name, entries = next((n, e) for n, e in MERCHANTS.items() if len(e) == 1)
        expected = {c.guid for c in possible_stock(entries[0]["stock"], "Vanessa", SHOP_CARDS)}
        self.assertEqual({c.guid for c in guide_cards(SHOP_CARDS, "Vanessa", name, "", ANY, ANY)}, expected)
        self.assertFalse(any(n.startswith("[DEBUG]") for n in MERCHANTS))


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
            guide.show_offer(("An event", [], None))  # bought: gone from the offer
            root.update()
            names = {w.cget("text") for w in _all_widgets(guide.inner) if isinstance(w, tkinter.Label)}
            self.assertIn(last.name, names)
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


class TestEventCentres(unittest.TestCase):
    """Event padlocks sit on the options' centres, measured on the owner's screenshots 2026-10-02."""

    def test_hourly_three_match_the_screenshot(self) -> None:
        from ..overlay import event_centres
        # Event3.jpg (1920x1080): frames centred at about (715, 303), (960, 364), (1205, 303)
        for (x, y), (ex, ey) in zip(event_centres(0, 0, 1920, 1080, "Choice-3"), ((715, 303), (960, 364), (1205, 303))):
            self.assertAlmostEqual(x, ex, delta=3)
            self.assertAlmostEqual(y, ey, delta=3)

    def test_a_line_is_centred_whatever_its_count(self) -> None:
        """Owner, 2026-10-02: without the portal's bubble its two events move to the centre."""
        from ..overlay import event_centres, event_row
        self.assertEqual(event_centres(0, 0, 1920, 1080, "Line-3"), [(678, 420), (960, 420), (1242, 420)])
        self.assertEqual(event_centres(0, 0, 1920, 1080, "Line-2"), [(819, 420), (1101, 420)])
        self.assertEqual(event_centres(0, 0, 1920, 1080, "Line-1"), [(960, 420)])
        self.assertIsNone(event_row("Choice-2"))  # an hourly count never measured
        self.assertIsNone(event_row("Line-0"))

    def test_scales_with_the_window(self) -> None:
        from ..overlay import event_centres
        small = event_centres(0, 0, 1920, 1080, "Choice-4")
        big = event_centres(100, 50, 2560, 1440, "Choice-4")
        for (x1, y1), (x2, y2) in zip(small, big):
            self.assertAlmostEqual(x2 - 100, x1 * 4 / 3, delta=1)
            self.assertAlmostEqual(y2 - 50, y1 * 4 / 3, delta=1)



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
