import logging
from typing import Any, ClassVar, Dict, List, Mapping, Optional

import settings
from BaseClasses import ItemClassification, Region, Tutorial
from Options import OptionError
from worlds.AutoWorld import WebWorld, World
from worlds.LauncherComponents import Component, Type, components, launch

from .data import (CARDS, CARDS_BY_NAME, ENCOUNTERS, EVENTS, HEROES, LEGENDARY_GUIDS, PACKS, TIERS, Encounter,
                   hero_key, tiers_on_day)
from .items import (ENCOUNTERS_BY_ITEM, EVENT_RARITY, EXPEDITION_TICKETS, FILLER_ITEMS, GAME, GROUP_ITEMS,
                    LEGENDARY_ITEMS, LOCK_BYPASS, SELL_TRAP, BazaarItem, encounter_item, hero_item, item_id_to_name,
                    item_name_groups, item_name_to_id, lock_items_by_hero, pack_item)
from .locations import (BazaarLocation, Check, card_requirements, champion_event, hero_checks, item_requirements,
                        location_name_groups, location_name_to_id, win_location)
from .options import (INCLUDE_HERO_OPTIONS, PACK_OPTIONS, BazaarOptions, option_groups,
                      option_presets)


def run_client(*args: str) -> None:
    from .client import launch_client
    launch(launch_client, name="The Bazaar Client", args=args)


components.append(Component("The Bazaar Client", func=run_client, game_name=GAME, component_type=Type.CLIENT,
                            supports_uri=True, description="Reads The Bazaar's log and syncs with Archipelago."))


class BazaarSettings(settings.Group):
    class LogPath(settings.OptionalUserFilePath):
        """
        Path to The Bazaar's Player.log. Leave empty to use the default location:
        %USERPROFILE%/AppData/LocalLow/Tempo Storm/The Bazaar/Player.log
        """
        description = "The Bazaar Player.log"

    log_path: LogPath = LogPath("")


class BazaarWeb(WebWorld):
    theme = "partyTime"
    rich_text_options_doc = True
    option_groups = option_groups
    options_presets = option_presets
    tutorials = [Tutorial(
        "Multiworld Setup Guide",
        "How to set up The Bazaar for Archipelago.",
        "English",
        "setup_en.md",
        "setup/en",
        ["Sulldog"],
    )]


MAX_COPIES = 3  # most copies of one item the duplicate filling adds up to
FREE_MARGIN = 2  # spare cheaper checks each logic requirement keeps, so the fill always has room (see fit_logic)
DEFAULT_LOGIC = {"day_10": 15, "diamond": 10, "legendary": 20}  # seeds from before slot_data carried it


