import unittest

from ..data import CARDS, MERCHANT_DATA
from ..merchants import can_stock, possible_stock

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

    def offer(self, name: str) -> dict:
        from ..data import OFFER_DATA
        return next(o for o in OFFER_DATA.values() if o["name"] == name)

    def test_deal_nested_in_a_combined_action_is_found(self) -> None:
        # Hidden Lake > "Fight the Beast" deals Sigils inside a TActionAnd, which the extractor used to miss
        names = {c.name for c in possible_stock(self.offer("Fight the Beast")["stock"], "Karnok", CARDS)}
        self.assertIn("Flame Sigil", names)

    def test_pick_several_deals_are_warned_too(self) -> None:
        self.assertTrue(possible_stock(self.offer("Walk the Middle Path")["stock"], "Karnok", CARDS))

    def test_deal_that_ignores_heroes_includes_other_heroes_cards(self) -> None:
        from ..data import OFFER_DATA
        offer = next(o for o in OFFER_DATA.values() if "TSpawnBehaviorIgnoreHero" in str(o["stock"]))
        heroes = {c.hero for c in possible_stock(offer["stock"], "Vanessa", CARDS)}
        self.assertTrue(heroes - {"Vanessa", "Common"})

