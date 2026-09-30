import types
from dataclasses import dataclass, make_dataclass

from Options import (Choice, DeathLink, DefaultOnToggle, ItemSet, OptionGroup, OptionSet, PerGameCommonOptions,
                     Range, Removed, StartInventoryPool, Toggle, Visibility)

from .data import CARDS, DLC_HEROES, HEROES, PACKS, TIERS, hero_key


class OwnedDLCHeroes(OptionSet):
    """
    Old way to list the DLC heroes you own (still accepted, so older YAMLs keep working). Use the "Own ..." options
    instead: they're simple on/off switches.
    """
    display_name = "Owned DLC Heroes (old)"
    valid_keys = frozenset(DLC_HEROES)
    default = frozenset()
    visibility = Visibility.none  # hidden from the website, the Options Creator and new templates


def _switch(class_name: str, display_name: str, doc: str, on: bool = False) -> type:
    """An on/off option made from data, so a new hero or pack needs no new class."""
    def body(namespace: dict) -> None:
        namespace.update(__doc__=doc, display_name=display_name, __module__=__name__)
    return types.new_class(class_name, (DefaultOnToggle if on else Toggle,), exec_body=body)


# Heroes are picked by ticking, never by typing names (user 2026-09-29). Built from data.HEROES, so a hero added
# by a patch gets its switches automatically. option name -> hero.
OWN_HERO_OPTIONS = {f"own_{hero_key(h)}": h for h in DLC_HEROES}
EXCLUDE_HERO_OPTIONS = {f"exclude_{hero_key(h)}": h for h in HEROES}
OWN_SWITCHES = {name: _switch(f"Own{hero.replace(' ', '')}", f"Own {hero}",
                              f"You own {hero} (DLC hero). Vanessa, Pygmalien and Dooley come with the base game "
                              f"and are always in.")
                for name, hero in OWN_HERO_OPTIONS.items()}
EXCLUDE_SWITCHES = {name: _switch(f"Exclude{hero.replace(' ', '')}", f"Exclude {hero}",
                                  f"Leave {hero} out of this multiworld even if you own them: no {hero} checks, "
                                  f"cards or unlock.")
                    for name, hero in EXCLUDE_HERO_OPTIONS.items()}
# One switch per legacy pack (user 2026-09-30: "doesn't have to be all or none"), named from the pack's data key so a
# renamed pack keeps its option. On by default: legacy_card_packs alone still means every pack. option name -> key.
PACK_OPTIONS = {f"pack_{p.key.lower()}": p.key for p in PACKS}
PACK_SWITCHES = {name: _switch(f"Pack{p.key.replace('_', '')}", f"{p.hero}: {p.name}",
                               f"With legacy_card_packs on, lock {p.name} ({p.hero}) as one item. Off: its cards are "
                               f"locked one by one like any other card.", on=True)
                 for name, p in zip(PACK_OPTIONS, PACKS)}


class ExcludedHeroes(OptionSet):
    """
    Old way to list heroes to leave out (still accepted, so older YAMLs keep working). Use the "Exclude ..."
    options instead: they're simple on/off switches.
    """
    display_name = "Excluded Heroes (old)"
    valid_keys = frozenset(HEROES)
    default = frozenset()
    visibility = Visibility.none  # hidden from the website, the Options Creator and new templates


def _starting_hero_body(namespace: dict) -> None:
    namespace.update(
        __doc__="""
    The hero you start with. Every other hero has to be found as an item.
    If the chosen hero isn't available (not owned or excluded), a random available hero is used instead.
    """,
        display_name="Starting Hero", default=0, __module__=__name__, option_any=0,
        # values follow data.HEROES, which is append-only, so a saved choice never changes meaning
        **{f"option_{hero_key(h)}": number for number, h in enumerate(HEROES, start=1)})


StartingHero = types.new_class("StartingHero", (Choice,), exec_body=_starting_hero_body)


class EarlyHeroUnlock(Toggle):
    """
    Puts a second hero's unlock among the checks you can do right away, so you get another hero early.
    Off by default: hero unlocks already have duplicate copies in the pool (up to 3 each), which usually
    makes them turn up early anyway.
    """
    display_name = "Early Hero Unlock"


class HeroesRequired(Range):
    """
    How many different heroes need a 10-win run to finish your goal.
    Capped at the number of heroes you have available (base heroes plus owned DLC heroes, minus excluded ones).
    """
    display_name = "Heroes Required"
    range_start = 1
    range_end = len(HEROES)
    default = 3


