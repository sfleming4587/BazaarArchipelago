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

Useful commands: `/status`, `/locked [hero]`, `/logpath`.

If you close the game mid-run, the client picks the run back up when you resume it.
Start the client before the game if possible, so it sees the start of every run.
