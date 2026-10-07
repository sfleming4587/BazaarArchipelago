# The Bazaar - Archipelago

**The Bazaar** for [Archipelago](https://archipelago.gg), the multiworld randomizer.

**Status:** playable, actively developed - [latest release](https://github.com/sfleming4587/BazaarArchipelago/releases/latest).
Windows only. Needs Archipelago 0.6.4 or newer; last tested with The Bazaar 1.0.12293.

---

## What is Archipelago?

Picture you and a friend each playing a different game. You reach day 5 in The Bazaar, and somewhere else your
friend's grappling hook unlocks. They open a chest in their game, and you suddenly get to play Dooley. Archipelago
shuffles the items of everyone's games together, so you keep finding things for each other until everyone has
reached their goal. You can play solo too.

## What changes in The Bazaar

- **You start with one hero.** The others are out in the multiworld, and you only play the heroes you've received.
- **Most cards start locked.** Each hero keeps a set of Bronze starter cards (20 by default), and the rest of the
  cards merchants sell turn up one by one as items. Until a card is unlocked, you leave it on the shelf.
- **Some merchants and events are locked too** (a quarter by default). Visiting a locked merchant is fine, but what
  you take there counts as locked; stepping into any other locked event costs you that run's checks. Diamond and
  Legendary ones wait for **Event Rarity Progression**.
- **Your progress sends items to others.** Each hero has checks for:
  - reaching each day;
  - winning that day's PvP fight;
  - beating monsters of each rarity;
  - a 10-win run.
- **The goal:** a 10-win run with a set number of different heroes (3 by default).
- **Optional spice:**
  - **Sell Traps:** sell the item it names within a couple of days, or your checks pause.
  - **Lock Bypasses:** keep a locked card for the rest of a run.
  - **DeathLink:** when one player loses, everyone loses.

Your YAML options file explains every setting, and the defaults make a great first game. For the details of
checks, logic and items, see the [game page](bazaar/docs/en_The%20Bazaar.md).

## How it works

The Bazaar is online-only and doesn't allow mods, so **the game itself is never changed**. Instead, **The Bazaar
Client** runs next to it and watches two things:

- **the log file the game already writes on your PC**, which shows runs, days, fights, purchases and sales;
- **the game's memory, read-only**: your own run's screen and the cards on offer, so it can put padlocks on the
  locked ones.

It never writes to the game, never talks to Tempo's servers, and never clicks or types for you. Since the game
can't stop you from buying a locked card, the client keeps things fair: break a rule and it holds back your checks
until you put it right (see [House rules](#house-rules)).

## What you see on screen

Everything sits beside the board, never on it, apart from the padlocks, which you can click straight through. It
only shows while The Bazaar is the active window, and it fades while you read a card's tooltip or drag a card.

- **Padlocks:** a red padlock on every locked card you're offered (in shops, level-ups, loot and events), on every
  locked merchant or event you're offered a choice of, and on
  the locked cards in your open stash.
- **The header (top left):** your hero, day, goal progress and Lock Bypasses, with buttons for the Shop Guide
  and the Tracker.
  It turns red if the client isn't connected to the multiworld.
- **Notices (top right):** **CHECKS ARE BLOCKED** and why, any locked card you're holding (with a **Use Bypass**
  button when you have one), Sell Traps (you'll know them by the flaming skull) and DeathLinks.
- **Pop-ups (bottom right):** everything you receive, send or find, always with the other player's name - and
  pictures of the cards you just unlocked.
- **Shop Guide (left column):** pictures of the cards on offer right now, framed in gold, then everything a
  merchant could stock, with the locked ones crossed out. Open it any time; search it or filter it by size,
  rarity or merchant.
- **The hero panel (main menu):** every hero in your multiworld with their checks and how many of their cards
  you've unlocked; locked heroes have a padlock. It warns you if the hero you picked is locked, or if Random could
  roll one you can't play.
- **Tracker:** every hero's checks at a glance, colour-coded green, yellow, red and grey, PopTracker-style. Hover
  a square to see its checks, or click to keep the list open.

The Tracker and the Shop Guide are normal windows: drag them anywhere, even onto a second monitor.

## Getting set up (Windows)

New to Archipelago? Just follow the steps in order. It takes about ten minutes the first time; after that it's
"open the client, open the game".

### 1. Install The Bazaar
1. Install [The Bazaar](https://store.steampowered.com/app/1617400/The_Bazaar/) on Steam and play until you
   reach the main menu once (that creates the log file the client reads).
2. Keep the game's display mode on **Fullscreen Window** (the default). Exclusive fullscreen would hide the
   client's helpers.

### 2. Install Archipelago
1. Download the Windows installer (`Setup.Archipelago.<version>.exe`) from the
   [Archipelago releases page](https://github.com/ArchipelagoMW/Archipelago/releases) - 0.6.4 or newer.
2. Run it with the default settings. You'll find the **Archipelago Launcher** in your Start menu.

### 3. Add The Bazaar to Archipelago
1. Download [`bazaar.apworld`](https://github.com/sfleming4587/BazaarArchipelago/releases/latest/download/bazaar.apworld)
   from the latest release.
2. Double-click it, or open the Launcher, click **Install APWorld** and pick the file.
3. Reopen the Launcher. **The Bazaar Client** is now in the list.

### 4. Make your options file (YAML)
1. In the Launcher, click **Generate Template Options**. A folder opens with `The Bazaar.yaml` in it.
2. Copy it somewhere handy and open it in Notepad. The essentials:
   - `name:` - your player name, e.g. `name: YourName`.
   - **Included Heroes (Must own):** `include_mak:`, `include_stelle:`, `include_jules:`, `include_karnok:`,
     `include_the_dragons:` - set `true` for each DLC hero you own. Vanessa, Pygmalien and Dooley are in by
     default; set one to `false` (e.g. `include_dooley: false`) to sit them out. Any hero not included isn't in
     your seed.
   - `heroes_required:` - how many heroes need a 10-win run to finish (default 3).

**Want a gentler game?** Turn on `duplicate_all_cards` (**Duplicate All Cards (casual)**). Every locked card gets
a second copy out in the multiworld, so each one turns up sooner.

### 5. Generate the game
Whoever hosts collects everyone's YAML files, and **the host needs `bazaar.apworld` installed too**.
1. Put all the YAML files into `C:\ProgramData\Archipelago\Players` (clear out any example files first).
2. In the Launcher, click **Generate**. The game appears in `C:\ProgramData\Archipelago\output` as
   `AP_<numbers>.zip`.

### 6. Host it
- **On the website:** upload the zip at [archipelago.gg/uploads](https://archipelago.gg/uploads) and create a
  room. The room page shows the address to connect to, like `archipelago.gg:38281`.
- **On your own PC:** click **Host** in the Launcher and pick the zip. Friends connect to your IP address (you may
  need to forward port 38281); you connect to `localhost`.

### 7. Play!
1. Open **The Bazaar Client** from the Launcher.
2. Type the room address at the top, click **Connect** and enter your player name.
3. Start The Bazaar. The hero panel on the main menu shows who you may play. Pick a hero and start a run.
4. Play like you always do. Checks go out on their own as you reach days, win fights and finish runs.

## House rules

The game doesn't know it's in a multiworld, so the client keeps watch. If a rule is broken, it holds back your
checks and the notices box says **CHECKS ARE BLOCKED** and why.

- **Only play heroes you've received.** A run with a locked hero sends nothing.
- **Don't keep locked cards.** If one lands in your hands anyway (a reward, say), just sell it: checks resume the
  moment the game logs the sale. Items the game makes for you by itself (from another item, a Shovel, a
  transformation) are always fine.
- **Sell Traps** (3 by default): sell the item it names before the day shown.
- **Don't step into locked events.** Going into one pauses your checks for the rest of that run. A locked merchant
  is fine to visit, but anything you take there has to be sold. If every event on offer is locked, the client lets
  the least rare one through and tells you which.
- **Lock Bypasses** (5 by default): holding a locked card, or went into a locked event? Press **Use Bypass** next to
  it and it's yours for the rest of that run. A bypass is never used by itself.
- **DeathLink** (off unless you turn it on): the second DeathLink you receive in a run (set by
  `death_links_before_concede` and `death_links_same_run`) means conceding your current run.
  Losing a run sends a DeathLink to everyone else; conceding only does if you turn on `death_link_on_concede`.

PvP wins count automatically - nothing to answer.

## Client commands

| Command | What it does |
|---|---|
| `/status` | your heroes, days done, 10-win runs, goal progress and the current run |
| `/locked [hero]` | cards that are still locked (and where they are, if you have a hint for them) |
| `/where <card>` | where a locked card is - only if you already got a hint for it |
| `/tracker` | open or close the Tracker |
| `/deathlink` | turn DeathLink on or off until you close the client (whatever your YAML says) |
| `/logpath [path]` | show or change where the client looks for The Bazaar's log |
| `/unblock` | emergency only: shows what's blocking checks; `/unblock confirm` clears it if something broke |

## FAQ

**Is this allowed? Can I get banned?**
Tempo's [mod policy](https://www.playthebazaar.com/mod-policy) prohibits mods that:
- change gameplay, game speed or the flow of combat;
- calculate or simulate combat;
- interact with the game without your input;
- talk to the game's server.

The client does none of those: it only reads the game's log and, read-only, a little of its memory. It isn't
affiliated with or reviewed by Tempo, and their policy can change, so check it yourself.

**My checks aren't sending.**
Look at the notices box (top right) for **CHECKS ARE BLOCKED**: a locked hero, a locked card you're holding, a
missed Sell Trap or a DeathLink. `/unblock` shows what's in the way. Also check the header doesn't say you're not
connected.

**The padlocks are missing.**
Playing through the Tempo launcher? It runs the game as administrator, so the client needs to be too: accept
Windows' prompt when the client asks, or start the Archipelago Launcher with "Run as administrator".
Otherwise, give the client a minute or two after starting the game. If the client says the memory reader turned itself off,
restart the game once. If it says so again, a game patch probably changed something, and padlocks stay off until a
newer `bazaar.apworld` supports it. The Shop Guide still crosses out locked cards, and everything else keeps
working.

**The client doesn't react to the game at all.**
Type `/logpath`. It should show `C:\Users\<you>\AppData\LocalLow\Tempo Storm\The Bazaar\Player.log`. If your game
writes its log somewhere else, use `/logpath <full path>`.

**I don't see any of the helpers.**
They only show while The Bazaar is the active window, and the game must be on **Fullscreen Window** or windowed.

**My wifi dropped, or I forgot to start the client.**
Keep playing! When the client reconnects it reads the game's log and sends everything you earned in the meantime,
usual rules included. It can look back as far as your previous game session.

**I closed the game mid-run.**
Just carry on; the client picks the run right back up.

**The client says The Bazaar was updated.**
No problem - everything keeps working. Cards or heroes a patch adds just aren't part of your seed.

## Updating

Download the newest `bazaar.apworld` from the [latest release](https://github.com/sfleming4587/BazaarArchipelago/releases/latest)
and install it as in step 3. Finish your current seed first: a seed generated with an older version may not work
with a newer client.

## Found a bug?

Open an [issue](https://github.com/sfleming4587/BazaarArchipelago/issues) and attach the client's log from
`C:\ProgramData\Archipelago\logs` (the newest `BazaarClient_...txt`).

## Credits

Card pictures are courtesy of [Bazaar DB](https://bazaardb.gg) - thank you! The card art and hero pictures belong
to The Bazaar. The Bazaar is made by Tempo; this project isn't affiliated with or endorsed by them. Thanks for
playing, and good luck at the Bazaar!

*Want to help build it? See [DEVELOPERS.md](DEVELOPERS.md).*
