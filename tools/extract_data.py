"""
Build bazaar/data/bazaar_data.json from The Bazaar's local card cache.

Owner, 2026-10-01: "re-extract the event data from the game files" - the 2026-09-29 freeze is lifted (Tempo's mod
policy is the only rulebook the owner counts). Run with --i-have-permission. It must not renumber anything: check
`git diff bazaar/data/bazaar_data.json` after every run.

Run this after a game patch (launch the game once first so its cache refreshes):
    python tools/extract_data.py

Archipelago ids are kept stable: cards already in the data file keep their ap_id,
new cards are appended. Never renumber existing entries - that would break
multiworlds generated with an older version of the apworld.
"""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bazaar" / "data" / "bazaar_data.json"
CACHE = Path(os.path.expandvars(r"%USERPROFILE%\AppData\LocalLow\Tempo Storm\The Bazaar"))
GAME_DB = CACHE / "prod" / "cache" / "GameData.db"
LEGACY_PACKS = CACHE / "cache" / "cardpacks.json"

# Game-internal hero names -> display names used by the apworld.
# Order matters for heroes: append only, never reorder (location ids depend on it).
HEROES = ["Vanessa", "Pygmalien", "Dooley", "Mak", "Stelle", "Jules", "Karnok", "The Dragons"]
HERO_ALIASES = {"Hero8": "The Dragons", "Dragons": "The Dragons", "Pyg": "Pygmalien", "Common": "Common"}

# The pre-Steam hero expansions. They were folded into the normal pools in patch 5.0.0,
# but their card lists survive in the old client cache. Localized pack names are buggy there.
LEGACY_PACK_NAMES = {
    "Vanessa_Mysteries_of_the_Deep": "Mysteries of the Deep",
    "Vanessa_The_Gang": "The Gang",
    "Vanessa_From_the_Shadows": "From the Shadows",
    "Pyg_Pigglestorm": "Pigglestorm",
    "Pyg_Investment_Opportunities": "Investment Opportunities",
    "Pyg_Frozen_Assets": "Frozen Assets",
    "Mak_Dangerous_Experiments": "Dangerous Experiments",
    "Mak_Lost_Treasures": "Lost Treasures",
    "Dooley_Primal_Dooley": "Primal Dooley",
    "Dooley_Dooltron": "Dooltron",
}

CARD_ID_START = 1000
PACK_ID_START = 100
ENCOUNTER_ID_START = 5000  # merchant/event lock items (item id = BASE + ap_id, like cards)
EXPEDITION = re.compile(r"^\[[^\]]*Expedition\]")  # the game's own InternalName prefix for an expedition's events


def item_deals(node):
    """Every TActionGameDealCards anywhere inside a card's data (abilities, nested actions, auras...)."""
    if isinstance(node, dict):
        if node.get("$type") == "TActionGameDealCards" and node.get("SpawnContext"):
            yield node
        for value in node.values():
            yield from item_deals(value)
    elif isinstance(node, list):
        for value in node:
            yield from item_deals(value)


def card_name(card: dict) -> str:
    title = ((card.get("Localization") or {}).get("Title") or {}).get("Text")
    return (title or card["InternalName"]).strip()


def hero_of(card: dict) -> str:
    heroes = card.get("Heroes") or ["Common"]
    hero = HERO_ALIASES.get(heroes[0], heroes[0])
    return hero


