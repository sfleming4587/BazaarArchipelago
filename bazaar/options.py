from dataclasses import dataclass

from Options import (Choice, DeathLink, DefaultOnToggle, OptionGroup, OptionSet, PerGameCommonOptions, Range,
                     StartInventoryPool, Toggle)

from .data import DLC_HEROES, HEROES


class OwnedDLCHeroes(OptionSet):
    """
    DLC heroes you own. Vanessa, Pygmalien and Dooley come with the base game and are always available.
    Valid names: Mak, Stelle, Jules, Karnok, The Dragons
    """
    display_name = "Owned DLC Heroes"
    valid_keys = frozenset(DLC_HEROES)
    default = frozenset()


class ExcludedHeroes(OptionSet):
    """Heroes you own but don't want in this multiworld. Their checks and cards are left out."""
    display_name = "Excluded Heroes"
    valid_keys = frozenset(HEROES)
    default = frozenset()


class StartingHero(Choice):
    """
    The hero you start with. Every other hero has to be found as an item.
    If the chosen hero isn't available (not owned or excluded), a random available hero is used instead.
    """
    display_name = "Starting Hero"
    option_any = 0
    option_vanessa = 1
    option_pygmalien = 2
    option_dooley = 3
    option_mak = 4
    option_stelle = 5
    option_jules = 6
    option_karnok = 7
    option_the_dragons = 8
    default = 0


class HeroesRequired(Range):
    """
    How many different heroes need a 10-win run to finish your goal.
    Only about 1 in 10 runs reaches 10 wins, so keep this modest.
    Capped at the number of heroes you have available.
    """
    display_name = "Heroes Required"
    range_start = 1
    range_end = len(HEROES)
    default = 3


class MaxDay(Range):
    """
    Each hero gets a "Reach Day N" check for every day from 1 up to this number.
    Getting 10 wins with a hero automatically sends all of that hero's day checks.
    """
    display_name = "Max Day Check"
    range_start = 5
    range_end = 20
    default = 15


class LockedCards(Range):
    """
    How many individual cards start locked. Locked cards may not be bought until you receive them.
    Cards are spread evenly across your available heroes (and the common pool, if enabled).
    Lowered automatically if there aren't enough checks to hold them all.
    """
    display_name = "Locked Cards"
    range_start = 0
    range_end = 400
    default = 90


class LockCommonCards(DefaultOnToggle):
    """Allow cards from the Common pool (usable by every hero) to be locked."""
    display_name = "Lock Common Cards"


class LegacyCardPacks(Toggle):
    """
    Lock the ten original hero expansion packs (e.g. Mysteries of the Deep, Dooltron, Pigglestorm) as single items.
    Receiving a pack unlocks all 10 of its cards at once. Only applies to heroes you have available.
    Pack cards are never picked as individual locks.
    """
    display_name = "Legacy Card Packs"


class LockEnforcement(Choice):
    """
    What the client does when you buy a card that's still locked.
    warn: show a warning, nothing else happens.
    strict: the current run stops sending checks (days and the 10-win check).
    """
    display_name = "Locked Card Enforcement"
    option_warn = 0
    option_strict = 1
    default = 0


class BazaarDeathLink(DeathLink):
    """
    When you lose a run, everyone else with DeathLink dies.
    When someone else dies, you must abandon your current run (Settings > Abandon Run).
    The client can't do this for you: automating game input is against Tempo's modding policy.
    """


class DeathLinkAmnesty(Range):
    """Number of lost runs that are forgiven before a DeathLink is sent (0 = every lost run sends one)."""
    display_name = "DeathLink Amnesty"
    range_start = 0
    range_end = 10
    default = 0


@dataclass
class BazaarOptions(PerGameCommonOptions):
    owned_dlc_heroes: OwnedDLCHeroes
    excluded_heroes: ExcludedHeroes
    starting_hero: StartingHero
    heroes_required: HeroesRequired
    max_day: MaxDay
    locked_cards: LockedCards
    lock_common_cards: LockCommonCards
    legacy_card_packs: LegacyCardPacks
    lock_enforcement: LockEnforcement
    death_link: BazaarDeathLink
    death_link_amnesty: DeathLinkAmnesty
    start_inventory_from_pool: StartInventoryPool


option_groups = [
    OptionGroup("Heroes", [OwnedDLCHeroes, ExcludedHeroes, StartingHero, HeroesRequired, MaxDay]),
    OptionGroup("Card Locks", [LockedCards, LockCommonCards, LegacyCardPacks, LockEnforcement]),
    OptionGroup("DeathLink", [BazaarDeathLink, DeathLinkAmnesty]),
]
