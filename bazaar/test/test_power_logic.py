"""Logic changes (owner, 2026-11-10). Expected results are the owner's words and the approved tables:
- "10 wins on each character locked behind at least 2 card packs" (fewer when the seed gives the hero fewer).
- "Count as 10": a pack counts as its 10 cards in the card logic.
- Power items = Expedition Tickets (3), Legendary Items (1st copy), Event Rarity Progression (first 2): 6 by default.
- Diamond/Legendary monster checks need power items counted DOWN from the seed's last day (owner 2026-11-11, "Yes" to:
  day 13 Diamond needs all 6, day 12 needs 5, ... day 8 needs 1 - from day 13 - 6 = 7). Diamond (day - start),
  Legendary one more, never more than the seed has.
- Spare copies never count, and the client's tracker must agree with the world's rules."""
import random
import unittest
from collections import Counter

from BaseClasses import CollectionState

from ..items import EVENT_RARITY, EXPEDITION_TICKETS, LEGENDARY_ITEMS, PACKS_BY_ITEM, TICKET_ITEMS, power_held, power_total
from ..locations import Check, monster_location, power_needed, win_location
from .bases import ALL_HEROES, BazaarTestBase
from .test_client import ClientTestBase



class TestPowerNumbers(unittest.TestCase):
    def test_default_seed_has_six(self) -> None:
        self.assertEqual(power_total([EXPEDITION_TICKETS, LEGENDARY_ITEMS], 3), 6)  # the 3rd Event Rarity is a bypass
        self.assertEqual(power_total(TICKET_ITEMS, 0), 3)  # separate tickets count one each
        self.assertEqual(power_total([], 0), 0)
        self.assertEqual(power_total([EXPEDITION_TICKETS, LEGENDARY_ITEMS, "Level Up: Shiny!"], 3), 7)  # Shiny! joined

    def test_owner_table(self) -> None:
        def need(day: int, tier: str, total: int = 6, max_day: int = 13) -> int:
            return power_needed(Check("x", "monster", day, tier), total, max_day)
        # the owner's example (2026-11-11): a 13-day seed with 6 power items
        self.assertEqual([need(13, "Diamond"), need(12, "Diamond"), need(8, "Diamond"), need(7, "Diamond")],
                         [6, 5, 1, 0])
        self.assertEqual([need(7, "Legendary"), need(12, "Legendary"), need(13, "Legendary")], [1, 6, 6])  # capped
        self.assertEqual([need(6, "Diamond"), need(6, "Legendary")], [0, 0])
        self.assertEqual([need(16, "Diamond", max_day=16), need(10, "Diamond", max_day=16)], [6, 0])  # a 16-day seed
        self.assertEqual(need(13, "Gold"), 0)
        self.assertEqual(need(13, "Diamond", 0), 0)
        self.assertEqual(need(10, "Diamond", 3), 0)  # 3 items start at day 10 of 13

    def test_spares_never_count(self) -> None:
        counts = Counter({EXPEDITION_TICKETS: 6, LEGENDARY_ITEMS: 3, EVENT_RARITY: 5})
        self.assertEqual(power_held(counts.__getitem__), 6)


def collect(test: BazaarTestBase, names) -> CollectionState:
    state = CollectionState(test.multiworld)
    for name in names:
        state.collect(test.world.create_item(name), True)
    return state