def main() -> None:
    if not GAME_DB.exists():
        sys.exit(f"Game database not found at {GAME_DB}. Launch The Bazaar once, then retry.")

    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"cards": [], "packs": []}
    old_encounter_ids = {e["name"]: e["ap_id"] for e in old.get("encounters", [])}
    old_card_ids = {c["guid"]: c["ap_id"] for c in old["cards"]}
    old_pack_ids = {p["key"]: p["ap_id"] for p in old["packs"]}
    next_card_id = max(old_card_ids.values(), default=CARD_ID_START - 1) + 1
    next_pack_id = max(old_pack_ids.values(), default=PACK_ID_START - 1) + 1

    # read-only + immutable: never lock, journal or modify the game's own database (safe even with the game open)
    db = sqlite3.connect(f"{GAME_DB.as_uri()}?mode=ro&immutable=1", uri=True)
    raw = {}
    # Encounters tagged Merchant: items taken inside them were bought, not rewarded. Their SpawnContext
    # describes what they can stock, which the client uses to warn about locked cards before you shop.
    merchants = []
    # Events and steps (level-up choices, "Enchanted item", ...) that hand you a choice of items.
    offers = []
    monsters = []  # hour-3 monster fights: tier = rarity shown in game (level is NOT the day it shows up)
    # Every event (merchants included): the choice-screen cards. Facts only - which are lockable is the world's call
    # (owner, 2026-10-01: merchant and event locks; "least rare" needs the tier).
    events = []
    # events a level-up hands you: never on the map, so never a merchant/event lock (owner, 2026-10-02)
    level_up = set(re.findall(r"[0-9a-f-]{36}", json.dumps([json.loads(d if isinstance(d, str) else d.decode("utf-8"))
                                                              for (d,) in db.execute("SELECT Data FROM level_ups")]).lower()))
    for (data,) in db.execute("SELECT Data FROM cards"):
        card = json.loads(data if isinstance(data, str) else data.decode("utf-8"))
        if card.get("Type") == "Item":
            raw[card["Id"]] = card
        elif card.get("Type") == "CombatEncounter" \
                and (card.get("CombatantType") or {}).get("$type") == "TCombatantMonster":
            monsters.append({"guid": card["Id"].lower(), "name": card_name(card), "tier": card.get("StartingTier"),
                             "level": (card.get("CombatantType") or {}).get("Level"),
                             "spawns": card.get("SpawningEligibility") == "Always"})
        if card.get("Type") == "EventEncounter":
            events.append({"guid": card["Id"].lower(), "name": card_name(card), "internal": card.get("InternalName"),
                           "tier": card.get("StartingTier"),
                           "heroes": [HERO_ALIASES.get(h, h) for h in card.get("Heroes") or ["Common"]],
                           "tags": sorted(card.get("Tags") or []), "spawns": card.get("SpawningEligibility"),
                           "level_up": card["Id"].lower() in level_up,
                           "expedition": bool(EXPEDITION.match(card.get("InternalName") or ""))})
        if card.get("Type") == "EventEncounter" and "Merchant" in (card.get("Tags") or []):
            merchants.append({"guid": card["Id"].lower(), "name": card_name(card),
                              "stock": (card.get("SelectionContext") or {}).get("SpawnContext")})
        elif card.get("Type") in ("EventEncounter", "EncounterStep", "PedestalEncounter"):  # (not a merchant)
            # Every deal that lays items out for you to take (pick one, pick several or leave them): the warning
            # lets you skip a locked one. Deals can sit anywhere - in an ability, nested in a TActionAnd (Hidden
            # Lake's "Fight the Beast"), and so on - so the whole card is searched. Direct grants
            # (TActionGameSpawnCards) give no choice; the "SELL IT NOW" alert covers those.
            contexts = [(card.get("SelectionContext") or {}).get("SpawnContext") or {}]
            contexts += [deal["SpawnContext"] for deal in item_deals({k: v for k, v in card.items()
                                                                       if k != "SelectionContext"})]
            # each group keeps its deal's behaviours (e.g. TSpawnBehaviorIgnoreHero: other heroes' cards too)
            groups = [{**group, "Behaviors": (group.get("Behaviors") or []) + (context.get("Behaviors") or [])}
                      for context in contexts for group in context.get("Groups") or []]
            if groups:
                offers.append({"guid": card["Id"].lower(), "name": card_name(card), "stock": {"Groups": groups}})

    def can_deal_items(stock: dict) -> bool:
        text = json.dumps(stock)
        return '"Item"' in text or any(guid in raw for guid in re.findall(r"[0-9a-f-]{36}", text))

    offers = [o for o in offers if can_deal_items(o["stock"])]

    legacy_packs = []
    if LEGACY_PACKS.exists():
        packs_json = json.loads(LEGACY_PACKS.read_text(encoding="utf-8"))
        for pack in next(iter(packs_json.values())):
            if pack["Id"] in LEGACY_PACK_NAMES:
                legacy_packs.append(pack)
    else:
        print(f"warning: {LEGACY_PACKS} missing, legacy packs keep their previous contents")

    pack_guids = {guid for p in legacy_packs for guid in p["Cards"]}
    wanted = {guid for guid, c in raw.items() if c.get("SpawningEligibility") == "Always"} | (pack_guids & raw.keys())
    # never drop a card that already has an id, even if Tempo made it unobtainable
    wanted |= old_card_ids.keys() & raw.keys()
    # Expedition tickets only come from events (never shops), but they're locked as their own group.
    tickets = {guid for guid, c in raw.items() if "Expedition Ticket" in (c.get("InternalName") or "")}
    wanted |= tickets

    unknown_heroes = set()
    cards = []
    for guid in sorted(wanted, key=lambda g: (old_card_ids.get(g, 10**9), card_name(raw[g]).lower())):
        card = raw[guid]
        hero = hero_of(card)
        if hero != "Common" and hero not in HEROES:
            unknown_heroes.add(hero)
        if guid not in old_card_ids:
            old_card_ids[guid] = next_card_id
            next_card_id += 1
        cards.append({
            "guid": guid,
            "ap_id": old_card_ids[guid],
            "name": card_name(card),
            "hero": hero,
            "tier": card.get("StartingTier"),
            "size": card.get("Size"),
            "tags": sorted(card.get("Tags") or []),
            "hidden_tags": sorted(card.get("HiddenTags") or []),
            "enchants": sorted(card.get("Enchantments") or {}),
            "tiers": sorted(card.get("Tiers") or {}),
            "shop": card.get("SpawningEligibility") == "Always",
            "ticket": guid in tickets,
        })
    # keep cards that vanished from the game so ids and names stay reserved
    known = {c["guid"] for c in cards}
    for c in old["cards"]:
        if c["guid"] not in known:
            cards.append({**c, "shop": False})

    # A card's name is its item's name (in YAMLs, hints, trackers), so a name once given never changes, and older
    # ids claim a plain name first. A clash gets the hero added, then the id, so no two cards ever share a name.
    old_names = {c["guid"]: c["name"] for c in old["cards"]}
    taken = set()
    for c in sorted(cards, key=lambda c: c["ap_id"]):
        name = old_names.get(c["guid"], c["name"])
        if name in taken:
            name = f'{name} ({c["hero"]})'
        if name in taken:
            name = f'{name} #{c["ap_id"]}'
        c["name"] = name
        taken.add(name)

    packs = []
    old_pack_by_key = {p["key"]: p for p in old["packs"]}
    for key, display in LEGACY_PACK_NAMES.items():
        source = next((p for p in legacy_packs if p["Id"] == key), None)
        if source is None and key not in old_pack_by_key:
            continue
        if key not in old_pack_ids:
            old_pack_ids[key] = next_pack_id
            next_pack_id += 1
        guids = source["Cards"] if source else old_pack_by_key[key]["cards"]
        hero = HERO_ALIASES.get(source["Hero"], source["Hero"]) if source else old_pack_by_key[key]["hero"]
        packs.append({"key": key, "ap_id": old_pack_ids[key], "name": display, "hero": hero,
                      "cards": [g for g in guids if g in known or g in old_card_ids]})

    # One lock item per merchant/event name, covering every template of it (Sharpening Kit has one per rarity).
    # Names group the templates here, once; everything after works on the guid lists. Expedition events are only
    # ever locked through the Expedition Tickets unlock. Ids are kept by name and never reused.
    lockable = {}
    for e in events:
        if not (e["level_up"] or e["expedition"] or e["spawns"] == "Never"):
            lockable.setdefault(e["name"], []).append(e["guid"])
    next_encounter_id = max(old_encounter_ids.values(), default=ENCOUNTER_ID_START - 1) + 1
    for name in sorted(lockable):
        if name not in old_encounter_ids:
            old_encounter_ids[name] = next_encounter_id
            next_encounter_id += 1
    merchant_guids = {m["guid"] for m in merchants}
    encounters = [{"ap_id": old_encounter_ids[name], "name": name, "guids": sorted(guids),
                   "merchant": any(g in merchant_guids for g in guids)} for name, guids in lockable.items()]
    gone = old_encounter_ids.keys() - lockable.keys()  # vanished from the game: keep the id and name reserved
    encounters += [e for e in old.get("encounters", []) if e["name"] in gone]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    versions = re.findall(r"\[VersionShow\]\s+Version: (\d+\.\d+\.\d+)", (CACHE / "Player.log").read_text(
        encoding="utf-8", errors="replace")) if (CACHE / "Player.log").exists() else []
    out = {"game_version": versions[-1] if versions else old.get("game_version", "unknown"),
           "heroes": HEROES, "cards": sorted(cards, key=lambda c: c["ap_id"]), "packs": packs,
           "merchants": sorted(merchants, key=lambda m: m["name"]),
           "offers": sorted(offers, key=lambda m: m["name"]),
           "monsters": sorted(monsters, key=lambda m: (m["level"] or 0, m["name"])),
           "events": sorted(events, key=lambda e: (e["name"], e["guid"])),
           "encounters": sorted(encounters, key=lambda e: e["ap_id"])}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    per_hero = {}
    for c in cards:
        if c["shop"]:
            per_hero[c["hero"]] = per_hero.get(c["hero"], 0) + 1
    print(f"wrote {OUT}: {len(cards)} cards, {len(packs)} packs, {len(out['merchants'])} merchants, "
          f"{len(out['offers'])} item choices, {len(out['monsters'])} monsters, {len(out['events'])} events, "
          f"{len(encounters)} lockable merchants/events")
    print("shop items per hero:", dict(sorted(per_hero.items())))
    if unknown_heroes:
        print(f"WARNING: unknown hero names {sorted(unknown_heroes)} - add them to HEROES/HERO_ALIASES")


if __name__ == "__main__":
    if "--i-have-permission" not in sys.argv:  # a deliberate step: see the docstring and docs/UPDATING-GAME-DATA.md
        sys.exit("Run with --i-have-permission (owner's go-ahead 2026-10-01); see docs/UPDATING-GAME-DATA.md.")
    main()
