import unittest

from NetUtils import NetworkItem

from ..card_picker import ANY, CardPicker, filter_cards
from ..data import CARDS
from ..items import BASE_ID, item_name_to_id
from ..logparser import CardGained, DayReached, RunEnded, RunStarted
from ..locations import day_location
from .test_client import LOCKED, ClientTestBase


class TestFilters(unittest.TestCase):
    def test_every_card_with_no_filter(self) -> None:
        self.assertEqual(len(filter_cards(CARDS, "", ANY, ANY, ANY, False, set())), len(CARDS))

    def test_filters_combine(self) -> None:
        cards = filter_cards(CARDS, "", "Vanessa", "Small", "Bronze", False, set())
        self.assertTrue(cards)
        self.assertTrue(all((c.hero, c.size, c.tier) == ("Vanessa", "Small", "Bronze") for c in cards))
        self.assertTrue(all(c.hero == "Common" for c in filter_cards(CARDS, "", "Common", ANY, ANY, False, set())))

    def test_search_ignores_case_and_matches_inside_names(self) -> None:
        part = LOCKED.name[1:4].upper()
        self.assertIn(LOCKED, filter_cards(CARDS, part, ANY, ANY, ANY, False, set()))

    def test_locked_only(self) -> None:
        self.assertEqual(filter_cards(CARDS, "", ANY, ANY, ANY, True, {LOCKED.guid}), [LOCKED])


class TestPickerWindow(unittest.TestCase):
    def test_only_a_locked_card_can_be_picked(self) -> None:
        import tkinter
        other = next(c for c in CARDS if c.guid != LOCKED.guid)
        picked = []
        root = tkinter.Tk()
        try:
            picker = CardPicker(tkinter, root, lambda: (0, 0, 1920, 1080), picked.append)
            picker.update(1, {LOCKED.guid})
            picker.open()
            root.update()
            self.assertEqual(len(picker.tree.get_children()), len(CARDS))
            picker.vars["text"].set(LOCKED.name)
            self.assertIn(LOCKED.guid, picker.tree.get_children())

            picker.vars["text"].set("")
            picker.tree.selection_set(other.guid)
            root.update()
            self.assertEqual(str(picker.button.cget("state")), "disabled")
            picker.tree.selection_set(LOCKED.guid)
            root.update()
            picker.button.invoke()
            self.assertEqual(picked, [LOCKED.guid])
            self.assertFalse(picker.is_open())

            picker.open()
            picker.update(0, set())  # the run ended or the bypass was used: it closes
            self.assertFalse(picker.is_open())
        finally:
            root.destroy()


class TestPickInClient(ClientTestBase):
    OTHER = next(c for c in CARDS if c.shop and c.hero == "Vanessa" and c.guid != LOCKED.guid)

    def setUp(self) -> None:
        super().setUp()
        self.ctx.slot_data["lock_items"].append(BASE_ID + self.OTHER.ap_id)
        self.ctx.items_received.append(NetworkItem(item_name_to_id["Lock Bypass"], 0, 0, 0))

    def test_picked_card_is_allowed_before_you_get_it(self) -> None:
        self.play(RunStarted("Vanessa"))
        self.ctx.pick_bypass(self.OTHER.guid)
        self.assertEqual(self.ctx.bypasses_ready(), 0)
        self.play(CardGained(LOCKED.guid, "itm_x", True))  # the bypass went to the picked card, not this one
        self.assertIn(LOCKED.name.upper(), self.ctx.blocked_reason())
        self.play(CardGained(self.OTHER.guid, "itm_o", True))
        self.assertNotIn(self.OTHER.name.upper(), self.ctx.blocked_reason())

    def test_picking_a_held_card_unblocks_checks(self) -> None:
        self.ctx.items_received.pop()  # no bypass yet: the card is held and blocks
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", True))
        self.assertIsNotNone(self.ctx.blocked_reason())
        self.ctx.items_received.append(NetworkItem(item_name_to_id["Lock Bypass"], 0, 0, 0))
        self.ctx.pick_bypass(LOCKED.guid)
        self.play(DayReached(2))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertTrue(self.was_sent(day_location("Vanessa", 2)))

    def test_a_pick_that_no_longer_applies_is_ignored(self) -> None:
        self.ctx.pick_bypass(LOCKED.guid)  # between runs
        self.play(RunStarted("Vanessa"))
        self.ctx.pick_bypass(next(c for c in CARDS if c.hero == "Common").guid)  # not locked
        self.assertEqual(self.ctx.bypasses_ready(), 1)
        self.play(RunEnded(False, 1))
