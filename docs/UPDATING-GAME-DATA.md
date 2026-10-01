# Updating the game data after a Bazaar patch

> ⚠️ **Frozen 2026-09-29 (EULA), lifted 2026-10-01 by the owner** ("re-extract the event data from the game
> files"; Tempo's mod policy is the only rulebook). Run the extractor with `--i-have-permission`. See DEVELOPERS.md,
> "Game data comes from the extractor".

**The apworld keeps working after a patch; updating only adds what the patch introduced.** The client tells you
when it's time: it warns once that the game version is newer than the data, or that it saw a card, hero or monster
it doesn't know (new cards are never locked, new heroes aren't in the seed, new monsters count as Bronze).

## What lives where

| Data | Source | File |
|---|---|---|
| Cards (items), tiers, sizes, tags | the game's local card database, via the extractor | `bazaar/data/bazaar_data.json` |
| Merchants and item-choice events (what they can offer) | same | same |
| Monsters and their rarity | same (`CombatEncounter` cards, `StartingTier`) | same |
| Every event (choice-screen cards: merchants and plain events) with rarity, heroes, tags, spawn rule | same (`EventEncounter` cards) | same, `events` |
| Game build the data came from | the newest `[VersionShow]` line in `Player.log` | `game_version` in the same file |
| First day each monster rarity appears | **observed in game** - the server decides this, it's not in local data | `FIRST_DAY_OF_TIER` in `bazaar/data/__init__.py` |
| Heroes (display names, order) | hand-kept list | `HEROES` / `HERO_ALIASES` in `tools/extract_data.py` |
| Hero names as the log writes them (`Changing EHero to X`) | hand-kept | `HERO_ALIASES` in `bazaar/logparser.py` |
| The log lines the client relies on | hand-kept regexes | top of `bazaar/logparser.py` (the docstring lists every line) |

## Steps

1. **Refresh the game's cache:** start The Bazaar, wait for the main menu, close it. This updates
   `%USERPROFILE%\AppData\LocalLow\Tempo Storm\The Bazaar\prod\cache\GameData.db`.
2. **Extract:** from the repo root run `python tools/extract_data.py --i-have-permission`. It opens the database read-only (it never
   changes game files, even with the game running) and prints counts, e.g.
   `1157 cards, 10 packs, 107 merchants, 379 item choices, 179 monsters`.
3. **New hero?** The extractor prints `WARNING: unknown hero names [...]`. Then:
   - append the display name to `HEROES` in `tools/extract_data.py` (append only - order sets location ids);
   - map the database name in `HERO_ALIASES` there (e.g. `"Hero8": "The Dragons"`);
   - start one run with the hero, find `Changing EHero to X` in `Player.log`, and add `X` to `HERO_ALIASES` in
     `bazaar/logparser.py` if it differs from the display name;
   - the starting-hero choice and the own/exclude switches are built from the data by themselves;
   - give the hero a tracker card: add it to `LAYOUT` in `tools/make_hero_cards.py` (and the picture) and to
     `CARD_ORDER` in `bazaar/tracker.py` (a hero without one shows as a plain card);
   - re-run the extractor.
4. **Monster days:** if a patch changes when rarities show up, update `FIRST_DAY_OF_TIER` from what players see
   in game (and note the date and who saw it in the comment).
5. **Check nothing was renumbered:** `git diff bazaar/data/bazaar_data.json` should only add entries or change
   stats. Existing `ap_id`s must never change (the extractor keeps them; don't edit them by hand).
6. **Test:** `cd Archipelago && ../.venv/Scripts/python.exe -m pytest worlds/bazaar`.
7. **Release:** bump `world_version` in `bazaar/archipelago.json`, then run
   `.venv/Scripts/python.exe tools/build_apworld.py` from the repo root; it writes `bazaar.apworld` there and
   into `releases/`.

## If the client says it can't recognise run starts

A patch changed the log. Play a short run, open the new `Player.log`, and compare it with the lines listed at the
top of `bazaar/logparser.py`; update the regexes and the tests in `bazaar/test/test_logparser.py`.

⚠️ Never add card data by scraping bazaardb.gg or other sites (bazaardb blocks bots and disallows it in robots.txt).
Card data comes only from the extractor above. Card *pictures* are separate: Bazaar DB's
image set, turned into the Shop Guide's picture zip by `tools/make_card_art.py` (see DEVELOPERS.md).
