"""
The integrated tracker (user, 2026-09-29): a PopTracker-style window with a card per hero and four squares on it -
reach day N, PvP win on day N, monster checks (a row per day: Bronze .. Legendary), 10 wins - each with its icon
(ICONS, owner 2026-11-13), and under its card the menu panel's check bar (check_bar) and the hero's checks done / all
and cards unlocked / all (the menu panel's numbers, client.hero_counts).

A square's colour is its best remaining check, the PopTracker way: green = in logic, yellow = out of logic (doable,
but logic expects more of the hero's cards first), red = not possible yet (hero locked), grey = all done. Hovering a
square shows its checks; clicking keeps that list open until clicked again.

It only draws what the client hands it (see BazaarContext.tracker_data); the logic lives in locations.py. It runs
in the overlay's Tk thread and needs no Pillow: the hero cards are small PNGs that Tk reads by itself.
"""
import base64
import json
import pkgutil
import zlib
from typing import Callable, Dict, List, NamedTuple, Optional

from . import screens
from .cardart import fit_rgba, png
from .data import HEROES, TIERS, hero_key
from .theme import ACCENT, DIM, FONT, WINDOW_BG

COLORS = {"green": "#3fbf4f", "yellow": "#e8c53a", "red": "#d9443b", "done": "#6f6f6f"}
FG = "#f2f2f2"
# The squares, in reading order: (check kind, what the list is called, column, row on the card). Adding a square
# is one entry here.
SQUARES = (("day", "Reach day N", 0, 0), ("pvp", "PvP win on day N", 1, 0), ("monster", "Monster checks", 2, 0),
           ("win", "10 wins", 0, 1))
SQUARE = 34  # a square's size on a full-size card
CARD_SIZE = (170, 210)  # a full-size card (tools/make_hero_cards.py), also for a hero with no picture yet
CARD_ORDER = ["Dooley", "Pygmalien", "Vanessa", "Mak", "Jules", "Karnok", "The Dragons", "Stelle"]  # the picture
CARDS_PER_ROW = 4
NOTE_AT, SQUARES_AT = 0.2, 0.36  # "LOCKED" and the squares, as a share of the card's height (above the name)
FIT_WIDTH, FIT_HEIGHT = 0.95, 0.9  # the window must fit this share of the screen, else half-size cards
POPUP_OFFSET = (16, 12)  # the list opens this far right of and below the pointer (or mirrored, near an edge)
LIST_ROWS = 12  # more checks than this: the list gets two columns
BAR_BG = "#3a3f4b"  # the empty part of a hero's check bar (check_bar)
BAR_HEIGHT = 6  # px, a full-size card's check bar
# Each square's icon (owner 2026-11-13: "pvp wins (Swoards clashing), day reached (Sunrise), monsters (Snake jaw
# unhinged or something), and 10 wins (Trophy)"): game-icons.net silhouettes (tools/make_tracker_icons.py, credited in
# README.md), in data/icons.json by square kind, drawn in the square's own colour made darker - its shadow (owner
# 2026-11-16: "a shade darker than the background of the squares color and kind of like a shadow")
ICON_SHADE = 0.6  # an icon's colour: its square's at this brightness
ICON_PAD = 0.12  # an icon's margin inside its square, as a share of the square
_ICONS: Dict[str, object] = {}  # data/icons.json, read once


def icon_masks() -> dict:
    """data/icons.json: {"size": n, "icons": {kind: zlib'd base64 of n*n see-through bytes}}."""
    if not _ICONS:
        _ICONS.update(json.loads(pkgutil.get_data(__name__, "data/icons.json").decode("utf-8")))
    return _ICONS


def icon_pixels(kind: str, colour: str, size: int, shade: float = ICON_SHADE):
    """The icon for `kind` (a square's, or "sell_trap") in `colour` at `shade` brightness (a square's icon: its
    shadow), size x size, see-through around it (cardart Pixels, RGBA); None if the data has no such icon."""
    data = icon_masks()
    packed = data["icons"].get(kind)
    if packed is None:
        return None
    n, alpha = data["size"], zlib.decompress(base64.b64decode(packed))
    rgb = bytes(round(int(colour[i:i + 2], 16) * shade) for i in (1, 3, 5))
    return fit_rgba((n, n, b"".join(rgb + bytes((a,)) for a in alpha)), size, size)


