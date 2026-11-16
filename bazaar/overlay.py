"""
Windows shown above The Bazaar: the alert box, the locked-card list, pop-ups, the Item Guide and the tracker.

They're separate windows owned by the client; they never draw inside the game or touch its process. They show over
the game when it runs borderless (the default "Fullscreen Window") or windowed, not over exclusive fullscreen.
Tk runs in its own thread; the client only talks to it through the command queue (the Overlay methods).

Rules (user, 2026-09-28/29): beside the board, never on it; never overlapping each other; never off screen;
only while the game is the active window; never taking the keyboard from the game; redrawing only what changed.
"""
import colorsys
import json
import logging
import queue
import sys
import threading
import time
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

from . import follower, padlocks, screens
from .padlocks import Padlock
from .data import HEROES
from .shop_guide import ShopGuide
from .theme import (ACCENT, BONE, DIM, FG, FLAMES, FONT, LOCKED_X, MUTED, OUTLINE, SEVERITY, TRAP_BG, TRAP_TITLE,
                    WARN)
from .tracker import Tracker, check_bar

logger = logging.getLogger("Client")
FILE_ONLY = {"NoStream": True, "skip_gui": True}  # to the client's log file, not its window

# see-through enough to read the game's tooltips behind (the list lets the mouse through, so they do show)
ALERT_ALPHA = 0.8

# Where the overlay may draw: the strips left and right of the board, measured on a 1920x1080 shop screenshot
# (2026-09-28). It must never cover the board: the overlay takes the clicks where it sits, and a list over the
# board once stopped the player leaving a shop. Measured in 1080p pixels and scaled to the game window's real
# size, so it works at any resolution, windowed or fullscreen, on any monitor.
MARGIN = 14  # from the window's left and right edges
LEFT_END = 960 - 363  # the left strip ends this far left of the window's centre (the board starts there)
RIGHT_START = 1565 - 960  # the right strip starts this far right of the centre
LEFT_BOTTOM = 1056
RIGHT_BOTTOM = 950  # above the settings gear in the bottom-right corner

MIN_FONT = 10  # never smaller than this many real pixels, however small the window (user rule: text >= 10 px)
POINT_TO_PX = 4 / 3  # Tk points to pixels at 96 dpi (the overlay's other text is sized in points)
PAD = 10  # inside every panel
BORDER = 2  # every panel's gold border
WINDOW_GAP = 4  # between two panels that sit on top of each other
ALERT_SHARE = 2  # the alert box takes at most 1/2 of the left strip (the rest is the list's)
MAX_ALERT_LINES = 6  # held cards / trap lines shown in it; more become "+ N more" (review 2026-09-30)
# Pop-ups (owner, 2026-11-12): one at a time, over your hero portrait and skills (memreader.BoardUI.toast_strip), a
# header and up to two rows of pictures - ALL of an unlock's, never "+ N more" - at a fixed height; wider when they
# need it, out to the game window's edges. A queue: each shows TOAST_SECONDS, faster the more are waiting.
TOAST_ROW = 60  # the smallest picture height at 1080p: the box holds a header + 2 rows of these (between the health
# bar and the board's bottom); fewer pictures get bigger, up to one row filling it (owner 2026-11-12: "cards could've
# filled more of the overlay"). Picture heights come from TOAST_SIZES (times TOAST_ROW), so few sizes are ever made
TOAST_SIZES = (2.0, 1.8, 1.6, 1.45, 1.3, 1.2, 1.1, 1.0, 0.8, 0.6, 0.4)  # ~10% apart
TOAST_TALL = 1.3  # pictures smaller than this (times TOAST_ROW) in the resting box: the box reaches down to the game
# window's bottom instead, same top (owner 2026-11-12: "if they need to go 'Taller' you go to the bottom of the screen")
TOAST_HEADER = 12  # the header's font size
TOAST_GAP = 4  # between pictures and rows
TOAST_TALL_ROWS = 6  # rows of pictures at most once the box reaches the window's bottom (2 in the resting box)
TOAST_SECONDS = (3.0, 1.0, 10)  # alone 3 s ... 1 s with this many waiting (the one showing included) (owner 2026-11-12)
HERO_WARM_MS, HERO_WARM_STEP_MS = 2000, 50  # the heroes' cards decoded ahead: from 2 s after start, one per 50 ms
COMMAND_BUDGET = 0.008  # seconds of queued commands one round handles: 2,350 "picture ready" commands in one round
# froze the overlay ~190 ms while the pictures were read at start (measured 2026-11-12); the rest go next round
TOAST_WAIT = 2.0  # a pop-up waits for its pictures up to this long before it shows anyway (owner 2026-11-12: "do not
# display until all UI elements are ready"; a picture that never comes mustn't stall the queue)
TOAST_RAINBOW_SECONDS = 6.0  # a rainbow one, however many wait (owner 2026-11-12: "maybe 6 seconds"; was 3)
MENU_WIDTH = 460  # the menu's centre panel, 1080p pixels (scaled with the window)
MENU_TILE = 100  # one hero's tile
MENU_COLUMNS = 4  # heroes per row, like the hero select
POLL_MS = 250

FLICKER_MS = 140  # the Sell Trap's flames
# A good unlock's pop-up (a pack, a hero, a group, a merchant/event, Event Rarity Progression): a soft rainbow that
# drifts over the usual green (owner, 2026-11-11: "just an opaque rainbow over the green background of the normal
# toast. Nothing crazy but something noticeable too")
RAINBOW_TINT = 0.3  # how much of each rainbow colour is mixed into the green
RAINBOW_BANDS = 24  # colour bands across the pop-up, one whole rainbow from left to right
RAINBOW_MS = 60  # the rainbow moves one band this often
# A flame's outline, as fractions of the skull's square (x right, y down); the inner flames are it shrunk upward.
FLAME = ((0.10, 1.0), (0.02, 0.55), (0.17, 0.30), (0.23, 0.46), (0.30, 0.10), (0.41, 0.36), (0.50, 0.0),
         (0.59, 0.36), (0.70, 0.10), (0.77, 0.46), (0.83, 0.30), (0.98, 0.55), (0.90, 1.0))
FADE_STEPS, FADE_MS = 6, 25  # opening and closing the Item Guide: a short fade (owner: "a simple transition")
FLIP_SECONDS = 1.0  # new cards flip over first: if the game's reveal flag doesn't start by then, show anyway
FLIP_DELAY = 0.7  # a shop's first card turns face-up this long after the reveal flag (3 of 3 clips, 2026-10-14)
FLIP_EARLY = 0.5  # a reveal that began this long before new cards' padlocks came in is theirs (the client reads
# offers every 0.3 s; the game starts flipping 0.3 s after dealing, and an event's flip can be over 0.3 s later)
HOVER_MS = 8  # how often the Tk thread looks for a new board read (client.MEMORY_SECONDS, 60 a second): about half a
# read apart. The padlocks' own movement is follower.py's, so this only decides how soon a fade follows a read (was 2
# while this tick moved them: a Tk timer that often cost 15% of a core by itself, measured 2026-11-12). Needs the
# client's 1 ms timers (client.main, keep_timers_sharp): Windows otherwise rounds a Tk timer up to ~15.6 ms
# The game's settings gear, top right: (left, top, right, bottom) in 1080p pixels from the window's top-right corner.
# MEASURED, not read: the owner chose a fixed place after three memory probes found only the Esc menu's settings
# button (2026-10-15, gear_probe 1-3: FightMenuDialog.SettingButton, collapsed). From the owner's 1080p recording
# (ring 1791-1855 x 43-107). ⚠️ Only 16:9 measured; assumed to stay in the corner and scale with the height.
SETTINGS_GEAR = (129, 43, 65, 107)
BUTTON_PAD = 16  # 1080p pixels around it where the mouse already makes the overlay get out of its way
# The notices (top of the right column) start below the gear, so their Use Bypass button is never under it (owner
# 2026-11-13: it sat on the gear, "impossible to click since it goes see through when you hover it")
NOTICE_TOP = SETTINGS_GEAR[3] + BUTTON_PAD
# Work done only when something changed (owner 2026-11-12: "WAY too much cpu load" - the overlay redid every fade
# 60 times a second whether anything had moved or not): the fades are worked out again when the board read, the
# padlocks' places or the mouse change, after a redraw, while new cards flip - and at least this often regardless
REFRESH_SECONDS = 0.25
# A panel coming back on screen stays fully see-through this long, so it shows only once its new content is painted:
# Windows first shows a re-shown window's LAST picture (owner 2026-11-13: the next pop-up's first frame or two showed
# the previous unlock; "only show the popup if it is ready and everything is rendered for display")
REVEAL_SECONDS = 0.05
REVEAL_TICKS = 3  # ...and at least this many fade rounds (Tk handles waiting window events, paints included, in
# between), so a busy moment can't use the time up before it's painted
PADLOCK = 56  # the mark's size
MIN_PADLOCK = 24  # real pixels, however small the window
PADLOCK_KEY = "#010203"  # the padlock window's see-through colour
SKULL_SHARE = 0.78  # the Sell Trap skull: this share of its round tile (draw_padlock)
MIN_GAME_WINDOW = 100  # a client area smaller than this is minimised or not laid out yet


def strips(x: int, y: int, w: int, h: int) -> tuple:
    """
    (left strip, right strip, scale) for a game window at x, y of size w x h: each strip is (x, y, width, height)
    in screen pixels, scale is h / 1080. The board is centred and grows with the window's height; on windows
    narrower than 16:9 it's assumed to shrink with the width instead (unverified - only 16:9 was measured).
    """
    k = h / 1080
    across = min(k, w / 1920)  # how the board's width scales
    centre = x + w / 2
    margin = round(MARGIN * k)
    left_x, left_end = x + margin, round(centre - LEFT_END * across)
    right_x, right_end = round(centre + RIGHT_START * across), x + w - margin
    return ((left_x, y, left_end - left_x, round(LEFT_BOTTOM * k)),
            (right_x, y, right_end - right_x, round(RIGHT_BOTTOM * k)), k)


def inside(point: tuple, box: tuple) -> bool:
    return box[0] <= point[0] < box[2] and box[1] <= point[1] < box[3]


def on_a_button(window, point: tuple) -> bool:
    """The point is on one of the window's own buttons (a Lock Bypass's "Use Bypass")."""
    widgets = list(window.winfo_children())
    while widgets:
        widget = widgets.pop()
        if widget.winfo_class() == "Button" and widget.winfo_ismapped():
            x, y = widget.winfo_rootx(), widget.winfo_rooty()
            if inside(point, (x, y, x + widget.winfo_width(), y + widget.winfo_height())):
                return True
        widgets += widget.winfo_children()
    return False



class Toast(NamedTuple):
    """A pop-up (Overlay.toast)."""
    text: str
    expires: Optional[float] = None  # time.monotonic() when it goes; set when it starts showing (toast_seconds)
    warning: bool = False
    trap: bool = False
    cards: tuple = ()  # the pictures it shows, by key (cards, merchants, events, "item-<id>", "hero:<name>")
    good: bool = False  # a good unlock's: on a drifting rainbow


def load_strip(path: Optional[str]) -> Optional[tuple]:
    """The pop-ups' spot from an earlier run on this PC (save_strip), or None."""
    try:
        with open(path, encoding="utf-8") as f:
            strip = json.load(f)["toast_strip"]
        return tuple(float(v) for v in strip) if len(strip) == 4 else None
    except (OSError, TypeError, ValueError, KeyError):
        return None


def save_strip(path: Optional[str], strip: tuple) -> None:
    """Kept for the main menu after a restart (owner, 2026-11-12: the same spot as in a run). Only when it moved."""
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"toast_strip": list(strip)}, f)
    except OSError:
        pass  # a spot not kept is only a fallback spot next session


def toast_seconds(waiting: int, good: bool) -> float:
    """How long a pop-up shows: 3 s alone, down to 1 s with 10 or more waiting (the one showing included), linearly;
    a rainbow one always TOAST_RAINBOW_SECONDS (owner, 2026-11-12)."""
    longest, shortest, busy = TOAST_SECONDS
    if good:
        return TOAST_RAINBOW_SECONDS
    if waiting <= 1:
        return longest
    return max(shortest, longest - (longest - shortest) * (waiting - 1) / (busy - 1))


