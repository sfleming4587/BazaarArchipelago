import logging
from typing import Any, ClassVar, Dict, List, Mapping

import settings
from BaseClasses import ItemClassification, Region, Tutorial
from Options import OptionError
from worlds.AutoWorld import WebWorld, World
from worlds.LauncherComponents import Component, Type, components, launch

from .data import BASE_HEROES, CARDS, CARDS_BY_NAME, HEROES, LEGENDARY_GUIDS, PACKS, TIERS, max_monster_tier_by_day
from .items import (EXPEDITION_TICKETS, FILLER_ITEMS, GAME, GROUP_ITEMS, LEGENDARY_ITEMS, SELL_TRAP, BazaarItem,
                    hero_item, item_name_groups, item_name_to_id, lock_items_by_hero, pack_item)
from .locations import (BazaarLocation, card_requirements, champion_event, day_location, location_name_groups,
                        location_name_to_id, monster_location, pvp_location, win_location)
from .options import OWN_HERO_OPTIONS, BazaarOptions, option_groups, option_presets


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
    lock_items: Dict[str, List[str]]  # hero (or "Common") -> lock item names placed in the pool

    @staticmethod
    def interpret_slot_data(slot_data: Dict[str, Any]) -> Dict[str, Any]:
        """Universal Tracker hands this back as re_gen_passthrough so the tracker rebuilds the exact same seed."""
        return slot_data

    def generate_early(self) -> None:
        self.passthrough = getattr(self.multiworld, "re_gen_passthrough", {}).get(self.game)
        if self.passthrough:
            self.rebuild_from_slot_data(self.passthrough)
            return
        owned = set(BASE_HEROES) | set(self.options.owned_dlc_heroes.value) \
            | {hero for option, hero in OWN_HERO_OPTIONS.items() if getattr(self.options, option)}
        self.heroes = [h for h in HEROES if h in owned and h not in self.options.excluded_heroes.value]
        if not self.heroes:
            raise OptionError(f"{self.player_name}: every hero is excluded, at least one is needed.")

        wanted = self.options.starting_hero.current_key.replace("_", " ")
        matches = [h for h in self.heroes if h.lower() == wanted]
        self.starting_hero = matches[0] if matches else self.random.choice(self.heroes)
        self.multiworld.push_precollected(self.create_item(hero_item(self.starting_hero)))

        others = [h for h in self.heroes if h != self.starting_hero]
        if self.options.early_hero_unlock and others:
            self.multiworld.local_early_items[self.player][hero_item(self.random.choice(others))] = 1
        self.goal_count = min(self.options.heroes_required.value, len(self.heroes))
        if self.goal_count < self.options.heroes_required.value:
            logging.warning(f"{self.player_name} (The Bazaar): heroes_required lowered to {self.goal_count}, "
                            f"the number of heroes available (owned DLC heroes minus excluded ones).")
        if self.options.duplicate_all_cards:
            logging.warning(f"{self.player_name} (The Bazaar): duplicate_all_cards is on. Not intended - half the "
                            f"item slots hold duplicates, so only about half as many cards start locked.")
        self.monster_table = max_monster_tier_by_day(self.options.max_day.value)

    def rebuild_from_slot_data(self, data: Dict[str, Any]) -> None:
        """Universal Tracker: take every random choice and setting from the real seed instead of rolling new ones."""
        self.heroes = list(data["heroes"])
        self.starting_hero = data["starting_hero"]
        self.goal_count = data["heroes_required"]
        self.options.max_day.value = data["max_day"]
        self.options.pvp_win_checks.value = int(data["pvp_win_checks"])
        for key, option in (("day_10", self.options.logic_day_10_cards), ("diamond", self.options.logic_diamond_cards),
                            ("legendary", self.options.logic_legendary_cards)):
            option.value = data["logic"][key]
        self.multiworld.push_precollected(self.create_item(hero_item(self.starting_hero)))

    def create_regions(self) -> None:
        menu = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu)
        for hero in self.heroes:
            region = Region(hero, self.player, self.multiworld)
            names = [name for day in range(1, self.options.max_day.value + 1) for name in self.day_checks(hero, day)]
            names.append(win_location(hero))
            region.add_locations({name: location_name_to_id[name] for name in names}, BazaarLocation)

            champion = BazaarLocation(self.player, champion_event(hero), None, region)
            champion.place_locked_item(BazaarItem("Champion", ItemClassification.progression, None, self.player))
            region.locations.append(champion)

            self.multiworld.regions.append(region)
            menu.connect(region, f"Play {hero}", lambda state, h=hero: state.has(hero_item(h), self.player))

    def monster_tiers(self, day: int) -> List[str]:
        """Rarities with a check on this day: everything that day's monsters can reach, up to the cap."""
        if self.passthrough:  # slot_data keys are strings once they've been through the server
            tiers = self.passthrough["monster_tiers"]
            return list(tiers.get(str(day), tiers.get(day, [])))
        if not self.options.monster_checks:
            return []
        top = min(self.monster_table[day], self.options.max_monster_tier.value)
        return list(TIERS[:top + 1])

    def day_checks(self, hero: str, day: int) -> List[str]:
        names = [day_location(hero, day)]
        if self.options.pvp_win_checks:
            names.append(pvp_location(hero, day))
        names += [monster_location(hero, day, tier) for tier in self.monster_tiers(day)]
        return names

    def create_item(self, name: str) -> BazaarItem:
        if name in FILLER_ITEMS:
            classification = ItemClassification.filler
        elif name == SELL_TRAP:
            classification = ItemClassification.trap
        elif name in GROUP_ITEMS or (name in CARDS_BY_NAME and CARDS_BY_NAME[name].hero == "Common"):
            classification = ItemClassification.useful  # never required by logic
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
            packs = [p for p in PACKS if p.hero in self.heroes]
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
        if LEGENDARY_ITEMS in groups:
            excluded |= LEGENDARY_GUIDS  # unlocked by the group item, never individually
        pool += groups
        pool += [SELL_TRAP] * min(self.options.sell_traps.value, max(0, slots - len(pool)))

        budget = (slots - len(pool)) * self.options.locked_cards_percent.value // 100
        duplicated = self.options.duplicate_cards.value
        if self.options.duplicate_all_cards:
            cards = self.pick_cards(budget // 2, excluded)
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

        copies += self.extra_copies(slots - len(pool) - len(copies), pool + copies, cards)
        self.multiworld.itempool += [self.create_item(name) for name in pool]
        # extra copies: the same items, but logic never needs them (the first copy is the one that counts)
        self.multiworld.itempool += [BazaarItem(name, ItemClassification.useful, item_name_to_id[name], self.player)
                                     for name in copies]
        # The Bazaar has no natural filler; this only happens when there's nothing left to duplicate
        self.multiworld.itempool += [self.create_filler() for _ in range(slots - len(pool) - len(copies))]

    def create_items_from_slot_data(self, data: Dict[str, Any]) -> None:
        """Universal Tracker only needs the same locations and rules; the item pool just has to be the right size."""
        self.lock_items, self.group_items = lock_items_by_hero(data["lock_items"])
        pool = [hero_item(h) for h in self.heroes if h != self.starting_hero]
        pool += [name for names_ in self.lock_items.values() for name in names_] + self.group_items
        slots = len(self.multiworld.get_unfilled_locations(self.player))
        self.multiworld.itempool += [self.create_item(name) for name in pool[:slots]]
        self.multiworld.itempool += [self.create_filler() for _ in range(slots - min(slots, len(pool)))]

    def extra_copies(self, free: int, placed: List[str], cards: List[str]) -> List[str]:
        """Fill `free` slots with duplicates: hero unlocks, then group unlocks, then locked cards (max 3 each)."""
        count = {name: placed.count(name) for name in set(placed)}
        extra: List[str] = []
        heroes = [hero_item(h) for h in self.heroes if h != self.starting_hero]
        groups = [name for name in GROUP_ITEMS if count.get(name)]
        for tier in (heroes, groups, self.random.sample(cards, len(cards))):
            progressing = True
            while progressing and len(extra) < free:
                progressing = False
                for name in tier:
                    if len(extra) < free and count.get(name, 0) < MAX_COPIES:
                        count[name] = count.get(name, 0) + 1
                        extra.append(name)
                        progressing = True
        return extra

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
        self.starters = {}
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
        logic = {"day_10": self.options.logic_day_10_cards.value, "diamond": self.options.logic_diamond_cards.value,
                 "legendary": self.options.logic_legendary_cards.value}
        for hero in self.heroes:
            items = self.lock_items.get(hero, [])
            needs = card_requirements(hero, len(items), self.options.max_day.value, bool(self.options.pvp_win_checks),
                                      self.monster_tiers, logic)
            for name, count in needs.items():
                self.set_card_rule(name, items, count)
            self.set_card_rule(champion_event(hero), items, needs[win_location(hero)])

        self.multiworld.completion_condition[self.player] = \
            lambda state: state.has("Champion", self.player, self.goal_count)

    def set_card_rule(self, location_name: str, items: List[str], count: int) -> None:
        if count:
            self.get_location(location_name).access_rule = \
                lambda state: state.has_from_list_unique(items, self.player, count)  # duplicates count once

    def write_spoiler(self, spoiler_handle) -> None:
        lines = [f"The Bazaar ({self.player_name})",
                 f"  Starting hero: {self.starting_hero}   Goal: 10 wins with {self.goal_count} heroes"]
        lines += [f"  {hero}: {len(self.lock_items.get(hero, []))} locked cards/packs" for hero in self.heroes]
        lines.append(f"  Common: {len(self.lock_items.get('Common', []))} locked cards")
        if self.group_items:
            lines.append(f"  Group unlocks: {', '.join(self.group_items)}")
        for group, starters in sorted(getattr(self, "starters", {}).items()):
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
            "sell_trap_days": self.options.sell_trap_days.value,
            "logic": {"day_10": self.options.logic_day_10_cards.value,
                      "diamond": self.options.logic_diamond_cards.value,
                      "legendary": self.options.logic_legendary_cards.value},
            "death_link_on_concede": bool(self.options.death_link_on_concede.value),
        }
