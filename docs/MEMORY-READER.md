# Memory reader - what the game's memory knows that Player.log doesn't

> ⚠️ **In the client since 2026-10-01 (owner: "yes this is the go ahead, but do not release anything yet til we test
> it al"), for the shop padlocks only, NOT RELEASED.** `bazaar/memreader.py` reads the screen, the encounter and the
> offered cards; nothing else from this page is used yet. Reading memory needed one-time reverse engineering (EULA
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
| Run lost | ⚠️ only after Continue | ✅ `Losses` up + `Prestige` 0, when the replay ends |
| Run won | ✅ `EndRunVictoryState` (after Continue, _unverified when_) | ✅ state `EndRunVictory` (_not seen yet_) |
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
appears once the fight starts.

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
- **K-mem7 (2026-10-01):** `ECardSize` doesn't count from 0, so naming enum values by declaration order read every
  card one size too big. Sizes come from `bazaar_data.json`; only `ECardType` (which does count from 0) is named
  by order.

## Padlocks on locked offers (built and passed in the game 2026-10-01, not released)

**A padlock sits on the centre of each locked card on offer in a shop or a level-up; the list beside the board
names only those cards.** Owner, 2026-10-01: place them by proportion ("the shop row of cards is always roughly 1/3
down from the top ... using their sizes you can accurately put a red X or lock in the middle of the card"), a
padlock rather than an X. The reader is always on (owner: "a cornerstone for how the archipelago client will
work").

Passed in the game 2026-10-01 (owner, 1080p, Valpak and other shops, a level-up): padlocks centred on mixed sizes;
they appear as the flip ends; hovering any card fades them, empty board doesn't; a bought card leaves the others
in place; stash and Esc menu hide them; a reroll clears them at once and the new ones follow the flip.

- **Driven by memory alone** (`client.refresh_padlocks`), so screens the log never mentions (level-ups) work the
  same. A screen gets padlocks only if its layout is in `overlay.ROW_GAPS` (measured): `Encounter` (cards touch)
  and `LevelUp` (68 px apart at 1080p), and `Loot` with one card only (centred; passed in the game 2026-10-01,
  Drafting Table). `ONE_CARD_ONLY` refuses several-card loot, which never happens: owner, 2026-10-01, "Every
  monster fight will only provide 1 item". Event item
  choices on the `Encounter` screen use the shop's touching layout: Wishing Fountain's five cards (M S M M S, 8
  slots) all centred within 2 px on the owner's screenshot 2026-10-01. Events
  with their own layouts and anything else: none until measured. The list beside the board still follows the log's merchant line (`offers_at`).
- **Positions** (`overlay.card_centres`): sizes from `bazaar_data.json` (K-mem7), Small/Medium/Large = 1/2/3 slots
  of 113 px at 1080p, the row centred across the window at 39.8% of its height (measured on two screenshots,
  centres within 1-2 px). An unknown size means no padlocks at all - a guessed width would move every padlock after
  it onto the wrong card.
- **Bought cards leave a gap** (owner: "cards do not move after a purchase"): the row keeps its layout until new
  cards (new instance ids) come in. ⚠️ If the client starts or reconnects after something was already bought from
  the row, it can't know where the gap was; that row's padlocks are off until the next new cards. Offered cards
  have no slot in memory (`LeftSocketId`/`Section` are empty for them, checked 2026-10-01) and the log doesn't
  list the row, so there's no exact fix. Owner, 2026-10-01: "no big deal". A cheap option not built: no padlocks
  in that one case (the log knows a purchase happened in this shop).
- **Your stash** (passed in the game 2026-10-01: centred on Sharkclaws, followed it to slots 5, 0 and back to 3,
  shop padlocks back on closing): while it's open the client swaps to padlocks on its locked cards, read from
  `Run.Player.Stash.Container.Sockets` (cards sit and move freely in any of its 10 slots, owner). It's laid out as a
  10-slot row with `Empty` in the free slots, so the same centring puts each card on the grid. Your board uses the
  same 10-slot numbering (level 2 = slots 2-7).
- **The game's own flags drive them** (`memreader.BoardUI`, read every 60 ms; owner: "apply those useful flags as
  the triggers instead"):

  | Flag | Where | Padlocks |
  |---|---|---|
  | stash open | `BoardManager.activeStorageToy.toyOpen` | hidden |
  | Esc menu / dialog | `BoardManager.DialogOpen` | hidden |
  | a card's tooltip | `TooltipParentComponent._cardTooltipController._currentCard` (the controller lingers while fading out; the card doesn't) | 30% |
  | dragging | `CardController.IsAnyCardDragging` (static) | 30% |
  | cards flipping | `BoardManager._isRevealing` (starts ~1 s after the screen opens, lasts ~1 s) | new padlocks wait for it to start and end; 1 s if it doesn't start, 3 s at most |

  `BoardManager` is reached through `Data.<TransitionIn>._boardManager`. If these can't be read (a patch), the
  padlocks fall back to the mouse's position (each card, plus your board's width for your level, as if full: 4/6/8
  slots at levels 1-3, 10 after; owner) and a fixed 1 s wait.
- Each padlock is its own small window: see-through around the lock, click-through (`WS_EX_TRANSPARENT`), never
  focused, shown only while the game is in front.
- If a check fails the reader turns itself off until the game restarts, says so once, and shops fall back to the
  list. Game not running or still loading is silent.
- ⚠️ Only 1080p and 16:9 measured; 1440p, 16:10 and 21:9 are untested.

Not built yet: locked heroes on the character select screen (owner wants it; needs a screenshot).

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
5. **DeathLink** the moment `Losses` goes up with `Prestige <= 0` (owner's ruling).
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
| Right-click a monster on the map, then check the dump | where the preview lives (it was not in the run data) |
| Run the real client and the reader together for a whole run | no slowdown, no interference |
| The 1440p PC | same offsets on another machine |

## Open questions and traps

- ⚠️ **Not shipped and needs a decision.** DEVELOPERS.md and the README promise "no reading game memory". Using
  any of this means changing that promise, the docs and the risk statement first.
- ⚠️ **One run, one PC, one patch.** A patch that renames these classes turns the reader off. By the owner's
  ruling it must stay off, not be re-engineered automatically.
- Run **victory** (`EndRunVictory`) was not seen. Check what memory shows at 10 wins before relying on it.
- Unknown encounter ids (not in `bazaar_data.json`, mostly level-up and pedestal steps): `054e937d`, `0c410bf1`,
  `255ae0fa`, `3212ade4`, `47c256d3`, `4c3d4b9d` (Argenta skill choice), `4df2e5f8`, `a07fbe69`, `aef5e7d8`
  (right after a PvP loss on Day 10).
- Tag numbers, most card stat numbers and several player stats are not decoded.
- Whether stat ids stay the same across patches is unknown. Re-check gold/health/prestige on a new patch before
  trusting them.
- The raw watch log (15,746 lines) and dumps are in `.quickrun/memspike/dumps/` on the dev PC. They contain no
  account data.
