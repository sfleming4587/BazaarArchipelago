from typing import Dict

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
