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

HEROES: List[str] = _raw["heroes"]
BASE_HEROES = ("Vanessa", "Pygmalien", "Dooley")
DLC_HEROES = tuple(h for h in HEROES if h not in BASE_HEROES)

CARDS: List[Card] = [Card(c["guid"], c["ap_id"], c["name"], c["hero"], c["tier"], c["size"],
                          tuple(c["tags"]), c["shop"]) for c in _raw["cards"]]
PACKS: List[Pack] = [Pack(p["key"], p["ap_id"], p["name"], p["hero"], tuple(p["cards"])) for p in _raw["packs"]]

CARDS_BY_NAME: Dict[str, Card] = {c.name: c for c in CARDS}
CARDS_BY_GUID: Dict[str, Card] = {c.guid: c for c in CARDS}
PACKS_BY_ITEM: Dict[str, Pack] = {}  # filled in by items.py once item names are known