class BazaarWorld(World):
    """
    The Bazaar is an asynchronous PvP roguelike deckbuilder. Pick a hero, spend each day
    shopping and fighting, and try to reach 10 wins before your prestige runs out.
    """
    game = GAME
    web = BazaarWeb()
    options_dataclass = BazaarOptions
    options: BazaarOptions
    settings: ClassVar[BazaarSettings]
    item_name_to_id = item_name_to_id
    location_name_to_id = location_name_to_id
    item_name_groups = item_name_groups
    location_name_groups = location_name_groups

    # Universal Tracker: it rebuilds this world from slot_data instead of a YAML (see generate_early)
    ut_can_gen_without_yaml = True

    heroes: List[str]
    starting_hero: str
    goal_count: int
    logic: Dict[str, int]  # day_10 / diamond / legendary: cards logic expects first (see locations.card_requirements)
    lock_items: Dict[str, List[str]]  # hero (or "Common") -> lock item names placed in the pool
    group_items: List[str]  # group unlocks (Legendary Items, Expedition Tickets) in the pool
    starters: Dict[str, List[str]]  # pool -> Bronze cards never locked
    encounter_locks: List[str]  # merchant/event lock items in the pool (see docs/ENCOUNTER-LOCKS.md)
    starter_merchants: List[str]  # merchants never locked
    event_rarity: int  # copies of Event Rarity Progression in the pool
    unlocks_in_logic: bool  # False only for Universal Tracker on a seed made before 2026-10-06
    gating: set  # unlocks some check's rule needs (see locations.item_requirements): these are progression
    passthrough: Optional[Dict[str, Any]]  # Universal Tracker: the real seed's slot_data

    @staticmethod
    def interpret_slot_data(slot_data: Dict[str, Any]) -> Dict[str, Any]:
        """Universal Tracker hands this back as re_gen_passthrough so the tracker rebuilds the exact same seed."""
        return slot_data

    def generate_early(self) -> None:
        self.passthrough = getattr(self.multiworld, "re_gen_passthrough", {}).get(self.game)
        self.gating = set()
        self.unlocks_in_logic = True
        if self.passthrough:
            self.rebuild_from_slot_data(self.passthrough)
            return
        included = {hero for option, hero in INCLUDE_HERO_OPTIONS.items() if getattr(self.options, option)}
        self.heroes = [h for h in HEROES if h in included]
        if not self.heroes:
            raise OptionError(f"{self.player_name}: no hero is included, at least one is needed.")

        matches = [h for h in self.heroes if hero_key(h) == self.options.starting_hero.current_key]
        self.starting_hero = matches[0] if matches else self.random.choice(self.heroes)
        self.multiworld.push_precollected(self.create_item(hero_item(self.starting_hero)))

        others = [h for h in self.heroes if h != self.starting_hero]
        if self.options.early_hero_unlock and others:
            self.multiworld.local_early_items[self.player][hero_item(self.random.choice(others))] = 1
        self.goal_count = min(self.options.heroes_required.value, len(self.heroes))
        if self.goal_count < self.options.heroes_required.value:
            logging.warning(f"{self.player_name} (The Bazaar): heroes_required lowered to {self.goal_count}, "
                            f"the number of included heroes.")
        self.starters = {}
        self.encounter_locks, self.starter_merchants, self.event_rarity = [], [], 0
        self.logic = {"day_10": self.options.logic_day_10_cards.value,
                      "last_day": self.options.logic_last_day_cards.value,
                      "diamond": self.options.logic_diamond_cards.value,
                      "legendary": self.options.logic_legendary_cards.value}  # fitted in create_items

    def fit_logic(self) -> None:
        """Every check that expects K of a hero's cards needs at least K (+ FREE_MARGIN) of that hero's checks that
        expect fewer - that's where the cards can go. Small seeds (one hero, PvP/monster checks off, a short max_day)
        can't give that (review 2026-09-30: generation failed on every seed), so all logic numbers are scaled down
        together until each hero fits. Runs once the locked items are known."""
        def fits(logic: Dict[str, int]) -> bool:
            for hero in self.heroes:
                needs = sorted(card_requirements(hero, len(self.lock_items.get(hero, [])),
                                                 self.options.max_day.value, bool(self.options.pvp_win_checks),
                                                 self.monster_tiers, logic).values())
                if any(need and sum(n < need for n in needs) < need + FREE_MARGIN for need in needs):
                    return False
            return True
        wanted = dict(self.logic)
        for percent in range(100, -1, -5):
            fitted = {key: value * percent // 100 for key, value in wanted.items()}
            if fits(fitted):
                break
        if fitted != wanted:
            logging.warning(f"{self.player_name} (The Bazaar): logic card counts lowered to {fitted} - this seed "
                            f"has too few checks to place that many cards first.")
            self.logic = fitted

    def rebuild_from_slot_data(self, data: Dict[str, Any]) -> None:
        """Universal Tracker: take every random choice and setting from the real seed instead of rolling new ones."""
        self.heroes = list(data["heroes"])
        self.starting_hero = data["starting_hero"]
        self.goal_count = data["heroes_required"]
        self.options.max_day.value = data["max_day"]
        # seeds from before v0.5.2 lack these: the defaults of that time
        self.options.pvp_win_checks.value = int(data.get("pvp_win_checks", True))
        self.logic = data.get("logic", DEFAULT_LOGIC)
        self.starters = {}
        self.encounter_locks, self.starter_merchants, self.event_rarity = [], [], 0
        self.multiworld.push_precollected(self.create_item(hero_item(self.starting_hero)))

    def create_regions(self) -> None:
        menu = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu)
        for hero in self.heroes:
            region = Region(hero, self.player, self.multiworld)
            checks = hero_checks(hero, self.options.max_day.value, bool(self.options.pvp_win_checks), self.monster_tiers)
            region.add_locations({c.name: location_name_to_id[c.name] for c in checks}, BazaarLocation)

            champion = BazaarLocation(self.player, champion_event(hero), None, region)
            champion.place_locked_item(BazaarItem("Champion", ItemClassification.progression, None, self.player))
            region.locations.append(champion)

            self.multiworld.regions.append(region)
            menu.connect(region, f"Play {hero}", lambda state, h=hero: state.has(hero_item(h), self.player))

    def monster_tiers(self, day: int) -> List[str]:
        """Rarities with a check on this day: everything that day's monsters can reach, up to the cap."""
        if self.passthrough:  # slot_data keys are strings once they've been through the server
            tiers = self.passthrough.get("monster_tiers", {})
            return list(tiers.get(str(day), tiers.get(day, [])))
        if not self.options.monster_checks:
            return []
        return tiers_on_day(day, TIERS[self.options.max_monster_tier.value])

    def create_item(self, name: str) -> BazaarItem:
        if name in FILLER_ITEMS:
            classification = ItemClassification.filler
        elif name == SELL_TRAP:
            classification = ItemClassification.trap
        elif name == LOCK_BYPASS:
            classification = ItemClassification.useful  # a buff, never required by logic
        elif name in self.gating:
            classification = ItemClassification.progression
        elif name in GROUP_ITEMS or name == EVENT_RARITY or name in ENCOUNTERS_BY_ITEM                 or (name in CARDS_BY_NAME and CARDS_BY_NAME[name].hero == "Common"):
            classification = ItemClassification.useful  # never required by logic: a choice screen always has a way on
        else:
            classification = ItemClassification.progression
        return BazaarItem(name, classification, item_name_to_id[name], self.player)

    def get_filler_item_name(self) -> str:
        return self.random.choice(FILLER_ITEMS)

    def create_items(self) -> None:
        if self.passthrough:
            self.create_items_from_slot_data(self.passthrough)
            return
        slots = len(self.multiworld.get_unfilled_locations(self.player))
        pool = [hero_item(h) for h in self.heroes if h != self.starting_hero]

        packs = []
        if self.options.legacy_card_packs:
            wanted = {key for option, key in PACK_OPTIONS.items() if getattr(self.options, option)}
            packs = [p for p in PACKS if p.hero in self.heroes and p.key in wanted]
            self.random.shuffle(packs)
            packs = packs[:max(0, slots - len(pool))]
        excluded = {guid for p in packs for guid in p.cards}
        pool += [pack_item(p.name) for p in packs]

        groups = []  # group unlocks; extra copies only make the unlock likely to turn up sooner
        for name, copies in ((LEGENDARY_ITEMS, self.options.legendary_items.value),
                             (EXPEDITION_TICKETS, self.options.expedition_tickets.value)):
            copies = min(copies, max(0, slots - len(pool) - len(groups)))
            if copies:
                groups += [name] * copies
        # Legendary cards are only ever locked as a group: with no Legendary Items unlock in the pool (0 copies, or
        # no room) they're simply never locked, as the option says - never one by one (review 2026-09-29)
        excluded |= LEGENDARY_GUIDS
        pool += groups
        self.event_rarity = min(self.options.event_rarity_progression.value, max(0, slots - len(pool)))
        pool += [EVENT_RARITY] * self.event_rarity
        pool += [SELL_TRAP] * min(self.options.sell_traps.value, max(0, slots - len(pool)))
        pool += [LOCK_BYPASS] * min(self.options.lock_bypasses.value, max(0, slots - len(pool)))
        self.encounter_locks = self.pick_encounters(max(0, slots - len(pool)))
        pool += self.encounter_locks

        budget = (slots - len(pool)) * self.options.locked_cards_percent.value // 100
        duplicated = self.options.duplicate_cards.value
        if self.options.duplicate_all_cards:  # every spare slot holds pairs, never filler (user 2026-09-30, "1 a")
            cards = self.pick_cards((slots - len(pool)) // 2, excluded)
            copies = list(cards)
        else:
            cards = self.pick_cards(budget, excluded)
            copies = [name for name in cards if name in duplicated]
            while len(cards) + len(copies) > budget:  # make room for the second copies
                dropped = cards.pop()
                if dropped in copies:
                    copies.remove(dropped)
        pool += cards

        self.lock_items = {}
        for p in packs:
            self.lock_items.setdefault(p.hero, []).append(pack_item(p.name))
        for name in cards:
            self.lock_items.setdefault(CARDS_BY_NAME[name].hero, []).append(name)
        self.group_items = sorted(set(groups))
        self.gating = self.gated_unlocks()

        # copy counts the player set (group unlocks, duplicated cards) never grow: only the others get extras
        chosen = set(copies) if self.options.duplicate_all_cards else set(duplicated)
        copies += self.extra_copies(slots - len(pool) - len(copies), pool + copies,
                                    [name for name in cards if name not in chosen])
        self.multiworld.itempool += [self.create_item(name) for name in pool]
        # extra copies: the same items, but logic never needs them (the first copy is the one that counts)
        self.multiworld.itempool += [BazaarItem(name, ItemClassification.useful, item_name_to_id[name], self.player)
                                     for name in copies]
        # The Bazaar has no natural filler; this only happens when there's nothing left to duplicate
        self.multiworld.itempool += [self.create_filler() for _ in range(slots - len(pool) - len(copies))]
        self.fit_logic()

    def create_items_from_slot_data(self, data: Dict[str, Any]) -> None:
        """Universal Tracker only needs the same locations and rules; the item pool just has to be the right size."""
        self.lock_items, self.group_items = lock_items_by_hero(data["lock_items"])
        self.encounter_locks = [item_id_to_name[i] for i in data.get("encounter_locks", [])]
        self.event_rarity = data.get("event_rarity", 0)
        self.unlocks_in_logic = data.get("unlocks_in_logic", False)  # seeds from before 2026-10-06 never needed them
        self.gating = self.gated_unlocks()
        pool = [hero_item(h) for h in self.heroes if h != self.starting_hero]
        pool += [name for names_ in self.lock_items.values() for name in names_] + self.group_items
        pool += self.encounter_locks + [EVENT_RARITY] * self.event_rarity
        slots = len(self.multiworld.get_unfilled_locations(self.player))
        self.multiworld.itempool += [self.create_item(name) for name in pool[:slots]]
        self.multiworld.itempool += [self.create_filler() for _ in range(slots - min(slots, len(pool)))]

    def extra_copies(self, free: int, placed: List[str], cards: List[str]) -> List[str]:
        """Fill `free` slots with duplicates: hero unlocks, then locked cards (max 3 each). Group unlocks never get
        extras: their copies are an option, and a player who asked for 2 must not find a 3rd (user, 2026-09-30)."""
        count = {name: placed.count(name) for name in set(placed)}
        extra: List[str] = []
        heroes = [hero_item(h) for h in self.heroes if h != self.starting_hero]
        for tier in (heroes, self.random.sample(cards, len(cards))):
            progressing = True
            while progressing and len(extra) < free:
                progressing = False
                for name in tier:
                    if len(extra) < free and count.get(name, 0) < MAX_COPIES:
                        count[name] = count.get(name, 0) + 1
                        extra.append(name)
                        progressing = True
        return extra

    def pick_encounters(self, free: int) -> List[str]:
        """Merchant/event lock items: locked_encounters_percent of those your heroes can meet, after setting aside
        starter_merchants merchants that never get a lock item. Starters come from merchants with a version below
        Diamond, so Event Rarity Progression leaves at least that version open."""
        def meets(encounter: Encounter) -> bool:
            heroes = {h for g in encounter.guids for h in EVENTS[g]["heroes"]}
            return "Common" in heroes or bool(heroes & set(self.heroes))
        candidates = [encounter_item(e) for e in ENCOUNTERS if meets(e)]
        self.random.shuffle(candidates)
        early = [name for name in candidates if ENCOUNTERS_BY_ITEM[name].merchant
                 and any(EVENTS[g]["tier"] in TIERS[:3] for g in ENCOUNTERS_BY_ITEM[name].guids)]
        self.starter_merchants = sorted(early[:self.options.starter_merchants.value])
        candidates = [name for name in candidates if name not in self.starter_merchants]
        return candidates[:min(free, len(candidates) * self.options.locked_encounters_percent.value // 100)]

    def pick_cards(self, count: int, excluded_guids: set) -> List[str]:
        """
        Spread `count` locks as evenly as possible over each hero pool (and the Common pool). Each pool first
        sets aside `starter_cards` Bronze cards that are never locked, so early days always have something to buy.
        """
        groups = self.heroes + (["Common"] if self.options.lock_common_cards else [])
        loot_ok = bool(self.options.lock_loot_items)
        candidates = {g: [c for c in CARDS if c.hero == g and c.shop and c.guid not in excluded_guids
                          and (loot_ok or "Loot" not in c.tags)]
                      for g in groups}
        for group, cards in candidates.items():
            self.random.shuffle(cards)
            bronze = [c for c in cards if c.tier == "Bronze"]
            starters = {c.name for c in bronze[:self.options.starter_cards.value]}
            self.starters[group] = sorted(starters)
            candidates[group] = [c.name for c in cards if c.name not in starters]
        picked: List[str] = []
        while len(picked) < count and any(candidates.values()):
            for group in self.random.sample(groups, len(groups)):
                if candidates[group] and len(picked) < count:
                    picked.append(candidates[group].pop())
        return picked

    def set_rules(self) -> None:
        for hero in self.heroes:
            items = self.lock_items.get(hero, [])
            needs = card_requirements(hero, len(items), self.options.max_day.value, bool(self.options.pvp_win_checks),
                                      self.monster_tiers, self.logic)
            for check in hero_checks(hero, self.options.max_day.value, bool(self.options.pvp_win_checks),
                                     self.monster_tiers):
                self.set_check_rule(check.name, items, needs[check.name], self.unlocks_needed(check))
            self.set_check_rule(champion_event(hero), items, needs[win_location(hero)], {})

        self.multiworld.completion_condition[self.player] = \
            lambda state: state.has("Champion", self.player, self.goal_count)

    def set_check_rule(self, location_name: str, items: List[str], count: int, unlocks: Dict[str, int]) -> None:
        if count or unlocks:
            self.get_location(location_name).access_rule = \
                lambda state: ((not count or state.has_from_list_unique(items, self.player, count))  # dupes count once
                               and state.has_all_counts(unlocks, self.player))

    def unlocks_needed(self, check: Check) -> Dict[str, int]:
        if not self.unlocks_in_logic:
            return {}
        return item_requirements(check, LEGENDARY_ITEMS in self.group_items, self.event_rarity)

    def gated_unlocks(self) -> set:
        """Unlocks some check needs: progression, so other games show them as important (user 2026-10-06)."""
        return {name for hero in self.heroes
                for check in hero_checks(hero, self.options.max_day.value, bool(self.options.pvp_win_checks),
                                         self.monster_tiers)
                for name in self.unlocks_needed(check)}

    def write_spoiler(self, spoiler_handle) -> None:
        lines = [f"The Bazaar ({self.player_name})",
                 f"  Starting hero: {self.starting_hero}   Goal: 10 wins with {self.goal_count} heroes"]
        lines += [f"  {hero}: {len(self.lock_items.get(hero, []))} locked cards/packs" for hero in self.heroes]
        if "Common" in self.lock_items:
            lines.append(f"  Common: {len(self.lock_items['Common'])} locked cards")
        if self.group_items:
            lines.append(f"  Group unlocks: {', '.join(self.group_items)}")
        if self.encounter_locks:
            lines.append(f"  Locked merchants/events: {', '.join(sorted(self.encounter_locks))}")
        if self.starter_merchants:
            lines.append(f"  Starter merchants (never locked): {', '.join(self.starter_merchants)}")
        if self.event_rarity:
            lines.append(f"  Event Rarity Progression: {self.event_rarity} copies")
        for group, starters in sorted(self.starters.items()):
            lines.append(f"  Starter cards ({group}, never locked): {', '.join(starters)}")
        days = [f"day {d}: {' / '.join(self.monster_tiers(d))}" for d in range(1, self.options.max_day.value + 1)
                if self.monster_tiers(d)]
        if days:
            lines.append(f"  Monster checks by day: {', '.join(days)}")
        spoiler_handle.write("\n\n" + "\n".join(lines) + "\n")

    def fill_slot_data(self) -> Mapping[str, Any]:
        return {
            "heroes": self.heroes,
            "starting_hero": self.starting_hero,
            "max_day": self.options.max_day.value,
            "pvp_win_checks": bool(self.options.pvp_win_checks),
            "monster_tiers": {day: self.monster_tiers(day) for day in range(1, self.options.max_day.value + 1)},
            "heroes_required": self.goal_count,
            "lock_items": sorted({item_name_to_id[name] for names in self.lock_items.values() for name in names}
                                 | {item_name_to_id[name] for name in self.group_items}),
            "death_link": bool(self.options.death_link.value),
            "death_link_amnesty": self.options.death_link_amnesty.value,
            "death_links_before_concede": self.options.death_links_before_concede.value,
            "death_links_same_run": bool(self.options.death_links_same_run.value),
            "sell_trap_days": self.options.sell_trap_days.value,
            "logic": self.logic,
            "death_link_on_concede": bool(self.options.death_link_on_concede.value),
            "encounter_locks": sorted(item_name_to_id[name] for name in self.encounter_locks),
            "event_rarity": self.event_rarity,
            "unlocks_in_logic": True,
            "exempt_expeditions": bool(self.options.exempt_expeditions.value),
        }
