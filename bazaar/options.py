import types
from dataclasses import dataclass, make_dataclass

from Options import (Choice, DeathLink, DefaultOnToggle, ItemSet, Option, OptionGroup, PerGameCommonOptions, Range,
                     StartInventoryPool, Toggle)

from .data import BASE_HEROES, CARDS, HEROES, PACKS, TIERS, hero_key


def _switch(class_name: str, display_name: str, doc: str, on: bool = False) -> type:
    """An on/off option made from data, so a new hero or pack needs no new class."""
    def body(namespace: dict) -> None:
        namespace.update(__doc__=doc, display_name=display_name, __module__=__name__)
    option = types.new_class(class_name, (DefaultOnToggle if on else Toggle,), exec_body=body)
    globals()[class_name] = option  # findable by name, so it can be pickled (the website pickles option values)
    return option


# Heroes are picked by ticking, never by typing names (user 2026-09-29), in one "Included Heroes (Must own)" list
# (user 2026-10-05): a hero left unticked isn't in the seed. Built from data.HEROES, so a hero added by a patch gets
# its switch automatically. option name -> hero.
INCLUDE_HERO_OPTIONS = {f"include_{hero_key(h)}": h for h in HEROES}
INCLUDE_SWITCHES = {name: _switch(f"Include{hero.replace(' ', '')}", hero,
                                  f"Include {hero} in your seed." + ("" if hero in BASE_HEROES else
                                                                     f" Requires owning {hero} (DLC).")
                                  + f"\n\nIf disabled, {hero} has no checks, cards or unlock item.",
                                  on=hero in BASE_HEROES)
                    for name, hero in INCLUDE_HERO_OPTIONS.items()}
# One switch per legacy pack (user 2026-09-30: "doesn't have to be all or none"), named from the pack's data key so a
# renamed pack keeps its option. On by default: legacy_card_packs alone still means every pack. option name -> key.
PACK_OPTIONS = {f"pack_{p.key.lower()}": p.key for p in PACKS}
PACK_SWITCHES = {name: _switch(f"Pack{p.key.replace('_', '')}", f"{p.hero}: {p.name}",
                               f"Locks {p.name} as a single item.\n\nOnly matters when Legacy Card Packs is enabled. "
                               f"If disabled, its cards are locked one by one like any other card.", on=True)
                 for name, p in zip(PACK_OPTIONS, PACKS)}


def _starting_hero_body(namespace: dict) -> None:
    namespace.update(
        __doc__="""
    The hero you start with.

    Every other hero has to be found as an item. If this hero isn't one of your included heroes, a random included
    hero is picked instead.
    """,
        display_name="Starting Hero", default=0, __module__=__name__, option_any=0,
        # values follow data.HEROES, which is append-only, so a saved choice never changes meaning
        **{f"option_{hero_key(h)}": number for number, h in enumerate(HEROES, start=1)})


StartingHero = types.new_class("StartingHero", (Choice,), exec_body=_starting_hero_body)


class EarlyHeroUnlock(Toggle):
    """
    Places a second hero's unlock early, so you get another hero sooner.

    Usually not needed, since spare checks already add extra copies of hero unlocks.
    """
    display_name = "Early Hero Unlock"


class HeroesRequired(Range):
    """
    How many different heroes need a 10-win run to complete your goal.

    This can't be higher than the number of included heroes.
    """
    display_name = "Heroes Required"
    range_start = 1
    range_end = len(HEROES)
    default = 3


class MaxDay(Range):
    """
    The last day that has checks.

    Every day up to this one has Reach Day, PvP Win and Monster checks. Getting 10 wins with a hero sends every check
    that hero has left. Days past 16 only happen through specific events, so 16 is the maximum.
    """
    display_name = "Last Day With Checks"
    range_start = 5
    range_end = 16  # later days need specific events; ids stay reserved up to MAX_DAY for old seeds
    default = 13


class PvPWinChecks(DefaultOnToggle):
    """
    Adds a check for winning the PvP fight at the end of each day.
    """
    display_name = "PvP Win Checks"


