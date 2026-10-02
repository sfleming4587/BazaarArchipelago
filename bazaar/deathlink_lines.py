"""What a DeathLink from The Bazaar says in everyone else's client (owner, 2026-10-02: per hero, different lines for
different situations, the player's name rather than "Sulldog's Mak", and some fun with the game's own lines).

Lines name the player but never use he/she: we don't know anyone's pronouns. {player} and {day} are filled in.
Adding a line is adding a string; a hero with no lines for a situation uses the shared ones.
"""
import random
from typing import Dict, List, Optional

EARLY_DAYS = 4  # lost on day 1-4: an "early" loss
LATE_DAYS = 9  # lost on day 9 or later: a "late" loss (so close)

# situation -> lines any hero can use
SHARED: Dict[str, List[str]] = {
    "early": [
        "The Bazaar's a crazy place, right? {player} found out on day {day}.",
        "{player} didn't make it past day {day}. The Bazaar's a crazy place, right?",
    ],
    "lost": [
        "The Bazaar's a crazy place, right? {player} just ran out of prestige on day {day}.",
        "{player} ran out of prestige on day {day}.",
    ],
    "late": [
        "{player} was so close... out of prestige on day {day}.",
        "The Bazaar's a crazy place, right? Ask {player}, who lost it all on day {day}.",
    ],
    "conceded": [
        "{player} walked out of the Bazaar on day {day}.",
        "{player} gave up on day {day}. The Bazaar's a crazy place, right?",
    ],
}

# hero -> situation -> lines (heroes' themes from their cards)
HEROES: Dict[str, Dict[str, List[str]]] = {
    "Vanessa": {
        "early": ["{player} sank before leaving the harbour (day {day}).",
                  "{player} was thrown overboard on day {day}."],
        "lost": ["{player} was thrown overboard on day {day}.",
                 "{player} walked the plank on day {day}."],
        "late": ["{player} could see the treasure from the plank (day {day})."],
        "conceded": ["{player} abandoned ship on day {day}."],
    },
    "Pygmalien": {
        "early": ["{player} went bankrupt on day {day}. Not very business of them."],
        "lost": ["{player} went bankrupt on day {day}.",
                 "{player}'s investments crashed on day {day}."],
        "late": ["{player} was one deal away from a fortune and lost it all on day {day}."],
        "conceded": ["{player} cashed out early on day {day}."],
    },
    "Dooley": {
        "early": ["Beep boop... {player} short-circuited on day {day}."],
        "lost": ["{player} short-circuited on day {day}.",
                 "Beep. Boop. {player} has been powered down (day {day})."],
        "late": ["{player}'s core overheated on day {day}, so close to the end."],
        "conceded": ["{player} pulled the plug on day {day}."],
    },
    "Mak": {
        "early": ["{player} drank the wrong vial on day {day}."],
        "lost": ["{player} fumbled the potions on day {day}.",
                 "{player}'s cauldron boiled over on day {day}."],
        "late": ["{player} spilled the final potion on day {day}."],
        "conceded": ["{player} corked the bottles and left on day {day}."],
    },
    "Stelle": {
        "early": ["{player} never got off the ground (day {day})."],
        "lost": ["{player} crash-landed on day {day}.",
                 "{player} flew too close to the sun on day {day}."],
        "late": ["{player} ran out of fuel within sight of the runway (day {day})."],
        "conceded": ["{player} bailed out on day {day}."],
    },
    "Jules": {
        "early": ["{player} burnt the first course on day {day}."],
        "lost": ["{player} burnt the dinner on day {day}.",
                 "{player} got kicked out of the kitchen on day {day}."],
        "late": ["{player} dropped the cake on the way to the table (day {day})."],
        "conceded": ["{player} hung up the apron on day {day}."],
    },
    "Karnok": {
        "early": ["{player} became the hunted on day {day}."],
        "lost": ["{player} was eaten by the wilds on day {day}.",
                 "{player} stepped in a bear trap on day {day}."],
        "late": ["{player} lost the trail on the final hunt (day {day})."],
        "conceded": ["{player} retreated into the woods on day {day}."],
    },
    "The Dragons": {
        "early": ["{player} got booed off the stage on day {day}."],
        "lost": ["{player}'s band broke up on day {day}.",
                 "{player} missed the high note on day {day}."],
        "late": ["{player}'s farewell tour ended on day {day}, one show short."],
        "conceded": ["{player} cancelled the tour on day {day}."],
    },
}


def situation(day: int, conceded: bool) -> str:
    if conceded:
        return "conceded"
    if day <= EARLY_DAYS:
        return "early"
    return "late" if day >= LATE_DAYS else "lost"


def deathlink_message(player: str, hero: Optional[str], day: int, conceded: bool,
                      rng: Optional[random.Random] = None) -> str:
    """A random line for this hero and situation, from the hero's own lines and the shared ones."""
    kind = situation(day, conceded)
    lines = HEROES.get(hero or "", {}).get(kind, []) + SHARED[kind]
    return (rng or random).choice(lines).format(player=player, day=day)
