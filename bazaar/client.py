"""
The Bazaar Archipelago client.

Watches The Bazaar's own Player.log (read-only) and turns what it sees into Archipelago checks. It also reads
what the shop is offering from the game's memory (read-only, see memreader.py and docs/MEMORY-READER.md) to put a
padlock on locked cards. It never modifies the game, talks to Tempo's servers or sends input to the game.
Locked heroes/cards and received DeathLinks are enforced by the player (honor system) with the client's help.
"""
import asyncio
import dataclasses
import json
import os
import random
import sys
from typing import Any, Dict, Optional, Set

import Utils
from CommonClient import (ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, handle_url_arg,
                          logger, server_loop)
from MultiServer import mark_raw
from NetUtils import ClientStatus

from .data import (CARDS, CARDS_BY_GUID, GAME_VERSION, HEROES, MERCHANT_DATA, MONSTERS, OFFER_DATA,
                   TIERS)
from .items import (GAME, HERO_ITEM_IDS, LOCK_BYPASS_ID, SELL_TRAP, SELL_TRAP_ID, UNLOCKS, hero_item,
                    item_id_to_name, item_name_to_id, lock_items_by_hero)
from .locations import (card_requirements, day_location, hero_checks, location_name_to_id, monster_location,
                        pvp_location, win_location)
from .logparser import (DEFAULT_LOG_PATH, PREV_LOG, HeroSelected, CardGained, CardSold, DayReached, EncounterEntered,
                        EncounterLeft, FightStarted, GameVersion, LogParser, LogTailer, MonsterFought, PvPFought,
                        RunEnded, RunStarted, UnrecognizedRun, log_session)
from .memreader import GAME_EXE, NotReady, Reader, ReaderOff, Snapshot, find_pid
from .merchants import possible_stock
from .overlay import FILE_ONLY, ROW_GAPS  # FILE_ONLY: to the log file only, not the console or the client window

POLL_SECONDS = 0.5
MEMORY_SECONDS = 0.06  # how often the board's on-screen flags are read (hover, drag, stash, dialog)
SNAPSHOT_EVERY = 5  # ...and what's on offer, every this many of those
MEMORY_RETRY = (5, 30)  # seconds before trying the reader again: game not running yet / a check failed
STATE_FILE = "bazaar_client_state.json"

SHOP_CARDS = [c for c in CARDS if c.shop]
GUIDE_MAX = 300  # the Shop Guide skips deals that could be almost anything (hundreds of pictures)
# what the client assumes when a seed's slot_data lacks a setting (older apworlds); read through BazaarContext.setting()
SLOT_DEFAULTS = {"heroes": [], "max_day": 15, "pvp_win_checks": False, "monster_tiers": {}, "heroes_required": 1,
                 "lock_items": [], "logic": None, "death_link": False, "death_link_amnesty": 0, "sell_trap_days": 2,
                 "death_link_on_concede": False}


def own_popup(item_id: int) -> bool:
    """Items announced by their own pop-up (UNLOCKED, a Sell Trap, a Lock Bypass) rather than the generic ones."""
    return item_id in UNLOCKS or item_id in HERO_ITEM_IDS or item_id in (SELL_TRAP_ID, LOCK_BYPASS_ID)


def items_on_screen(snapshot: Optional[Snapshot]) -> Optional[tuple]:
    """The items offered on screen right now, left to right, as read from memory; None unless it's a row of items on
    a screen whose layout is known (ROW_GAPS) - e.g. a skill choice, or memory being off."""
    if not snapshot or snapshot.state not in ROW_GAPS or not snapshot.offers:
        return None
    if any(offer.kind != "Item" or offer.template is None for offer in snapshot.offers):
        return None
    return snapshot.offers


def offers_at(snapshot: Optional[Snapshot], guid: str) -> Optional[tuple]:
    """The items on offer at this merchant/event (the one the log says you're at); None if memory can't say."""
    items = items_on_screen(snapshot)
    return items if items and snapshot.state == "Encounter" and snapshot.encounter == guid else None


def default_log_path() -> str:
    try:
        from . import BazaarWorld
        # an empty setting resolves to Archipelago's own folder, so only trust it if it names an actual file
        configured = str(BazaarWorld.settings.log_path or "")
        if os.path.isfile(configured):
            return configured
    except Exception:  # settings unavailable, e.g. host.yaml not writable
        pass
    return DEFAULT_LOG_PATH


def beep() -> None:
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass


class BazaarCommandProcessor(ClientCommandProcessor):
    ctx: "BazaarContext"

    def _cmd_status(self) -> bool:
        """Show your heroes, the current run and goal progress."""
        self.ctx.print_status()
        return True

    @mark_raw  # the whole text as typed: hero names can have spaces ("The Dragons")
    def _cmd_locked(self, hero: str = "") -> bool:
        """List cards that are still locked (and where they are, if you have a hint). E.g. /locked Vanessa"""
        hero = hero.strip()
        hints = self.ctx.locked_card_hints()
        names = sorted(CARDS_BY_GUID[g].name + f" ({CARDS_BY_GUID[g].hero})" + (f"  -> {hints[g]}" if g in hints else "")
                       for g in self.ctx.locked_guids()
                       if (not hero or CARDS_BY_GUID[g].hero.lower() == hero.lower()))
        self.output(f"{len(names)} locked card(s):" if names else "No locked cards.")
        for name in names:
            self.output(f"  {name}")
        return True

    def _cmd_where(self, *card: str) -> bool:
        """Where is a locked card? Only answers if you already got a hint for it through Archipelago."""
        wanted = " ".join(card).strip().lower()
        guid = next((g for g in self.ctx.locked_guids() if CARDS_BY_GUID[g].name.lower() == wanted),
                    None)
        if not guid:
            self.output("That isn't one of your locked cards (see /locked).")
            return False
        hint = self.ctx.locked_card_hints().get(guid)
        if hint:
            self.output(f"{CARDS_BY_GUID[guid].name}: {hint}")
            return True
        self.output(f"No hint for {CARDS_BY_GUID[guid].name} yet. Get one through Archipelago "
                    f"(e.g. !hint {self.ctx.unlock_item_for(guid)}) and it will show here and in /locked.")
        return False

    def _cmd_unblock(self, confirm: str = "") -> bool:
        """Emergency only, if something broke: /unblock shows what's blocking checks; /unblock confirm clears it all
        for the current run (locked cards held, Sell Traps, a DeathLink owed, a locked hero)."""
        reason = self.ctx.blocked_reason()
        if confirm.lower() != "confirm":
            self.output(f"Checks are blocked {reason}." if reason else "Nothing is blocking checks right now.")
            if reason:
                self.output("If this is wrong (something broke), type: /unblock confirm")
            return True
        if not reason:
            self.output("Nothing to clear.")
            return True
        self.ctx.clear_blocks()
        self.output("All blocks for this run were cleared by hand.")
        return True

    def _cmd_tracker(self) -> bool:
        """Open or close the tracker (also the Tracker button on the overlay)."""
        if not self.ctx.overlay or not self.ctx.overlay.available:
            self.output("The tracker needs the overlay, which can't open on this PC.")
            return False
        self.ctx.overlay.toggle_tracker()
        return True

    @mark_raw  # the whole text as typed: Windows paths have backslashes and spaces (review 2026-09-30)
    def _cmd_logpath(self, path: str = "") -> bool:
        """Show or change the path of The Bazaar's Player.log."""
        path = path.strip().strip('"')
        if path and not os.path.isfile(path):
            self.output(f"No file at {path} - still watching {self.ctx.log_path}")
            return False
        if path:
            self.ctx.log_path = path
            self.ctx.restart_watcher = True
        self.output(f"Watching: {self.ctx.log_path}")
        return True


