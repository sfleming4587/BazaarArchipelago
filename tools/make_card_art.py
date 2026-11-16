"""
Build card-art.zip, the Item Guide's pictures (see bazaar/cardart.py), from the image set Bazaar DB's developer
gave this project: a zip (sent in parts; join them first) with Item/<card guid>_<name>.png at full size.

Each card in our data gets <guid>.webp at exactly the size the Item Guide shows it (user 2026-09-30: no sharper
than that - a smaller apworld). Pillow is needed here only (the client never needs it). The result ships inside the
apworld; for a new set, also bump cardart.ART_SET:
    .venv/Scripts/python.exe tools/make_card_art.py path/to/images.zip bazaar/data/card-art.zip
Cards a patch added can be added to the existing zip from a folder of pictures named after the cards (e.g.
"SodaMachine.png", from Tempo's patch notes, owner 2026-10-07); bump ART_SET then too:
    .venv/Scripts/python.exe tools/make_card_art.py --add path/to/folder bazaar/data/card-art.zip
"""
import io
import json
import pathlib
import re
import sys
import zipfile

from PIL import Image, ImageOps

ROOT = pathlib.Path(__file__).resolve().parent.parent
HEIGHT = 192  # every picture's height as shipped: twice the Item Guide's (shop_guide.CARD_HEIGHT), so every size the
# client draws - the guide's 96, pop-ups up to ~160 - is made by shrinking, never by stretching (owner 2026-11-12:
# "Can the pictures have a few more pixels? They look choppy"; was 96)
SLOTS = {"Small": 1, "Medium": 2, "Large": 3}  # half a card height wide per slot, as cardart.card_shape
QUALITY = 80  # WebP
FLAT = 0.2  # one exact colour covering this share of a picture... (see blank): the 12 blanks 0.26-0.97
FEW_COLOURS = 1000  # ...with fewer distinct colours than this makes it a blank box: the 12 blanks had at most 463,
# real card art at least 2,631 (all 1,180 pictures, 2026-11-12); encounter art can have a flat border (Fortis 0.23)


def blank(picture: Image.Image) -> bool:
    """Mostly one flat colour and little else: what a source gives when its image failed to load. 12 cards shipped as tier-coloured boxes
    with their name in tiny print until 2026-11-12 (Ancient Specimen and the Crash Site cards; owner's report)."""
    rgb = picture.convert("RGB")
    colours = rgb.getcolors(rgb.width * rgb.height)
    return len(colours) < FEW_COLOURS and max(count for count, _ in colours) >= FLAT * rgb.width * rgb.height


def webp_of(picture: Image.Image, size: tuple) -> bytes:
    if blank(picture):
        raise ValueError("a blank picture (one flat colour) - get the card's real art")
    picture = ImageOps.fit(picture.convert("RGB"), size, Image.LANCZOS)  # the card's in-game shape, centred
    webp = io.BytesIO()
    picture.save(webp, "WEBP", quality=QUALITY, method=6)
    return webp.getvalue()


def add(folder: str, target: str) -> None:
    """Add pictures named after cards (letters and digits only, any case) to the zip. A card's existing picture is
    kept unless it's blank (see blank): then the new one replaces it."""
    data = json.loads((ROOT / "bazaar" / "data" / "bazaar_data.json").read_text(encoding="utf-8"))
    norm = lambda name: re.sub(r"[^a-z0-9]", "", name.lower())
    cards = {norm(card["name"]): card for card in data["cards"]}
    with zipfile.ZipFile(target) as old:
        pictures = {name: old.read(name) for name in old.namelist()}
    for path in sorted(p for p in pathlib.Path(folder).iterdir() if p.suffix.lower() in (".png", ".webp")):
        card = cards.get(norm(path.stem))
        if not card:
            print(f"skipped {path.name}: no card by that name")
            continue
        name = f"{card['guid']}.webp"
        if name in pictures and not blank(Image.open(io.BytesIO(pictures[name]))):
            print(f"skipped {path.name}: {card['name']} already has a picture")
            continue
        size = (HEIGHT * SLOTS.get(card["size"], 2) // 2, HEIGHT)
        how = "replaced the blank picture of" if name in pictures else "added"
        pictures[name] = webp_of(Image.open(path), size)
        print(f"{how} {card['name']}")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as out:  # rewritten: a zip can't replace an entry
        for name in sorted(pictures):
            out.writestr(name, pictures[name])


def main(source: str, target: str) -> None:
    data = json.loads((ROOT / "bazaar" / "data" / "bazaar_data.json").read_text(encoding="utf-8"))
    wanted = {card["guid"]: card["name"] for card in data["cards"]}
    size = {card["guid"]: (HEIGHT * SLOTS.get(card["size"], 2) // 2, HEIGHT) for card in data["cards"]}
    done = set()
    with zipfile.ZipFile(source) as images, zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as out:
        for name in sorted(images.namelist()):
            guid = name[len("Item/"):][:36]
            if not name.startswith("Item/") or not name.endswith(".png") or guid not in wanted or guid in done:
                continue
            # stored: WebP doesn't compress further
            out.writestr(f"{guid}.webp", webp_of(Image.open(io.BytesIO(images.read(name))), size[guid]))
            done.add(guid)
    missing = sorted(wanted[g] for g in set(wanted) - done)
    print(f"{len(done)} pictures written to {target}; no picture for {len(missing)}: {', '.join(missing)}")


if __name__ == "__main__":
    if sys.argv[1] == "--add":
        add(*sys.argv[2:4])
    else:
        main(*sys.argv[1:3])
