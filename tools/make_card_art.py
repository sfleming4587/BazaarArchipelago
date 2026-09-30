"""
Build card-art.zip, the Shop Guide's pictures (see bazaar/cardart.py), from the image set Bazaar DB's developer
gave this project: a zip (sent in parts; join them first) with Item/<card guid>_<name>.png at full size.

Each card in our data gets <guid>.webp at exactly the size the Shop Guide shows it (user 2026-09-30: no sharper
than that - a smaller download). Pillow is needed here only (the client never needs it). Then attach the result
to the GitHub release named in cardart.ART_SET:
    .venv/Scripts/python.exe tools/make_card_art.py path/to/images.zip card-art.zip
    gh release upload card-art-1 card-art.zip --repo sfleming4587/BazaarArchipelago
"""
import io
import json
import pathlib
import sys
import zipfile

from PIL import Image, ImageOps

ROOT = pathlib.Path(__file__).resolve().parent.parent
HEIGHT = 96  # the Shop Guide's card height (shop_guide.CARD_HEIGHT)
SLOTS = {"Small": 1, "Medium": 2, "Large": 3}  # half a card height wide per slot, as cardart.card_shape
QUALITY = 80  # WebP


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
            picture = Image.open(io.BytesIO(images.read(name))).convert("RGB")
            picture = ImageOps.fit(picture, size[guid], Image.LANCZOS)  # the card's in-game shape, centred
            webp = io.BytesIO()
            picture.save(webp, "WEBP", quality=QUALITY, method=6)
            out.writestr(f"{guid}.webp", webp.getvalue())  # stored: WebP doesn't compress further
            done.add(guid)
    missing = sorted(wanted[g] for g in set(wanted) - done)
    print(f"{len(done)} pictures written to {target}; no picture for {len(missing)}: {', '.join(missing)}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