class BazaarContext(CommonContext):
    game = GAME
    items_handling = 0b111
    command_processor = BazaarCommandProcessor
    want_slot_data = True

    def __init__(self, server_address: Optional[str] = None, password: Optional[str] = None) -> None:
        super().__init__(server_address, password)
        self.slot_data: Dict[str, Any] = {}
        self.log_path = default_log_path()
        self.restart_watcher = False
        self.run: Dict[str, Any] = {}  # persisted: hero, day, counting, tainted, deathlink_owed
        self.defeats_since_death = 0
        self.goal_sent = False
        self.overlay = None
        self.shop_guide = True  # the picture window next to the game; --no-shop-guide turns it off
        self.notices_shown: Set[str] = set()  # patch warnings are shown once per session
        self.traps_seen = 0
        self.bypasses_used = 0  # Lock Bypasses spent; the rest of those received are ready
        self.watched: Dict[str, Any] = {}  # {"log": game session, "runs": runs of that log already seen}
        # {"log": game session, "events": how many of its events were handled}: a reconnect carries on from here
        # instead of judging the run again with today's unlocks (review 2026-09-30)
        self.position: Dict[str, Any] = {}
        self.caught_up = False  # the log has been read up to now since connecting: received Sell Traps can start
        self.quiet = False  # replaying runs that ended while the client wasn't watching: no alerts, no DeathLinks
        self.encounter: Optional[EncounterEntered] = None  # the merchant or event you're at, if any
        self.memory: Optional[Snapshot] = None  # what memory says is on screen now; None while the reader is off
        # the row the padlocks are laid out on: (screen, ((instance id, size), ...)). Bought cards leave a gap - the
        # others don't move (user, 2026-10-01) - so it's only replaced when new cards come in
        self.padlock_row: Optional[tuple] = None
        self.board_ui = None  # memreader.BoardUI: hover/drag/stash/dialog/reveal, None if unreadable
        self.menu_hero: Optional[str] = None  # hero picked on the hero-select screen, while not in a run
        self.room_seed = ""  # CommonClient never sets seed_name, so the saved state is keyed on this instead
        self.log_session: Optional[str] = None  # which game session the log being read is from (see log_session)

    # --- connection ---------------------------------------------------------------------------------------------

    async def server_auth(self, password_requested: bool = False) -> None:
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict) -> None:
        if cmd == "RoomInfo":
            self.room_seed = args.get("seed_name", "")
        elif cmd == "Connected":
            self.slot_data = args.get("slot_data") or {}
            self.load_state()
            Utils.async_start(self.update_death_link(bool(self.setting("death_link"))))
            logger.info(f"Watching {self.log_path}", extra=FILE_ONLY)
        elif cmd == "ReceivedItems":
            for item in args["items"]:
                name = self.item_names.lookup_in_game(item.item)
                if item.item in UNLOCKS or item.item in HERO_ITEM_IDS:
                    logger.info(f"Unlocked: {name}", extra=FILE_ONLY)
                    if self.overlay and args.get("index", 0) > 0:  # index 0 = the full list resent on connect
                        self.overlay.toast(f"UNLOCKED: {HERO_ITEM_IDS.get(item.item, name)}  (from {self.who(item.player)})")
                elif item.item == LOCK_BYPASS_ID and args.get("index", 0) > 0:
                    self.event("Lock Bypass received: use it on a locked card you're holding (the button next to it).")
                    self.toast(f"LOCK BYPASS from {self.who(item.player)}! Use it on a locked card you're holding.",
                               seconds=12)
            self.refresh_held()
            if self.encounter:  # an unlock that arrives while you're in a shop takes it off the list at once
                self.handle_encounter(self.encounter)
            self.refresh_padlocks()  # ...and its padlock away, on any screen
            self.receive_traps()
            self.update_status()
        elif cmd == "RoomUpdate" and "checked_locations" in args:
            self.check_goal()
            self.update_status()

    def on_print_json(self, args: dict) -> None:
        super().on_print_json(args)
        if self.overlay and args.get("type") == "ItemSend" and args["item"].player == self.slot:
            # one of your checks found an item: say what and for whom (unlocks you get yourself already pop up
            # as UNLOCKED, and Sell Traps have their own pop-up)
            item, receiver = args["item"], args["receiving"]
            name = self.item_names.lookup_in_slot(item.item, receiver)
            if receiver != self.slot:
                self.overlay.toast(f"SENT: {name} to {self.who(receiver)}")
            elif not own_popup(item.item):
                self.overlay.toast(f"FOUND: {name}  (in {self.who(self.slot)})")
        elif self.overlay and args.get("type") == "ItemSend" and args["receiving"] == self.slot:
            # someone else found something for you; unlocks and Sell Traps have their own pop-ups
            item = args["item"]
            name = self.item_names.lookup_in_slot(item.item, self.slot)
            if not own_popup(item.item):
                self.overlay.toast(f"RECEIVED: {name}  (from {self.who(item.player)})")

    def who(self, slot: int) -> str:
        """The other side of an item, from Archipelago's player list, for the pop-ups."""
        return "your own world" if slot == self.slot else self.player_names.get(slot, "another player")

    def reset_server_state(self) -> None:
        """Also on an unexpected drop: without slot_data the log watcher pauses (no unlocks are known while
        disconnected, so nothing could be judged), then replays the log once connected again."""
        super().reset_server_state()
        self.slot_data = {}
        self.caught_up = False

    async def disconnect(self, allow_autoreconnect: bool = False) -> None:
        # a different room may follow: nothing from this one (checks, goal, the hero on the menu) may leak into it
        self.locations_checked = set()
        self.goal_sent = self.finished_game = False
        self.menu_hero = None
        await super().disconnect(allow_autoreconnect)

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "Archipelago The Bazaar Client"
        return ui

    # --- persistence --------------------------------------------------------------------------------------------

    def state_key(self) -> str:
        return f"{self.room_seed}:{self.slot}"

    def load_state(self) -> None:
        try:
            with open(Utils.user_path(STATE_FILE), encoding="utf-8") as f:
                saved = json.load(f).get(self.state_key(), {})
        except (FileNotFoundError, ValueError):
            saved = {}
        self.run = saved.get("run", {})
        self.defeats_since_death = saved.get("defeats_since_death", 0)
        self.traps_seen = saved.get("traps_seen", 0)  # Sell Traps already handled (items_received is resent)
        self.bypasses_used = saved.get("bypasses_used", 0)
        # state saved before "watched" existed: the tracked run is the last one seen
        self.position = saved.get("position", {})
        self.watched = saved.get("watched") or ({"log": self.run["log"], "runs": self.run["run_index"] + 1}
                                                if self.run.get("log") else {})

    def save_state(self) -> None:
        path = Utils.user_path(STATE_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                everything = json.load(f)
        except (FileNotFoundError, ValueError):
            everything = {}
        everything[self.state_key()] = {"run": self.run, "defeats_since_death": self.defeats_since_death,
                                        "traps_seen": self.traps_seen, "bypasses_used": self.bypasses_used,
                                        "watched": self.watched, "position": self.position}
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(everything, f, indent=1)
        os.replace(path + ".tmp", path)  # a crash mid-write can't corrupt it (that would re-fire every Sell Trap)

    # --- unlocks ------------------------------------------------------------------------------------------------

    def received_ids(self) -> Set[int]:
        return {item.item for item in self.items_received}

    def hero_unlocked(self, hero: str) -> bool:
        return item_name_to_id.get(hero_item(hero)) in self.received_ids()

    def unlock_item_for(self, guid: str) -> str:
        """The name of the item (card, pack or group) in this seed that unlocks a locked card."""
        received = self.received_ids()
        for item_id in self.setting("lock_items"):
            if item_id not in received and guid in UNLOCKS.get(item_id, set()):
                return self.item_names.lookup_in_game(item_id)
        return CARDS_BY_GUID[guid].name

    def locked_card_hints(self) -> Dict[str, str]:
        """Locked card guid -> "Player's location" for every hint you have that hasn't been found yet."""
        found: Dict[str, str] = {}
        for hint in self.stored_data.get(f"_read_hints_{self.team}_{self.slot}") or []:
            if hint.get("receiving_player") != self.slot or hint.get("found"):
                continue
            guids = UNLOCKS.get(hint.get("item"))
            if not guids:
                continue
            finder = hint.get("finding_player")
            where = f"{self.player_names.get(finder, 'someone')}'s "                     f"{self.location_names.lookup_in_slot(hint.get('location'), finder)}"
            for guid in guids:
                found.setdefault(guid, where)
        return found

    def locked_guids(self) -> Set[str]:
        received = self.received_ids()
        locked: Set[str] = set()
        for item_id in self.setting("lock_items"):
            if item_id not in received:
                locked |= UNLOCKS.get(item_id, set())
        return locked

    def bypasses_ready(self) -> int:
        return sum(item.item == LOCK_BYPASS_ID for item in self.items_received) - self.bypasses_used

    def use_bypass(self, guid: str) -> None:
        """The "Use Bypass" button next to a locked card you're holding: that card (its copies and upgrades too) is
        allowed for the rest of the run, using up one Lock Bypass. The only way a bypass is spent, and only on a card
        that's blocking checks (user, 2026-09-30) - never automatically, so one isn't lost on a card you didn't
        realise was locked. Checked again here: the button may be a moment behind."""
        if not self.run.get("active") or self.bypasses_ready() <= 0 or guid not in self.run.get("held", {}).values():
            self.event("That Lock Bypass doesn't apply any more (no bypass ready, or the card isn't held).")
            return
        self.bypasses_used += 1
        self.run.setdefault("bypassed", []).append(guid)
        self.event(f"Lock Bypass used: {self.held_text(guid)} is allowed for the rest of this run.")
        self.toast(f"LOCK BYPASS USED: {CARDS_BY_GUID[guid].name} is yours for this run", seconds=12)
        self.refresh_held()  # every copy of it you hold stops blocking checks
        if self.encounter:  # the shop warning and the Shop Guide show it as allowed now
            self.handle_encounter(self.encounter)
        self.refresh_padlocks()
        self.update_status()

    def run_locked_guids(self) -> Set[str]:
        """Cards you may not hold in this run: the locked ones, minus those a Lock Bypass allowed for this run."""
        return self.locked_guids() - set(self.run.get("bypassed", []))

    # --- game events --------------------------------------------------------------------------------------------

    def resumes(self, event: RunStarted) -> bool:
        """Is this run start the run we were tracking, carried on? The log has no run ids, so: in the same game
        session it must be the same run of the log; after a game restart it must be the new log's first run, and
        only if the previous session's log shows that run was left unfinished (the game resumes an unfinished
        run - you can't start another until it's over)."""
        saved = self.run
        if not saved.get("active") or saved.get("hero") != event.hero or not self.log_session:
            return False
        if saved.get("log") == self.log_session:
            return saved.get("run_index") == event.index
        return event.index == 0 and run_left_open(os.path.join(os.path.dirname(self.log_path), PREV_LOG), saved)

    def handle_run_started(self, event: RunStarted) -> None:
        if self.resumes(event):
            if self.run["log"] != self.log_session:  # a restarted game: the new log counts days from 1 again
                self.run.update(log=self.log_session, run_index=event.index, day_offset=self.run["day"] - 1)
                self.watched = {"log": self.log_session, "runs": event.index + 1}
            self.event(f"Resumed your {event.hero} run on day {self.run['day']}.")
            return
        if self.run.get("active"):
            self.event(f"Your previous {self.run['hero']} run ended while the client wasn't watching.")
        counting = True
        if event.hero == "Unknown":
            self.notice("hero:?", "The client couldn't tell which hero this run is with, so it doesn't count.")
        elif event.hero not in HEROES:
            self.notice(f"hero:{event.hero}", f"{event.hero} is newer than this apworld, so it isn't part of this "
                                              f"seed.")
        if event.hero not in self.setting("heroes"):
            self.event(f"CHECKS ARE BLOCKED: {event.hero} isn't part of this multiworld.", warning=True)
            counting = False
        elif not self.hero_unlocked(event.hero):
            self.event(f"CHECKS ARE BLOCKED: {event.hero} IS LOCKED. Abandon this run.", warning=True)
            self.beep()
            counting = False
        else:
            self.event(f"Started a run with {event.hero}. Good luck!")
        # "legal" = a hero you're allowed to play. Only legal runs send DeathLinks when lost; losing a
        # run you were told to abandon shouldn't kill your friends.
        # A new run is a clean slate: nothing from an earlier run (held cards, DeathLink, PvP questions) carries over.
        self.watched = {"log": self.log_session, "runs": event.index + 1}
        self.run = {"active": True, "hero": event.hero, "day": 1, "counting": counting, "legal": counting,
                    "deathlink_owed": False, "held": {}, "inventory": {}, "traps": [],
                    "log": self.log_session, "run_index": event.index, "day_offset": 0}
        self.refresh_held()
        self.update_status()

    async def handle_day(self, event: DayReached) -> None:
        if not self.run.get("active"):
            return
        # send the day's own check before moving the day on, so a Sell Trap due today doesn't block reaching it
        if event.day <= self.setting("max_day"):
            await self.send_run_checks([day_location(self.run["hero"], event.day)])
        self.run["day"] = event.day
        self.save_state()
        self.update_status()
        if any(t["deadline"] == event.day for t in self.run.get("traps", [])):
            self.beep()
            self.update_block_banner()

    def held_text(self, guid: str) -> str:
        return f"{CARDS_BY_GUID[guid].name} ({CARDS_BY_GUID[guid].hero})"

    def refresh_held(self) -> None:
        """Drop held cards that got unlocked in the meantime, then update the overlay and save."""
        held = self.run.get("held", {})
        locked = self.run_locked_guids()
        for instance, guid in list(held.items()):
            if guid not in locked:
                del held[instance]
                self.event(f"{CARDS_BY_GUID[guid].name} is unlocked now, you can keep it.")
        self.update_block_banner()
        if self.run:
            self.save_state()

    def receive_traps(self) -> None:
        """Start every Sell Trap received since last time (the server resends all items on connect). Not before the
        log is read up to now: a trap that arrived while disconnected gets today's day and today's items."""
        if not self.caught_up:
            return
        traps = [item for item in self.items_received if item.item == item_name_to_id[SELL_TRAP]]
        while self.traps_seen < len(traps):
            self.traps_seen += 1
            self.start_trap(self.who(traps[self.traps_seen - 1].player))
        self.save_state()

    def start_trap(self, sender: str = "another player") -> None:
        """Pick a random item the player holds; it must be sold before the deadline day starts."""
        targeted = {t["instance"] for t in self.run.get("traps", [])}
        choices = [i for i in self.run.get("inventory", {}) if i not in targeted] if self.run.get("active") else []
        if not choices:  # not in a run, or holding nothing it can target: the trap misses
            self.event("Sell Trap DODGED - you had nothing it could make you sell.")
            self.toast(f"Sell Trap from {sender} DODGED!")
            return
        instance = random.choice(choices)
        guid = self.run["inventory"][instance]
        deadline = self.run.get("day", 1) + self.setting("sell_trap_days")
        self.run.setdefault("traps", []).append({"instance": instance, "guid": guid, "deadline": deadline})
        name = self.card_name(guid)
        self.event(f"SELL TRAP! Sell {name} before day {deadline} starts, or checks get blocked.", warning=True)
        self.beep()
        self.toast(f"SELL TRAP from {sender}! Sell {name} before day {deadline} starts.", seconds=15)
        self.update_block_banner()

    def card_name(self, guid: str) -> str:
        return CARDS_BY_GUID[guid].name if guid in CARDS_BY_GUID else "that new item"

    def overdue_traps(self) -> list:
        return [t for t in self.run.get("traps", []) if self.run.get("day", 1) >= t["deadline"]]

    def notice(self, key: str, text: str) -> None:
        """A patch-related warning, shown once per session in the client and above the game."""
        if key in self.notices_shown:
            return
        self.notices_shown.add(key)
        self.event(text, warning=True)
        self.toast(text, seconds=12)

    def handle_version(self, event: GameVersion) -> None:
        if GAME_VERSION != "unknown" and event.version != GAME_VERSION:
            self.notice("version", f"The Bazaar was updated (this apworld was made for {GAME_VERSION}, you have "
                                   f"{event.version}). Everything keeps working; anything the patch added just "
                                   f"isn't part of this seed. A newer apworld will include it.")

    def handle_unrecognized_run(self) -> None:
        self.notice("format", "The client can't recognise run starts in The Bazaar's log anymore (probably a patch). "
                              "Checks can't be detected until the apworld is updated.")

    def blocked_reason(self) -> Optional[str]:
        """Why checks can't be sent right now, or None. Every check a run can earn goes through this."""
        if not self.run.get("active"):
            return None
        if self.run.get("deathlink_owed"):
            return "- DEATHLINK: ABANDON THIS RUN"
        if self.run.get("concede_reason"):
            return self.run["concede_reason"]
        if not self.run.get("counting"):
            return f"- {self.run.get('hero', 'this hero').upper()} IS LOCKED: ABANDON THIS RUN"
        names = sorted({CARDS_BY_GUID[g].name.upper() for g in self.run.get("held", {}).values()}
                       | {self.card_name(t["guid"]).upper() for t in self.overdue_traps()})
        if names:
            return f"UNTIL {' AND '.join(names)} {'IS' if len(names) == 1 else 'ARE'} SOLD"
        return None

    def clear_blocks(self) -> None:
        """/unblock confirm: an escape hatch if tracking breaks. Logged so it's never silent."""
        logger.warning(f"Blocks cleared by hand (/unblock): {self.blocked_reason()}")
        allowed = self.run.get("hero") in self.setting("heroes")  # a hero outside the seed never counts
        self.run.update(held={}, traps=[], deathlink_owed=False, counting=allowed, legal=allowed, concede_reason=None)
        self.save_state()
        self.update_block_banner()

    def update_block_banner(self) -> None:
        if self.overlay:
            reason = self.blocked_reason()
            held = self.run.get("held", {}) if self.run.get("active") else {}
            bypass = self.bypasses_ready() > 0  # each held card gets a "Use Bypass" button
            lines = [(f"{self.held_text(g)} - SELL OR USE BYPASS", g) if bypass else self.held_text(g)
                     for g in held.values()]
            upcoming = [t for t in self.run.get("traps", []) if t not in self.overdue_traps()] \
                if self.run.get("active") else []
            lines += [f"Sell Trap: sell {self.card_name(t['guid'])} before day {t['deadline']} starts"
                      for t in upcoming]
            title = f"CHECKS ARE BLOCKED {reason}" if reason else ("SELL TRAP" if upcoming else None)
            self.overlay.show_locked(title, lines, blocked=bool(reason))

    async def send_run_checks(self, names) -> None:
        """The only way checks earned in a run are sent: refused while cheating (locked hero or locked card)."""
        reason = self.blocked_reason()
        if reason:
            self.event(f"CHECKS ARE BLOCKED {reason}. Not sent: {', '.join(names)}", warning=True)
            self.beep()
            self.toast(f"CHECK NOT SENT: {', '.join(names)}", seconds=10, warning=True)
            return
        await self.send_checks(names)

    def handle_gain(self, event: CardGained) -> None:
        if self.run.get("active"):
            self.run.setdefault("inventory", {})[event.instance] = event.guid
        if event.guid not in CARDS_BY_GUID:
            self.notice("card", "You got a card this apworld doesn't track (a special item like Midsworth's Package, "
                                "or one added by a patch). It's never locked.")
        if not self.run.get("active") or event.guid not in self.run_locked_guids():
            return
        self.run.setdefault("held", {})[event.instance] = event.guid
        how = "bought" if event.bought else "got"
        self.event(f"You {how} {self.held_text(event.guid)}, which is still locked! "
                   "CHECKS ARE BLOCKED until you sell it.", warning=True)
        self.beep()
        what = "SELL OR USE BYPASS" if self.bypasses_ready() > 0 else "SELL IT NOW"
        self.toast(f"{what}: {CARDS_BY_GUID[event.guid].name} is locked", seconds=12, warning=True)
        self.refresh_held()

    def handle_sold(self, event: CardSold) -> None:
        self.run.get("inventory", {}).pop(event.instance, None)
        traps = self.run.get("traps", [])
        if any(t["instance"] == event.instance for t in traps):
            self.run["traps"] = [t for t in traps if t["instance"] != event.instance]
            self.event("Sell Trap done.")
            self.toast("Sell Trap done!")
            self.update_block_banner()
            self.save_state()
        guid = self.run.get("held", {}).pop(event.instance, None)
        if guid:
            self.event(f"Sold {CARDS_BY_GUID[guid].name}." + ("" if self.run.get("held") else " Checks unblocked."))
            self.refresh_held()

    def handle_fight(self, event: FightStarted) -> None:
        held = self.run.get("held", {})
        if not self.run.get("active") or not held:
            return
        names = ", ".join(CARDS_BY_GUID[g].name for g in held.values())
        self.beep()
        self.event(f"You went into a fight holding locked cards ({names}). Nothing from this fight counts.",
                   warning=True)

    def handle_snapshot(self, snapshot: Optional[Snapshot]) -> None:
        """A new reading from memory (None: the reader is off). The padlocks are redone when what's on screen
        changed; the shop warning when what's on offer at the current merchant did (you bought a card, rerolled, or
        memory caught up with the log)."""
        before, self.memory = self.memory, snapshot
        seen = lambda s: (s.state, items_on_screen(s), s.level) if s else None
        if seen(before) != seen(snapshot):
            self.refresh_padlocks()
        if self.encounter and offers_at(before, self.encounter.guid) != offers_at(snapshot, self.encounter.guid):
            self.handle_encounter(self.encounter)

    def refresh_padlocks(self) -> None:
        """A padlock on each locked item on screen (shops, level-ups: whatever ROW_GAPS knows). Driven by memory
        alone, so a screen the log never mentions works the same. Cards keep their places when one is bought (user,
        2026-10-01), so the row stays as it was until new cards come in; new cards flip over first, so their
        padlocks wait for that (overlay, by the game's own reveal flag)."""
        if not self.overlay:
            return
        snapshot, items = self.memory, items_on_screen(self.memory) if self.run.get("active") else None
        if not items:
            self.padlock_row = None
            self.overlay.show_padlocks(None, [], [])
            return
        here = {o.instance: o.template for o in items}
        row = self.padlock_row
        new = not (row and row[0] == snapshot.state and set(here) <= {instance for instance, _ in row[1]})
        if new:
            row = self.padlock_row = (snapshot.state, tuple(
                (o.instance, CARDS_BY_GUID[o.template].size if o.template in CARDS_BY_GUID else None) for o in items))
        locked = self.run_locked_guids()
        self.overlay.show_padlocks(row[0], [size for _, size in row[1]],
                                   [i for i, (instance, _) in enumerate(row[1]) if here.get(instance) in locked],
                                   reveal=new, level=snapshot.level)

    def handle_board_ui(self, ui) -> None:
        """The board's on-screen flags (memreader.BoardUI, or None): the padlocks hide or fade by them."""
        if ui != self.board_ui:
            self.board_ui = ui
            if self.overlay:
                self.overlay.show_board_ui(ui)

    def handle_encounter(self, event: EncounterEntered) -> None:
        merchant = MERCHANT_DATA.get(event.guid) or OFFER_DATA.get(event.guid)
        if not merchant or not self.run.get("active"):
            return
        self.encounter = event
        verb = "sell" if event.guid in MERCHANT_DATA else "offer"
        locked = self.run_locked_guids()
        stock = possible_stock(merchant["stock"], self.run["hero"], (CARDS_BY_GUID[g] for g in locked))
        offers = offers_at(self.memory, event.guid)
        if offers is not None:  # exactly what's on screen: only those are named (and padlocked, refresh_padlocks)
            names = [self.card_name(o.template) for o in offers if o.template in locked]
        else:
            names = sorted(c.name for c in stock)
        if names:
            how = "offers" if offers is not None else f"may {verb}"
            logger.info(f"{merchant['name']} {how} these locked cards: {', '.join(names)}", extra=FILE_ONLY)
        if self.overlay and (names or verb == "sell"):  # free choices only warn when something is locked
            self.overlay.show_shop(merchant["name"], names, verb, exact=offers is not None)
        elif self.overlay:  # memory says the locked card that was offered has gone
            self.overlay.show_shop(None, [])
        everything = possible_stock(merchant["stock"], self.run["hero"], SHOP_CARDS)
        if self.overlay and self.shop_guide and len(everything) <= GUIDE_MAX:
            allowed = [c for c in everything if c.guid not in locked]
            self.overlay.show_board(f"{merchant['name']} can stock {len(everything)} cards for {self.run['hero']}",
                                    allowed, stock)

    def handle_encounter_left(self) -> None:
        self.encounter = None
        if self.overlay:
            self.overlay.show_shop(None, [])
            if self.shop_guide:
                self.overlay.show_board(None, [], [])

    async def handle_monster(self, event: MonsterFought) -> None:
        if not self.run.get("active") or not event.won:
            return
        monster = MONSTERS.get(event.guid)
        if not monster:
            # added by a patch: its rarity is unknown, so it counts as the lowest rarity that day
            self.notice("monster", "You beat a monster this apworld doesn't know (added by a patch). "
                                   "It counts as a Bronze monster until the apworld is updated.")
            monster = {"name": "a new monster", "tier": "Bronze"}
        tiers = self.tiers(event.day)
        beaten = [t for t in tiers if TIERS.index(t) <= TIERS.index(monster["tier"])]
        self.event(f"Beat {monster['name']} ({monster['tier']}) on day {event.day}.")
        if beaten:
            await self.send_run_checks([monster_location(self.run["hero"], event.day, t) for t in beaten])

    async def handle_pvp(self, event: PvPFought) -> None:
        if not self.run.get("active") or not self.setting("pvp_win_checks"):
            return
        if event.day > self.setting("max_day"):
            return
        # Mid-run the log doesn't say who won, but "Waiting for N exit tasks" only follows a won fight: it matched
        # all 10 answers in the user's Karnok run (2026-09-28), so wins are counted from it (user: "yes on the pvp
        # win auto count").
        if event.won:
            await self.send_run_checks([pvp_location(self.run["hero"], event.day)])

    async def handle_run_end(self, event: RunEnded) -> None:
        if not self.run.get("active"):
            return
        hero = self.run["hero"]
        deathlink_owed = self.run.get("deathlink_owed")
        if event.victory:
            self.event(f"10 wins with {hero}!")
            # every day check and the 10-win check, plus PvP and monster checks of the days the run never reached
            await self.send_run_checks([c.name for c in hero_checks(hero, self.setting("max_day"), self.setting("pvp_win_checks"),
                                                                    self.tiers)
                                        if c.kind in ("day", "win") or c.day > event.day])
        self.run = {**self.run, "active": False, "held": {}}
        self.refresh_held()
        self.handle_encounter_left()
        self.update_status()
        if event.victory:
            pass  # a won run never sends a DeathLink
        elif deathlink_owed:
            self.event("Run over. DeathLink paid off.")
        elif event.conceded:
            if self.setting("death_link_on_concede"):
                await self.maybe_send_death(f"conceded on day {event.day}")
            else:
                self.event("Run conceded. Conceding doesn't send a DeathLink.")
        else:
            await self.maybe_send_death(f"ran out of prestige on day {event.day}")
        self.save_state()

    async def maybe_send_death(self, what: str) -> None:
        """Send a DeathLink unless it's off, the run doesn't count (locked hero / DeathLink owed) or amnesty applies."""
        legal = self.run.get("legal", True) and not self.run.get("deathlink_owed")
        if "DeathLink" not in self.tags or not legal:
            return
        if self.quiet:  # hours late, it would kill your friends for nothing they can see
            self.event(f"Your {self.run.get('hero', 'hero')} run {what} while the client wasn't connected: "
                       f"no DeathLink sent.")
            return
        self.defeats_since_death += 1
        amnesty = self.setting("death_link_amnesty")
        if self.defeats_since_death > amnesty:
            self.defeats_since_death = 0
            player = self.player_names.get(self.slot, "A Bazaar player")
            await self.send_death(f"{player}'s {self.run.get('hero', 'hero')} {what}.")
            self.event("DeathLink sent.")
        else:
            self.event(f"Forgiven by DeathLink amnesty ({self.defeats_since_death}/{amnesty}).")
        self.save_state()

    def on_deathlink(self, data: Dict[str, Any]) -> None:
        super().on_deathlink(data)
        beep()
        if self.run.get("active"):
            self.run["deathlink_owed"] = True
            self.save_state()
            self.update_block_banner()
            self.event("DEATHLINK! Abandon your current run now (Settings > Abandon Run). "
                       "No more checks count from this run.", warning=True)
            if self.overlay:
                self.overlay.show_deathlink(data.get("cause") or f"{data.get('source', 'Someone')} died.")
        else:
            self.event("DeathLink received while you weren't in a run. You're safe this time.")

    # --- checks & goal ------------------------------------------------------------------------------------------

    async def send_checks(self, names) -> None:
        ids = {location_name_to_id[n] for n in names if n in location_name_to_id}
        self.locations_checked |= ids
        await self.check_locations(ids)
        self.check_goal()

    def beep(self) -> None:
        if not self.quiet:
            beep()

    def toast(self, text: str, **kwargs) -> None:
        if self.overlay and not self.quiet:
            self.overlay.toast(text, **kwargs)

    def event(self, text: str, warning: bool = False) -> None:
        """A game event. The client window keeps strictly item history (user, 2026-09-28) since the overlay shows
        these; without an overlay they still show here."""
        if self.overlay and self.overlay.available:
            logger.info(text, extra=FILE_ONLY)
        else:
            (logger.warning if warning else logger.info)(text)

    def setting(self, key: str):
        """A setting of the connected seed (slot_data), or what older seeds meant when they didn't send it."""
        return self.slot_data.get(key, SLOT_DEFAULTS[key])

    def tiers(self, day: int) -> list:
        """The monster rarities with a check on this day (slot_data keys are strings after the server)."""
        return self.setting("monster_tiers").get(str(day), [])

    def done(self) -> Set[int]:
        return self.checked_locations | self.locations_checked

    def heroes_won(self) -> list:
        """Heroes whose 10-win check is done: the goal counts these (/status and the overlay show the same)."""
        return [h for h in self.setting("heroes") if location_name_to_id[win_location(h)] in self.done()]

    def check_goal(self) -> None:
        if self.goal_sent or not self.slot_data:
            return
        if len(self.heroes_won()) >= self.setting("heroes_required"):
            self.goal_sent = True
            self.finished_game = True
            Utils.async_start(self.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}]))
            logger.info("Goal complete! Congratulations, champion of the Bazaar.")

    def check_states(self, hero: str) -> Optional[list]:
        """[(Check, done, in logic)] for every check of a hero, from the same card requirements the world's rules
        use. The menu's hero list and the tracker both read this. None for seeds made before the client could
        tell (no "logic" in slot_data)."""
        logic = self.setting("logic")
        if not logic or "lock_items" not in self.slot_data:
            return None
        items = lock_items_by_hero(self.setting("lock_items"))[0].get(hero, [])
        received = {item_id_to_name.get(item.item) for item in self.items_received}
        have = len(set(items) & received)
        tiers = self.setting("monster_tiers")
        max_day, pvp = self.setting("max_day"), bool(self.setting("pvp_win_checks"))
        needs = card_requirements(hero, len(items), max_day, pvp, lambda day: tiers.get(str(day), []), logic)
        unlocked, done = self.hero_unlocked(hero), self.done()
        return [(check, location_name_to_id[check.name] in done, unlocked and have >= needs[check.name])
                for check in hero_checks(hero, max_day, pvp, lambda day: tiers.get(str(day), []))]

    def hero_progress(self, hero: str) -> Optional[tuple]:
        """(checks done, checks in logic) for the menu's hero list."""
        states = self.check_states(hero)
        if states is None:
            return None
        return sum(done for _, done, _ in states), sum(in_logic for _, _, in_logic in states)

    def tracker_data(self) -> Dict[str, dict]:
        """What the tracker shows: every hero (in the seed or not) and each check's colour. User's colour rules
        (2026-09-29): grey = done, green = in logic, yellow = out of logic, red = hero locked."""
        data: Dict[str, dict] = {}
        if not self.slot_data:
            return data
        for hero in HEROES:
            states = self.check_states(hero) if hero in self.setting("heroes") else None
            if states is None:
                data[hero] = {"in_seed": False, "unlocked": False, "checks": []}
                continue
            unlocked = self.hero_unlocked(hero)
            data[hero] = {"in_seed": True, "unlocked": unlocked, "checks": [
                (check.kind, check.day, check.tier, check.name,
                 "done" if done else "red" if not unlocked else "green" if in_logic else "yellow")
                for check, done, in_logic in states]}
        return data

    def status_line(self) -> tuple:
        """The overlay's status line: (text or None, is it a warning, show it big). In a run: hero, day and goal
        (what's still to check is PopTracker's job - user, 2026-09-28). On the hero-select screen: the heroes you
        may play with (checks done / checks in logic), and a warning if the picked one is locked (user, 2026-09-29:
        "make it more obvious on the homescreen which heros are available")."""
        if not self.slot_data:
            return None, False, False
        goal = f"Goal {len(self.heroes_won())}/{self.setting('heroes_required')}"
        if self.run.get("active"):
            hero, day, max_day = self.run["hero"], self.run.get("day", 1), self.setting("max_day")
            return f"{hero}: day {day}/{max_day} · {goal}{self.bypass_text()}", False, False
        if self.menu_hero:
            playable = [h for h in self.setting("heroes") if self.hero_unlocked(h)]
            lines = ["HEROES YOU CAN PLAY  (checks done / in logic)"] if playable else ["No hero unlocked yet"]
            for hero in playable:
                progress = self.hero_progress(hero)
                lines.append(f"   {hero}   {progress[0]} / {progress[1]}" if progress else f"   {hero}")
            lines.append(goal + self.bypass_text())
            if self.menu_hero not in playable:
                return "\n".join([f"{self.menu_hero.upper()} IS LOCKED - pick another hero."] + lines), True, True
            return "\n".join(lines), False, True
        # connected, game not showing a hero yet: keeps the box (and its Tracker button)
        return goal + self.bypass_text(), False, False

    def bypass_text(self) -> str:
        """The Lock Bypasses you have, always on the status line while there's at least one (user, 2026-09-30)."""
        ready = self.bypasses_ready()
        return f" · Lock Bypass{'es' if ready != 1 else ''}: {ready}" if ready > 0 else ""

    def update_status(self) -> None:
        if self.overlay:
            self.overlay.show_status(*self.status_line())
            self.overlay.show_tracker_data(self.tracker_data())

    def handle_hero_selected(self, event: HeroSelected) -> None:
        self.menu_hero = event.hero
        self.update_status()

    def print_status(self) -> None:
        if not self.slot_data:
            logger.info("Not connected.")
            return
        done = self.done()
        max_day = self.setting("max_day")
        for hero in self.setting("heroes"):
            days = sum(location_name_to_id[day_location(hero, d)] in done for d in range(1, max_day + 1))
            won = location_name_to_id[win_location(hero)] in done
            lock = "unlocked" if self.hero_unlocked(hero) else "LOCKED"
            logger.info(f"{hero:12} {lock:9} days {days}/{max_day}  10 wins: {'yes' if won else 'no'}")
        logger.info(f"Goal: {len(self.heroes_won())}/{self.setting('heroes_required')} heroes with 10 wins")
        if self.run.get("active"):
            reason = self.blocked_reason()
            note = f" - CHECKS ARE BLOCKED {reason}" if reason else ""
            logger.info(f"Current run: {self.run['hero']} on day {self.run['day']}{note}")