class MaxDay(Range):
    """
    Day-based checks (reach day, PvP win, monsters) exist for every day from 1 up to this number.
    Getting 10 wins with a hero sends all of that hero's "Reach Day" checks, plus the PvP and monster
    checks for the days that run never got to.
    Days after 16 only happen through specific events, so 16 is the highest.
    """
    display_name = "Max Day Check"
    range_start = 5
    range_end = 16  # later days need specific events; ids stay reserved up to MAX_DAY for old seeds
    default = 13


class PvPWinChecks(DefaultOnToggle):
    """Each hero gets a check for winning the PvP fight at the end of each day (up to max_day). The client counts
    wins by itself from the game's log."""
    display_name = "PvP Win Checks"


class MonsterChecks(DefaultOnToggle):
    """
    Each hero gets monster checks for each day, one per rarity that day's hour-3 monsters can have
    (day 1 up to Silver, day 2 up to Gold, days 3-5 up to Diamond, day 6+ up to Legendary).
    Beating a monster sends its rarity and every rarity below it for that day.
    Monsters from events (not the hour-3 monster choice) don't count.
    """
    display_name = "Monster Checks"


def _max_monster_tier_body(namespace: dict) -> None:
    namespace.update(
        __doc__="The highest monster rarity that has a check. Pick diamond to leave out Legendary monster checks.",
        display_name="Maximum Monster Difficulty", default=TIERS.index("Diamond"), __module__=__name__,
        **{f"option_{tier.lower()}": number for number, tier in enumerate(TIERS)})  # from data.TIERS


MaxMonsterTier = types.new_class("MaxMonsterTier", (Choice,), exec_body=_max_monster_tier_body)


class LockedCards(Removed):
    """Removed in 0.3.1: replaced by locked_cards_percent."""
    display_name = "Locked Cards"


class LockedCardsPercent(Range):
    """
    Percent of the checks left over (after hero, pack and group unlocks) that hold a different locked card.
    Locked cards may not be bought or kept until you receive them. They're spread evenly over your heroes
    (and the Common pool, if enabled).
    Below 100, the other checks hold duplicates instead: first extra hero unlocks (up to 3 of each), then extra
    copies of locked cards (up to 3 of each). Copy counts you set yourself never change: Legendary Items and
    Expedition Tickets unlocks, and cards in duplicate_cards (or every card, with duplicate_all_cards).
    """
    display_name = "Locked Cards Percent"
    range_start = 0
    range_end = 100
    default = 80


class StarterCards(Range):
    """
    For each hero (and the Common pool), this many Bronze cards are never locked, so early days always have
    something to buy even when lots of cards are locked.
    """
    display_name = "Starter Cards"
    range_start = 0
    range_end = 60
    default = 20


class LegendaryItems(Range):
    """
    Copies of the "Legendary Items" unlock in the multiworld. Every Legendary item is locked until the first copy
    is found; extra copies just make it likely to turn up sooner. 0 = Legendary items are never locked.
    """
    display_name = "Legendary Items Unlocks"
    range_start = 0
    range_end = 3
    default = 2


class ExpeditionTickets(Range):
    """
    Copies of the "Expedition Tickets" unlock in the multiworld. Expedition tickets (Crash Site, Temple) are
    locked until the first copy is found. 0 = tickets are never locked.
    """
    display_name = "Expedition Tickets Unlocks"
    range_start = 0
    range_end = 3
    default = 2


class DuplicateAllCards(Toggle):
    """
    Casual mode: the same number of checks, but only about half as many locked cards. Every locked card gets a
    second copy in the multiworld (either copy unlocks it), so half of the item slots hold duplicates - fewer cards
    to avoid, and each one turns up sooner.
    """
    display_name = "Duplicate All Cards (casual)"


class DuplicateCards(ItemSet):
    """Cards that get a second copy if they're locked (either copy unlocks the card), e.g. ["Cutlass"]."""
    display_name = "Duplicate Cards"
    valid_keys = frozenset(c.name for c in CARDS if not c.ticket)


class SellTraps(Range):
    """
    Number of Sell Traps in the multiworld (0 = off). When you receive one, the client picks a random item you're
    holding; sell it before the start of the day given by sell_trap_days or checks are blocked until you do.
    A trap never blocks the fight you're in. Each trap takes the place of one locked card.
    """
    display_name = "Sell Traps"
    range_start = 0
    range_end = 20
    default = 3


