"""Plentiful Items (owner, 2026-11-10). Expected results are the owner's own words and the table the owner approved:
- "no duplicates of anything should exist by default. Allow an option for "Plentiful items" which then turns on
  duplicates for all the important ones" - "Plentiful meaning 2 of each important item".
- Approved table: hero unlocks, packs, merchant/event unlocks 2; Expedition Tickets 6 progressive (2 of each separate);
  single cards, Legendary Items, Event Rarity Progression, traps and buffs keep their own counts.
- "MAKE SURE NONE OF THE LOGIC BREAKS FROM DUPLICATES"; "Make sure ticket is progression by default for all
  difficulties"."""
import unittest

from BaseClasses import ItemClassification

from ..data import CARDS_BY_NAME
from ..items import ENCOUNTERS_BY_ITEM, EXPEDITION_TICKETS, PACKS_BY_ITEM, TICKET_ITEMS, item_name_to_id
from ..options import ExpeditionTicketUnlocks, LegendaryItems, PlentifulItems, option_presets
from .bases import ALL_HEROES, BazaarTestBase
from .test_client import ClientTestBase

ALL = {**ALL_HEROES, "legacy_card_packs": True, "locked_encounters_percent": 50}


class TestDefaultsAndPresets(unittest.TestCase):
    def test_off_by_default_on_in_casual(self) -> None:
        self.assertFalse(PlentifulItems.default)
        self.assertIs(option_presets["Casual"]["plentiful_items"], True)
        self.assertEqual(LegendaryItems.default, 1)

    def test_tickets_progressive_in_every_preset(self) -> None:
        self.assertEqual(ExpeditionTicketUnlocks.default, ExpeditionTicketUnlocks.option_progressive)
        for name, preset in option_presets.items():
            self.assertNotIn("expedition_ticket_unlocks", preset, name)


class TestPlentiful(BazaarTestBase):
    options = {**ALL, "plentiful_items": True, "legendary_items": 1, "event_rarity_progression": 3,
               "duplicate_cards": ["Cutlass"]}

    def test_two_of_each_important_unlock(self) -> None:
        names = [i.name for i in self.pool_items()]
        important = [n for n in set(names) if n.startswith("Hero: ") or n in PACKS_BY_ITEM or n in ENCOUNTERS_BY_ITEM]
        self.assertTrue(important)
        self.assertEqual({n: names.count(n) for n in important}, {n: 2 for n in important})
        self.assertEqual(names.count(EXPEDITION_TICKETS), 6)

    def test_counted_items_keep_their_option(self) -> None:
        names = [i.name for i in self.pool_items()]
        self.assertEqual(names.count("Legendary Items"), 1)
        self.assertEqual(names.count("Event Rarity Progression"), 3)
        cards = {n for n in names if n in CARDS_BY_NAME and n not in TICKET_ITEMS and n != "Cutlass"}
        self.assertTrue(cards and all(names.count(n) == 1 for n in cards))

    def test_only_one_copy_counts_for_logic(self) -> None:
        """Logic counts progression items only: every unlock has exactly as many progression copies as without
        Plentiful (one each, three progressive tickets); the copies are useful."""
        progression = [i.name for i in self.pool_items() if i.classification & ItemClassification.progression]
        for name in set(progression):
            expected = 3 if name == EXPEDITION_TICKETS else 1
            if name.startswith("Hero: ") or name in PACKS_BY_ITEM or name == EXPEDITION_TICKETS:
                self.assertEqual(progression.count(name), expected, name)

    def test_tickets_are_progression(self) -> None:
        tickets = [i for i in self.pool_items() if i.name == EXPEDITION_TICKETS]
        self.assertEqual(sum(bool(i.classification & ItemClassification.progression) for i in tickets), 3)


class TestSeparateTicketsPlentiful(BazaarTestBase):
    options = {"plentiful_items": True, "expedition_ticket_unlocks": "separate"}

    def test_two_of_each_ticket(self) -> None:
        names = [i.name for i in self.pool_items()]
        self.assertEqual({t: names.count(t) for t in TICKET_ITEMS}, {t: 2 for t in TICKET_ITEMS})


class TestPlentifulTakesCardSlots(BazaarTestBase):
    """The copies come out of the checks before the card budget, so Plentiful also means fewer locked cards."""
    options = {**ALL, "plentiful_items": True, "locked_cards_percent": 100}

    def test_no_filler_and_every_copy_fits(self) -> None:
        from ..items import FILLER_ITEMS
        names = [i.name for i in self.pool_items()]
        self.assertFalse([n for n in names if n in FILLER_ITEMS])
        self.assertEqual(names.count(EXPEDITION_TICKETS), 6)



class TestSpareCopyPopUps(ClientTestBase):
    def popups(self, item_id: int, earlier: int) -> list:
        from unittest import mock

        from NetUtils import NetworkItem
        self.ctx.overlay = mock.Mock()
        self.ctx.slot = 1
        self.ctx.slot_data["lock_items"] = [item_name_to_id[EXPEDITION_TICKETS]]
        self.ctx.slot_data["expedition_ticket_unlocks"] = "progressive"
        # a filler first: index 0 is the full list resent on connect, which never pops up
        self.ctx.items_received = [NetworkItem(item_name_to_id["Spare Change"], 1, 1, 0)]
        self.ctx.items_received += [NetworkItem(item_id, 1, 1, 0) for _ in range(earlier + 1)]
        self.ctx.on_package("ReceivedItems", {"index": earlier + 1, "items": [NetworkItem(item_id, 1, 1, 0)]})
        return [c.args[0] for c in self.ctx.overlay.toast.call_args_list]

    def test_second_hero_unlock_is_a_spare(self) -> None:
        hero = item_name_to_id["Hero: Dooley"]
        self.assertEqual(self.popups(hero, 0), ["FOUND: Dooley"])
        self.assertEqual(self.popups(hero, 1), ["FOUND: Dooley (spare copy)"])

    def test_tickets_count_up_then_spares(self) -> None:
        tickets = item_name_to_id[EXPEDITION_TICKETS]
        self.assertEqual(self.popups(tickets, 2), [f"FOUND: {EXPEDITION_TICKETS}"])  # the 3rd: Tiny World
        self.assertEqual(self.popups(tickets, 3), [f"FOUND: {EXPEDITION_TICKETS} (spare copy)"])

    def test_event_rarity_extras_are_never_spares(self) -> None:
        self.assertEqual(self.popups(item_name_to_id["Event Rarity Progression"], 2),
                         ["FOUND: Event Rarity Progression"])

    def test_a_spare_card_or_pack_still_shows_its_pictures(self) -> None:
        """Review 2026-11-10: the label is new, the pictures stay as before (a Duplicate Cards copy, a spare pack)."""
        from unittest import mock

        from NetUtils import NetworkItem
        cutlass = item_name_to_id["Cutlass"]
        self.ctx.overlay = mock.Mock()
        self.ctx.slot = 1
        self.ctx.slot_data["lock_items"] = [cutlass]
        self.ctx.items_received = [NetworkItem(item_name_to_id["Spare Change"], 1, 1, 0)] +             [NetworkItem(cutlass, 1, 1, 0)] * 2
        self.ctx.on_package("ReceivedItems", {"index": 2, "items": [NetworkItem(cutlass, 1, 1, 0)]})
        call = self.ctx.overlay.toast.call_args
        self.assertEqual(call.args[0], "FOUND: Cutlass (spare copy)")
        self.assertEqual(call.kwargs["cards"], [CARDS_BY_NAME["Cutlass"].guid])