async def dispatch(ctx: BazaarContext, event) -> None:
    if ctx.run.get("day_offset") and not isinstance(event, RunStarted) and hasattr(event, "day"):
        # a run resumed after a game restart: the new log counts its days from 1 again
        event = dataclasses.replace(event, day=event.day + ctx.run["day_offset"])
    if isinstance(event, RunStarted):
        ctx.handle_run_started(event)
    elif isinstance(event, HeroSelected):
        ctx.handle_hero_selected(event)
    elif isinstance(event, DayReached):
        await ctx.handle_day(event)
    elif isinstance(event, CardGained):
        ctx.handle_gain(event)
    elif isinstance(event, CardSold):
        ctx.handle_sold(event)
    elif isinstance(event, FightStarted):
        ctx.handle_fight(event)
    elif isinstance(event, EncounterEntered):
        ctx.handle_encounter(event)
    elif isinstance(event, EncounterLeft):
        ctx.handle_encounter_left()
    elif isinstance(event, MonsterFought):
        await ctx.handle_monster(event)
    elif isinstance(event, PvPFought):
        await ctx.handle_pvp(event)
    elif isinstance(event, RunEnded):
        await ctx.handle_run_end(event)
    elif isinstance(event, GameVersion):
        ctx.handle_version(event)
    elif isinstance(event, UnrecognizedRun):
        ctx.handle_unrecognized_run()


