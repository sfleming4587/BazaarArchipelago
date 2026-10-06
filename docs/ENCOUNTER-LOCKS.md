# Merchant and event locks

Merchants and events (the cards on the hourly choice screen) can be locked like cards, and Diamond/Legendary ones
sit behind a progressive item. Designed with the owner 2026-10-01 and 2026-10-02.

> ⚠️ **Status 2026-10-02:** world side, client enforcement and event padlocks built and unit-tested. In game
> (owner, 2026-10-02): shop padlocks "look good"; event padlocks seen, hover rule changed (below).

## The owner's rulings

- **Merchants and events both lock** (2026-10-01: "merchants AND events, but we will have to come up with caveats").
- **A locked merchant can be visited; what you buy there counts as a locked card** (2026-10-01: "B for merchants";
  2026-10-02: "it only blocks checks if you buy anything in their shop"). Events that hand you items count as
  merchants: only the items you take are locked.
- **Going into any other locked event blocks checks for the rest of the run, unless a Lock Bypass is used on it**
  (2026-10-01: "block checks for the rest of the run unless a lock bypass is used"). Like cards, a bypass is only
  ever spent by pressing Use Bypass, never automatically.
- **If every event offered is locked, the least rare one is let through; a tie is broken at random with a message
  at the top** (2026-10-01). The random pick must be the same on every reading and reconnect. It does **not** apply
  when an allowed non-event option is on screen, such as the Mysterious Portal's item bubble (2026-10-02).