class MonsterChecks(DefaultOnToggle):
    """
    Adds checks for beating the monster you pick each day.

    There's one check per rarity that day's monsters can be: day 1 goes up to Silver, day 2 up to Gold, days 3 to 5
    up to Diamond and day 6 onward up to Legendary. Beating a monster sends its rarity and every rarity below it.
    Only the monster you pick at hour 3 counts, not monsters from events.
    """
    display_name = "Monster Checks"


def _max_monster_tier_body(namespace: dict) -> None:
    namespace.update(
        __doc__="""
    The highest monster rarity that has checks.

    Choose Diamond to leave out Legendary monster checks.
    """,
        display_name="Highest Monster Rarity", default=TIERS.index("Diamond"), __module__=__name__,
        **{f"option_{tier.lower()}": number for number, tier in enumerate(TIERS)})  # from data.TIERS


MaxMonsterTier = types.new_class("MaxMonsterTier", (Choice,), exec_body=_max_monster_tier_body)


class LockedCardsPercent(Range):
    """
    How many of your spare checks hold a locked card.

    Locked cards can't be bought or kept until you receive them, and they're spread evenly across your heroes.
    Spare checks are the ones left after hero unlocks, packs, group unlocks, Sell Traps and Lock Bypasses.

    Below 100, the rest get extra copies instead: extra hero unlocks first, then extra copies of locked cards (up to
    3 of each). Copy counts you set yourself never change. Does nothing if Duplicate All Cards is enabled.
    """
    display_name = "Locked Cards Percent"
    range_start = 0
    range_end = 100
    default = 80


class StarterCards(Range):
    """
    How many Bronze cards per hero are never locked.

    This makes sure the early days always have something to buy.
    """
    display_name = "Starter Cards"
    range_start = 0
    range_end = 60
    default = 20


class LegendaryItems(Range):
    """
    Number of Legendary Items unlocks in the item pool.

    Every Legendary item is locked until you find the first one. Extra copies just make it show up sooner. Set to 0
    to never lock Legendary items. Logic expects it before Legendary monster checks.
    """
    display_name = "Legendary Items Unlocks"
    range_start = 0
    range_end = 3
    default = 2


class ExpeditionTickets(Range):
    """
    Number of Expedition Tickets unlocks in the item pool.

    The Crash Site and Temple tickets are locked until you find the first one. Set to 0 to never lock the tickets.
    """
    display_name = "Expedition Tickets Unlocks"
    range_start = 0
    range_end = 3
    default = 2


class LockedEncountersPercent(Range):
    """
    How many of the merchants and events you can run into are locked behind an item.

    You can still visit a locked merchant, but anything you buy there counts as a locked card. Going into any other
    locked event blocks your checks for the rest of the run, unless you use a Lock Bypass on it.

    Level-up rewards and monsters are never locked. If every event you're offered is locked, the least rare one is
    let through. Set to 0 to turn this off.
    """
    display_name = "Locked Merchants and Events Percent"
    range_start = 0
    range_end = 100
    default = 25


class StarterMerchants(Range):
    """
    How many merchants are never locked.

    This makes sure there's always somewhere to shop.
    """
    display_name = "Starter Merchants"
    range_start = 0
    range_end = 20
    default = 5


class EventRarityProgression(Range):
    """
    Number of Event Rarity Progression items in the item pool.

    Diamond merchants and events are locked until you find the first one, and the second one unlocks Legendary ones.
    Any extra copies count as Lock Bypasses. Logic expects the first one before PvP wins from day 8, and the second
    from day 14. Monsters and level-up rewards are never affected. Set to 0 to turn this off.
    """
    display_name = "Event Rarity Progression"
    range_start = 0
    range_end = 5
    default = 3


class ExemptExpeditions(DefaultOnToggle):
    """
    Keeps the Crash Site and Temple expeditions unlocked by Event Rarity Progression.

    The tickets still need the Expedition Tickets unlock.
    """
    display_name = "Exempt Expeditions"


class DuplicateAllCards(Toggle):
    """
    Gives every locked card a second copy, for a more casual game.

    Either copy unlocks the card, so you deal with about half as many locked cards over the same number of checks.
    Locked Cards Percent does nothing while this is enabled.
    """
    display_name = "Duplicate All Cards (casual)"