class SellTrapDays(Range):
    """Days you get to sell a Sell Trap's item: received on day 3 with 2 days means sell it before day 5 starts."""
    display_name = "Sell Trap Days"
    range_start = 1
    range_end = 5
    default = 2


class LockBypasses(Range):
    """
    Number of Lock Bypasses in the multiworld (0 = off). A buff: during a run, press Lock Bypass in the client's
    overlay and pick a locked card; it's allowed for the rest of that run, including more copies of it (upgrades).
    A bypass is never used by itself. Unused ones carry over to later runs. Each takes the place of one locked card.
    """
    display_name = "Lock Bypasses"
    range_start = 0
    range_end = 20
    default = 5


class LogicDay10Cards(Range):
    """
    Logic: how many of a hero's own locked cards should be unlocked before reaching day 10 is expected. Later days
    climb from here to Logic: Cards Before The Last Day. Days 8-9 expect half as many. Days 1-7 only need the hero
    (every run reaches day 7).
    This only decides where other players' items can be placed; you can always try anything.
    """
    display_name = "Logic: Cards Before Day 10"
    range_start = 0
    range_end = 30  # lowered for a seed with too few checks that need no cards (see BazaarWorld.fit_logic)
    default = 16


class LogicLastDayCards(Range):
    """
    Logic: how many of a hero's own locked cards should be unlocked before the last day (max_day) and the 10-win
    check. From day 10 the expected amount climbs evenly from Logic: Cards Before Day 10 up to this, so later days
    expect more cards. This only decides where other players' items can be placed; you can always try anything.
    """
    display_name = "Logic: Cards Before The Last Day"
    range_start = 0
    range_end = 80  # lowered for a seed with too few checks that need no cards (see BazaarWorld.fit_logic)
    default = 28


class LogicDiamondCards(Range):
    """Logic: how many of a hero's own locked cards are expected before beating a Diamond monster."""
    display_name = "Logic: Cards Before Diamond Monsters"
    range_start = 0
    range_end = 30  # lowered for a seed with too few checks that need no cards (see BazaarWorld.fit_logic)
    default = 10


class LogicLegendaryCards(Range):
    """Logic: how many of a hero's own locked cards are expected before beating a Legendary monster."""
    display_name = "Logic: Cards Before Legendary Monsters"
    range_start = 0
    range_end = 30  # lowered for a seed with too few checks that need no cards (see BazaarWorld.fit_logic)
    default = 20


class LockCommonCards(DefaultOnToggle):
    """Allow neutral cards (the Common pool, usable by every hero) to be locked."""
    display_name = "Lock Common Cards"


class LockLootItems(Toggle):
    """
    Allow Loot items (Med Kit, Reroll Token, Skill Voucher, Upgrade Hammer, Scrap, ...) to be locked.
    These are meant to be used or sold for their effect, so they're left out by default.
    """
    display_name = "Lock Loot Items"


class LegacyCardPacks(Toggle):
    """
    Lock the original hero expansion packs (e.g. Mysteries of the Deep, Dooltron, Pigglestorm) as single items.
    Receiving a pack unlocks all 10 of its cards at once. Only applies to heroes you have available.
    Pack cards are never picked as individual locks. Untick any pack below to leave it out.
    Recommended: also turn on Duplicate All Cards (casual). Each pack locks 10 cards with a single check, so packs lock
    far more cards in total (a Standard seed with the base heroes: about 200 without packs, 275 with all of them;
    with Duplicate All Cards too, about 190).
    """
    display_name = "Legacy Card Packs"


class LockEnforcement(Removed):
    """Removed in 0.2.5: checks are now always blocked while you hold a locked card or play a locked hero."""
    display_name = "Locked Card Enforcement"


class BazaarDeathLink(DeathLink):
    """
    When you lose a run (your last PvP fight takes the last of your prestige), everyone else with DeathLink dies.
    Conceding a run doesn't send one unless death_link_on_concede is on.
    When someone else dies, you must abandon your current run (Settings > Abandon Run).
    The client can't do this for you: automating game input is against Tempo's modding policy.
    """


class DeathLinkTrigger(Removed):
    """Removed in 0.4.1: a DeathLink is only sent when a run is lost (or conceded, see death_link_on_concede)."""
    display_name = "DeathLink Trigger"


class DeathLinkOnConcede(Toggle):
    """Conceding (abandoning) a run also sends a DeathLink. Conceding because you received a DeathLink never does.
    Off by default."""
    display_name = "DeathLink On Concede"


