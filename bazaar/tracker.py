"""
The integrated tracker (user, 2026-09-29): a PopTracker-style window with a card per hero and four squares on it -
reach day N, PvP win on day N, monster checks (a row per day: Bronze .. Legendary), 10 wins.

A square's colour is its best remaining check, the PopTracker way: green = in logic, yellow = out of logic (doable,
but logic expects more of the hero's cards first), red = not possible yet (hero locked), grey = all done. Hovering a
square shows its checks; clicking keeps that list open until clicked again.

It only draws what the client hands it (see BazaarContext.tracker_data); the logic lives in locations.py. It runs
in the overlay's Tk thread and needs no Pillow: the hero cards are small PNGs that Tk reads by itself.
"""
import base64
import pkgutil
from typing import Callable, Dict, List, Optional

from . import screens
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
    try:
        data = pkgutil.get_data(__name__, f"data/heroes/{hero_key(hero)}.png")
    except OSError:
        return None  # a hero added by a patch before its card was cut: drawn as a plain card
    image = tk.PhotoImage(master=root, data=base64.b64encode(data))  # this Tk, not whichever started first
    return image.subsample(2) if half else image


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
        self.images: Dict[str, object] = {}  # Tk forgets images nobody holds on to
        self.popup = None
        self.popup_for: Optional[tuple] = None  # (hero, kind) the list shows
        self.popup_checks: list = []  # what it shows, to redraw it only when that changes
        self.popup_at: Optional[tuple] = None  # where it is (x, y)
        self.pinned = False

    # --- opening -----------------------------------------------------------------------------------------------

    def is_open(self) -> bool:
        return bool(self.win) and self.win.state() == "normal"

    def toggle(self) -> None:
        if self.is_open():
            self.close()
        else:
            self.open()

    def windows(self) -> List[int]:
        """Window handles of the tracker and its list (so using them doesn't count as leaving the game)."""
        return [screens.window_handle(w) for w in (self.win, self.popup) if w is not None and w.winfo_exists()]

    def set_visible(self, game_in_front: bool) -> None:
        """A pinned list floats on top of everything, so it hides with the overlay when you leave the game (the
        tracker itself is a normal window and stays)."""
        if self.popup:
            if game_in_front and self.popup.state() != "normal":
                self.popup.deiconify()
            elif not game_in_front and self.popup.state() == "normal":
                self.popup.withdraw()

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
                self.win, self.squares, self.canvases, self.half = None, {}, {}, True
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
        size = SQUARE // scale
        for index, hero in enumerate(hero_order()):
            if hero not in self.images:
                self.images[hero] = card_image(tk, self.root, hero, self.half)
            image = self.images[hero]
            width, height = (image.width(), image.height()) if image else (CARD_SIZE[0] // scale,
                                                                           CARD_SIZE[1] // scale)
            canvas = tk.Canvas(self.win, width=width, height=height, bg=WINDOW_BG, highlightthickness=0)
            canvas.grid(row=index // CARDS_PER_ROW, column=index % CARDS_PER_ROW, padx=4, pady=4)
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
            for kind, *_ in SQUARES:
                status = square_status([c[4] for c in self.checks(hero, kind)]) if info and info["in_seed"] \
                    else None
                canvas.itemconfigure(kind, state="hidden" if status is None else "normal")
                if status:
                    canvas.itemconfigure(self.squares[hero, kind], fill=COLORS[status])
        if self.popup_for and self.checks(*self.popup_for) != self.popup_checks:
            self.show_popup(*self.popup_for, keep_position=True)

    def checks(self, hero: str, kind: str) -> list:
        return [c for c in (self.data.get(hero) or {}).get("checks", []) if c[0] == kind]

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
