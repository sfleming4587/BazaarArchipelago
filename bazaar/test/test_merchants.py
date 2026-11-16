import unittest

from ..data import CARDS, MERCHANT_DATA
from ..merchants import can_stock, possible_stock


def merchant(guid: str) -> int:
    """A merchant's Item Guide key (its lock, shop_guide.MERCHANTS) from one of its templates' guid."""
    from ..data import ENCOUNTER_OF
    return ENCOUNTER_OF[guid].ap_id


# merchants by their game guid (the live, non-tutorial template)
HERMA = "2708055d-a8be-4c2f-a8d6-574e884a254e"
CHRONOS = "b1288f12-2cf9-4473-a43e-4dd521703990"
CURIO = "c6cffe25-8e94-4a7b-a821-3e3c7093333b"
DOOLEY_MERCHANT = "4580fb31-b2ea-4f9b-9ab9-2979602f83d8"  # the merchant called Dooley (met by every other hero)
DRAGONS_MERCHANT = "85cdd52b-12c2-4b64-b308-a5788f791b81"  # the merchant called The Dragons (the game's Hero8)
STICKYBEANS = "d0276b47-be8a-4bbc-ab55-9f92b352480a"
ANTIQUARIAN = "e840f7a3-0a04-455d-852c-286dc5011efc"  # The Antiquarian

MEDIUM_ITEMS = {"Groups": [{"Filters": [{"$type": "TSpawnFilterQuery", "Constraints": {
    "$type": "ConstraintAnd", "Constraints": [
        {"$type": "ConstraintSize", "Sizes": ["Medium"], "IsNot": False},
        {"$type": "ConstraintCardType", "Types": ["Item"], "IsNot": False}]}}]}]}


class TestMerchants(unittest.TestCase):
    def test_size_filter(self) -> None:
        stock = possible_stock(MEDIUM_ITEMS, "Vanessa", CARDS)
        self.assertTrue(stock)
        self.assertTrue(all(c.size == "Medium" and c.hero in ("Vanessa", "Common") for c in stock))

    def test_upgrade_merchants_sell_nothing_new(self) -> None:
        upgrade = {"Groups": [{"Filters": [{"$type": "TSpawnFilterUpgrade", "CardType": "Item"}]}]}
        self.assertFalse(any(can_stock(upgrade, c) for c in CARDS))

    def test_real_merchants_load(self) -> None:
        self.assertGreater(len(MERCHANT_DATA), 50)
        self.assertTrue(any(possible_stock(m["stock"], "Dooley", CARDS) for m in MERCHANT_DATA.values()))


class TestItemChoices(unittest.TestCase):
    """Every event option that lays items out is warned about (user 2026-09-28: Hidden Lake had no overlay)."""

    FIGHT_THE_BEAST, MIDDLE_PATH = "8a452702-604e-4e26-941e-619ba6396c36", "6742a4ff-e5d4-4039-9003-ac3417c3d7de"
    FLAME_SIGIL = "904ffad8-86e3-4e3b-8a26-723604cc4f0e"

    def offer(self, guid: str) -> dict:
        from ..data import OFFER_DATA
        return OFFER_DATA[guid]

    def test_deal_nested_in_a_combined_action_is_found(self) -> None:
        # Hidden Lake > "Fight the Beast" deals Sigils inside a TActionAnd, which the data used to miss
        guids = {c.guid for c in possible_stock(self.offer(self.FIGHT_THE_BEAST)["stock"], "Karnok", CARDS)}
        self.assertIn(self.FLAME_SIGIL, guids)

    def test_pick_several_deals_are_warned_too(self) -> None:
        self.assertTrue(possible_stock(self.offer(self.MIDDLE_PATH)["stock"], "Karnok", CARDS))

    def test_deal_that_ignores_heroes_includes_other_heroes_cards(self) -> None:
        from ..data import OFFER_DATA
        offer = next(o for o in OFFER_DATA.values() if "TSpawnBehaviorIgnoreHero" in str(o["stock"]))
        heroes = {c.hero for c in possible_stock(offer["stock"], "Vanessa", CARDS)}
        self.assertTrue(heroes - {"Vanessa", "Common"})



