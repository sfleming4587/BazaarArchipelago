import unittest
from unittest import mock

from .. import padlocks
from ..memreader import BoardUI
from ..padlocks import HIDDEN, SEE_THROUGH, SOLID, Padlock

WINDOW = (0, 0, 1920, 1080)
SIZE = 56


def frac(rect):
    """Screen pixels at 1080p (as logged 2026-10-14) to fractions of the window, as memreader gives them."""
    return rect[0] / 1920, rect[1] / 1080, rect[2] / 1920, rect[3] / 1080


# Real rects read from memory 2026-10-14 (and matched to the owner's screenshots):
PASTA = frac((1081, 559, 1177, 779))  # a Small card on your board
PREP = frac((857, 559, 1063, 779))  # the Medium card left of it
PREP_HOVERED = frac((808, 506, 1112, 831))  # Prep Station enlarged while hovered
PASTA_INSPECTED = frac((535, 163, 856, 897))  # Pasta in the right-click view
PREP_TOOLTIP = (frac((661, 170, 1128, 251)), frac((609, 249, 734, 362)))  # its title bar, its cooldown clock


def ui(**kw):
    base = dict(hovering=False, dragging=False, inventory=False, dialog=False, revealing=False)
    base.update(kw)
    return BoardUI(**base)


class TestPadlockSitsOnItsCard(unittest.TestCase):
    """Owner, 2026-10-14: "padlocks to appear as if they are ART on the card"; "positioning ... NEVER GUESSED"."""

    def test_it_sits_on_the_centre_of_its_card_as_memory_places_it(self) -> None:
        square = padlocks.spot(Padlock(card="pasta"), ui(cards={"pasta": PASTA}), WINDOW, SIZE)
        self.assertEqual(tuple(round(v) for v in square), (1101, 641, 1157, 697))

    def test_it_rides_on_its_card_when_the_card_moves(self) -> None:
        dragged = frac((1007, 361, 1104, 583))  # Pasta mid-drag, as logged
        square = padlocks.spot(Padlock(card="pasta"), ui(cards={"pasta": dragged}), WINDOW, SIZE)
        self.assertEqual(tuple(round(v) for v in square), (1028, 444, 1084, 500))

    def test_a_card_off_the_game_window_gets_no_padlock_rather_than_one_clamped_to_the_edge(self) -> None:
        """Owner, 2026-10-15: a padlock shows only where its card's art is."""
        sliding_in = frac((1900, 559, 2100, 779))  # centre past the right edge
        self.assertIsNone(padlocks.spot(Padlock(card="c"), ui(cards={"c": sliding_in}), WINDOW, SIZE))
        half_out = frac((-100, 559, 40, 779))  # centre 30 px in: the padlock wouldn't fit
        self.assertIsNone(padlocks.spot(Padlock(card="c"), ui(cards={"c": half_out}), WINDOW, SIZE))

    def test_a_card_memory_cant_place_gets_no_padlock_rather_than_a_guessed_one(self) -> None:
        self.assertIsNone(padlocks.spot(Padlock(card="pasta"), ui(cards={}), WINDOW, SIZE))
        self.assertIsNone(padlocks.spot(Padlock(card="pasta"), None, WINDOW, SIZE))

    def test_an_event_option_shows_only_while_memory_has_it_on_screen(self) -> None:
        """Owner, 2026-10-15: "padlocks are to only be seen if the art for what it is supposed to be on top of is
        there" - an event's padlock stayed over the stash flipped over it. Memory places the option (a point, the
        centre of its art: recorded at 715,305 where the measured spot was 715,303) only while it faces you."""
        lock = Padlock(card="enc_a")
        seen = ui(cards={"enc_a": frac((715, 305, 715, 305))})
        self.assertEqual(padlocks.spot(lock, seen, WINDOW, SIZE), (687, 277, 743, 333))
        for gone in (ui(), None):  # flipped away under the stash, or the board's state unreadable
            self.assertIsNone(padlocks.spot(lock, gone, WINDOW, SIZE))

    def test_a_right_clicked_event_keeps_its_padlock_on_the_enlarged_art(self) -> None:
        """Owner, 2026-10-15: right-clicking an event hid its padlock; it is art on the card, so it rides along.
        Recorded: the enlarged Jungle Ruins' centre at 0.363, 0.41 of the window (matched to the owner's video)."""
        lock = Padlock(card="enc_a")
        board = ui(hovering=True, inspecting=True, hovered_card="enc_a", cards={"enc_a": (0.363, 0.41, 0.363, 0.41)})
        square = padlocks.spot(lock, board, WINDOW, SIZE)
        self.assertEqual(tuple(round(v) for v in square), (669, 415, 725, 471))
        self.assertEqual(padlocks.alpha(lock, square, board, [], 6, 0.0, 100.0), SOLID)
        other = Padlock(card="enc_b")  # another option, under the big view
        board = board._replace(cards={**board.cards, "enc_b": frac((960, 364, 960, 364))})
        self.assertEqual(padlocks.alpha(other, padlocks.spot(other, board, WINDOW, SIZE), board, [], 6, 0.0, 100.0),
                         HIDDEN)

    def test_a_right_clicked_monsters_items_carry_their_padlocks_and_your_board_hides(self) -> None:
        """Owner, 2026-10-15: padlocks on a monster's board in its right-click view. Recorded: Soda Swiller's
        Medium item at 706-958 x 731-973 px, on its art in the owner's video."""
        item = frac((706, 731, 958, 973))
        board = ui(hovering=True, inspecting=True, hovered_card="com_soda", monster_items=(("monster:2", "guid"),),
                   cards={"monster:2": item, "pasta": PASTA})
        lock = Padlock(card="monster:2")
        square = padlocks.spot(lock, board, WINDOW, SIZE)
        self.assertEqual(tuple(round(v) for v in square), (804, 824, 860, 880))
        self.assertEqual(padlocks.alpha(lock, square, board, [], 6, 0.0, 100.0), SOLID)
        mine = Padlock(card="pasta")
        self.assertEqual(padlocks.alpha(mine, padlocks.spot(mine, board, WINDOW, SIZE), board, [], 6, 0.0, 100.0),
                         HIDDEN)
        sliding_in = board._replace(cards={"monster:2": frac((706, 1060, 958, 1300))})  # rises from below the window
        self.assertIsNone(padlocks.spot(lock, sliding_in, WINDOW, SIZE))


