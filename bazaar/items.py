from typing import Dict, Iterable, List, Set, Tuple

from BaseClasses import Item

from .data import CARDS, CARDS_BY_NAME, ENCOUNTERS, HEROES, LEGENDARY_GUIDS, PACKS, Encounter, Pack, TICKET_GUIDS

GAME = "The Bazaar"
BASE_ID = 0xBA20000

FILLER_ITEMS = ["Spare Change", "Pile of Trinkets", "Merchant's Gossip"]
SELL_TRAP = "Sell Trap"  # sell a random item you hold within a few days, or checks get blocked
LOCK_BYPASS = "Lock Bypass"  # the next locked card you get is allowed for the rest of that run
LEGENDARY_ITEMS = "Legendary Items"  # unlocks every Legendary item
EXPEDITION_TICKETS = "Expedition Tickets"  # unlocks the expedition ticket cards
GROUP_ITEMS = {LEGENDARY_ITEMS: LEGENDARY_GUIDS, EXPEDITION_TICKETS: TICKET_GUIDS}
EVENT_RARITY = "Event Rarity Progression"  # 1st copy: Diamond merchants/events, 2nd: Legendary, more: Lock Bypasses


class BazaarItem(Item):
    game = GAME


def hero_item(hero: str) -> str:
    return f"Hero: {hero}"


def pack_item(pack_name: str) -> str:
    return f"Pack: {pack_name}"


def encounter_item(encounter: Encounter) -> str:
    return f"{'Merchant' if encounter.merchant else 'Event'}: {encounter.name}"


# Id layout (never reorder, only append):
#   BASE + 1..      hero unlocks, in data.HEROES order
#   BASE + 100..    legacy card packs (ap_id from the data file)
#   BASE + 200..    filler (BASE + 250 = Sell Trap, BASE + 260 = Lock Bypass)
#   BASE + 300..    group unlocks (Legendary Items, Expedition Tickets)
#   BASE + 310      Event Rarity Progression
#   BASE + 1000..   individual cards (ap_id from the data file)
#   BASE + 5000..   merchants and events (ap_id from the data file)
item_name_to_id: Dict[str, int] = {}
for i, hero in enumerate(HEROES):
    item_name_to_id[hero_item(hero)] = BASE_ID + 1 + i
PACKS_BY_ITEM: Dict[str, Pack] = {pack_item(p.name): p for p in PACKS}
for name, pack in PACKS_BY_ITEM.items():
    item_name_to_id[name] = BASE_ID + pack.ap_id
for i, name in enumerate(FILLER_ITEMS):
    item_name_to_id[name] = BASE_ID + 200 + i
item_name_to_id[SELL_TRAP] = BASE_ID + 250
item_name_to_id[LOCK_BYPASS] = BASE_ID + 260
for i, name in enumerate(GROUP_ITEMS):
    item_name_to_id[name] = BASE_ID + 300 + i
item_name_to_id[EVENT_RARITY] = BASE_ID + 310
for card in CARDS:
    if not card.ticket:  # tickets are only ever unlocked as a group
        item_name_to_id[card.name] = BASE_ID + card.ap_id
ENCOUNTERS_BY_ITEM: Dict[str, Encounter] = {encounter_item(e): e for e in ENCOUNTERS}
for name, encounter in ENCOUNTERS_BY_ITEM.items():
    item_name_to_id[name] = BASE_ID + encounter.ap_id

item_name_groups = {
    "Heroes": {hero_item(h) for h in HEROES},
    "Packs": {pack_item(p.name) for p in PACKS},
    "Cards": {c.name for c in CARDS if not c.ticket},
    "Groups": set(GROUP_ITEMS),
    "Merchants": {name for name, e in ENCOUNTERS_BY_ITEM.items() if e.merchant},
    "Events": {name for name, e in ENCOUNTERS_BY_ITEM.items() if not e.merchant},
    "Common Cards": {c.name for c in CARDS if c.hero == "Common" and not c.ticket},
    **{f"{h} Cards": {c.name for c in CARDS if c.hero == h and not c.ticket} for h in HEROES},
}


item_id_to_name: Dict[int, str] = {item_id: name for name, item_id in item_name_to_id.items()}
HERO_ITEM_IDS: Dict[int, str] = {item_name_to_id[hero_item(h)]: h for h in HEROES}
SELL_TRAP_ID = item_name_to_id[SELL_TRAP]
LOCK_BYPASS_ID = item_name_to_id[LOCK_BYPASS]
EVENT_RARITY_ID = item_name_to_id[EVENT_RARITY]
# item id -> the event templates it unlocks (every template of one merchant or event)
ENCOUNTER_UNLOCKS: Dict[int, Set[str]] = {item_name_to_id[name]: set(e.guids) for name, e in ENCOUNTERS_BY_ITEM.items()}
# item id -> the cards it unlocks (a card, a pack's cards, or a group's cards)
UNLOCKS: Dict[int, Set[str]] = {BASE_ID + c.ap_id: {c.guid} for c in CARDS if not c.ticket}
UNLOCKS.update({item_name_to_id[name]: set(p.cards) for name, p in PACKS_BY_ITEM.items()})
UNLOCKS.update({item_name_to_id[name]: set(guids) for name, guids in GROUP_ITEMS.items()})


def lock_items_by_hero(item_ids: Iterable[int]) -> Tuple[Dict[str, List[str]], List[str]]:
    """slot_data's lock item ids -> ({hero or "Common": item names}, group unlocks). Universal Tracker's rebuild and
    the client's hero list both read the seed's locks this way."""
    by_hero: Dict[str, List[str]] = {}
    groups: List[str] = []
    for item_id in item_ids:
        name = item_id_to_name[item_id]
        if name in GROUP_ITEMS:
            groups.append(name)
        else:
            hero = CARDS_BY_NAME[name].hero if name in CARDS_BY_NAME else PACKS_BY_ITEM[name].hero
            by_hero.setdefault(hero, []).append(name)
    return by_hero, groups