class TestOnlyTheVisitingHerosCards(unittest.TestCase):
    """Owner, 2026-11-13: "Herma ONLY OFFERS ITEMS FOR THE HERO. no neutral items, no other heros"; "curio sells
    'Junk' items which are neutral"; "Dooley would sell dooley items"; some merchants offer "items from literally
    anyone, like relics or toys or apparel"."""

    def pool(self, guid: str, hero: str) -> list:
        from ..data import SHOP_CARDS
        from ..shop_guide import merchant_pool
        return merchant_pool(merchant(guid), hero, SHOP_CARDS)

    def test_a_hero_pool_merchant_deals_only_your_heros_cards(self) -> None:
        for guid in (HERMA, CHRONOS):
            cards = self.pool(guid, "Jules")
            self.assertTrue(cards)
            self.assertEqual({c.hero for c in cards}, {"Jules"}, guid)
        guids = {c.guid for c in self.pool(HERMA, "Jules")}
        # the owner's examples: Gland, Starfish, Junkyard Repairbot
        for neutral in ("638a6b50-7803-4da5-9514-ca0627fd7b5f", "52f1b056-9af2-4e32-8c09-6a93d7b7b68f",
                        "51696368-e409-4771-8baf-22c6da533cd8"):
            self.assertNotIn(neutral, guids)

    def test_a_merchant_naming_its_cards_deals_them_to_anyone(self) -> None:
        for hero in ("Jules", "Vanessa"):
            self.assertEqual({c.hero for c in self.pool(CURIO, hero)}, {"Common"})
        self.assertEqual({c.hero for c in self.pool(DOOLEY_MERCHANT, "Dooley")}, {"Dooley"})
        self.assertTrue(self.pool(DRAGONS_MERCHANT, "The Dragons"))  # the game calls them Hero8

    def test_an_any_hero_merchant_still_deals_anyones(self) -> None:
        self.assertGreater(len({c.hero for c in self.pool(ANTIQUARIAN, "Jules")}), 2)


class TestMerchantsWhoDealOthersCards(unittest.TestCase):
    """Owner, 2026-11-13 (audit of every merchant): "fix 1/2" - the hero merchants (met by every hero but their own)
    and Stickybeans (every card but yours) listed nothing / only yours; "Yes bronze only" for Curio."""

    def listed(self, guid: str, playing: str) -> list:
        from ..data import SHOP_CARDS
        from ..shop_guide import ANY, default_hero, guide_cards
        key = merchant(guid)
        return guide_cards(SHOP_CARDS, default_hero(key, playing), key, "", ANY, ANY, playing=playing)

    def test_a_hero_merchant_lists_its_heros_cards_to_another_hero(self) -> None:
        from ..data import EVENTS
        self.assertNotIn("Dooley", EVENTS[DOOLEY_MERCHANT]["heroes"])  # you meet it as anyone but Dooley
        self.assertEqual({c.hero for c in self.listed(DOOLEY_MERCHANT, "Jules")}, {"Dooley"})

    def test_stickybeans_deals_every_card_but_yours(self) -> None:
        from ..data import SHOP_CARDS
        from ..shop_guide import merchant_pool
        heroes = {c.hero for c in merchant_pool(merchant(STICKYBEANS), "Jules", SHOP_CARDS)}
        self.assertNotIn("Jules", heroes)
        self.assertGreater(len(heroes), 5)

    def test_curio_only_cards_that_come_in_bronze(self) -> None:
        cards = self.listed(CURIO, "Jules")
        self.assertTrue(cards)
        self.assertTrue(all("Bronze" in (c.tiers or (c.tier,)) for c in cards))
        self.assertTrue(all(c.hero == "Common" for c in cards))
