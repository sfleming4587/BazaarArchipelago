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


def _load() -> dict:
    # pkgutil works both from a source checkout and from inside a zipped .apworld
    return json.loads(pkgutil.get_data(__name__, "bazaar_data.json").decode("utf-8"))


_raw = _load()

GAME_VERSION: str = _raw.get("game_version", "unknown")  # The Bazaar build this data was extracted from
HEROES: List[str] = _raw["heroes"]
BASE_HEROES = ("Vanessa", "Pygmalien", "Dooley")
DLC_HEROES = tuple(h for h in HEROES if h not in BASE_HEROES)


def hero_key(hero: str) -> str:
    """How a hero appears in option names/values and file names: "The Dragons" -> "the_dragons"."""
    return hero.lower().replace(" ", "_")

CARDS: List[Card] = [Card(c["guid"], c["ap_id"], c["name"], c["hero"], c["tier"], c["size"], tuple(c["tags"]),
                          c["shop"], tuple(c.get("hidden_tags", ())), tuple(c.get("enchants", ())),
                          tuple(c.get("tiers", ())), c.get("ticket", False)) for c in _raw["cards"]]
PACKS: List[Pack] = [Pack(p["key"], p["ap_id"], p["name"], p["hero"], tuple(p["cards"])) for p in _raw["packs"]]

# encounter guid -> {"name": ..., "stock": SpawnContext}; taking an item inside one of these costs gold
MERCHANT_DATA: Dict[str, dict] = {m["guid"]: m for m in _raw.get("merchants", [])}
# events / steps that let you take an item for free: guid -> {"name": ..., "stock": SpawnContext}
OFFER_DATA: Dict[str, dict] = {m["guid"]: m for m in _raw.get("offers", [])}
EVENT_NAMES: Dict[str, str] = {e["guid"]: e["name"] for e in _raw.get("events", [])}  # every event, merchants too
# every event template: guid -> {"name", "tier", "heroes", "level_up", "expedition", ...}
EVENTS: Dict[str, dict] = {e["guid"]: e for e in _raw.get("events", [])}
ENCOUNTERS: List[Encounter] = [Encounter(e["ap_id"], e["name"], tuple(e["guids"]), e["merchant"])
                               for e in _raw.get("encounters", [])]

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
LEGENDARY_GUIDS = frozenset(c.guid for c in CARDS if c.shop and c.tier == "Legendary")
TICKET_GUIDS = frozenset(c.guid for c in CARDS if c.ticket)

CARDS_BY_NAME: Dict[str, Card] = {c.name: c for c in CARDS}
CARDS_BY_GUID: Dict[str, Card] = {c.guid: c for c in CARDS}
# card names are item names: two cards with one name would silently share an item id (the extractor prevents it)
assert len(CARDS_BY_NAME) == len(CARDS), "two cards share a name - rerun tools/extract_data.py"
