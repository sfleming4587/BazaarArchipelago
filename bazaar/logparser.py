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
"""
import os
import re
from dataclasses import dataclass
from typing import Iterator, List, Optional, Union

DEFAULT_LOG_PATH = os.path.join(os.path.expandvars("%USERPROFILE%"), "AppData", "LocalLow", "Tempo Storm",
                                "The Bazaar", "Player.log")

HERO_RE = re.compile(r"Changing EHero to (\w+)")
RUN_READY_RE = re.compile(r"\[StartRunAppState\] Run initialization finalized")
STATE_RE = re.compile(r"\[AppState\] State changed from \[(\w+)\] to \[(\w+)\]")
PURCHASE_RE = re.compile(r"Card Purchased: InstanceId: (itm_\S+) - TemplateId([0-9a-fA-F-]{36}) - Target:\S+ - "
                         r"Section(Player|Storage)")

# EHero enum names that differ from the display names used by the apworld
HERO_ALIASES = {"Pyg": "Pygmalien", "Dragons": "The Dragons", "Hero8": "The Dragons", "TheDragons": "The Dragons"}


@dataclass(frozen=True)
class RunStarted:
    hero: str


@dataclass(frozen=True)
class DayReached:
    day: int


@dataclass(frozen=True)
class CardBought:
    guid: str


@dataclass(frozen=True)
class RunEnded:
    victory: bool
    day: int


Event = Union[RunStarted, DayReached, CardBought, RunEnded]


class LogParser:
    """Feed it log lines in order; it yields game events."""

    def __init__(self) -> None:
        self.hero: Optional[str] = None  # last hero selected in the menu
        self.in_run = False
        self.day = 0
        self.in_pvp = False

    def feed(self, line: str) -> Iterator[Event]:
        if match := HERO_RE.search(line):
            self.hero = HERO_ALIASES.get(match[1], match[1])
            return
        if RUN_READY_RE.search(line):
            self.in_run, self.day, self.in_pvp = True, 1, False
            yield RunStarted(self.hero or "Unknown")
            yield DayReached(1)
            return
        if match := STATE_RE.search(line):
            old, new = match[1], match[2]
            if new == "PVPCombatState":
                self.in_pvp = True
            elif new in ("EndRunVictoryState", "EndRunDefeatState"):
                if self.in_run:
                    yield RunEnded(new == "EndRunVictoryState", self.day)
                self.in_run = self.in_pvp = False
            elif old == "ReplayState" and self.in_pvp:
                # the replay of the day's PvP fight finished and the run goes on
                self.in_pvp = False
                if self.in_run:
                    self.day += 1
                    yield DayReached(self.day)
            return
        if self.in_run and (match := PURCHASE_RE.search(line)):
            yield CardBought(match[2].lower())

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
        return getattr(stat, "st_birthtime", None) or stat.st_ctime

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
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            chunk = f.read(stat.st_size - self.offset)
        self.offset += len(chunk)
        data = self.buffer + chunk
        lines = data.split(b"\n")
        self.buffer = lines.pop()
        return [line.decode("utf-8", errors="replace").rstrip("\r").lstrip("﻿") for line in lines]