def icon_image(tk, root, kind: str, colour: str, size: int, shade: float = ICON_SHADE):
    """icon_pixels as a Tk picture, made once per Tk window (kept on the root, like card_image)."""
    cache = root.__dict__.setdefault("bazaar_icons", {})
    key = (kind, colour, size, shade)
    if key not in cache:
        pixels = icon_pixels(kind, colour, size, shade)
        cache[key] = tk.PhotoImage(master=root, data=base64.b64encode(png(pixels))) if pixels else None
    return cache[key]


def check_bar(tk, parent, width: int, height: int, done: int, total: int, fill: str):
    """A hero's check bar: the checks you've got with this hero, of all of them (owner, 2026-10-01: "that bar should
    represent how many checks I have gotten with her"). One drawing for the menu's hero panel and the Tracker (owner
    2026-11-13: the Tracker shows the same, "similar to the hero guide on the main menu")."""
    bar = tk.Canvas(parent, width=width, height=height, bg=BAR_BG, highlightthickness=0)
    bar.create_rectangle(0, 0, 0, height, fill=fill, width=0, tags="done")
    fill_bar(bar, done, total)
    return bar


def fill_bar(bar, done: int, total: int) -> None:
    """Set a check bar (check_bar) to done of total."""
    width, height = int(bar["width"]), int(bar["height"])
    bar.coords("done", 0, 0, round(width * done / max(1, total)), height)


class TrackedCheck(NamedTuple):
    """One check as the tracker shows it (client.tracker_data builds them)."""
    kind: str
    day: int
    tier: str
    name: str
    status: str  # done / green / yellow / red


def square_status(statuses: List[str]) -> Optional[str]:
    """The colour of a square: its best check still to do, or "done" when nothing is left. None: no checks."""
    if not statuses:
        return None
    for status in ("green", "yellow", "red"):
        if status in statuses:
            return status
    return "done"


def hero_order() -> List[str]:
    """The heroes as on the hero-select screen (the picture's order); any hero added later goes at the end."""
    return [h for h in CARD_ORDER if h in HEROES] + [h for h in HEROES if h not in CARD_ORDER]


def card_image(tk, root, hero: str, half: bool):
    """A hero's card, full or half size - decoded once per Tk window (kept on the root, so it goes with it): the
    Tracker, the menu panel and hero pop-ups share it, and the overlay decodes them ahead (2026-11-12: the Tracker's
    first open spent 33 ms of its 117 decoding them)."""
    cache = root.__dict__.setdefault("bazaar_hero_cards", {})
    if (hero, half) not in cache:
        if (hero, False) not in cache:
            try:
                data = pkgutil.get_data(__name__, f"data/heroes/{hero_key(hero)}.png")
                # this Tk, not whichever started first
                cache[(hero, False)] = tk.PhotoImage(master=root, data=base64.b64encode(data))
            except OSError:
                cache[(hero, False)] = None  # a hero added by a patch before its card was cut: a plain card
        full = cache[(hero, False)]
        cache[(hero, True)] = full.subsample(2) if full is not None else None
    return cache[(hero, half)]


