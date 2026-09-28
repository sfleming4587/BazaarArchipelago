"""
The Bazaar Archipelago client.

Watches The Bazaar's own Player.log (read-only) and turns what it sees into Archipelago checks.
It never modifies the game, reads its memory, talks to Tempo's servers or sends input to the game.
Locked heroes/cards and received DeathLinks are enforced by the player (honor system) with the client's help.
"""
import asyncio
import json
import os
import time
from typing import Any, Dict, Optional, Set

import Utils
from CommonClient import (ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, handle_url_arg,
                          logger, server_loop)
from NetUtils import ClientStatus

from .data import CARDS, CARDS_BY_GUID, PACKS
from .items import BASE_ID, GAME, hero_item
from .locations import day_location, location_name_to_id, win_location
from .logparser import (DEFAULT_LOG_PATH, CardBought, DayReached, LogParser, LogTailer, RunEnded, RunStarted)

POLL_SECONDS = 0.5
STATE_FILE = "bazaar_client_state.json"

LOCK_ITEM_GUIDS: Dict[int, Set[str]] = {BASE_ID + c.ap_id: {c.guid} for c in CARDS}
LOCK_ITEM_GUIDS.update({BASE_ID + p.ap_id: set(p.cards) for p in PACKS})


def default_log_path() -> str:
    try:
        from . import BazaarWorld
        configured = BazaarWorld.settings.log_path
        if configured:
            return str(configured)
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

    def _cmd_locked(self, hero: str = "") -> bool:
        """List cards that are still locked. Optionally filter by hero, e.g. /locked Vanessa"""
        names = sorted(CARDS_BY_GUID[g].name + f" ({CARDS_BY_GUID[g].hero})" for g in self.ctx.locked_guids()
                       if g in CARDS_BY_GUID and (not hero or CARDS_BY_GUID[g].hero.lower() == hero.lower()))
        self.output(f"{len(names)} locked card(s):" if names else "No locked cards.")
        for name in names:
            self.output(f"  {name}")
        return True

    def _cmd_logpath(self, path: str = "") -> bool:
        """Show or change the path of The Bazaar's Player.log."""
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
    log_path_override: Optional[str] = None

    def __init__(self, server_address: Optional[str] = None, password: Optional[str] = None) -> None:
        super().__init__(server_address, password)
        self.slot_data: Dict[str, Any] = {}
        self.log_path = self.log_path_override or default_log_path()
        self.restart_watcher = False
        self.run: Dict[str, Any] = {}  # persisted: hero, day, counting, tainted, deathlink_owed
        self.defeats_since_death = 0
        self.goal_sent = False

    # --- connection ---------------------------------------------------------------------------------------------

    async def server_auth(self, password_requested: bool = False) -> None:
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict) -> None:
        if cmd == "Connected":
            self.slot_data = args.get("slot_data") or {}
            self.load_state()
            Utils.async_start(self.update_death_link(bool(self.slot_data.get("death_link"))))
            logger.info(f"Watching {self.log_path}")
        elif cmd == "ReceivedItems":
            for item in args["items"]:
                if item.item in LOCK_ITEM_GUIDS or self.item_names.lookup_in_game(item.item).startswith("Hero: "):
                    logger.info(f"Unlocked: {self.item_names.lookup_in_game(item.item)}")
        elif cmd == "RoomUpdate" and "checked_locations" in args:
            self.check_goal()

    async def disconnect(self, allow_autoreconnect: bool = False) -> None:
        self.slot_data = {}
        await super().disconnect(allow_autoreconnect)

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "Archipelago The Bazaar Client"
        return ui

    # --- persistence --------------------------------------------------------------------------------------------

    def state_key(self) -> str:
        return f"{self.seed_name}:{self.slot}"

    def load_state(self) -> None:
        try:
            with open(Utils.user_path(STATE_FILE), encoding="utf-8") as f:
                saved = json.load(f).get(self.state_key(), {})
        except (FileNotFoundError, ValueError):
            saved = {}
        self.run = saved.get("run", {})
        self.defeats_since_death = saved.get("defeats_since_death", 0)

    def save_state(self) -> None:
        path = Utils.user_path(STATE_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                everything = json.load(f)
        except (FileNotFoundError, ValueError):
            everything = {}
        everything[self.state_key()] = {"run": self.run, "defeats_since_death": self.defeats_since_death}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(everything, f, indent=1)

    # --- unlocks ------------------------------------------------------------------------------------------------

    def received_ids(self) -> Set[int]:
        return {item.item for item in self.items_received}

    def hero_unlocked(self, hero: str) -> bool:
        from .items import item_name_to_id
        return item_name_to_id.get(hero_item(hero)) in self.received_ids()

    def locked_guids(self) -> Set[str]:
        received = self.received_ids()
        locked: Set[str] = set()
        for item_id in self.slot_data.get("lock_items", []):
            if item_id not in received:
                locked |= LOCK_ITEM_GUIDS.get(item_id, set())
        return locked

    # --- game events --------------------------------------------------------------------------------------------

    def handle_run_started(self, event: RunStarted, parser: LogParser, first_run_in_log: bool) -> None:
        if first_run_in_log and self.run.get("hero") == event.hero and self.run.get("active"):
            # The game was restarted and put us back into the run we were already tracking.
            parser.day = max(parser.day, self.run.get("day", 1))
            logger.info(f"Resumed your {event.hero} run on day {parser.day}.")
            return
        if self.run.get("active"):
            logger.info(f"Your previous {self.run['hero']} run ended while the client wasn't watching.")
        counting = True
        if event.hero not in self.slot_data.get("heroes", []):
            logger.warning(f"{event.hero} isn't part of this multiworld. This run won't send checks.")
            counting = False
        elif not self.hero_unlocked(event.hero):
            logger.warning(f"{event.hero} is still LOCKED. Abandon this run; it won't send checks.")
            beep()
            counting = False
        else:
            logger.info(f"Started a run with {event.hero}. Good luck!")
        # "legal" = a hero you're allowed to play. Only legal runs send DeathLinks when lost; losing a
        # run you were told to abandon shouldn't kill your friends.
        self.run = {"active": True, "hero": event.hero, "day": 1, "counting": counting, "legal": counting,
                    "tainted": False, "deathlink_owed": False}
        self.save_state()

    async def handle_day(self, event: DayReached) -> None:
        if not self.run.get("active"):
            return
        self.run["day"] = event.day
        self.save_state()
        if self.run["counting"] and event.day <= self.slot_data.get("max_day", 15):
            await self.send_checks([day_location(self.run["hero"], event.day)])

    def handle_card(self, event: CardBought) -> None:
        if not self.run.get("active") or event.guid not in self.locked_guids():
            return
        card = CARDS_BY_GUID[event.guid]
        beep()
        if self.slot_data.get("lock_enforcement") == "strict" and self.run["counting"]:
            self.run["counting"] = False
            self.run["tainted"] = True
            self.save_state()
            logger.warning(f"You bought {card.name}, which is still locked! This run no longer sends checks.")
        else:
            logger.warning(f"You bought {card.name}, which is still locked! Please sell it.")

    async def handle_run_end(self, event: RunEnded) -> None:
        if not self.run.get("active"):
            return
        hero = self.run["hero"]
        counting = self.run["counting"]
        deathlink_owed = self.run.get("deathlink_owed")
        self.run = {**self.run, "active": False}
        if event.victory:
            if counting:
                max_day = self.slot_data.get("max_day", 15)
                logger.info(f"10 wins with {hero}! Sending all of {hero}'s day checks.")
                await self.send_checks([day_location(hero, d) for d in range(1, max_day + 1)] + [win_location(hero)])
            else:
                logger.info(f"10 wins with {hero}, but this run wasn't counting checks.")
        elif deathlink_owed:
            logger.info("Run over. DeathLink paid off.")
        elif "DeathLink" in self.tags and self.run.get("legal", True):
            self.defeats_since_death += 1
            amnesty = self.slot_data.get("death_link_amnesty", 0)
            if self.defeats_since_death > amnesty:
                self.defeats_since_death = 0
                await self.send_death(f"{self.player_names[self.slot]}'s {hero} ran out of prestige on day {event.day}.")
                logger.info("DeathLink sent.")
            else:
                logger.info(f"Lost run forgiven by DeathLink amnesty ({self.defeats_since_death}/{amnesty}).")
        self.save_state()

    def on_deathlink(self, data: Dict[str, Any]) -> None:
        super().on_deathlink(data)
        beep()
        if self.run.get("active"):
            self.run["deathlink_owed"] = True
            self.save_state()
            logger.warning("DEATHLINK! Abandon your current run now (Settings > Abandon Run).")
        else:
            logger.info("DeathLink received while you weren't in a run. You're safe this time.")

    # --- checks & goal ------------------------------------------------------------------------------------------

    async def send_checks(self, names) -> None:
        ids = {location_name_to_id[n] for n in names}
        self.locations_checked |= ids
        await self.check_locations(ids)
        self.check_goal()

    def check_goal(self) -> None:
        if self.goal_sent or not self.slot_data:
            return
        done = self.checked_locations | self.locations_checked
        won = [h for h in self.slot_data.get("heroes", []) if location_name_to_id[win_location(h)] in done]
        if len(won) >= self.slot_data.get("heroes_required", 1):
            self.goal_sent = True
            self.finished_game = True
            Utils.async_start(self.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}]))
            logger.info("Goal complete! Congratulations, champion of the Bazaar.")

    def print_status(self) -> None:
        if not self.slot_data:
            logger.info("Not connected.")
            return
        done = self.checked_locations | self.locations_checked
        max_day = self.slot_data["max_day"]
        for hero in self.slot_data["heroes"]:
            days = sum(location_name_to_id[day_location(hero, d)] in done for d in range(1, max_day + 1))
            won = location_name_to_id[win_location(hero)] in done
            lock = "unlocked" if self.hero_unlocked(hero) else "LOCKED"
            logger.info(f"{hero:12} {lock:9} days {days}/{max_day}  10 wins: {'yes' if won else 'no'}")
        won = sum(location_name_to_id[win_location(h)] in done for h in self.slot_data["heroes"])
        logger.info(f"Goal: {won}/{self.slot_data['heroes_required']} heroes with 10 wins")
        if self.run.get("active"):
            note = "" if self.run["counting"] else " (not counting)"
            logger.info(f"Current run: {self.run['hero']} on day {self.run['day']}{note}")