class TestPadlockShows(unittest.TestCase):
    """Hidden while its card can't be bought or clicked, see-through while the game shows something over it, solid
    otherwise (owner, 2026-10-14)."""

    def alpha(self, board, card="pasta", place=None, turning_since=0.0, now=100.0):
        lock = Padlock(card=card, place=place)
        square = padlocks.spot(lock, board, WINDOW, SIZE)
        return padlocks.alpha(lock, square, board, padlocks.coverings(board, WINDOW), 6, turning_since, now)

    def test_solid_when_nothing_covers_it(self) -> None:
        self.assertEqual(self.alpha(ui(cards={"pasta": PASTA, "prep": PREP})), SOLID)

    def test_hidden_under_our_own_tracker_or_shop_guide(self) -> None:
        """Owner's screenshot 2026-11-11: a padlock sat on the open Tracker. Its card can't be seen under our own
        window, so it hides there (and shows again once the window moves off it)."""
        board = ui(cards={"pasta": PASTA})
        lock = Padlock(card="pasta")
        square = padlocks.spot(lock, board, WINDOW, SIZE)
        over = (1000, 500, 1300, 900)  # the tracker, over Pasta's padlock
        aside = (0, 0, 300, 200)
        self.assertEqual(padlocks.alpha(lock, square, board, [], 6, 0.0, 100.0, [over]), HIDDEN)
        self.assertEqual(padlocks.alpha(lock, square, board, [], 6, 0.0, 100.0, [aside]), SOLID)

    def test_hidden_under_a_dialog(self) -> None:
        self.assertEqual(self.alpha(ui(cards={"pasta": PASTA}, dialog=True)), HIDDEN)

    def test_a_stash_flipping_never_hides_a_card_you_can_still_see(self) -> None:
        """Owner, 2026-10-15: "it is not okay to keep 'Hiding padlocks' if the card is still visible". Your board
        stays put while the stash flips; a card turned away has no position from memory, so no padlock."""
        board = ui(stash_moving=True, cards={"pasta": PASTA})  # "prep" is in the shop, turned away
        self.assertEqual(self.alpha(board, "pasta"), SOLID)
        self.assertIsNone(padlocks.spot(Padlock(card="prep"), board, WINDOW, SIZE))

    def test_a_medium_cards_enlargement_reaches_its_neighbour_but_never_its_own_padlock(self) -> None:
        """Owner, 2026-10-14: hovering blocks nearby cards "only if it is medium size or greater"."""
        board = ui(hovering=True, hovered_card="prep", cards={"pasta": PASTA, "prep": PREP_HOVERED})
        self.assertEqual(self.alpha(board, "pasta"), SEE_THROUGH)
        self.assertEqual(self.alpha(board, "prep"), SOLID)

    def test_a_tooltip_piece_over_it_makes_it_see_through_and_only_that_one(self) -> None:
        under_clock = frac((640, 280, 700, 340))
        board = ui(hovering=True, hovered_card="prep", tooltips=PREP_TOOLTIP,
                   cards={"under": under_clock, "pasta": PASTA, "prep": PREP})
        self.assertEqual(self.alpha(board, "under"), SEE_THROUGH)
        self.assertEqual(self.alpha(board, "pasta"), SOLID)

    def test_the_hovered_cards_own_tooltip_never_fades_its_padlock(self) -> None:
        """Owner's clip, 2026-10-15: an event option's tooltip slides in over its own padlock and flashed it."""
        under_title = frac((900, 150, 1000, 260))  # under Prep's tooltip title bar
        board = ui(hovering=True, hovered_card="prep", tooltips=PREP_TOOLTIP, cards={"prep": under_title})
        self.assertEqual(self.alpha(board, "prep"), SOLID)

    def test_an_ap_marker_fades_under_its_own_cards_tooltip_but_not_its_own_picture(self) -> None:
        """Owner 2026-11-13: "Almost impossible to get hit by its own tooltip but might as well code it in there".
        The marker sits on its card's top-right corner, so its own (lifted) picture always reaches it."""
        marker = Padlock(card="prep", marker="green")
        under_title = frac((900, 150, 1000, 260))
        board = ui(hovering=True, hovered_card="prep", tooltips=PREP_TOOLTIP, cards={"prep": under_title})
        square = padlocks.spot(marker, board, WINDOW, SIZE)
        covers = padlocks.coverings(board, WINDOW)
        self.assertEqual(padlocks.alpha(marker, square, board, covers, 6, 0.0, 100.0), SEE_THROUGH)
        alone = ui(hovering=True, hovered_card="prep", cards={"prep": PREP_HOVERED})  # its picture, no tooltip
        square = padlocks.spot(marker, alone, WINDOW, SIZE)
        self.assertEqual(padlocks.alpha(marker, square, alone, padlocks.coverings(alone, WINDOW), 6, 0.0, 100.0),
                         SOLID)

    def test_the_padding_reaches_a_little_past_the_padlock_and_no_further(self) -> None:
        tooltip = (frac((1162, 600, 1300, 700)),)  # 5 px right of Pasta's padlock (1101-1157)
        board = ui(hovering=True, tooltips=tooltip, cards={"pasta": PASTA})
        self.assertEqual(self.alpha(board), SEE_THROUGH)
        board = ui(hovering=True, tooltips=(frac((1170, 600, 1300, 700)),), cards={"pasta": PASTA})
        self.assertEqual(self.alpha(board), SOLID)

    def test_a_dragged_card_covers_the_padlock_under_it_never_its_own(self) -> None:
        board = ui(dragging=True, dragged_card="prep", cards={"pasta": PASTA, "prep": frac((1000, 540, 1200, 760))})
        self.assertEqual(self.alpha(board, "pasta"), SEE_THROUGH)
        self.assertEqual(self.alpha(board, "prep"), SOLID)

    def test_a_right_clicked_card_keeps_its_padlock_and_everything_else_hides(self) -> None:
        board = ui(hovering=True, inspecting=True, hovered_card="pasta", cards={"pasta": PASTA_INSPECTED, "prep": PREP})
        self.assertEqual(self.alpha(board, "pasta"), SOLID)
        self.assertEqual(self.alpha(board, "prep"), HIDDEN)

    def test_new_cards_turn_left_to_right_and_their_padlocks_follow(self) -> None:
        board = ui(cards={"pasta": PASTA})
        third = dict(place=2, turning_since=100.0)
        self.assertEqual(self.alpha(board, now=100.0 + padlocks.FLIP_STAGGER, **third), HIDDEN)
        self.assertEqual(self.alpha(board, now=100.0 + 2 * padlocks.FLIP_STAGGER, **third), SOLID)


