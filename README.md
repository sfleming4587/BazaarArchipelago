# The Bazaar - Archipelago

Play **The Bazaar** as part of an [Archipelago](https://archipelago.gg) multiworld randomizer. You start with one
hero; the other heroes and most cards are locked and shuffled into the multiworld. Reaching days, winning PvP
fights, beating monsters and getting 10-win runs sends items to the other players. The goal is 10 wins with a
number of different heroes (3 by default).

**It doesn't mod the game.** A small program next to the game reads the log file The Bazaar writes on your PC.
It never changes game files, never reads the game's memory, never talks to Tempo's servers and never clicks or
types for you.

*Developers: see [DEVELOPERS.md](DEVELOPERS.md).*

---

## Setting it up on a new PC (Windows)

### 1. Install The Bazaar
1. Install [Steam](https://store.steampowered.com/about/) and sign in.
2. Install [The Bazaar](https://store.steampowered.com/app/1617400/The_Bazaar/) and play until you reach the main
   menu once (this creates the game's log file).
3. In the game's settings, keep the display mode on **Fullscreen Window** (the default). The Archipelago alerts
   are a separate window on top of the game; they can't show over exclusive fullscreen.

### 2. Install Archipelago
1. Go to the [Archipelago releases page](https://github.com/ArchipelagoMW/Archipelago/releases) and download the
   Windows installer (`Setup.Archipelago.<version>.exe`) of the newest release (0.6.4 or newer).
2. Run it and keep the defaults. It installs to `C:\ProgramData\Archipelago` and adds the
   **Archipelago Launcher** to the Start menu. Nothing else (like Python) is needed.

### 3. Add The Bazaar to Archipelago
1. Download [`releases/bazaar.apworld`](releases/bazaar.apworld) from this repository (open it, then **Download
   raw file**).
2. Double-click the downloaded `bazaar.apworld`, **or** open the Archipelago Launcher and click
   **Install APWorld** and pick the file.
3. Close and reopen the Launcher. You should now see **The Bazaar Client** in its list.

### 4. Make your options file (YAML)
1. In the Launcher, click **Generate Template Options**. A folder opens; find `The Bazaar.yaml` in it.
2. Copy it somewhere and open it with Notepad. At minimum set:
   - `name:` - your player name (no spaces is easiest), e.g. `name: YourName`
   - `owned_dlc_heroes:` - the DLC heroes you own, e.g. `["Mak", "Stelle", "Jules", "Karnok", "The Dragons"]`
     (Vanessa, Pygmalien and Dooley are always included)
   - `heroes_required:` - how many heroes need a 10-win run to finish (default 3)
3. Every other option has a description in the file; the defaults are a good start.

### 5. Generate the game
Whoever hosts collects everyone's YAML files. **The host must also have `bazaar.apworld` installed.**
1. Put all the YAML files into `C:\ProgramData\Archipelago\Players` (remove any example files there).
2. In the Launcher, click **Generate**. When it finishes, the game is in `C:\ProgramData\Archipelago\output` as
   `AP_<numbers>.zip`.

### 6. Host the game
Pick one:
- **On the website:** go to [archipelago.gg/uploads](https://archipelago.gg/uploads), upload the `AP_….zip` and
  create a room. The room page shows the address to connect to, like `archipelago.gg:38281`. If the site won't
  take the file, use the other option.
- **On your own PC:** in the Launcher click **Host** and pick the `AP_….zip`. Friends connect to your IP address
  (you may need to forward port 38281 on your router); you connect to `localhost`.

### 7. Play
1. In the Launcher, open **The Bazaar Client**.
2. At the top, type the room address (e.g. `archipelago.gg:38281`) and click **Connect**, then enter your player
   name.
3. Start The Bazaar and start a run with a hero you've unlocked (type `/status` in the client to see which).
4. Play normally. Checks are sent automatically as you reach days, win fights and win runs.

---

## Rules while you play

The client enforces these by blocking checks - a banner at the top of the screen says **CHECKS ARE BLOCKED** and
why:

- **Only play heroes you've received.** A run with a locked hero sends nothing.
- **Don't keep locked cards.** When you open a merchant, a warning lists the locked cards it could sell, so you
  know what not to buy. If you end up with a locked card anyway (a reward), sell it: checks are blocked until the
  game's log shows you sold it. Items the game creates for you by itself (from another item, a Shovel, a
  transformation) are always allowed.
- **DeathLink** (if on): when someone else dies, abandon your current run (Settings > Abandon Run). No checks
  count for the rest of that run. Losing a run, or conceding one, sends a DeathLink to everyone else.
- **Sell Traps** (if on): sell the named item before the day shown, or checks are blocked until you do.
- After each PvP fight the client asks **Did you win?** - answer honestly; the game's log doesn't say.

## Client commands

| Command | What it does |
|---|---|
| `/status` | your heroes, days done, 10-win runs, goal progress and the current run |
| `/locked [hero]` | cards that are still locked (and where they are, if you have a hint for them) |
| `/where <card>` | where a locked card is - only if you already got a hint for it through Archipelago |
| `/pvpwin <day>` | answer the client's "did you win?" question for that day |
| `/logpath [path]` | show or change where the client looks for The Bazaar's log |
| `/unblock` | emergency only: shows what's blocking checks; `/unblock confirm` clears it if something broke |

## Troubleshooting

- **The client doesn't react to the game.** Type `/logpath`. It should show
  `C:\Users\<you>\AppData\LocalLow\Tempo Storm\The Bazaar\Player.log`. If your game writes its log elsewhere, set
  it with `/logpath <full path>`.
- **I don't see the alert window.** Check the game is on **Fullscreen Window** or windowed. If the client says
  the alert window can't open on this PC, warnings still appear in the client window.
- **The client says The Bazaar was updated.** That's fine - everything keeps working. Cards, heroes or monsters
  added by the patch just aren't part of your seed until a newer `bazaar.apworld` is released.
- **A run didn't count.** Check the client for a "CHECKS ARE BLOCKED" message (locked hero, locked card, DeathLink).
- **Closed the game mid-run?** Just continue the run; the client picks it back up.

## Updating
Download the newest [`releases/bazaar.apworld`](releases/bazaar.apworld) and install it the same way (step 3).
Games that are already running keep working with the version they were generated with.

## Credits
Card pictures (when available) come from [howbazaar.gg](https://www.howbazaar.gg). The Bazaar is made by Tempo; this
project isn't affiliated with or endorsed by them.
