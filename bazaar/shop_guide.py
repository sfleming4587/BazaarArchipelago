"""
The Shop Guide: pictures of everything the merchant you're at could stock, at their in-game sizes, locked ones
greyed out with a red cross. A real window you can drag anywhere (other monitors too); until you move it, it
follows the strip right of the board. Runs in the overlay's Tk thread and only renders what it's given.

Pictures come from cardart (no Pillow needed); a card without one yet shows a "no picture" box of the same shape.
"""
import json
from typing import Callable, Dict, List, Optional

from . import screens
from .cardart import TIER_COLORS, CardArt, card_shape
from .data import CARDS, CARDS_BY_GUID
from .theme import ACCENT, DIM, FONT, GOOD, LOCKED_X, WARN, WINDOW_BG

TILE_BG = "#1d1a24"  # a card with no picture

CARD_HEIGHT = 96  # every card this tall, 1/2/3 slots wide like in game (see cardart.card_shape)
CARD_PAD = 4  # around each card
HEADER_RESERVE = 170  # header text width left for the Locked only and X buttons beside it
ROW_MARGIN = 24  # a row is closed this far before the edge (borders, names a bit wider than their card)
SAVE_DELAY_MS = 500  # while you drag it, its position is saved once you stop, not on every move
REFLOW_PX = 8  # re-flow the rows only when the width changed by more than this
DEFAULT_WIDTH = 300


def _saved_rect(value) -> Optional[tuple]:
    """A saved position, or None if it isn't exactly four whole numbers (a hand-edited or damaged file)."""
    if isinstance(value, list) and len(value) == 4 and all(isinstance(v, int) for v in value):
        return tuple(value)
    return None