def toast_fit(shapes: Sequence[float], width: float, height: float, gap: float, max_rows: int = 2) -> Tuple[int, float]:
    """(rows, picture height) for pictures of these shapes (width / height each) in a picture area this big: up to
    max_rows rows, whichever count lets them be biggest."""
    if not shapes:
        return 0, 0.0
    best = (1, 0.0)
    for rows in range(1, min(max_rows, len(shapes)) + 1):
        per_row = -(-len(shapes) // rows)
        tall = (height - gap * (rows - 1)) / rows
        wide = (width - gap * (per_row - 1)) * rows / sum(shapes)
        if min(tall, wide) > best[1]:
            best = (rows, min(tall, wide))
    return best


def toast_rows(widths: Sequence[int], gap: int, rows: int = 2) -> Tuple[list, int]:
    """Pictures of these widths in at most `rows` rows, as even as their order allows: (the rows, as lists of
    indices; the widest row's width)."""
    if not widths:
        return [], 0
    rows = max(1, min(rows, len(widths)))
    target = (sum(widths) + gap * (len(widths) - 1)) / rows
    out: list = []
    row: list = []
    used = 0
    for i, width in enumerate(widths):
        if row and len(out) < rows - 1 and used + gap + width > target + width / 2:
            out.append(row)
            row, used = [], 0
        used += (gap if row else 0) + width
        row.append(i)
    out.append(row)
    return out, max(sum(widths[i] for i in r) + gap * (len(r) - 1) for r in out)


def text_lines(measure: Callable[[str], int], text: str, width: int) -> int:
    """How many lines `text` wraps to at this width, word by word as Tk wraps it (measure: a word's width)."""
    lines, line = 1, ""
    for word in text.split():
        trial = f"{line} {word}" if line else word
        if line and measure(trial) > width:
            lines, line = lines + 1, word
        else:
            line = trial
    return lines


def toast_place(strip: Optional[tuple], column: tuple, window: tuple, height: int, needed: int,
                bounds: Optional[Tuple[int, int]] = None) -> tuple:
    """The pop-up's (x, y, width, height) on screen: on the strip (from memory) at least its width, wider - evenly
    both ways - when the pictures need it, never past `bounds` (left, right: between the overlay's side columns -
    owner 2026-11-12: "no overlay should be able to sit on another overlay"; the game window when not given); off
    the board, the bottom of the right column instead (column: its x, y, width, height)."""
    if strip is None:
        x, y, width, room = column
        return x, y + room - height, width, height
    low, high = bounds or (window[0], window[0] + window[2])
    left, centre_y, right = strip[0], strip[1], strip[2]
    width = min(max(round(right - left), needed), high - low)
    x = round((left + right) / 2 - width / 2)
    x = min(max(x, low), high - width)
    return x, round(centre_y - height / 2), width, height


def padlock_shape(canvas, x: float, y: float, s: int) -> None:
    """A red padlock with a dark outline (so it reads on light and dark cards alike), s pixels square at x, y."""
    line = max(2, s // 12)
    for colour, width in ((OUTLINE, line + 4), (LOCKED_X, line)):  # the shackle, outlined
        canvas.create_arc(x + s * 0.3, y + s * 0.08, x + s * 0.7, y + s * 0.62, start=0, extent=180, style="arc",
                          outline=colour, width=width)
        canvas.create_line(x + s * 0.3, y + s * 0.35, x + s * 0.3, y + s * 0.48, fill=colour, width=width)
        canvas.create_line(x + s * 0.7, y + s * 0.35, x + s * 0.7, y + s * 0.48, fill=colour, width=width)
    canvas.create_rectangle(x + s * 0.16, y + s * 0.45, x + s * 0.84, y + s * 0.94, fill=LOCKED_X, outline=OUTLINE,
                            width=max(2, s // 20))
    canvas.create_oval(x + s * 0.43, y + s * 0.58, x + s * 0.57, y + s * 0.72, fill=OUTLINE, outline=OUTLINE)
    canvas.create_rectangle(x + s * 0.47, y + s * 0.68, x + s * 0.53, y + s * 0.84, fill=OUTLINE, outline=OUTLINE)


def below(strip: tuple, taken: int) -> tuple:
    """What's left of a strip under a panel `taken` pixels tall at its top (x, y, width, height)."""
    x, y, width, height = strip
    offset = taken + WINDOW_GAP if taken else 0
    return x, y + offset, width, height - offset


def dpi_awareness() -> str:
    """How Windows scales this process's coordinates (a mismatch here puts windows in the wrong place)."""
    if sys.platform != "win32":
        return "n/a"
    import ctypes
    try:
        context = ctypes.windll.user32.GetThreadDpiAwarenessContext()
        return {0: "unaware", 1: "system", 2: "per-monitor"}.get(
            ctypes.windll.user32.GetAwarenessFromDpiAwarenessContext(context), "unknown")
    except (AttributeError, OSError):
        return "unknown"


def game_in_front(own: Set[int]) -> tuple:
    """
    (in front, window) - in front: True while The Bazaar is the active window (Windows only; elsewhere always
    True), None when one of our own windows is (that says nothing about the game, so the caller keeps what it
    had). window: the game's client area (x, y, width, height) on screen while it's in front, else None.
    The game's window is looked up every time (memreader.game_window): Windows reuses handles and process ids.
    """
    if sys.platform != "win32":
        return True, None
    import ctypes
    from ctypes import wintypes
    from .memreader import game_window
    user32 = ctypes.windll.user32
    hwnd = user32.GetAncestor(user32.GetForegroundWindow(), 2)  # GA_ROOT
    if not hwnd:
        return False, None
    if hwnd in own:
        return None, None
    game = game_window()  # the game's own window; whatever else is in front is never looked into (owner, 2026-10-01)
    if not game or game[0] != hwnd:
        return False, None
    rect, corner = wintypes.RECT(), wintypes.POINT(0, 0)
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    user32.ClientToScreen(hwnd, ctypes.byref(corner))
    if rect.right < MIN_GAME_WINDOW or rect.bottom < MIN_GAME_WINDOW:
        return True, None
    return True, (corner.x, corner.y, rect.right, rect.bottom)


def overlaps(a: tuple, b: tuple) -> bool:
    """Two (x, y, width, height) rectangles share any area."""
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def draw_skull(tk, parent, size: int, bg: str):
    """A skull with glowing eyes in front of flickering flames: a Sell Trap's mark (owner, 2026-10-01)."""
    canvas = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
    flames = []
    for i, (grow, lift) in enumerate(((1.0, 0.0), (0.74, 0.26), (0.48, 0.5))):
        points = [v * size for x, y in FLAME for v in (0.5 + (x - 0.5) * grow, lift + y * (1 - lift))]
        flames.append(canvas.create_polygon(points, smooth=True, fill=FLAMES[0][i], outline=""))

    def box(x0, y0, x1, y1):  # the skull sits low and a little smaller, so the flames rise above it
        return tuple(size * (0.5 + (v - 0.5) * 0.8 if i % 2 == 0 else 0.2 + v * 0.8)
                     for i, v in enumerate((x0, y0, x1, y1)))
    line = max(1, size // 32)
    canvas.create_rectangle(box(0.37, 0.66, 0.63, 0.90), fill=BONE, outline="black", width=line)  # jaw
    canvas.create_oval(box(0.24, 0.28, 0.76, 0.78), fill=BONE, outline="black", width=line)  # cranium
    canvas.create_rectangle(box(0.38, 0.70, 0.62, 0.76), fill=BONE, outline="")  # cranium meets jaw
    eyes = []
    for x in (0.31, 0.53):
        canvas.create_oval(box(x, 0.44, x + 0.16, 0.61), fill="black", outline="")
        eyes.append(canvas.create_oval(box(x + 0.04, 0.49, x + 0.12, 0.57), fill=FLAMES[0][1], outline=""))
    canvas.create_polygon(box(0.5, 0.62, 0.46, 0.70)[:2] + box(0.46, 0.70, 0.54, 0.70)[2:] +
                          box(0.5, 0.62, 0.54, 0.70)[2:], fill="black")  # nose
    for x in (0.43, 0.5, 0.57):  # teeth
        canvas.create_line(box(x, 0.80, x, 0.90), fill="black", width=line)

    def flicker(step: int = 1) -> None:
        if not canvas.winfo_exists():  # the panel was redrawn
            return
        colours = FLAMES[step % len(FLAMES)]
        for flame, colour in zip(flames, colours):
            canvas.itemconfigure(flame, fill=colour)
        for eye in eyes:
            canvas.itemconfigure(eye, fill=colours[1 + step % 2])
        canvas.after(FLICKER_MS, flicker, step + 1)
    canvas.after(FLICKER_MS, flicker)
    return canvas


SHIELD_FILL, SHIELD_EDGE = "#8fb8de", "#23405f"


def draw_shields(tk, parent, count: int, size: int, bg: str):
    """`count` Trap Shields as stacked shield icons, each one a little to the right of the last (owner, 2026-11-10:
    "a shield icon (stacked to show how many shield you have)")."""
    step = max(3, round(size * 0.45))
    canvas = tk.Canvas(parent, width=size + step * (count - 1), height=size, bg=bg, highlightthickness=0, bd=0)
    for i in range(count):  # left to right: each new one in front of the last
        x = i * step
        outline = [(0.12, 0.10), (0.5, 0.02), (0.88, 0.10), (0.86, 0.52), (0.5, 0.98), (0.14, 0.52)]
        canvas.create_polygon([v for px, py in outline for v in (x + px * size, py * size)], fill=SHIELD_FILL,
                              outline=SHIELD_EDGE, width=max(1, size // 12))
        canvas.create_line(x + 0.5 * size, 0.14 * size, x + 0.5 * size, 0.84 * size, fill=SHIELD_EDGE,
                           width=max(1, size // 14))
    return canvas


def rainbow(base: str, tint: float = RAINBOW_TINT, count: int = RAINBOW_BANDS) -> List[str]:
    """`count` colours round the colour wheel, each mixed `tint` into `base` (a "#rrggbb")."""
    under = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    out = []
    for n in range(count):
        hue = colorsys.hsv_to_rgb(n / count, 1, 1)
        out.append("#" + "".join(f"{round(c * 255 * tint + u * (1 - tint)):02x}" for c, u in zip(hue, under)))
    return out


def draw_toast_background(tk, parent, width: int, height: int, bg: str, good: bool):
    """A pop-up's background - see-through like every panel (ALERT_ALPHA): its colour, and for a good unlock a
    rainbow drifting sideways over it (owner, 2026-11-11). Its text and pictures sit in a window of their own on top,
    solid (draw_toast_content; owner, 2026-11-12: "the card art not opaque, just the background")."""
    canvas = tk.Canvas(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0)
    if not good:
        return canvas
    colours = rainbow(bg)
    step = width / RAINBOW_BANDS
    bands = [canvas.create_rectangle(round(n * step), 0, round((n + 1) * step) + 1, 10_000, fill=colour, outline="")
             for n, colour in enumerate(colours)]

    def drift(tick: int = 1) -> None:
        if not canvas.winfo_exists():  # the pop-up was redrawn or went
            return
        for n, band in enumerate(bands):
            canvas.itemconfigure(band, fill=colours[(n - tick) % RAINBOW_BANDS])
        canvas.after(RAINBOW_MS, drift, tick + 1)
    canvas.after(RAINBOW_MS, drift)
    return canvas


def draw_toast_content(tk, parent, width: int, height: int, key: str, fg: str, text: str, font: tuple, rows: list,
                       gap: int):
    """A pop-up's text on top and its pictures under it in rows (lists of PhotoImages), each row centred, on `key`:
    the colour its window shows as see-through, so only the text and pictures show, solid, over the background."""
    canvas = tk.Canvas(parent, width=width, height=height, bg=key, highlightthickness=0, bd=0)
    middle = height / 2 if not rows else gap
    text_id = canvas.create_text(width / 2, middle, text=text, fill=fg, font=font, width=width - 4 * gap,
                                 justify="center", anchor="center" if not rows else "n")
    top = canvas.bbox(text_id)[3] + gap
    for row in rows:
        span = sum(p.width() for p in row) + gap * (len(row) - 1)
        x = (width - span) / 2
        for picture in row:
            canvas.create_image(x, top, image=picture, anchor="nw")
            x += picture.width() + gap
        top += max(p.height() for p in row) + gap
    return canvas


def draw_flame_band(tk, parent, width: int, height: int, bg: str):
    """A row of the Sell Trap's flickering flames (FLAME, FLAMES), side by side across `width`: the border of the
    warning before a PvP fight (owner, 2026-11-09: "bolder and surrounded by flames")."""
    canvas = tk.Canvas(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0)
    count = max(3, width // max(1, height))
    step = width / count
    rows = []
    for n in range(count):
        layers = []
        for i, (grow, lift) in enumerate(((1.0, 0.0), (0.7, 0.3))):
            points = [v for x, y in FLAME for v in (n * step + step * (0.5 + (x - 0.5) * grow),
                                                    height * (lift + y * (1 - lift)))]
            layers.append(canvas.create_polygon(points, smooth=True, fill=FLAMES[0][i], outline=""))
        rows.append(layers)

    def flicker(tick: int = 1) -> None:
        if not canvas.winfo_exists():  # the panel was redrawn
            return
        for n, layers in enumerate(rows):  # neighbours out of step, so the row dances
            colours = FLAMES[(tick + n) % len(FLAMES)]
            for layer, colour in zip(layers, colours):
                canvas.itemconfigure(layer, fill=colour)
        canvas.after(FLICKER_MS, flicker, tick + 1)
    canvas.after(FLICKER_MS, flicker)
    return canvas


class Overlay:
    """The client's handle on the windows: every method only queues a command for the Tk thread."""

    def __init__(self, art_cache_dir: Optional[str] = None, guide_file: Optional[str] = None,
                 overlay_file: Optional[str] = None) -> None:
        self.only_over_game = True  # False shows the windows whatever is in front (tests)
        self.game_window: Optional[tuple] = None  # tests: pretend the game's client area is here (x, y, w, h)
        self.guide_file = guide_file  # where the Item Guide remembers whether it's closed and where you put it
        self.overlay_file = overlay_file  # where the pop-ups' spot from the last run is kept (_Screen.toast_strip)
        self.art_cache_dir = art_cache_dir
        self.on_bypass: Optional[Callable[[str], None]] = None  # the client: use a Lock Bypass on a held card
        self.latest_board_ui = None  # the newest board flags (see show_board_ui)
        # the client's memory reader: where these cards are this instant (memreader.Reader.positions), so padlocks
        # can follow moving cards every game frame; None: they follow each board read only
        self.positions: Optional[Callable[[Sequence[str]], Dict[str, tuple]]] = None
        self.commands: "queue.Queue" = queue.Queue()
        self.available = True  # False if the windows can't open (no tkinter, or Tk can't start)
        self.ready = threading.Event()  # set once the windows are up (or failed to come up)
        self.thread = threading.Thread(target=self._run, name="bazaar overlay", daemon=True)
        self.thread.start()

    # --- called from the client ---------------------------------------------------------------------------------

    def show_locked(self, title: Optional[str], cards: list, blocked: bool = False, trap: bool = False,
                    danger: bool = False) -> None:
        """The alert box's banner and the lines under it (held locked cards, Sell Traps). title=None hides it.
        A line is text, or (text, card guid) to give it a "Use Bypass" button (a Lock Bypass is ready).
        blocked: checks are blocked (critical, red) rather than just a warning (a Sell Trap coming up).
        trap: a Sell Trap is behind it - drawn as a skull in flames.
        danger: the PvP fight is next and keeping what's listed would lose the run - bolder, between flames."""
        self.commands.put(("locked", (title, list(cards), blocked, trap, danger) if title else None))

    def show_padlocks(self, locks: Sequence[Padlock], reveal: bool = False) -> None:
        """The padlocks on what's offered, each on its card or event option (padlocks.Padlock). None hides them at
        once. reveal: new cards, so they wait until each has turned face-up."""
        value = tuple(locks) if locks else None
        self.commands.put(("padlocks", (value, time.monotonic(), reveal and value is not None)))

    def show_board_ui(self, ui) -> None:
        """The board's on-screen flags (memreader.BoardUI), or None when they can't be read: then no padlocks show
        (nothing says their art is there)."""
        # picked up every HOVER_MS by the Tk thread, not queued: the queue is only emptied every POLL_MS, which made
        # padlocks show up to a quarter second after a reveal ended (and a queued older reading could undo a newer)
        self.latest_board_ui = ui

    def show_board_padlocks(self, locks: Sequence[Padlock]) -> None:
        """The padlocks on your own board's locked cards (they don't wait for any reveal)."""
        self.commands.put(("board_padlocks", tuple(locks) or None))

    def show_board(self, title: Optional[str], offered: List[str], merchant: Optional[int]) -> None:
        """Item Guide: what's on offer on screen (card guids, first, framed in gold) and the merchant you're at (its
        stock is listed below). title=None: you left; the guide keeps its list and filters."""
        self.commands.put(("board", (title, tuple(offered), merchant) if title else None))

    def guide_context(self, hero: Optional[str], locked) -> None:
        """Item Guide: your hero and the cards you may not hold (greyed out with a red cross)."""
        self.commands.put(("guide_context", (hero, frozenset(locked))))

    def toggle_guide(self) -> None:
        self.commands.put(("guide_toggle", None))

    def toast(self, text: str, warning: bool = False, trap: bool = False, cards: Sequence[str] = (),
              good: bool = False) -> None:
        """A pop-up, queued (toast_seconds says how long each shows). trap: a Sell Trap's colours. cards: the
        pictures it shows, by key (Toast.cards). good: a big unlock's, on a drifting rainbow (draw_toast_background)."""
        self.commands.put(("toast", Toast(text, None, warning, trap, tuple(cards), good)))

    def show_menu_covered(self, covered: bool) -> None:
        """One of the game's own screens is open over the menu (or not): picked up every HOVER_MS by the Tk thread,
        like the board's flags, so the hero panel goes and comes back with the game's screens."""
        self.latest_menu_covered = covered

    def show_menu(self, data: Optional[dict]) -> None:
        """The menu's centre panel (see client.menu_data); None hides it."""
        self.commands.put(("menu", data))

    def show_status(self, text: Optional[str], warning: bool = False, big: bool = False, shields: int = 0) -> None:
        """The bottom of the alert box: run progress, or (big) the heroes you may pick on the menu. None hides it.
        shields: Trap Shields ready, drawn as stacked icons after the text (next to the Lock Bypasses)."""
        self.commands.put(("status", (text, warning, big, shields) if text else None))

    def show_tracker_data(self, data: Dict[str, dict]) -> None:
        """What the tracker shows (see tracker.Tracker.update); sent whenever items or checks change."""
        self.commands.put(("tracker", data))

    def show_tracker(self) -> None:
        self.commands.put(("tracker_show", None))

    def show_deathlink(self, text: Optional[str]) -> None:
        self.commands.put(("deathlink", text))

    def close(self) -> None:
        self.commands.put(("quit", None))

    # --- Tk thread ----------------------------------------------------------------------------------------------

    def _run(self) -> None:
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception:  # no tkinter, or Tk can't start (no display, broken Tcl): no windows at all
            self.available = False
            self.ready.set()
            return
        screen = _Screen(self, tk, root)
        self.ready.set()
        screen.run()


class _Screen:
    """Everything that lives in the Tk thread: the panels, what they show, and the command loop."""

    def __init__(self, overlay: Overlay, tk, root) -> None:
        self.overlay, self.tk, self.root = overlay, tk, root
        root.withdraw()
        # No two windows overlap: the alert box (root) takes the top of the left strip, the locked-card list goes
        # right under it, and the right strip belongs to the Item Guide - or, while the guide is closed, to the
        # rest of a long list. Pop-ups (toasts) stack up from the bottom of the right strip, which then shrinks.
        # Owner, 2026-10-01: "The item guide is always going to be the whole left column": the alert box (root) is
        # now just its header (status and buttons); DeathLink, held locked cards and Sell Traps are the notices box at
        # the top of the right column, the pop-ups at the bottom. The locked-card list that sat between them went
        # (owner, 2026-10-01: the padlocks on the cards themselves say it).
        # On the menu (no run, no board) the heroes you may play sit in the centre (owner, 2026-10-01).
        self.alert_box, self.notice_box, self.toast_box, self.menu_box = \
            root, tk.Toplevel(root), tk.Toplevel(root), tk.Toplevel(root)
        self.panels = [self.alert_box, self.notice_box, self.toast_box, self.menu_box]
        # nothing to click in these (the menu panel must never block the game's menu buttons)
        self.click_through = {self.toast_box, self.menu_box}
        # ...and these go see-through and let clicks reach the game while the mouse is over the game's settings gear
        # under them (SETTINGS_GEAR, padded), but never on their own buttons (owner, 2026-10-15: the concede
        # notice sat on the settings gear - "it has to have a UI element behind it that is interactable and being
        # blocked", "once a mouse starts to hover above the position of the settings icon (With some padding)")
        self.hover_through = (self.alert_box, self.notice_box, self.toast_box, self.menu_box)
        self.passing: Dict[object, bool] = {}  # window -> letting clicks through now (see fade_padlocks)
        for panel in self.panels:
            panel.withdraw()
            panel.overrideredirect(True)
            panel.attributes("-topmost", True)
            panel.attributes("-alpha", ALERT_ALPHA)
            panel.configure(bg=SEVERITY["info"], highlightthickness=BORDER, highlightbackground=ACCENT)
            screens.never_focus(panel)
        # the pop-up's text and pictures: a window of their own over toast_box, solid (draw_toast_content), its
        # background colour see-through (-transparentcolor, set per pop-up), clicks passing through
        self.toast_content = tk.Toplevel(root)
        self.toast_content.withdraw()
        self.toast_content.overrideredirect(True)
        self.toast_content.attributes("-topmost", True)
        screens.never_focus(self.toast_content)
        self.panels.append(self.toast_content)  # after toast_box: lifted after it, so it sits on top
        self.click_through.add(self.toast_content)
        self.padlocks: list = []  # one small click-through window per padlock, made as needed and reused
        self.padlocks_wanted = 0  # how many of them are in use
        self.pending_padlocks = None  # (padlocks, since, wait for the reveal) while new cards are still flipping
        self.reveal_started = False  # the game's reveal began since those padlocks came in
        self.reveal_began = -FLIP_EARLY  # when the game's current (or last) reveal began
        self.reveal_ended = -FLIP_EARLY  # when the game's last reveal ended
        self.stagger_from = 0.0  # new padlocks show left to right from then, padlocks.FLIP_STAGGER apart (0: all at once)
        self.locks: List[Padlock] = []  # the padlocks shown now: what's offered (or the stash), then your board
        self.lock_squares: List[Optional[tuple]] = []  # each one's square on screen now (None: its card isn't)
        self.padlock_alphas: List[float] = []  # each padlock's alpha now (see padlock_look)
        self.padlock_trace: Dict[Optional[str], str] = {}  # each padlock's card -> why it shows so (trace_padlocks)
        self.board_ui = None  # memreader.BoardUI, or None (unreadable: no padlocks, nothing says the art is there)
        self.overlay_faded = 1.0  # every other window's fade now (see overlay_factor)
        self.followed = None  # the board read the padlocks last followed (see fade_padlocks)
        # moves the padlock windows, from its own thread while their cards move (follower.py)
        self.follower = follower.Follower(lambda: getattr(overlay, "positions", None))
        self.fade_key: tuple = ()  # what the fades were last worked out from, and when (see fade_padlocks)
        self.faded_at = 0.0
        self.fade_command = root.register(self.fade_padlocks)  # one Tcl command for the whole session, not one a tick
        self.guide_fading = False  # the Item Guide is fading in or out (a second click waits for it)

        self.layout: dict = {}  # the strips for where the game window is now (see relayout)
        self.relayout((0, 0, root.winfo_screenwidth(), root.winfo_screenheight()))  # until the game is seen
        self.state = {"locked": None, "deathlink": None, "toasts": [], "status": None,
                      "padlocks": None, "board_padlocks": None, "menu": None}
        self.hero_pictures: Dict[str, object] = {}  # the menu panel's portraits (Tk drops an image Python lets go)
        self.toast_pictures: Dict[tuple, object] = {}  # pop-ups' pictures, (key, height) -> image
        self.toast_art: Dict[int, object] = {}  # cardart.CardArt by picture height (the pop-ups' own sizes)
        self.root.after(HERO_WARM_MS, self.warm_hero_cards, list(HEROES))
        self.toast_shown = None  # the pop-up drawn now, complete (its time runs: next_toast)
        self.toast_see_through = False  # the pop-up is see-through now: padlocks under it show (windows_over_board)
        self.toast_waiting: Dict[object, float] = {}  # pop-up -> when it first waited for its pictures
        self.toast_sizes: Dict[object, int] = {}  # queued pop-up -> its pictures' height (made ahead, new_art)
        self.last_toast_strip = load_strip(getattr(overlay, "overlay_file", None))  # from an earlier run, this PC
        # the player hid the menu's hero panel, e.g. over character select, which the game gives no sign of
        # (owner, 2026-10-01: a button, option 3)
        self.menu_hidden = False
        # the Tracker covers the menu panel (it opens in the middle of the screen too, and shows the same checks and
        # more): the panel steps aside while it does (owner, 2026-10-01)
        self.menu_rect: Optional[tuple] = None  # where the menu panel goes (x, y, width, height)
        self.menu_under_tracker = False
        # what each window shows now, to skip redraws that change nothing
        self.drawn: dict = {"alerts": None, "notices": None, "toasts": None, "alerts_height": 0,
                            "notices_height": 0, "toasts_height": 0, "padlocks": None}
        self.wanted: set = set()  # windows that have something to show (shown only while the game is in front)
        self.revealing: Dict = {}  # panel -> [time it may be seen, fade rounds still to wait]: just shown, see-through
        self.game_in_front = not overlay.only_over_game
        self.ours_in_front = False  # one of our own windows is the active one (see keep_on_top)
        self.rendering = self.render_again = False
        self.guide = ShopGuide.create(
            tk, root, overlay.art_cache_dir, overlay.guide_file, self.layout["right"],
            on_art=lambda guid: overlay.commands.put(("art", guid)),
            on_closed=lambda: overlay.commands.put(("redraw", None)),
            on_close_click=lambda: overlay.commands.put(("guide_toggle", None)))
        self.tracker = Tracker(tk, root, lambda: self.layout["screen"])
        self.handlers: Dict[str, Callable] = {
            "art": self.new_art,
            "board": lambda value: self.guide and self.guide.show_offer(value),
            "guide_context": lambda value: self.guide and self.guide.set_context(*value),
            "guide_toggle": self.toggle_guide,
            "redraw": lambda _: True,
            "tracker": self.new_tracker_data,
            "tracker_show": lambda _: self.tracker.open(),
            "toast": self.new_toast,
            **{kind: (lambda value, kind=kind: self.set_state(kind, value))
               for kind in ("locked", "deathlink", "status")},
            "menu": self.new_menu,
            "padlocks": self.new_padlocks,
            "board_padlocks": lambda value: self.set_state("board_padlocks", value),
        }

    def overlay_factor(self) -> float:
        """Whether the overlay shows at all, by the game's own flags: hidden under a dialog (Esc menu, the new-day
        screen). Not while your stash slides: only the padlocks hide then (owner, 2026-10-15: "the ENTIRE overlay is
        hidden when this is happening"; was 2026-10-01). Going see-through is each window's own business: only one
        the game's tooltip or dragged card reaches (owner, 2026-10-14; see fade_padlocks)."""
        ui = self.board_ui
        return 0.0 if ui is not None and ui.dialog else 1.0

    def dialog_hides(self, window) -> bool:
        """A game dialog (the Esc menu, a loading screen, the new-day screen: overlay_factor) hides an overlay window
        only while it sits on the game window; one elsewhere - the Tracker or the Item Guide on another monitor - stays
        (owner 2026-11-16: "Only hide portions of the overlay if it is in front of the bazaar game window"; was: all
        but the Tracker, 2026-11-13). A withdrawn window keeps its place, so this holds while it's hidden too."""
        if self.overlay_factor() > 0 or window is None or not window.winfo_exists() or "window" not in self.layout:
            return False
        x, y, w, h = self.layout["window"]
        left, top = window.winfo_rootx(), window.winfo_rooty()
        return padlocks.touches((left, top, left + window.winfo_width(), top + window.winfo_height()),
                                (x, y, x + w, y + h))

    def faded_windows(self) -> list:
        """(window, its own alpha) for every overlay window the fade scales."""
        out = [(self.alert_box, ALERT_ALPHA), (self.notice_box, ALERT_ALPHA), (self.toast_box, ALERT_ALPHA),
               (self.toast_content, 1.0), (self.menu_box, ALERT_ALPHA)]
        if self.guide and not self.guide_fading:
            out.append((self.guide.win, 1.0))
        if self.tracker.win is not None and self.tracker.win.winfo_exists():
            out.append((self.tracker.win, 1.0))
        return out

    def padlock_look(self, i: int, covers: List[tuple], windows: Sequence[tuple] = ()) -> tuple:
        """Padlock i by the rules in padlocks.py; none while the board's flags can't be read (owner, 2026-10-15: a
        padlock shows only where its card's art is - was: event options followed the mouse, 2026-10-01)."""
        if self.board_ui is None:
            return padlocks.HIDDEN, "no board read"
        return padlocks.look(self.locks[i], self.lock_squares[i], self.board_ui, covers,
                              padlocks.COVER_PAD * self.layout["k"], self.stagger_from, time.monotonic(), windows)

    def windows_over_board(self) -> List[tuple]:
        """Our own windows that can sit over the board, as (left, top, right, bottom) on screen: the tracker, its
        list and the Item Guide while shown, and the pop-up while it's solid. While the pop-up is see-through (the mouse
        on it, or the game covering it) padlocks show over it instead (owner, 2026-11-12: "ONLY IF the other overlay
        element is turning transparent, AKA one of the UI elements is 'gone' so there is technically no overlapping")."""
        out = []
        shown = [self.tracker.win, self.tracker.popup] + ([self.guide.win] if self.guide and not self.guide.hidden else []) \
            + ([] if self.toast_see_through else [self.toast_box])
        for window in shown:
            if window is not None and window.winfo_exists() and window.winfo_ismapped():
                box = screens.visible_bounds(window) or (window.winfo_rootx(), window.winfo_rooty(),
                                                         window.winfo_width(), window.winfo_height())
                out.append((box[0], box[1], box[0] + box[2], box[1] + box[3]))
        return out

    def toast_hit_box(self, box: tuple) -> tuple:
        """The part of a pop-up that the game's tooltips and cards fade: from your portrait's centre line down (the
        strip, read from the board), so a card row brushing its top as it flips doesn't blink it out (owner
        2026-11-13: "move the hitbox a little further from the top ... probably below the health bar"). Off the
        board (no strip): the whole pop-up."""
        strip = self.toast_strip()
        if not strip:
            return box
        x, y, w, h = self.layout["window"]
        return box[0], max(box[1], y + strip[1] * h), box[2], max(box[3], y + strip[1] * h)

    def covers(self) -> List[tuple]:
        return padlocks.coverings(self.board_ui, self.layout["window"]) if self.board_ui is not None else []

    def fade_padlocks(self) -> None:
        """Every HOVER_MS. On a board read that changed, the padlocks are placed on their cards (and follow them
        from there while they move: follower.py). Each padlock and window follows what covers it - worked out again
        only when something it depends on changed (REFRESH_SECONDS). One still waiting checks if it's due."""
        try:
            if not self.overlay.commands.empty() and self.tick() == "quit":  # queued news shows now, not at the
                return  # next POLL_MS round (owner 2026-10-15: the hero panel lagged a hero pick)
            ui = getattr(self.overlay, "latest_board_ui", self.board_ui)
            rendered = False
            if ui is not self.board_ui and self.new_board_ui(ui):  # a reveal ending is seen within HOVER_MS
                self.render()
                rendered = True
            if self.pending_padlocks and self.show_due_padlocks():
                self.render()
                rendered = True
            covered = getattr(self.overlay, "latest_menu_covered", None)
            menu = self.state["menu"]
            if menu and covered is not None and bool(menu.get("covered")) != covered:
                self.state["menu"] = dict(menu, covered=covered)
                self.render()
                rendered = True
            now = time.perf_counter()
            if rendered or ui != self.followed:  # by value: the reader makes a new one every read, mostly the same
                self.followed = ui
                self.place_padlocks()  # they ride on their cards: dragged, sliding, enlarged
            pointer = self.root.winfo_pointerxy() if self.game_in_front else None  # never read off the game
            key = (ui, tuple(self.lock_squares), pointer)
            flipping = self.stagger_from and time.monotonic() < self.stagger_from + len(self.locks) * padlocks.FLIP_STAGGER
            if not rendered and not flipping and not self.revealing and key == self.fade_key \
                    and now - self.faded_at < REFRESH_SECONDS:
                self.again()
                return
            self.fade_key, self.faded_at = key, now
            covers = self.covers()
            self.apply_padlock_alphas(covers)
            factor = self.overlay_factor()
            if factor != self.overlay_faded:
                if (factor == 0) != (self.overlay_faded == 0):
                    self.sync_visibility()  # hidden, not just see-through: an invisible window still takes clicks
                self.overlay_faded = factor
            button = self.game_button_at(pointer) if pointer is not None else None  # the mouse is on it (padded)
            for window, wait in list(self.revealing.items()):
                wait[1] -= 1
                if (time.monotonic() >= wait[0] and wait[1] <= 0) or window.state() != "normal":
                    del self.revealing[window]
            for window, own in self.faded_windows():
                # a game dialog or loading screen hides only what sits on the game window (dialog_hides; owner
                # 2026-11-13 about the Tracker on another monitor: "every load screen I go to look at it and its just
                # gone")
                shown = 0.0 if self.dialog_hides(window) else 1.0
                alpha = 0.0 if window in self.revealing else own * shown
                over = False
                if alpha and window.winfo_ismapped():
                    x, y = window.winfo_rootx(), window.winfo_rooty()
                    box = (x, y, x + window.winfo_width(), y + window.winfo_height())
                    # only the window that sits on that button gets out of its way
                    over = window in self.hover_through and button is not None and padlocks.touches(box, button)
                    # a pop-up over your hero and skills lets you see them while the mouse is on it (owner 2026-11-12)
                    under_mouse = window in (self.toast_box, self.toast_content) and pointer is not None \
                        and inside(pointer, box)
                    guide = self.guide and window is self.guide.win
                    # the keyword tray never fades the guide; all else does (owner 2026-11-13: "ONLY FROM THIS TRAY")
                    hits = covers if not guide or self.board_ui is None else (
                        padlocks.coverings(self.board_ui, self.layout["window"], keyword_tray=False))
                    if window in (self.toast_box, self.toast_content):
                        hits_box = self.toast_hit_box(box)
                    else:
                        hits_box = box
                    if over or under_mouse or hits and padlocks.covered(hits_box, hits):
                        alpha *= padlocks.SEE_THROUGH
                if window is self.toast_box:  # padlocks under it show only while it's see-through (windows_over_board)
                    self.toast_see_through = alpha < own * shown
                if window in self.hover_through and window not in self.click_through:
                    passing = over and not on_a_button(window, pointer)
                    if self.passing.get(window) != passing:
                        screens.pass_clicks(window, passing)
                        self.passing[window] = passing
                if abs(float(window.attributes("-alpha")) - alpha) > 0.001:  # others set it too (the guide's fade)
                    window.attributes("-alpha", alpha)
        except Exception:
            logger.exception("Overlay error (it keeps going)", extra=FILE_ONLY)
        self.again()

    def again(self) -> None:
        self.root.tk.call("after", HOVER_MS, self.fade_command)

    def game_button_at(self, point: tuple) -> Optional[tuple]:
        """The game's settings gear on screen if the point is on it, padded by BUTTON_PAD. From memory on the board
        (memreader.find_gear); the measured SETTINGS_GEAR where the reader hasn't got it (the menu, reader off)."""
        k, (x, y, w) = self.layout["k"], self.layout["window"][:3]
        ui = getattr(self, "board_ui", None)
        if ui is not None and ui.gear:
            gear = padlocks.to_screen(ui.gear, self.layout["window"])
        else:
            gear = (x + w - SETTINGS_GEAR[0] * k, y + SETTINGS_GEAR[1] * k, x + w - SETTINGS_GEAR[2] * k,
                    y + SETTINGS_GEAR[3] * k)
        pad = BUTTON_PAD * k
        return gear if inside(point, (gear[0] - pad, gear[1] - pad, gear[2] + pad, gear[3] + pad)) else None

    def apply_padlock_alphas(self, covers: List[tuple]) -> None:
        windows = self.windows_over_board() if self.padlocks_wanted else []
        looks = [self.padlock_look(i, covers, windows) for i in range(self.padlocks_wanted)]
        alphas = [alpha for alpha, _why in looks]
        self.trace_padlocks(looks)
        for i, alpha in enumerate(alphas):
            if i >= len(self.padlock_alphas) or self.padlock_alphas[i] != alpha:
                self.padlocks[i].attributes("-alpha", alpha)
        self.padlock_alphas = alphas

    def trace_padlocks(self, looks: List[tuple]) -> None:
        """To the client's log file: each padlock's card and why it shows as it does, whenever that changes (2026-11-12,
        F4: padlocks went missing on the owner's other PC with nothing to say why). Never the client's window."""
        trace = {lock.card: why for lock, (_alpha, why) in zip(self.locks, looks)}
        if trace != self.padlock_trace:
            changed = {card: why for card, why in trace.items() if self.padlock_trace.get(card) != why}
            gone = [card for card in self.padlock_trace if card not in trace]
            ui = self.board_ui
            flags = "no board read" if ui is None else (
                f"hovering {ui.hovered_card} ({len(ui.tooltips)} tooltip pieces), dragging {ui.dragged_card}, "
                f"inspecting {ui.inspecting}, dialog {ui.dialog}, revealing {ui.revealing}, {len(ui.cards)} cards placed")
            logger.info(f"Padlocks: {changed}{f', gone {gone}' if gone else ''} | {flags}", extra=FILE_ONLY)
            self.padlock_trace = trace

    def run(self) -> None:
        # laid out once now: with the game exactly on the primary screen no later tick sees a "move", and an open
        # Item Guide showed at its unsettled size over the game's corner (review 2026-09-30)
        self.render()
        self.root.after(POLL_MS, self.poll)
        self.again()
        threading.Thread(target=self.follower.run, name="bazaar padlocks", daemon=True).start()
        self.root.mainloop()
        self.follower.stop()

    # --- where things go --------------------------------------------------------------------------------------

    def relayout(self, window: tuple) -> None:
        root = self.root
        primary = (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
        monitors = screens.monitors() or [primary]
        screen = screens.monitor_for(window, monitors)
        if screen is None:  # the game's position is on no monitor at all: don't trust it, use the main screen
            logger.warning(f"Overlay: game window {window} is on no monitor {monitors}; using {primary}",
                           extra=FILE_ONLY)
            window = screen = screens.monitor_for(primary, monitors) or primary
        left, right, k = strips(*window)
        # every window the overlay shows is kept inside this monitor (see render / screens.clamp)
        self.layout.update(window=window, screen=screen, left=left, right=right, k=k,
                           inner_w=left[2] - 2 * (PAD + BORDER))
        # to the log file only: where the overlay thinks the game is (for placement bugs on other screens)
        logger.info(f"Overlay layout: game window {window}, screen {primary[2]}x{primary[3]}, Tk scaling "
                    f"{root.tk.call('tk', 'scaling'):.2f}, DPI awareness {dpi_awareness()}, left strip {left}, "
                    f"right strip {right}, monitor {screen}", extra=FILE_ONLY)

    def font(self, size: float, weight: str = "normal") -> tuple:
        """A font of `size` points at 1080p, scaled with the game window."""
        return FONT, -max(MIN_FONT, round(size * POINT_TO_PX * self.layout["k"])), weight

    def swap(self, panel, bg: str):
        """A fresh content frame for the panel. The old one is destroyed only after the new one is packed, so the
        window never shows up empty in between (no flicker)."""
        old = [child for child in panel.winfo_children() if type(child) is self.tk.Frame]  # not other windows
        new = self.tk.Frame(panel, bg=bg, padx=PAD, pady=PAD)
        panel.configure(bg=bg)
        return new, lambda: (new.pack(fill="both", expand=True), [child.destroy() for child in old])

    @staticmethod
    def place(moves: list, panel, space: tuple) -> int:
        """Fixed width, height as needed but never past its space (x, y, width, height): a panel can't spill onto
        anything else. The move is only queued (see render) and its height returned."""
        panel.update_idletasks()
        x, y, width, room = space
        height = min(panel.winfo_reqheight(), room)
        moves.append((panel, (x, y, width, height)))
        return height

    def reveal(self, window) -> None:
        """Fully see-through until its new content is painted (REVEAL_SECONDS, REVEAL_TICKS); the fade rounds
        then give it its own alpha again."""
        window.attributes("-alpha", 0.0)
        self.revealing[window] = [time.monotonic() + REVEAL_SECONDS, REVEAL_TICKS]

    def sync_visibility(self) -> None:
        """Show what has something to show, but only while The Bazaar (or one of these windows) is in front - and
        not while the game's own flags hide the overlay (a fully faded window would still catch clicks)."""
        guide = self.guide.win if self.guide else None
        front = self.game_in_front and self.overlay_factor() > 0  # padlocks: always on the game window
        raised = False  # a panel came up: padlocks go back above it (they show over the pop-up, windows_over_board)
        for window in self.panels + ([guide] if guide else []):
            show = self.game_in_front and not self.dialog_hides(window)                 and (not self.guide.hidden if window is guide else window in self.wanted)
            if show and window.state() != "normal":
                if window is not guide:  # see-through until its new content is painted (REVEAL_SECONDS)
                    self.reveal(window)
                window.deiconify()
                window.lift()
                raised = True
                if window in self.click_through:
                    screens.click_through(window)
                if window is guide:
                    self.guide.place_on_screen(self.layout["screen"])  # needs it shown to measure its frame
            elif not show and window.state() == "normal":
                window.withdraw()
        for i, padlock in enumerate(self.padlocks):
            show = front and i < self.padlocks_wanted
            if show and padlock.state() != "normal":
                padlock.deiconify()
                padlock.lift()
                screens.click_through(padlock)  # the card under it must stay clickable, tooltip and all
            elif not show and padlock.state() == "normal":
                padlock.withdraw()
        if raised:
            for padlock in self.padlocks[:self.padlocks_wanted]:
                if padlock.state() == "normal":
                    padlock.lift()
        self.tracker.set_visible(self.game_in_front, self.dialog_hides)

    # --- drawing ----------------------------------------------------------------------------------------------

    def render(self) -> None:
        """Windows are laid out first and all moved together at the end, so one never sits on another while the
        next is still being worked out. Re-entered (a Tk update inside placing a window ran another redraw)? Then
        that redraw waits until this one is done."""
        if self.rendering:
            self.render_again = True
            return
        self.rendering = True
        try:
            self._render()
        finally:
            self.rendering = False
        if self.render_again:
            self.render_again = False
            self.root.after_idle(self.render)

    def _render(self) -> None:
        state, drawn, layout = self.state, self.drawn, self.layout
        moves: list = []
        # the notices first (they matter more), then the pop-ups take all the room left under them
        right = layout["right"]
        notices = (state["deathlink"], state["locked"], right)
        if notices != drawn["notices"]:
            drawn["notices"] = notices
            drawn["notices_height"] = self.render_notices(moves, right)
        strip = self.toast_strip()
        toasts =(state["toasts"][0]._replace(expires=None) if state["toasts"] else None,
                  tuple(round(v, 3) for v in strip) if strip else None, drawn["notices_height"], layout["window"])
        if toasts != drawn["toasts"]:
            drawn["toasts"] = toasts
            drawn["toasts_height"] = self.render_toasts(moves)
        buttons = self.buttons()
        alerts = (state["status"], tuple(label for label, _ in buttons), state["deathlink"] is not None,
                  bool(state["locked"]), str(state["menu"]))
        if alerts != drawn["alerts"]:
            drawn["alerts"] = alerts
            drawn["alerts_height"] = self.render_alerts(moves, buttons)
            self.render_menu(moves)
        if self.guide:  # the whole left column under its header
            self.guide.fit(screens.clamp(below(layout["left"], drawn["alerts_height"]), layout["screen"]),
                           layout["screen"])
        padlocks = (state["padlocks"], state["board_padlocks"], layout["window"])
        if padlocks != drawn["padlocks"]:
            drawn["padlocks"] = padlocks
            self.render_padlocks()
        for panel, rect in sorted(moves, key=lambda move: move[0] in (self.alert_box, self.notice_box)):  # grow last
            if rect is None:
                self.wanted.discard(panel)
                continue
            self.wanted.add(panel)
            geometry = screens.geometry(screens.clamp(rect, layout["screen"]))  # never off the monitor
            if panel.geometry() != geometry:  # leave an unchanged window alone
                panel.geometry(geometry)
        self.sync_visibility()

    def buttons(self) -> list:
        """(label, action) for the buttons in the alert box (the list and pop-ups let clicks through): the tracker
        (user: "on the permanent top-left overlay"), the Item Guide when it's closed, and hiding the list."""
        state = self.state
        # it never closes the tracker, only brings it up (owner, 2026-11-11); its own window has the close button
        buttons = [("Tracker", self.tracker.open)] if self.tracker.data else []
        if self.guide:  # any time, not only in a shop; the same button closes it (owner, 2026-10-01)
            buttons.append(("Item Guide" if self.guide.hidden else "Hide guide", self.toggle_guide))
        if state["menu"]:
            buttons.append(("Show heroes" if self.menu_hidden else "Hide heroes", self.toggle_menu))
        return buttons

    def toggle_guide(self, _=None) -> bool:
        """Opens or closes the Item Guide with a short fade (owner, 2026-10-01: "a simple transition")."""
        if not self.guide or self.guide_fading:
            return False
        win = self.guide.win
        if self.guide.hidden:
            win.attributes("-alpha", 0.0)
            self.guide.show()  # the next render shows it; the fade brings it up
            self.fade(win, 0.0, self.overlay_factor())
        else:
            self.fade(win, float(win.attributes("-alpha")), 0.0, then=self.guide.close)
        return True

    def fade(self, window, start: float, end: float, then: Optional[Callable] = None, step: int = 0) -> None:
        self.guide_fading = step < FADE_STEPS
        window.attributes("-alpha", start + (end - start) * step / FADE_STEPS)
        if step < FADE_STEPS:
            self.root.after(FADE_MS, self.fade, window, start, end, then, step + 1)
        elif then:
            then()

    def new_menu(self, value) -> bool:
        if not value:  # left the menu: next time it shows again
            self.menu_hidden = False
        self.state["menu"] = value
        return True

    def toggle_menu(self) -> None:
        self.menu_hidden = not self.menu_hidden

    def render_menu(self, moves: list) -> None:
        """On the menu - only while none of the game's own screens is open over it (client.menu_data's "covered") -
        a grid of hero tiles like the game's hero select - card, a bar of the checks you've got
        with that hero out of all of them - the picked hero framed gold (red when it can't be
        played), locked heroes dimmed; a warning banner on top, the goal at the bottom. In the centre of the game
        window and click-through, so it never blocks the menu (owner, 2026-10-01)."""
        tk, f, layout, data = self.tk, self.font, self.layout, self.state["menu"]
        if not data or self.menu_hidden or data.get("covered") or self.menu_under_tracker:
            moves.append((self.menu_box, None))
            return
        k = layout["k"]
        bg = SEVERITY["info"]
        frame, show = self.swap(self.menu_box, bg)
        tk.Label(frame, text="HEROES IN THIS MULTIWORLD", fg=ACCENT, bg=bg, font=f(15, "bold")).pack(pady=(0, 6))
        if data["warning"]:
            tk.Label(frame, text=data["warning"], fg=FG, bg=SEVERITY["critical"], font=f(12, "bold"),
                     padx=10, pady=6, wraplength=round(MENU_WIDTH * k)).pack(fill="x", pady=(0, 8))
        elif data.get("note"):
            tk.Label(frame, text=data["note"], fg=FG, bg=SEVERITY["ok"], font=f(11, "bold"), padx=10, pady=5,
                     wraplength=round(MENU_WIDTH * k)).pack(fill="x", pady=(0, 8))
        grid = tk.Frame(frame, bg=bg)
        grid.pack()
        bar_width, bar_height = round(MENU_TILE * k) - 8, max(4, round(6 * k))
        for index, hero in enumerate(data["heroes"]):
            picked = hero["name"] == data["picked"]
            ring = (WARN if data["warning"] else ACCENT) if picked else bg
            tile = tk.Frame(grid, bg=bg, highlightthickness=max(2, round(3 * k)), highlightbackground=ring,
                            padx=4, pady=4)
            tile.grid(row=index // MENU_COLUMNS, column=index % MENU_COLUMNS, padx=4, pady=4, sticky="n")
            picture = self.hero_picture(hero["name"], k)
            if picture is None:  # a hero added by a patch, with no card cut yet: just the name
                tk.Label(tile, text=hero["name"], fg=FG if hero["unlocked"] else DIM, bg=bg,
                         font=f(10, "bold")).pack()
            else:  # the card carries the hero's name already
                width, height = picture.width(), picture.height()
                card = tk.Canvas(tile, width=width, height=height, bg=bg, highlightthickness=0)
                card.pack()
                card.create_image(0, 0, image=picture, anchor="nw")
                if not hero["unlocked"]:  # dimmed, with the cards' padlock on it
                    card.create_rectangle(0, 0, width, height, fill="#000000", stipple="gray50", width=0)
                    lock = round(min(width, height) * 0.45)
                    padlock_shape(card, (width - lock) / 2, (height - lock) / 2, lock)
            cards = tk.Label(tile, text=f"Cards {hero['cards_unlocked']} / {hero['cards']}", fg=MUTED, bg=bg,
                             font=f(9))
            if not hero["unlocked"]:
                tk.Label(tile, text="LOCKED", fg=WARN, bg=bg, font=f(9, "bold")).pack(pady=(2, 0))
                cards.pack()
                continue
            check_bar(tk, tile, bar_width, bar_height, hero["done"], hero["total"], ACCENT).pack(pady=(2, 0))
            tk.Label(tile, text=f"{hero['done']} / {hero['total']} checks", fg=MUTED, bg=bg, font=f(9)).pack()
            cards.pack()
        bypasses = f"   ·   Lock Bypasses: {data['bypasses']}" if data["bypasses"] else ""
        goal = tk.Frame(frame, bg=bg)
        goal.pack(pady=(6, 0))
        tk.Label(goal, text=f"Goal: {data['won']} / {data['required']} heroes won{bypasses}", fg=MUTED, bg=bg,
                 font=f(10)).pack(side="left")
        if data.get("shields"):
            draw_shields(tk, goal, data["shields"], max(MIN_FONT + 2, round(16 * self.layout["k"])),
                         bg).pack(side="left", padx=(6, 0))
        show()
        self.menu_box.update_idletasks()
        width, height = self.menu_box.winfo_reqwidth(), self.menu_box.winfo_reqheight()
        x, y, w, h = layout["window"]
        self.menu_rect = (x + (w - width) // 2, y + (h - height) // 2, width, height)
        moves.append((self.menu_box, self.menu_rect))

    def hero_picture(self, hero: str, k: float):
        """The hero's portrait for the menu panel (the tracker's cards), sized for the window; None if missing."""
        key = (hero, k < 0.9)
        if key not in self.hero_pictures:
            from .tracker import card_image
            self.hero_pictures[key] = card_image(self.tk, self.root, hero, half=True)
            if self.hero_pictures[key] is not None and k < 0.9:
                self.hero_pictures[key] = self.hero_pictures[key].subsample(2)
        return self.hero_pictures[key]

    def toast_picture(self, key: str, height: int):
        """A pop-up's picture at this row height: a hero's card, or any picture in the set (a card's, a merchant's,
        an event's, an item's symbol) made at exactly that height; None while it isn't ready yet - the "art"
        command redraws the pop-up once it is. No pictures without the Item Guide's picture cache."""
        cached = self.toast_pictures.get((key, height))
        if cached is not None:
            return cached
        if key.startswith("hero:"):
            from .tracker import card_image
            image = card_image(self.tk, self.root, key[len("hero:"):], half=False)
            picture = image.subsample(max(1, -(-image.height() // height))) if image is not None else None
        else:
            if not self.overlay.art_cache_dir:
                return None
            from .cardart import CardArt, framed
            art = self.toast_art.get(height)
            if art is None:
                art = self.toast_art[height] = CardArt(self.overlay.art_cache_dir, height,
                                                       lambda guid: self.overlay.commands.put(("art", guid)))
            data = art.picture(framed(key), False)
            picture = self.tk.PhotoImage(data=data, master=self.root) if data else None  # from memory
        if picture is not None:
            self.toast_pictures[(key, height)] = picture
        return picture

    @staticmethod
    def toast_shape(key: str) -> float:
        """A picture's width / height before it's made: a hero's card, else as cardart makes it (a card's by its
        size, a framed one by its frame, else square)."""
        if key.startswith("hero:"):
            return 170 / 209
        from .cardart import picture_shape
        return picture_shape(key)

    def toast_plan(self, toast: "Toast", area: Tuple[int, int], widest: int, max_rows: int = 2) -> Tuple[int, int]:
        """(rows, picture height) for a pop-up: as big as its box's picture area (width, height) allows
        (toast_fit); below the smallest size, as wide as they need up to `widest` (the box widens), smaller only
        past that. Heights come from TOAST_SIZES."""
        k, (width, height) = self.layout["k"], area
        gap = max(2, round(TOAST_GAP * k))
        shapes = [self.toast_shape(key) for key in toast.cards]
        smallest = TOAST_ROW * k
        rows, tall = toast_fit(shapes, width, height, gap, max_rows)
        if tall < smallest and shapes:  # wider instead of smaller, as far as it may go
            rows, tall = toast_fit(shapes, widest, height, gap, max_rows)
            tall = min(tall, smallest)
        return rows, next((round(s * TOAST_ROW * k) for s in TOAST_SIZES if s * TOAST_ROW * k <= tall),
                          round(TOAST_SIZES[-1] * TOAST_ROW * k))

    def toast_layout(self, pictures: list, rows: int) -> Tuple[list, int]:
        """These pictures in those rows, and the width they need."""
        gap = max(2, round(TOAST_GAP * self.layout["k"]))
        layout, span = toast_rows([p.width() for p in pictures], gap, rows)
        return [[pictures[i] for i in row] for row in layout], span

    def warm_hero_cards(self, heroes: list) -> None:
        """The heroes' cards decoded ahead, one per HERO_WARM_STEP_MS, so the Tracker and the menu panel open at
        once (tracker.card_image keeps them)."""
        if heroes:
            from .tracker import card_image
            card_image(self.tk, self.root, heroes[0], half=True)
            self.root.after(HERO_WARM_STEP_MS, self.warm_hero_cards, heroes[1:])

    def toast_strip(self) -> Optional[tuple]:
        """Where pop-ups sit, as fractions of the game window: the board's strip (memreader.BoardUI.toast_strip),
        and on the main menu - where the game drops the board - the last one read in a run, so they stay exactly
        where they are in a run (owner 2026-11-12: "Keep the same EXACT positioning of the popups in run"; that spot
        is free on the menu). None before any run this session: the bottom of the right column then."""
        strip = getattr(self.board_ui, "toast_strip", None)
        last = getattr(self, "last_toast_strip", None)
        if strip and (last is None or any(abs(a - b) > 0.002 for a, b in zip(strip, last))):
            self.last_toast_strip = strip
            save_strip(getattr(getattr(self, "overlay", None), "overlay_file", None), strip)
        return strip or last

    def toast_frame(self, toast: "Toast") -> dict:
        """Where a pop-up goes and how big its pictures are, before any picture is made: its strip on screen,
        the gap, the header's font and height, the inner and outer height, rows and picture size, and the top when
        it reaches down to the window's bottom (None at its resting height)."""
        layout, k = self.layout, self.layout["k"]
        gap = max(2, round(TOAST_GAP * k))
        font = self.font(TOAST_HEADER, "bold")
        line = int(self.root.tk.call("font", "metrics", font, "-linespace"))  # no named font made
        strip = self.toast_strip()
        strip = padlocks.to_screen(strip, layout["window"]) if strip else None
        frame_width = 2 * (PAD + BORDER) + 4 * gap
        resting = (strip[2] - strip[0]) if strip else layout["right"][2]
        bounds = self.toast_bounds()
        widest = (bounds[1] - bounds[0] if strip else layout["right"][2]) - frame_width
        # the header as it will wrap in the resting width (wider only ever means fewer lines): a long one pushed the
        # pictures off the bottom (2026-11-12, "RECEIVED a LOCK BYPASS from ...! Use it on ...")
        text_height = line * text_lines(lambda text: int(self.root.tk.call("font", "measure", font, text)),
                                        toast.text, resting - frame_width)
        inner = round(max(text_height, line) + 2 * TOAST_ROW * k + 3 * gap)
        height = inner + 2 * (PAD + BORDER)
        rows, size = self.toast_plan(toast, (resting - frame_width, inner - text_height - 3 * gap), widest)
        # the top never moves above the resting box's (a one-line header's): more height only ever goes down, never
        # onto the health bar (owner 2026-11-12: grow to the bottom of the screen, never above the health bar)
        top = round(strip[1] - (line + 2 * TOAST_ROW * k + 3 * gap + 2 * (PAD + BORDER)) / 2) if strip else None
        if strip and toast.cards and size < TOAST_TALL * TOAST_ROW * k:  # small pictures: down to the bottom
            window = layout["window"]
            tall_inner = window[1] + window[3] - top - 2 * (PAD + BORDER)
            tall_rows, tall_size = self.toast_plan(toast, (resting - frame_width, tall_inner - text_height - 3 * gap),
                                                   widest, TOAST_TALL_ROWS)
            if tall_size > size:
                rows, size, inner, height = tall_rows, tall_size, tall_inner, tall_inner + 2 * (PAD + BORDER)
        return dict(strip=strip, gap=gap, font=font, inner=inner, height=height, rows=rows, size=size, top=top,
                    bounds=bounds)

    def toast_bounds(self) -> Tuple[int, int]:
        """How far left and right a pop-up may reach: between the overlay's side columns, never over them (owner,
        2026-11-12: "no overlay should be able to sit on another overlay")."""
        left, right = self.layout["left"], self.layout["right"]
        gap = WINDOW_GAP
        return left[0] + left[2] + gap, right[0] - gap

    def toast_images(self, toast: "Toast", size: int) -> list:
        """Its pictures at that height; None for each not made yet (asking makes it: new_art says when)."""
        return [self.toast_picture(key, size) for key in toast.cards]

    def render_toasts(self, moves: list) -> int:
        """The pop-up showing now (the queue's first): over your hero portrait and skills, a header and its pictures
        (owner, 2026-11-12) - drawn once, when all its pictures are ready (or after TOAST_WAIT); until then nothing
        shows and its time doesn't run (next_toast). Returns its height."""
        tk, layout = self.tk, self.layout
        if not self.state["toasts"]:
            moves += [(self.toast_box, None), (self.toast_content, None)]
            return 0
        toast = self.state["toasts"][0]
        plan = self.toast_frame(toast)
        pictures = self.toast_images(toast, plan["size"])
        key = toast._replace(expires=None)
        started = self.toast_waiting.setdefault(key, time.monotonic())
        if None in pictures and time.monotonic() - started < TOAST_WAIT:
            self.toast_shown = None
            moves += [(self.toast_box, None), (self.toast_content, None)]
            return 0
        rows, span = self.toast_layout([p for p in pictures if p is not None], plan["rows"])
        gap, height, inner = plan["gap"], plan["height"], plan["inner"]
        needed = span + 4 * gap + 2 * (PAD + BORDER)
        place = toast_place(plan["strip"], layout["right"], layout["window"], height, needed, plan["bounds"])
        if plan["top"] is not None:  # on the strip: the resting box's top, whatever its height
            place = (place[0], plan["top"], place[2], height)
        bg = TRAP_BG if toast.trap else SEVERITY["critical" if toast.warning else "ok"]
        width = place[2] - 2 * (PAD + BORDER)
        frame, show = self.swap(self.toast_box, bg)
        draw_toast_background(tk, frame, width, inner, bg, toast.good).pack()
        show()
        # the content window has no frame: its padding is the background's padding plus its border, so they line up
        content = self.toast_content
        content.configure(bg=bg)
        content.attributes("-transparentcolor", bg)
        old = content.winfo_children()
        holder = tk.Frame(content, bg=bg, padx=PAD + BORDER, pady=PAD + BORDER)
        canvas = draw_toast_content(tk, holder, width, inner, bg, TRAP_TITLE if toast.trap else FG, toast.text,
                                    plan["font"], rows, gap)
        canvas.pack()
        canvas.images = [p for row in rows for p in row]  # Tk forgets images nobody holds on to
        holder.pack()
        for child in old:
            child.destroy()
        moves += [(self.toast_box, place), (self.toast_content, place)]
        if self.toast_shown != key:  # another unlock: see-through until it's painted, shown or not (REVEAL_SECONDS)
            for window in (self.toast_box, self.toast_content):
                self.reveal(window)
        self.toast_shown = key
        self.toast_waiting.pop(key, None)
        return height

    def notice_severity(self) -> str:
        state = self.state
        return "critical" if state["deathlink"] or (state["locked"] and state["locked"][2]) else "warning"

    def render_notices(self, moves: list, right: tuple) -> int:
        """The top of the right column: a DeathLink to act on, locked cards you hold (with Use Bypass), Sell Traps.
        Returns its height (0 when there's nothing)."""
        tk, state, f = self.tk, self.state, self.font
        inner_w = right[2] - 2 * (PAD + BORDER)
        if not (state["deathlink"] or state["locked"]):
            moves.append((self.notice_box, None))
            return 0
        trap = bool(state["locked"] and state["locked"][3])
        danger = bool(state["locked"] and len(state["locked"]) > 4 and state["locked"][4])
        bg = TRAP_BG if trap or danger else SEVERITY[self.notice_severity()]
        frame, show = self.swap(self.notice_box, bg)
        band = max(14, round(22 * self.layout["k"]))  # the flames' height
        if danger:  # owner, 2026-11-09: the same notice, "bolder and surrounded by flames"
            draw_flame_band(tk, frame, inner_w, band, bg).pack(fill="x")
        if state["deathlink"]:
            tk.Label(frame, text="DEATHLINK", fg=ACCENT, bg=bg, font=f(16, "bold")).pack(anchor="w")
            tk.Label(frame, text=state["deathlink"], fg=FG, bg=bg, font=f(11), wraplength=inner_w,
                     justify="left").pack(anchor="w")
            tk.Label(frame, text="Concede your current run.", fg=FG, bg=bg,
                     font=f(11, "bold"), wraplength=inner_w, justify="left").pack(anchor="w", pady=(2, 6))
        if state["locked"]:
            title, cards, blocked = state["locked"][:3]
            head = tk.Frame(frame, bg=bg)
            head.pack(fill="x", pady=(6 if state["deathlink"] else 0, 2 if cards else 0))
            room = inner_w
            if trap:  # owner, 2026-10-01: "more menacing ... like a skull with a flame behind it"
                skull = draw_skull(tk, head, max(40, round(64 * self.layout["k"])), bg)
                skull.pack(side="left", padx=(0, 8))
                room -= skull.winfo_reqwidth() + 8
            colour = WARN if danger else (WARN if blocked else TRAP_TITLE) if trap else ACCENT
            tk.Label(head, text=title, fg=colour, bg=bg, font=f(18 if danger else 16 if trap else 14, "bold"),
                     wraplength=room, justify="left").pack(side="left", anchor="w")
            if len(cards) > MAX_ALERT_LINES:  # the box would grow past its share and hide its own buttons
                cards = cards[:MAX_ALERT_LINES - 1] + [f"+ {len(cards) - MAX_ALERT_LINES + 1} more"]
            for line in cards:  # cleared automatically when the log says it was sold
                text, guid = line if isinstance(line, tuple) else (line, None)
                if not guid:
                    loud = danger and line is cards[0]  # the warning's own line (client.update_block_banner)
                    tk.Label(frame, text=text, fg=WARN if loud else FG, bg=bg, font=f(13, "bold") if loud else f(11),
                             wraplength=inner_w, justify="left").pack(anchor="w")
                    continue
                card = tk.Frame(frame, bg=bg)
                card.pack(fill="x")
                use = tk.Button(card, text="Use Bypass", font=f(9, "bold"), padx=4, pady=0,
                                command=lambda g=guid: self.overlay.on_bypass and self.overlay.on_bypass(g))
                use.pack(side="right", anchor="n", padx=(4, 0))
                use.update_idletasks()
                tk.Label(card, text=text, fg=FG, bg=bg, font=f(11), wraplength=inner_w - use.winfo_reqwidth() - 8,
                         justify="left").pack(side="left", anchor="w")
        if danger:
            draw_flame_band(tk, frame, inner_w, band, bg).pack(fill="x", pady=(4, 0))
        show()
        x, y, width, height = right
        top = round(NOTICE_TOP * self.layout["k"])  # below the settings gear (NOTICE_TOP)
        return self.place(moves, self.notice_box, (x, y + top, width, height // ALERT_SHARE))

    def render_alerts(self, moves: list, buttons: list) -> int:
        """The left column's header: the status line with the buttons (Item Guide, Tracker, the list) on its right;
        the buttons get a row of their own only when that would squeeze the text below half the width. Returns its
        height (0 when hidden)."""
        tk, state, inner_w, f = self.tk, self.state, self.layout["inner_w"], self.font
        if not (state["status"] or buttons):
            moves.append((self.alert_box, None))
            return 0
        status = state["status"] if state["status"] and not state["status"][2] else None  # big: the menu panel
        if not (status or buttons):
            moves.append((self.alert_box, None))
            return 0
        bg = SEVERITY["warning" if status and status[1] else "info"]
        frame, show = self.swap(self.alert_box, bg)
        row = tk.Frame(frame, bg=bg)
        row.pack(fill="x")
        bar = tk.Frame(row, bg=bg)
        for label, action in buttons:
            tk.Button(bar, text=label, font=f(8), padx=3, pady=0,
                      command=lambda a=action: (a(), self.render())).pack(side="left", padx=(4, 0))
        bar.update_idletasks()
        room = inner_w - (bar.winfo_reqwidth() + 8 if buttons else 0)
        own_row = bool(status) and room < inner_w // 2
        if buttons:
            bar.pack(side="bottom" if own_row else "right", anchor="e", pady=(4, 0) if own_row else 0)
        if status:
            text, warning, big, shields = (*status, 0)[:4]
            size = max(MIN_FONT + 2, round(16 * self.layout["k"]))
            room -= (size + round(size * 0.45) * (shields - 1) + 6) if shields else 0
            tk.Label(row, text=text, fg=WARN if warning else (FG if big else MUTED), bg=bg,
                     font=f(12 if big else 11 if warning else 10, "bold" if warning or big else "normal"),
                     wraplength=inner_w if own_row else room, justify="left").pack(side="left", anchor="w")
            if shields:
                draw_shields(tk, row, shields, size, bg).pack(side="left", anchor="w", padx=(6, 0))
        show()
        x, y, width, strip_height = self.layout["left"]
        return self.place(moves, self.alert_box, (x, y, width, strip_height // ALERT_SHARE))

    def render_padlocks(self) -> None:
        """The padlocks wanted now: one window each, sized for the game window (placed by place_padlocks)."""
        layout, value = self.layout, self.state["padlocks"]
        self.locks = list(value or ()) + list(self.state["board_padlocks"] or ())
        size = max(MIN_PADLOCK, round(PADLOCK * layout["k"]))
        while len(self.padlocks) < len(self.locks):
            self.padlocks.append(self.new_padlock())
        for padlock, lock in zip(self.padlocks, self.locks):
            if padlock.drawn_size != (size, lock.marker, lock.kind):
                self.draw_padlock(padlock, size, lock.marker, lock.kind)
        self.padlocks_wanted = len(self.locks)
        self.place_padlocks()
        self.padlock_alphas = []  # set afresh: a moved padlock may be covered (or not) where it is now
        self.apply_padlock_alphas(self.covers())

    def place_padlocks(self) -> None:
        """Each padlock on its card, wherever the card is now (padlocks.spot), and followed from there (follower.py).
        A padlock never shown yet is placed by Tk: Windows gives its window the handle the follower moves only once
        it's first shown (wm frame, checked 2026-11-12)."""
        size = max(MIN_PADLOCK, round(PADLOCK * self.layout["k"]))
        self.lock_squares = [padlocks.spot(lock, self.board_ui, self.layout["window"], size) for lock in self.locks]
        handles = []
        for padlock, square in zip(self.padlocks, self.lock_squares):
            if not getattr(padlock, "handle", 0) and padlock.winfo_ismapped():
                frame = int(padlock.wm_frame(), 16)
                padlock.handle = frame if frame != padlock.winfo_id() else 0
            handles.append(getattr(padlock, "handle", 0))
            if not handles[-1] and square is not None:
                padlock.geometry(screens.geometry(screens.clamp((round(square[0]), round(square[1]), size, size),
                                                                self.layout["screen"])))
        followed = [(lock, handle) for lock, handle in zip(self.locks, handles) if handle]
        self.follower.follow(follower.Plan(tuple(lock for lock, _ in followed), tuple(h for _, h in followed),
                                           self.board_ui, self.layout["window"], size, self.layout["screen"]))
        self.place_why()

    def place_why(self) -> None:
        """Under a right-clicked locked card or event: "Locked behind: <the item that unlocks it>" (owner, 2026-11-10),
        placed from the card's own rect in memory (padlocks.inspected). Hidden the rest of the time."""
        line = padlocks.inspected(self.locks, self.lock_squares, self.board_ui, self.layout["window"]) \
            if self.game_in_front else None
        box = getattr(self, "why_box", None)
        if line is None:
            if box is not None and box.state() == "normal":
                box.withdraw()
            return
        if box is None:
            box = self.why_box = self.tk.Toplevel(self.root)
            box.withdraw()
            box.overrideredirect(True)
            box.attributes("-topmost", True)
            screens.never_focus(box)
            box.label = self.tk.Label(box, fg=FG, bg=SEVERITY["info"], padx=PAD, pady=PAD // 2)
            box.label.pack()
        text, centre_x, top = line
        box.label.configure(text=text, font=self.font(12, "bold"))
        box.update_idletasks()
        width, height = box.winfo_reqwidth(), box.winfo_reqheight()
        spot = screens.clamp((round(centre_x - width / 2), round(top + PAD), width, height), self.layout["screen"])
        if getattr(box, "spot", None) != spot:
            box.spot = spot
            box.geometry(screens.geometry(spot))
        if box.state() != "normal":
            box.deiconify()
            box.lift()
            screens.click_through(box)  # the inspect view stays clickable under it

    def new_padlock(self):
        padlock = self.tk.Toplevel(self.root)
        padlock.withdraw()
        padlock.overrideredirect(True)
        padlock.attributes("-topmost", True)
        padlock.configure(bg=PADLOCK_KEY)
        padlock.attributes("-transparentcolor", PADLOCK_KEY)  # only the padlock itself shows
        screens.never_focus(padlock)
        padlock.canvas = self.tk.Canvas(padlock, bg=PADLOCK_KEY, highlightthickness=0, bd=0)
        padlock.canvas.pack(fill="both", expand=True)
        padlock.drawn_size = 0
        padlock.attributes("-alpha", 0.0)  # until apply_padlock_alphas says otherwise
        return padlock

    def draw_padlock(self, padlock, s: int, marker: Optional[str] = None, kind: str = "lock") -> None:
        """A padlock, an AP marker (padlocks.Padlock.marker: the Archipelago logo on a square of its colour), or the
        Sell Trap's burning skull (Padlock.kind "sell_trap": in the trap's flames on its dark tile, like its pop-up
        symbol, so it reads on any card)."""
        canvas = padlock.canvas
        canvas.delete("all")
        canvas.configure(width=s, height=s)
        if marker:
            from .tracker import COLORS  # the Tracker's green and yellow (one palette)
            canvas.create_rectangle(1, 1, s - 1, s - 1, fill=COLORS.get(marker, COLORS["green"]), outline="black",
                                    width=max(2, s // 20))
            logo = self.ap_logo(s)
            if logo is not None:
                canvas.create_image(s // 2, s // 2, image=logo)
            else:  # no logo file: the letters
                canvas.create_text(s // 2, s // 2, text="AP", fill="black", font=(FONT, -max(10, s // 3), "bold"))
        elif kind == "sell_trap":
            from .tracker import icon_image
            canvas.create_oval(1, 1, s - 1, s - 1, fill=TRAP_BG, outline=OUTLINE, width=max(2, s // 20))
            skull = icon_image(self.tk, self.root, "sell_trap", FLAMES[0][1], round(s * SKULL_SHARE), shade=1.0)
            if skull is not None:
                canvas.create_image(s // 2, s // 2, image=skull)
        else:
            padlock_shape(canvas, 0, 0, s)
        padlock.drawn_size = (s, marker, kind)

    def ap_logo(self, s: int):
        """Archipelago's own logo (its data/icon.png, shipped with every Archipelago - nothing of ours, nothing
        downloaded), shrunk to fit an AP marker of size s; None if it can't be read."""
        logos = self.__dict__.setdefault("ap_logos", {})
        if s not in logos:
            try:
                import Utils  # Archipelago's
                full = logos.get("full") or self.tk.PhotoImage(master=self.root,
                                                              file=Utils.local_path("data", "icon.png"))
                logos["full"] = full
                logos[s] = full.subsample(max(1, -(-full.width() // round(s * 0.78))))
            except Exception:  # an install without it: the marker shows "AP"
                logos[s] = None
        return logos[s]

    # --- commands and the loop --------------------------------------------------------------------------------

    def set_state(self, kind: str, value) -> bool:
        self.state[kind] = value
        return True

    def new_padlocks(self, value) -> bool:  # (padlocks, since, wait for the reveal)
        pending = self.pending_padlocks
        if pending and pending[2] and value[0] == pending[0]:  # the same cards again while they wait for their flip
            return False  # (the shop's log line refreshes them): they keep waiting - a "not new" repeat showed them
            # on face-down cards, ~0.9 s before the flip (live test 2026-11-12)
        self.pending_padlocks, self.reveal_started = value, False
        if not self.show_due_padlocks() and self.state["padlocks"]:
            self.state["padlocks"] = None  # the old cards' padlocks go at once (user: they lingered on a reroll)
        return True

    def new_board_ui(self, ui) -> bool:
        was, now = self.board_ui, time.monotonic()
        revealing, was_revealing = ui is not None and ui.revealing, was is not None and was.revealing
        if revealing and not was_revealing:
            self.reveal_began = now
        elif was_revealing and not revealing:
            self.reveal_ended = now
        self.board_ui = ui
        cleared = False
        if ui is not None and ui.dealing and not (was is not None and was.dealing) and self.state["padlocks"]:
            self.state["padlocks"] = None  # a reroll's old cards dissolve now: their padlocks go with them (clip)
            cleared = True
        return self.show_due_padlocks() or cleared

    def show_due_padlocks(self) -> bool:
        """The latest padlocks once they may show (a newer command replaces one still waiting). New cards: as each
        turns face-up (owner, 2026-10-14: not while face-down, when only size and rarity show, and not after, when
        the player could buy before noticing). The game's reveal flag starts as the card backs swirl in; the first
        card turns FLIP_DELAY later and the rest padlocks.FLIP_STAGGER apart (clips, 2026-10-14). Items that don't flip
        (rewards, events) are up when the flag ends, so whichever comes first. If no reveal starts within
        FLIP_SECONDS (or the flag can't be read), after FLIP_SECONDS. A dialog still hides them (padlock_look)."""
        if not self.pending_padlocks:
            return False
        value, since, reveal = self.pending_padlocks
        ui, now = self.board_ui, time.monotonic()
        if ui and ui.revealing or self.reveal_began >= since - FLIP_EARLY:
            self.reveal_started = True
        elif self.reveal_ended > self.reveal_began >= since - FLIP_SECONDS:  # a flip that's already over when the
            self.reveal_started = True  # padlocks came in: its cards are face-up, so no wait (was a full FLIP_SECONDS,
            # 2026-11-12, F3)
        self.stagger_from = 0.0
        if reveal and self.reveal_started:
            ended = self.reveal_ended > self.reveal_began
            if not ended and now < self.reveal_began + FLIP_DELAY:
                return False
            if not ended:
                self.stagger_from = self.reveal_began + FLIP_DELAY
        elif reveal and now - since < FLIP_SECONDS:
            return False
        self.state["padlocks"], self.pending_padlocks = value, None
        return True

    def new_art(self, guid: str) -> bool:
        """A picture is ready: the guide shows it; a queued pop-up loads it now (so drawing it later costs nothing);
        the first one, still waiting, is drawn once its last picture is in (render_toasts)."""
        if self.guide:
            self.guide.refresh(guid)
        for toast in self.state["toasts"]:
            if guid in toast.cards and toast._replace(expires=None) in self.toast_sizes:
                self.toast_picture(guid, self.toast_sizes[toast._replace(expires=None)])
        toasts = self.state["toasts"]
        if toasts and guid in toasts[0].cards and self.toast_shown != toasts[0]._replace(expires=None):
            self.drawn["toasts"] = None
            return True
        return False

    def new_toast(self, value: "Toast") -> bool:
        """Queued behind the others (owner, 2026-11-12); the one showing stays until its time is up. Its pictures
        are asked for now, while it waits, so it's ready when its turn comes."""
        self.state["toasts"] = self.state["toasts"] + [value]  # never dropped (owner: show ALL of them)
        if value.cards:
            size = self.toast_sizes[value._replace(expires=None)] = self.toast_frame(value)["size"]
            self.toast_images(value, size)
        return True

    def new_tracker_data(self, data) -> bool:
        first = not self.tracker.data
        self.tracker.update(data)
        return first  # the Tracker button appears once there's something to track

    def own_windows(self) -> Set[int]:
        windows = self.panels + self.padlocks
        return {screens.window_handle(w) for w in windows} | set(self.tracker.windows()) | \
            set(self.guide.windows() if self.guide else [])

    def tracker_covers_menu(self) -> bool:
        """The open Tracker overlaps where the menu panel goes."""
        win = self.tracker.win
        if not (self.menu_rect and self.state["menu"] and self.tracker.is_open() and win.winfo_ismapped()):
            return False
        return overlaps(self.menu_rect, (win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()))

    def poll(self) -> None:
        """Runs every POLL_MS in the Tk thread. An error is logged and the loop carries on - a stopped loop would
        leave the windows frozen for the rest of the session."""
        try:
            if self.tick() == "quit":
                return
        except Exception:
            logger.exception("Overlay error (it keeps going)", extra=FILE_ONLY)  # never the GUI from this thread
        self.root.after(POLL_MS, self.poll)

    def tick(self) -> Optional[str]:
        """One round: the queued commands, where the game is, and a redraw if anything changed. "quit" once the
        windows are gone."""
        overlay, changed = self.overlay, False
        started = time.perf_counter()
        while time.perf_counter() - started < COMMAND_BUDGET:  # the rest waits for the next round, in order
            try:
                kind, value = overlay.commands.get_nowait()
            except queue.Empty:
                break
            if kind == "quit":
                if self.guide:
                    self.guide.shutdown()
                self.hero_pictures.clear()  # images are freed here, in Tk's own thread, not at exit from another
                self.toast_pictures.clear()
                self.root.destroy()
                return "quit"
            changed = bool(self.handlers[kind](value)) or changed
        changed = self.show_due_padlocks() or changed
        now = time.monotonic()
        changed = self.next_toast(now) or changed
        game, window = game_in_front(self.own_windows()) if overlay.only_over_game else (True, overlay.game_window)
        if window and window != self.layout["window"]:  # the game window moved, was resized or changed resolution
            self.relayout(window)
            self.drawn.update(alerts=None, shop=None, toasts=None)  # everything is laid out again
            changed = True
        self.ours_in_front = game is None  # you're using one of our windows (the Item Guide and its lists, ...)
        if game is not None and game != self.game_in_front:
            self.game_in_front = game
            self.sync_visibility()
        under = self.tracker_covers_menu()
        if under != self.menu_under_tracker:
            self.menu_under_tracker = under
            self.drawn["alerts"] = None  # the menu panel is drawn with the header
            changed = True
        if self.guide and self.game_in_front and not self.guide.hidden and self.guide.win.state() == "iconic":
            self.guide.win.deiconify()  # Windows minimised it along with something else: it belongs on screen
        if changed:
            self.render()
        else:
            self.keep_on_top()
        self.trace_menu()

    def trace_menu(self) -> None:
        """To the client's log file: why the menu's hero panel shows or not, and whether the game sits above it,
        whenever that changes (2026-11-12: after a run the panel stayed away though the button said "Hide heroes")."""
        data, box = self.state["menu"], self.menu_box
        why = ("no menu data" if not data else "hidden by button" if self.menu_hidden
               else "game screen open (covered)" if data.get("covered") else "under the tracker"
               if self.menu_under_tracker else "wanted")
        shown = box.state() == "normal"
        above = None
        if shown and sys.platform == "win32":
            import ctypes
            from .memreader import game_window
            game, hwnd = game_window(), screens.window_handle(box)
            above = False
            while hwnd:  # walk up the z-order from the panel: is the game's window above it?
                hwnd = ctypes.windll.user32.GetWindow(hwnd, 3)  # GW_HWNDPREV
                if game and hwnd == game[0]:
                    above = True
                    break
        trace = (why, shown, above, self.game_in_front, self.overlay_factor())
        if trace != getattr(self, "menu_trace", None):
            self.menu_trace = trace
            logger.info(f"Hero panel: {why}, window {'shown' if shown else 'hidden'}"
                        f"{', the game is ABOVE it' if above else ''}, game in front {self.game_in_front}, "
                        f"fade {self.overlay_factor()}", extra=FILE_ONLY)

    def next_toast(self, now: float) -> bool:
        """The queue moves on: the pop-up showing goes when its time is up, and the next one's time starts when it
        shows (toast_seconds, counting everything waiting then). True when what shows changed."""
        toasts = self.state["toasts"]
        # hidden (the game not in front, or a dialog, the Esc menu or a loading screen): the clock stops, so no pop-up
        # runs out unseen (owner 2026-11-16: "make sure the popup ... if hidden from a loading screen or something the
        # timer pauses"). The pop-up sits on the game window (your hero strip), so a dialog always hides it
        # (dialog_hides)
        hidden = not getattr(self, "game_in_front", True) or getattr(getattr(self, "board_ui", None), "dialog", False)
        last, self.toast_clock = getattr(self, "toast_clock", now), now
        if hidden:
            if toasts and toasts[0].expires is not None:
                self.state["toasts"] = [toasts[0]._replace(expires=toasts[0].expires + now - last)] + toasts[1:]
            return False
        moved = False
        if toasts and toasts[0].expires is not None and toasts[0].expires <= now:
            toasts = self.state["toasts"] = toasts[1:]
            moved = True  # always a change: the next one must be drawn, or the old drawing stays (owner 2026-11-12:
            # a pack's pop-up "not going away" - the queue had moved on to one never drawn)
        if toasts and toasts[0].expires is None:
            head = toasts[0]
            if self.toast_shown != head._replace(expires=None):  # not drawn yet: its pictures are coming
                started = self.toast_waiting.get(head._replace(expires=None))
                if started is not None and now - started >= TOAST_WAIT:  # time's up: draw it anyway
                    self.drawn["toasts"] = None
                    return True
                return moved
            self.state["toasts"] = [head._replace(expires=now + toast_seconds(len(toasts), head.good))] + toasts[1:]
            self.toast_sizes.pop(head._replace(expires=None), None)
            return True
        return moved

    def keep_on_top(self) -> None:
        """Games sometimes take the top spot; the shown windows claim it back - but not while you're using one of
        ours: claiming it lifted the Item Guide over its own open Merchant/Size/Rarity list every POLL_MS, so the
        list vanished at once (owner's video, 2026-11-11)."""
        if self.ours_in_front:
            return
        for panel in self.panels:
            if panel.state() == "normal":
                panel.attributes("-topmost", True)
        if self.guide and self.guide.win.state() == "normal":
            self.guide.win.attributes("-topmost", True)
        for padlock in self.padlocks:
            if padlock.state() == "normal":
                padlock.attributes("-topmost", True)
