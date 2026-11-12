"""Trap Shield (owner, 2026-11-10): "a trap shield would be pretty cool (Dont name is sell trap shield, just trap shield
incase we have more traps in the future)"; "the shield is only to prevent traps FOUND AFTER YOU RECEIVED IT, aka the
only time a trap can be blocked is upon receiving it". A trap that misses anyway keeps the shield; unused ones carry
over; it never counts in logic."""
import unittest

from BaseClasses import ItemClassification
from NetUtils import NetworkItem

from ..items import TRAP_SHIELD, TRAPS, item_name_to_id
from ..logparser import CardGained, CardSold, DayReached, RunStarted
from ..options import TrapShields, option_presets
from .bases import BazaarTestBase
from .test_client import TestSellTraps

SHIELD = item_name_to_id[TRAP_SHIELD]


class TestShieldInPool(BazaarTestBase):
    options = {"trap_shields": 4}

    def test_count_and_useful(self) -> None:
        shields = [i for i in self.multiworld.itempool if i.player == self.player and i.name == TRAP_SHIELD]
        self.assertEqual(len(shields), 4)
        self.assertTrue(all(i.classification == ItemClassification.useful for i in shields))

    def test_defaults(self) -> None:
        self.assertEqual(TrapShields.default, 3)
        self.assertEqual((option_presets["Casual"]["trap_shields"], option_presets["Hardcore"]["trap_shields"]), (0, 0))
        self.assertEqual(TRAPS, ["Sell Trap"])  # the list a new trap joins


class TestShields(TestSellTraps):
    def receive_shield(self) -> None:
        self.ctx.items_received.append(NetworkItem(SHIELD, 0, 0, 0))
        self.ctx.receive_traps()

    def test_shield_first_blocks_the_next_trap(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_a", False), DayReached(2))
        self.receive_shield()
        self.receive_trap()
        self.assertEqual(self.ctx.run["traps"], [])
        self.receive_trap()  # used up: the next one hits
        self.assertEqual(len(self.ctx.run["traps"]), 1)

    def test_a_shield_never_touches_a_trap_you_already_had(self) -> None:
        """Owner 2026-11-10: "the only time a trap can be blocked is upon receiving it"."""
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_a", False), DayReached(2))
        self.receive_trap()
        self.play(DayReached(4))
        self.receive_shield()
        self.assertEqual(len(self.ctx.run["traps"]), 1)
        self.assertIsNotNone(self.ctx.blocked_reason())
        self.assertEqual(self.ctx.shields_ready(), 1)  # kept for the next trap

    def test_a_trap_that_misses_keeps_the_shield(self) -> None:
        self.play(RunStarted("Vanessa"))  # holding nothing: the trap misses
        self.receive_shield()
        self.receive_trap()
        self.assertEqual(self.ctx.shields_ready(), 1)

    def test_between_runs_the_shield_waits(self) -> None:
        self.receive_shield()
        self.receive_trap()  # not in a run: dodged, shield kept
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_a", False))
        self.receive_trap()
        self.assertEqual(self.ctx.run["traps"], [])
        self.assertEqual(self.ctx.shields_ready(), 0)

    def test_resent_items_never_use_a_shield_twice(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_a", False))
        self.receive_shield()
        self.receive_trap()
        self.ctx.save_state()
        self.ctx.load_state()
        self.ctx.receive_traps()  # reconnect: everything resent
        self.receive_trap()
        self.assertEqual(len(self.ctx.run["traps"]), 1)  # the second trap hits: the shield was spent once

    def test_selling_still_ends_an_unshielded_trap(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_a", False), DayReached(2))
        self.receive_trap()
        self.play(CardSold("itm_a"))
        self.receive_shield()  # nothing running: kept for later
        self.assertEqual(self.ctx.shields_ready(), 1)



class TestShieldIcons(unittest.TestCase):
    """Owner 2026-11-10: "a shield icon (stacked to show how many shield you have) should be shown on the top left
    along side with how many bypasses you have"."""
    def test_status_line_draws_one_icon_per_shield(self) -> None:
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
            for shields in (0, 3):
                screen.state["status"] = ("Mak: day 2/13 · Goal 0/1 · Lock Bypasses: 1", False, False, shields)
                screen.render()
                root.update()
                canvases = [w for w in _all(screen.alert_box) if isinstance(w, tkinter.Canvas)]
                shapes = sum(len(c.find_all()) for c in canvases)
                self.assertEqual(shapes, 2 * shields)  # each shield: its outline and its middle line
        finally:
            root.destroy()


def _all(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _all(child)

