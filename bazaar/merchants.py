"""
Works out which cards a merchant could put on sale, from the merchant's SpawnContext in the game data.

The log doesn't say what a shop is showing, but it does say which merchant you walked into. Every merchant
defines its stock with a few simple filters (size, tags, hero, tier, enchantment, or an explicit id list),
so we can list the locked cards it might offer. Unknown filters are treated as "could be anything" so the
warning errs on the side of listing too much rather than too little.
"""
from typing import Iterable, List

from .data import Card


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
    elif kind == "ConstraintHero":
        result = card.hero in constraint.get("Heroes", [])
    elif kind == "ConstraintTier":
        result = bool(set(card.tiers or (card.tier,)) & set(constraint.get("Tiers", [])))
    elif kind == "ConstraintEnchantmentEligible":
        result = bool(set(card.enchants) & set(constraint.get("Enchantments", [])))
    else:
        return True
    return result != bool(constraint.get("IsNot"))


def _filter_allows(spawn_filter: dict, card: Card) -> bool:
    kind = spawn_filter.get("$type", "")
    if kind == "TSpawnFilterIdList":
        return card.guid in {i.lower() for i in spawn_filter.get("Ids", [])}
    if kind == "TSpawnFilterQuery":
        return _matches(spawn_filter.get("Constraints") or {}, card)
    if kind == "TSpawnFilterUpgrade":
        return False  # upgrades items you already own
    return True


def can_stock(stock: dict, card: Card) -> bool:
    if not stock:
        return True
    groups = stock.get("Groups") or []
    if not groups:
        return True
    return any(all(_filter_allows(f, card) for f in group.get("Filters") or []) for group in groups)


def possible_stock(stock: dict, hero: str, cards: Iterable[Card]) -> List[Card]:
    """Cards from `cards` this merchant could offer while playing `hero` (your hero's pool plus Common)."""
    return [c for c in cards if c.hero in (hero, "Common") and can_stock(stock, c)]