class DuplicateCards(ItemSet):
    """
    Cards that get a second copy in the item pool if they're locked.

    Either copy unlocks the card.
    """
    display_name = "Duplicate Cards"
    valid_keys = frozenset(c.name for c in CARDS if not c.ticket)


class SellTraps(Range):
    """
    Number of Sell Traps in the item pool.

    When you receive one, the client picks a random item you're holding. Sell it before the deadline from Sell Trap
    Days, or your checks are blocked until you do. A trap never blocks the fight you're in, and each one replaces a
    locked card in the pool. Set to 0 to turn them off.
    """
    display_name = "Sell Traps"
    range_start = 0
    range_end = 20
    default = 3


class SellTrapDays(Range):
    """
    How many days you get to sell a Sell Trap's item.

    For example, getting one on day 3 with 2 days means you have to sell it before day 5 starts.
    """
    display_name = "Sell Trap Days"
    range_start = 1
    range_end = 5
    default = 2


class LockBypasses(Range):
    """
    Number of Lock Bypasses in the item pool.

    When you're holding a locked card, press Use Bypass next to it in the client to keep it for the rest of the run,
    upgrades and extra copies included. Bypasses are never used automatically, and unused ones carry over to later
    runs. Each one replaces a locked card in the pool. Set to 0 to turn them off.
    """
    display_name = "Lock Bypasses"
    range_start = 0
    range_end = 20
    default = 5


class LogicDay10Cards(Range):
    """
    How many of a hero's locked cards logic expects you to have before day 10.

    Days 8 and 9 expect half as many, and days 1 to 7 only need the hero, since every run makes it to day 7. Later
    days climb from here up to Logic: Cards Before The Last Day. This only affects where items get placed, you can
    always try anything.
    """
    display_name = "Logic: Cards Before Day 10"
    range_start = 0
    range_end = 30  # lowered for a seed with too few checks that need no cards (see BazaarWorld.fit_logic)
    default = 16


class LogicLastDayCards(Range):
    """
    How many of a hero's locked cards logic expects you to have before the last day and the 10-win check.

    From day 10 on, the amount climbs evenly from Logic: Cards Before Day 10 up to this number. If your last day is 10
    or lower, the day 10 amount is used. This only affects where items get placed, you can always try anything.
    """
    display_name = "Logic: Cards Before The Last Day"
    range_start = 0
    range_end = 80  # lowered for a seed with too few checks that need no cards (see BazaarWorld.fit_logic)
    default = 28


class LogicDiamondCards(Range):
    """
    How many of a hero's locked cards logic expects you to have before beating a Diamond monster.
    """
    display_name = "Logic: Cards Before Diamond Monsters"
    range_start = 0
    range_end = 30  # lowered for a seed with too few checks that need no cards (see BazaarWorld.fit_logic)
    default = 10


class LogicLegendaryCards(Range):
    """
    How many of a hero's locked cards logic expects you to have before beating a Legendary monster.
    """
    display_name = "Logic: Cards Before Legendary Monsters"
    range_start = 0
    range_end = 30  # lowered for a seed with too few checks that need no cards (see BazaarWorld.fit_logic)
    default = 20


class LockCommonCards(DefaultOnToggle):
    """
    Lets Common cards be locked too.

    Common cards are the neutral ones every hero can use.
    """
    display_name = "Lock Common Cards"


class LockLootItems(Toggle):
    """
    Lets Loot items be locked too.

    Loot items are things like Med Kit, Reroll Token, Skill Voucher, Upgrade Hammer and Scrap. They're meant to be
    used or sold, so they're left out by default.
    """
    display_name = "Lock Loot Items"


