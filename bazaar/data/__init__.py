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

CARDS: List[Card] = [Card(c["guid"], c["ap_id"], c["name"], c["hero"], c["tier"], c["size"], tuple(c["tags"]),
                          c["shop"], tuple(c.get("hidden_tags", ())), tuple(c.get("enchants", ())),
                          tuple(c.get("tiers", ())), c.get("ticket", False)) for c in _raw["cards"]]
PACKS: List[Pack] = [Pack(p["key"], p["ap_id"], p["name"], p["hero"], tuple(p["cards"])) for p in _raw["packs"]]

# encounter guid -> {"name": ..., "stock": SpawnContext}; taking an item inside one of these costs gold
MERCHANT_DATA: Dict[str, dict] = {m["guid"]: m for m in _raw.get("merchants", [])}
MERCHANTS = frozenset(MERCHANT_DATA)
# events / steps that let you take an item for free: guid -> {"name": ..., "stock": SpawnContext}
OFFER_DATA: Dict[str, dict] = {m["guid"]: m for m in _raw.get("offers", [])}

TIERS = ("Bronze", "Silver", "Gold", "Diamond", "Legendary")

# hour-3 monster encounters: guid -> {"name", "tier", "level"}
MONSTERS: Dict[str, dict] = {m["guid"]: m for m in _raw.get("monsters", [])}


# First day each rarity can be offered as the hour-3 monster. The server decides this; it isn't in the local
# game data (a monster's "level" is NOT its day: a level-4 Gold monster showed up on day 2).
# Verified by the user in game 2026-09-28: Silver day 1, Gold day 2, Diamond day 3, first Legendary (Lich) day 6.
FIRST_DAY_OF_TIER = {"Bronze": 1, "Silver": 1, "Gold": 2, "Diamond": 3, "Legendary": 6}


def max_monster_tier_by_day(last_day: int) -> Dict[int, int]:
    """Highest monster rarity (index into TIERS) you can meet on each day."""
    return {day: max(i for i, tier in enumerate(TIERS) if FIRST_DAY_OF_TIER[tier] <= day)
            for day in range(1, last_day + 1)}


# Cards unlocked together by one group item.
LEGENDARY_GUIDS = frozenset(c.guid for c in CARDS if c.shop and c.tier == "Legendary")
TICKET_GUIDS = frozenset(c.guid for c in CARDS if c.ticket)

CARDS_BY_NAME: Dict[str, Card] = {c.name: c for c in CARDS}
CARDS_BY_GUID: Dict[str, Card] = {c.guid: c for c in CARDS}
PACKS_BY_ITEM: Dict[str, Pack] = {}  # filled in by items.py once item names are known
