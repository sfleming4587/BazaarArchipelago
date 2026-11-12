from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, FrozenSet, Iterable, List, Set, Tuple

from BaseClasses import Item, ItemClassification

from .data import CARDS, CARDS_BY_NAME, ENCOUNTERS, HEROES, LEGENDARY_GUIDS, PACKS, Encounter, Pack, TICKET_GUIDS

GAME = "The Bazaar"
BASE_ID = 0xBA20000
# What slot_data holds: raise it when a key is added or changes meaning. The client only plays seeds of its own
# version (owner, 2026-11-11: older seeds needn't keep working), so no setting needs an old-seed default.
SLOT_DATA_VERSION = 2

FILLER_ITEMS = ["Spare Change", "Pile of Trinkets", "Merchant's Gossip"]
SELL_TRAP = "Sell Trap"  # sell a random item you hold within a few days, or checks get blocked
LOCK_BYPASS = "Lock Bypass"  # the next locked card you get is allowed for the rest of that run
TRAP_SHIELD = "Trap Shield"  # blocks the next trap that would hit you, or clears one already running (owner 2026-11-10)
LEGENDARY_ITEMS = "Legendary Items"  # unlocks every Legendary item
EXPEDITION_TICKETS = "Expedition Tickets"  # progressive: each copy unlocks the next ticket (see unlock_steps)
GROUP_ITEMS = {LEGENDARY_ITEMS: LEGENDARY_GUIDS, EXPEDITION_TICKETS: TICKET_GUIDS}
# The tickets in the order progressive Expedition Tickets unlock them: the order Tempo added them (owner, 2026-11-09:
# Crash Site, Temple, then Tiny World). A new ticket gets the next ap_id, so it goes last by itself.
TICKETS = sorted((c for c in CARDS if c.ticket), key=lambda c: c.ap_id)
TICKET_ITEMS = [c.name for c in TICKETS]  # their own items when expedition_ticket_unlocks is "separate"
# Owner, 2026-11-09: the Sizeinator unlocks with the Tiny World Ticket by default, or with Legendary Items (hard)
SIZEINATOR = "7b30db1a-80c8-4889-ae2f-12b0ad047796"
TINY_WORLD_TICKET = "24dc340b-bb3d-4c9b-8715-a807c0c06a8c"
EVENT_RARITY = "Event Rarity Progression"  # 1st copy: Diamond merchants/events, 2nd: Legendary, more: Lock Bypasses




@dataclass(frozen=True)
class Counted:
    """A trap or buff whose copies in the pool are its own count option. A new one is one row in COUNTED (plus its
    option): its id, classification, pool count and pop-up all come from here."""
    name: str
    offset: int  # its id is BASE_ID + offset (never change one)
    classification: ItemClassification
    option: str  # the BazaarOptions field holding how many go in the pool


# in pool order (changing the order changes generated seeds)
COUNTED = (Counted(SELL_TRAP, 250, ItemClassification.trap, "sell_traps"),
           Counted(LOCK_BYPASS, 260, ItemClassification.useful, "lock_bypasses"),
           Counted(TRAP_SHIELD, 270, ItemClassification.useful, "trap_shields"))
TRAPS = [c.name for c in COUNTED if c.classification == ItemClassification.trap]  # what a Trap Shield blocks


class BazaarItem(Item):
    game = GAME


def hero_item(hero: str) -> str:
    return f"Hero: {hero}"


def pack_item(pack_name: str) -> str:
    return f"Pack: {pack_name}"


def encounter_item(encounter: Encounter) -> str:
    return f"{'Merchant' if encounter.merchant else 'Event'}: {encounter.name}"


# Level-up events with their own lock item (owner, 2026-11-11: "lock the first level up event Shiny! as its own
# check"; "treat it like a locked merchant in all ways"). They behave like merchant/event locks (ENCOUNTER_UNLOCKS)
# and count as power items. A new one is one more row. ⚠️ Append only, never change an offset (it is the item id).
@dataclass(frozen=True)
class LevelUp:
    name: str
    offset: int  # its item id is BASE_ID + 320 + offset
    guids: Tuple[str, ...]  # its templates
    tier: str  # its rarity, for the all-locked let-through (the game's StartingTier)

    @property
    def item(self) -> str:
        return f"Level Up: {self.name}"


LEVEL_UPS = (LevelUp("Shiny!", 0, ("e286d583-65b1-4fc3-b76e-c182c5c34604",), "Bronze"),)  # pick 1 of 3 small enchanted
LEVEL_UP_ITEMS = [level_up.item for level_up in LEVEL_UPS]
LEVEL_UP_TIERS: Dict[str, str] = {guid: level_up.tier for level_up in LEVEL_UPS for guid in level_up.guids}


