import json
import pkgutil
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Card:
    guid: str
    ap_id: int
    name: str
    hero: str  # a hero name, or "Common"
    tier: str
    size: str
    tags: Tuple[str, ...]
    shop: bool  # can appear in shops (only these are picked as individual locks)
    hidden_tags: Tuple[str, ...] = ()
    enchants: Tuple[str, ...] = ()
    tiers: Tuple[str, ...] = ()
    ticket: bool = False  # an expedition ticket (locked as the "Expedition Tickets" group)


@dataclass(frozen=True)
class Encounter:
    """A merchant or event that can be locked: one lock item for every template of it (see docs/ENCOUNTER-LOCKS.md)."""
    ap_id: int
    name: str
    guids: Tuple[str, ...]
    merchant: bool  # a shop: entering is fine, what you buy there counts as locked


@dataclass(frozen=True)
class Pack:
    key: str
    ap_id: int
    name: str
    hero: str
    cards: Tuple[str, ...]  # card guids
    custom: bool = False  # hand-made (custom_packs.json), not one of the game's original expansions


def _load(name: str = "bazaar_data.json") -> dict:
    # pkgutil works both from a source checkout and from inside a zipped .apworld
    return json.loads(pkgutil.get_data(__name__, name).decode("utf-8"))


_raw = _load()

GAME_VERSION: str = _raw.get("game_version", "unknown")  # The Bazaar build this data matches
HEROES: List[str] = _raw["heroes"]
# The game's hero codes (its EHero enum, BazaarGameShared.dll: the log's "Changing EHero to", merchant filters, Random's
# exclusions) -> the heroes above: only Hero8 differs ("The Dragons"). Kept in bazaar_data.json, the one place the
# mapping is kept (2026-11-16: it was copied three times).
HERO_CODES: Dict[str, str] = _raw["hero_codes"]


def hero_of_code(code: str) -> str:
    """The hero a game hero code stands for (a code the data doesn't know passes through as it is)."""
    return HERO_CODES.get(code, code)


BASE_HEROES = ("Vanessa", "Pygmalien", "Dooley")
DLC_HEROES = tuple(h for h in HEROES if h not in BASE_HEROES)


def hero_key(hero: str) -> str:
    """How a hero appears in option names/values and file names: "The Dragons" -> "the_dragons"."""
    return hero.lower().replace(" ", "_")

CARDS: List[Card] = [Card(c["guid"], c["ap_id"], c["name"], c["hero"], c["tier"], c["size"], tuple(c["tags"]),
                          c["shop"], tuple(c.get("hidden_tags", ())), tuple(c.get("enchants", ())),
                          tuple(c.get("tiers", ())), c.get("ticket", False)) for c in _raw["cards"]]
# Legacy packs are in the data file; custom packs are hand-made and live in their own file, so a data update
# never touches them (see docs/CARD-PACKS.md). Both share the pack item range: legacy 100.., custom 150..
PACKS: List[Pack] = [Pack(p["key"], p["ap_id"], p["name"], p["hero"], tuple(p["cards"])) for p in _raw["packs"]]
PACKS += [Pack(p["key"], p["ap_id"], p["name"], p["hero"], tuple(c["guid"] for c in p["cards"]), custom=True)
          for p in _load("custom_packs.json")["packs"]]

# encounter guid -> {"name": ..., "stock": SpawnContext}; taking an item inside one of these costs gold
MERCHANT_DATA: Dict[str, dict] = {m["guid"]: m for m in _raw.get("merchants", [])}
# events / steps that let you take an item for free: guid -> {"name": ..., "stock": SpawnContext}
OFFER_DATA: Dict[str, dict] = {m["guid"]: m for m in _raw.get("offers", [])}
EVENT_NAMES: Dict[str, str] = {e["guid"]: e["name"] for e in _raw.get("events", [])}  # every event, merchants too
# every event template: guid -> {"name", "tier", "heroes", "level_up", "expedition", ...}
EVENTS: Dict[str, dict] = {e["guid"]: e for e in _raw.get("events", [])}
ENCOUNTERS: List[Encounter] = [Encounter(e["ap_id"], e["name"], tuple(e["guids"]), e["merchant"])
                               for e in _raw.get("encounters", [])]
# each merchant/event template -> its lockable encounter (every copy of it, tutorial ones too, is one encounter)
ENCOUNTER_OF: Dict[str, Encounter] = {g: e for e in ENCOUNTERS for g in e.guids}

TIERS = ("Bronze", "Silver", "Gold", "Diamond", "Legendary")

# hour-3 monster encounters: guid -> {"name", "tier", "level"}
MONSTERS: Dict[str, dict] = {m["guid"]: m for m in _raw.get("monsters", [])}


# First day each rarity can be offered as the hour-3 monster. The server decides this; it isn't in the local
# game data (a monster's "level" is NOT its day: a level-4 Gold monster showed up on day 2).
# Verified by the user in game 2026-09-28: Silver day 1, Gold day 2, Diamond day 3, first Legendary (Lich) day 6.
FIRST_DAY_OF_TIER = {"Bronze": 1, "Silver": 1, "Gold": 2, "Diamond": 3, "Legendary": 6}


def tiers_on_day(day: int, highest: str) -> List[str]:
    """The monster rarities you can meet on a day, up to and including `highest`."""
    return [tier for tier in TIERS[:TIERS.index(highest) + 1] if FIRST_DAY_OF_TIER[tier] <= day]


# Cards unlocked together by one group item.
SHOP_CARDS = [c for c in CARDS if c.shop]  # cards a shop can sell (the Item Guide's list, the menu's card counts)
LEGENDARY_GUIDS = frozenset(c.guid for c in CARDS if c.shop and c.tier == "Legendary")
TICKET_GUIDS = frozenset(c.guid for c in CARDS if c.ticket)
# item guid -> the lockable card it always spawns (Temporary Shelter -> Scrap); random spawns aren't listed
FIXED_SPAWNS: Dict[str, Tuple[str, ...]] = {k: tuple(v) for k, v in _raw.get("fixed_spawns", {}).items()}
# Every card of every type, by guid (bazaar_data.json's catalog, 2026-11-13): the facts a feature may need beyond `cards`
CATALOG: Dict[str, dict] = {c["guid"]: c for c in _raw.get("catalog", [])}
# Cards that deal random cards when sold -> how many one sale deals (the catalog's sold_deals: the game's own spawn
# Limit, 2026-11-16): every "<Merchant>'s Package" (1), Shipment (its Custom_0 attribute: 3)... A card that always
# deals the same card (FIXED_SPAWNS: Temporary Shelter's 2 Scrap, Colossal Popsicle's Icicles) isn't one: what it
# deals is known, and only that is free.
SOLD_DEALS: Dict[str, int] = {g: c["sold_deals"] for g, c in CATALOG.items()
                              if c.get("sold_deals") and g not in FIXED_SPAWNS}

CARDS_BY_NAME: Dict[str, Card] = {c.name: c for c in CARDS}
CARDS_BY_GUID: Dict[str, Card] = {c.guid: c for c in CARDS}
# card names are item names: two cards with one name would silently share an item id (the data file never has two)
assert len(CARDS_BY_NAME) == len(CARDS), "two cards share a name - fix the data file"
