"""Right-click "Locked behind" line (owner, 2026-11-10): right-clicking a locked item shows, where the red square was
(under the big card), "Locked behind: Pack (...)"; "This of course applies to events and any locked event and item"."""
import queue
import types
import unittest

from ..data import CARDS_BY_GUID, ENCOUNTERS, LEGENDARY_GUIDS
from ..items import BASE_ID, EVENT_RARITY_ID, SIZEINATOR, item_name_to_id
from ..memreader import BoardUI
from ..padlocks import Padlock, inspected
from .test_client import ClientTestBase

WINDOW = (0, 0, 1000, 500)
CUTLASS, ICE_SWAN = "1b955b8d-0ea6-4437-935c-d588be5898c1", "fdd78910-3e5c-4244-8c13-ac90a223fae3"  # by guid


def ui(**kw) -> BoardUI:
    base = dict(hovering=True, dragging=False, inventory=False, dialog=False, revealing=False, inspecting=True,
                hovered_card="c1", cards={"c1": (0.2, 0.1, 0.5, 0.8)})
    base.update(kw)
    return BoardUI(**base)


class TestWhere(unittest.TestCase):
    def test_under_the_inspected_card(self) -> None:
        self.assertEqual(inspected([Padlock(card="c1", why="Pack: Chill Out")], [(330, 160, 370, 200)], ui(), WINDOW),
                         ("Locked behind: Pack: Chill Out", 350.0, 400.0))

    def test_an_event_point_goes_under_its_padlock(self) -> None:
        point = ui(cards={"c1": (0.5, 0.5, 0.5, 0.5)})
        self.assertEqual(inspected([Padlock(card="c1", why="Event: X")], [(480, 230, 520, 270)], point, WINDOW),
                         ("Locked behind: Event: X", 500.0, 270))

    def test_only_while_inspecting_a_locked_one(self) -> None:
        lock, square = [Padlock(card="c1", why="Pack: X")], [(0, 0, 10, 10)]
        self.assertIsNone(inspected(lock, square, ui(inspecting=False), WINDOW))  # a plain hover
        self.assertIsNone(inspected(lock, square, ui(dialog=True), WINDOW))
        self.assertIsNone(inspected(lock, square, ui(hovered_card="c2"), WINDOW))  # another card, not locked
        self.assertIsNone(inspected([Padlock(card="c1")], square, ui(), WINDOW))
        self.assertIsNone(inspected(lock, [None], ui(), WINDOW))  # its padlock isn't showing


class TestWhatItSays(ClientTestBase):
    def test_a_card_names_its_item_and_an_unlocked_one_nothing(self) -> None:
        swan = CARDS_BY_GUID[ICE_SWAN]
        pack = item_name_to_id["Pack: Chill Out"]
        self.ctx.slot_data["lock_items"] = [pack]
        self.assertEqual(self.ctx.locked_behind(swan.guid), "Pack: Chill Out")
        self.assertIsNone(self.ctx.locked_behind(CUTLASS))

    def test_a_single_cards_own_unlock_is_named_too(self) -> None:
        """Owner, 2026-11-12: "I want EVERY 'Locked behind: {item}' available even for single card/event unlocks"
        (was 2026-11-11: never "this card")."""
        cutlass = CARDS_BY_GUID[CUTLASS]
        self.ctx.slot_data["lock_items"] = [item_name_to_id["Cutlass"]]
        self.assertEqual(self.ctx.locked_behind(cutlass.guid), "Cutlass")
        self.ctx.slot_data["lock_items"] = [item_name_to_id["Legendary Items"]]
        legendary = next(iter(LEGENDARY_GUIDS - {SIZEINATOR}))
        self.assertEqual(self.ctx.locked_behind(legendary), "Legendary Items")

    def test_an_event_names_its_own_unlock_then_event_rarity(self) -> None:
        """Owner, 2026-11-12: its own unlock is named too (was 2026-11-11: no line); then "if it was a legendary
        event 'Locked behind Event Progression' would be cool"."""
        encounter = ENCOUNTERS[0]
        self.ctx.slot_data["encounter_locks"] = [BASE_ID + encounter.ap_id]  # where a seed lists them
        self.assertEqual(self.ctx.event_locked_behind(encounter.guids[0]),
                         self.ctx.item_names.lookup_in_game(BASE_ID + encounter.ap_id))
        from NetUtils import NetworkItem
        self.ctx.items_received = [NetworkItem(BASE_ID + encounter.ap_id, 0, 0, 0)]
        self.assertEqual(self.ctx.event_locked_behind(encounter.guids[0]),  # what still locks it: its rarity
                         self.ctx.item_names.lookup_in_game(EVENT_RARITY_ID))


class TestTheWindow(unittest.TestCase):
    def test_shows_under_the_card_and_hides_after(self) -> None:
        import tkinter

        from ..overlay import _Screen
        root = tkinter.Tk()
        try:
            fake = types.SimpleNamespace(only_over_game=False, game_window=(0, 0, 1280, 720), art_cache_dir=None,
                                         guide_file=None, commands=queue.Queue(), on_bypass=None)
            screen = _Screen(fake, tkinter, root)
            screen.relayout((0, 0, 1280, 720))
            screen.game_in_front = True
            screen.board_ui = ui()
            screen.locks, screen.lock_squares = [Padlock(card="c1", why="Pack: Brewing Trouble")], [(400, 200, 440, 240)]
            screen.place_why()
            root.update()
            box = screen.why_box
            self.assertEqual(box.state(), "normal")
            self.assertEqual(box.label.cget("text"), "Locked behind: Pack: Brewing Trouble")
            self.assertGreaterEqual(box.winfo_y(), round(0.8 * 720))  # below the card's art, never on it
            screen.board_ui = ui(inspecting=False)
            screen.place_why()
            self.assertNotEqual(box.state(), "normal")
        finally:
            root.destroy()