class TestRevealWait(unittest.TestCase):
    """overlay._Screen.show_due_padlocks: new cards' padlocks wait for their flip - never for one that's over."""

    def screen(self, began: float, ended: float, since: float):
        from types import SimpleNamespace
        return SimpleNamespace(board_ui=SimpleNamespace(revealing=False), reveal_began=began, reveal_ended=ended,
                               reveal_started=False, state={"padlocks": None}, stagger_from=0.0,
                               pending_padlocks=(("lock",), since, True))

    def test_a_flip_already_over_when_the_padlocks_arrive_shows_them_at_once(self) -> None:
        """2026-11-12 (owner's other PC: padlocks "didn't load instantly"): learned 0.9 s into a 0.8 s flip, they
        waited another full second with the cards face-up."""
        from ..overlay import _Screen
        with mock.patch("time.monotonic", return_value=100.0):
            self.assertTrue(_Screen.show_due_padlocks(self.screen(began=99.1, ended=99.9, since=100.0)))

    def test_the_same_padlocks_again_keep_waiting_for_their_flip(self) -> None:
        """Live test 2026-11-12: the shop's log line refreshed the padlocks as "not new" and they showed on face-down
        cards ~0.9 s before the flip."""
        from ..overlay import _Screen
        screen = self.screen(began=0.0, ended=0.0, since=100.0)
        screen.pending_padlocks = (("lock",), 100.0, True)
        screen.show_due_padlocks = lambda: _Screen.show_due_padlocks(screen)
        with mock.patch("time.monotonic", return_value=100.1):
            self.assertFalse(_Screen.new_padlocks(screen, (("lock",), 100.1, False)))
        self.assertEqual(screen.pending_padlocks, (("lock",), 100.0, True))  # still waiting
        with mock.patch("time.monotonic", return_value=100.1):
            _Screen.new_padlocks(screen, (("other",), 100.1, True))  # different cards replace it
        self.assertEqual(screen.pending_padlocks[0], ("other",))

    def test_with_no_flip_at_all_they_still_wait(self) -> None:
        from ..overlay import FLIP_SECONDS, _Screen
        with mock.patch("time.monotonic", return_value=100.0):
            self.assertFalse(_Screen.show_due_padlocks(self.screen(began=90.0, ended=91.0, since=100.0)))
        with mock.patch("time.monotonic", return_value=100.0 + FLIP_SECONDS):
            self.assertTrue(_Screen.show_due_padlocks(self.screen(began=90.0, ended=91.0, since=100.0)))

    def test_why_each_padlock_shows_as_it_does(self) -> None:
        """The reason the log file gets (F4) is the same rule as the alpha (one source)."""
        board = ui(hovering=True, inspecting=True, hovered_card="pasta", cards={"pasta": PASTA_INSPECTED, "prep": PREP})
        lock = Padlock(card="prep")
        self.assertEqual(padlocks.look(lock, padlocks.spot(lock, board, WINDOW, SIZE), board, [], 6, 0.0, 100.0),
                         (HIDDEN, "right-click view"))
        self.assertEqual(padlocks.look(lock, None, board, [], 6, 0.0, 100.0), (HIDDEN, "card not placed"))