class DeathLinkAmnesty(Range):
    """Number of DeathLink triggers that are forgiven before one is sent (0 = every trigger sends one)."""
    display_name = "DeathLink Amnesty"
    range_start = 0
    range_end = 10
    default = 0


@dataclass
class _BazaarOptions(PerGameCommonOptions):
    owned_dlc_heroes: OwnedDLCHeroes
    excluded_heroes: ExcludedHeroes
    starting_hero: StartingHero
    heroes_required: HeroesRequired
    early_hero_unlock: EarlyHeroUnlock
    max_day: MaxDay
    pvp_win_checks: PvPWinChecks
    monster_checks: MonsterChecks
    max_monster_tier: MaxMonsterTier
    locked_cards: LockedCards
    locked_cards_percent: LockedCardsPercent
    lock_common_cards: LockCommonCards
    lock_loot_items: LockLootItems
    starter_cards: StarterCards
    legendary_items: LegendaryItems
    expedition_tickets: ExpeditionTickets
    duplicate_all_cards: DuplicateAllCards
    duplicate_cards: DuplicateCards
    sell_traps: SellTraps
    sell_trap_days: SellTrapDays
    lock_bypasses: LockBypasses
    logic_day_10_cards: LogicDay10Cards
    logic_last_day_cards: LogicLastDayCards
    logic_diamond_cards: LogicDiamondCards
    logic_legendary_cards: LogicLegendaryCards
    legacy_card_packs: LegacyCardPacks
    lock_enforcement: LockEnforcement
    death_link: BazaarDeathLink
    death_link_trigger: DeathLinkTrigger
    death_link_on_concede: DeathLinkOnConcede
    death_link_amnesty: DeathLinkAmnesty
    start_inventory_from_pool: StartInventoryPool


# the hero and pack switches are generated (see above), so they're added to the options here
BazaarOptions = make_dataclass("BazaarOptions", [(name, option) for name, option in {**OWN_SWITCHES,
                                                                                     **EXCLUDE_SWITCHES,
                                                                                     **PACK_SWITCHES}.items()],
                               bases=(_BazaarOptions,))


# One-click setups: the website's options page and the Launcher's "Generate Template Options" (Players/Templates/
# Presets). Standard is the option defaults and nothing else (user, 2026-09-30): change a default and Standard follows.
# Owned DLC heroes are never set by a preset.
option_presets = {
    "Casual": {
        "heroes_required": 1, "early_hero_unlock": True, "max_day": 12, "max_monster_tier": "gold",
        "locked_cards_percent": 60, "starter_cards": 30, "legendary_items": 3, "expedition_tickets": 3,
        "sell_traps": 0, "lock_bypasses": 10,
        "logic_day_10_cards": 8, "logic_last_day_cards": 12, "logic_diamond_cards": 5, "logic_legendary_cards": 10,
        "death_link": False,
    },
    "Standard": {},
    "Hardcore": {
        "heroes_required": 6, "max_day": 16, "max_monster_tier": "legendary", "locked_cards_percent": 100,
        "starter_cards": 10, "legendary_items": 1, "expedition_tickets": 1, "legacy_card_packs": True,
        "sell_traps": 10, "sell_trap_days": 1, "lock_bypasses": 0,
        "logic_day_10_cards": 25, "logic_last_day_cards": 50, "logic_diamond_cards": 20, "logic_legendary_cards": 30,
        "death_link": True, "death_link_on_concede": True,
    },
}

option_groups = [
    OptionGroup("Heroes", [*OWN_SWITCHES.values(), StartingHero, HeroesRequired, EarlyHeroUnlock]),
    OptionGroup("Excluded Heroes", list(EXCLUDE_SWITCHES.values())),
    OptionGroup("Checks", [MaxDay, PvPWinChecks, MonsterChecks, MaxMonsterTier]),
    OptionGroup("Card Locks", [LockedCardsPercent, LockCommonCards, LockLootItems, StarterCards,
                               LegendaryItems, ExpeditionTickets, DuplicateAllCards, DuplicateCards]),
    OptionGroup("Legacy Card Packs", [LegacyCardPacks, *PACK_SWITCHES.values()]),
    OptionGroup("Traps and Buffs", [SellTraps, SellTrapDays, LockBypasses]),
    OptionGroup("Logic", [LogicDay10Cards, LogicLastDayCards, LogicDiamondCards, LogicLegendaryCards]),
    OptionGroup("DeathLink", [BazaarDeathLink, DeathLinkOnConcede, DeathLinkAmnesty]),
]