def read_events(path: str) -> list:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return LogParser(MERCHANT_DATA.keys()).feed_all(f)
    except OSError:
        return []


def run_left_open(path: str, saved: dict) -> bool:
    """Does the log at `path` (a previous game session) show the saved run started and never finished?"""
    if log_session(path) != saved.get("log"):
        return False
    events = read_events(path)
    started = [i for i, e in enumerate(events) if isinstance(e, RunStarted) and e.index == saved.get("run_index")]
    return bool(started) and not any(isinstance(e, (RunStarted, RunEnded)) for e in events[started[0] + 1:])


def from_run(events: list, index: int) -> list:
    """The events from run number `index` of a log on (nothing if the log has no such run)."""
    return next((events[i:] for i, e in enumerate(events) if isinstance(e, RunStarted) and e.index >= index), [])


def missed(ctx: BazaarContext, past: list) -> list:
    """
    What the game logged while the client wasn't watching, as (game session, events) oldest first: the rest of the
    previous game session (if the game restarted meanwhile and Unity still keeps that log), then this one.
    It starts exactly where the client stopped (ctx.position), so nothing already judged is judged again.
    On a seed's first connection that's nothing: runs from before could predate the seed.
    """
    seen, where = ctx.watched, ctx.position
    if not (seen or where) or not ctx.log_session:
        return []
    if where:
        stopped_log, since = where["log"], (lambda events: events[where["events"]:])
    else:  # saved by a client from before positions were kept: from the tracked run on
        first = ctx.run["run_index"] if ctx.run.get("active") else seen["runs"]
        stopped_log, since = seen["log"], (lambda events: from_run(events, first))
    if stopped_log == ctx.log_session:
        return [(ctx.log_session, since(past))]
    earlier = []
    prev = os.path.join(os.path.dirname(ctx.log_path), PREV_LOG)
    if log_session(prev) == stopped_log:
        earlier = [(stopped_log, since(read_events(prev)))]
    else:
        ctx.event("The game restarted more than once while the client was closed: runs from the older game "
                  "session can't be read any more.", warning=True)
    return earlier + [(ctx.log_session, past)]