# Id layout (never reorder, only append):
#   BASE + 1..      hero unlocks, in data.HEROES order
#   BASE + 100..    legacy card packs, 150.. custom card packs (ap_id from the data files)
#   BASE + 200..    filler; BASE + 250.. traps and buffs (COUNTED)
#   BASE + 300..    group unlocks (Legendary Items, Expedition Tickets)
#   BASE + 310      Event Rarity Progression
#   BASE + 320..    level-up event unlocks (LEVEL_UPS)
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
for counted in COUNTED:
    item_name_to_id[counted.name] = BASE_ID + counted.offset
for i, name in enumerate(GROUP_ITEMS):
    item_name_to_id[name] = BASE_ID + 300 + i
item_name_to_id[EVENT_RARITY] = BASE_ID + 310
for level_up in LEVEL_UPS:
    item_name_to_id[level_up.item] = BASE_ID + 320 + level_up.offset
for card in CARDS:  # a ticket is its own item only with expedition_ticket_unlocks "separate"
    item_name_to_id[card.name] = BASE_ID + card.ap_id
ENCOUNTERS_BY_ITEM: Dict[str, Encounter] = {encounter_item(e): e for e in ENCOUNTERS}
for name, encounter in ENCOUNTERS_BY_ITEM.items():
    item_name_to_id[name] = BASE_ID + encounter.ap_id

item_name_groups = {
    "Heroes": {hero_item(h) for h in HEROES},
    "Packs": {pack_item(p.name) for p in PACKS},
    "Cards": {c.name for c in CARDS if not c.ticket},
    "Groups": set(GROUP_ITEMS),
    "Tickets": set(TICKET_ITEMS),
    "Merchants": {name for name, e in ENCOUNTERS_BY_ITEM.items() if e.merchant},
    "Events": {name for name, e in ENCOUNTERS_BY_ITEM.items() if not e.merchant},
    "Level Ups": set(LEVEL_UP_ITEMS),
    "Common Cards": {c.name for c in CARDS if c.hero == "Common" and not c.ticket},
    **{f"{h} Cards": {c.name for c in CARDS if c.hero == h and not c.ticket} for h in HEROES},
}


item_id_to_name: Dict[int, str] = {item_id: name for name, item_id in item_name_to_id.items()}
HERO_ITEM_IDS: Dict[int, str] = {item_name_to_id[hero_item(h)]: h for h in HEROES}
SELL_TRAP_ID = item_name_to_id[SELL_TRAP]
LOCK_BYPASS_ID = item_name_to_id[LOCK_BYPASS]
TRAP_SHIELD_ID = item_name_to_id[TRAP_SHIELD]
EVENT_RARITY_ID = item_name_to_id[EVENT_RARITY]
# item id -> the event templates it unlocks (every template of one merchant or event, or of a level-up event)
ENCOUNTER_UNLOCKS: Dict[int, Set[str]] = {item_name_to_id[name]: set(e.guids) for name, e in ENCOUNTERS_BY_ITEM.items()}
ENCOUNTER_UNLOCKS.update({item_name_to_id[level_up.item]: set(level_up.guids) for level_up in LEVEL_UPS})
# item id -> the cards it unlocks (a card, a pack's cards, or a group's cards)
UNLOCKS: Dict[int, Set[str]] = {BASE_ID + c.ap_id: {c.guid} for c in CARDS}
UNLOCKS.update({item_name_to_id[name]: set(p.cards) for name, p in PACKS_BY_ITEM.items()})
UNLOCKS.update({item_name_to_id[name]: set(guids) for name, guids in GROUP_ITEMS.items()})
# every item that unlocks something (cards, a hero, a merchant/event, Event Rarity Progression): the client's
# UNLOCKED pop-up. SINGLE ones unlock one thing on its own (a card - a separate ticket too - or one merchant/event/
# level-up event): their "Locked behind" line would only name the thing itself, so it isn't shown (owner, 2026-11-11)
UNLOCK_IDS = frozenset(UNLOCKS) | frozenset(HERO_ITEM_IDS) | frozenset(ENCOUNTER_UNLOCKS) | {EVENT_RARITY_ID}
SINGLE_UNLOCK_IDS = frozenset(BASE_ID + c.ap_id for c in CARDS) | frozenset(ENCOUNTER_UNLOCKS)
COUNTED_IDS = frozenset(item_name_to_id[c.name] for c in COUNTED)
COUNTED_BY_NAME: Dict[str, Counted] = {c.name: c for c in COUNTED}


def base_classification(name: str) -> ItemClassification:
    """An item's classification before the seed's logic: the world makes any unlock a check needs progression
    (BazaarWorld.gating)."""
    if name in FILLER_ITEMS:
        return ItemClassification.filler
    if name in COUNTED_BY_NAME:
        return COUNTED_BY_NAME[name].classification
    if name == EXPEDITION_TICKETS or name in TICKET_ITEMS:  # always shown as important (owner 2026-11-10)
        return ItemClassification.progression
    if name in GROUP_ITEMS or name == EVENT_RARITY or name in ENCOUNTERS_BY_ITEM or name in LEVEL_UP_ITEMS \
            or (name in CARDS_BY_NAME and CARDS_BY_NAME[name].hero == "Common"):
        return ItemClassification.useful  # never required by logic: a choice screen always has a way on
    return ItemClassification.progression


