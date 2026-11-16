"""
The Tracker's square icons and the Sell Trap card marker (owner, 2026-11-16: "a shade darker than the background of
the squares color and kind of like a shadow of what it is supposed to be"; the Sell Trap: "the skull with flames").
Silhouettes from game-icons.net (CC BY 3.0, credited in README.md and in the data file), kept in tools/icons/. Each is
filled (SVG's nonzero rule) on a MASK x MASK grid and written as a see-through mask to bazaar/data/icons.json; the
client tints it per square colour (tracker.icon_image). Pillow is needed here only:
    .venv/Scripts/python.exe tools/make_tracker_icons.py            # writes the data file
    .venv/Scripts/python.exe tools/make_tracker_icons.py --preview  # every candidate on every square colour
"""
import base64
import json
import math
import pathlib
import re
import sys
import zlib

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = pathlib.Path(__file__).resolve().parent / "icons"
OUT = ROOT / "bazaar" / "data" / "icons.json"
MASK = 64  # px: the shipped mask (the client shrinks it to the square)
SUPER = 4  # filled at MASK * SUPER, then averaged down: smooth edges
CURVE_STEPS = 16  # straight pieces per curve or arc
# what each icon stands for -> its game-icons.net name (one line to swap one)
CHOSEN = {"day": "sunrise", "pvp": "sword-clash", "monster": "snake-tongue", "win": "trophy",
          "sell_trap": "burning-skull"}
# every source's author (its page: https://game-icons.net/1x1/<author>/<name>.html, checked 2026-11-16)
AUTHORS = {"crossed-swords": "Lorc", "sword-clash": "Lorc", "sunrise": "Lorc", "sunset": "Delapouite",
           "snake-bite": "Lorc", "snake-tongue": "Delapouite", "rattlesnake": "Delapouite", "croc-jaws": "Lorc",
           "trophy": "Lorc", "trophy-cup": "Delapouite", "laurels-trophy": "Delapouite", "burning-skull": "Skoll"}
SQUARE_COLORS = {"green": "#3fbf4f", "yellow": "#e8c53a", "red": "#d9443b", "done": "#6f6f6f"}  # tracker.COLORS
SHADE = 0.6  # the icon: its square's colour at this brightness (tracker.ICON_SHADE)

TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