async def catch_up(ctx: BazaarContext, parser: LogParser, past: list) -> None:
    """
    Plays what the game logged while the client wasn't watching, in log order, so checks and blocks come out
    exactly as if it had been: runs that ended meanwhile quietly (no alerts, no late DeathLinks), the run in
    progress out loud. Events handled before (up to ctx.position) are never handled again.
    """
    session = ctx.log_session
    segments = missed(ctx, past)
    unseen = next((len(past) - len(events) for log, events in segments if log == session), len(past))
    run_start = max((i for i, e in enumerate(past) if isinstance(e, RunStarted)), default=None)         if parser.in_run else None
    if run_start is None:
        loud = len(past)  # no run going: everything missed is quiet
    elif not segments or run_start >= unseen:
        loud = run_start  # a run the client never saw start (or its first connection): the whole run, out loud
    else:
        loud = unseen  # the run the client was already following: just what it missed
    ctx.quiet = True
    try:
        for ctx.log_session, events in segments:
            if ctx.log_session == session:
                events = past[unseen:loud]
            for event in events:
                await dispatch(ctx, event)
    finally:
        ctx.quiet = False
    ctx.log_session = session
    if session and ctx.watched.get("log") != session:  # nothing from before counts, but it's been seen now
        ctx.watched = {"log": session, "runs": parser.runs_started - parser.in_run}
    if run_start is None:
        picked = [e for e in past if isinstance(e, HeroSelected)]
        if picked:
            ctx.handle_hero_selected(picked[-1])
    else:
        resumed = loud > run_start or ctx.resumes(past[run_start])
        for event in past[loud:]:
            await dispatch(ctx, event)
        reason = ctx.blocked_reason()
        if not resumed and reason:
            # A run the client didn't see start (it was closed or disconnected) that is outside logic (locked hero
            # or locked cards) needs conceding - selling doesn't fix it (user 2026-09-30: "2 a"). Not a legal run,
            # so ending it never sends a DeathLink.
            ctx.run.update(counting=False, legal=False,
                           concede_reason="- THIS RUN WAS OUTSIDE LOGIC WHEN THE CLIENT STARTED: CONCEDE IT")
            ctx.event(f"Your {parser.hero} run was already outside logic when the client started ({reason}). "
                      f"Concede it; no DeathLink will be sent.", warning=True)
            beep()
            ctx.update_block_banner()
    if session:
        ctx.position = {"log": session, "events": len(past)}
    ctx.save_state()