ITEM_CLASSIFICATION: Dict[str, ItemClassification] = {name: base_classification(name) for name in item_name_to_id}
# Plentiful Items' spare copies (owner, 2026-11-10): hero unlocks, packs, merchant/event unlocks and tickets. Items with
# their own count option (Legendary Items, Event Rarity Progression, COUNTED, Duplicate Cards) and single cards never.
PLENTIFUL = frozenset({hero_item(h) for h in HEROES} | set(PACKS_BY_ITEM) | set(ENCOUNTERS_BY_ITEM)
                      | set(LEVEL_UP_ITEMS) | {EXPEDITION_TICKETS, *TICKET_ITEMS})


@lru_cache(maxsize=None)
def unlock_steps(tickets: str, sizeinator: str) -> Dict[int, Tuple[FrozenSet[str], ...]]:
    """Item id -> what each copy of it unlocks, in order: the first copy received unlocks steps[0], the second
    steps[1], and so on. Everything has one step except progressive Expedition Tickets. The world (what goes in the
    pool) and the client (what's locked now) both read this, so they never disagree.
    tickets: the seed's expedition_ticket_unlocks ("progressive", "separate", "off"). sizeinator:
    "with_tiny_world_ticket" or "legendary_items"."""
    with_ticket = sizeinator == "with_tiny_world_ticket"

    def step(guids) -> FrozenSet[str]:
        return frozenset(guids) | ({SIZEINATOR} if with_ticket and TINY_WORLD_TICKET in guids else set())
    steps = {item_id: (frozenset(guids),) for item_id, guids in UNLOCKS.items()}
    steps[item_name_to_id[LEGENDARY_ITEMS]] = (frozenset(LEGENDARY_GUIDS - {SIZEINATOR} if with_ticket
                                                         else LEGENDARY_GUIDS),)
    for ticket in TICKETS:
        steps[BASE_ID + ticket.ap_id] = (step({ticket.guid}),)
    steps[item_name_to_id[EXPEDITION_TICKETS]] = tuple(step({t.guid}) for t in TICKETS) if tickets == "progressive" \
        else (step(TICKET_GUIDS),)
    return steps


def item_weight(name: str) -> int:
    """How many cards a lock item stands for in the card logic: a pack its cards, anything else 1 (owner 2026-11-10:
    a pack counts as its 10 cards)."""
    return len(PACKS_BY_ITEM[name].cards) if name in PACKS_BY_ITEM else 1


# Power items (owner, 2026-11-10): the unlocks late Diamond/Legendary monster checks want, each counted up to what it
# can really unlock - 3 progressive Expedition Tickets (or each separate ticket once), the first Legendary Items, the
# first 2 Event Rarity Progression (later copies are Lock Bypasses), each level-up event unlock (owner, 2026-11-11:
# Shiny! "should be added to the List"). Spare copies never count, on either side.
POWER_CAPS: Dict[str, int] = {EXPEDITION_TICKETS: len(TICKETS), LEGENDARY_ITEMS: 1, EVENT_RARITY: 2,
                              **{name: 1 for name in TICKET_ITEMS}, **{name: 1 for name in LEVEL_UP_ITEMS}}
# The pop-up rainbow (owner, 2026-11-11): unlocks of more than one thing, and EVERY power item ("The rainbow shows up
# for EVERY POWER ITEM. So shiny is included") - never a single card or merchant/event otherwise
GOOD_UNLOCK_IDS = (UNLOCK_IDS - SINGLE_UNLOCK_IDS) | frozenset(item_name_to_id[name] for name in POWER_CAPS)


def power_total(group_items: Iterable[str], event_rarity: int) -> int:
    """How many power items a seed holds: its group unlocks (tickets, Legendary Items) and level-up event unlocks,
    plus Event Rarity copies."""
    groups = set(group_items)
    return sum(cap for name, cap in POWER_CAPS.items() if name in groups) + min(event_rarity, POWER_CAPS[EVENT_RARITY])


def power_held(count) -> int:
    """How many power items `count(name) -> copies received` adds up to, capped per item."""
    return sum(min(cap, count(name)) for name, cap in POWER_CAPS.items())


def lock_items_by_hero(item_ids: Iterable[int]) -> Tuple[Dict[str, List[str]], List[str]]:
    """slot_data's lock item ids -> ({hero or "Common": item names}, group unlocks). Universal Tracker's rebuild and
    the client's hero list both read the seed's locks this way."""
    by_hero: Dict[str, List[str]] = {}
    groups: List[str] = []
    for item_id in item_ids:
        name = item_id_to_name[item_id]
        if name in GROUP_ITEMS or name in TICKET_ITEMS:
            groups.append(name)
        else:
            hero = CARDS_BY_NAME[name].hero if name in CARDS_BY_NAME else PACKS_BY_ITEM[name].hero
            by_hero.setdefault(hero, []).append(name)
    return by_hero, groups

