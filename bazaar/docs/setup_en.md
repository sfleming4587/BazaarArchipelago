# The Bazaar Setup Guide

## Required Software

- [The Bazaar](https://store.steampowered.com/app/1617400/The_Bazaar/) on Steam
- [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases) 0.6.4 or newer
- `bazaar.apworld` from the [latest release](https://github.com/sfleming4587/BazaarArchipelago/releases/latest)

## Optional Software

- [Universal Tracker](https://github.com/FarisTheAncient/Archipelago/releases) works with this world too, if you
  like it better than the built-in tracker.

## Installation

1. Double-click `bazaar.apworld`, or open the Archipelago Launcher and pick **Install APWorld**.
2. Restart the Launcher. **The Bazaar Client** now shows up in its list.

That's it! Nothing gets installed into The Bazaar itself - the client only reads the log file the game already
writes.

In the game's settings, keep the display mode on **Fullscreen Window** (the default). The client's helpers are
their own windows on top of the game, and exclusive fullscreen would hide them.

## Configuring your YAML file

### What is a YAML and why do I need one?
Your YAML file holds your options for the game. See the
[basic multiworld setup guide](/tutorial/Archipelago/setup/en) to learn more.

### Where do I get a YAML?
Open the Launcher, click **Generate Template Options**, and edit `The Bazaar.yaml`. Switch on each DLC hero you
own (in the Options Creator or on a player options page they're simple on/off switches):

```yaml
The Bazaar:
  own_mak: true
  own_karnok: true
  heroes_required: 3
```

On a player options page you can also start from a preset: **Casual**, **Standard** or **Hardcore**.

Looking for a relaxed game? **Duplicate All Cards (casual)** keeps the same number of checks but gives every locked
card a second copy in the multiworld, so there are about half as many locked cards and each one turns up sooner.

## Joining a game

1. Open **The Bazaar Client** from the Launcher and connect to the room.
2. Start The Bazaar - the order doesn't matter. The client finds `Player.log` on its own; if yours lives somewhere
   else, use `/logpath <path>` or set `bazaar_options.log_path` in `host.yaml`.
3. Pick a hero you've received and play! Checks are sent as you reach new days, win PvP fights, beat monsters and
   finish 10-win runs.

Handy commands: `/tracker` (opens the tracker), `/status`, `/locked [hero]` (with hints: where each locked card
is), `/where <card>` (your hint for a locked card, if you already have one), `/logpath`, and `/unblock` (emergency
only: shows what's blocking checks; `/unblock confirm` clears it if something broke).

## Your helpers while you play

The Archipelago client window keeps to your item history (what your checks found, sent and received) and replies
to your commands. Everything about your run shows up in small helper windows around the board instead (and in the
client's log file). If those can't open on your PC, the messages show in the client window as a fallback.

### The alert window (top left)

- **Shopping:** when you open a merchant, it lists the locked cards that merchant could sell, grouped by first
  letter, so you know what to leave on the shelf - or shows a green tick when nothing there is locked. Clicks go
  straight through the list to the game, so it never gets in your way. **Hide list** / **Show list** tucks it away.
- **Item choices:** whenever an event, an event option (like Hidden Lake's "Fight the Beast") or a level-up lays
  items out for you to take, it lists the locked cards it could offer - or, if it could be almost anything (Make a
  Wish), says so. Items handed to you with no choice get no warning; if one of those is locked, just sell it.
- **CHECKS ARE BLOCKED:** shown while you hold a locked card, play a locked hero or owe a DeathLink. It clears by
  itself once you sell the card; a locked hero or a DeathLink blocks the rest of that run.
- **DeathLink:** time to abandon your run.
- **Status line:** during a run, your hero, day and goal progress. On the hero-select screen, in bigger text,
  every hero you may play with their checks done / checks in logic, and a warning if the hero you picked is locked.

The colour tells you how urgent it is: **red** = checks are blocked or a DeathLink arrived, **amber** = something to
act on (locked cards for sale, a Sell Trap, a locked hero picked), **dark** = just so you know, **green** = all good.

### Pop-ups (bottom right)

Short pop-ups that always name the other player: an unlock you receive (**UNLOCKED ... from**), an item one of your
checks sends (**SENT ... to**), filler someone found for you (**RECEIVED ... from**) or you found yourself
(**FOUND**), a Sell Trap and who sent it, **SELL IT NOW** if you buy or get a locked card, and a note when the game
was updated since the apworld was made. A red **CHECK NOT SENT** pop-up names any check the moment it's blocked.

### Shop Guide

A second window with pictures (from [howbazaar.gg](https://www.howbazaar.gg)) of everything the merchant you're
visiting could stock, each at its in-game size (small = 1 slot wide, medium = 2, large = 3), with the locked ones
greyed out behind a red X. The shorter list goes on top.

- It opens in the strip right of the board, and the locked-card list stays on the left. If that list doesn't fit,
  it says how many more are in the Shop Guide.
- It's a real window: drag it anywhere, even onto another monitor, and it stays put.
- **Locked only** shows just the cards you may not buy - a great way to learn what they look like. **Show all**
  brings the rest back.
- After you leave a shop, it keeps showing the last one.
- Closing it with **X** keeps it closed (next time too) and gives a long list the right strip, until you press
  **Pictures** in the alert window while at a merchant.
- Pictures download once in the background when the client starts. Until a card's picture is in - and for cards
  newer than howbazaar.gg, which stopped updating at game v6.0.0 (so all of Karnok and The Dragons) - you'll see a
  "no picture" box of the card's size with its name under it.

Start the client with `--no-shop-guide` to turn it off completely.

### Tracker

Press **Tracker** in the alert window or type `/tracker`. You get a card for every hero, each with four squares:
**1** reach day N, **2** PvP win on day N, **3** monster checks, **4** 10 wins.

- **Green:** something in it is in logic.
- **Yellow:** what's left is out of logic - doable, but logic expects more of that hero's cards first.
- **Red:** the hero is still locked.
- **Grey:** all done!

Hover a square to see its checks (square 3 shows a row per day, Bronze to Legendary); click to keep the list open,
click again to close it. Heroes that aren't in your seed are dimmed. It's a normal window, so a second monitor works
great.

### Where the helpers sit

The helpers live in the strips left and right of the board - never over the board and never over each other. They
only show while The Bazaar is the active window, never take the keyboard from the game, and stay see-through enough
to read item tooltips behind them. They follow the game window, so they fit any resolution (1080p, 1440p, 4K,
ultrawide), fullscreen window or windowed, on any monitor, and always stay fully on screen. Start the client with
`--no-overlay` to turn them off.

## Good to know

- Closed the game mid-run? Just resume the run - the client picks it right back up.
- Wifi dropped, or the client wasn't running? Keep playing. When the client reconnects it sends everything you
  earned in the meantime, even for runs that already ended (those don't send a late DeathLink). It can read back as
  far as the previous game session.