class TestOtherOverlayWindows(unittest.TestCase):
    def test_a_window_fades_only_when_something_reaches_it(self) -> None:
        """Owner, 2026-10-14: "ANY UI overlay element to only become opaque when something is being blocked by it"."""
        covers = padlocks.coverings(ui(hovering=True, tooltips=PREP_TOOLTIP), WINDOW)
        self.assertFalse(padlocks.covered((20, 300, 360, 600), covers))  # the left strip's box
        self.assertTrue(padlocks.covered((1000, 200, 1500, 300), covers))  # under the title bar


class TestKeywordTrayLeavesTheGuide(unittest.TestCase):
    """Owner, 2026-11-13: the keyword tray (bottom left, under the Item Guide) faded the whole guide on every hover -
    "Guide stays solid ONLY FROM THIS TRAY, every other thing that made it go transparent will still do so"."""

    def test_tray_left_out_only_when_asked(self) -> None:
        from ..padlocks import coverings
        tray, tip = (0.01, 0.77, 0.15, 0.97), (0.55, 0.27, 0.73, 0.49)
        ui = BoardUI(True, False, False, False, False, tooltips=(tip, tray), hovered_card="c1", keyword_tray=tray)
        window = (0, 0, 1000, 1000)
        everything = coverings(ui, window)
        self.assertEqual(len(everything), 2)  # padlocks and the other windows: the tray still counts
        for_guide = coverings(ui, window, keyword_tray=False)
        self.assertEqual([c.rect for c in for_guide], [c.rect for c in everything if c.rect[0] > 500])  # only the tooltip
        no_tray = ui._replace(keyword_tray=None)  # right-click view: the big keyword box is no tray - it counts
        self.assertEqual(len(coverings(no_tray, window, keyword_tray=False)), 2)


