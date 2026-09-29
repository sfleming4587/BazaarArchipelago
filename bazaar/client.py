"""
The Bazaar Archipelago client.

Watches The Bazaar's own Player.log (read-only) and turns what it sees into Archipelago checks.
It never modifies the game, reads its memory, talks to Tempo's servers or sends input to the game.
Locked heroes/cards and received DeathLinks are enforced by the player (honor system) with the client's help.
"""
import asyncio
import dataclasses
import json
import os
import queue
import random
from typing import Any, Dict, Optional, Set

import Utils
from CommonClient import (ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, handle_url_arg,
                          logger, server_loop)
from NetUtils import ClientStatus

from .data import (CARDS, CARDS_BY_GUID, GAME_VERSION, HEROES, MERCHANT_DATA, MERCHANTS, MONSTERS, OFFER_DATA, PACKS,
                   TIERS)
from .items import BASE_ID, GAME, GROUP_ITEMS, SELL_TRAP, hero_item, item_name_to_id
from .locations import day_location, location_name_to_id, monster_location, pvp_location, win_location
from .logparser import (DEFAULT_LOG_PATH, CardGained, CardSold, DayReached, EncounterEntered, EncounterLeft,
                        FightStarted, GameVersion, LogParser, LogTailer, MonsterFought, PvPFought, RunEnded,
                        RunStarted, UnrecognizedRun)
from .merchants import possible_stock

POLL_SECONDS = 0.5
STATE_FILE = "bazaar_client_state.json"