- **Only choices count:** events the game forces on you never do (2026-10-01). Level-up rewards are never locked
  (2026-10-02: "Level ups not included"). Monster fights are not part of this (2026-10-02: "this does NOT include
  fights with monsters").
- **Event Rarity Progression:** until the first copy, Diamond merchants/events are locked; the second unlocks
  Legendary (2026-10-02). Default 3 copies; a copy past the two stages counts as a Lock Bypass (2026-10-02: "if
  there is an extra, turn it to a buff like the lock bypass").
- **Exempt Expeditions, on by default:** expeditions are never rarity-locked (2026-10-02), and that covers the
  whole expedition, follow-up events included (2026-10-02). The ticket cards still need the Expedition Tickets
  unlock, and stay out of the Legendary Items group (they aren't shop cards).
- **`locked_encounters_percent` default 25, `starter_merchants` default 5** (2026-10-02).

## How the world builds it

- **One lock item per merchant/event name**, covering every template of it: Sharpening Kit has a template per
  rarity, Aila has eight. `tools/extract_data.py` groups templates by display name once and stores the guid lists
  in `encounters`; everything after that works on guids. Item names: `Merchant: <name>` or `Event: <name>`; ids
  `BASE + ap_id`, ap_ids from 5000, kept by name and never reused. Event Rarity Progression is `BASE + 310`.
- **Lockable = every `EventEncounter` that isn't a level-up reward, part of an expedition, or `SpawningEligibility
  Never`** (183 names on 1.0.12293, 51 of them merchants). Level-up rewards come from the `level_ups` table;
  expedition events carry the game's own `[... Expedition]` InternalName prefix.
- **Which of those a seed can lock:** the ones whose templates list a seed hero or Common. `starter_merchants` of
  the merchants among them, each with at least one version below Diamond, never get a lock item. Of the rest,
  `locked_encounters_percent` are locked.
- **Pool order:** hero unlocks, packs, Legendary Items / Expedition Tickets, Event Rarity Progression, Sell Traps,
  Lock Bypasses, merchant/event locks, then card locks from what's left. A default seed (228 slots) gets 39
  merchant/event locks and 137 card/pack locks, against 171 card/pack locks with merchant/event locks off.
- **No logic for merchant/event locks:** they are `useful`. A choice screen always has a way on (the least-rare
  rule), so no check ever needs one.
- **Event Rarity Progression IS in logic (user, 2026-10-06):** PvP wins from day 8 need copy 1, from day 14 copy 2
  (`locations.EVENT_RARITY_PVP_DAYS`, user: "Legendary events are so stupidly rare though ... it should be later
  like 14+"). Why: as `useful`, other games told the finder "This item does not seem important". Every copy is
  progression when any check needs it, since whichever copy arrives first is the one that unlocks.
  ⚠️ With `pvp_win_checks` off or `max_day` under 8 nothing needs it and it stays `useful`.
- **slot_data:** `encounter_locks` (item ids), `event_rarity` (copies placed), `exempt_expeditions`.

⚠️ **The hourly event pool isn't in the local game data.** The server decides it, so "lockable" is a superset:
some locked names may never be offered in a given run. That wastes a slot, never blocks anyone.

⚠️ **The game's `SpawningEligibility` is no filter.** In the recorded run 42 of the offered events were `GuidOnly`.

## How the client enforces it

- **Locked right now** (`encounters.locked_events`): every template of a lock item not received, plus Diamond
  (until one Event Rarity Progression) and Legendary (until two) templates when the seed has the item - never
  level-up rewards, and not expeditions while `exempt_expeditions` is on. Minus, for the run, events bypassed
  (`run["bypassed_events"]`) or let through (`run["let_through"]`).
- **Entering** is the log's `Card Purchased: enc_...` line (`EncounterEntered`), which is a pick from a choice
  screen. A merchant, or an event in `OFFER_DATA` (it hands out items), only gets a warning; what you take there is
  held with `run["held_at"]` = that merchant, and stays held until sold, its card or the merchant is unlocked, or a
  bypass is used on the card. Any other locked event goes into `run["event_blocks"]`: `blocked_reason` names it
  until its unlock arrives or Use Bypass spends a bypass on it.
- **All locked:** on every new `Choice`/`Encounter` reading from memory, `encounters.let_through` checks the offers.
  Only events, every one locked: the lowest rarity wins; a tie is picked from a SHA-256 of the screen's instance
  ids, so every reading and reconnect picks the same one. That template is let through for the rest of the run.
- **Extra Event Rarity copies** are added to `bypasses_ready`.

⚠️ **Let-through lasts the run, by template.** The log line doesn't carry the screen, so the event can't be tied to
one screen; the same event offered later that run is allowed too. Lenient by design, never a false block.

⚠️ **The all-locked rule needs memory.** With the reader off, or the client closed when that screen was up, the
client can't see the offers, so going into a locked event blocks as usual (and a run caught up that way must be
conceded, like a held locked card).

⚠️ _Unverified:_ events the game puts you in without a choice are assumed to write no `Card Purchased: enc_` line,
so they're never judged. Check this in game.

## Screens and padlocks

Positions are `overlay.event_row`: each option's centre at 1080p, x from the window's centre (scaled like the
shop row), y as a share of the window's height. The client picks the row from memory (`client.event_screen`):
screen `Choice` with N options is `Choice-N`, screen `Encounter` with event options is `Line-N`. An hourly count
that isn't in `CHOICE_ROWS` gets no padlocks rather than misplaced ones; a line of any count is worked out.

- **Hourly choice:** 3 events at the same positions as the monster pick (owner, 2026-10-02; `Event3.jpg`, the middle
  one lower). Memory screen `Choice`.
- **Ticket day:** 4 events, the usual three plus the expedition, the middle two lower (`OffCenter4Event.jpg`).
- **An event leading to events:** its options in a straight line in a panel, 282 px apart (`EventToEvents.webp`,
  the Mysterious Portal). Memory screen `Encounter`. **The line is centred whatever its count** (owner, 2026-10-02:
  without the portal's bubble "they move to the center", and other events can add such an option too, "so it needs
  to be a generic solution"). An extra option that isn't an event (the portal's left bubble) never gets a padlock,
  but it takes its place in the row.
- **Hovering an event option keeps the padlocks solid** (owner, 2026-10-02: "dont make padlocks transparent on
  events when hovering an event, in all other cases still hide/make transparent it"). Hovering your board, dragging,
  the Esc menu and the stash still fade or hide them as everywhere else (`overlay.padlock_alpha`). ⚠️ Decided by
  the mouse, not the game's hover flag: the flag stays on for a moment after leaving an option, which flashed the
  padlocks see-through on the way out (owner's test, 2026-10-02).

⚠️ The 4-option row was measured on a small crop (571x350), scaled by the board's width: the pitch matches the
3-option row exactly; the heights are taken from it (the crop's own read was within about 15 px).
- The screenshots are local reference files in the repo root (ignored by git).