class CreatedItems(Choice):
    """
    Decides if cards the game makes for you count as locked.

    This covers cards spawned by other cards, like the Scrap you get from selling Temporary Shelter, and cards
    transformed outside of a fight, like at Mandala or by selling Catalyst. Anything The Cult gives you is always
    allowed.

    - **Allowed:** Every created card is yours to keep, even if it's locked.
    - **Special Cases:** Only cards that are meant to be made are allowed. That's the first transform of Mak's
      Reagents, anything from Wink, Soda and Vending Machine drinks, and items that always spawn the same card (like
      Temporary Shelter's Scrap). Everything else is treated like Locked.
    - **Locked:** A created card that's still locked blocks your checks until you sell it, transform it again or use
      a Lock Bypass on it.
    """
    display_name = "Created Items"
    option_allowed = 0
    option_special_cases = 1
    option_locked = 2
    default = 1


class LegacyCardPacks(Toggle):
    """
    Locks the original hero expansion packs as single items.

    Receiving a pack unlocks all 10 of its cards at once, like Mysteries of the Deep, Dooltron or Pigglestorm. Only
    packs for your included heroes are used, and you can leave out any pack with its switch below.

    Packs lock a lot more cards overall, so Duplicate All Cards is recommended with this. A Standard seed with the
    base heroes has about 200 locked cards without packs, 275 with all of them, and 190 with Duplicate All Cards too.
    """
    display_name = "Legacy Card Packs"


class BazaarDeathLink(DeathLink):
    """
    When you lose a run, everyone else with DeathLink dies, and when they die, you have to concede your run.

    A run is lost when your last PvP fight takes the rest of your prestige. Conceding doesn't send a DeathLink unless
    DeathLink On Concede is enabled. The client can't concede for you, since automating game input is against Tempo's
    modding policy.
    """


class DeathLinkOnConcede(Toggle):
    """
    Conceding a run also sends a DeathLink.

    Conceding because you received a DeathLink never sends one.
    """
    display_name = "DeathLink On Concede"


class DeathLinkAmnesty(Range):
    """
    How many of your DeathLinks are forgiven before one is actually sent.

    Set to 0 to send every one.
    """
    display_name = "DeathLink Amnesty"
    range_start = 0
    range_end = 10
    default = 0


class DeathLinksBeforeConcede(Range):
    """
    How many DeathLinks you need to receive before you have to concede a run.

    Set to 1 to concede on every one. The count starts over after you concede, and DeathLinks that arrive while you're
    not in a run don't count. See DeathLinks In The Same Run for whether they have to arrive in one run.
    """
    display_name = "DeathLinks Before Concede"
    range_start = 1
    range_end = 10
    default = 2


class DeathLinksSameRun(DefaultOnToggle):
    """
    The DeathLinks for DeathLinks Before Concede have to arrive during the same run.

    The count starts over every new run. If disabled, they add up across runs.
    """
    display_name = "DeathLinks In The Same Run"


@dataclass
class _BazaarOptions(PerGameCommonOptions):
    starting_hero: StartingHero
    heroes_required: HeroesRequired
    early_hero_unlock: EarlyHeroUnlock
    max_day: MaxDay
    pvp_win_checks: PvPWinChecks
    monster_checks: MonsterChecks
    max_monster_tier: MaxMonsterTier
    locked_cards_percent: LockedCardsPercent
    lock_common_cards: LockCommonCards
    lock_loot_items: LockLootItems
    created_items: CreatedItems
    starter_cards: StarterCards
    legendary_items: LegendaryItems
    expedition_tickets: ExpeditionTickets
    duplicate_all_cards: DuplicateAllCards
    duplicate_cards: DuplicateCards
    locked_encounters_percent: LockedEncountersPercent
    starter_merchants: StarterMerchants
    event_rarity_progression: EventRarityProgression
    exempt_expeditions: ExemptExpeditions
    sell_traps: SellTraps
    sell_trap_days: SellTrapDays
    lock_bypasses: LockBypasses
    logic_day_10_cards: LogicDay10Cards
    logic_last_day_cards: LogicLastDayCards
    logic_diamond_cards: LogicDiamondCards
    logic_legendary_cards: LogicLegendaryCards
    legacy_card_packs: LegacyCardPacks
    death_link: BazaarDeathLink
    death_link_on_concede: DeathLinkOnConcede
    death_link_amnesty: DeathLinkAmnesty
    death_links_before_concede: DeathLinksBeforeConcede
    death_links_same_run: DeathLinksSameRun
    start_inventory_from_pool: StartInventoryPool


