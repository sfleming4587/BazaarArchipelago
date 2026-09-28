# The Bazaar

## What does randomization do to this game?

You start with one hero. Every other hero, plus a set of locked cards, is shuffled into the multiworld.
Until you receive a hero you may not play them, and until you receive a locked card you may not buy it.

The game itself is never modified. The Bazaar is online-only and Tempo's modding policy forbids client mods,
so this integration only reads the log file the game writes on your PC. Locks are enforced by you
(honor system), with the client warning you when you break one.

## What are the checks?

- **Reach Day N** with each hero, from day 1 up to the `max_day` option (default 15).
- **10 Wins** with each hero.

Getting 10 wins with a hero also sends every one of that hero's day checks, since winning fast ends a run early.

## What is the goal?

Get 10 wins with a number of different heroes (the `heroes_required` option).

## What items can I receive?

- **Hero: X** - you may now play hero X.
- **Individual cards** - you may now buy that card.
- **Pack: X** (optional, `legacy_card_packs`) - one of the ten original hero expansions, such as Mysteries of the
  Deep or Dooltron. Unlocks all of its cards at once.
- Filler items with no effect.

## Rules you enforce yourself

- Only play heroes you've received.
- Don't buy locked cards. If an event or reward hands you one, sell it or keep it off your board.
  Use `/locked` in the client to see what's locked.
- DeathLink: when someone else dies, abandon your current run.

## Is this allowed by Tempo?

The client only reads `Player.log`, which falls under "display of information local to the user" in Tempo's
[Third-Party Plugin & Modding Policy](https://www.playthebazaar.com/mod-policy). It never modifies the game, reads
game memory, contacts Tempo's servers or sends input to the game. Tempo's policy can change, so check it yourself.
