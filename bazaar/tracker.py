"""
The integrated tracker (user, 2026-09-29): a PopTracker-style window with a card per hero and four squares on it.

    1  Reach day N      2  PvP win on day N      3  monster checks (a row per day: Bronze .. Legendary)
    4  10 wins

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

TIERS = ("Bronze", "Silver", "Gold", "Diamond", "Legendary")
COLORS = {"green": "#3fbf4f", "yellow": "#e8c53a", "red": "#d9443b", "done": "#6f6f6f"}
BG = "#16141c"
FG = "#f2f2f2"
DONE_FG = "#8a8a8a"
SQUARE = 34
CARD_ORDER = ["Dooley", "Pygmalien", "Vanessa", "Mak", "Jules", "Karnok", "The Dragons", "Stelle"]
SQUARE_NAMES = {1: "Reach day N", 2: "PvP win on day N", 3: "Monster checks", 4: "10 wins"}
SQUARE_KINDS = {1: "day", 2: "pvp", 3: "monster", 4: "win"}


def square_status(statuses: List[str]) -> Optional[str]:
    """The colour of a square: its best check still to do, or "done" when nothing is left. None: no checks."""
    if not statuses:
        return None
    for status in ("green", "yellow", "red"):
        if status in statuses:
            return status
    return "done"


def card_image(tk, root, hero: str, half: bool):
    data = pkgutil.get_data(__name__, f"data/heroes/{hero.lower().replace(' ', '_')}.png")
    if not data:
        return None
    image = tk.PhotoImage(master=root, data=base64.b64encode(data))  # this Tk, not whichever started first
    return image.subsample(2) if half else image


class Tracker:
    """The window. Built on first open; update() redraws the squares and any open list in place."""

    def __init__(self, tk, root, screen: Callable[[], tuple]) -> None:
        self.tk, self.root = tk, root
        self.screen = screen  # the monitor the game is on: where the tracker first opens
        self.half = False  # half-size cards, for screens too small for the full-size window
        self.win = None
        self.data: Dict[str, dict] = {}
        self.squares: Dict[tuple, int] = {}  # (hero, square) -> canvas rectangle id
        self.canvases: Dict[str, object] = {}
        self.images: Dict[str, object] = {}  # Tk forgets images nobody holds on to
        self.popup = None
        self.popup_for: Optional[tuple] = None  # (hero, square) the list shows
        self.pinned = False

    # --- opening -----------------------------------------------------------------------------------------------

    def toggle(self) -> None:
        if self.win and self.win.state() == "normal":
            self.close()
        else:
            self.open()

    def is_open(self) -> bool:
        return bool(self.win) and self.win.state() == "normal"

    def windows(self) -> List[int]:
        """Window handles of the tracker and its list (so using them doesn't count as leaving the game)."""
        from .overlay import window_handle
        return [window_handle(w) for w in (self.win, self.popup) if w is not None and w.winfo_exists()]

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
            if self.win.winfo_reqwidth() > area[2] * 0.95 or self.win.winfo_reqheight() > area[3] * 0.9:
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
        self.update(self.data)

    def close(self) -> None:
        self.hide_popup()
        if self.win:
            self.win.withdraw()

    def build(self) -> None:
        tk = self.tk
        self.win = tk.Toplevel(self.root)
        self.win.title("The Bazaar - Archipelago Tracker")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        size = SQUARE // 2 if self.half else SQUARE
        for index, hero in enumerate(CARD_ORDER):
            image = self.images.setdefault(hero, card_image(tk, self.root, hero, self.half))
            width, height = (image.width(), image.height()) if image else ((85, 105) if self.half else (170, 210))
            canvas = tk.Canvas(self.win, width=width, height=height, bg=BG, highlightthickness=0)
            canvas.grid(row=index // 4, column=index % 4, padx=4, pady=4)
            if image:
                canvas.create_image(0, 0, image=image, anchor="nw")
            canvas.create_rectangle(0, 0, width, height, fill="black", stipple="gray50", outline="",
                                    tags="dim", state="hidden")
            canvas.create_text(width // 2, int(height * 0.2), text="", fill=FG, tags="note", width=width - 10,
                               font=("Segoe UI", 8 if self.half else 10, "bold"), justify="center")
            # squares 1 2 3 on the first row, 4 below 1 - over the portrait, above the name banner
            gap = size // 4
            left, top = (width - 3 * size - 2 * gap) // 2, int(height * 0.36)
            spots = {1: (left, top), 2: (left + size + gap, top), 3: (left + 2 * (size + gap), top),
                     4: (left, top + size + gap)}
            for square, (x, y) in spots.items():
                rect = canvas.create_rectangle(x, y, x + size, y + size, width=2, outline="black",
                                               tags=f"square{square}")
                canvas.create_text(x + size // 2, y + size // 2, text=str(square), fill="black",
                                   font=("Segoe UI", 8 if self.half else 13, "bold"), tags=f"square{square}")
                self.squares[hero, square] = rect
                canvas.tag_bind(f"square{square}", "<Enter>", lambda e, h=hero, s=square: self.hover(h, s, e))
                canvas.tag_bind(f"square{square}", "<Leave>", lambda e: self.unhover())
                canvas.tag_bind(f"square{square}", "<Button-1>", lambda e, h=hero, s=square: self.click(h, s, e))
            self.canvases[hero] = canvas
        tk.Label(self.win, text="green = in logic   yellow = out of logic   red = not possible yet   grey = done   "
                                "(hover a square, click to keep it open)",
                 bg=BG, fg=DONE_FG, font=("Segoe UI", 9)).grid(row=2, column=0, columnspan=4, pady=(0, 6))

    # --- drawing -----------------------------------------------------------------------------------------------

    def update(self, data: Dict[str, dict]) -> None:
        """data: hero -> {"in_seed": bool, "unlocked": bool, "checks": [(kind, day, tier, name, status)]}"""
        self.data = data or {}
        if not self.win:
            return
        for hero, canvas in self.canvases.items():
            info = self.data.get(hero)
            note = "" if info and info["in_seed"] else "Not in this seed"
            if info and info["in_seed"] and not info["unlocked"]:
                note = "LOCKED"
            canvas.itemconfigure("dim", state="normal" if note else "hidden")
            canvas.itemconfigure("note", text=note)
            for square in range(1, 5):
                status = square_status(self.statuses(hero, square)) if info and info["in_seed"] else None
                canvas.itemconfigure(f"square{square}", state="hidden" if status is None else "normal")
                if status:
                    canvas.itemconfigure(self.squares[hero, square], fill=COLORS[status])
        if self.popup_for:
            self.show_popup(*self.popup_for, keep_position=True)

    def checks(self, hero: str, square: int) -> list:
        info = self.data.get(hero) or {}
        return [c for c in info.get("checks", []) if c[0] == SQUARE_KINDS[square]]

    def statuses(self, hero: str, square: int) -> List[str]:
        return [c[4] for c in self.checks(hero, square)]

    # --- hover / click lists -----------------------------------------------------------------------------------

    def hover(self, hero: str, square: int, event) -> None:
        if not self.pinned:
            self.show_popup(hero, square, event)

    def unhover(self) -> None:
        if not self.pinned:
            self.hide_popup()

    def click(self, hero: str, square: int, event) -> None:
        if self.pinned and self.popup_for == (hero, square):
            self.pinned = False
            self.hide_popup()
        else:
            self.pinned = True
            self.show_popup(hero, square, event)

    def hide_popup(self) -> None:
        if self.popup:
            self.popup.destroy()
        self.popup, self.popup_for = None, None

    def show_popup(self, hero: str, square: int, event=None, keep_position: bool = False) -> None:
        tk = self.tk
        position = self.popup.geometry().split("+", 1)[1] if keep_position and self.popup else None
        self.hide_popup()
        self.popup_for = (hero, square)
        popup = self.popup = tk.Toplevel(self.win)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=BG, highlightthickness=2, highlightbackground="#ffcf5a")
        pinned = "  (click the square again to close)" if self.pinned else "  (click to keep open)"
        tk.Label(popup, text=f"{hero} - {SQUARE_NAMES[square]}{pinned}", bg=BG, fg="#ffcf5a",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=8, pady=(6, 4))
        body = tk.Frame(popup, bg=BG)
        body.pack(anchor="w", padx=8, pady=(0, 8))
        checks = self.checks(hero, square)
        if square == 3:
            self.monster_grid(body, checks)
        else:
            columns = 2 if len(checks) > 12 else 1
            rows = -(-len(checks) // columns)
            for index, (kind, day, tier, name, status) in enumerate(checks):
                label = "10 wins" if kind == "win" else f"Day {day}"
                self.entry(body, label, status).grid(row=index % rows, column=index // rows, sticky="w", padx=(0, 16))
        popup.update_idletasks()
        width, height = popup.winfo_reqwidth(), popup.winfo_reqheight()
        if position:
            x, y = self.parse(position)
        elif event is not None:
            x, y = event.x_root + 16, event.y_root + 12
        else:
            x, y = self.win.winfo_rootx(), self.win.winfo_rooty()
        popup.geometry(screens.geometry(screens.clamp((x, y, width, height), self.monitor())))  # never off screen

    @staticmethod
    def parse(position: str) -> tuple:
        """ "X+Y" from a Tk geometry (either may be negative, e.g. "-1500+20") -> (x, y)."""
        import re
        x, y = re.fullmatch(r"(-?\d+)\+(-?\d+)", position).groups()
        return int(x), int(y)

    def entry(self, parent, text: str, status: str):
        tk = self.tk
        row = tk.Frame(parent, bg=BG)
        tk.Label(row, bg=COLORS[status], width=2, relief="solid", bd=1).pack(side="left", padx=(0, 6), pady=1)
        font = ("Segoe UI", 10, "overstrike") if status == "done" else ("Segoe UI", 10)
        tk.Label(row, text=text, bg=BG, fg=DONE_FG if status == "done" else FG, font=font).pack(side="left")
        return row

    def monster_grid(self, parent, checks: list) -> None:
        """A row per day that has monster checks; columns Bronze .. Legendary (blank where that day has none)."""
        tk = self.tk
        by_day: Dict[int, Dict[str, str]] = {}
        for kind, day, tier, name, status in checks:
            by_day.setdefault(day, {})[tier] = status
        for column, tier in enumerate(TIERS, start=1):
            tk.Label(parent, text=tier, bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).grid(row=0, column=column, padx=3)
        for row, day in enumerate(sorted(by_day), start=1):
            tk.Label(parent, text=f"Day {day}", bg=BG, fg=FG, font=("Segoe UI", 10)).grid(row=row, column=0,
                                                                                         sticky="w", padx=(0, 8))
            for column, tier in enumerate(TIERS, start=1):
                status = by_day[day].get(tier)
                if status:
                    tk.Label(parent, bg=COLORS[status], width=3, relief="solid", bd=1,
                             text="✓" if status == "done" else "", fg=FG).grid(row=row, column=column,
                                                                                   padx=3, pady=1)
