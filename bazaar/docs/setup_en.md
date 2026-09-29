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
Switch on each DLC hero you own (in the Options Creator or on the website they're simple on/off switches):

```yaml
The Bazaar:
  own_mak: true
  own_karnok: true
  heroes_required: 3
```

## Playing

1. Open **The Bazaar Client** from the Launcher and connect to the room.
2. Start The Bazaar. The order doesn't matter. The client finds `Player.log` on its own. If yours lives somewhere
   else, use `/logpath <path>` or set `bazaar_options.log_path` in `host.yaml`.
3. Play. Checks are sent as you reach new days and win runs.

Useful commands: `/tracker` (opens the tracker, see below), `/status`, `/locked [hero]` (with hints: where each locked card is), `/where <card>` (shows your hint for
a locked card; only hints you already got through Archipelago), `/logpath`,
`/unblock` (emergency only: shows what's blocking checks; `/unblock confirm` clears it if something broke).

### The alert window

The Archipelago client window keeps to item history (what your checks found, sent and received) and the replies
to your commands; everything about your run shows in the overlay instead (and goes to the client's log file). If
the overlay can't open, those messages show in the client window as before.

Alerts appear in a small window at the top left of your screen, above the game:

- **Shopping:** when you open a merchant it lists the locked cards that merchant could sell, grouped by first
  letter, so you know what not to buy (or shows a green tick when nothing there is locked). Clicks go straight
  through this list to the game, so it never gets in your way; its text is solid and only its background is
  see-through. **Hide list** / **Show list** in the alert window hides it until you show it again.
- **Item choices:** whenever an event, an event option (e.g. Hidden Lake's "Fight the Beast") or a level-up lays
  items out for you to take, it lists the locked cards it could offer - or, when it could be almost any item
  (Make a Wish), says so. Items handed to you with no choice get no warning; if one is locked, sell it.
- **CHECKS ARE BLOCKED:** shown while you hold a locked card, play a locked hero or owe a DeathLink. It clears
  by itself when you sell the card; a locked hero or DeathLink blocks the rest of the run.
- **DeathLink:** abandon your run.
- **Unlocks and notices:** short pop-ups in the bottom right, always naming the other player: an unlock you
  receive (**UNLOCKED ... from**), an item one of your checks sends (**SENT ... to**), filler someone found for you
  (**RECEIVED ... from**) or you found yourself (**FOUND**), a Sell Trap (**from** whom), you buy or get a
  locked card (**SELL IT NOW**), a Sell
  Trap arrives, or the game was updated since the apworld was made. A red **CHECK NOT SENT** pop-up names any
  check the moment it is blocked.
- **Status line:** during a run, your hero, day and goal progress (what's left to check: use a tracker). On the
  hero-select screen, in bigger text: every hero you may play with its checks done / checks in logic, and a warning
  if the hero you picked is locked.

The overlay sits in the strips left and right of the board, never over the board itself or over another overlay
window: alerts at the top left, a shop's locked cards under them, pop-ups at the bottom right. Its colour tells you
how urgent it is: red = checks are blocked or a DeathLink, amber = something to act on (locked cards on sale, a
PvP question, a Sell Trap, a locked hero picked), dark = just information, green = all good. It's see-through, so
item tooltips behind it stay readable, it only shows while The Bazaar is the active window, and it never takes
the keyboard focus from the game. It follows the game window, so it fits any resolution (1080p, 1440p, 4K,
ultrawide), fullscreen or windowed, on any monitor. It's a separate window, not part of the game,
so it only shows over The Bazaar when the game's display mode is **Fullscreen Window** (the default) or windowed.
Start the client with `--no-overlay` to turn it off.

**Shop Guide** (only when Archipelago runs from source - the Windows installer leaves out the image library the
pictures need, so there the shop warning above is what you get): a second window with card pictures (from [howbazaar.gg](https://www.howbazaar.gg)) of everything
the merchant you're visiting could stock, each at its in-game size (small = 1 slot wide, medium = 2, large = 3),
locked ones greyed out with a red X (the shorter list goes on top). It opens in
the strip right of the board (the locked-card list then stays on the left; if it doesn't fit, it says how many
more are in the Shop Guide). It's a real window: drag it anywhere, another monitor too, and it stays there. **Locked only** (top of the guide) shows just the cards you
may not buy, so you learn their pictures; **Show all** brings the rest back. After you leave a shop it keeps
showing the last one. Closing it with **X** keeps it
closed (also next time) and lets a long list use the right strip, until you press **Pictures** in the alert
window while at a merchant. All card pictures are downloaded once in the background when the client starts.
Start the client with `--no-shop-guide` to turn it off completely.

**Tracker:** press **Tracker** in the alert window (top left) or type `/tracker`. A window with a card for every
hero opens; each card has four squares - **1** reach day N, **2** PvP win on day N, **3** monster checks, **4** 10
wins. A square is green when something in it is in logic, yellow when what's left is out of logic (doable, but
logic expects more of that hero's cards first), red when the hero is still locked, grey when it's all done. Hover a
square to see its checks (square 3 shows a row per day with Bronze to Legendary); click it to keep the list open,
click again to close. Heroes not in your seed are dimmed. It's a normal window you can put on another monitor.

Every overlay window stays fully on a monitor, whatever the game's resolution or window size.

If you close the game mid-run, the client picks the run back up when you resume it. If the client was closed or
lost its connection while you played, it sends what you earned meanwhile when it reconnects (runs that ended
meanwhile count, but send no DeathLink). It reads back as far as the previous game session only.
Start the client before the game if possible, so it sees the start of every run.
