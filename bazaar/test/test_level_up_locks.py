"""Level-up event locks (owner, 2026-11-11): "lock the first level up event Shiny! as its own check", "Label the
Shiny! as a level up event", "treat it like a locked merchant in all ways, similar to events where ... one gets free
would be applied too", and it joins the power items ("The rainbow shows up for EVERY POWER ITEM. So shiny is
included"). The log line for picking it was seen in the owner's Player.log (ste_ ... TemplateIde286d583...) and the
level-up screen's options in memory (watcher, 2026-11-11)."""
from unittest import mock

from NetUtils import NetworkItem

from ..client import event_screen, good_unlock
from ..data import CARDS
from ..items import (GOOD_UNLOCK_IDS, ITEM_CLASSIFICATION, LEVEL_UP_ITEMS, LEVEL_UPS, LOCK_BYPASS_ID, POWER_CAPS,
                     TICKET_ITEMS, item_name_to_id)
from ..logparser import CardGained, CardSold, DayReached, EncounterEntered, EncounterLeft, RunStarted
from ..memreader import Offer, Snapshot
from .bases import BazaarTestBase
from .test_client import ClientTestBase

SHINY = "e286d583-65b1-4fc3-b76e-c182c5c34604"
SHINY_ITEM = "Level Up: Shiny!"
SHINY_ID = item_name_to_id[SHINY_ITEM]


class TestTheItem(BazaarTestBase):
    def test_always_in_the_pool_labelled_as_a_level_up_and_a_power_item(self) -> None:
        self.assertEqual(LEVEL_UP_ITEMS, [SHINY_ITEM])
        self.assertEqual(LEVEL_UPS[0].guids, (SHINY,))
        self.assertEqual(self.pool_names().count(SHINY_ITEM), 1)
        self.assertIn(SHINY_ITEM, POWER_CAPS)
        self.assertEqual(self.world.power, 7)  # 3 tickets + Legendary Items + 2 Event Rarity + Shiny!
        self.assertIn(SHINY_ITEM, self.world.encounter_locks)

    def test_rainbow_for_every_power_item_and_never_a_lone_card_or_event(self) -> None:
        self.assertTrue(good_unlock(SHINY_ID))
        for name in POWER_CAPS:
            self.assertIn(item_name_to_id[name], GOOD_UNLOCK_IDS, name)
        self.assertFalse(good_unlock(item_name_to_id["Cutlass"]))
        self.assertTrue(all(good_unlock(item_name_to_id[n]) for n in TICKET_ITEMS))  # separate tickets are power


class TestLikeALockedMerchant(ClientTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.ctx.slot_data.update(encounter_locks=[SHINY_ID])
        self.ctx.overlay = mock.Mock()

    def receive(self, item_id: int) -> None:
        self.ctx.items_received.append(NetworkItem(item_id, 0, 0, 0))
        self.ctx.on_package("ReceivedItems", {"index": 1, "items": [NetworkItem(item_id, 0, 0, 0)]})

    def level_up(self, *offers):
        return Snapshot("LevelUp", None, tuple(Offer(f"x_{i}", t, k) for i, (t, k) in enumerate(offers)))

    def test_picking_it_warns_and_what_you_take_blocks_until_sold_or_unlocked(self) -> None:
        item = next(c for c in CARDS if c.shop and c.hero == "Common" and c.size == "Small")
        self.play(RunStarted("Vanessa"), DayReached(2), EncounterEntered(SHINY))
        self.assertIsNone(self.ctx.blocked_reason())  # picking it is fine, like visiting a locked merchant
        toasts = [c.args[0] for c in self.ctx.overlay.toast.call_args_list]
        self.assertTrue(any("SHINY! IS LOCKED" in t for t in toasts), toasts)
        self.play(CardGained(item.guid, "itm_s", False))
        self.assertIn("UNTIL", self.ctx.blocked_reason())
        self.play(CardSold("itm_s"), EncounterLeft())
        self.assertIsNone(self.ctx.blocked_reason())
        self.play(EncounterEntered(SHINY), CardGained(item.guid, "itm_t", False))
        self.receive(SHINY_ID)  # its unlock arrives: keep it
        self.assertIsNone(self.ctx.blocked_reason())

    def test_a_lock_bypass_frees_what_you_took(self) -> None:
        item = next(c for c in CARDS if c.shop and c.hero == "Common" and c.size == "Small")
        self.play(RunStarted("Vanessa"), DayReached(2), EncounterEntered(SHINY), CardGained(item.guid, "itm_s", False))
        self.receive(LOCK_BYPASS_ID)
        self.ctx.use_bypass(item.guid)
        self.assertIsNone(self.ctx.blocked_reason())

    def test_padlock_on_the_level_up_option_and_no_self_naming_label(self) -> None:
        self.play(RunStarted("Vanessa"), DayReached(2))
        other = "1453be13-1d81-45ea-82a5-7d1ef35ec78b"  # Get Bronze item: a level-up event, never locked
        screen = self.level_up((other, "EventEncounter"), (SHINY, "EncounterStep"))
        self.assertIsNotNone(event_screen(screen))
        self.ctx.handle_snapshot(screen)
        locks = self.ctx.overlay.show_padlocks.call_args.args[0]
        self.assertEqual([lock.card for lock in locks], ["x_1"])
        self.assertIsNone(locks[0].why)  # "Locked behind: Level Up: Shiny!" would only name itself

    def test_every_option_locked_lets_one_through(self) -> None:
        self.play(RunStarted("Vanessa"), DayReached(2))
        self.ctx.handle_snapshot(self.level_up((SHINY, "EncounterStep")))
        self.assertIn(SHINY, self.ctx.run.get("let_through", []))
        self.play(EncounterEntered(SHINY))
        self.assertNotIn(SHINY, self.ctx.run_locked_events())

    def test_an_unknown_level_up_option_is_a_way_on(self) -> None:
        self.play(RunStarted("Vanessa"), DayReached(2))
        self.ctx.handle_snapshot(self.level_up((SHINY, "EncounterStep"),
                                               ("bc5a6ce7-dabf-4588-bd33-3b68217b38ca", "EncounterStep")))
        self.assertFalse(self.ctx.run.get("let_through"))

    def test_received_it_is_never_padlocked(self) -> None:
        self.receive(SHINY_ID)
        self.play(RunStarted("Vanessa"), DayReached(2))
        self.ctx.handle_snapshot(self.level_up((SHINY, "EncounterStep")))
        self.assertEqual(self.ctx.overlay.show_padlocks.call_args.args[0], [])


class TestClassification(BazaarTestBase):
    def test_useful_unless_power_is_needed(self) -> None:
        from BaseClasses import ItemClassification
        self.assertEqual(ITEM_CLASSIFICATION[SHINY_ITEM], ItemClassification.useful)
        shiny = next(i for i in self.pool_items() if i.name == SHINY_ITEM)
        self.assertTrue(shiny.advancement)  # default seed: late Diamond monsters need power
