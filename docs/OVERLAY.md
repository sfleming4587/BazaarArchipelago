# The overlay - what shows where, and why

**Everything the client shows over the game lives in two columns beside the board, plus padlocks on the cards
themselves; nothing ever covers the board except the padlocks, and they let every click through.** Owner's rules
(2026-09-28 to 2026-10-01): only beside the board, never overlapping each other, never off screen, text at least
10 px, only while The Bazaar is the active window, never taking the keyboard from the game, silent redraws.

Code: `bazaar/overlay.py` (layout, fading, padlocks), `bazaar/shop_guide.py` (the guide), `bazaar/tracker.py`.
The information comes from `Player.log` and the game's memory (`bazaar/memreader.py`, `docs/MEMORY-READER.md`).

## Layout (owner, 2026-10-01: "The shop guide is always going to be the whole left column")

```
+------------------+----------------------------------------+------------------+
| HEADER           |                                        | NOTICES          |
| status + buttons |                                        | DeathLink,       |
+------------------+          the game's board              | held locked      |
| SHOP GUIDE       |     (padlocks sit on locked cards)     | cards, traps     |
|  On offer now    |                                        +------------------+
|  You can buy     |                                        |                  |
|  LOCKED          |                                        |                  |
|  filters on top  |                                        |                  |
|                  |                                        | POP-UPS (bottom) |
+------------------+----------------------------------------+------------------+
```

| Window | Where | Shows | Comes from |
|---|---|---|---|
| Header | top of the left column | run progress ("Vanessa day 4, 8 checks left"), or on the menu the heroes you may pick; buttons: Shop Guide / Hide guide, Tracker, Hide heroes (menu) | the server's items and checks; the log's hero pick |
| Shop Guide | the rest of the left column (until you drag it elsewhere) | **On offer now** (gold frames): the cards on screen right now; under it what the chosen merchant could stock for your hero, allowed first or locked first (the shorter part on top); Search, Size, Rarity and Merchant filters | memory (what's on offer, any screen); the game data (what a merchant can stock) |
| Notices | top of the right column | DEATHLINK (with Done); "CHECKS ARE BLOCKED" and each locked card you hold, with Use Bypass when one is ready; Sell Traps, drawn as a skull in flickering flames (also on the trap's pop-up; owner 2026-10-01: "more menacing") | the log (cards gained/sold/transformed), the server (DeathLink, traps, bypasses) |
| Pop-ups | bottom of the right column | items received and sent, unlocks | the server |
| Padlocks | on the locked cards themselves | a red padlock on each locked card offered (shops, level-ups, single-card loot, events' items) and in your open stash | memory |
| Tracker | its own window, anywhere | each hero's checks | the server |
| Menu panel | centre of the game window, only on the menu (no run) | every hero in the multiworld as a tile: card, a bar of checks done (gold) and ready (green), "14/52 (9 ready)"; locked heroes dimmed with a padlock; your pick framed gold, or red with a banner when it's locked or Random; the goal and Lock Bypasses | the log's hero pick ("Changing EHero to X"), the server |

The menu panel is the one exception to "only beside the board" (owner, 2026-10-01: "put it in the center of the
screen"): there's no board on the menu, and it's click-through so it can never block the menu's buttons. Random
always warns - it can roll a locked hero, or one not in this multiworld. ⚠️ The log's exact text for Random hasn't
been seen yet; any name that isn't a known hero is treated as Random.

Random itself comes from memory (your character-select settings: Random on/off and the heroes you excluded), so the
warning names the heroes Random could roll that are locked or not in the multiworld, or says Random is safe. Each
tile shows the checks you've got with that hero and "Cards X / Y" (their cards unlocked of all of them).

**The panel only shows while none of the game's own screens is open over the menu** - settings, the stores, chests,
character select, MENU, anything: the game keeps a stack of input layers (`InputManager.Context`) and every one of
those screens pushes "Modal" onto it while it's open (watched with the owner 2026-10-01). One generic rule, no
per-screen lists (owner: "I want a generic solution ... simple is a priority"). A click-detection version came first
and was dropped for this. If the stack can't be read (a patch), the panel just stays visible; the header's "Hide
heroes" / "Show heroes" is the fallback. It also steps aside while the Tracker window overlaps it (owner, 2026-10-01: they
shouldn't sit on top of each other): the Tracker opens in the middle of the screen too and shows the same checks;
drag the Tracker off the panel, or close it, and the panel comes back.

**No locked-card list** (owner, 2026-10-01: "as long as we can put a lock on the card in the event correctly ...
there is no need for that overlay"): a list in the right column used to name the locked cards a shop or event
offered; the padlocks on the cards say the same, so it went. ⚠️ Without memory (a patch the reader doesn't match)
there are no padlocks, so the only shop warnings left are the Shop Guide's LOCKED section and, after a purchase, the
"CHECKS ARE BLOCKED" notice. The client's log file still records the locked cards each shop offers.

**Not connected:** while the client has no connection to the multiworld, the header says so in red - "NOT CONNECTED
... click Connect at the top of the Bazaar Client (or type /connect)" (owner, 2026-10-01).

## When things show, fade or hide

Every overlay window follows the same rules as the padlocks (owner, 2026-10-01: "infact the entire overlay should
follow those rules"), from the game's own flags in memory:

| The game | The overlay |
|---|---|
| a card's tooltip is showing, or you're dragging a card | 30% see-through |
| the Esc menu or a dialog is open | hidden (not just see-through: an invisible window would still catch clicks) |
| your stash is sliding open or shut | hidden; once open, padlocks move onto the stash's own locked cards |
| new cards are flipping over | their padlocks wait until the flip ends |
| you click away from The Bazaar | everything hides; it comes back when you click into the game |

If those flags can't be read (a game patch), padlocks fall back to the mouse's position and a fixed 1 s wait, and
the other windows simply stay visible.

The Shop Guide opens and closes with one button (and its X) with a short fade. Typing in its Search box takes the
keyboard only while you type; Enter, Esc or clicking away gives it back to the game.

## Example

Day 4 with Vanessa. You walk into Valpak, which offers Beach Ball, Fishing Net and Pearl; Beach Ball and Pearl are
locked, and you're holding a locked Volcanic Vents from an event:

- **Header:** "Vanessa day 4 - 8 checks left this run" with [Hide guide] [Tracker].
- **Shop Guide:** title "Valpak | Valpak: 2 locked of 41". On offer now: Beach Ball (red cross), Fishing Net,
  Pearl (red cross). Below: the 41 cards Valpak could stock for Vanessa, locked ones under "LOCKED - don't buy".
- **Notices:** red box, "CHECKS ARE BLOCKED until you sell: Volcanic Vents" (and [Use Bypass] if you have one).
- **Padlocks:** on Beach Ball and Pearl, a second after the cards flip over.
- You hover Fishing Net: its tooltip shows and the whole overlay drops to 30%. You buy it: only "On offer now"
  redraws; the padlocks stay put (cards don't slide). You press Esc: everything hides until the menu closes.

## Traps

- ⚠️ Positions are measured at 1080p, 16:9 (`docs/MEMORY-READER.md`); 1440p, 16:10 and 21:9 are untested.
- ⚠️ Each picture tile in the guide is a window of its own to Windows; rebuilding ~300 of them on every purchase
  crashed Tk (2026-10-01). The guide only redraws the section that changed - keep it that way.
- ⚠️ Any new overlay window must join `own_windows()` (or the overlay hides itself when you use it) and the fade
  (`faded_windows()`), and must not overlap the others (check with EnumWindows, as in the layout check above).
