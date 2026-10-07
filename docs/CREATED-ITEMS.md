# Created items - cards the game makes for you

**The `created_items` option decides whether cards the game makes (spawned by another card, or transformed and kept
after any fight) are allowed, allowed only in special cases, or judged like any card you take.** Default (= Standard):
Special Cases; Casual: Allowed; Hardcore: Locked (owner, 2026-10-07: "hardcore uses locked, casual uses free and
standard uses the select cases for defaults"). Seeds from before the option behave as Allowed (rule adopted
2026-09-29).

## Rulings (owner, 2026-10-07)

- Three levels: "Always allow transformed and spawned cards, how it is today"; "Items meant to be transformed allow
  the first transformation such as Mak's reagents or events like the witchs cult or wish which transform your entire
  board"; "If the item spawned or transformed into is locked, it must be sold to continue checks, or transform again
  into a new item."
- Spawns under the middle level: "allow items that spawn 1 item consistently, not random".
- "wish" meant **Wink**. "yes I still want the cult to be included in the second rule to not totally brick your run".
- "events are not included to allow a 'free' transformation, just the ones specified that are special cases. Mandala
  is one where we want to treat it as rule 3 unless rule 1 is selected." Only Wink and The Cult are free events.
- Fight transforms never count: "it only pertains to the fight and afterward will be reset to before the fight so
  its moot."
- Reading the board is approved: "It should be able to, you already read whats in the stash".
- "soda machine should be in the rule 2 selected cases list for allow" - its drinks are free under Special Cases
  although it picks at random (`OWNER_SPAWNS` in `client.py`; Mystery Flavor is its only lockable drink).
- "Mandala is the primary way to transform items since the event will transform your leftmost item, so make sure this
  will work with the select cases from rule 2": a Mandala transform of a Reagent is free under Special Cases (the
  Reagent rule); any other Mandala transform is judged, as ruled earlier ("rule 3 unless rule 1 is selected").
- "Let the cult event allow all items that it gives", and under Locked: "It should be treated as a special case to
  allow" - everything The Cult gives is free at every level (`CULT` in `client.py`). Wink stays judged under Locked.
- "Vending machine should count ... I am only counting soda machine and vending machine since they have a limited pool
  of items that can be acquired" - both in `OWNER_SPAWNS` (Mystery Flavor is the only lockable card either makes).
  Other random spawners (Assembly Line's Loot item) are judged under Special Cases.
- Assembly Line's "At the end of each fight, transform the item to the left into a Friend from any Hero" follows the
  transform rules (free only for a Reagent under Special Cases). Its "upgrade an item of a lower tier" changes no
  card, so nothing to judge.

## The levels

| | Allowed (0) | Special Cases (1) | Locked (2) |
|---|---|---|---|
| Spawned card | free | free if one of your items always makes exactly that card (`fixed_spawns`) or it's a Soda/Vending Machine drink, or at Wink/The Cult; else judged | free at The Cult; else judged |
| Transformed card | free | free if the old card was a Reagent (and not itself a transform result), or at Wink/The Cult; else judged | free at The Cult; else judged |
| Cards The Cult hands out (logged gains) | free | free | free |

"Judged" = like a card you took: if it's locked it's held, checks are blocked until it's sold, transformed again, or
a Lock Bypass is used on it. An unlocked created card is simply fine.

⚠️ **The Cult is free at every level** (owner, 2026-10-07). This replaces the 2026-09-30 ruling "cores can be sold
so we can still block cores" for The Cult's cores.

## How the client tells

- **Transforms** come from the log (`[GameSimHandler] Transformed: itm_old into: itm_new`); the parser marks those
  logged during `CombatState`/`PVPCombatState`/`ReplayState` as `in_fight`. Those wait (`fight_transforms`) until the
  fight is over: if memory then shows the new card, it was an end-of-fight transform (Assembly Line, Fairy Statue -
  the game logs a fight's end before it leaves the replay, seen in two logs) and the usual rules apply; if the old
  card is back after `UNDONE_AFTER` (3 s), the fight undid it and nothing happened. Memory off: ignored. What a card
  became isn't in the log: when it isn't free, the new instance waits (`pending_transforms`) until memory shows it on
  your board or stash, then it's judged. Memory off, or the card gone within `TRANSFORM_WAIT` (10 s): allowed.
- **Spawns** never get a log line (verified twice: selling a card logged `spawned=2`, then two items that never had a
  `Card Purchased` line were sold). Memory reads your board (`Run.Player.Hand`) and stash; a card on them that no log
  line explains for `SPAWN_GRACE` (2 s - the log tailer can be a moment behind memory) was made by the game. If its
  log line arrives after all, the log wins.
- **Cards already there at memory's first look** (client start, reader re-attach, a new run) are adopted, never
  judged: they may predate the client watching.
- Not judged: anything during a fight screen, or in a quiet catch-up replay (transforms replayed from the log are
  allowed - memory can't say what they became hours later).
- Wink and The Cult are matched by event id (`FREE_EVENTS`, `CULT` in `client.py`), Reagents by the card's
  `Reagent` tag.
- Padlocks: allowed created cards, and cards not judged yet, get none in your stash.

## ⚠️ Unverified (needs a game session with the watcher)

- Whether a transform's new card is already on your board when its log line is read (the 10 s wait covers a delay).
- Whether a fight's own transforms (Virus, Mirror...) write a log line at all, and whether an end-of-fight transform
  (Assembly Line, Fairy Statue) is on your board by the first reading after the fight (the 10 s wait covers a delay).
- Pedestal results: if they make a new card with no log line, they're judged as spawns (never free under Special
  Cases).
- How Wink writes its transforms (one line per item is expected) and which of The Cult's cards get log lines.
- Random spawns (e.g. buying Alembic gives a Small Reagent): assumed to have no log line either.
