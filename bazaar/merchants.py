"""
Works out which cards a merchant could put on sale, from the merchant's SpawnContext in the game data.

The log doesn't say what a shop is showing, but it does say which merchant you walked into. Every merchant
defines its stock with a few simple filters (size, tags, hero, tier, enchantment, or an explicit id list),
so we can list the locked cards it might offer. Unknown filters are treated as "could be anything" so the
warning errs on the side of listing too much rather than too little.
"""
from typing import Dict, Iterable, List, Optional

from .data import Card, hero_of_code


def _matches(constraint: dict, card: Card) -> bool:
    kind = constraint.get("$type", "")
    if kind == "ConstraintAnd":
        return all(_matches(c, card) for c in constraint.get("Constraints") or [])
    if kind == "ConstraintOr":
        return any(_matches(c, card) for c in constraint.get("Constraints") or [])
    if kind == "ConstraintCardType":
        result = "Item" in constraint.get("Types", [])
    elif kind == "ConstraintSize":
        result = card.size in constraint.get("Sizes", [])
    elif kind == "ConstraintTag":
        result = bool(set(card.tags) & set(constraint.get("Tags", [])))
    elif kind == "ConstraintHiddenTag":
        result = bool(set(card.hidden_tags) & set(constraint.get("HiddenTags", [])))
    elif kind == "ConstraintHero":  # the game's hero codes (data.HERO_CODES)
        result = card.hero in [hero_of_code(h) for h in constraint.get("Heroes", [])]
    elif kind == "ConstraintTier":
        result = bool(set(card.tiers or (card.tier,)) & set(constraint.get("Tiers", [])))
    elif kind == "ConstraintEnchantmentEligible":
        result = bool(set(card.enchants) & set(constraint.get("Enchantments", [])))
    else:
        return True
    return result != bool(constraint.get("IsNot"))


def _filter_allows(spawn_filter: dict, card: Card, ids: Optional[Dict[int, set]] = None) -> bool:
    """ids: id lists already lowered, by filter (possible_stock builds each once: rebuilt for every card it took
    ~180 ms for one merchant in the Item Guide, measured 2026-11-12)."""
    kind = spawn_filter.get("$type", "")
    if kind == "TSpawnFilterIdList":
        if ids is None:
            return card.guid in {i.lower() for i in spawn_filter.get("Ids", [])}
        if id(spawn_filter) not in ids:
            ids[id(spawn_filter)] = {i.lower() for i in spawn_filter.get("Ids", [])}
        return card.guid in ids[id(spawn_filter)]
    if kind == "TSpawnFilterQuery":
        return _matches(spawn_filter.get("Constraints") or {}, card)
    if kind == "TSpawnFilterUpgrade":
        return False  # upgrades items you already own
    return True


def _ignores_hero(behaviors) -> bool:
    return any((b or {}).get("$type") == "TSpawnBehaviorIgnoreHero" for b in behaviors or [])


def _needs_skill(group: dict) -> bool:
    """A group that only deals while you own a certain skill (TPrerequisiteCardCount on SelfSkills). Such groups
    never count (owner, 2026-11-13: "Just pretend the skills dont exist"): every one of the 368 groups that deals
    other heroes' cards needs one of 8 skills, so counting them listed e.g. Dooley's 3D Printer at Chronos while
    playing Jules. Other prerequisites (TPrerequisiteRun: from day 2) still count - they come true later in a run."""
    return any((p or {}).get("$type") == "TPrerequisiteCardCount"
               and ((p.get("Subject") or {}).get("TargetSection") == "SelfSkills")
               for p in group.get("Prerequisites") or [])


def _groups(stock: dict) -> list:
    """The stock's groups that can deal in a run (see _needs_skill)."""
    return [g for g in stock.get("Groups") or [{}] if not _needs_skill(g)]


def _has(behaviors, kind: str) -> bool:
    return any((b or {}).get("$type") == kind for b in behaviors or [])


