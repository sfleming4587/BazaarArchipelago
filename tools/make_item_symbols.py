"""
A generic symbol for each item with no card behind it (owner, 2026-11-12: "Just make a generic symbol for each of
those" - Lock Bypass, Trap Shield, the trap, the buffs), added to bazaar/data/card-art.zip as item-<item id>.webp
beside the cards' and encounters' pictures. Drawn here (no outside art); one style: a dark rounded tile, one glyph
in the overlay's colours (bazaar/theme.py). Pillow is needed here only:
    .venv/Scripts/python.exe tools/make_item_symbols.py
"""
import io
import pathlib
import sys
import zipfile

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
THEME: dict = {}
exec((ROOT / "bazaar" / "theme.py").read_text(encoding="utf-8"), THEME)  # the colours only (the package needs AP)
ACCENT, BONE, FLAMES, GOOD, MUTED = (THEME[k] for k in ("ACCENT", "BONE", "FLAMES", "GOOD", "MUTED"))
SEVERITY, TRAP_BG, WINDOW_BG = THEME["SEVERITY"], THEME["TRAP_BG"], THEME["WINDOW_BG"]

ART = ROOT / "bazaar" / "data" / "card-art.zip"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_card_art import HEIGHT as SIZE  # noqa: E402  (shipped size, square: one size rule for every picture)
S = 384  # the drawings' grid (their coordinates are on it): drawn this big, shrunk once to SIZE (smooth edges)
# item id -> the symbol drawing it; ids are the apworld's, never changed (items.py)
ITEMS = {195166468: "lock_bypass", 195166478: "trap_shield", 195166458: "sell_trap",
         195166408: "spare_change", 195166409: "pile_of_trinkets", 195166410: "merchants_gossip"}


def tile(background: str) -> tuple:
    picture = Image.new("RGB", (S, S), WINDOW_BG)
    draw = ImageDraw.Draw(picture)
    draw.rounded_rectangle((8, 8, S - 8, S - 8), radius=48, fill=background, outline=ACCENT, width=10)
    return picture, draw


def lock_bypass():  # an open padlock: the lock no longer holds
    picture, d = tile(SEVERITY["ok"])
    d.arc((120, 50, 264, 194), 180, 360, fill=ACCENT, width=26)
    d.line((133, 122, 133, 165), fill=ACCENT, width=26)  # left leg down into the body; the right one is lifted out
    d.line((251, 122, 251, 90), fill=ACCENT, width=26)
    d.rounded_rectangle((96, 165, 288, 320), radius=22, fill=ACCENT)
    d.ellipse((176, 210, 208, 242), fill=SEVERITY["ok"])
    d.polygon(((184, 236), (200, 236), (206, 284), (178, 284)), fill=SEVERITY["ok"])
    return picture


def trap_shield():  # a shield with a check
    picture, d = tile(SEVERITY["info"])
    d.polygon(((192, 52), (318, 98), (306, 230), (192, 336), (78, 230), (66, 98)), fill=MUTED)
    d.polygon(((192, 82), (290, 118), (280, 222), (192, 304), (104, 222), (94, 118)), fill=SEVERITY["info"])
    d.line(((132, 196), (178, 244), (258, 148)), fill=GOOD, width=30, joint="curve")
    return picture


def sell_trap():  # the skull in flames, like the overlay's Sell Trap notice
    picture, d = tile(TRAP_BG)
    for i, (dark, mid, light) in enumerate(FLAMES):
        x = 96 + i * 96
        d.polygon(((x - 50, 330), (x - 30, 230), (x - 8, 270), (x, 150), (x + 12, 260), (x + 34, 220), (x + 50, 330)),
                  fill=(dark, mid, light)[i % 3])
    d.ellipse((112, 70, 272, 220), fill=BONE)
    d.rounded_rectangle((146, 190, 238, 262), radius=14, fill=BONE)
    d.ellipse((140, 120, 182, 162), fill=TRAP_BG)
    d.ellipse((202, 120, 244, 162), fill=TRAP_BG)
    d.polygon(((192, 168), (180, 192), (204, 192)), fill=TRAP_BG)
    for x in (166, 192, 218):
        d.line((x, 226, x, 262), fill=TRAP_BG, width=8)
    return picture


def spare_change():  # a short stack of coins
    picture, d = tile(SEVERITY["warning"])
    for i, y in enumerate((270, 228, 186, 144)):
        d.ellipse((112, y, 272, y + 56), fill="#b8860b", outline="#7a5806", width=6)
        d.ellipse((112, y - 10, 272, y + 46), fill=ACCENT, outline="#7a5806", width=6)
    return picture


def pile_of_trinkets():  # a small heap of gems
    picture, d = tile(SEVERITY["info"])
    gems = (((108, 290), "#e0303a"), ((192, 300), "#3aa0ff"), ((276, 290), GOOD), ((150, 210), ACCENT), ((234, 210), "#c77dff"),
            ((192, 135), MUTED))
    for (x, y), colour in gems:
        d.polygon(((x, y - 54), (x + 48, y - 18), (x, y + 40), (x - 48, y - 18)), fill=colour, outline=WINDOW_BG)
        d.polygon(((x, y - 54), (x + 20, y - 18), (x, y + 40), (x - 20, y - 18)), outline=WINDOW_BG)
    return picture


def merchants_gossip():  # a speech bubble with three dots
    picture, d = tile(SEVERITY["info"])
    d.rounded_rectangle((70, 90, 314, 262), radius=60, fill=MUTED)
    d.polygon(((130, 250), (110, 320), (190, 255)), fill=MUTED)
    for x in (132, 192, 252):
        d.ellipse((x - 20, 156, x + 20, 196), fill=SEVERITY["info"])
    return picture


def main() -> None:
    with zipfile.ZipFile(ART) as old:
        pictures = {name: old.read(name) for name in old.namelist()}
    for item, drawing in ITEMS.items():
        buffer = io.BytesIO()
        globals()[drawing]().resize((SIZE, SIZE), Image.LANCZOS).save(buffer, "WEBP", quality=90, method=6)
        pictures[f"item-{item}.webp"] = buffer.getvalue()
    with zipfile.ZipFile(ART, "w", zipfile.ZIP_STORED) as out:
        for name in sorted(pictures):
            out.writestr(name, pictures[name])
    print(f"{len(ITEMS)} item symbols written to {ART}")


if __name__ == "__main__":
    main()
