"""
Which merchants and events are locked, and which one a screen of nothing but locked events lets through.
The owner's rulings and the traps are in docs/ENCOUNTER-LOCKS.md.
"""
import hashlib
from typing import Iterable, Optional, Set

from .data import EVENTS, TIERS
from .items import ENCOUNTER_UNLOCKS, LEVEL_UP_TIERS

# what a choice screen's event options are: map events, and the steps a level-up offers (owner, 2026-11-11: Shiny!)
EVENT_KINDS = ("EventEncounter", "EncounterStep")


def event_tier(guid: str) -> Optional[str]:
    """A choosable event's rarity: a map event's, or a lockable level-up event's (items.LEVEL_UPS); None if unknown."""
    return EVENTS[guid]["tier"] if guid in EVENTS else LEVEL_UP_TIERS.get(guid)

# Event templates Event Rarity Progression locks until its first / second copy: never level-up rewards (owner,
# 2026-10-02: "Level ups not included"); expeditions only when they aren't exempt
RARITY_STAGES = ("Diamond", "Legendary")


def locked_events(lock_ids: Iterable[int], received: Iterable[int], rarity_copies: int, rarity_received: int,
                  exempt_expeditions: bool) -> Set[str]:
    """Event template guids locked right now: those of every lock item not received yet, plus the rarities
    Event Rarity Progression hasn't reached (when the seed has it)."""
    got = set(received)
    locked = {guid for item_id in lock_ids if item_id not in got for guid in ENCOUNTER_UNLOCKS.get(item_id, ())}
    if rarity_copies:
        tiers = RARITY_STAGES[min(rarity_received, len(RARITY_STAGES)):]
        locked |= {guid for guid, e in EVENTS.items() if e["tier"] in tiers and not e["level_up"]
                   and not (exempt_expeditions and e["expedition"])}
    return locked


def rarity_bypasses(rarity_received: int) -> int:
    """Copies past the two stages each count as a Lock Bypass (owner, 2026-10-02)."""
    return max(0, rarity_received - len(RARITY_STAGES))


def let_through(offers, locked: Set[str]) -> Optional[str]:
    """When every option on a choice screen is a locked event, the least rare one is let through (owner,
    2026-10-01); a tie is broken by the screen's own instance ids, so the pick is the same on every reading and
    reconnect. None when there's an allowed way on: an unlocked event, or anything that isn't an event (the
    Mysterious Portal's item bubble, owner 2026-10-02)."""
    if not offers or any(o.kind not in EVENT_KINDS or event_tier(o.template) is None for o in offers):
        return None
    if any(o.template not in locked for o in offers):
        return None
    rank = lambda o: TIERS.index(event_tier(o.template))
    lowest = min(rank(o) for o in offers)
    tied = sorted((o for o in offers if rank(o) == lowest), key=lambda o: o.instance)
    digest = hashlib.sha256("|".join(o.instance for o in offers).encode()).digest()
    return tied[int.from_bytes(digest[:4], "big") % len(tied)].template
