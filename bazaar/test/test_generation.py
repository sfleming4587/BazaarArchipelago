from ..items import hero_item
from ..locations import day_location, monster_location, pvp_location, win_location
from BaseClasses import CollectionState

from .bases import BazaarTestBase

ALL_DLC = ["Mak", "Stelle", "Jules", "Karnok", "The Dragons"]


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


class TestEverything(BazaarTestBase):
    options = {
        "owned_dlc_heroes": ALL_DLC,
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
        "excluded_heroes": ["Pygmalien", "Dooley"],
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
               "monster_checks": False}

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


class TestOwnHeroSwitches(BazaarTestBase):
    """DLC heroes are picked with on/off switches (user 2026-09-29); the old owned_dlc_heroes list still works."""
    options = {"own_karnok": True, "own_the_dragons": True, "starting_hero": "karnok"}

    def test_switched_on_heroes_are_in(self) -> None:
        self.assertEqual(set(self.world.heroes), {"Vanessa", "Pygmalien", "Dooley", "Karnok", "The Dragons"})

    def test_starting_hero_values_never_move(self) -> None:
        from ..options import StartingHero
        self.assertEqual(StartingHero.options, {"any": 0, "vanessa": 1, "pygmalien": 2, "dooley": 3, "mak": 4,
                                                "stelle": 5, "jules": 6, "karnok": 7, "the_dragons": 8})

    def test_deathlink_options_default_off(self) -> None:
        self.assertFalse(self.world.options.death_link)
        self.assertFalse(self.world.options.death_link_on_concede)


class TestExcludeHeroSwitches(BazaarTestBase):
    """Heroes are left out with on/off switches too (user 2026-09-29); the old excluded_heroes list still works."""
    options = {"own_karnok": True, "exclude_karnok": True, "exclude_dooley": True, "starting_hero": "vanessa"}

    def test_switched_off_heroes_are_out(self) -> None:
        self.assertEqual(set(self.world.heroes), {"Vanessa", "Pygmalien"})


class TestOnlyDayChecks(BazaarTestBase):
    """PvP and monster checks both off leaves each hero 7 checks that need no cards; logic used to expect 8 of its
    cards before day 8 and generation failed on some seeds (review 2026-09-29). The world lowers logic to fit."""
    options = {"pvp_win_checks": False, "monster_checks": False}

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
    options = {"owned_dlc_heroes": ["Mak", "Karnok"], "max_day": 12, "max_monster_tier": "diamond",
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
