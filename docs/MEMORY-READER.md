# Memory reader - what the game's memory knows that Player.log doesn't

> ⚠️ **In the client since 2026-10-01 (owner: "yes this is the go ahead, but do not release anything yet til we test
> it al"), released in v0.8.0 on 2026-10-01 (owner: "I believe we are ready for a release").** `bazaar/memreader.py`
> reads the screen, the encounter, the offered cards, the stash, your board's cards (2026-10-07, owner: "we should
> be able to read the board"; see `docs/CREATED-ITEMS.md`), the board's UI flags, your Random setting and the
> game's input layers; nothing else from this page is used yet. Reading memory needed one-time reverse engineering (EULA
> section 3); the owner accepted that on 2026-09-30, on the condition that the reader only reads and switches itself
> off after a breaking patch instead of being re-engineered automatically. **Always on, no switch to turn it off**
> (owner, 2026-10-01: "always have the memory reader on, no option to turn off, this will be a cornerstone for how
> the archipelago client will work"); only a failed check turns it off. Widening what it reads needs the owner's OK.

**One live run (2026-09-30, Mak, Unranked, Day 1 to Day 11, 5 wins / 6 losses) was watched once a second. Everything
below was seen in that run unless it is marked _unverified_.**

## Contents

1. [The findings that matter for the randomizer](#the-findings-that-matter-for-the-randomizer)
2. [Player.log vs memory](#playerlog-vs-memory)
3. [Everything memory holds, field by field](#everything-memory-holds-field-by-field)
4. [The run we watched](#the-run-we-watched)
5. [What the reader refuses to read](#what-the-reader-refuses-to-read)
6. [How the reader works](#how-the-reader-works)
7. [Open questions and traps](#open-questions-and-traps)

## The findings that matter for the randomizer

### 1. Every PvP result is known the moment the fight ends

`Run.Victories` / `Run.Losses` went up at the end of each fight's replay, 11 out of 11 times (5 wins, 6 losses
including the run-ending one). Checked against the owner 2026-10-01: `Victories` 1 -> 2 at 11:29:01, while the screen was still
`PVPCombat`, the same second the owner's "W" arrived; Continue (screen `Choice`) came 10 s later. And a loss:
`Losses` 0 -> 1 and prestige 25 -> 22 at 11:44:59, still `PVPCombat`, the same second the owner's "L" arrived. Today the client asks "did you win?" or guesses from the "Waiting for N exit tasks"
log line. Memory makes both unnecessary.

### 2. A lost run is known when the loss is counted, not when the player presses Continue

Memory has the loss as soon as the fight's replay ends. Player.log only writes `EndRunDefeatState` once Continue
is pressed. **The gap is however long the player waits**: a few seconds normally, forever if they never press it.
In the test it was 41 seconds only because the player waited on the screen while we checked the log by hand.

The final loss (Day 11):

| Time | What happened |
|---|---|
| 00:11:46 | your health went below 0 in the replay (`Health = -247`) |
| 00:11:52 | `Losses` 5 → 6 **and** `Prestige` 1 → 0, in the same reading. Game state still `PVPCombat` |
| 00:11:52 - 00:12:33 | the player waited on the result screen while we checked: **Player.log had no `EndRun` line yet** |
| 00:12:33 | player pressed Continue. Only now: memory state `EndRunDefeat`, log line `[EndRunDefeatState]` |

**Ruling (owner, 2026-09-30):** DeathLink fires when the loss is counted, not when Continue is pressed. The log
version could be dodged by never pressing Continue. Trigger: `Losses` went up **and** `Prestige <= 0`. Still only
the run-ending loss, never every PvP loss (v0.4.1 ruling).

**BUILT 2026-10-06** (`BazaarContext.check_run_lost`) after a v0.9.0 game (owner + friend) showed DeathLinks still
only going out on Continue: the ruling had been written down but never built. The snapshot carries `losses`
(`Run.Losses`, read on its own so a rename never costs level/stash) and `prestige` (stat 9). The run remembers
`losses_before_fight` (Losses on the last reading off the `PVPCombat` screen); a DeathLink goes out when a reading
**on the `PVPCombat` screen** has `Prestige <= 0` and `Losses` above `losses_before_fight`. Comparing with that,
not the reading just before, means a no-screen reading or Losses read a moment before Prestige can't hide the loss.
A reader that attaches mid-fight has no `losses_before_fight`: that loss goes out on Continue.
The log's run end still sends it if memory missed it (reader off) and sends nothing if memory already did
(`run["lost_sent"]`), also when the run then ends as a concede. A DeathLink received after the loss is a dodge
(the run is over). Nothing is judged while disconnected (no slot_data).
The game greys out Concede during a fight (owner, in game 2026-10-06), so a concede can never be read as a loss.
⚠️ Not yet seen against a real lost run in game.

**Game closed mid-fight (owner, in game 2026-10-06):** the server finishes the fight; the game comes back on the
NEXT day with the result counted (memory: Day 2, Hour 0, Victories 1) and Player.log never says so. A run resumed
after a game restart is resynced from memory (`BazaarContext.resync_run`, `run["resync"]`): the new log's days
count from `Run.Day`, missed days are sent, and one extra `Run.Victories` with the day one ahead is the last day's
PvP win. Verified in game the same day: "Resumed ... day 1" then "moved on to day 2", Day 1 PvP Win + Reach Day 2
sent. ⚠️ More than one missed win (never seen) only updates the win count: which days they were is unknown.
⚠️ Closing the game while the reader is attaching once crashed the reader with OverflowError
(CreateToolhelp32Snapshot gave INVALID_HANDLE_VALUE); `find_module` now says "still loading" instead.

Prestige moved with the loss counter every time: 25 → 24 (Day 1), 24 → 22, 22 → 14 (Day 8), 14 → 5 (Day 9),
5 → 1 (Day 10), 1 → 0 (Day 11). Monster losses did **not** cost prestige.

### 3. Monster tier is known before the fight, and so is the result

- The monster choice cards carry their tier: e.g. Day 2 offered Rogue Scrapper (Bronze), Boarrior (Silver),
  Ventriloquist (Gold). 31 different monsters were seen with a tier (list below).
- Win or loss is plain: whoever's `Health` reaches 0. Radiant Corsair (Day 7) and Frost Street Champion (Day 10)
  were lost. Your health went to -137 and -1491 while the monster still had health left.
- **A lost monster fight has no loot screen.** Win: `Combat → Loot → ...`. Loss: `Combat → Choice` or
  `Combat → LevelUp` (XP still counts). Confirmed again 2026-10-01: `Combat → Choice` at 11:18:55, owner: "yes i
  lost". This is very likely why the Karnok run "lost" its Day 4, 7 and 9 monster
  checks (Replay → Choice, no LootState): those fights were probably lost. _Unverified for that run_ - we only have
  its logs.

### 4. The shop's exact contents, with tier, size and price

Every merchant, loot and level-up offer is readable, including rerolls. Example, Herma on Day 2: Cellar (Bronze,
Medium, 4 gold), Philosopher's Stone (Bronze, Small, 2 gold), Sword Cane (Bronze, Medium, 4 gold), reroll cost 3,
1 reroll left. 469 item offers were read across the run with no misses we noticed. This is what the opt-in
screenshot idea was for: it could mark locked cards on the overlay without matching card art.

## Player.log vs memory

| Question | Player.log | Memory |
|---|---|---|
| Hero | ✅ `Changing EHero to X` | ✅ `Player.Hero` |
| Day | ✅ (from day transitions) | ✅ `Run.Day` |
| Hour of the day (0-6) | ❌ | ✅ `Run.Hour`, `HoursInADay = 6` |
| PvP win/loss | ❌ guessed / asked | ✅ `Victories` / `Losses`, when the replay ends |
| Run lost | ⚠️ only after Continue | ✅ `Losses` up + `Prestige` 0, when the replay ends (DeathLink uses this, 2026-10-06) |
| Run won | ✅ `EndRunVictoryState`, ~8 s after the 10th win (seen 2026-10-01) | ✅ `Victories` = 10 when the fight ends; state `EndRunVictory` when the player moves on, like a loss (~7 s on 2026-10-01; 76 s on 2026-10-14 while the owner looked through the recaps) |
| Monster tier | ⚠️ only through loot after a win | ✅ on the choice card, before the fight |
| Monster win/loss | ⚠️ inferred from a loot screen | ✅ health of both sides |
| Monster's board | ❌ | ✅ once the fight starts |
| What a shop offers | ❌ | ✅ every card with tier, size, price |
| Card bought | ✅ TemplateId | ✅ plus where it went (board/stash, slot) |
| Your board and stash | ❌ | ✅ every card, slot, tier, size, tags, prices, cooldowns |
| Gold, health, level, XP, prestige, income | ❌ | ✅ player stats (table below) |
| Rerolls | ❌ | ✅ cost and rerolls left |
| Level-up and skill offers | ❌ | ✅ |
| Current screen | ⚠️ some `AppState` changes | ✅ `RunState.StateName`, 11 states |

## Everything memory holds, field by field

The path is static `TheBazaar.Data` (in `TheBazaarRuntime.dll`). Only the fields below are read.

### The run - `Data.<Run>` (`BazaarGameClient.Domain.Models.Run`)

| Field | Seen as | Notes |
|---|---|---|
| `Day`, `Hour` | 1-11, 0-6 | Hour 0 is right after the PvP fight; Hour 6 is the PvP fight |
| `Victories`, `Losses` | 0-5, 0-6 | PvP only. Monster fights don't count |
| `PlayMode` | `Unranked` | |
| `GameModeId` | a GUID | not decoded |
| `HasVisitedFates` | true/false | not decoded |
| `Player` | see below | |
| `Opponent`, `SeedManager` | **not read** | see "What the reader refuses to read" |

### The current screen - `Data.<CurrentState>` (`RunState`)

| Field | Notes |
|---|---|
| `StateName` | `Choice, Combat, Encounter, EndRunDefeat, EndRunVictory, LevelUp, Loot, NewRun, Pedestal, PVPCombat, Shutdown` (the enum order matched the screens every time) |
| `CurrentEncounterId` | the encounter you are in: a merchant, event, monster or level-up step. Matches our monster/merchant GUIDs |
| `RerollCost`, `RerollsRemaining` | e.g. 3 / 1. Aerodrome showed cost 1 with 50 rerolls, cost going up 1 each time |
| `SelectionSet` | the cards on offer right now (instance ids, resolved through `Data.Entities`) |

### Player stats - `Player.Attributes` (stat number → value)

The numbers are the game's own stat ids. The names were worked out by watching values change against what happened
on screen.

| Stat | Meaning | How we know |
|---|---|---|
| 4 | **Gold** | bought Refractor for 4: 16 → 12; income day: 8 → 13 |
| 5 | **Income** | 5 all run; gold rose by 5 each new day |
| 9 | **Prestige** | 25 at start, dropped on every PvP loss, 0 when the run ended |
| 10 | **Health** (current) | fell during fights, below 0 on a loss, full again after |
| 11 | **Max health** | 400 → 440 → 590 → ... → 5123, up on level-ups and days |
| 15 | **Level** | 2 → 3 at the first level-up screen, 11 by the end |
| 3 | **XP** | counted up, reset at a level-up |
| 27 | gold earned this run (_likely_) | rose by exactly what each sale paid |
| 29 | unknown counter | 1 → 2 after Boarrior, but 10 by Day 7, so not monster wins |
| 0, 16, 12 | burn, poison, regen on you (_unverified_) | only non-zero during fights |
| 28, 30-33, 35, 38, 40, 41 | unknown | 40/41 are ±999999999 (limits?) |

### Cards (your board, stash, skills, offers and the monster's board)

Each card is an entity in `Data.Entities`, with:

| Field | Seen as |
|---|---|
| name | from `TemplateId` + our data; falls back to the game's internal name (`Template.InternalName`) |
| `Tier` | Bronze, Silver, Gold, Diamond, Legendary |
| `Size` | ⚠️ read one size too big by the spike (2026-10-01): `ECardSize` doesn't count from 0, so naming values by declaration order is wrong. Not read any more - sizes come from `bazaar_data.json` |
| `Type` | Item, Skill, CombatEncounter, EventEncounter, PvpEncounter, PedestalEncounter, EncounterStep |
| `Section` | 0 = board, 1 = stash, empty = not placed (on offer) |
| `LeftSocketId` | the slot, 0-9. **Live while dragging**: Cellar showed stash slot 3 while it was held over it |
| `State` | Alive (others not seen) |
| `Tags`, `HiddenTags` | numbers, not decoded to names |
| `Enchantment` | read, but no enchanted card appeared this run |
| `InstanceId` | e.g. `itm_OB9L9CU`, stable while the card exists |

Card stats (`Card.Attributes`):

| Stat | Meaning | How we know |
|---|---|---|
| 37 | **Buy price** | Refractor 4, paid 4 |
| 38 | **Sell price** | about half the buy price (2→1, 8→4, but 3→2); sales matched |
| 4 | cooldown left, in ms (live in fights) | Floor Spike 3050 of 8000 mid-fight |
| 5 | cooldown, in ms | |
| 70, 71 | quest progress (_unverified_) | only on Eternal Torch |
| others | damage, burn, shield... (_unverified_) | the game's own number table didn't line up with names by position |

### Monsters (only while fighting one)

When the current encounter is a known monster and the fight has started, `Run.Opponent` holds its board, skills
and stats: e.g. Boarrior had Frontal Shielding (skill), Scrap, Tusked Helm, Old Sword, Hatchet, Lumboars, a
Legendary Crash Site Ticket and Sharpening Stone, each with its slot, tier and cooldowns. Its health and max health
(350) were live.

⚠️ The right-click preview on the map did **not** put the monster's cards into the run data. Its board only
appears once the fight starts. **2026-10-15:** the preview lives in the tooltip instead -
`_cardTooltipController._monsterBoardTooltip` (`MonsterBoardTooltip`): `_activeCards` is a `List<CardPreviewItem>`,
each a UI element on the tooltip canvas (`_canvasForWorldBounds`) with its card in `_clientCard` (`TemplateId`), and
`_sockets` the 10 slots. The items slide up from below the window for ~0.5 s, then sit still; their rects matched the
owner's video (Soda Swiller, Baron Boys) to the pixel. Read only while a right-click view is open on a
`CombatEncounterCard` whose template's `CombatantType` is a `TCombatantMonster` - never a PvP opponent
(`memreader._monster_board`).

### Monster tiers seen on choice cards

Bronze: Cosmic Roc, Dabbling Apprentice, Dire Inglet, Hulking Experiment, Master Alchemist, Outlands Dervish,
Preening Duelist, Rogue Scrapper, Surly Mechanic, Unibou.
Silver: Boarrior, Bouncertron, Frost Street Challenger, Ghost Pepper, Industry Plant, Infernal Envoy, Sandwich
Artist, Terrorform, Test Subject Alpha, Wild Boar.
Gold: Annex Trooper, Drone Operator, Hoverbike Hooligan, Prince Marianas, Ventriloquist.
Diamond: Foreman, Frost Street Champion, Gibbus, Yerdan.
Legendary: Dragon, Radiant Corsair.

## The run we watched

| Day | Monster | PvP | Prestige after |
|---|---|---|---|
| 1 | Fanged Inglet (before the watcher started) | lost | 24 |
| 2 | Boarrior (Silver) won, loot Scrap | lost | 22 |
| 3 | Dabbling Apprentice (Bronze) won | won | 22 |
| 4 | Wild Boar (Silver) won | won | 22 |
| 5 | Drone Operator (Gold) won | won | 22 |
| 6 | Foreman (Diamond) won | won | 22 |
| 7 | Radiant Corsair (Legendary) **lost**, Ghost Pepper (Silver) won | won | 22 |
| 8 | Bouncertron (Silver) won | lost | 14 |
| 9 | Terrorform (Silver) won | lost | 5 |
| 10 | Frost Street Champion (Diamond) **lost** | lost | 1 |
| 11 | Test Subject Alpha (Silver) won | lost - run over | 0 |

States counted: 174 Choice, 227 Encounter, 156 Combat, 196 PVPCombat, 9 Loot, 15 LevelUp, 6 Pedestal,
2 EndRunDefeat. Mountain Pass started a fight straight from an event; Mysterious Portal and Street Festival led
into hero merchants (Stelle, The Dragons, Jules). Those are shops, not players.

## What the reader refuses to read

Owner's rules, 2026-09-30: "only memory and nothing that we are not allowed to see", "Any information about the
cards ... even if it is when you right click a monster", "Just dont involve players".

- **Allowlist:** only `Data.<Run>`, `<CurrentState>`, `Entities`, `<CurrentEncounterId>`, `<HoursInADay>`,
  `<CurrentBoardId>`, and (2026-10-01, for the padlocks) `<TransitionIn>` (to reach the `BoardManager`) and
  `<TooltipParentComponent>`, plus `CardController`'s static drag flag. Nothing else in `TheBazaar.Data` is touched.
- **Blocked by name anywhere below that:** anything containing seed, rng, random, opponent, steam, store, title,
  account, ticket, token, auth.
- **Real players are never read:** no opponent during PvP, no `SimPvpOpponent`, no PvP encounter cards, and no
  entity owned by a hero. `Run.Opponent` is read only when the current encounter is one of our known monsters and
  the screen isn't PvP.
- **Read-only:** the process is opened with `PROCESS_VM_READ` only. No writes, no injection, no network, no game
  files.
- **Nothing outside the game** (owner, 2026-10-01): the game is found by its window (class `UnityWndClass`, title
  `The Bazaar`) and only that window's process is opened, to confirm it's `TheBazaar.exe`. No process list, and the
  overlay never opens whatever app is in front; it only compares the front window with the game's.

## How the reader works

The spike scripts live in `.quickrun/memspike/` (git-ignored, on the dev PC only):

| Script | What it does |
|---|---|
| `memread.py` | finds The Bazaar and Mono, discovers Mono's struct offsets, reads day/hour/W/L and the selection |
| `memdump.py [depth]` | allowlisted dump of the run state to `dumps/dump-<time>.json` |
| `watch.py` | once a second: readable summary to `dumps/watch.log` when anything changes, plus a full dump per screen change |

Run with `.venv/Scripts/python.exe .quickrun/memspike/watch.py` while the game is open.

**No offset is hard-coded.** The game is Unity 6000.3.11f1 on Mono (`mono-2.0-bdwgc.dll`). Each start, the reader
finds every Mono runtime offset by probing and checks it against names it must find (`mscorlib`,
`TheBazaarRuntime`, the `Data` class and its fields). If any check fails it stops with "Reader turned off" instead
of guessing. Offsets found on 2026-09-30: assembly list +0xA0, class cache +0x4D0, class name +0x48, next class
+0x108, parent +0x30, fields +0x98, runtime info +0xD0, static data +0x68 (vtable).

⚠️ Traps hit while building it, so the next person doesn't repeat them:
- **K-mem1:** a `MonoClass` starts with pointers to itself. Probes that accept "points back to the class" will
  lock onto those and loop or return garbage. Skip self-pointers.
- **K-mem2:** the static field block was found by matching one known field. One match can be a coincidence. Now
  it needs two.
- **K-mem3:** .NET Core `Dictionary` entries are 16 bytes for enum → int and 24 bytes for reference keys. Guessing
  24 first garbled the stat tables. Enum keys are checked by `hashCode == key`.
- **K-mem4:** `x or default` in Python turns a real `0` into the default. A dictionary "next" index of 0 made
  every entry look invalid.
- **K-mem5:** the class an instance field belongs to may be in another assembly (`BazaarGameClient`,
  `BazaarGameShared`), so search classes through the object, not by name in one image.
- **K-mem6 (2026-10-01):** a class's statics are NOT at a fixed vtable slot. They sit after its vtable's method
  slots: `vt->vtable[klass->vtable_size]` (array at vt+0x48, method count at class+0x5C here). `Data` and
  `AnalyticsManager` happen to have the same method count, so slot +0x68 looked fixed; `BoardManager` and
  `CardController` both read garbage there. `Mono.learn_static_blocks` finds the count's place and only accepts
  it when two classes agree (`BoardManager.CancellationToken` is a `CancellationTokenSource`, `CardController`'s
  drag flag is 0 or 1).
- **K-mem9 (2026-10-07): the Tempo launcher runs the game as administrator.** Same Mono build, window and exe as
  Steam's (`%APPDATA%\Tempo Launcher - Beta\game\buildx64\TheBazaar.exe`), but its token is elevated, so a normal
  client gets error 5 on `OpenProcess(VM_READ | QUERY_INFORMATION)` and an empty module list - which read as "the
  game is still loading" forever (a player's log, 2026-10-06). `memreader.needs_admin` checks this first and raises
  `NeedsAdmin`; the client then restarts itself through Windows' permission prompt (owner: "ask for admin right
  away", no Yes/No box - one opened under the game unseen) and closes the old window like `/exit`. Verified live
  2026-10-07: an elevated reader attaches to the Tempo game; a normal one gets `NeedsAdmin`.
- **K-mem8 (2026-10-01):** some objects nothing static points to (the input manager) are found by searching the
  game's private read-write memory once for their class's vtable pointer (`Memory.find_pointer`, ~4.4 GB in 6-28 s);
  this Mono's GC never moves objects, so the address holds while the object lives. Needs PROCESS_QUERY_INFORMATION
  (to list the regions) on top of VM_READ - still read-only. ⚠️ 2026-10-14: the game REPLACES its input manager
  when a run ends and the menu comes back (watched: the stack size went to None at the concede, a fresh search read
  1 with the hero-change screen open). Kept "for the session", the hero panel stopped hiding under the game's
  screens after every run; `menu_layers` now searches again when it's gone (`INPUT_SEARCH_SECONDS`).
- **K-mem7 (2026-10-01):** `ECardSize` doesn't count from 0, so naming enum values by declaration order read every
  card one size too big. Sizes come from `bazaar_data.json`; only `ECardType` (which does count from 0) is named
  by order.
- **K-mem10 (2026-10-14): at the main menu `BoardManager` and `CardController` aren't set up yet** (their
  `MonoClass` runtime info is 0), so learning the board's flags fails there - and it was tried only once per game
  session, so a client that attached at the menu (the usual case) had no stash padlocks, padlocks in the
  loading screen, mouse-only fading and the fixed flip wait all session (owner's bugs 1 and 5). The hero preferences
  (`_learn_prefs`) need the same static blocks and were off too. `Reader.ui()` now retries every
  `UI_RETRY_SECONDS` until a run's board has loaded (watched: learned at once); the class search (~150 ms) is done
  once and cached, since `ui()` runs on the client's event loop.
  ⚠️ Found and dropped the same day: `BaseTooltipController._contentWorldCorners` is NOT the tooltip's shape - it
  leaves out the cooldown clock and the tag chips, the keyword box isn't the `_auxiliaryTooltipController` (that
  one sits elsewhere), and it keeps old values in the right-click view; the owner's screenshots showed all four.
  The pieces are read instead (K-mem11). `BoardManager.Instance` is a static on its generic parent class, not on
  `BoardManager`.
- **K-mem12 (2026-10-14): nothing the game can replace is kept for the session.** Swept after the input manager
  (K-mem8): the reader keeps only class layouts and static-field slots (fixed while the game runs; every value
  behind them is re-read) and per-reading card ids. A snapshot that fails reads as "no screen" for up to
  `SNAPSHOT_GRACE` (10 s) - the game swaps objects around a run's end - and only a lasting failure turns the reader
  off for the session (attach's layout checks catch a patch first). ⚠️ When adding a reader: anything found once
  must be re-found when it's gone, and a failed read must not count as a patch unless it lasts.
- **K-mem11 (2026-10-14, amended the same day): a card's on-screen position is not in managed memory - it is in
  Unity's native objects, and is read from there** (`bazaar/unity.py`, Unity 6000.3.11). Owner, 2026-10-14: "I want
  the positioning of where UI is supposed to be NEVER GUESSED". How, every offset checked against the owner's
  screenshots:
  - A UnityEngine.Object's native object: `+0x10`. Transform: hierarchy `+0x28`, index `+0x30`; hierarchy: local
    position/rotation/scale `+0x18` (48 bytes per index), parent index `+0x20` (-1 = root), Transform* table `+0x30`.
    World = the parents composed (`unity.world`).
  - The camera: `CardController.mainCamera`, native `+0xF0` = world->clip, column-major. Board anchors landed within
    ~5 px.
  - A card: its `Rig` transform and its `BoxCollider` (native `+0x60` centre, `+0x6C` size: Small 1.39 x 3.2,
    Medium 3.0 x 3.2), 8 corners projected (`unity.box_rect`). Matched shop (5/5, Small to Large), loot, level-up,
    board, stash: 1-4 px vertically, ~7 px inside the gold frame (the collider is the clickable area). Dragging,
    swapping, the others sliding aside, the hover enlargement and the right-click view all move this same
    transform, so all of them follow.
  - Interface pieces: Component `+0x20` = GameObject; GameObject `+0x20` = components (the first is its
    Transform), `+0x50` = name, `+0x46` = Unity's on/off switch. RectTransform `+0xB8` = rect (x, y, w, h) on a
    screen canvas whose units are pixels, y up (`unity.ui_rect`).
  - ⚠️ The game pools card controllers: a scan finds dead ones and other players' cards - never scan; reach cards
    through the board's sockets (`playerItemSockets`, `playerStorageSockets`; the merchant's `opponent*Sockets` only
    off fights and only for ids on offer - owner ruling 2026-10-14).
  - ⚠️ Event options (`BoardManager._opponentBoardSocketControllers`, found by id) have no native Rig; their place
    needs the GameObject route and wasn't finished - events keep the measured layout (owner: "leave the hard coded
    positions of padlocks as they are for events").
    **2026-10-15 (recorded with the owner):** the list is a `List<EncounterSocketController>`; each socket's own
    GameObject Transform has a world pose that flips with the stash exactly like the shop's cards, and options drop
    out of the list as they leave after a pick. So an option's padlock shows only while its socket is switched on
    and faces you (`memreader._card_rects`; `padlocks.spot`).
    **Second recording, 2026-10-15:** the socket projected ~18 px off the measured centres, but the option's own
    `CardController` Transform lands on the art's centre (715,305 where the measured spot was 715,303), and when the
    event is right-clicked it moves into the big view and sits on the enlarged art's centre (0.363, 0.41, matched to
    the owner's video). So event padlocks are placed there - the socket only says which way it faces. ⚠️ Unverified:
    that an option's controller carries the camera (else the last camera seen is used).
  - **The on/off switch of each card (2026-10-15 recording):** a sold card's GameObject turns off one frame before it
    leaves its slot; cards are skipped while off. Card backs during a reveal are *not* a rotation of the card (it
    faces you throughout), so the flip timers stay.
  - ⚠️ The on/off switch hides only some tooltip pieces (the sell box); the keyword boxes and an empty bottom box
    stay "on" - see `memreader.TOOLTIP_PIECES` for the chosen pieces and the right-click rule for the keyword boxes.
    A padlock just below a short tooltip can go 30% with nothing over it; never hidden. Not finished: the pieces'
    own transparency.
  - ⚠️ A Unity update can move these offsets: then positions read nothing (no padlocks on cards), never wrong ones.
- **K-mem9 (2026-10-02):** a game that is still loading fails other checks too, not just the assembly list:
  "MonoImage.class_cache not found" 5 s after "still loading" turned the reader off for the whole session (no
  padlocks, menu panel never hidden); it attached fine once loaded. Any failed attach within `LOADING_SECONDS` of
  first seeing the game is now "still loading"; only after that is it a failed check.

## Padlocks on locked offers (passed in the game 2026-10-01, released in v0.8.0)

**A padlock sits on the centre of each locked card - on offer, in your stash, on your board - wherever the
card is, read from memory (K-mem11); the list beside the board names only those cards.** Owner, 2026-10-14: "I
basically want these padlocks to appear as if they are ART on the card"; "NEVER GUESSED". (2026-10-01 to 10-14 they
were placed by measured proportions of the window; that is gone, event options included since 2026-10-15.)

- **Who decides what** (one job each): `client.refresh_padlocks` says *which* cards (their instance ids: locked
  offers on `ITEM_SCREENS`, locked stash and board cards off fights); `memreader.ui` says
  *where* every card and tooltip piece is; `padlocks.py` says where each padlock goes and how it shows; the overlay
  only draws. A card memory can't place gets no padlock.
- **Event options** are placed from memory too since 2026-10-15 (their art's centre, above). The measured layout
  (`overlay.event_row`) is used only by `padlocks.spot` for an option with no card, which the client never sends;
  every option count gets padlocks (an unmeasured hourly count used to get none).
- **A right-clicked monster's board** (owner, 2026-10-15): each locked item on it gets a padlock, keyed
  `monster:<i>` (`BoardUI.monster_items`), the same lock list as the shop.
- **Bought cards**: the others don't move (owner), and their padlocks stay on them because they follow the cards.
- **The game's own flags drive them** (`memreader.BoardUI`, read 60 times a second, was every 60 ms until 2026-10-15; ⚠️ asyncio.sleep and Tk timers round up to Windows' ~15.6 ms tick, so "16 ms" really ran ~35 and ~45 times a second (owner saw ~20 fps): since 2026-10-15 the client asks Windows for 1 ms timers (timeBeginPeriod, this process only), the read loop runs at 60/s and the overlay looks for a new read every 2 ms (measured ~400/s) and moves the padlocks on each one - one clock, so the two can't drift against each other (they ran 58/s and 64/s before); ⚠️ a board read cost ~0.7 ms a card plus 1-1.5 ms for a tooltip (recorded 2026-10-15, ~50 calls into Windows a card) - too slow for a 144 Hz frame (6.9 ms) - so during one read memory is fetched in page-sized (4 KB) aligned blocks and reused (`READ_BLOCK`; never across reads, so nothing goes stale). Measured 2026-10-15: a call into Windows costs ~5 us whatever its size, 13 cards read in 4.0 ms with 4 KB blocks (4.5 with 256 B) - the rest is Python's own work, and 60 fps (16.7 ms) is the target (owner: a 60 cap is fine); owner: "apply those useful flags as
  the triggers instead"):

  | Flag | Where | Padlocks |
  |---|---|---|
  | stash flipping open or shut | not a flag: each card's own pose. The stash is the back of the shop's panel, which flips 180 degrees about x in ~0.6 s; `toyOpen` and `StorageMoving` turn on at the *start*, so they can't say what's seen (recorded 2026-10-15) | a card has a position only while its face is toward the camera (`unity.faces_camera`): your board's padlocks never hide, the shop's go and the stash's appear as the panel turns edge-on, and back (owner 2026-10-15: "it is not okay to keep 'Hiding padlocks' if the card is still visible"; was hidden by `toyOpen`) |
  | Esc menu / dialog | `BoardManager.DialogOpen` (also on through the new-day screen, from Continue until the next events are visible; watched 2026-10-14) | hidden |
  | a card's tooltip | `_cardTooltipController._currentCard`; its pieces' rects (`memreader._tooltip_pieces`, K-mem11) | 30%, only padlocks a piece reaches (plus `padlocks.COVER_PAD`) |
  | dragging | `CardController.IsAnyCardDragging` + `DraggedCard`'s instance id | the dragged card's padlock rides on it; padlocks under it 30% |
  | hovering | the tooltip's card | its enlarged picture (its real rect) fades the padlocks it reaches - never its own |
  | right-click view | `_cardTooltipController.isLocked` (on exactly while it's open: shop card, monster, events; 2026-10-14) | the right-clicked card keeps its padlock (on the big card) - an event's too, since 2026-10-15 - and so do a right-clicked monster's items; all others hidden |
  | new cards dealt | `BoardManager._cardsBeingDealt` (on as a reroll's old cards start to dissolve) | the old padlocks go at once |
  | cards flipping | `BoardManager._isRevealing` (on as the card backs swirl in, ~0.1 s after the deal flag; a shop's 1.5 s, a reward choice's 0.55 s, an event's ~0.3 s; clips 2026-10-14) | new padlocks show `FLIP_DELAY` (0.7 s) after it turns on, left to right `padlocks.FLIP_STAGGER` (0.12 s) apart - when the first shop card turns face-up, 3 of 3 clips - or when it ends if sooner (rewards and events don't flip); one that began up to `FLIP_EARLY` before the client noticed the cards counts; 1 s if none starts |

  **The rule behind the table (owner, 2026-10-14): can the player buy or click the card right now?** Not -> hidden
  (turned away under the stash, settings/Esc, dialogs, loading). Covered but still actionable -> 30% (a tooltip, a drag): "with
  the tooltips you can still buy the item or go to the event so the padlock should remain translucent". New cards:
  the padlock appears as the card turns face-up, not while face-down ("you can see the size and rarity of a card
  BEFORE it has flipped") and not after (the player could buy before noticing). "Covered" means reaching the padlock
  itself, "but add some padding to the edges, not a lot though"; padlocks don't grow with a hovered card (owner,
  2026-10-14).

  `BoardManager` is reached through `Data.<TransitionIn>._boardManager`. If these can't be read (a patch), no
  padlocks show, event options included (owner 2026-10-15: "padlocks are to only be seen if the art for what it is
  supposed to be on top of is there"; until then event options followed the mouse's position, with your board's
  width for your level as if full: 4/6/8 slots at levels 1-3, 10 after, and a fixed 1 s wait).
- Each padlock is its own small window: see-through around the lock, click-through (`WS_EX_TRANSPARENT`), never
  focused, shown only while the game is in front.
- If a check fails the reader turns itself off until the game restarts, says so once, and shops fall back to the
  list. Game not running or still loading is silent.
- ⚠️ Positions are fractions of the game window from the camera, so any size should work - only 1080p 16:9
  checked.

Not built yet: locked heroes on the character select screen (owner wants it; needs a screenshot).

## The settings gear (found 2026-10-15, owner's run left open)

**The gear at the board's top right is `FightMenuDialog.SettingButton`, a "Btn_Settings" in the HUD's 1920x1080
"Buttons" canvas** (path Dialogs/Buttons/ScalerOffset/Resources_Tabs_P/BtnContainer_Settings/Btn_Settings).
Read as fractions of the window it was (0.928, 0.030, 0.973, 0.109); a capture of the game window put that box
exactly on the gear. Used for the overlay windows that get out of its way (docs/OVERLAY.md).

- Nothing static points to the dialog: `find_gear` searches for it by its vtable like the input manager (~16 s,
  worker thread, on the board only, at most every `GEAR_SEARCH_SECONDS`). Seven FightMenuDialogs existed; only the
  live one's button is switched on. Kept while its class still matches and the button is on; then searched again.
- ⚠️ The hierarchy's root ("Dialogs") reads a canvas size of ~1e-44, not 0: the canvas is the outermost ancestor
  with a size of at least 1 ("Buttons").
- ⚠️ Not looked at: the main menu's gear (a different object, `LoginScreen/.../Btn_Settings` exists) - the measured
  place is used there.

## Bringing the rest into the client (plan, nothing built)

**Memory adds to the log; it never replaces it.** Everything the client does from `Player.log` today keeps
working. If the reader is off or turns itself off mid-run, the client carries on from the log and says so on the
status line.

1. **`bazaar/memreader.py`** - the spike made proper: read-only, no Archipelago imports (testable like
   `logparser.py`), probes and verifies offsets once per game start, turns itself off on any failed check.
2. **A poll thread** (2-4 readings a second) that turns readings into events, the same way `logparser.py` turns
   lines into events: screen changed, offer changed, PvP won/lost, run lost, monster chosen (with tier), monster
   won/lost.
3. **Locked cards in the shop (the big one) - BUILT 2026-10-01, see "Padlocks on locked offers".** On every offer change, the client compares the offered cards with
   what's unlocked and tells the overlay exactly which offered cards are locked, using the existing `show_shop()`
   list in the left strip: "Herma: Cellar is locked (2nd card)". That replaces today's "could sell any of N cards"
   list with the real cards. Overlay rules still apply: only beside the board, never over the shop cards, text
   at least 10 px. Naming the position ("2nd card") needs the selection order to match the screen (test below).
   The Shop Guide could highlight the same cards.
4. **PvP results** from `Victories`/`Losses`: no more "did you win?" prompt or exit-task guess.
5. **DeathLink** the moment `Losses` goes up with `Prestige <= 0` (owner's ruling) - BUILT 2026-10-06.
6. **Monster checks** from the choice card's tier plus the health result, so a won fight is never missed and a
   lost one is never mistaken for a detection failure.
7. **Docs and the promise.** README, DEVELOPERS.md ("the one big rule") and the setup guide must say plainly that
   the client reads memory and what the risk is, before any release. Whether it's opt-in, and the default, is the
   owner's call.

## Next test session - what to look for

| Test | Why it matters |
|---|---|
| Win a run (10 wins): when does memory show `EndRunVictory`, and what do `Victories`/state read before Continue? | the goal check |
| Concede a run | concede DeathLink option and run reset |
| Restart the game mid-run, start the reader again | the reader must reattach and pick the run up |
| Is `SelectionSet` order the same as left-to-right on screen? Note one shop's cards in screen order | "2nd card is locked" on the overlay |
| A shop with a Medium card, and a 1440p screen: padlocks still centred? (row measured on Small/Large at 1080p-ratio, 2026-10-01) | padlock positions |
| Padlocks sit on the right cards, clicks and tooltips still work through them, they go when you leave | the padlocks themselves |
| Buy a card: do the others slide over? Reroll: do the padlocks move with the new cards? | padlocks follow purchases |
| An event that offers a choice of items: same row as a shop? | padlocks outside merchants |
| Read gold, health, prestige, level and XP off the screen once and compare | confirms the stat table |
| An enchanted card on the board | `Enchantment` decoding |
| Run the real client and the reader together for a whole run | no slowdown, no interference |
| The 1440p PC | same offsets on another machine |

## Open questions and traps

- ⚠️ **Shipped in v0.8.0 (2026-10-01).** README and DEVELOPERS.md now say the client reads the game's memory,
  read-only. Using anything more from this page means updating those first.
- ⚠️ **One run, one PC, one patch.** A patch that renames these classes turns the reader off. By the owner's
  ruling it must stay off, not be re-engineered automatically.
- ⚠️ **`<CurrentState>` can point at a dead object for a moment.** 2026-10-01, right after a concede, at the log's
  `[AppState] Clean up completed`, it held something that wasn't a `RunState` ("field StateName not found") and
  the reader switched off for the session. A failed check on a non-`RunState` object is no patch (attach already
  checks the static's type), so the snapshot reads it as "no screen" and the next look tries again
  (`Mono.is_a`). Only a field missing from a real `RunState` still turns the reader off. The same moment once read
  `StateName` as "0" ("unknown screen 0", 15:20, a run start): an unknown screen name is now "no screen" as well.
- ⚠️ **A few seconds after launch the assembly list exists without the game's code** (2026-10-01: "the game's
  assembly list wasn't found" switched the reader off for that session). A list holding `mscorlib` but not yet
  `TheBazaarRuntime` means "still loading" (retried in 5 s). That wasn't enough - at 15:33 there was no list at
  all yet - so for `LOADING_SECONDS` (120) after the reader first looks at a game, a missing list is "still
  loading" too; only after that is it a failed check (`test_memreader.py`).
- Run **victory** seen 2026-10-01 (Vanessa, 10 wins 3 losses, day 13): `Victories` 9 -> 10 at 13:00:39 while still
  `PVPCombat`; state `EndRunVictory` at 13:00:46; the log's `EndRunVictoryState` at 13:00:47. So memory knows the
  run is won as soon as the 10th win counts, ~8 s before the log.
- Unknown encounter ids (not in `bazaar_data.json`, mostly level-up and pedestal steps): `054e937d`, `0c410bf1`,
  `255ae0fa`, `3212ade4`, `47c256d3`, `4c3d4b9d` (Argenta skill choice), `4df2e5f8`, `a07fbe69`, `aef5e7d8`
  (right after a PvP loss on Day 10).
- Tag numbers, most card stat numbers and several player stats are not decoded.
- Whether stat ids stay the same across patches is unknown. Re-check gold/health/prestige on a new patch before
  trusting them.
- The raw watch log (15,746 lines) and dumps are in `.quickrun/memspike/dumps/` on the dev PC. They contain no
  account data.