class TestRules(BazaarTestBase):
    options = {**ALL_HEROES, "starting_hero": "stelle", "max_day": 13, "max_monster_tier": "legendary",
               "monster_rarities": "all", "locked_cards_percent": 100, "legacy_card_packs": True}

    def everything_but(self, *left_out: str) -> CollectionState:
        hero = "Stelle"
        names = [n for n in self.world.lock_items[hero]] + [i.name for i in self.multiworld.itempool
                                                            if i.player == self.player and i.advancement]
        names = [n for n in names if n not in left_out and (n not in PACKS_BY_ITEM or n in self.world.lock_items[hero])]
        return collect(self, names)

    def reach(self, state: CollectionState, location: str) -> bool:
        return self.multiworld.get_location(location, self.player).can_reach(state)

    def test_ten_wins_need_two_packs(self) -> None:
        packs = [n for n in self.world.lock_items["Stelle"] if n in PACKS_BY_ITEM]
        self.assertEqual(len(packs), 3)
        self.assertTrue(self.reach(self.everything_but(), win_location("Stelle")))
        self.assertTrue(self.reach(self.everything_but(packs[0]), win_location("Stelle")))  # 2 of 3 is enough
        self.assertFalse(self.reach(self.everything_but(packs[0], packs[1]), win_location("Stelle")))

    def test_late_diamond_needs_power(self) -> None:
        """13-day seed, 7 power items (Shiny! joined, owner 2026-11-11): they count down from day 13, so day D's
        Diamond wants D - 6 and the last day's wants all 7; Legendary one more (capped) and Legendary Items."""
        self.assertEqual(self.world.power, 7)
        def diamond(day: int) -> str:
            return monster_location("Stelle", day, "Diamond")
        all_in = self.everything_but()
        self.assertTrue(self.reach(all_in, diamond(13)))
        self.assertTrue(self.reach(all_in, monster_location("Stelle", 13, "Legendary")))
        no_tickets = self.everything_but(EXPEDITION_TICKETS)  # 1 Legendary + 2 Event Rarity + Shiny! = 4 left
        self.assertTrue(self.reach(no_tickets, diamond(10)))  # wants 4
        self.assertFalse(self.reach(no_tickets, diamond(11)))  # wants 5
        self.assertFalse(self.reach(no_tickets, diamond(13)))
        two_left = self.everything_but(EXPEDITION_TICKETS, LEGENDARY_ITEMS)  # 3 left
        self.assertTrue(self.reach(two_left, diamond(9)))  # wants 3
        self.assertFalse(self.reach(two_left, diamond(10)))

    def test_power_items_are_progression(self) -> None:
        kinds = {i.name: i.advancement for i in self.multiworld.itempool if i.player == self.player}
        self.assertTrue(kinds[LEGENDARY_ITEMS] and kinds[EVENT_RARITY] and kinds[EXPEDITION_TICKETS])


class TestPackWeight(BazaarTestBase):
    options = {"include_karnok": True, "starting_hero": "karnok", "locked_cards_percent": 100}

    def test_two_packs_cover_day_ten(self) -> None:
        """Day 10 wants 16 cards: two packs (20 cards) are enough without one single card."""
        packs = [n for n in self.world.lock_items["Karnok"] if n in PACKS_BY_ITEM]
        day10 = "Karnok - Reach Day 10"
        self.assertFalse(self.multiworld.get_location(day10, self.player).can_reach(collect(self, packs[:1])))
        self.assertTrue(self.multiworld.get_location(day10, self.player).can_reach(collect(self, packs[:2])))


class TestTrackerMatchesTheRules(ClientTestBase):
    """One definition: for random received items, the client's "in logic" equals the world's access rule."""
    def test_random_states(self) -> None:
        from .bases import BazaarTestBase as Base
        world_test = type("W", (Base,), {"options": {**ALL_HEROES, "legacy_card_packs": True, "plentiful_items": True,
                                                       "max_monster_tier": "legendary", "monster_rarities": "all",
                                                       "max_day": 16, "locked_cards_percent": 100}})
        w = world_test("test_empty_state_can_reach_something")
        w.world_setup()
        import json
        self.ctx.slot_data = json.loads(json.dumps(w.world.fill_slot_data()))
        pool = [i for i in w.multiworld.itempool if i.player == w.player] + list(w.multiworld.precollected_items[1])
        rng = random.Random(1110)
        from NetUtils import NetworkItem
        for _ in range(25):
            got = rng.sample(pool, rng.randint(0, len(pool)))
            got += [i for i in w.multiworld.precollected_items[1]]
            # by item, not by copy: a spare copy received first really unlocks it in game, so the world is asked
            # with every received copy counting as the item it is
            state = CollectionState(w.multiworld)
            for item in got:
                state.collect(w.world.create_item(item.name), True)
            self.ctx.items_received = [NetworkItem(item.code, 0, 1, 0) for item in got]
            for hero in w.world.heroes:
                for check, _, in_logic in self.ctx.check_states(hero):
                    world_says = w.multiworld.get_location(check.name, w.player).can_reach(state)
                    self.assertEqual(in_logic, world_says, f"{check.name} with {len(got)} items")