class Tracker:
    """The window. Built on first open; update() recolours the squares and refreshes an open list only if it
    changed."""

    def __init__(self, tk, root, screen: Callable[[], tuple]) -> None:
        self.tk, self.root = tk, root
        self.screen = screen  # the monitor the game is on: where the tracker first opens
        self.half = False  # half-size cards, for screens too small for the full-size window
        self.win = None
        self.data: Dict[str, dict] = {}
        self.squares: Dict[tuple, int] = {}  # (hero, kind) -> canvas rectangle id
        self.canvases: Dict[str, object] = {}
        self.counts: Dict[str, object] = {}  # hero -> the label under its card
        self.bars: Dict[str, object] = {}  # hero -> its check bar, above that label (check_bar)
        self.icons: Dict[tuple, int] = {}  # (hero, kind) -> its square's icon on the hero's canvas
        self.square_size = SQUARE
        self.images: Dict[str, object] = {}  # Tk forgets images nobody holds on to
        self.popup = None
        self.dialog_hid = False  # the tracker withdrew for a game dialog (set_visible) and comes back after it
        self.popup_for: Optional[tuple] = None  # (hero, kind) the list shows
        self.popup_checks: list = []  # what it shows, to redraw it only when that changes
        self.popup_at: Optional[tuple] = None  # where it is (x, y)
        self.pinned = False

    # --- opening -----------------------------------------------------------------------------------------------

    def is_open(self) -> bool:
        return bool(self.win) and self.win.state() == "normal"

    def windows(self) -> List[int]:
        """Window handles of the tracker and its list (so using them doesn't count as leaving the game)."""
        return [screens.window_handle(w) for w in (self.win, self.popup) if w is not None and w.winfo_exists()]

    def set_visible(self, game_in_front: bool, dialog_hides: Callable[[object], bool] = lambda window: False) -> None:
        """A pinned list floats on top of everything, so it hides with the overlay when you leave the game (the
        tracker itself is a normal window and stays). A game dialog hides either only while it sits on the game
        window (dialog_hides: owner 2026-11-16, "if I have the tracker open and it is on a seperate monitor there s no
        reason to hide it"); withdrawn, not see-through, so it can't catch the dialog's clicks."""
        if self.popup:
            show = game_in_front and not dialog_hides(self.popup)
            if show and self.popup.state() != "normal":
                self.popup.deiconify()
            elif not show and self.popup.state() == "normal":
                self.popup.withdraw()
        if self.win is not None and self.win.winfo_exists():
            if dialog_hides(self.win):
                if self.win.state() == "normal":
                    self.win.withdraw()
                    self.dialog_hid = True
            elif self.dialog_hid:
                self.dialog_hid = False
                self.win.deiconify()

    def monitor(self) -> tuple:
        """The monitor the tracker is on (or the game's, before it's placed)."""
        if self.win and self.win.winfo_ismapped():
            rect = (self.win.winfo_rootx(), self.win.winfo_rooty(), self.win.winfo_width(), self.win.winfo_height())
            return screens.monitor_for(rect, screens.monitors()) or self.screen()
        return self.screen()

    def open(self) -> None:
        if not self.win:
            area = self.screen()
            self.build()
            self.win.update_idletasks()
            if self.win.winfo_reqwidth() > area[2] * FIT_WIDTH or self.win.winfo_reqheight() > area[3] * FIT_HEIGHT:
                self.win.destroy()  # too big for this screen: half-size cards
                self.win, self.squares, self.canvases, self.counts, self.bars, self.half = None, {}, {}, {}, {}, True
                self.icons = {}
                self.images.clear()
                self.build()
                self.win.update_idletasks()
            width, height = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
            x, y = area[0] + (area[2] - width) // 2, area[1] + (area[3] - height) // 3
            self.win.geometry(screens.geometry(screens.clamp((x, y, width, height), area)))
        self.win.deiconify()
        self.win.lift()
        self.win.update_idletasks()
        # wherever it is (first time: centred on the game's monitor), its whole frame stays on a monitor -
        # also when reopened after that monitor was unplugged
        seen = screens.visible_bounds(self.win)
        if seen:
            area = screens.monitor_for(seen, screens.monitors()) or self.screen()
            if screens.clamp(seen, area) != seen:
                screens.settle(self.win, seen, area)
        self.draw()

    def close(self) -> None:
        self.hide_popup()
        if self.win:
            self.win.withdraw()

    def build(self) -> None:
        tk = self.tk
        self.win = tk.Toplevel(self.root)
        self.win.title("The Bazaar - Archipelago Tracker")
        self.win.configure(bg=WINDOW_BG)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        scale = 2 if self.half else 1
        size = self.square_size = SQUARE // scale
        for index, hero in enumerate(hero_order()):
            if hero not in self.images:
                self.images[hero] = card_image(tk, self.root, hero, self.half)
            image = self.images[hero]
            width, height = (image.width(), image.height()) if image else (CARD_SIZE[0] // scale,
                                                                           CARD_SIZE[1] // scale)
            cell = tk.Frame(self.win, bg=WINDOW_BG)
            cell.grid(row=index // CARDS_PER_ROW, column=index % CARDS_PER_ROW, padx=4, pady=4)
            canvas = tk.Canvas(cell, width=width, height=height, bg=WINDOW_BG, highlightthickness=0)
            canvas.pack()
            # the menu panel's check bar (owner 2026-11-13: "similar to the hero guide on the main menu"), shown in
            # draw while the hero is in the seed and unlocked, like the menu's
            self.bars[hero] = check_bar(tk, cell, width - 8, max(3, BAR_HEIGHT // scale), 0, 1, ACCENT)
            # checks done and own cards unlocked, under the card (owner 2026-11-13; the menu panel's numbers)
            self.counts[hero] = tk.Label(cell, text="", bg=WINDOW_BG, fg=DIM, font=(FONT, 8 if self.half else 9))
            self.counts[hero].pack()
            if image:
                canvas.create_image(0, 0, image=image, anchor="nw")
            else:
                canvas.create_rectangle(2, 2, width - 2, height - 2, outline=ACCENT, width=2)
                canvas.create_text(width // 2, height - 24 // scale, text=hero, fill=FG,
                                   font=(FONT, 12 // scale, "bold"))
            canvas.create_rectangle(0, 0, width, height, fill="black", stipple="gray50", outline="",
                                    tags="dim", state="hidden")
            canvas.create_text(width // 2, int(height * NOTE_AT), text="", fill=FG, tags="note", width=width - 10,
                               font=(FONT, 8 if self.half else 10, "bold"), justify="center")
            gap = size // 4
            left, top = (width - 3 * size - 2 * gap) // 2, int(height * SQUARES_AT)
            for kind, _, column, row in SQUARES:
                x, y = left + column * (size + gap), top + row * (size + gap)
                self.squares[hero, kind] = canvas.create_rectangle(x, y, x + size, y + size, width=2,
                                                                   outline="black", tags=kind)
                # its icon: drawn in draw(), in the square's colour (icon_image), tagged like the square for hovering
                self.icons[hero, kind] = canvas.create_image(x + size / 2, y + size / 2, tags=kind)
                canvas.tag_bind(kind, "<Enter>", lambda e, h=hero, k=kind: self.hover(h, k, e))
                canvas.tag_bind(kind, "<Leave>", lambda e: self.unhover())
                canvas.tag_bind(kind, "<Button-1>", lambda e, h=hero, k=kind: self.click(h, k, e))
            self.canvases[hero] = canvas
        tk.Label(self.win, text="green = in logic   yellow = out of logic   red = not possible yet   grey = done   "
                                "(hover a square, click to keep it open)",
                 bg=WINDOW_BG, fg=DIM, font=(FONT, 9)).grid(row=CARDS_PER_ROW, column=0, columnspan=CARDS_PER_ROW,
                                                           pady=(0, 6))

    # --- drawing -----------------------------------------------------------------------------------------------

    def update(self, data: Dict[str, dict]) -> None:
        """data: hero -> {"in_seed": bool, "unlocked": bool, "checks": [(kind, day, tier, name, status)]}.
        Nothing is redrawn when nothing changed."""
        data = data or {}
        if data == self.data:
            return
        self.data = data
        self.draw()

    def draw(self) -> None:
        if not self.win:
            return
        for hero, canvas in self.canvases.items():
            info = self.data.get(hero)
            note = "" if info and info["in_seed"] else "Not in this seed"
            if info and info["in_seed"] and not info["unlocked"]:
                note = "LOCKED"
            canvas.itemconfigure("dim", state="normal" if note else "hidden")
            canvas.itemconfigure("note", text=note)
            counted = info and info["in_seed"] and "total" in info
            self.counts[hero].configure(text=f"{info['done']} / {info['total']} checks  ·  {info['cards_unlocked']} / "
                                             f"{info['cards']} cards" if counted else "")
            bar = self.bars[hero]
            if counted and info["unlocked"]:
                fill_bar(bar, info["done"], info["total"])
                if not bar.winfo_ismapped():
                    bar.pack(before=self.counts[hero], pady=(2, 0))
            else:
                bar.pack_forget()
            for kind, *_ in SQUARES:
                status = square_status([c.status for c in self.checks(hero, kind)]) if info and info["in_seed"] \
                    else None
                canvas.itemconfigure(kind, state="hidden" if status is None else "normal")
                if status:
                    canvas.itemconfigure(self.squares[hero, kind], fill=COLORS[status])
                    canvas.itemconfigure(self.icons[hero, kind], image=icon_image(
                        self.tk, self.root, kind, COLORS[status], round(self.square_size * (1 - 2 * ICON_PAD))))
        if self.popup_for and self.checks(*self.popup_for) != self.popup_checks:
            self.show_popup(*self.popup_for, keep_position=True)

    def checks(self, hero: str, kind: str) -> list:
        return [c for c in (self.data.get(hero) or {}).get("checks", []) if c.kind == kind]

    # --- hover / click lists -----------------------------------------------------------------------------------

    def hover(self, hero: str, kind: str, event) -> None:
        if not self.pinned:
            self.show_popup(hero, kind, event)

    def unhover(self) -> None:
        if not self.pinned:
            self.hide_popup()

    def click(self, hero: str, kind: str, event) -> None:
        if self.pinned and self.popup_for == (hero, kind):
            self.pinned = False
            self.hide_popup()
        else:
            self.pinned = True
            self.show_popup(hero, kind, event)

    def hide_popup(self) -> None:
        if self.popup:
            self.popup.destroy()
        self.popup, self.popup_for, self.popup_at = None, None, None

    def show_popup(self, hero: str, kind: str, event=None, keep_position: bool = False) -> None:
        tk = self.tk
        at = self.popup_at if keep_position else None
        self.hide_popup()
        self.popup_for, self.popup_checks = (hero, kind), self.checks(hero, kind)
        popup = self.popup = tk.Toplevel(self.win)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=WINDOW_BG, highlightthickness=2, highlightbackground=ACCENT)
        hint = "  (click the square again to close)" if self.pinned else "  (click to keep open)"
        title = next(name for k, name, *_ in SQUARES if k == kind)
        tk.Label(popup, text=f"{hero} - {title}{hint}", bg=WINDOW_BG, fg=ACCENT,
                 font=(FONT, 10, "bold")).pack(anchor="w", padx=8, pady=(6, 4))
        body = tk.Frame(popup, bg=WINDOW_BG)
        body.pack(anchor="w", padx=8, pady=(0, 8))
        if kind == "monster":
            self.monster_grid(body, self.popup_checks)
        else:
            columns = 2 if len(self.popup_checks) > LIST_ROWS else 1
            rows = -(-len(self.popup_checks) // columns)
            for index, (check_kind, day, _, _, status) in enumerate(self.popup_checks):
                label = "10 wins" if check_kind == "win" else f"Day {day}"
                self.entry(body, label, status).grid(row=index % rows, column=index // rows, sticky="w",
                                                     padx=(0, 16))
        popup.update_idletasks()
        width, height = popup.winfo_reqwidth(), popup.winfo_reqheight()
        area = self.monitor()
        if at:
            x, y = at
        elif event is not None:
            # beside the pointer; near an edge on the other side of it, never under it (that would flicker:
            # the list under the pointer makes it "leave" the square)
            dx, dy = POPUP_OFFSET
            x = event.x_root + dx if event.x_root + dx + width <= area[0] + area[2] else event.x_root - dx - width
            y = event.y_root + dy if event.y_root + dy + height <= area[1] + area[3] else event.y_root - dy - height
        else:
            x, y = self.win.winfo_rootx(), self.win.winfo_rooty()
        x, y, width, height = screens.clamp((x, y, width, height), area)  # never off screen
        self.popup_at = (x, y)
        popup.geometry(screens.geometry((x, y, width, height)))

    def entry(self, parent, text: str, status: str):
        tk = self.tk
        row = tk.Frame(parent, bg=WINDOW_BG)
        tk.Label(row, bg=COLORS[status], width=2, relief="solid", bd=1).pack(side="left", padx=(0, 6), pady=1)
        font = (FONT, 10, "overstrike") if status == "done" else (FONT, 10)
        tk.Label(row, text=text, bg=WINDOW_BG, fg=DIM if status == "done" else FG, font=font).pack(side="left")
        return row

    def monster_grid(self, parent, checks: list) -> None:
        """A row per day that has monster checks; columns Bronze .. Legendary (blank where that day has none)."""
        tk = self.tk
        by_day: Dict[int, Dict[str, str]] = {}
        for _, day, tier, _, status in checks:
            by_day.setdefault(day, {})[tier] = status
        for column, tier in enumerate(TIERS, start=1):
            tk.Label(parent, text=tier, bg=WINDOW_BG, fg=FG, font=(FONT, 9, "bold")).grid(row=0, column=column,
                                                                                         padx=3)
        for row, day in enumerate(sorted(by_day), start=1):
            tk.Label(parent, text=f"Day {day}", bg=WINDOW_BG, fg=FG, font=(FONT, 10)).grid(row=row, column=0,
                                                                                         sticky="w", padx=(0, 8))
            for column, tier in enumerate(TIERS, start=1):
                status = by_day[day].get(tier)
                if status:
                    tk.Label(parent, bg=COLORS[status], width=3, relief="solid", bd=1,
                             text="✓" if status == "done" else "", fg=FG).grid(row=row, column=column,
                                                                                   padx=3, pady=1)
