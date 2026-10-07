# Created items - cards the game makes for you

**The `created_items` option decides whether cards the game makes (spawned by another card, or transformed outside a
fight) are allowed, allowed only in special cases, or judged like any card you take.** Default: allowed, which is
how it worked before the option (rule adopted 2026-09-29).

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

## The levels

| | Allowed (0) | Special Cases (1) | Locked (2) |
|---|---|---|---|
| Spawned card | free | free if one of your items always makes exactly that card (`fixed_spawns`), or at Wink/The Cult; else judged | judged |
| Transformed card | free | free if the old card was a Reagent (and not itself a transform result), or at Wink/The Cult; else judged | judged |
| Cards The Cult hands out (logged gains) | free | free | judged |

"Judged" = like a card you took: if it's locked it's held, checks are blocked until it's sold, transformed again, or
a Lock Bypass is used on it. An unlocked created card is simply fine.

⚠️ **The Cult under Allowed is free too** (my call, 2026-10-07, not yet confirmed by the owner): Allowed is meant to be
the most lenient level, so it can't be stricter than Special Cases. Before the option, a locked core from The Cult
had to be sold (2026-09-30 "cores can be sold so we can still block cores").

## How the client tells

- **Transforms** come from the log (`[GameSimHandler] Transformed: itm_old into: itm_new`); the parser marks those
  logged during `CombatState`/`PVPCombatState`/`ReplayState` as `in_fight` and the client ignores them. What a card
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
- Wink and The Cult are matched by event id (`FREE_EVENTS` in `client.py`), Reagents by the card's `Reagent` tag.
- Padlocks: allowed created cards, and cards not judged yet, get none in your stash.

## ⚠️ Unverified (needs a game session with the watcher)

- Whether a transform's new card is already on your board when its log line is read (the 10 s wait covers a delay).
- Fairy Statue (transforms when a fight ends): if its log line comes while the parser still says `ReplayState`, it's
  ignored as a fight transform (lenient).
- Pedestal results: if they make a new card with no log line, they're judged as spawns (never free under Special
  Cases).
- How Wink writes its transforms (one line per item is expected) and which of The Cult's cards get log lines.
- Random spawns (e.g. buying Alembic gives a Small Reagent): assumed to have no log line either.
