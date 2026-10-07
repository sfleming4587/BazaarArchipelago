"""
Build card-art.zip, the Shop Guide's pictures (see bazaar/cardart.py), from the image set Bazaar DB's developer
gave this project: a zip (sent in parts; join them first) with Item/<card guid>_<name>.png at full size.

Each card in our data gets <guid>.webp at exactly the size the Shop Guide shows it (user 2026-09-30: no sharper
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
HEIGHT = 96  # the Shop Guide's card height (shop_guide.CARD_HEIGHT)
SLOTS = {"Small": 1, "Medium": 2, "Large": 3}  # half a card height wide per slot, as cardart.card_shape
QUALITY = 80  # WebP


def webp_of(picture: Image.Image, size: tuple) -> bytes:
    picture = ImageOps.fit(picture.convert("RGB"), size, Image.LANCZOS)  # the card's in-game shape, centred
    webp = io.BytesIO()
    picture.save(webp, "WEBP", quality=QUALITY, method=6)
    return webp.getvalue()


def add(folder: str, target: str) -> None:
    """Add pictures named after cards (letters and digits only, any case) to the zip; existing ones are kept."""
    data = json.loads((ROOT / "bazaar" / "data" / "bazaar_data.json").read_text(encoding="utf-8"))
    norm = lambda name: re.sub(r"[^a-z0-9]", "", name.lower())
    cards = {norm(card["name"]): card for card in data["cards"]}
    with zipfile.ZipFile(target, "a", zipfile.ZIP_STORED) as out:
        have = set(out.namelist())
        for path in sorted(pathlib.Path(folder).glob("*.png")):
            card = cards.get(norm(path.stem))
            if not card:
                print(f"skipped {path.name}: no card by that name")
                continue
            if f"{card['guid']}.webp" in have:
                print(f"skipped {path.name}: {card['name']} already has a picture")
                continue
            size = (HEIGHT * SLOTS.get(card["size"], 2) // 2, HEIGHT)
            out.writestr(f"{card['guid']}.webp", webp_of(Image.open(path), size))
            print(f"added {card['name']}")


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
