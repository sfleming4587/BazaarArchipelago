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
