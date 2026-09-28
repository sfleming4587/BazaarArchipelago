"""
Build bazaar/data/bazaar_data.json from The Bazaar's local card cache.

Run this after a game patch (launch the game once first so its cache refreshes):
    python tools/extract_data.py

Archipelago ids are kept stable: cards already in the data file keep their ap_id,
new cards are appended. Never renumber existing entries - that would break
multiworlds generated with an older version of the apworld.
"""
import json
import os
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
    old_card_ids = {c["guid"]: c["ap_id"] for c in old["cards"]}
    old_pack_ids = {p["key"]: p["ap_id"] for p in old["packs"]}
    next_card_id = max(old_card_ids.values(), default=CARD_ID_START - 1) + 1
    next_pack_id = max(old_pack_ids.values(), default=PACK_ID_START - 1) + 1

    db = sqlite3.connect(GAME_DB)
    raw = {}
    for (data,) in db.execute("SELECT Data FROM cards"):
        card = json.loads(data if isinstance(data, str) else data.decode("utf-8"))
        if card.get("Type") == "Item":
            raw[card["Id"]] = card

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
            "shop": card.get("SpawningEligibility") == "Always",
        })
    # keep cards that vanished from the game so ids and names stay reserved
    known = {c["guid"] for c in cards}
    for c in old["cards"]:
        if c["guid"] not in known:
            cards.append({**c, "shop": False})

    names = {}
    for c in cards:
        if c["name"] in names:
            c["name"] = f'{c["name"]} ({c["hero"]})'
        names[c["name"]] = c["guid"]

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

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = {"heroes": HEROES, "cards": sorted(cards, key=lambda c: c["ap_id"]), "packs": packs}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    per_hero = {}
    for c in cards:
        if c["shop"]:
            per_hero[c["hero"]] = per_hero.get(c["hero"], 0) + 1
    print(f"wrote {OUT}: {len(cards)} cards, {len(packs)} packs")
    print("shop items per hero:", dict(sorted(per_hero.items())))
    if unknown_heroes:
        print(f"WARNING: unknown hero names {sorted(unknown_heroes)} - add them to HEROES/HERO_ALIASES")


if __name__ == "__main__":
    main()
