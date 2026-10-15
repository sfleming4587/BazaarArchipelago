import unittest

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
        lock, options = Padlock(card="enc_a", option=0), [(715, 303)]
        seen = ui(cards={"enc_a": frac((715, 305, 715, 305))})
        self.assertEqual(padlocks.spot(lock, seen, WINDOW, SIZE, options), (687, 277, 743, 333))
        for gone in (ui(), None):  # flipped away under the stash, or the board's state unreadable
            self.assertIsNone(padlocks.spot(lock, gone, WINDOW, SIZE, options))

    def test_a_right_clicked_event_keeps_its_padlock_on_the_enlarged_art(self) -> None:
        """Owner, 2026-10-15: right-clicking an event hid its padlock; it is art on the card, so it rides along.
        Recorded: the enlarged Jungle Ruins' centre at 0.363, 0.41 of the window (matched to the owner's video)."""
        lock, options = Padlock(card="enc_a", option=0), [(715, 303)]
        board = ui(hovering=True, inspecting=True, hovered_card="enc_a", cards={"enc_a": (0.363, 0.41, 0.363, 0.41)})
        square = padlocks.spot(lock, board, WINDOW, SIZE, options)
        self.assertEqual(tuple(round(v) for v in square), (669, 415, 725, 471))
        self.assertEqual(padlocks.alpha(lock, square, board, [], 6, 0.0, 100.0), SOLID)
        other = Padlock(card="enc_b", option=1)  # another option, under the big view
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

    def test_an_event_option_uses_its_measured_place(self) -> None:
        """Owner, 2026-10-14: events keep the measured layout until their positions are read."""
        square = padlocks.spot(Padlock(option=1), ui(), WINDOW, SIZE, options=[(715, 303), (960, 364)])
        self.assertEqual(square, (932, 336, 988, 392))


class TestPadlockShows(unittest.TestCase):
    """Hidden while its card can't be bought or clicked, see-through while the game shows something over it, solid
    otherwise (owner, 2026-10-14)."""

    def alpha(self, board, card="pasta", place=None, turning_since=0.0, now=100.0):
        lock = Padlock(card=card, place=place)
        square = padlocks.spot(lock, board, WINDOW, SIZE)
        return padlocks.alpha(lock, square, board, padlocks.coverings(board, WINDOW), 6, turning_since, now)

    def test_solid_when_nothing_covers_it(self) -> None:
        self.assertEqual(self.alpha(ui(cards={"pasta": PASTA, "prep": PREP})), SOLID)

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


class TestOtherOverlayWindows(unittest.TestCase):
    def test_a_window_fades_only_when_something_reaches_it(self) -> None:
        """Owner, 2026-10-14: "ANY UI overlay element to only become opaque when something is being blocked by it"."""
        covers = padlocks.coverings(ui(hovering=True, tooltips=PREP_TOOLTIP), WINDOW)
        self.assertFalse(padlocks.covered((20, 300, 360, 600), covers))  # the left strip's box
        self.assertTrue(padlocks.covered((1000, 200, 1500, 300), covers))  # under the title bar