class ShopGuide:
    @classmethod
    def create(cls, tk, root, art_cache_dir: Optional[str], guide_file: Optional[str], area: tuple,
               on_art: Callable[[str], None], on_closed: Callable[[], None]) -> Optional["ShopGuide"]:
        """The guide, or None when it's turned off (no art_cache_dir)."""
        if not art_cache_dir:
            return None
        return cls(tk, root, art_cache_dir, guide_file, area, on_art, on_closed)

    def __init__(self, tk, root, art_cache_dir: str, guide_file: Optional[str], area: tuple,
                 on_art: Callable[[str], None], on_closed: Callable[[], None]) -> None:
        self.tk, self.guide_file, self.on_closed = tk, guide_file, on_closed
        self.art = CardArt(art_cache_dir, CARD_HEIGHT, on_ready=on_art)
        self.art.preload(c for c in CARDS if c.shop)
        saved = self._load()
        self.hidden = bool(saved.get("hidden"))
        self.locked_only = bool(saved.get("locked_only"))  # show only the cards you may not buy
        # Until you move it, it follows the right strip; once moved it stays where you put it (user 2026-09-29:
        # "allow windows to leave the game").
        self.moved_to: Optional[tuple] = _saved_rect(saved.get("moved_to"))
        self.strip: Optional[tuple] = None  # (rect, monitor) of the right strip it follows
        self.fitted: Optional[str] = None  # the geometry our own placing last gave it
        self.placing = False  # True while we move it ourselves (those moves aren't the player dragging it)
        self.pending_save = None
        self.shown = None  # (title, allowed, locked) on screen
        self.cells: Dict[tuple, object] = {}  # (guid, locked) -> the frame showing that card right now
        self.photos: Dict[tuple, object] = {}
        self.width = DEFAULT_WIDTH

        win = self.win = tk.Toplevel(root)
        win.title("Shop Guide - The Bazaar")
        win.configure(bg=WINDOW_BG)
        win.attributes("-topmost", True)
        win.attributes("-toolwindow", True)  # a small title bar with only X: nothing to minimise it by
        win.geometry(screens.geometry(area))
        win.withdraw()  # the overlay shows it, only while the game (or one of its windows) is in front
        win.protocol("WM_DELETE_WINDOW", self.close)
        screens.never_focus(win)  # showing it again (e.g. alt-tab back) must not take the keyboard from the game

        top = tk.Frame(win, bg=WINDOW_BG)
        top.pack(fill="x")
        tk.Button(top, text="X", command=self.close, bg=WINDOW_BG, fg=ACCENT, relief="flat", padx=6).pack(
            side="right")
        self.only = tk.Button(top, text=self.only_label(), command=self.toggle_locked_only, bg=WINDOW_BG, fg=ACCENT,
                              relief="flat", padx=6)
        self.only.pack(side="right")
        self.header = tk.Label(top, bg=WINDOW_BG, fg=ACCENT, font=(FONT, 12, "bold"), anchor="w", padx=10, pady=6,
                               justify="left", wraplength=area[2] - HEADER_RESERVE,
                               text="Shop Guide: open a merchant to see what it can sell")
        self.header.pack(side="left", fill="x")
        self.canvas = tk.Canvas(win, bg=WINDOW_BG, highlightthickness=0)
        scroll = tk.Scrollbar(win, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=WINDOW_BG)
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        win.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Configure>", self.on_resize)
        win.bind("<Configure>", self.on_moved)

    # --- where it is ------------------------------------------------------------------------------------------

    def fit(self, rect: tuple, monitor: tuple) -> None:
        """Follow the right strip (minus any pop-ups below it) - unless you moved it yourself."""
        if self.moved_to or self.strip == (rect, monitor):
            return
        self.strip = (rect, monitor)
        self.header.configure(wraplength=rect[2] - HEADER_RESERVE)
        if self.win.winfo_ismapped():
            self.place_on_screen(monitor)

    def place_on_screen(self, fallback: tuple) -> None:
        """Once shown: where you put it, or the right strip - its visible frame always fully on a monitor."""
        if self.moved_to:
            target = self.moved_to
            area = screens.monitor_for(target, screens.monitors()) or fallback
        elif self.strip:
            target, area = self.strip
        else:
            return
        self.placing = True
        try:
            screens.settle(self.win, target, area)
            self.win.update()  # let the resulting <Configure> events arrive while still flagged
        finally:
            self.placing = False
        self.fitted = self.win.geometry()

    def on_moved(self, event) -> None:
        # <Configure> also fires for child widgets and for our own placing: only the player moving it counts
        if event.widget is not self.win or self.placing or not self.fitted or self.win.state() != "normal" \
                or self.win.geometry() == self.fitted:
            return
        rect = screens.visible_bounds(self.win)
        if rect and rect != self.moved_to:
            self.moved_to = rect
            if self.pending_save:
                self.win.after_cancel(self.pending_save)
            self.pending_save = self.win.after(SAVE_DELAY_MS, self.save)

    # --- open / closed ----------------------------------------------------------------------------------------

    def close(self) -> None:
        self.hidden = True
        self.save()
        self.on_closed()  # the overlay hides it; the locked-card list may use the right strip now

    def show(self) -> None:
        self.hidden = False
        self.save()

    def only_label(self) -> str:
        return "Show all" if self.locked_only else "Locked only"

    def toggle_locked_only(self) -> None:
        self.locked_only = not self.locked_only
        self.save()
        self.only.configure(text=self.only_label())
        if self.shown:
            self.render(self.shown)

    # --- pictures ---------------------------------------------------------------------------------------------

    def picture(self, card, locked: bool):
        """The card's picture, or None if it has none (yet)."""
        key = (card.guid, locked)
        if key not in self.photos:
            path = self.art.picture(card, locked)
            if not path:
                return None
            try:  # master: this window's Tk, never whichever Tk happened to start first in the process
                self.photos[key] = self.tk.PhotoImage(file=path, master=self.win)
            except self.tk.TclError:  # an unreadable file: the placeholder
                return None
        return self.photos[key]

    def placeholder(self, parent, card, locked: bool):
        """In place of a missing picture: a box of the card's in-game shape in its tier colour (red if locked).
        Its name goes under it like a picture's; a 1-slot box is too narrow for many names (measured)."""
        width, height = card_shape(card, CARD_HEIGHT)
        box = self.tk.Frame(parent, width=width, height=height, bg=TILE_BG, highlightthickness=3,
                            highlightbackground=LOCKED_X if locked else TIER_COLORS.get(card.tier, DIM))
        box.pack_propagate(False)
        self.tk.Label(box, text="no\npicture", bg=TILE_BG, fg=DIM, font=(FONT, 7)).pack(expand=True)
        return box

    def refresh(self, guid: str) -> None:
        """A card's picture arrived: swap it in where that card is shown, touching nothing else (rebuilding the
        whole guide for every picture kept Tk from painting while a first shop's pictures streamed in)."""
        for locked in (False, True):
            self.photos.pop((guid, locked), None)
            cell = self.cells.get((guid, locked))
            if cell is not None and cell.winfo_exists():
                for child in cell.winfo_children():
                    child.destroy()
                self.fill(cell, CARDS_BY_GUID[guid], locked)

    def on_resize(self, event) -> None:
        if abs(event.width - self.width) > REFLOW_PX:  # rows are filled by width: re-flow when it really changed
            self.width = event.width
            if self.shown:
                self.render(self.shown, keep_scroll=True)

    # --- drawing ----------------------------------------------------------------------------------------------

    def section(self, parent, title: str, color: str, cards: List, locked: bool, row: int) -> int:
        tk = self.tk
        if not cards:
            return row
        tk.Label(parent, text=title, bg=WINDOW_BG, fg=color, font=(FONT, 11, "bold")).grid(
            row=row, column=0, sticky="w", padx=6, pady=(8, 2))
        row += 1
        line, used = None, 0  # cards go left to right in rows, each as wide as its slots (like the board)
        for card in cards:
            width = card_shape(card, CARD_HEIGHT)[0] + 2 * CARD_PAD
            if line is None or used + width > self.width - ROW_MARGIN:
                line, used = tk.Frame(parent, bg=WINDOW_BG), 0
                line.grid(row=row, column=0, sticky="w", padx=2)
                row += 1
            used += width
            cell = tk.Frame(line, bg=WINDOW_BG, width=width)
            cell.pack(side="left", anchor="n", padx=CARD_PAD, pady=3)
            self.cells[(card.guid, locked)] = cell
            self.fill(cell, card, locked)
        return row

    def fill(self, cell, card, locked: bool) -> None:
        """A card's picture (or a placeholder until it has one) and its name."""
        photo = self.picture(card, locked)
        if photo is None:
            self.placeholder(cell, card, locked).pack()
        else:
            self.tk.Label(cell, image=photo, bg=WINDOW_BG).pack()
        width = card_shape(card, CARD_HEIGHT)[0] + 2 * CARD_PAD
        self.tk.Label(cell, text=card.name, bg=WINDOW_BG, fg=DIM if locked else "#eeeeee", font=(FONT, 8),
                      wraplength=max(40, width - 4), justify="center").pack()

    def render(self, value, keep_scroll: bool = False) -> None:
        """value: (title, allowed cards, locked cards), or None when you left the shop (the last one stays)."""
        if not value:
            if self.shown:
                self.header.configure(text=f"Last shop: {self.shown[0]}")
            return
        self.shown = value
        title, allowed, locked = value
        locked_first = len(locked) < len(allowed)  # the shorter list on top, so it's seen without scrolling
        if not locked:
            note = "nothing locked here"
        elif self.locked_only:
            note = f"{len(locked)} locked"
        elif locked_first:
            note = f"{len(locked)} locked (top)"
        else:
            note = f"{len(allowed)} you can buy (top)"
        self.header.configure(text=f"{title}  |  {note}")
        sections = [(f"You can buy ({len(allowed)})", GOOD, allowed, False),
                    (f"LOCKED - don't buy ({len(locked)})", WARN, locked, True)]
        if self.locked_only:  # just the cards to recognise and avoid
            sections = sections[1:]
        elif locked_first:
            sections.reverse()
        # built in a new frame, then swapped in: the window never shows up empty in between (no flicker)
        old = self.inner.winfo_children()
        frame = self.tk.Frame(self.inner, bg=WINDOW_BG)
        self.cells = {}
        row = 0
        for label, color, cards, is_locked in sections:
            row = self.section(frame, label, color, sorted(cards, key=lambda c: c.name), is_locked, row)
        frame.pack(anchor="nw")
        for child in old:
            child.destroy()
        if not keep_scroll:
            self.canvas.yview_moveto(0)

    # --- saved settings ---------------------------------------------------------------------------------------

    def _load(self) -> dict:
        try:
            with open(self.guide_file, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, TypeError, ValueError):
            return {}

    def save(self) -> None:
        self.pending_save = None
        try:
            with open(self.guide_file, "w", encoding="utf-8") as f:
                json.dump({"hidden": self.hidden, "locked_only": self.locked_only,
                           "moved_to": list(self.moved_to) if self.moved_to else None}, f)
        except (OSError, TypeError):
            pass

    def shutdown(self) -> None:
        self.art.shutdown()