def count_event(ctx: BazaarContext) -> None:
    """One more event of the current game session handled (counted before it's handled, so its save includes it)."""
    if ctx.position.get("log") != ctx.log_session:
        ctx.position = {"log": ctx.log_session, "events": 0}
    ctx.position["events"] += 1


async def watch_log(ctx: BazaarContext) -> None:
    """Follow the game's log file and feed events to the context. Never stops on an error: it's logged, and the
    log is read again from the start (catch_up puts the state right)."""
    while not ctx.exit_event.is_set():
        if not ctx.slot_data:
            await asyncio.sleep(POLL_SECONDS)
            continue
        try:
            await asyncio.sleep(1)  # let the initial ReceivedItems arrive before judging unlocks
            ctx.restart_watcher = False
            tailer, parser = LogTailer(ctx.log_path), LogParser(MERCHANT_DATA.keys())
            lines = tailer.read_new_lines() or []
            ctx.log_session = log_session(ctx.log_path)
            ctx.caught_up = False
            await catch_up(ctx, parser, parser.feed_all(lines))
            ctx.caught_up = True
            ctx.receive_traps()  # the ones that arrived while the log was being read
            while not ctx.exit_event.is_set() and ctx.slot_data and not ctx.restart_watcher:
                lines = tailer.read_new_lines()
                if lines is None:  # the game restarted and began a fresh log
                    parser, ctx.log_session = LogParser(MERCHANT_DATA.keys()), None
                    ctx.event("The Bazaar restarted, following the new log.")
                    continue
                if lines and not ctx.log_session:
                    ctx.log_session = log_session(ctx.log_path)
                handled = False
                for line in lines:
                    for event in parser.feed(line):
                        count_event(ctx)
                        await dispatch(ctx, event)
                        handled = True
                if handled:
                    ctx.save_state()  # the position too, even for events that changed nothing else
                    ctx.refresh_padlocks()  # a run that started or ended changes what may be padlocked
                await asyncio.sleep(POLL_SECONDS)
        except Exception:
            logger.exception("Error while following the game's log; reading it again")
            await asyncio.sleep(POLL_SECONDS)


