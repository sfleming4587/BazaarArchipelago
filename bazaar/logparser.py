"""
Read-only parsing of The Bazaar's Unity Player.log.

This module never touches the game process, its memory or its servers. It only reads the text log the game
writes for itself. Keep it free of Archipelago imports so it can be tested on its own.

Game state as seen in the log (client version 1.0.x, Sept 2026):
    [RunConfigurationCache] RunConfigurationCache: Changing EHero to Vanessa
    [StartRunAppState] Run initialization finalized.
    [AppState] State changed from [ChoiceState] to [PVPCombatState]      <- the day's PvP fight
    [AppState] State changed from [ReplayState] to [ChoiceState]         <- survived it: next day
    [AppState] State changed from [ReplayState] to [EndRunVictoryState]  <- 10 wins
    [AppState] State changed from [ReplayState] to [EndRunDefeatState]   <- out of prestige
    [BoardManager] Card Purchased: InstanceId: itm_xxx - TemplateId<guid> - Target:PlayerSocket_3 - SectionPlayer
        ^ logged for every item that lands on your board or in storage: shop buys, event rewards, loot, level-ups
    [BoardManager] Sold Card itm_xxx for 2 gold.
        ^ the same instance id the item got when it was gained, so held items can be tracked exactly
"""
import os
import re
from dataclasses import dataclass
from typing import Collection, Iterator, List, Optional, Union

DEFAULT_LOG_PATH = os.path.join(os.path.expandvars("%USERPROFILE%"), "AppData", "LocalLow", "Tempo Storm",
                                "The Bazaar", "Player.log")

HERO_RE = re.compile(r"Changing EHero to (\w+)")
STAMP_RE = re.compile(rb"^\[(\d\d:\d\d:\d\d\.\d+)\]", re.MULTILINE)
PREV_LOG = "Player-prev.log"  # where Unity moves the previous session's log when the game starts
RUN_READY_RE = re.compile(r"\[StartRunAppState\] Run initialization finalized")
STATE_RE = re.compile(r"\[AppState\] State changed from \[(\w+)\] to \[(\w+)\]")
GAIN_RE = re.compile(r"Card Purchased: InstanceId: (itm_\S+) - TemplateId([0-9a-fA-F-]{36}) - Target:\S+ - "
                     r"Section(Player|Storage)")
ENCOUNTER_RE = re.compile(r"Card Purchased: InstanceId: (enc|ste|com|pvp|ped)_\S+ - TemplateId([0-9a-fA-F-]{36})")
# Candidate PvP-win signal, under investigation (see docs): seen once, only after a won PvP fight.
EXIT_TASKS_RE = re.compile(r"\[AppState\] Waiting for \d+ exit tasks")
VERSION_RE = re.compile(r"\[VersionShow\]\s+Version: (\d+\.\d+\.\d+)")
CONCEDE_RE = re.compile(r"type=AbandonRunCommand|Sending AbandonRunCommand")
SOLD_RE = re.compile(r"\[BoardManager\] Sold Card (itm_\S+) for \d+ gold")

# states in which the game shows you something to pick from (a shop, an event, a level-up, loot)
CHOICE_STATES = ("EncounterState", "LevelUpState", "LootState", "PedestalState")

# EHero enum names that differ from the display names used by the apworld
HERO_ALIASES = {"Pyg": "Pygmalien", "Hero8": "The Dragons", "Dragon": "The Dragons", "Dragons": "The Dragons",
                "TheDragons": "The Dragons"}


@dataclass(frozen=True)
class RunStarted:
    hero: str
    index: int = 0  # which run of this log (game session) it is: 0 for the first. The log has no run ids.


@dataclass(frozen=True)
class HeroSelected:
    hero: str  # picked on the hero-select screen (outside a run)


@dataclass(frozen=True)
class DayReached:
    day: int


@dataclass(frozen=True)
class CardGained:
    guid: str
    instance: str
    bought: bool  # True: taken inside a merchant encounter (paid gold). False: event, loot or level-up reward


@dataclass(frozen=True)
class CardSold:
    instance: str


@dataclass(frozen=True)
class FightStarted:
    pvp: bool


@dataclass(frozen=True)
class EncounterEntered:
    guid: str  # the encounter's template id, e.g. a merchant


@dataclass(frozen=True)
class EncounterLeft:
    pass


@dataclass(frozen=True)
class MonsterFought:
    guid: str  # the monster encounter picked at hour 3
    day: int
    won: bool  # a won fight always leads to picking loot from the monster's board


@dataclass(frozen=True)
class PvPFought:
    day: int
    won: Optional[bool]  # None: the log doesn't say (only a fight that ends the run tells us)
    exit_tasks: bool = False  # the candidate win signal was seen during this fight


@dataclass(frozen=True)
class RunEnded:
    victory: bool
    day: int
    conceded: bool = False  # the player abandoned the run (as opposed to running out of prestige)


@dataclass(frozen=True)
class GameVersion:
    version: str  # e.g. "1.0.12293"


@dataclass(frozen=True)
class UnrecognizedRun:
    """A fight happened but no run start was recognised: the log format probably changed in a patch."""


Event = Union[RunStarted, HeroSelected, DayReached, CardGained, CardSold, FightStarted, EncounterEntered, EncounterLeft,
              MonsterFought, PvPFought, RunEnded, GameVersion, UnrecognizedRun]