SHOP_CARDS = [c for c in CARDS if c.shop]
LOCK_ITEM_GUIDS: Dict[int, Set[str]] = {BASE_ID + c.ap_id: {c.guid} for c in CARDS}
LOCK_ITEM_GUIDS.update({BASE_ID + p.ap_id: set(p.cards) for p in PACKS})
LOCK_ITEM_GUIDS.update({item_name_to_id[name]: set(guids) for name, guids in GROUP_ITEMS.items()})


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

    def _cmd_locked(self, hero: str = "") -> bool:
        """List cards that are still locked (and where they are, if you have a hint). E.g. /locked Vanessa"""
        hints = self.ctx.locked_card_hints()
        names = sorted(CARDS_BY_GUID[g].name + f" ({CARDS_BY_GUID[g].hero})" + (f"  -> {hints[g]}" if g in hints else "")
                       for g in self.ctx.locked_guids()
                       if g in CARDS_BY_GUID and (not hero or CARDS_BY_GUID[g].hero.lower() == hero.lower()))
        self.output(f"{len(names)} locked card(s):" if names else "No locked cards.")
        for name in names:
            self.output(f"  {name}")
        return True

    def _cmd_where(self, *card: str) -> bool:
        """Where is a locked card? Only answers if you already got a hint for it through Archipelago."""
        wanted = " ".join(card).strip().lower()
        guid = next((g for g in self.ctx.locked_guids() if g in CARDS_BY_GUID and CARDS_BY_GUID[g].name.lower() == wanted),
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

    def _cmd_pvpwin(self, day: str = "") -> bool:
        """Answer the client's "did you win?" question for a PvP fight, e.g. /pvpwin 3"""
        key = f"{self.ctx.run.get('hero')}|{day}"
        if key not in self.ctx.pvp_questions:
            self.output("There's no open PvP question for that day.")
            return False
        self.ctx.ui_events.put(("pvp", key, True))
        self.output(f"Noted: won day {day}'s PvP fight.")
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
        self.overlay = None
        self.shop_guide = True  # the picture window next to the game; --no-shop-guide turns it off
        self.ui_events: "queue.Queue[tuple]" = queue.Queue()  # button presses from the overlay
        self.pvp_questions: Dict[str, str] = {}  # "hero|day" -> text, waiting for Won / Lost
        self.pvp_signals: Dict[str, bool] = {}  # "hero|day" -> candidate win signal seen (evidence gathering)
        self.pvp_blocked: Dict[str, Optional[str]] = {}  # "hero|day" -> why checks were blocked during that fight
        self.notices_shown: Set[str] = set()  # patch warnings are shown once per session
        self.traps_seen = 0
        self.room_seed = ""  # CommonClient never sets seed_name, so the saved state is keyed on this instead

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
            Utils.async_start(self.update_death_link(bool(self.slot_data.get("death_link"))))
            logger.info(f"Watching {self.log_path}")
        elif cmd == "ReceivedItems":
            for item in args["items"]:
                name = self.item_names.lookup_in_game(item.item)
                if item.item in LOCK_ITEM_GUIDS or name.startswith("Hero: "):
                    logger.info(f"Unlocked: {name}")
                    if self.overlay and args.get("index", 0) > 0:  # index 0 = the full list resent on connect
                        sender = self.player_names.get(item.player, "the server") if item.player != self.slot \
                            else "your own world"
                        self.overlay.toast(f"UNLOCKED: {name.replace('Hero: ', '')}  (from {sender})")
            self.refresh_held()
            self.receive_traps()
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

    def save_state(self) -> None:
        path = Utils.user_path(STATE_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                everything = json.load(f)
        except (FileNotFoundError, ValueError):
            everything = {}
        everything[self.state_key()] = {"run": self.run, "defeats_since_death": self.defeats_since_death,
                                        "traps_seen": self.traps_seen}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(everything, f, indent=1)

    # --- unlocks ------------------------------------------------------------------------------------------------

    def received_ids(self) -> Set[int]:
        return {item.item for item in self.items_received}

    def hero_unlocked(self, hero: str) -> bool:
        return item_name_to_id.get(hero_item(hero)) in self.received_ids()

    def unlock_item_for(self, guid: str) -> str:
        """The name of the item (card, pack or group) in this seed that unlocks a locked card."""
        received = self.received_ids()
        for item_id in self.slot_data.get("lock_items", []):
            if item_id not in received and guid in LOCK_ITEM_GUIDS.get(item_id, set()):
                return self.item_names.lookup_in_game(item_id)
        return CARDS_BY_GUID[guid].name

    def locked_card_hints(self) -> Dict[str, str]:
        """Locked card guid -> "Player's location" for every hint you have that hasn't been found yet."""
        found: Dict[str, str] = {}
        for hint in self.stored_data.get(f"_read_hints_{self.team}_{self.slot}") or []:
            if hint.get("receiving_player") != self.slot or hint.get("found"):
                continue
            guids = LOCK_ITEM_GUIDS.get(hint.get("item"))
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
        if event.hero not in HEROES:
            self.notice("hero", f"{event.hero} is newer than this apworld, so it isn't part of this seed.")
        if event.hero not in self.slot_data.get("heroes", []):
            logger.warning(f"CHECKS ARE BLOCKED: {event.hero} isn't part of this multiworld.")
            counting = False
        elif not self.hero_unlocked(event.hero):
            logger.warning(f"CHECKS ARE BLOCKED: {event.hero} IS LOCKED. Abandon this run.")
            beep()
            counting = False
        else:
            logger.info(f"Started a run with {event.hero}. Good luck!")
        # "legal" = a hero you're allowed to play. Only legal runs send DeathLinks when lost; losing a
        # run you were told to abandon shouldn't kill your friends.
        # A new run is a clean slate: nothing from an earlier run (held cards, DeathLink, PvP questions) carries over.
        self.run = {"active": True, "hero": event.hero, "day": 1, "counting": counting, "legal": counting,
                    "deathlink_owed": False, "held": {}, "inventory": {}, "traps": []}
        self.pvp_questions.clear()
        self.pvp_signals.clear()
        self.pvp_blocked.clear()
        if self.overlay:
            self.overlay.ask_pvp({})
        self.refresh_held()

    async def handle_day(self, event: DayReached) -> None:
        if not self.run.get("active"):
            return
        # send the day's own check before moving the day on, so a Sell Trap due today doesn't block reaching it
        if event.day <= self.slot_data.get("max_day", 15):
            await self.send_run_checks([day_location(self.run["hero"], event.day)])
        self.run["day"] = event.day
        self.save_state()
        if any(t["deadline"] == event.day for t in self.run.get("traps", [])):
            beep()
            self.update_block_banner()

    def held_text(self, guid: str) -> str:
        return f"{CARDS_BY_GUID[guid].name} ({CARDS_BY_GUID[guid].hero})"

    def refresh_held(self) -> None:
        """Drop held cards that got unlocked in the meantime, then update the overlay and save."""
        held = self.run.get("held", {})
        locked = self.locked_guids()
        for instance, guid in list(held.items()):
            if guid not in locked:
                del held[instance]
                logger.info(f"{CARDS_BY_GUID[guid].name} is unlocked now, you can keep it.")
        self.update_block_banner()
        if self.run:
            self.save_state()

    def receive_traps(self) -> None:
        """Start every Sell Trap received since last time (the server resends all items on connect)."""
        trap_id = item_name_to_id[SELL_TRAP]
        total = sum(1 for item in self.items_received if item.item == trap_id)
        while self.traps_seen < total:
            self.traps_seen += 1
            self.start_trap()
        self.save_state()

    def start_trap(self) -> None:
        """Pick a random item the player holds; it must be sold before the deadline day starts."""
        targeted = {t["instance"] for t in self.run.get("traps", [])}
        choices = [i for i in self.run.get("inventory", {}) if i not in targeted] if self.run.get("active") else []
        if not choices:  # not in a run, or holding nothing it can target: the trap misses
            logger.info("Sell Trap DODGED - you had nothing it could make you sell.")
            if self.overlay:
                self.overlay.toast("Sell Trap DODGED!")
            return
        instance = random.choice(choices)
        guid = self.run["inventory"][instance]
        deadline = self.run.get("day", 1) + self.slot_data.get("sell_trap_days", 2)
        self.run.setdefault("traps", []).append({"instance": instance, "guid": guid, "deadline": deadline})
        name = self.card_name(guid)
        logger.warning(f"SELL TRAP! Sell {name} before day {deadline} starts, or checks get blocked.")
        beep()
        if self.overlay:
            self.overlay.toast(f"SELL TRAP! Sell {name} before day {deadline} starts.", seconds=15)
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
        logger.warning(text)
        if self.overlay:
            self.overlay.toast(text, seconds=12)

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
        self.run.update(held={}, traps=[], deathlink_owed=False, counting=True, legal=True, concede_reason=None)
        self.save_state()
        self.update_block_banner()

    def update_block_banner(self) -> None:
        if self.overlay:
            reason = self.blocked_reason()
            held = self.run.get("held", {}) if self.run.get("active") else {}
            lines = [self.held_text(g) for g in held.values()]
            upcoming = [t for t in self.run.get("traps", []) if t not in self.overdue_traps()] \
                if self.run.get("active") else []
            lines += [f"Sell Trap: sell {self.card_name(t['guid'])} before day {t['deadline']} starts"
                      for t in upcoming]
            title = f"CHECKS ARE BLOCKED {reason}" if reason else ("SELL TRAP" if upcoming else None)
            self.overlay.show_locked(title, lines)

    async def send_run_checks(self, names) -> None:
        """The only way checks earned in a run are sent: refused while cheating (locked hero or locked card)."""
        reason = self.blocked_reason()
        if reason:
            logger.warning(f"CHECKS ARE BLOCKED {reason}. Not sent: {', '.join(names)}")
            beep()
            return
        await self.send_checks(names)

    def handle_gain(self, event: CardGained) -> None:
        if self.run.get("active"):
            self.run.setdefault("inventory", {})[event.instance] = event.guid
        if event.guid not in CARDS_BY_GUID:
            self.notice("card", "You got a card this apworld doesn't know (added by a patch). It's never locked.")
        if not self.run.get("active") or event.guid not in self.locked_guids():
            return
        self.run.setdefault("held", {})[event.instance] = event.guid
        how = "bought" if event.bought else "got"
        logger.warning(f"You {how} {self.held_text(event.guid)}, which is still locked! "
                       "CHECKS ARE BLOCKED until you sell it.")
        beep()
        self.refresh_held()

    def handle_sold(self, event: CardSold) -> None:
        self.run.get("inventory", {}).pop(event.instance, None)
        traps = self.run.get("traps", [])
        if any(t["instance"] == event.instance for t in traps):
            self.run["traps"] = [t for t in traps if t["instance"] != event.instance]
            logger.info("Sell Trap done.")
            if self.overlay:
                self.overlay.toast("Sell Trap done!")
            self.update_block_banner()
            self.save_state()
        guid = self.run.get("held", {}).pop(event.instance, None)
        if guid:
            logger.info(f"Sold {CARDS_BY_GUID[guid].name}." + ("" if self.run.get("held") else " Checks unblocked."))
            self.refresh_held()

    def handle_fight(self, event: FightStarted) -> None:
        held = self.run.get("held", {})
        if not self.run.get("active") or not held:
            return
        names = ", ".join(CARDS_BY_GUID[g].name for g in held.values())
        beep()
        logger.warning(f"You went into a fight holding locked cards ({names}). Nothing from this fight counts.")

    def handle_encounter(self, event: EncounterEntered) -> None:
        merchant = MERCHANT_DATA.get(event.guid) or OFFER_DATA.get(event.guid)
        if not merchant or not self.run.get("active"):
            return
        verb = "sell" if event.guid in MERCHANT_DATA else "offer"
        locked = self.locked_guids()
        stock = possible_stock(merchant["stock"], self.run["hero"], (CARDS_BY_GUID[g] for g in locked
                                                                     if g in CARDS_BY_GUID))
        names = sorted(c.name for c in stock)
        if names:
            logger.info(f"{merchant['name']} may {verb} these locked cards: {', '.join(names)}")
        if self.overlay and (names or verb == "sell"):  # free choices only warn when something is locked
            self.overlay.show_shop(merchant["name"], names, verb)
        if self.overlay and self.shop_guide:
            everything = possible_stock(merchant["stock"], self.run["hero"], SHOP_CARDS)
            allowed = [c for c in everything if c.guid not in locked]
            self.overlay.show_board(f"{merchant['name']} can stock {len(everything)} cards for {self.run['hero']}",
                                    allowed, stock)

    def handle_encounter_left(self) -> None:
        if self.overlay:
            self.overlay.show_shop(None, [])
            if self.shop_guide:
                self.overlay.show_board(None, [], [])

    async def drain_ui_events(self) -> None:
        changed = False
        while True:
            try:
                event = self.ui_events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "pvp":
                _, key, won = event
                if self.pvp_questions.pop(key, None) is None:
                    continue  # only a question the client actually asked can be answered
                hero, day = key.split("|")
                self.record_pvp_evidence(hero, int(day), self.pvp_signals.pop(key, None), won)
                # blocked during the fight, or since (a DeathLink arriving before the answer also counts)
                blocked = self.pvp_blocked.pop(key, None) or self.blocked_reason()
                if won and blocked:
                    logger.warning(f"Day {day} PvP win not sent: checks were blocked {blocked} during that fight.")
                elif won:
                    await self.send_checks([pvp_location(hero, int(day))])
        if changed:
            self.save_state()

    def day_checks_after(self, hero: str, last_day: int) -> list:
        """PvP and monster checks for the days after `last_day` (days a 10-win run never reached)."""
        names = []
        for day in range(last_day + 1, self.slot_data.get("max_day", 15) + 1):
            if self.slot_data.get("pvp_win_checks"):
                names.append(pvp_location(hero, day))
            names += [monster_location(hero, day, t) for t in self.slot_data.get("monster_tiers", {}).get(str(day), [])]
        return names

    async def handle_monster(self, event: MonsterFought) -> None:
        if not self.run.get("active") or not event.won:
            return
        monster = MONSTERS.get(event.guid)
        if not monster:
            # added by a patch: its rarity is unknown, so it counts as the lowest rarity that day
            self.notice("monster", "You beat a monster this apworld doesn't know (added by a patch). "
                                   "It counts as a Bronze monster until the apworld is updated.")
            monster = {"name": "a new monster", "tier": "Bronze"}
        tiers = self.slot_data.get("monster_tiers", {}).get(str(event.day), [])
        beaten = [t for t in tiers if TIERS.index(t) <= TIERS.index(monster["tier"])]
        logger.info(f"Beat {monster['name']} ({monster['tier']}) on day {event.day}.")
        if beaten:
            await self.send_run_checks([monster_location(self.run["hero"], event.day, t) for t in beaten])

    def record_pvp_evidence(self, hero: str, day: int, signal: Optional[bool], won: bool) -> None:
        """Pairs the candidate log signal with the real result so we can learn whether it predicts a win."""
        if signal is None:
            return
        with open(Utils.user_path("bazaar_pvp_evidence.csv"), "a", encoding="utf-8") as f:
            f.write(f"{self.seed_name},{hero},{day},{int(signal)},{int(won)}\n")

    async def handle_pvp(self, event: PvPFought) -> None:
        if not self.run.get("active") or not self.slot_data.get("pvp_win_checks"):
            return
        if event.day > self.slot_data.get("max_day", 15):
            return
        if event.won is not None:
            self.record_pvp_evidence(self.run["hero"], event.day, event.exit_tasks, event.won)
        if event.won:
            await self.send_run_checks([pvp_location(self.run["hero"], event.day)])
        elif event.won is None:
            self.pvp_signals[f"{self.run['hero']}|{event.day}"] = event.exit_tasks
            self.pvp_blocked[f"{self.run['hero']}|{event.day}"] = self.blocked_reason()
            self.pvp_questions[f"{self.run['hero']}|{event.day}"] = f"{self.run['hero']}, day {event.day}"
            if self.overlay:
                self.overlay.ask_pvp(self.pvp_questions)
            else:
                logger.info(f"Did you win day {event.day}'s PvP fight? Type /pvpwin {event.day} if you did.")

    async def handle_run_end(self, event: RunEnded) -> None:
        if not self.run.get("active"):
            return
        hero = self.run["hero"]
        deathlink_owed = self.run.get("deathlink_owed")
        if event.victory:
            max_day = self.slot_data.get("max_day", 15)
            logger.info(f"10 wins with {hero}!")
            await self.send_run_checks([day_location(hero, d) for d in range(1, max_day + 1)] + [win_location(hero)]
                                       + self.day_checks_after(hero, event.day))
        self.run = {**self.run, "active": False, "held": {}}
        self.refresh_held()
        self.handle_encounter_left()
        if event.victory:
            pass  # a won run never sends a DeathLink
        elif deathlink_owed:
            logger.info("Run over. DeathLink paid off.")
        elif event.conceded:
            if self.slot_data.get("death_link_on_concede"):
                await self.maybe_send_death(f"conceded on day {event.day}", legal=self.run.get("legal", True))
            else:
                logger.info("Run conceded. Conceding doesn't send a DeathLink.")
        else:
            await self.maybe_send_death(f"ran out of prestige on day {event.day}", legal=self.run.get("legal", True))
        self.save_state()

    async def maybe_send_death(self, what: str, legal: Optional[bool] = None) -> None:
        """Send a DeathLink unless it's off, the run doesn't count (locked hero / DeathLink owed) or amnesty applies."""
        if legal is None:
            legal = self.run.get("legal", True) and not self.run.get("deathlink_owed")
        if "DeathLink" not in self.tags or not legal:
            return
        self.defeats_since_death += 1
        amnesty = self.slot_data.get("death_link_amnesty", 0)
        if self.defeats_since_death > amnesty:
            self.defeats_since_death = 0
            player = self.player_names.get(self.slot, "A Bazaar player")
            await self.send_death(f"{player}'s {self.run.get('hero', 'hero')} {what}.")
            logger.info("DeathLink sent.")
        else:
            logger.info(f"Forgiven by DeathLink amnesty ({self.defeats_since_death}/{amnesty}).")
        self.save_state()

    def on_deathlink(self, data: Dict[str, Any]) -> None:
        super().on_deathlink(data)
        beep()
        if self.run.get("active"):
            self.run["deathlink_owed"] = True
            self.save_state()
            self.update_block_banner()
            logger.warning("DEATHLINK! Abandon your current run now (Settings > Abandon Run). "
                           "No more checks count from this run.")
            if self.overlay:
                self.overlay.show_deathlink(data.get("cause") or f"{data.get('source', 'Someone')} died.")
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
            reason = self.blocked_reason()
            note = f" - CHECKS ARE BLOCKED {reason}" if reason else ""
            logger.info(f"Current run: {self.run['hero']} on day {self.run['day']}{note}")


async def dispatch(ctx: BazaarContext, event, parser: LogParser, first_run_in_log: bool) -> None:
    if isinstance(event, RunStarted):
        ctx.handle_run_started(event, parser, first_run_in_log)
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


async def catch_up(ctx: BazaarContext, parser: LogParser, past: list) -> int:
    """
    Replays the run that's in progress (if any) in log order, so blocks and checks come out exactly as if the
    client had been watching. Finished runs earlier in the log are ignored. Returns how many runs were seen.
    """
    if not parser.in_run:
        return 0
    run_start = max(i for i, e in enumerate(past) if isinstance(e, RunStarted))
    resuming = ctx.run.get("active") and ctx.run.get("hero") == past[run_start].hero
    # A resumed run's log starts counting days at 1 again; shift them onto the real day.
    offset = max(0, ctx.run.get("day", 1) - 1) if resuming and run_start == 0 else 0
    if resuming:
        logger.info(f"Continuing your {parser.hero} run on day {parser.day + offset}.")
    else:
        ctx.handle_run_started(past[run_start], parser, first_run_in_log=False)
    for event in past[run_start + 1:]:
        if offset and hasattr(event, "day"):
            event = dataclasses.replace(event, day=event.day + offset)
        await dispatch(ctx, event, parser, first_run_in_log=False)
    parser.day += offset
    reason = ctx.blocked_reason()
    if not resuming and reason:
        # The run was already going when the client started and is outside logic (locked hero or locked cards):
        # selling can't fix that, only conceding. Not a legal run, so ending it never sends a DeathLink.
        ctx.run.update(counting=False, legal=False,
                       concede_reason="- THIS RUN WAS OUTSIDE LOGIC WHEN THE CLIENT STARTED: CONCEDE IT")
        logger.warning(f"Your {parser.hero} run was already outside logic when the client started ({reason}). "
                       f"Concede it; no DeathLink will be sent.")
        beep()
        ctx.save_state()
        ctx.update_block_banner()
    return 1


async def watch_log(ctx: BazaarContext) -> None:
    """Follow the game's log file and feed events to the context."""
    while not ctx.exit_event.is_set():
        if not ctx.slot_data:
            await asyncio.sleep(POLL_SECONDS)
            continue
        await asyncio.sleep(1)  # let the initial ReceivedItems arrive before judging unlocks
        ctx.restart_watcher = False
        tailer, parser = LogTailer(ctx.log_path), LogParser(MERCHANTS)
        runs_seen = await catch_up(ctx, parser, parser.feed_all(tailer.read_new_lines() or []))

        while not ctx.exit_event.is_set() and ctx.slot_data and not ctx.restart_watcher:
            lines = tailer.read_new_lines()
            await ctx.drain_ui_events()
            if lines is None:  # the game restarted and began a fresh log
                parser, runs_seen = LogParser(MERCHANTS), 0
                logger.info("The Bazaar restarted, following the new log.")
                continue
            for line in lines:
                for event in parser.feed(line):
                    if isinstance(event, RunStarted):
                        runs_seen += 1
                    try:
                        await dispatch(ctx, event, parser, first_run_in_log=runs_seen == 1)
                    except Exception:
                        logger.exception("Error while handling a game event")
            await asyncio.sleep(POLL_SECONDS)


async def main(args) -> None:
    ctx = BazaarContext(args.connect, args.password)
    ctx.auth = args.name
    ctx.shop_guide = not args.no_shop_guide
    if not args.no_overlay:
        from .overlay import Overlay
        ctx.overlay = Overlay(on_pvp=lambda key, won: ctx.ui_events.put(("pvp", key, won)),
                              art_cache_dir=Utils.cache_path("bazaar_card_art") if ctx.shop_guide else None,
                              guide_file=Utils.user_path("bazaar_shop_guide.json"))
    ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")
    if ctx.overlay:
        await asyncio.sleep(1)  # the overlay starts in its own thread
        if not ctx.overlay.available:
            logger.warning("The alert window can't open on this PC (tkinter is missing). Warnings still show here.")
        elif ctx.shop_guide and ctx.overlay.shop_guide_unavailable:
            logger.info("Shop Guide card pictures need Pillow, which this Archipelago install doesn't include. "
                        "The shop warning at the top of the screen still lists locked cards.")
    watcher = asyncio.create_task(watch_log(ctx), name="log watcher")
    if gui_enabled:
        ctx.run_gui()
    ctx.run_cli()
    await ctx.exit_event.wait()
    watcher.cancel()
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
    if parsed.logpath:
        BazaarContext.log_path_override = parsed.logpath
    colorama.just_fix_windows_console()
    asyncio.run(main(parsed))
    colorama.deinit()
