import unittest

from ..data import CARDS, CARDS_BY_NAME
from ..items import hero_item
from ..locations import day_location, monster_location, pvp_location, win_location
from BaseClasses import CollectionState

from .bases import BazaarTestBase

# merchant/event locks take slots card locks would get; tests about card locks and logic fitting leave them out
NO_ENCOUNTER_LOCKS = {"locked_encounters_percent": 0, "event_rarity_progression": 0}
ALL_DLC = {"include_mak": True, "include_stelle": True, "include_jules": True, "include_karnok": True,
           "include_the_dragons": True}


class TestDefaults(BazaarTestBase):
    def test_base_heroes_only(self) -> None:
        self.assertEqual(self.world.heroes, ["Vanessa", "Pygmalien", "Dooley"])
        self.assertEqual(self.world.goal_count, 3)

    def test_location_count(self) -> None:
        real = [loc for loc in self.multiworld.get_locations(self.player) if loc.address is not None]
        # per day: reach + PvP + monster rarities up to Diamond (d1 2, d2 3, d3-13 4 each) = 13 + 13 + 49, + 10 wins
        self.assertEqual(len(real), 3 * (13 + 13 + 49 + 1))

    def test_monster_tiers_by_day(self) -> None:
        hero = self.world.starting_hero
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertIn(monster_location(hero, 1, "Silver"), names)
        self.assertNotIn(monster_location(hero, 1, "Gold"), names)
        self.assertIn(monster_location(hero, 2, "Gold"), names)
        self.assertNotIn(monster_location(hero, 2, "Diamond"), names)
        self.assertIn(monster_location(hero, 3, "Diamond"), names)
        self.assertNotIn(monster_location(hero, 6, "Legendary"), names)  # Standard stops at Diamond
        self.assertIn(pvp_location(hero, 13), names)


class TestLegendaryMonsters(BazaarTestBase):
    options = {"max_monster_tier": "legendary"}

    def test_legendary_from_day_6(self) -> None:
        hero = self.world.starting_hero
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertNotIn(monster_location(hero, 5, "Legendary"), names)
        self.assertIn(monster_location(hero, 6, "Legendary"), names)

    def test_starting_hero_is_precollected_not_in_pool(self) -> None:
        start = hero_item(self.world.starting_hero)
        self.assertIn(start, [i.name for i in self.multiworld.precollected_items[self.player]])
        self.assertNotIn(start, [i.name for i in self.multiworld.itempool if i.player == self.player])

    def test_no_loot_items_locked(self) -> None:
        from ..data import CARDS_BY_NAME
        pool = [i.name for i in self.multiworld.itempool if i.player == self.player]
        self.assertFalse([n for n in pool if n in CARDS_BY_NAME and "Loot" in CARDS_BY_NAME[n].tags])

    def test_early_days_need_only_the_hero(self) -> None:
        hero = self.world.starting_hero
        for day in range(1, 6):
            self.assertTrue(self.can_reach_location(day_location(hero, day)))

    def test_late_days_need_cards(self) -> None:
        hero = self.world.starting_hero
        if self.world.lock_items.get(hero):
            self.assertFalse(self.can_reach_location(day_location(hero, 13)))
            self.assertFalse(self.can_reach_location(win_location(hero)))
            self.collect_by_name(self.world.lock_items[hero])
            self.assertTrue(self.can_reach_location(win_location(hero)))


class TestSomePacks(BazaarTestBase):
    """User, 2026-09-30: packs don't have to be all or none."""
    options = {"legacy_card_packs": True, "pack_dooley_dooltron": False, "pack_vanessa_the_gang": False}

    def test_unticked_packs_are_left_out(self) -> None:
        from ..data import PACKS
        names = [i.name for i in self.multiworld.itempool if i.player == self.player]
        packs = {n for n in names if n.startswith("Pack: ")}
        self.assertNotIn("Pack: Dooltron", packs)
        self.assertNotIn("Pack: The Gang", packs)
        self.assertIn("Pack: Mysteries of the Deep", packs)
        self.assertEqual(len(packs), 6)  # 8 packs for the base heroes, 2 unticked
        ticked = {guid for p in PACKS if f"Pack: {p.name}" in packs for guid in p.cards}
        self.assertFalse(ticked & {c.guid for c in CARDS if c.name in names})  # a pack's cards never also lock singly


