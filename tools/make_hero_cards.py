"""
Cut the tracker's hero cards out of tools/art/Characters.png (the user's 4x2 screenshot of the hero select).

The cards are saved small (PNG) inside the world, so the tracker shows them with plain Tk - Archipelago's
Windows installer has no Pillow. Run after replacing the art:
    .venv/Scripts/python.exe tools/make_hero_cards.py
"""
import pathlib

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "art" / "Characters.png"
OUT = ROOT / "bazaar" / "data" / "heroes"
LAYOUT = [["Dooley", "Pygmalien", "Vanessa", "Mak"], ["Jules", "Karnok", "The Dragons", "Stelle"]]
WIDTH = 170  # pixels per card in the tracker


def slug(hero: str) -> str:
    return hero.lower().replace(" ", "_")


def main() -> None:
    image = Image.open(SOURCE).convert("RGBA")
    rgb = image.convert("RGB").load()
    gold = lambda p: p[0] > 170 and p[1] > 120 and p[2] < 90 and p[0] - p[2] > 100  # the cards' frames
    width, height = image.size
    OUT.mkdir(parents=True, exist_ok=True)
    for row, heroes in enumerate(LAYOUT):
        for column, hero in enumerate(heroes):
            x0, x1 = column * width // 4, (column + 1) * width // 4
            y0, y1 = row * height // 2, (row + 1) * height // 2
            xs = [x for x in range(x0, x1) if sum(gold(rgb[x, y]) for y in range(y0, y1, 2)) > 40]
            ys = [y for y in range(y0, y1) if sum(gold(rgb[x, y]) for x in range(x0, x1, 2)) > 40]
            box = (max(x0, min(xs) - 12), max(y0, min(ys) - 12), min(x1, max(xs) + 13), min(y1, max(ys) + 14))
            card = image.crop(box)
            card = card.resize((WIDTH, round(card.height * WIDTH / card.width)), Image.LANCZOS)
            card.save(OUT / f"{slug(hero)}.png", optimize=True)
            print(f"{hero}: {box} -> {card.size}")


if __name__ == "__main__":
    main()
