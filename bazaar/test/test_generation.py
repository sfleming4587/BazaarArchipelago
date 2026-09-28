from ..items import hero_item
from ..locations import day_location, win_location
from .bases import BazaarTestBase

ALL_DLC = ["Mak", "Stelle", "Jules", "Karnok", "The Dragons"]


class TestDefaults(BazaarTestBase):
    def test_base_heroes_only(self) -> None:
        self.assertEqual(self.world.heroes, ["Vanessa", "Pygmalien", "Dooley"])
        self.assertEqual(self.world.goal_count, 3)

    def test_location_count(self) -> None:
        real = [loc for loc in self.multiworld.get_locations(self.player) if loc.address is not None]
        self.assertEqual(len(real), 3 * (15 + 1))

    def test_starting_hero_is_precollected_not_in_pool(self) -> None:
        start = hero_item(self.world.starting_hero)
        self.assertIn(start, [i.name for i in self.multiworld.precollected_items[self.player]])
        self.assertNotIn(start, [i.name for i in self.multiworld.itempool if i.player == self.player])

    def test_early_days_need_only_the_hero(self) -> None:
        hero = self.world.starting_hero
        for day in range(1, 6):
            self.assertTrue(self.can_reach_location(day_location(hero, day)))

    def test_late_days_need_cards(self) -> None:
        hero = self.world.starting_hero
        if self.world.lock_items.get(hero):
            self.assertFalse(self.can_reach_location(day_location(hero, 15)))
            self.assertFalse(self.can_reach_location(win_location(hero)))
            self.collect_by_name(self.world.lock_items[hero])
            self.assertTrue(self.can_reach_location(win_location(hero)))


class TestEverything(BazaarTestBase):
    options = {
        "owned_dlc_heroes": ALL_DLC,
        "legacy_card_packs": True,
        "heroes_required": 8,
        "starting_hero": "the_dragons",
        "locked_cards": 200,
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
        "locked_cards": 400,
        "legacy_card_packs": True,
        "heroes_required": 5,
    }

    def test_clamped(self) -> None:
        self.assertEqual(self.world.heroes, ["Vanessa"])
        self.assertEqual(self.world.goal_count, 1)
        pool = [i for i in self.multiworld.itempool if i.player == self.player]
        self.assertEqual(len(pool), 6)


class TestNoLocks(BazaarTestBase):
    options = {"locked_cards": 0, "lock_common_cards": False}

    def test_only_heroes_and_filler(self) -> None:
        names = [i.name for i in self.multiworld.itempool if i.player == self.player]
        self.assertEqual(sum(n.startswith("Hero: ") for n in names), 2)
        self.assertEqual(len(names), 48)
