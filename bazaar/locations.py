from typing import Dict

from BaseClasses import Location

from .data import HEROES
from .items import BASE_ID, GAME

MAX_DAY = 20  # ids are reserved up to this day; the max_day option picks how many exist


class BazaarLocation(Location):
    game = GAME


def day_location(hero: str, day: int) -> str:
    return f"{hero} - Reach Day {day}"


def win_location(hero: str) -> str:
    return f"{hero} - 10 Wins"


def champion_event(hero: str) -> str:
    return f"{hero} - Champion"


# Id layout: BASE + hero_index * 32 + day, and + 31 for the 10-win check.
location_name_to_id: Dict[str, int] = {}
for i, hero in enumerate(HEROES):
    for day in range(1, MAX_DAY + 1):
        location_name_to_id[day_location(hero, day)] = BASE_ID + i * 32 + day
    location_name_to_id[win_location(hero)] = BASE_ID + i * 32 + 31

location_name_groups = {
    hero: {day_location(hero, d) for d in range(1, MAX_DAY + 1)} | {win_location(hero)} for hero in HEROES
}
location_name_groups["10 Wins"] = {win_location(h) for h in HEROES}