async def watch_memory(ctx: BazaarContext) -> None:
    """Reads what's on offer from the game's memory a few times a second. If a check fails the reader stays off
    for this game session and the shop warning falls back to everything the merchant could sell; it's only tried
    again when the game restarts (never re-engineered after a patch, owner 2026-09-30)."""
    reader, loop, said = Reader(), asyncio.get_running_loop(), None
    while not ctx.exit_event.is_set():
        try:
            if not reader.attached():
                ctx.handle_snapshot(None)
                await loop.run_in_executor(None, reader.attach)
                logger.info("Memory reader: reading The Bazaar's shop.", extra=FILE_ONLY)
                said = None
            for _ in range(SNAPSHOT_EVERY):
                ctx.handle_board_ui(reader.ui())  # a couple of milliseconds: fine on the event loop
                await asyncio.sleep(MEMORY_SECONDS)
            ctx.handle_snapshot(await loop.run_in_executor(None, reader.snapshot))
        except ReaderOff as error:
            reader.close()
            ctx.handle_snapshot(None)
            ctx.handle_board_ui(None)
            if str(error) != said:
                said = str(error)
                logger.info(f"Memory reader off: {error}", extra=FILE_ONLY)
                if not isinstance(error, NotReady):
                    ctx.event(f"The memory reader turned itself off ({error}), probably after a game patch. Shops "
                              f"list every locked card they could sell instead of padlocking the ones on offer.")
            if isinstance(error, NotReady):
                await asyncio.sleep(MEMORY_RETRY[0])
            else:  # wait for this game session to end before trying again
                session = find_pid(GAME_EXE)
                while not ctx.exit_event.is_set() and session and find_pid(GAME_EXE) == session:
                    await asyncio.sleep(MEMORY_RETRY[1])
        except Exception:
            logger.exception("Memory reader error; trying again")
            reader.close()
            ctx.handle_snapshot(None)
            await asyncio.sleep(MEMORY_RETRY[1])


