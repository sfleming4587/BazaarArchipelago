"""Expedition tickets and the Sizeinator (owner, 2026-11-09). Expected results are the owner's own words:
- "treat each of the expedition tickets as their own item ... or keep them as progressive. Default to progressive."
- Progressive order: Crash Site, then Temple, then Tiny World ("yes that order").
- "an option to have sizenator as a legendary item (Hard) or come with the tiny ticket (Default/easy)"."""
from NetUtils import NetworkItem

from ..data import CARDS_BY_NAME
from ..items import (BASE_ID, EXPEDITION_TICKETS, LEGENDARY_ITEMS, SIZEINATOR, TICKET_ITEMS, item_name_to_id,
                     unlock_steps)
from .bases import BazaarTestBase
from .test_client import ClientTestBase

CRASH, TEMPLE, TINY = (CARDS_BY_NAME[n].guid for n in ("Crash Site Ticket", "Temple Expedition Ticket",
                                                       "Tiny World Ticket"))
TICKETS_ID = item_name_to_id[EXPEDITION_TICKETS]
LEGENDARY_ID = item_name_to_id[LEGENDARY_ITEMS]


class TestProgressiveIsTheDefault(BazaarTestBase):
    def test_one_expedition_tickets_per_ticket_and_no_ticket_items(self) -> None:
        self.assertEqual(self.pool_names().count(EXPEDITION_TICKETS), 3)
        self.assertFalse(set(TICKET_ITEMS) & set(self.pool_names()))
        self.assertEqual(self.world.fill_slot_data()["expedition_ticket_unlocks"], "progressive")
        self.assertEqual(self.world.fill_slot_data()["sizeinator_unlock"], "with_tiny_world_ticket")


class TestSeparateTickets(BazaarTestBase):
    options = {"expedition_ticket_unlocks": "separate"}

    def test_each_ticket_is_its_own_item(self) -> None:
        pool = self.pool_names()
        self.assertEqual(sorted(n for n in pool if n in TICKET_ITEMS), sorted(TICKET_ITEMS))
        self.assertNotIn(EXPEDITION_TICKETS, pool)
        self.assertEqual(self.world.fill_slot_data()["expedition_ticket_unlocks"], "separate")


class TestTicketsOff(BazaarTestBase):
    options = {"expedition_ticket_unlocks": "off"}

    def test_no_ticket_unlocks(self) -> None:
        pool = self.pool_names()
        self.assertFalse(({EXPEDITION_TICKETS} | set(TICKET_ITEMS)) & set(pool))


class TestUnlockSteps(ClientTestBase):
    def received(self, *item_ids: int) -> None:
        self.ctx.items_received = [NetworkItem(i, 0, 0, 0) for i in item_ids]

    def seed(self, tickets=None, sizeinator=None, locks=(TICKETS_ID, LEGENDARY_ID)) -> None:
        self.ctx.slot_data["lock_items"] = list(locks)
        for key, value in (("expedition_ticket_unlocks", tickets), ("sizeinator_unlock", sizeinator)):
            if value is not None:
                self.ctx.slot_data[key] = value

    def test_progressive_unlocks_crash_site_then_temple_then_tiny_world_with_the_sizeinator(self) -> None:
        self.seed("progressive", "with_tiny_world_ticket", locks=(TICKETS_ID,))
        self.received()
        self.assertTrue({CRASH, TEMPLE, TINY, SIZEINATOR} <= self.ctx.locked_guids())
        self.received(TICKETS_ID)
        self.assertEqual({CRASH, TEMPLE, TINY, SIZEINATOR} & self.ctx.locked_guids(), {TEMPLE, TINY, SIZEINATOR})
        self.received(TICKETS_ID, TICKETS_ID)
        self.assertEqual({CRASH, TEMPLE, TINY, SIZEINATOR} & self.ctx.locked_guids(), {TINY, SIZEINATOR})
        self.received(TICKETS_ID, TICKETS_ID, TICKETS_ID)
        self.assertFalse({CRASH, TEMPLE, TINY, SIZEINATOR} & self.ctx.locked_guids())

    def test_separate_tiny_world_ticket_unlocks_only_itself_and_the_sizeinator(self) -> None:
        ids = [BASE_ID + CARDS_BY_NAME[n].ap_id for n in TICKET_ITEMS]
        self.seed("separate", "with_tiny_world_ticket", locks=ids)
        self.received(BASE_ID + CARDS_BY_NAME["Tiny World Ticket"].ap_id)
        self.assertEqual({CRASH, TEMPLE, TINY, SIZEINATOR} & self.ctx.locked_guids(), {CRASH, TEMPLE})

    def test_hard_sizeinator_needs_legendary_items_not_the_ticket(self) -> None:
        self.seed("progressive", "legendary_items")
        self.received(TICKETS_ID, TICKETS_ID, TICKETS_ID)
        self.assertIn(SIZEINATOR, self.ctx.locked_guids())
        self.received(TICKETS_ID, TICKETS_ID, TICKETS_ID, LEGENDARY_ID)
        self.assertNotIn(SIZEINATOR, self.ctx.locked_guids())

    def test_default_sizeinator_is_not_held_back_by_legendary_items(self) -> None:
        self.seed("progressive", "with_tiny_world_ticket")
        self.received(TICKETS_ID, TICKETS_ID, TICKETS_ID)
        self.assertNotIn(SIZEINATOR, self.ctx.locked_guids())

    def test_the_next_ticket_is_named_as_what_unlocks_it(self) -> None:
        self.seed("progressive", locks=(TICKETS_ID,))
        self.received(TICKETS_ID)
        self.assertEqual(self.ctx.unlock_item_for(TINY), EXPEDITION_TICKETS)

    def test_world_and_client_share_one_rule(self) -> None:
        steps = unlock_steps("progressive", "with_tiny_world_ticket")[TICKETS_ID]
        self.assertEqual([set(s) for s in steps], [{CRASH}, {TEMPLE}, {TINY, SIZEINATOR}])
