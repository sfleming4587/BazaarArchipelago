"""What a DeathLink from The Bazaar says in everyone else's client (owner, 2026-10-02: per hero, different lines for
different situations, the player's name rather than "Sulldog's Mak", and some fun with the game's own lines).

How far the run got is told by its PvP wins, not its day (owner: the earliest possible loss is day 7).
Lines name the player but never use he/she: we don't know anyone's pronouns. {player}, {day} and {wins} are filled
in ({wins} reads "1 win" / "5 wins"). Adding a line is adding a string; a hero with no lines for a situation uses the shared ones.
"""
import random
from typing import Dict, List, Optional

EARLY_WINS = 3  # lost with 1-3 wins: an "early" loss (0 wins is "zero": trash)
LATE_WINS = 8  # lost with 8 or 9 wins: a "late" loss (so close to 10)

# situation -> lines any hero can use ("any": every situation; owner's picks from the game's lines, 2026-10-02)
SHARED: Dict[str, List[str]] = {
    "any": [
        "From the grand society of blahblahblah... {player} says byyyyye!",
        "{player}: all cannon, no balls!",
        "I suppose {player} should've bought a WEAPON instead.",
        "ENTER. PURCHASE. LEAVE. {player} left on day {day}.",
    ],
    # owner, 2026-10-02: the trash line, always, for a run lost without a single win
    "zero": [
        "Trash is tragedy... so is {player}. 0 Wins.",
    ],
    "early": [
        "BOOOOORRRRRIIIINNNNGGGG... {player} went out with {wins}.",
        "The Bazaar's a crazy place, right? {player} found out on day {day}.",
        "{player} didn't make it past day {day}. The Bazaar's a crazy place, right?",
    ],
    "mid": [
        "BOOOOORRRRRIIIINNNNGGGG... {player} went out with {wins}.",
        "The Bazaar's a crazy place, right? {player} just ran out of prestige on day {day}.",
        "{player} ran out of prestige on day {day}, {wins} in.",
    ],
    "late": [
        "{player} was so close... {wins}, then out of prestige on day {day}.",
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
        "mid": ["{player} was thrown overboard on day {day}.",
                 "{player} walked the plank on day {day}."],
        "late": ["{player} could see the treasure from the plank (day {day})."],
        "conceded": ["{player} abandoned ship on day {day}."],
    },
    "Pygmalien": {
        "early": ["{player} went bankrupt on day {day}."],
        "mid": ["{player} went bankrupt on day {day}.",
                 "{player}'s investments crashed on day {day}."],
        "late": ["{player} was one deal away from a fortune and lost it all on day {day}.",
                 "Have you noticed {player} was HUGE... hmm? Not any more (day {day})."],
        "conceded": ["{player} cashed out early on day {day}."],
    },
    "Dooley": {
        "early": ["{player}: BEEP BOOP BEEP BOOooo..."],
        "mid": ["{player} beeped and booped their last on day {day}.",
                 "{player}: BEEP BOOP BEEP BOOooo..."],
        "late": ["{player}: BEEP BOOP BEEP... BEEP... BOOooo..."],
        "conceded": ["{player}: BOOP. BOOP. BOOP."],
    },
    "Mak": {
        "early": ["{player} drank the wrong vial on day {day}."],
        "mid": ["{player} fumbled the potions on day {day}.",
                 "{player}'s cauldron boiled over on day {day}."],
        "late": ["{player} spilled the final potion on day {day}."],
        "conceded": ["{player} corked the bottles and left on day {day}."],
    },
    "Stelle": {
        "early": ["{player} never got off the ground (day {day})."],
        "mid": ["{player} crash-landed on day {day}.",
                 "{player} flew too close to the sun on day {day}."],
        "late": ["{player} ran out of fuel within sight of the runway (day {day})."],
        "conceded": ["{player} bailed out on day {day}."],
    },
    "Jules": {
        "early": ["{player} burnt the first course on day {day}."],
        "mid": ["{player} burnt the dinner on day {day}.",
                 "{player} got kicked out of the kitchen on day {day}."],
        "late": ["{player} dropped the cake on the way to the table (day {day})."],
        "conceded": ["{player} hung up the apron on day {day}."],
    },
    "Karnok": {
        "early": ["{player} became the hunted on day {day}."],
        "mid": ["{player} was eaten by the wilds on day {day}.",
                 "{player} stepped in a bear trap on day {day}."],
        "late": ["{player} lost the trail on the final hunt (day {day})."],
        "conceded": ["{player} retreated into the woods on day {day}."],
    },
    "The Dragons": {
        "early": ["{player} got booed off the stage on day {day}."],
        "mid": ["{player}'s band broke up on day {day}.",
                 "{player} missed the high note on day {day}."],
        "late": ["{player}'s farewell tour ended on day {day}, one show short."],
        "conceded": ["{player} cancelled the tour on day {day}."],
    },
}


def situation(wins: int, conceded: bool) -> str:
    if conceded:
        return "conceded"
    if wins == 0:
        return "zero"
    if wins <= EARLY_WINS:
        return "early"
    return "late" if wins >= LATE_WINS else "mid"


def deathlink_message(player: str, hero: Optional[str], day: int, wins: int, conceded: bool,
                      rng: Optional[random.Random] = None) -> str:
    """A random line for this hero and situation: the hero's own half the time (so the shared lines, which
    outnumber them, don't drown them out), else a shared one."""
    rng = rng or random
    kind = situation(wins, conceded)
    fill = {"player": player, "day": day, "wins": f"{wins} win" + ("" if wins == 1 else "s")}
    if kind == "zero":
        return rng.choice(SHARED["zero"]).format(**fill)
    own = HEROES.get(hero or "", {}).get(kind, [])
    lines = own if own and rng.random() < 0.5 else SHARED[kind] + SHARED["any"]
    return rng.choice(lines).format(**fill)