class TestPackSwitchesMatchTheData(unittest.TestCase):
    def test_one_switch_per_pack_on_by_default(self) -> None:
        from ..data import PACKS
        from ..options import PACK_SWITCHES
        self.assertEqual(len(PACK_SWITCHES), len(PACKS))
        self.assertTrue(all(option.default for option in PACK_SWITCHES.values()))


class TestEverything(BazaarTestBase):
    options = {
        **ALL_DLC,
        "legacy_card_packs": True,
        "heroes_required": 8,
        "starting_hero": "the_dragons",
        "locked_cards_percent": 100,
    }

    def test_all_heroes(self) -> None:
        self.assertEqual(len(self.world.heroes), 8)
        self.assertEqual(self.world.starting_hero, "The Dragons")

    def test_packs_in_pool(self) -> None:
        names = [i.name for i in self.multiworld.itempool if i.player == self.player]
        self.assertEqual(sum(n.startswith("Pack: ") for n in names), 10)
        self.assertIn("Pack: Mysteries of the Deep", names)

    def test_pack_cards_not_locked_individually(self) -> None:
        names = {i.name for i in self.multiworld.itempool if i.player == self.player}
        self.assertNotIn("Diving Helmet", names)  # part of Mysteries of the Deep


class TestTightSpace(BazaarTestBase):
    """One hero, few days, far more locks requested than there are checks."""
    options = {
        "include_pygmalien": False,
        "include_dooley": False,
        "max_day": 5,
        "locked_cards_percent": 100,
        "legacy_card_packs": True,
        "heroes_required": 5,
        "pvp_win_checks": False,
        "monster_checks": False,
    }

    def test_clamped(self) -> None:
        self.assertEqual(self.world.heroes, ["Vanessa"])
        self.assertEqual(self.world.goal_count, 1)
        pool = [i for i in self.multiworld.itempool if i.player == self.player]
        self.assertEqual(len(pool), 6)


class TestNoLocks(BazaarTestBase):
    options = {"locked_cards_percent": 0, "lock_common_cards": False, "pvp_win_checks": False,
               "monster_checks": False, **NO_ENCOUNTER_LOCKS}

    def test_duplicates_before_filler(self) -> None:
        names = [i.name for i in self.multiworld.itempool if i.player == self.player]
        self.assertEqual(len(names), 42)
        self.assertEqual(sum(n.startswith("Hero: ") for n in names), 2 * 3)  # two heroes to find, 3 copies each
        self.assertEqual(names.count("Legendary Items"), 2)  # the option's copies, never topped up
        self.assertEqual(names.count("Expedition Tickets"), 2)