def arc_points(x0, y0, rx, ry, angle, large, sweep, x1, y1):
    """An SVG arc as points (the spec's endpoint-to-centre conversion, F.6.5)."""
    if rx == 0 or ry == 0:
        return [(x1, y1)]
    rx, ry, phi = abs(rx), abs(ry), math.radians(angle)
    cos, sin = math.cos(phi), math.sin(phi)
    dx, dy = (x0 - x1) / 2, (y0 - y1) / 2
    x_, y_ = cos * dx + sin * dy, -sin * dx + cos * dy
    scale = x_ ** 2 / rx ** 2 + y_ ** 2 / ry ** 2
    if scale > 1:
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    num = rx ** 2 * ry ** 2 - rx ** 2 * y_ ** 2 - ry ** 2 * x_ ** 2
    coef = math.sqrt(max(0.0, num / (rx ** 2 * y_ ** 2 + ry ** 2 * x_ ** 2))) * (-1 if large == sweep else 1)
    cx_, cy_ = coef * rx * y_ / ry, -coef * ry * x_ / rx
    cx, cy = cos * cx_ - sin * cy_ + (x0 + x1) / 2, sin * cx_ + cos * cy_ + (y0 + y1) / 2

    def angle_of(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    start = angle_of(1, 0, (x_ - cx_) / rx, (y_ - cy_) / ry)
    delta = angle_of((x_ - cx_) / rx, (y_ - cy_) / ry, (-x_ - cx_) / rx, (-y_ - cy_) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    out = []
    for i in range(1, CURVE_STEPS + 1):
        t = start + delta * i / CURVE_STEPS
        px, py = rx * math.cos(t), ry * math.sin(t)
        out.append((cos * px - sin * py + cx, sin * px + cos * py + cy))
    return out


def bezier(points, steps=CURVE_STEPS):
    """A quadratic or cubic Bezier's points after its start (de Casteljau)."""
    out = []
    for i in range(1, steps + 1):
        t, level = i / steps, list(points)
        while len(level) > 1:
            level = [(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t) for a, b in zip(level, level[1:])]
        out.append(level[0])
    return out


def outlines(d: str):
    """An SVG path's subpaths as closed point lists."""
    tokens, i = TOKEN.findall(d), 0
    shapes, shape, x, y, start, command, last_control = [], [], 0.0, 0.0, (0.0, 0.0), "M", None
    while i < len(tokens):
        if tokens[i].isalpha():
            command, i = tokens[i], i + 1
        upper, relative = command.upper(), command.islower()
        if upper == "Z":
            if shape:
                shapes.append(shape)
            shape, (x, y), last_control = [], start, None
            continue
        values = [float(v) for v in tokens[i:i + ARGS[upper]]]
        i += ARGS[upper]
        ox, oy = (x, y) if relative else (0.0, 0.0)
        control = None
        if upper == "M":
            if shape:
                shapes.append(shape)
            x, y = values[0] + ox, values[1] + oy
            start, shape = (x, y), [(x, y)]
            command = "l" if relative else "L"  # pairs after a move are lines
        elif upper == "L":
            x, y = values[0] + ox, values[1] + oy
            shape.append((x, y))
        elif upper == "H":
            x = values[0] + (x if relative else 0.0)
            shape.append((x, y))
        elif upper == "V":
            y = values[0] + (y if relative else 0.0)
            shape.append((x, y))
        elif upper in "CS":
            if upper == "C":
                c1 = (values[0] + ox, values[1] + oy)
                c2, end = (values[2] + ox, values[3] + oy), (values[4] + ox, values[5] + oy)
            else:
                c1 = (2 * x - last_control[0], 2 * y - last_control[1]) if last_control and last_control[2] == "C" \
                    else (x, y)
                c2, end = (values[0] + ox, values[1] + oy), (values[2] + ox, values[3] + oy)
            shape += bezier([(x, y), c1, c2, end])
            control, (x, y) = (c2[0], c2[1], "C"), end
        elif upper in "QT":
            if upper == "Q":
                c1, end = (values[0] + ox, values[1] + oy), (values[2] + ox, values[3] + oy)
            else:
                c1 = (2 * x - last_control[0], 2 * y - last_control[1]) if last_control and last_control[2] == "Q" \
                    else (x, y)
                end = (values[0] + ox, values[1] + oy)
            shape += bezier([(x, y), c1, end])
            control, (x, y) = (c1[0], c1[1], "Q"), end
        elif upper == "A":
            end = (values[5] + ox, values[6] + oy)
            shape += arc_points(x, y, values[0], values[1], values[2], int(values[3]), int(values[4]), *end)
            x, y = end
        last_control = control
    if shape:
        shapes.append(shape)
    return shapes


def mask(svg: str) -> bytes:
    """The icon filled (nonzero, SVG's default) on a MASK x MASK grid: one see-through byte per pixel."""
    box = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg)[1].split()]
    size = MASK * SUPER
    scale = size / max(box[2], box[3])
    edges = []
    for d in re.findall(r'\sd="([^"]+)"', svg):
        for shape in outlines(d):
            pts = [((px - box[0]) * scale, (py - box[1]) * scale) for px, py in shape]
            for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
                if ay != by:
                    edges.append((ax, ay, bx, by, 1 if by > ay else -1))
    big = bytearray(size * size)
    for row in range(size):
        sy = row + 0.5
        crossings = sorted((ax + (sy - ay) * (bx - ax) / (by - ay), w) for ax, ay, bx, by, w in edges
                           if min(ay, by) <= sy < max(ay, by))
        winding = 0
        for (x0, w), (x1, _w) in zip(crossings, crossings[1:] + [(0, 0)]):
            winding += w
            if winding:
                for col in range(max(0, round(x0)), min(size, round(x1))):
                    big[row * size + col] = 255
    return Image.frombytes("L", (size, size), bytes(big)).resize((MASK, MASK), Image.BOX).tobytes()


def tinted(alpha: bytes, colour: str) -> Image.Image:
    rgb = tuple(int(int(colour[i:i + 2], 16) * SHADE) for i in (1, 3, 5))
    image = Image.new("RGBA", (MASK, MASK), colour)
    shadow = Image.new("RGBA", (MASK, MASK), rgb + (255,))
    image.paste(shadow, (0, 0), Image.frombytes("L", (MASK, MASK), alpha))
    return image


def preview(path: pathlib.Path) -> None:
    """Every candidate on every square colour, one row each (for the owner to pick)."""
    names = sorted(AUTHORS)
    cell = MASK + 8
    sheet = Image.new("RGBA", (cell * len(SQUARE_COLORS), cell * len(names)), "#151318")
    for r, name in enumerate(names):
        alpha = mask((SOURCES / f"{name}.svg").read_text(encoding="utf-8"))
        for c, colour in enumerate(SQUARE_COLORS.values()):
            sheet.paste(tinted(alpha, colour), (c * cell + 4, r * cell + 4))
    sheet.save(path)
    print("preview:", path, "rows:", ", ".join(names))


def main() -> None:
    if "--preview" in sys.argv:
        preview(pathlib.Path(sys.argv[sys.argv.index("--preview") + 1]))
        return
    icons = {kind: base64.b64encode(zlib.compress(mask((SOURCES / f"{name}.svg").read_text(encoding="utf-8"))))
             .decode() for kind, name in CHOSEN.items()}
    credits = {kind: f"{name} by {AUTHORS[name]} (https://game-icons.net, CC BY 3.0)" for kind, name in CHOSEN.items()}
    OUT.write_text(json.dumps({"size": MASK, "credits": credits, "icons": icons}, indent=1) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