class LogParser:
    """Feed it log lines in order; it yields game events."""

    def __init__(self, merchants: Collection[str] = ()) -> None:
        self.merchants = frozenset(merchants)
        self.hero: Optional[str] = None  # last hero selected in the menu
        self.in_run = False
        self.day = 0
        self.in_pvp = False
        self.state = ""
        self.encounter = ""  # template guid of the encounter picked most recently
        self.monster: Optional[str] = None  # hour-3 monster being fought (None for event fights)
        self.in_combat = False
        self.pvp_exit_tasks = False
        self.conceded = False
        self.warned_unrecognized = False
        self.runs_started = 0  # runs started so far in this log

    def feed(self, line: str) -> Iterator[Event]:
        if match := VERSION_RE.search(line):
            yield GameVersion(match[1])
            return
        if match := HERO_RE.search(line):
            self.hero = HERO_ALIASES.get(match[1], match[1])
            if not self.in_run:
                yield HeroSelected(self.hero)
            return
        if RUN_READY_RE.search(line):
            self.in_run, self.day, self.in_pvp, self.conceded = True, 1, False, False
            self.runs_started += 1
            yield RunStarted(self.hero or "Unknown", self.runs_started - 1)
            yield DayReached(1)
            return
        if match := STATE_RE.search(line):
            old, new = match[1], match[2]
            self.state = new
            if old in CHOICE_STATES and new != old and self.in_run:
                yield EncounterLeft()
            if new in ("PVPCombatState", "CombatState"):
                self.in_pvp = new == "PVPCombatState"
                self.in_combat = new == "CombatState"
                self.pvp_exit_tasks = False
                self.monster = None
                if self.in_run:
                    yield FightStarted(self.in_pvp)
                elif not self.warned_unrecognized:
                    self.warned_unrecognized = True
                    yield UnrecognizedRun()
                return
            if old == "ReplayState" and new != "ReplayState" and self.in_combat:
                self.in_combat = False
                if self.monster and self.in_run:
                    yield MonsterFought(self.monster, self.day, new == "LootState")
                self.monster = None
            if new in ("EndRunVictoryState", "EndRunDefeatState"):
                if self.in_run:
                    if self.in_pvp:
                        yield PvPFought(self.day, new == "EndRunVictoryState", self.pvp_exit_tasks)
                    yield RunEnded(new == "EndRunVictoryState", self.day, self.conceded)
                self.in_run = self.in_pvp = False
            elif old == "ReplayState" and self.in_pvp:
                # the replay of the day's PvP fight finished and the run goes on
                self.in_pvp = False
                if self.in_run:
                    yield PvPFought(self.day, None, self.pvp_exit_tasks)
                    self.day += 1
                    yield DayReached(self.day)
            return
        if not self.in_run:
            return
        if match := GAIN_RE.search(line):
            bought = self.state == "EncounterState" and self.encounter in self.merchants
            yield CardGained(match[2].lower(), match[1], bought)
        elif match := ENCOUNTER_RE.search(line):
            self.encounter = match[2].lower()
            if match[1] in ("enc", "ste", "ped"):
                yield EncounterEntered(self.encounter)
            elif match[1] == "com" and self.in_combat:
                self.monster = self.encounter  # the monster picked at hour 3 (event fights have no com_ pick)
        elif CONCEDE_RE.search(line):
            self.conceded = True
        elif match := SOLD_RE.search(line):
            yield CardSold(match[1])
        elif self.in_pvp and EXIT_TASKS_RE.search(line):
            self.pvp_exit_tasks = True

    def feed_all(self, lines) -> List[Event]:
        return [event for line in lines for event in self.feed(line)]


class LogTailer:
    """
    Incrementally reads a growing log file. Detects the game restarting (Unity truncates Player.log
    and moves the old one to Player-prev.log) and keeps partial lines until they're complete.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.offset = 0
        self.buffer = b""
        self.identity = None

    def _identity(self, stat: os.stat_result):
        # The creation time alone can survive a restart (NTFS keeps it for a file re-created under the same name
        # within seconds), so the session's first timestamp is part of it.
        return getattr(stat, "st_birthtime", None) or stat.st_ctime, log_session(self.path)

    def read_new_lines(self) -> Optional[List[str]]:
        """Returns new complete lines, [] if nothing new, or None if the log was restarted (call again)."""
        try:
            stat = os.stat(self.path)
        except FileNotFoundError:
            return []
        identity = self._identity(stat)
        if self.identity is not None and (identity != self.identity or stat.st_size < self.offset):
            self.identity, self.offset, self.buffer = identity, 0, b""
            return None
        self.identity = identity
        if stat.st_size == self.offset:
            return []
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read(stat.st_size - self.offset)
        except OSError:  # e.g. the game moving the log aside at this very moment: try again next time
            return []
        self.offset += len(chunk)
        data = self.buffer + chunk
        lines = data.split(b"\n")
        self.buffer = lines.pop()
        return [line.decode("utf-8", errors="replace").rstrip("\r").lstrip("﻿") for line in lines]


def log_session(path: str) -> Optional[str]:
    """Which game session a log is from: the time on its first timestamped line (None until there is one). Used to
    tell a resumed run from a new one, since the log has no run ids."""
    try:
        with open(path, "rb") as f:
            match = STAMP_RE.search(f.read(65536))
    except OSError:
        return None
    return match.group(1).decode() if match else None

