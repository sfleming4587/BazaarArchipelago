# BazaarArchipelago - developer guide

Thanks for wanting to help! This page is for working on the apworld and the client. If you just want to play,
[README.md](README.md) is the place to start.

## The one big rule

The client only ever **reads**: the game's own `Player.log`, and - for the shop padlocks only - the game's memory,
through `bazaar/memreader.py`. Please keep it that way: no writing to memory, no injection, no automated input, no
calls to Tempo's servers, no changes to game files, and nothing about other players. **Nothing outside the game
either** (owner, 2026-10-01: "make sure this whole client is NOT TOUCHING ANYTHING outside of bazaar"): the game is
found by its own window (`memreader.game_window`), never by listing or opening other programs, and the mouse is only
read while the game is in front. Tempo's policy expressly
prohibits mods that change gameplay or combat flow, simulate combat, act without user input, or talk to the game's
server; the owner's ruling (2026-10-01) is that those are the lines that apply here. The reader is always on, with
no switch to turn it off (owner, 2026-10-01: "a cornerstone for how the archipelago client will work"); only a
failed check turns it off. Don't widen what it reads without the owner's OK (rules in `docs/MEMORY-READER.md`), and
nobody should risk their account to play a randomizer.

## Finding your way around

| Path | What it is |
|---|---|
| `bazaar/` | the world, packaged as `bazaar.apworld`. The player docs for the website are in `bazaar/docs/` |
| `bazaar/logparser.py` | `Player.log` parsing (no Archipelago imports, so it's easy to test on its own) |
| `bazaar/client.py` | the CommonClient-based client ("The Bazaar Client" in the Launcher); every run check goes through `send_run_checks` |
| `bazaar/overlay.py` | the overlay: `Overlay` is the client's handle (a command queue), `_Screen` the Tk thread (header, notices, pop-ups, menu panel, padlocks) |
| `bazaar/memreader.py` | reads the shop's offered cards from game memory, read-only; finds Mono's offsets by probing and turns itself off if a check fails (no Archipelago imports) |
| `bazaar/unity.py` | where things are on screen, read from the game's Unity objects (transforms, camera, colliders, interface boxes); pure reading, no game rules |
| `bazaar/follower.py` | moves the padlock windows on their own thread while their cards move, from where the cards are that instant (docs/OVERLAY.md "How padlocks keep up") |
| `bazaar/padlocks.py` | the padlock rules: where each one goes and whether it shows solid, see-through or hidden; pure, no windows or memory |
| `bazaar/shop_guide.py` | the Item Guide window (card pictures, or "no picture" boxes) |
| `bazaar/theme.py` | colours and the font shared by every window |
| `bazaar/merchants.py` | which cards a merchant / item choice can offer (from the game's spawn filters) |
| `bazaar/cardart.py` | Item Guide pictures: `data/card-art.zip` shipped in the apworld, decoded by Archipelago's SDL2_image |
| `bazaar/data/bazaar_data.json` | cards, packs, merchants, item choices, monsters, events |
| `bazaar/tracker.py`, `bazaar/screens.py` | the tracker window; monitor areas, keeping every window on one, and window styles |
| `bazaar/locations.py` | location names and ids, and `hero_checks` / `card_requirements`: the one definition of each hero's checks and what logic needs for them (world rules, client and tracker all use it) |
| `tools/make_hero_cards.py` | cuts the tracker's hero cards (`bazaar/data/heroes/`) from `tools/art/Characters.png` |
| `tools/make_card_art.py` | builds `card-art.zip` from the card pictures; `--add <folder>` adds or replaces blank ones |
| `tools/make_item_symbols.py` | draws a symbol for each item with no card behind it (Lock Bypass, Trap Shield, the trap, the buffs) |
| `tools/make_tracker_icons.py` | fills the Tracker's square icons and the Sell Trap skull from `tools/icons/` (game-icons.net, CC BY 3.0) into `bazaar/data/icons.json`; `--preview <png>` shows every candidate on every square colour |
| `tools/build_apworld.py` | builds `bazaar.apworld` (repo root + `releases/`) without opening a window |
| `tools/quick_run.ps1` | a solo test game: generate, host locally, open the client |
| `docs/UPDATING-GAME-DATA.md` | what to do after a Bazaar patch |
| `docs/ENCOUNTER-LOCKS.md` | merchant and event locks and Event Rarity Progression: the owner's rulings, how the pool is built, what's built so far |
| `docs/CARD-PACKS.md` | legacy and custom card packs: where each lives, how custom cards were picked, the rules the tests hold |
| `docs/CREATED-ITEMS.md` | the Created Items option: rulings, how spawns and transforms are spotted, what's unverified |
| `docs/OVERLAY.md` | what the overlay shows where, when it fades or hides, with an example |
| `docs/MEMORY-READER.md` | what the game's memory shows that `Player.log` doesn't, the reader's rules, and the shop padlocks |
| `README.md` | for players only: what changes, how it works, setup, FAQ (shaped after other worlds' READMEs, 2026-10-01) |
| `Archipelago/` (not in git) | an Archipelago 0.6.7 source checkout; `worlds/bazaar` is a junction to `bazaar/` |
| `.venv/` (not in git) | Python 3.13 (Archipelago doesn't support 3.14 yet) |

## Getting set up

```sh
git clone --depth 1 --branch 0.6.7 https://github.com/ArchipelagoMW/Archipelago.git
py -3.13 -m venv .venv   # or: uv venv --python 3.13 .venv
.venv/Scripts/python -m pip install -r Archipelago/requirements.txt pytest pytest-subtests pillow pyflakes
# PowerShell: New-Item -ItemType Junction -Path Archipelago/worlds/bazaar -Target bazaar
```

(Pillow is only for the tools in `tools/`; the client itself must never need it - see below.)

## Everyday commands

```sh
# run all the tests (world generation, log parser, client rules, overlay layout, Item Guide)
cd Archipelago && ../.venv/Scripts/python.exe -m pytest worlds/bazaar

# unused imports / names (keep it clean)
.venv/Scripts/python.exe -m pyflakes bazaar/*.py bazaar/data/__init__.py tools/*.py

# build bazaar.apworld (repo root and releases/) - never use the Launcher's "Build APWorlds", it opens Explorer
.venv/Scripts/python.exe tools/build_apworld.py

# a solo test game with your local build
powershell -ExecutionPolicy Bypass -File tools\quick_run.ps1 -StartingHero vanessa
```


## Rules that keep saves and seeds working

- Bump `world_version` in `bazaar/archipelago.json` for every release, build, commit `releases/bazaar.apworld`,
  push, then publish a GitHub release with the file attached (players download from the latest release):
  `gh release create v<version> bazaar.apworld --target main --title "The Bazaar for Archipelago v<version>" --notes "..."`
- Never renumber item or location ids. Existing `ap_id`s stay and new cards are appended; heroes are
  append-only (their index sets their location ids).
- Retired options become `Removed` options (so old YAMLs get a clear message), never silently deleted.
- **The goal counts only 10-win checks this client sent; the Tracker shows every checked location** (owner,
  2026-10-15). Another player's collect marks your locations checked on the server (`collect_player` in
  MultiServer.py); a seed was won that way. The client stores every id it sends in data storage key
  `bazaar_sent_<team>_<slot>` (one list, follows the player across computers). `sent_by_you()` reads it and feeds
  the goal, the overlay's Goal x/y and `/status`' 10-win column; `done()` (Tracker, menu counts) also includes
  collected checks, as Hollow Knight's client does (it marks them opened in-game, ItemNetworkingModule.cs). The
  goal is also checked when the key arrives on connect; checks sent while offline are stored again on reconnect.
  ⚠️ Official clients differ on showing collected checks (HK, Factorio, SMW, KDL3, DKC3, KH2 show them done; ALttP
  and SM have an `allow_collect` option; OoT ignores them), but none derives its goal from them.
  ⚠️ Wins sent before 2026-10-15 aren't in the key; they count again once replayed.
- The Windows Archipelago installer does **not** include Pillow: client code must never need it (only tools/ may).
  Item Guide pictures are decoded by the SDL2_image Archipelago ships for its GUI, called through ctypes - never by
  importing Kivy, which Archipelago's GUI must set up first (`KIVY_DATA_DIR`, `KIVY_HOME`).
- **Every item has a picture, all in one place: `bazaar/data/card-art.zip`**, shipped inside the apworld (owner
  2026-11-12: "pictures for ALL unlockables"): `<card guid>.webp`, `<merchant/event/level-up step guid>.webp` and
  `item-<item id>.webp` for the items with no card - **and nothing else**: only pictures an item uses ship (owner
  2026-11-12). A test fails the build if any item has none, any picture is unused, or any picture
  is blank (`make_card_art.blank`: one colour over a fifth of it and under 1,000 colours - 12 cards shipped as
  tier-coloured boxes from a broken source until 2026-11-12). Nothing is
  downloaded (owner, 2026-10-02: only what Archipelago strictly needs leaves the network). The images are
  community sourced, with credit to Bazaar DB; `tools/make_card_art.py` turns them into the zip (192 px tall since 2026-11-12,
  twice the Item Guide's, so big pop-up pictures stay sharp - owner: "they look choppy"; about 10 MB). For a new set, replace the zip and bump `ART_SET` in `bazaar/cardart.py` (the cache folder of
  converted pictures). Cards a patch adds can be added to the zip from pictures named after them
  (`make_card_art.py --add <folder>`; 2026-10-07: 19 cards from Tempo's patch notes, supplied by the owner), then
  bump `ART_SET`. The item symbols are drawn by `tools/make_item_symbols.py`. The zip also holds the game's 20
  rarity frames (`frame-<rarity>-<kind>.webp`, 2026-11-13), which the client lays over pop-up and Item Guide pictures; where
  each sits is `cardart.FRAMES`, and the art never shows outside a frame (`test_rarity_frames`).

Happy hacking, and thanks again for pitching in!
