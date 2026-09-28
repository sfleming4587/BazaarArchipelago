import math
from typing import Any, ClassVar, Dict, List, Mapping

import settings
from BaseClasses import ItemClassification, Region, Tutorial
from Options import OptionError
from worlds.AutoWorld import WebWorld, World
from worlds.LauncherComponents import Component, Type, components, launch

from .data import BASE_HEROES, CARDS, CARDS_BY_NAME, HEROES, PACKS
from .items import (FILLER_ITEMS, GAME, PACKS_BY_ITEM, BazaarItem, hero_item, item_name_groups, item_name_to_id,
                    pack_item)
from .locations import (BazaarLocation, champion_event, day_location, location_name_groups, location_name_to_id,
                        win_location)
from .options import BazaarOptions, option_groups


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
    tutorials = [Tutorial(
        "Multiworld Setup Guide",
        "How to set up The Bazaar for Archipelago.",
        "English",
        "setup_en.md",
        "setup/en",
        ["Sulldog"],
    )]


def days_card_requirement(day: int, lock_count: int) -> int:
    """How many of a hero's own locked items logic expects before a given day (day 21 = the 10-win check)."""
    if day <= 5:
        return 0
    if day <= 10:
        return math.ceil(lock_count * 0.25)
    return math.ceil(lock_count * 0.5)


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

    heroes: List[str]
    starting_hero: str
    goal_count: int
    lock_items: Dict[str, List[str]]  # hero (or "Common") -> lock item names placed in the pool

    def generate_early(self) -> None:
        owned = set(BASE_HEROES) | set(self.options.owned_dlc_heroes.value)
        self.heroes = [h for h in HEROES if h in owned and h not in self.options.excluded_heroes.value]
        if not self.heroes:
            raise OptionError(f"{self.player_name}: every hero is excluded, at least one is needed.")

        wanted = self.options.starting_hero.current_key.replace("_", " ")
        matches = [h for h in self.heroes if h.lower() == wanted]
        self.starting_hero = matches[0] if matches else self.random.choice(self.heroes)
        self.multiworld.push_precollected(self.create_item(hero_item(self.starting_hero)))

        self.goal_count = min(self.options.heroes_required.value, len(self.heroes))

    def create_regions(self) -> None:
        menu = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu)
        for hero in self.heroes:
            region = Region(hero, self.player, self.multiworld)
            names = [day_location(hero, d) for d in range(1, self.options.max_day.value + 1)] + [win_location(hero)]
            region.add_locations({name: location_name_to_id[name] for name in names}, BazaarLocation)

            champion = BazaarLocation(self.player, champion_event(hero), None, region)
            champion.place_locked_item(BazaarItem("Champion", ItemClassification.progression, None, self.player))
            region.locations.append(champion)

            self.multiworld.regions.append(region)
            menu.connect(region, f"Play {hero}", lambda state, h=hero: state.has(hero_item(h), self.player))

    def create_item(self, name: str) -> BazaarItem:
        if name in FILLER_ITEMS:
            classification = ItemClassification.filler
        elif name in CARDS_BY_NAME and CARDS_BY_NAME[name].hero == "Common":
            classification = ItemClassification.useful
        else:
            classification = ItemClassification.progression
        return BazaarItem(name, classification, item_name_to_id[name], self.player)

    def get_filler_item_name(self) -> str:
        return self.random.choice(FILLER_ITEMS)

    def create_items(self) -> None:
        slots = len(self.multiworld.get_unfilled_locations(self.player))
        pool = [hero_item(h) for h in self.heroes if h != self.starting_hero]

        packs = []
        if self.options.legacy_card_packs:
            packs = [p for p in PACKS if p.hero in self.heroes]
            self.random.shuffle(packs)
            packs = packs[:max(0, slots - len(pool))]
        pack_guids = {guid for p in packs for guid in p.cards}
        pool += [pack_item(p.name) for p in packs]

        cards = self.pick_cards(min(self.options.locked_cards.value, slots - len(pool)), pack_guids)
        pool += cards

        self.lock_items = {}
        for p in packs:
            self.lock_items.setdefault(p.hero, []).append(pack_item(p.name))
        for name in cards:
            self.lock_items.setdefault(CARDS_BY_NAME[name].hero, []).append(name)

        self.multiworld.itempool += [self.create_item(name) for name in pool]
        self.multiworld.itempool += [self.create_filler() for _ in range(slots - len(pool))]

    def pick_cards(self, count: int, excluded_guids: set) -> List[str]:
        """Spread `count` locks as evenly as possible over each hero pool (and the Common pool)."""
        groups = self.heroes + (["Common"] if self.options.lock_common_cards else [])
        candidates = {g: [c.name for c in CARDS if c.hero == g and c.shop and c.guid not in excluded_guids]
                      for g in groups}
        for names in candidates.values():
            self.random.shuffle(names)
        picked: List[str] = []
        while len(picked) < count and any(candidates.values()):
            for group in self.random.sample(groups, len(groups)):
                if candidates[group] and len(picked) < count:
                    picked.append(candidates[group].pop())
        return picked

    def set_rules(self) -> None:
        for hero in self.heroes:
            items = self.lock_items.get(hero, [])
            for day in range(1, self.options.max_day.value + 1):
                self.set_card_rule(day_location(hero, day), items, days_card_requirement(day, len(items)))
            late = days_card_requirement(21, len(items))
            self.set_card_rule(win_location(hero), items, late)
            self.set_card_rule(champion_event(hero), items, late)

        self.multiworld.completion_condition[self.player] = \
            lambda state: state.has("Champion", self.player, self.goal_count)

    def set_card_rule(self, location_name: str, items: List[str], count: int) -> None:
        if count:
            self.get_location(location_name).access_rule = \
                lambda state: state.has_from_list(items, self.player, count)

    def fill_slot_data(self) -> Mapping[str, Any]:
        return {
            "heroes": self.heroes,
            "starting_hero": self.starting_hero,
            "max_day": self.options.max_day.value,
            "heroes_required": self.goal_count,
            "lock_items": sorted(item_name_to_id[name] for names in self.lock_items.values() for name in names),
            "lock_enforcement": self.options.lock_enforcement.current_key,
            "death_link": bool(self.options.death_link.value),
            "death_link_amnesty": self.options.death_link_amnesty.value,
        }