# the hero and pack switches are generated (see above), so they're added to the options here
BazaarOptions = make_dataclass("BazaarOptions", [(name, option) for name, option in {**INCLUDE_SWITCHES,
                                                                                     **PACK_SWITCHES}.items()],
                               bases=(_BazaarOptions,))


# One-click setups: the website's options page and the Launcher's "Generate Template Options" (Players/Templates/
# Presets). Standard is the option defaults and nothing else (user, 2026-09-30): change a default and Standard follows.
# Included heroes are never set by a preset.
option_presets = {
    "Casual": {
        "heroes_required": 1, "early_hero_unlock": True, "max_day": 12, "max_monster_tier": "gold",
        "locked_cards_percent": 60, "starter_cards": 30, "legendary_items": 3, "expedition_tickets": 3,
        "locked_encounters_percent": 10, "starter_merchants": 10,
        "sell_traps": 0, "lock_bypasses": 10, "created_items": "allowed",
        "logic_day_10_cards": 8, "logic_last_day_cards": 12, "logic_diamond_cards": 5, "logic_legendary_cards": 10,
        "death_link": False,
    },
    "Standard": {},
    "Hardcore": {
        "heroes_required": 6, "max_day": 16, "max_monster_tier": "legendary", "locked_cards_percent": 100,
        "starter_cards": 10, "legendary_items": 1, "expedition_tickets": 1, "legacy_card_packs": True,
        "locked_encounters_percent": 50, "starter_merchants": 2, "event_rarity_progression": 2,
        "sell_traps": 10, "sell_trap_days": 1, "lock_bypasses": 0, "created_items": "locked",
        "logic_day_10_cards": 25, "logic_last_day_cards": 50, "logic_diamond_cards": 20, "logic_legendary_cards": 30,
        "death_link": True, "death_link_on_concede": True, "death_links_before_concede": 1,
    },
}

option_groups = [
    OptionGroup("Included Heroes (Must own)", list(INCLUDE_SWITCHES.values())),
    OptionGroup("Heroes", [StartingHero, HeroesRequired, EarlyHeroUnlock]),
    OptionGroup("Checks", [MaxDay, PvPWinChecks, MonsterChecks, MaxMonsterTier]),
    OptionGroup("Card Locks", [LockedCardsPercent, LockCommonCards, LockLootItems, CreatedItems, StarterCards,
                               LegendaryItems, ExpeditionTickets, DuplicateAllCards, DuplicateCards]),
    OptionGroup("Merchant and Event Locks", [LockedEncountersPercent, StarterMerchants, EventRarityProgression,
                                              ExemptExpeditions]),
    OptionGroup("Legacy Card Packs", [LegacyCardPacks, *PACK_SWITCHES.values()]),
    OptionGroup("Traps and Buffs", [SellTraps, SellTrapDays, LockBypasses]),
    OptionGroup("Logic", [LogicDay10Cards, LogicLastDayCards, LogicDiamondCards, LogicLegendaryCards]),
    OptionGroup("DeathLink", [BazaarDeathLink, DeathLinkOnConcede, DeathLinkAmnesty,
                                   DeathLinksBeforeConcede, DeathLinksSameRun]),
]


def _flow(doc: str) -> str:
    """One line per paragraph and per list item. The Launcher's Options Creator shows every line break in a tooltip,
    so the source's wrapping would break sentences in half there (the website joins them by itself)."""
    paragraphs, lines = [], []
    for line in [line.strip() for line in doc.strip().splitlines()] + [""]:
        if not line or line.startswith("- "):
            if lines:
                paragraphs.append(" ".join(lines))
            lines = [line] if line else []
            if not line:
                paragraphs.append("")
        else:
            lines.append(line)
    return "\n".join(paragraphs).strip().replace("\n\n\n", "\n\n")


for _option in list(globals().values()):
    if isinstance(_option, type) and issubclass(_option, Option) and _option.__module__ == __name__ and _option.__doc__:
        _option.__doc__ = _flow(_option.__doc__)
