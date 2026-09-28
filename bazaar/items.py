from typing import Dict

from BaseClasses import Item, ItemClassification

from .data import CARDS, HEROES, PACKS, PACKS_BY_ITEM

GAME = "The Bazaar"
BASE_ID = 0xBA20000

FILLER_ITEMS = ["Spare Change", "Pile of Trinkets", "Merchant's Gossip"]


class BazaarItem(Item):
    game = GAME


def hero_item(hero: str) -> str:
    return f"Hero: {hero}"


def pack_item(pack_name: str) -> str:
    return f"Pack: {pack_name}"


# Id layout (never reorder, only append):
#   BASE + 1..      hero unlocks, in data.HEROES order
#   BASE + 100..    legacy card packs (ap_id from the data file)
#   BASE + 200..    filler
#   BASE + 1000..   individual cards (ap_id from the data file)
item_name_to_id: Dict[str, int] = {}
for i, hero in enumerate(HEROES):
    item_name_to_id[hero_item(hero)] = BASE_ID + 1 + i
for pack in PACKS:
    item_name_to_id[pack_item(pack.name)] = BASE_ID + pack.ap_id
    PACKS_BY_ITEM[pack_item(pack.name)] = pack
for i, name in enumerate(FILLER_ITEMS):
    item_name_to_id[name] = BASE_ID + 200 + i
for card in CARDS:
    item_name_to_id[card.name] = BASE_ID + card.ap_id

item_name_groups = {
    "Heroes": {hero_item(h) for h in HEROES},
    "Packs": {pack_item(p.name) for p in PACKS},
    "Cards": {c.name for c in CARDS},
    "Common Cards": {c.name for c in CARDS if c.hero == "Common"},
    **{f"{h} Cards": {c.name for c in CARDS if c.hero == h} for h in HEROES},
}
