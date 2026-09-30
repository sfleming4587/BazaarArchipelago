# The Bazaar - Archipelago

Welcome to the Bazaar, traveler! This brings **The Bazaar** into [Archipelago](https://archipelago.gg), the
multiworld randomizer where your games and your friends' games are shuffled together.

You start with a single hero. Every other hero, and most of the cards merchants would sell you, are locked away
and scattered across the multiworld. Reach new days, win your PvP fights, beat monsters and go for those 10-win
runs, and each of those sends something to another player - maybe their hookshot, maybe their next area. In
return, their games unlock your heroes and cards, one find at a time. Get 10 wins with enough different heroes (3
by default) and you've won!

**Your game stays untouched.** A small companion program sits next to The Bazaar and simply reads the log file the
game already writes on your PC. It never changes game files, never reads the game's memory, never talks to Tempo's
servers and never clicks or types for you.

*Want to work on it? Head over to [DEVELOPERS.md](DEVELOPERS.md).*

---

## Getting set up (Windows)

It takes about ten minutes the first time. After that it's just "open the client, open the game".

### 1. Install The Bazaar
1. Install [Steam](https://store.steampowered.com/about/) and sign in.
2. Install [The Bazaar](https://store.steampowered.com/app/1617400/The_Bazaar/) and play until you reach the main
   menu once (that creates the log file the client reads).
3. Keep the game's display mode on **Fullscreen Window** (the default). The Archipelago helpers are their own
   windows on top of the game, and exclusive fullscreen would hide them.

### 2. Install Archipelago
1. Grab the Windows installer (`Setup.Archipelago.<version>.exe`) of the newest release from the
   [Archipelago releases page](https://github.com/ArchipelagoMW/Archipelago/releases) - 0.6.4 or newer.
2. Run it with the default settings. It installs to `C:\ProgramData\Archipelago` and puts the
   **Archipelago Launcher** in your Start menu. That's all you need - no Python or anything else.

### 3. Add The Bazaar to Archipelago
1. Download `bazaar.apworld` from the [latest release](https://github.com/sfleming4587/BazaarArchipelago/releases/latest)
   ([direct download](https://github.com/sfleming4587/BazaarArchipelago/releases/latest/download/bazaar.apworld)).
2. Double-click it, **or** open the Archipelago Launcher, click **Install APWorld** and pick the file.
3. Close and reopen the Launcher. **The Bazaar Client** should now be in the list. You're all set!

### 4. Make your options file (YAML)
1. In the Launcher, click **Generate Template Options**. A folder opens with `The Bazaar.yaml` in it.
2. Copy it somewhere handy and open it in Notepad. The essentials:
   - `name:` - your player name, e.g. `name: YourName` (no spaces is easiest)
   - `own_mak:`, `own_stelle:`, `own_jules:`, `own_karnok:`, `own_the_dragons:` - `true` for each DLC hero you
     own (Vanessa, Pygmalien and Dooley are always in)
   - `exclude_<hero>:` (e.g. `exclude_dooley: true`) - optional, to sit a hero out even though you own them
   - `heroes_required:` - how many heroes need a 10-win run to finish (default 3)
3. Everything else is explained right there in the file, and the defaults make a great first game.

**Want a gentler game?** Turn on `duplicate_all_cards` (shown as **Duplicate All Cards (casual)**). You get the
same number of checks, but about half as many locked cards: every locked card has two copies out in the
multiworld, so each one turns up sooner and there's less to steer around in the shops.

### 5. Generate the game
Whoever hosts collects everyone's YAML files. **The host needs `bazaar.apworld` installed too.**
1. Put all the YAML files into `C:\ProgramData\Archipelago\Players` (clear out any example files first).
2. In the Launcher, click **Generate**. When it's done, your game is waiting in
   `C:\ProgramData\Archipelago\output` as `AP_<numbers>.zip`.

### 6. Host it
Pick whichever suits you:
- **On the website:** upload the `AP_….zip` at [archipelago.gg/uploads](https://archipelago.gg/uploads) and create
  a room. The room page shows the address to connect to, like `archipelago.gg:38281`. If the site won't take the
  file, use the other option.
- **On your own PC:** click **Host** in the Launcher and pick the `AP_….zip`. Friends connect to your IP address
  (you may need to forward port 38281 on your router); you connect to `localhost`.

### 7. Play!
1. Open **The Bazaar Client** from the Launcher.
2. Type the room address at the top (e.g. `archipelago.gg:38281`), click **Connect** and enter your player name.
3. Start The Bazaar. On the hero-select screen, the box in the top-left corner shows which heroes you may play,
   with how many of their checks are done and how many are in logic. Pick one and start a run.
4. Play like you always do. Checks go out on their own as you reach days, win fights and finish runs.

---

## House rules

The Bazaar doesn't know it's in a multiworld, so the client keeps things fair: if a rule is broken, it holds back
your checks and the top-left box turns red and tells you **CHECKS ARE BLOCKED** and why.

- **Only play heroes you've received.** A run with a locked hero sends nothing.
- **Don't keep locked cards.** When you visit a merchant, the client lists the locked cards it could sell, so you
  know what to leave on the shelf. If a locked card lands in your hands anyway (a reward, say), just sell it -
  checks resume the moment the game's log shows the sale. Items the game makes for you by itself (from another
  item, a Shovel, a transformation) are always fine.
- **DeathLink** (off unless you turn it on): when someone else dies, abandon your current run (Settings > Abandon
  Run); nothing more counts in that run. Losing a run sends a DeathLink to everyone else, and conceding does too
  only if you turn on `death_link_on_concede`.
- **Sell Traps** (off unless you turn them on): sell the item it names before the day shown, or checks pause until
  you do.
- **Lock Bypasses** (off unless you turn them on): the next locked card you get is yours for the rest of that run,
  upgrades included - or press **Lock Bypass** during a run and pick the card yourself.
- PvP wins count automatically - nothing to answer.

## Your helpers on screen

- **The top-left box:** your hero, day and goal during a run; on the hero-select screen, the heroes you may play.
  It turns red when checks are blocked or a DeathLink arrives, amber when something needs you. Its **Tracker**
  button opens the tracker, and **Lock Bypass** (while you have one ready) lets you pick the card it goes to.
- **Locked-card list:** right under that box whenever you're at a merchant or an item choice - the locked cards on
  offer, so you know what not to take. **Hide list** tucks it away.
- **Pop-ups (bottom right):** everything you receive, send or find, always with the other player's name; Sell
  Traps; **SELL IT NOW** if you pick up a locked card; **CHECK NOT SENT** the moment a check is blocked.
- **Shop Guide:** a window with pictures of everything the merchant could stock, at their real in-game sizes,
  with the locked ones greyed out and crossed. Great for learning what the locked cards look like! Cards newer than
  our picture source (all of Karnok and The Dragons, for now) show a "no picture" box with their name.
- **Tracker:** a card for every hero, PopTracker-style, with four squares - reach day N, PvP win on day N, monster
  checks, and 10 wins. Green = in logic, yellow = out of logic, red = hero still locked, grey = all done. Hover a
  square to see its checks, click to keep the list open.

All of it stays beside the board (never on it), only shows while The Bazaar is the active window, never steals the
keyboard from the game, and always fits fully on your screen, whatever your resolution. The tracker and the Shop
Guide are normal windows - drag them anywhere, even onto a second monitor. The Archipelago client window itself
stays tidy: it only shows your item history and replies to your commands.

## Client commands

| Command | What it does |
|---|---|
| `/status` | your heroes, days done, 10-win runs, goal progress and the current run |
| `/locked [hero]` | cards that are still locked (and where they are, if you have a hint for them) |
| `/where <card>` | where a locked card is - only if you already got a hint for it through Archipelago |
| `/tracker` | open or close the tracker (same as the **Tracker** button) |
| `/logpath [path]` | show or change where the client looks for The Bazaar's log |
| `/unblock` | emergency only: shows what's blocking checks; `/unblock confirm` clears it if something broke |

## Troubleshooting

- **The client doesn't react to the game.** Type `/logpath`. It should show
  `C:\Users\<you>\AppData\LocalLow\Tempo Storm\The Bazaar\Player.log`. If your game writes its log somewhere else,
  point the client there with `/logpath <full path>`.
- **I don't see the helpers.** They only show while The Bazaar is the active window, and the game needs to be on
  **Fullscreen Window** or windowed. If the client says the alert window can't open on this PC, the warnings show
  up in the client window instead.
- **The client says The Bazaar was updated.** No problem - everything keeps working. Anything a patch adds just
  isn't part of your seed.
- **A check didn't count.** Look for the red **CHECKS ARE BLOCKED** box and the **CHECK NOT SENT** pop-ups (locked
  hero, locked card, DeathLink, Sell Trap), or type `/unblock` to see what's in the way.
- **I closed the game mid-run.** Just carry on with the run; the client picks it right back up.
- **My wifi dropped, or I forgot to start the client.** Keep playing! When the client reconnects it reads the
  game's log and sends everything you earned in the meantime, usual rules included - even for runs that already
  ended (those don't send a DeathLink hours later). It can look back as far as the previous game session; runs
  from before your seed's first connection don't count.

## Updating
Download `bazaar.apworld` from the [latest release](https://github.com/sfleming4587/BazaarArchipelago/releases/latest)
and install it the same way as in step 3. Games already in progress keep working with the version they were
generated with.

## Credits
Card pictures come from [howbazaar.gg](https://www.howbazaar.gg) (it stopped updating at game v6.0.0); the
tracker's hero pictures are from The Bazaar. The Bazaar is made by Tempo; this project isn't affiliated with or
endorsed by them. Thanks for playing, and good luck at the Bazaar!
