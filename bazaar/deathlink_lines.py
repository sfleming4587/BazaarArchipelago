"""What a DeathLink from The Bazaar says in everyone else's client (owner, 2026-10-02: per hero, different lines for
different situations, the player's name rather than "Sulldog's Mak", and some fun with the game's own lines).

How far the run got is told by its PvP wins, never its day: the earliest possible loss is day 7, which means
nothing to players of other games (owner, 2026-10-02). Lines name the player but never use he/she: we don't know
anyone's pronouns. {player} and {wins} ("1 win" / "5 wins") are filled in. Adding a line is adding a string; a
hero with no lines for a situation uses the shared ones.
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
        "ENTER. PURCHASE. LEAVE. {player} left with {wins}.",
    ],
    # owner, 2026-10-02: the trash line, always, for a run lost without a single win
    "zero": [
        "Trash is tragedy... so is {player}. 0 Wins.",
    ],
    "early": [
        "BOOOOORRRRRIIIINNNNGGGG... {player} went out with {wins}.",
        "The Bazaar's a crazy place, right? {player} found out with {wins}.",
        "{player} didn't make it past {wins}. The Bazaar's a crazy place, right?",
    ],
    "mid": [
        "BOOOOORRRRRIIIINNNNGGGG... {player} went out with {wins}.",
        "The Bazaar's a crazy place, right? {player} just ran out of prestige with {wins}.",
    ],
    "late": [
        "{player} was so close... {wins}, then out of prestige.",
        "The Bazaar's a crazy place, right? Ask {player}, who lost it all with {wins}.",
    ],
    "conceded": [
        "{player} walked out of the Bazaar with {wins}.",
        "{player} gave up with {wins}. The Bazaar's a crazy place, right?",
    ],
}

# hero -> situation -> lines (heroes' themes from their cards)
HEROES: Dict[str, Dict[str, List[str]]] = {
    "Vanessa": {
        "early": ["{player} sank before leaving the harbour, with {wins}.",
                  "{player} was thrown overboard with {wins}."],
        "mid": ["{player} was thrown overboard with {wins}.",
                "{player} walked the plank with {wins}."],
        "late": ["{player} spotted treasure island with {wins}... then the ship went down."],
        "conceded": ["{player} abandoned ship with {wins}."],
    },
    "Pygmalien": {
        "early": ["{player} went bankrupt with {wins}."],
        "mid": ["{player} went bankrupt with {wins}.",
                "{player}'s investments crashed with {wins}."],
        "late": ["{player} was one deal away from a fortune and lost it all with {wins}.",
                 "Have you noticed {player} was HUGE... hmm? Well not anymore, {wins}."],
        "conceded": ["{player} cashed out early with {wins}."],
    },
    "Dooley": {
        "early": ["{player}: BEEP BOOP BEEP BOOooo..."],
        "mid": ["{player} beeped and booped their last with {wins}.",
                "{player}: BEEP BOOP BEEP BOOooo..."],
        "late": ["{player}: BEEP BOOP BEEP... BEEP... BOOooo..."],
        "conceded": ["{player}: BOOP. BOOP. BOOP."],
    },
    "Mak": {
        "early": ["{player} drank the wrong vial with {wins}."],
        "mid": ["{player} fumbled the potions with {wins}.",
                "{player}'s cauldron boiled over with {wins}."],
        "late": ["{player} spilled the final potion with {wins}."],
        "conceded": ["{player} corked the bottles and left with {wins}."],
    },
    "Stelle": {
        "early": ["{player} never got off the ground, with {wins}."],
        "mid": ["{player} crash-landed with {wins}.",
                "{player} flew too close to the sun with {wins}."],
        "late": ["{player} ran out of fuel within sight of the runway, with {wins}."],
        "conceded": ["{player} bailed out with {wins}."],
    },
    "Jules": {
        "early": ["{player} burnt the first course with {wins}."],
        "mid": ["{player} burnt the dinner with {wins}.",
                "{player} got kicked out of the kitchen with {wins}."],
        "late": ["{player} dropped the cake on the way to the table, with {wins}."],
        "conceded": ["{player} hung up the apron with {wins}."],
    },
    "Karnok": {
        "early": ["{player} became the hunted with {wins}."],
        "mid": ["{player} was eaten by the wilds with {wins}.",
                "{player} stepped in a bear trap with {wins}."],
        "late": ["{player} lost the trail on the final hunt, with {wins}."],
        "conceded": ["{player} retreated into the woods with {wins}."],
    },
    "The Dragons": {
        "early": ["{player} got booed off the stage with {wins}."],
        "mid": ["{player}'s band broke up with {wins}.",
                "{player} missed the high note with {wins}."],
        "late": ["{player}'s farewell tour ended one show short, with {wins}."],
        "conceded": ["{player} cancelled the tour with {wins}."],
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


def deathlink_message(player: str, hero: Optional[str], wins: int, conceded: bool,
                      rng: Optional[random.Random] = None) -> str:
    """A random line for this hero and situation: the hero's own half the time (so the shared lines, which
    outnumber them, don't drown them out), else a shared one."""
    rng = rng or random
    kind = situation(wins, conceded)
    fill = {"player": player, "wins": f"{wins} win" + ("" if wins == 1 else "s")}
    if kind == "zero":
        return rng.choice(SHARED["zero"]).format(**fill)
    own = HEROES.get(hero or "", {}).get(kind, [])
    lines = own if own and rng.random() < 0.5 else SHARED[kind] + SHARED["any"]
    return rng.choice(lines).format(**fill)