class TestMonsterCap(BazaarTestBase):
    options = {"max_monster_tier": "gold", "pvp_win_checks": False}

    def test_no_diamond_or_legendary(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertFalse([n for n in names if "(Diamond)" in n or "(Legendary)" in n])
        self.assertIn(monster_location(self.world.starting_hero, 12, "Gold"), names)


class TestGroupsAndStarters(BazaarTestBase):
    options = {"locked_cards_percent": 100, "lock_common_cards": True}

    def pool(self) -> list:
        return [i.name for i in self.multiworld.itempool if i.player == self.player]

    def test_group_items_have_two_copies(self) -> None:
        self.assertEqual(self.pool().count("Legendary Items"), 2)
        self.assertEqual(self.pool().count("Expedition Tickets"), 2)

    def test_legendary_cards_are_not_locked_individually(self) -> None:
        from ..data import CARDS_BY_NAME
        self.assertFalse([n for n in self.pool() if n in CARDS_BY_NAME and CARDS_BY_NAME[n].tier == "Legendary"])

    def test_starter_cards_are_never_locked(self) -> None:
        from ..data import CARDS_BY_NAME
        pool = set(self.pool())
        for group, starters in self.world.starters.items():
            self.assertEqual(len(starters), 20, group)
            self.assertTrue(all(CARDS_BY_NAME[n].tier == "Bronze" for n in starters))
            self.assertFalse(pool & set(starters), group)


class TestDuplicates(BazaarTestBase):
    options = {"duplicate_all_cards": True}

    def test_every_locked_card_has_at_least_two_copies(self) -> None:
        from ..data import CARDS_BY_NAME
        cards = [i.name for i in self.multiworld.itempool if i.player == self.player and i.name in CARDS_BY_NAME]
        self.assertTrue(cards)
        self.assertTrue(all(2 <= cards.count(n) <= 3 for n in cards))


class TestLogicThresholds(BazaarTestBase):
    options = {"logic_day_10_cards": 30, "logic_diamond_cards": 30, "logic_legendary_cards": 30,
               "locked_cards_percent": 5, "max_monster_tier": "legendary"}

    def test_late_checks_need_every_hero_card_but_early_monsters_do_not(self) -> None:
        hero = self.world.starting_hero
        items = self.world.lock_items.get(hero, [])
        self.assertTrue(items)
        self.assertTrue(self.can_reach_location(monster_location(hero, 3, "Silver")))
        self.assertFalse(self.can_reach_location(monster_location(hero, 3, "Diamond")))
        self.assertFalse(self.can_reach_location(day_location(hero, 10)))
        self.collect_by_name(items[:-1])
        self.assertFalse(self.can_reach_location(day_location(hero, 10)))
        self.collect_by_name(items[-1:])
        self.assertTrue(self.can_reach_location(day_location(hero, 10)))
        self.assertTrue(self.can_reach_location(monster_location(hero, 6, "Legendary")))


class TestFullPoolHasNoFiller(BazaarTestBase):
    def test_default_fills_every_check_with_real_unlocks(self) -> None:
        from ..items import FILLER_ITEMS
        names = [i.name for i in self.multiworld.itempool if i.player == self.player]
        self.assertFalse([n for n in names if n in FILLER_ITEMS])


class TestHalfPercent(BazaarTestBase):
    options = {"locked_cards_percent": 50, "legendary_items": 2, "expedition_tickets": 1,
               "duplicate_cards": ["Cutlass"]}

    def test_rest_are_duplicates_in_order(self) -> None:
        from ..items import FILLER_ITEMS
        names = [i.name for i in self.multiworld.itempool if i.player == self.player]
        self.assertFalse([n for n in names if n in FILLER_ITEMS])
        self.assertEqual(sum(n.startswith("Hero: ") for n in names), 2 * 3)
        unlocks = [n for n in names if n not in ("Sell Trap", "Lock Bypass")]  # those are counts, not copies
        self.assertTrue(max(unlocks.count(n) for n in set(unlocks)) <= 3)

    def test_copy_counts_you_set_never_grow(self) -> None:
        """User, 2026-09-30: asking for 2 Legendary Items and then finding a 3rd would feel wrong."""
        names = [i.name for i in self.multiworld.itempool if i.player == self.player]
        self.assertEqual(names.count("Legendary Items"), 2)
        self.assertEqual(names.count("Expedition Tickets"), 1)
        self.assertIn(names.count("Cutlass"), (0, 2))  # 0 if Cutlass wasn't picked as a lock


class TestDay7IsFree(BazaarTestBase):
    options = {"logic_day_10_cards": 30, "logic_diamond_cards": 30, "logic_legendary_cards": 30}

    def test_days_up_to_7_need_only_the_hero(self) -> None:
        hero = self.world.starting_hero
        self.assertTrue(self.can_reach_location(day_location(hero, 7)))
        if self.world.lock_items.get(hero):
            self.assertFalse(self.can_reach_location(day_location(hero, 8)))


class TestPvPLogicIsOneDayAhead(BazaarTestBase):
    options = {"logic_day_10_cards": 30}

    def test_day_7_pvp_needs_cards_but_reaching_day_7_does_not(self) -> None:
        hero = self.world.starting_hero
        if not self.world.lock_items.get(hero):
            return
        self.assertTrue(self.can_reach_location(day_location(hero, 7)))
        self.assertFalse(self.can_reach_location(pvp_location(hero, 7)))
        self.assertTrue(self.can_reach_location(pvp_location(hero, 6)))


class TestEarlyHeroUnlock(BazaarTestBase):
    options = {"early_hero_unlock": True}

    def test_a_second_hero_is_requested_early(self) -> None:
        early = self.multiworld.local_early_items[self.player]
        heroes = [name for name in early if name.startswith("Hero: ")]
        self.assertEqual(len(heroes), 1)
        self.assertNotEqual(heroes[0], f"Hero: {self.world.starting_hero}")


class TestSellTrapsInPool(BazaarTestBase):
    options = {"sell_traps": 5}

    def test_traps_are_placed(self) -> None:
        names = [i.name for i in self.multiworld.itempool if i.player == self.player]
        self.assertEqual(names.count("Sell Trap"), 5)


class TestLockBypassesInPool(BazaarTestBase):
    options = {"sell_traps": 2, "lock_bypasses": 3}

    def test_bypasses_are_placed_next_to_traps(self) -> None:
        names = [i.name for i in self.multiworld.itempool if i.player == self.player]
        self.assertEqual(names.count("Lock Bypass"), 3)
        self.assertEqual(names.count("Sell Trap"), 2)


class TestIncludedHeroSwitches(BazaarTestBase):
    """Heroes are picked with one on/off switch each (user 2026-09-29), all under "Included Heroes (Must own)"
    (user 2026-10-05). The base heroes are ticked by default."""
    options = {"include_karnok": True, "include_the_dragons": True, "starting_hero": "karnok"}

    def test_switched_on_heroes_are_in(self) -> None:
        self.assertEqual(set(self.world.heroes), {"Vanessa", "Pygmalien", "Dooley", "Karnok", "The Dragons"})

    def test_starting_hero_values_never_move(self) -> None:
        from ..options import StartingHero
        self.assertEqual(StartingHero.options, {"any": 0, "vanessa": 1, "pygmalien": 2, "dooley": 3, "mak": 4,
                                                "stelle": 5, "jules": 6, "karnok": 7, "the_dragons": 8})

    def test_deathlink_options_default_off(self) -> None:
        self.assertFalse(self.world.options.death_link)
        self.assertFalse(self.world.options.death_link_on_concede)


class TestUntickedHeroesAreOut(BazaarTestBase):
    """A hero left unticked, base hero or not, isn't in the seed (user 2026-10-05)."""
    options = {"include_dooley": False, "starting_hero": "vanessa"}

    def test_switched_off_heroes_are_out(self) -> None:
        self.assertEqual(set(self.world.heroes), {"Vanessa", "Pygmalien"})


class TestOnlyDayChecks(BazaarTestBase):
    """PvP and monster checks both off leaves each hero 7 checks that need no cards; logic used to expect 8 of its
    cards before day 8 and generation failed on some seeds (review 2026-09-29). The world lowers logic to fit."""
    options = {"pvp_win_checks": False, "monster_checks": False, **NO_ENCOUNTER_LOCKS}

    def test_logic_fits_the_free_checks(self) -> None:
        self.assertLessEqual(-(-self.world.logic["day_10"] // 2), 7 - 2)


class TestNoLegendaryItemsUnlock(BazaarTestBase):
    """legendary_items: 0 means Legendary items are never locked - also not one by one (review 2026-09-29)."""
    options = {"legendary_items": 0}

    def test_no_legendary_card_is_locked(self) -> None:
        from ..data import CARDS_BY_NAME
        locked = [name for names in self.world.lock_items.values() for name in names if name in CARDS_BY_NAME]
        self.assertFalse([name for name in locked if CARDS_BY_NAME[name].tier == "Legendary"])
        self.assertNotIn("Legendary Items", self.world.group_items)


class TestUniversalTrackerRebuild(BazaarTestBase):
    """Universal Tracker rebuilds the world from slot_data with default options; it must match the real seed."""
    options = {"include_mak": True, "include_karnok": True, "max_day": 12, "max_monster_tier": "diamond",
               "logic_day_10_cards": 22, "logic_diamond_cards": 7, "logic_legendary_cards": 12,
               "legacy_card_packs": True, "starting_hero": "karnok"}

    def rebuild(self):
        import json
        from argparse import Namespace
        from BaseClasses import CollectionState, MultiWorld
        from worlds.AutoWorld import call_all
        slot_data = json.loads(json.dumps(self.world.fill_slot_data()))  # as it arrives from the server
        world_type = type(self.world)
        multiworld = MultiWorld(1)
        multiworld.game = {1: world_type.game}
        multiworld.player_name = {1: "Tracker"}
        multiworld.set_seed(12345)
        args = Namespace(**{key: {1: option.from_any(option.default)}
                            for key, option in world_type.options_dataclass.type_hints.items()})
        multiworld.set_options(args)
        multiworld.re_gen_passthrough = {world_type.game: world_type.interpret_slot_data(slot_data)}
        multiworld.state = CollectionState(multiworld)
        for step in ("generate_early", "create_regions", "create_items", "set_rules"):
            call_all(multiworld, step)
        return multiworld

    def test_same_locations_and_logic(self) -> None:
        rebuilt = self.rebuild()
        mine = {loc.name for loc in self.multiworld.get_locations(self.player)}
        theirs = {loc.name for loc in rebuilt.get_locations(1)}
        self.assertEqual(mine, theirs)
        self.assertEqual({h: sorted(v) for h, v in self.world.lock_items.items()},
                         {h: sorted(v) for h, v in rebuilt.worlds[1].lock_items.items()})
        # the same things are reachable with nothing, and with the starting hero's cards
        start = self.world.starting_hero
        cards = self.world.lock_items.get(start, [])[:22]
        for collect in ([], cards):
            state_a, state_b = CollectionState(self.multiworld), CollectionState(rebuilt)
            for name in collect:
                state_a.collect(self.world.create_item(name), True)
                state_b.collect(rebuilt.worlds[1].create_item(name), True)
            reach_a = {loc.name for loc in self.multiworld.get_locations(self.player) if loc.can_reach(state_a)}
            reach_b = {loc.name for loc in rebuilt.get_locations(1) if loc.can_reach(state_b)}
            self.assertEqual(reach_a, reach_b)


class TestOneUnlockPerCard(unittest.TestCase):
    """User, 2026-09-30: e.g. a Mysteries of the Deep card must never be locked both by its pack and on its own.
    Across many option mixes, no card may be unlocked by two different items (it would need both), and every
    unlock item in the pool must unlock something."""
    MIXES = [
        {},
        {"legacy_card_packs": True},
        {"legacy_card_packs": True, "pack_vanessa_the_gang": False, "pack_dooley_primal_dooley": False},
        {"legacy_card_packs": True, "duplicate_all_cards": True, "locked_cards_percent": 50},
        {"legendary_items": 0, "expedition_tickets": 0},
        {"legendary_items": 3, "expedition_tickets": 3, "locked_cards_percent": 100, "lock_common_cards": True,
         "lock_loot_items": True, "starter_cards": 0},
        {**ALL_DLC, "legacy_card_packs": True, "heroes_required": 8, "locked_cards_percent": 100,
         "duplicate_cards": ["Cutlass", "Dooltron"]},
    ]

    def test_no_card_has_two_unlocks(self) -> None:
        from ..items import UNLOCKS, item_name_to_id
        for options in self.MIXES:
            with self.subTest(**{k: str(v) for k, v in options.items()}):
                mix = type("Mix", (BazaarTestBase,), {"options": options, "build": lambda self: None})
                base = mix("build")  # a method of its own: the test base skips set-up for its own test names
                base.setUp()
                names = {i.name for i in base.multiworld.itempool if i.player == base.player}
                unlocks = {n: UNLOCKS[item_name_to_id[n]] for n in names if item_name_to_id[n] in UNLOCKS}
                owners: dict = {}
                for name, guids in unlocks.items():
                    self.assertTrue(guids, f"{name} unlocks nothing")
                    for guid in guids:
                        owners.setdefault(guid, set()).add(name)
                self.assertFalse({g: o for g, o in owners.items() if len(o) > 1})
                in_seed = {base.world.create_item(n).code for ns in base.world.lock_items.values() for n in ns}
                self.assertLessEqual(in_seed, {item_name_to_id[n] for n in names})  # slot_data locks are all real


class TestLogicClimbsAfterDay10(unittest.TestCase):
    """User, 2026-09-30: a late day on the day-10 minimum is much harder, so logic climbs to the last-day amount."""

    @staticmethod
    def needs(max_day: int, logic: dict, lock_count: int = 100) -> dict:
        from ..locations import card_requirements
        return card_requirements("Vanessa", lock_count, max_day, True, lambda day: [], logic)

    def test_standard_and_hardcore_climb(self) -> None:
        standard = self.needs(13, {"day_10": 16, "last_day": 28, "diamond": 10, "legendary": 20})
        self.assertEqual([standard[day_location("Vanessa", d)] for d in (7, 8, 9, 10, 11, 12, 13)],
                         [0, 8, 8, 16, 20, 24, 28])
        hardcore = self.needs(16, {"day_10": 25, "last_day": 50, "diamond": 20, "legendary": 30})
        self.assertEqual([hardcore[day_location("Vanessa", d)] for d in range(10, 17)], [25, 29, 33, 38, 42, 46, 50])

    def test_ten_wins_and_the_last_pvp_need_the_last_day_amount(self) -> None:
        needs = self.needs(13, {"day_10": 16, "last_day": 28, "diamond": 10, "legendary": 20})
        self.assertEqual(needs[win_location("Vanessa")], 28)
        self.assertEqual(needs[pvp_location("Vanessa", 12)], 28)  # PvP day N expects day N+1
        self.assertEqual(needs[pvp_location("Vanessa", 13)], 28)  # never past the last day

    def test_never_more_than_the_hero_has(self) -> None:
        needs = self.needs(13, {"day_10": 16, "last_day": 28, "diamond": 10, "legendary": 20}, lock_count=20)
        self.assertEqual(needs[win_location("Vanessa")], 20)

    def test_ten_wins_never_expects_less_than_day_10_with_a_short_max_day(self) -> None:
        """Found while double-checking (2026-09-30): max_day can be 5-9, and 10 wins then fell to 0 or half."""
        for max_day in (5, 7, 8, 9, 10):
            needs = self.needs(max_day, {"day_10": 16, "last_day": 28, "diamond": 10, "legendary": 20})
            self.assertEqual(needs[win_location("Vanessa")], 16, max_day)

    def test_seeds_from_before_the_climb_keep_their_flat_logic(self) -> None:
        needs = self.needs(13, {"day_10": 15, "diamond": 10, "legendary": 20})
        self.assertEqual({needs[day_location("Vanessa", d)] for d in range(10, 14)}, {15})
        self.assertEqual(needs[win_location("Vanessa")], 15)


class TestHardcoreLogicGenerates(BazaarTestBase):
    options = {"max_day": 16, "locked_cards_percent": 100, "logic_day_10_cards": 25, "logic_last_day_cards": 50,
               "max_monster_tier": "legendary"}

    def test_last_day_needs_more_than_day_10(self) -> None:
        hero = self.world.starting_hero
        items = self.world.lock_items[hero]
        self.collect_by_name([hero_item(h) for h in self.world.heroes])
        self.collect_by_name(items[:25])
        self.assertTrue(self.can_reach_location(day_location(hero, 10)))
        self.assertFalse(self.can_reach_location(day_location(hero, 16)))
        self.collect_by_name(items[25:50])
        self.assertTrue(self.can_reach_location(day_location(hero, 16)))


# Review 2026-09-30: these option mixes are allowed but generation failed on every seed; fit_logic now lowers logic
# per hero until it fits. Each class gets Archipelago's own fill/beatable tests.
TIGHT = {"locked_cards_percent": 100, "lock_common_cards": False, "sell_traps": 0, "lock_bypasses": 0,
         **NO_ENCOUNTER_LOCKS}
ONE_HERO = {"include_pygmalien": False, "include_dooley": False, "starting_hero": "vanessa"}


class TestTightOneHeroDaysOnly(BazaarTestBase):
    options = {**TIGHT, **ONE_HERO, "pvp_win_checks": False, "monster_checks": False}


class TestTightOneHeroPvPOnly(BazaarTestBase):
    options = {**TIGHT, **ONE_HERO, "monster_checks": False, "legendary_items": 0, "expedition_tickets": 0,
               "logic_day_10_cards": 18}


class TestTightOneHeroShortRun(BazaarTestBase):
    options = {**TIGHT, **ONE_HERO, "max_day": 5, "legendary_items": 0, "expedition_tickets": 0}


class TestTightThreeHeroesShortRun(BazaarTestBase):
    options = {**TIGHT, "max_day": 7, "pvp_win_checks": False, "monster_checks": False, "legendary_items": 0,
               "expedition_tickets": 0}

    def test_logic_was_lowered_to_fit(self) -> None:
        self.assertLess(self.world.logic["day_10"], 16)


class TestDuplicateAllHasNoFiller(BazaarTestBase):
    """User, 2026-09-30 ("1 a"): with duplicate_all_cards every spare slot holds another locked card as a pair."""
    options = {"duplicate_all_cards": True, "locked_cards_percent": 60}

    def test_pairs_not_filler(self) -> None:
        from ..items import FILLER_ITEMS
        names = [i.name for i in self.multiworld.itempool if i.player == self.player]
        self.assertFalse([n for n in names if n in FILLER_ITEMS])
        cards = {n for n in names if n in CARDS_BY_NAME}
        self.assertTrue(cards and all(names.count(n) == 2 for n in cards))


class TestEncounterLocks(BazaarTestBase):
    """Merchant/event locks (owner, 2026-10-02): 25% of those your heroes can meet, 5 starter merchants, 3 copies of
    Event Rarity Progression, none of them needed by logic."""

    def test_a_quarter_of_the_meetable_ones_are_locked(self) -> None:
        from ..data import ENCOUNTERS, EVENTS
        from ..items import encounter_item
        heroes = set(self.world.heroes) | {"Common"}
        meetable = [encounter_item(e) for e in ENCOUNTERS
                    if heroes & {h for g in e.guids for h in EVENTS[g]["heroes"]}]
        self.assertEqual(len(self.world.encounter_locks), (len(meetable) - 5) * 25 // 100)
        self.assertTrue(set(self.world.encounter_locks) <= set(meetable))

    def test_starters_are_low_tier_merchants_never_locked(self) -> None:
        from ..data import EVENTS
        from ..items import ENCOUNTERS_BY_ITEM
        self.assertEqual(len(self.world.starter_merchants), 5)
        self.assertFalse(set(self.world.starter_merchants) & set(self.world.encounter_locks))
        for name in self.world.starter_merchants:
            encounter = ENCOUNTERS_BY_ITEM[name]
            self.assertTrue(encounter.merchant)
            self.assertTrue(any(EVENTS[g]["tier"] in ("Bronze", "Silver", "Gold") for g in encounter.guids))

    def test_items_are_in_the_pool_and_never_progression(self) -> None:
        items = [i for i in self.multiworld.itempool if i.player == self.player]
        names = [i.name for i in items]
        self.assertEqual(names.count("Event Rarity Progression"), 3)
        for name in self.world.encounter_locks:
            self.assertEqual(names.count(name), 1)
        self.assertFalse([i.name for i in items if i.advancement
                          and (i.name == "Event Rarity Progression" or i.name in self.world.encounter_locks)])

    def test_slot_data_carries_them(self) -> None:
        from ..items import item_name_to_id
        data = self.world.fill_slot_data()
        self.assertEqual(data["encounter_locks"], sorted(item_name_to_id[n] for n in self.world.encounter_locks))
        self.assertEqual(data["event_rarity"], 3)
        self.assertTrue(data["exempt_expeditions"])


class TestEncounterLocksMeetOnlySeedHeroes(BazaarTestBase):
    """With only Vanessa, an event only other heroes can meet is never locked."""
    options = {"include_pygmalien": False, "include_dooley": False, "starting_hero": "vanessa",
               "locked_encounters_percent": 100}

    def test_only_vanessa_or_common_encounters(self) -> None:
        from ..data import EVENTS
        from ..items import ENCOUNTERS_BY_ITEM
        for name in self.world.encounter_locks:
            heroes = {h for g in ENCOUNTERS_BY_ITEM[name].guids for h in EVENTS[g]["heroes"]}
            self.assertTrue(heroes & {"Vanessa", "Common"}, name)


class TestEncounterData(unittest.TestCase):
    def test_lockable_encounters_exclude_level_ups_expeditions_and_never(self) -> None:
        """Level-up rewards never appear on the map; expeditions are locked through their tickets (owner, 2026-10-02)."""
        from ..data import ENCOUNTERS, EVENTS
        for encounter in ENCOUNTERS:
            for guid in encounter.guids:
                event = EVENTS[guid]
                self.assertFalse(event["level_up"] or event["expedition"] or event["spawns"] == "Never", event["name"])

    def test_ids_are_unique_and_in_their_own_range(self) -> None:
        from ..data import CARDS, ENCOUNTERS
        ids = [e.ap_id for e in ENCOUNTERS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(min(ids), max(c.ap_id for c in CARDS))

    def test_every_expedition_event_is_marked(self) -> None:
        from ..data import EVENTS
        marked = {e["name"] for e in EVENTS.values() if e["expedition"]}
        self.assertTrue({"Crash Site Expedition", "Temple Expedition", "Temple Vault", "Temple Reliquary"} <= marked)