async def main(args) -> None:
    ctx = BazaarContext(args.connect, args.password)
    ctx.auth = args.name
    if args.logpath:
        ctx.log_path = args.logpath
    ctx.shop_guide = not args.no_shop_guide
    if not args.no_overlay:
        from .overlay import Overlay
        ctx.overlay = Overlay(art_cache_dir=Utils.cache_path("bazaar_card_art") if ctx.shop_guide else None,
                              guide_file=Utils.user_path("bazaar_shop_guide.json"))
        loop = asyncio.get_running_loop()  # the button lives in the overlay's thread; the bypass is used here
        ctx.overlay.on_bypass = lambda guid: loop.call_soon_threadsafe(ctx.use_bypass, guid)
    ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")
    if ctx.overlay:
        # the windows start in their own thread; wait until they're up (or known not to come up)
        await asyncio.get_running_loop().run_in_executor(None, ctx.overlay.ready.wait, 10)
        if not ctx.overlay.available:
            logger.warning("The alert window can't open on this PC (tkinter is missing). Warnings still show here.")
    watcher = asyncio.create_task(watch_log(ctx), name="log watcher")
    # always on (owner, 2026-10-01: "a cornerstone for how the archipelago client will work"); Windows-only, like
    # the game. If a check fails it turns itself off and the client carries on from the log (see watch_memory).
    memory = asyncio.create_task(watch_memory(ctx), name="memory reader") if sys.platform == "win32" else None
    if gui_enabled:
        ctx.run_gui()
    ctx.run_cli()
    await ctx.exit_event.wait()
    watcher.cancel()
    if memory:
        memory.cancel()
    if ctx.overlay:
        ctx.overlay.close()
    await ctx.shutdown()


def launch_client(*args: str) -> None:
    import colorama
    Utils.init_logging("BazaarClient", exception_logger="Client")
    parser = get_base_parser(description="The Bazaar Archipelago client.")
    parser.add_argument("--name", default=None, help="Slot name to connect as.")
    parser.add_argument("--logpath", default=None, help="Path to The Bazaar's Player.log.")
    parser.add_argument("--no-overlay", action="store_true", help="Don't show alerts in a window above the game.")
    parser.add_argument("--no-shop-guide", action="store_true",
                        help="Don't open the Shop Guide window (card pictures of what a merchant can sell).")
    parser.add_argument("url", nargs="?", help="Archipelago connection url")
    parsed = handle_url_arg(parser.parse_args(args), parser=parser)
    colorama.just_fix_windows_console()
    asyncio.run(main(parsed))
    colorama.deinit()