class TestCheckMarkerSpot(unittest.TestCase):
    """Owner, 2026-11-13: the AP marker sits on the card's top-right corner ("Top-right corner"); a padlock stays at
    the centre."""

    def test_top_right_corner(self) -> None:
        from ..padlocks import MARKER_INSET, spot
        card = (0.4, 0.3, 0.5, 0.5)  # fractions of a 1000 x 1000 window: 100 x 200 on screen
        ui = BoardUI(False, False, False, False, False, cards={"c1": card})
        window, size = (0, 0, 1000, 1000), 40
        left, top, right, bottom = spot(Padlock(card="c1", marker="green"), ui, window, size)
        self.assertAlmostEqual((left + right) / 2, 500 - size * MARKER_INSET)
        self.assertAlmostEqual((top + bottom) / 2, 300 + size * MARKER_INSET)
        self.assertEqual(spot(Padlock(card="c1"), ui, window, size), (430, 380, 470, 420))  # the padlock: centre

    def test_an_event_option_placed_as_a_point(self) -> None:
        """Owner's screenshot 2026-11-13: the marker sat mid-card - event options are a point (their art's centre),
        so their size comes from their BoxCollider (BoardUI.sizes, read live: the PvP card's box matched its frame)."""
        from ..padlocks import MARKER_INSET, spot
        point = (0.5, 0.34, 0.5, 0.34)
        ui = BoardUI(False, False, False, False, False, cards={"pvp_1": point}, sizes={"pvp_1": (0.1, 0.15)})
        window, size = (0, 0, 1920, 1080), 56
        left, top, right, bottom = spot(Padlock(card="pvp_1", marker="green"), ui, window, size)
        card_right, card_top = 960 + 0.05 * 1920, 0.34 * 1080 - 0.075 * 1080
        self.assertAlmostEqual((left + right) / 2, card_right - size * MARKER_INSET)
        self.assertAlmostEqual((top + bottom) / 2, card_top + size * MARKER_INSET)
        centre = spot(Padlock(card="pvp_1"), ui, window, size)  # a padlock still sits on the centre
        self.assertEqual(((centre[0] + centre[2]) / 2, (centre[1] + centre[3]) / 2), (960, 0.34 * 1080))
