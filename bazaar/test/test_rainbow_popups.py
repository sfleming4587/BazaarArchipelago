"""Good unlocks pop up on a drifting rainbow (owner, 2026-11-11: card packs, Legendary Items, Expedition Tickets,
Event Rarity Progression, heroes - "pretty much everything except the traps/buffs/single card locks"; one merchant or
event is like a single card)."""
import unittest

from ..client import good_unlock
from ..items import (ENCOUNTERS_BY_ITEM, EVENT_RARITY_ID, EXPEDITION_TICKETS, LEGENDARY_ITEMS, LOCK_BYPASS_ID,
                     PACKS_BY_ITEM, SELL_TRAP_ID, TICKET_ITEMS, TRAP_SHIELD_ID, item_name_to_id)
from ..theme import SEVERITY
from .test_client import ClientTestBase


class TestWhichUnlocksAreGood(unittest.TestCase):
    def test_big_unlocks_are_good(self) -> None:
        for name in (next(iter(PACKS_BY_ITEM)), LEGENDARY_ITEMS, EXPEDITION_TICKETS, TICKET_ITEMS[0], "Hero: Dooley"):
            self.assertTrue(good_unlock(item_name_to_id[name]), name)
        self.assertTrue(good_unlock(EVENT_RARITY_ID))

    def test_single_cards_traps_buffs_and_filler_are_not(self) -> None:
        merchant = next(n for n, e in ENCOUNTERS_BY_ITEM.items() if e.merchant)
        event = next(n for n, e in ENCOUNTERS_BY_ITEM.items() if not e.merchant)
        # owner 2026-11-11: "events that are locked behind their own individual check like single cards" - none
        for item_id in (item_name_to_id["Cutlass"], item_name_to_id[merchant], item_name_to_id[event], SELL_TRAP_ID,
                        LOCK_BYPASS_ID, TRAP_SHIELD_ID, item_name_to_id["Spare Change"]):
            self.assertFalse(good_unlock(item_id), item_id)


class TestSpareCopyHasNoRainbow(ClientTestBase):
    def good(self, item_id: int, earlier: int) -> bool:
        from unittest import mock

        from NetUtils import NetworkItem
        self.ctx.overlay = mock.Mock()
        self.ctx.slot = 1
        self.ctx.items_received = [NetworkItem(item_name_to_id["Spare Change"], 1, 1, 0)]
        self.ctx.items_received += [NetworkItem(item_id, 1, 1, 0) for _ in range(earlier + 1)]
        self.ctx.on_package("ReceivedItems", {"index": earlier + 1, "items": [NetworkItem(item_id, 1, 1, 0)]})
        return self.ctx.overlay.toast.call_args.kwargs["good"]

    def test_first_hero_copy_is_good_the_spare_is_not(self) -> None:
        hero = item_name_to_id["Hero: Dooley"]
        self.assertTrue(self.good(hero, 0))
        self.assertFalse(self.good(hero, 1))


class TestRainbowRow(unittest.TestCase):
    def test_colours_stay_close_to_the_green(self) -> None:
        from ..overlay import RAINBOW_BANDS, rainbow
        base = SEVERITY["ok"]
        colours = rainbow(base)
        self.assertEqual(len(set(colours)), RAINBOW_BANDS)
        for colour in colours:  # a tint, never a loud colour: no channel moves more than the tint allows
            for i in (1, 3, 5):
                self.assertLessEqual(abs(int(colour[i:i + 2], 16) - int(base[i:i + 2], 16)), 0.3 * 255 + 1)

    def test_good_popup_is_a_rainbow_that_moves(self) -> None:
        import queue
        import tkinter
        import types
        from ..overlay import RAINBOW_MS, Toast, _Screen
        root = tkinter.Tk()
        try:
            fake = types.SimpleNamespace(only_over_game=False, game_window=(0, 0, 1920, 1080), art_cache_dir=None,
                                         guide_file=None, commands=queue.Queue(), on_bypass=None)
            screen = _Screen(fake, tkinter, root)
            screen.relayout((0, 0, 1920, 1080))
            screen.new_toast(Toast("FOUND: Hero: Dooley", 1e12, False, False, (), True))
            screen.new_toast(Toast("FOUND: Cutlass", 1e12, False, False, (), False))
            screen.render()
            root.update()
            rows = screen.toast_box.winfo_children()[0].winfo_children()
            canvases = [r for r in rows if isinstance(r, tkinter.Canvas)]
            self.assertEqual(len(canvases), 1)  # only the good one
            canvas = canvases[0]
            texts = [canvas.itemcget(i, "text") for i in canvas.find_all() if canvas.type(i) == "text"]
            self.assertEqual(texts, ["FOUND: Hero: Dooley"])
            band = canvas.find_all()[0]
            before = canvas.itemcget(band, "fill")
            root.after(RAINBOW_MS * 2 + 20, root.quit)
            root.mainloop()
            self.assertNotEqual(canvas.itemcget(band, "fill"), before)  # it drifts
            screen.guide and screen.guide.shutdown()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
