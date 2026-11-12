# Card packs

**A pack is one item that unlocks all of its cards at once; legacy packs come from the game, custom packs are ours.**

## Legacy packs (2026-09-30)

- **The ten original hero expansions, read by the extractor into `bazaar_data.json` (`packs`, ap_id 100..).**
  Option `legacy_card_packs` (off by default) plus one switch per pack (`pack_<key>`, on by default).

## Custom packs (owner, 2026-11-10)

- **14 hand-made packs in `bazaar/data/custom_packs.json`, ap_id 150..163, option `custom_card_packs`.**
  Three per DLC hero (Stelle, Jules, Karnok, The Dragons) plus one each for Mak and Dooley; Vanessa and Pygmalien keep
  their three legacy packs. Own option section "Custom Card Packs" with one switch per pack, like the legacy section.
- **Defaults (owner): on by default, off in Casual, on in Hardcore (with legacy packs).**
- **How cards were picked (owner rulings):** one build archetype per pack, "close to 10" cards, legacy-pack style
  (one centrepiece); strongest cards first - player guides (bazaar-builds.net, bazaardex), 10-win boards, then the
  bazaardb tier lists on unduel.com (S-B preferred, a lower card allowed when it fits the theme better). Cards the owner
  named (Aerial Turret, Gatling Gun, Battle Drone, Lightning Butterfly, Repair Drone) override the tier rule.
- **Swapped for being weak (owner OK):** Dooley's Friends pack -> Overclocked (PC parts); Stelle's Burn pack ->
  Tinkerer's Toolbox (Tools).

⚠️ **Why a separate file:** the extractor rewrites the `packs` list in `bazaar_data.json` from the game cache; custom
packs there would be wiped by the next data update.

⚠️ **Cards are keyed by guid; `name` is for reading only.** `test_custom_packs` fails if a name stops matching its
guid (a patch renamed or replaced the card) - re-check that pack by hand, never fix it by editing the name alone.

⚠️ **Rules the tests hold:** every card is its own hero's shop card; never Legendary (Legendary Items owns those) or a
ticket (Expedition Tickets); no card in two packs (legacy included), so both sections can be on together; a pack name
is never a card name (owner renamed "Stelle's Workshop" -> Tinkerer's Toolbox, and "Backstage Pass" -> Headliner since
Backstage Pass is a Dragons card); ap_ids append only, never reused.

⚠️ **The tier evidence is dated:** the 10-win boards are April-May 2026 (before Patch 20.0); the tier lists were read
2026-11-10. A big patch may make a pack weak - re-run the same pass then.

## Packs in logic (owner, 2026-11-10)

- **A pack counts as its 10 cards in the card logic** (`items.item_weight`), and 10 wins needs 2 of the hero's packs
  (fewer if the seed gives it fewer; `locations.WIN_PACKS`). Both go through `locations.check_needs` / `meets`, which
  the world's rules and the client's tracker share. ⚠️ Never count packs a second way anywhere else.