async def watch_log(ctx: BazaarContext) -> None:
    """Follow the game's log file and feed events to the context."""
    while not ctx.exit_event.is_set():
        if not ctx.slot_data:
            await asyncio.sleep(POLL_SECONDS)
            continue
        await asyncio.sleep(1)  # let the initial ReceivedItems arrive before judging unlocks
        ctx.restart_watcher = False
        tailer, parser = LogTailer(ctx.log_path), LogParser()

        # Catch up silently on what happened earlier in this game session. Past runs never send anything;
        # only a run that's still in progress gets picked up.
        lines = tailer.read_new_lines() or []
        parser.feed_all(lines)
        runs_seen = 0
        if parser.in_run:
            runs_seen = 1
            if ctx.run.get("active") and ctx.run.get("hero") == parser.hero:
                parser.day = max(parser.day, ctx.run.get("day", 1))
                logger.info(f"Continuing your {parser.hero} run on day {parser.day}.")
            else:
                ctx.handle_run_started(RunStarted(parser.hero or "Unknown"), parser, first_run_in_log=False)
            for day in range(1, parser.day + 1):
                await ctx.handle_day(DayReached(day))

        while not ctx.exit_event.is_set() and ctx.slot_data and not ctx.restart_watcher:
            lines = tailer.read_new_lines()
            if lines is None:  # the game restarted and began a fresh log
                parser, runs_seen = LogParser(), 0
                logger.info("The Bazaar restarted, following the new log.")
                continue
            for line in lines:
                for event in parser.feed(line):
                    try:
                        if isinstance(event, RunStarted):
                            runs_seen += 1
                            ctx.handle_run_started(event, parser, first_run_in_log=runs_seen == 1)
                        elif isinstance(event, DayReached):
                            await ctx.handle_day(event)
                        elif isinstance(event, CardBought):
                            ctx.handle_card(event)
                        elif isinstance(event, RunEnded):
                            await ctx.handle_run_end(event)
                    except Exception:
                        logger.exception("Error while handling a game event")
            await asyncio.sleep(POLL_SECONDS)


async def main(args) -> None:
    ctx = BazaarContext(args.connect, args.password)
    ctx.auth = args.name
    ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")
    watcher = asyncio.create_task(watch_log(ctx), name="log watcher")
    if gui_enabled:
        ctx.run_gui()
    ctx.run_cli()
    await ctx.exit_event.wait()
    watcher.cancel()
    await ctx.shutdown()


def launch_client(*args: str) -> None:
    import colorama
    Utils.init_logging("BazaarClient", exception_logger="Client")
    parser = get_base_parser(description="The Bazaar Archipelago client.")
    parser.add_argument("--name", default=None, help="Slot name to connect as.")
    parser.add_argument("--logpath", default=None, help="Path to The Bazaar's Player.log.")
    parser.add_argument("url", nargs="?", help="Archipelago connection url")
    parsed = handle_url_arg(parser.parse_args(args), parser=parser)
    if parsed.logpath:
        BazaarContext.log_path_override = parsed.logpath
    colorama.just_fix_windows_console()
    asyncio.run(main(parsed))
    colorama.deinit()
