# The Bazaar Setup Guide

## Required software

- [The Bazaar](https://store.steampowered.com/app/1617400/The_Bazaar/) on Steam
- [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases) 0.6.4 or newer
- `bazaar.apworld`

## Installation

1. Double-click `bazaar.apworld`, or open the Archipelago Launcher and pick **Install APWorld**.
2. Restart the Launcher.

Nothing is installed into The Bazaar itself.

## Creating your options file

On the website's options page you can start from a preset: **Casual**, **Standard** or **Hardcore**.

### Tracking

[Universal Tracker](https://github.com/FarisTheAncient/Archipelago/releases) works with this world: it shows which
checks are in logic for your seed.


Open the Launcher, click **Generate Template Options**, and edit `The Bazaar.yaml`.
List the DLC heroes you own under `owned_dlc_heroes`, for example:

```yaml
The Bazaar:
  owned_dlc_heroes: ["Mak", "Stelle", "Jules", "Karnok", "The Dragons"]
  heroes_required: 3
```

## Playing

1. Open **The Bazaar Client** from the Launcher and connect to the room.
2. Start The Bazaar. The order doesn't matter. The client finds `Player.log` on its own. If yours lives somewhere
   else, use `/logpath <path>` or set `bazaar_options.log_path` in `host.yaml`.
3. Play. Checks are sent as you reach new days and win runs.

Useful commands: `/status`, `/locked [hero]` (with hints: where each locked card is), `/where <card>` (shows your hint for
a locked card; only hints you already got through Archipelago), `/pvpwin <day>` (answers an open PvP question), `/logpath`,
`/unblock` (emergency only: shows what's blocking checks; `/unblock confirm` clears it if something broke).

### The alert window

Alerts appear in a small window at the top of your screen, above the game:

- **Shopping:** when you open a merchant it lists the locked cards that merchant could sell, grouped by first
  letter, so you know what not to buy (or tells you nothing there is locked).
- **Item choices:** when an event or level-up deals several items and you pick one (e.g. "Shiny!"), it lists the
  locked cards it could offer. Random rewards you can't choose (Make a Wish, single-item events) get no warning;
  if one hands you a locked card, sell it like any other.
- **CHECKS ARE BLOCKED:** shown while you hold a locked card, play a locked hero or owe a DeathLink. It clears
  by itself when you sell the card; a locked hero or DeathLink blocks the rest of the run.
- **PvP result:** after each PvP fight, press **Won** or **Lost**.
- **DeathLink:** abandon your run.
- **Unlocks and notices:** short pop-ups when you receive an unlock (and from whom), a Sell Trap arrives, or
  the game was updated since the apworld was made.

The overlay sits in the strips left and right of the board, never over the board itself or over another overlay
window: alerts at the top left, a shop's locked cards under them. It's a separate window, not part of the game,
so it only shows over The Bazaar when the game's display mode is **Fullscreen Window** (the default) or windowed.
Start the client with `--no-overlay` to turn it off.

**Shop Guide** (only when Archipelago runs from source - the Windows installer leaves out the image library the
pictures need, so there the shop warning above is what you get): a second window with card pictures (from [howbazaar.gg](https://www.howbazaar.gg)) of everything
the merchant you're visiting could stock, locked ones greyed out with a red X (the shorter list goes on top). It sits in
the strip right of the board (the locked-card list then stays on the left; if it doesn't fit, it says how many
more are in the Shop Guide). After you leave a shop it keeps showing the last one. Closing it with **X** keeps it
closed (also next time) and lets a long list use the right strip, until you press **Show pictures** next to the
shop warning. All card pictures are downloaded once in the background when the client starts.
Start the client with `--no-shop-guide` to turn it off completely.

If you close the game mid-run, the client picks the run back up when you resume it.
Start the client before the game if possible, so it sees the start of every run.