def _only_tiers(stock: dict, group: dict) -> Optional[set]:
    """The rarities this deal offers its cards at only (TSpawnBehaviorTier), when a card must come in one of them:
    Curio, Bronze only (owner, 2026-11-13: "Yes bronze only"). Not with TSpawnBehaviorIgnoreTierTable (Goldie, Luxe,
    Silvia, Aila, Jay Jay): what that flag allows isn't known, so those aren't narrowed. None: any rarity."""
    behaviors = (stock.get("Behaviors") or []) + (group.get("Behaviors") or [])
    if _has(behaviors, "TSpawnBehaviorIgnoreTierTable"):
        return None
    tiers = [set(b.get("Tiers") or []) for b in behaviors if (b or {}).get("$type") == "TSpawnBehaviorTier"]
    return set.intersection(*tiers) if tiers else None


def deals_any_hero(stock: dict) -> bool:
    """Could this stock deal cards that aren't your hero's - ignoring heroes (TSpawnBehaviorIgnoreHero), excluding
    yours (TSpawnBehaviorExcludePlayerHero: Stickybeans) or naming whose cards it takes (Curio, the hero merchants:
    Dooley's meets every hero but Dooley)? The same tests can_stock uses; the Item Guide's Hero filter starts on Any
    for these."""
    behaviors = stock.get("Behaviors") if stock else None
    return bool(stock) and (_ignores_hero(behaviors) or _has(behaviors, "TSpawnBehaviorExcludePlayerHero")
                            or any(_ignores_hero(g.get("Behaviors")) or _names_hero(g.get("Filters"))
                                   for g in _groups(stock)))


def _names_hero(constraint) -> bool:
    """Does the deal say itself whose cards it takes (a ConstraintHero anywhere in its filters)?"""
    if isinstance(constraint, dict):
        return constraint.get("$type") == "ConstraintHero" or any(_names_hero(v) for v in constraint.values())
    return isinstance(constraint, list) and any(_names_hero(v) for v in constraint)


def can_stock(stock: dict, card: Card, hero: str = "", ids: Optional[Dict[int, set]] = None) -> bool:
    """Could this stock deal the card? With `hero` (owner, 2026-11-13: "Herma ONLY OFFERS ITEMS FOR THE HERO. no
    neutral items, no other heros"): only your hero's own cards - unless the deal ignores heroes
    (TSpawnBehaviorIgnoreHero, on the whole stock or on one group: relics, toys, apparel... anyone's cards), or names
    whose cards it takes itself (a ConstraintHero: Curio's neutral Junk items, a hero merchant's own hero; owner:
    "curio sells 'Junk' items which are neutral", "Dooley would sell dooley items"). Stickybeans
    (TSpawnBehaviorExcludePlayerHero): every card but your hero's. A deal at one rarity only takes cards that come in
    it (_only_tiers: Curio, Bronze). Groups that need a skill never count (_needs_skill). Was until 2026-11-13: your
    hero's cards plus neutral ones everywhere."""
    if not stock:
        return not hero or card.hero == hero
    groups = _groups(stock)
    any_hero = _ignores_hero(stock.get("Behaviors"))
    # Stickybeans: every card but your hero's (owner, 2026-11-13: "fix 1/2"; neutral ones included - unconfirmed)
    others = _has(stock.get("Behaviors"), "TSpawnBehaviorExcludePlayerHero")

    def hero_ok(group: dict) -> bool:
        if not hero:
            return True
        if others:
            return card.hero != hero
        return card.hero == hero or any_hero or _ignores_hero(group.get("Behaviors")) \
            or _names_hero(group.get("Filters"))

    def tier_ok(group: dict) -> bool:
        tiers = _only_tiers(stock, group)
        return tiers is None or bool(tiers & set(card.tiers or (card.tier,)))
    return any(hero_ok(group) and tier_ok(group) and all(_filter_allows(f, card, ids) for f in group.get("Filters") or [])
               for group in groups)


def possible_stock(stock: dict, hero: str, cards: Iterable[Card]) -> List[Card]:
    """Cards from `cards` this merchant or item choice could offer while playing `hero`."""
    ids: Dict[int, set] = {}  # each id list lowered once for this stock (the filters live as long as this call)
    return [c for c in cards if can_stock(stock, c, hero, ids)]
