import math
from dataclasses import dataclass
from typing import Callable, Dict, List

from BaseClasses import Location

from .data import HEROES, TIERS
from .items import BASE_ID, EVENT_RARITY, GAME, LEGENDARY_ITEMS

MAX_DAY = 20  # ids are reserved up to this day; the max_day option picks how many exist
EVENT_RARITY_PVP_DAYS = (8, 14)  # PvP wins from these days need the 1st / 2nd Event Rarity Progression (user 2026-10-06:
#   Legendary events are so rare the 2nd copy only gates late days)


class BazaarLocation(Location):
    game = GAME


def day_location(hero: str, day: int) -> str:
    return f"{hero} - Reach Day {day}"


def pvp_location(hero: str, day: int) -> str:
    return f"{hero} - Day {day} PvP Win"


def monster_location(hero: str, day: int, tier: str) -> str:
    return f"{hero} - Day {day} Monster ({tier})"


def win_location(hero: str) -> str:
    return f"{hero} - 10 Wins"


def days_card_requirement(day: int, lock_count: int, day_10_cards: int, last_day_cards: int, max_day: int) -> int:
    """How many of a hero's own locked items logic expects before a day: none on days 1-7 (every run, even with
    zero wins, reaches day 7), half the day-10 amount on days 8-9, then an even climb from the day-10 amount on day 10
    to the last-day amount on max_day (user 2026-09-30: a late day on the day-10 minimum is much harder)."""
    if day <= 7:
        return 0
    if day <= 9:
        return min(math.ceil(day_10_cards / 2), lock_count)
    last = max(last_day_cards, day_10_cards)  # never easier later on
    final = max(max_day, 10)  # a max_day under 10: nothing to climb, day 10 (10 wins) just needs the day-10 amount
    wanted = day_10_cards + (last - day_10_cards) * (min(day, final) - 10) / max(final - 10, 1)
    return min(math.floor(wanted + 0.5), lock_count)


@dataclass(frozen=True)
class Check:
    """One check of a hero, described by what it is (never by parsing its name)."""
    name: str
    kind: str  # "day" (reach the day), "pvp" (win that day's fight), "monster" (beat a tier), "win" (10 wins)
    day: int
    tier: str = ""


def hero_checks(hero: str, max_day: int, pvp_win_checks: bool,
                monster_tiers: Callable[[int], List[str]]) -> List[Check]:
    """Every check a hero has in a seed. The world's rules and the client's tracker both list them this way."""
    checks = []
    for day in range(1, max_day + 1):
        checks.append(Check(day_location(hero, day), "day", day))
        if pvp_win_checks:
            checks.append(Check(pvp_location(hero, day), "pvp", day))
        checks += [Check(monster_location(hero, day, tier), "monster", day, tier) for tier in monster_tiers(day)]
    checks.append(Check(win_location(hero), "win", 10))
    return checks


def card_requirements(hero: str, lock_count: int, max_day: int, pvp_win_checks: bool,
                      monster_tiers: Callable[[int], List[str]], logic: Dict[str, int]) -> Dict[str, int]:
    """
    Every check of a hero -> how many of that hero's locked items logic wants received first. The one definition:
    the world's rules, the client's "checks in logic" count and its tracker all use it. logic: day_10 / last_day /
    diamond / legendary (seeds from before last_day existed climb nowhere: last_day = day_10, as they were made).
    """
    def by_day(day: int) -> int:
        return days_card_requirement(day, lock_count, logic["day_10"], logic.get("last_day", logic["day_10"]), max_day)
    tier_cards = {"Diamond": logic["diamond"], "Legendary": logic["legendary"]}
    needs: Dict[str, int] = {}
    for check in hero_checks(hero, max_day, pvp_win_checks, monster_tiers):
        if check.kind == "pvp":  # winning the day's fight is harder than just reaching the day
            needs[check.name] = by_day(check.day + 1)
        elif check.kind == "monster":  # Bronze/Silver/Gold only follow the day's requirement
            needs[check.name] = max(by_day(check.day), min(lock_count, tier_cards.get(check.tier, 0)))
        elif check.kind == "win":  # the hardest thing a run does: the last day's amount (user 2026-09-30)
            needs[check.name] = by_day(max(max_day, 10))
        else:  # reaching a day
            needs[check.name] = by_day(check.day)
    return needs


def item_requirements(check: Check, legendary_items: bool, event_rarity: int) -> Dict[str, int]:
    """
    Unlocks a check needs besides the hero's cards -> copies wanted (user 2026-10-06): Legendary monsters need
    Legendary Items, PvP wins from day 8 / day 14 need 1 / 2 Event Rarity Progression. Only items the seed has count
    (legendary_items: the unlock is in the pool; event_rarity: its copies). The world's rules and the client's
    "checks in logic" both use this.
    """
    if check.kind == "monster" and check.tier == "Legendary" and legendary_items:
        return {LEGENDARY_ITEMS: 1}
    if check.kind == "pvp":
        copies = min(event_rarity, sum(check.day >= day for day in EVENT_RARITY_PVP_DAYS))
        if copies:
            return {EVENT_RARITY: copies}
    return {}


def champion_event(hero: str) -> str:
    return f"{hero} - Champion"


# Id layout (never reorder, only append):
#   BASE + hero_index * 32 + day                     reach day
#   BASE + hero_index * 32 + 31                      10 wins
#   BASE + 0x1000 + hero_index * 32 + day            day's PvP win
#   BASE + 0x2000 + hero_index * 256 + day * 8 + t   day's monster, tier t (0 = Bronze .. 4 = Legendary)
location_name_to_id: Dict[str, int] = {}
for i, hero in enumerate(HEROES):
    for day in range(1, MAX_DAY + 1):
        location_name_to_id[day_location(hero, day)] = BASE_ID + i * 32 + day
        location_name_to_id[pvp_location(hero, day)] = BASE_ID + 0x1000 + i * 32 + day
        for t, tier in enumerate(TIERS):
            location_name_to_id[monster_location(hero, day, tier)] = BASE_ID + 0x2000 + i * 256 + day * 8 + t
    location_name_to_id[win_location(hero)] = BASE_ID + i * 32 + 31

location_name_groups = {
    hero: {name for name in location_name_to_id if name.startswith(f"{hero} - ")} for hero in HEROES
}
location_name_groups["10 Wins"] = {win_location(h) for h in HEROES}
location_name_groups["Reach Day"] = {day_location(h, d) for h in HEROES for d in range(1, MAX_DAY + 1)}
location_name_groups["PvP Wins"] = {pvp_location(h, d) for h in HEROES for d in range(1, MAX_DAY + 1)}
location_name_groups["Monsters"] = {monster_location(h, d, t) for h in HEROES for d in range(1, MAX_DAY + 1)
                                    for t in TIERS}
