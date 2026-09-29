import math
from dataclasses import dataclass
from typing import Callable, Dict, List

from BaseClasses import Location

from .data import HEROES, TIERS
from .items import BASE_ID, GAME

MAX_DAY = 20  # ids are reserved up to this day; the max_day option picks how many exist


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


def days_card_requirement(day: int, lock_count: int, day_10_cards: int) -> int:
    """How many of a hero's own locked items logic expects before a day: none on days 1-7 (every run, even with
    zero wins, reaches day 7), half the day-10 amount on days 8-9, the full amount from day 10 on."""
    if day <= 7:
        return 0
    wanted = day_10_cards if day >= 10 else math.ceil(day_10_cards / 2)
    return min(wanted, lock_count)


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
    the world's rules, the client's "checks in logic" count and its tracker all use it. logic: day_10 / diamond /
    legendary.
    """
    day_10 = logic["day_10"]
    tier_cards = {"Diamond": logic["diamond"], "Legendary": logic["legendary"]}
    needs: Dict[str, int] = {}
    for check in hero_checks(hero, max_day, pvp_win_checks, monster_tiers):
        if check.kind == "pvp":  # winning the day's fight is harder than just reaching the day
            needs[check.name] = days_card_requirement(check.day + 1, lock_count, day_10)
        elif check.kind == "monster":  # Bronze/Silver/Gold only follow the day's requirement
            needs[check.name] = max(days_card_requirement(check.day, lock_count, day_10),
                                    min(lock_count, tier_cards.get(check.tier, 0)))
        else:  # reaching a day; 10 wins counts as reaching day 10
            needs[check.name] = days_card_requirement(check.day, lock_count, day_10)
    return needs


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
