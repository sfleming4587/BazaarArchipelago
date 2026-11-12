"""
The Shop Guide: card pictures at their in-game sizes, locked ones greyed out with a red cross. A real window you can
drag anywhere (other monitors too); until you move it, it follows the strip right of the board. Runs in the
overlay's Tk thread and only renders what it's given.

Owner, 2026-10-01 ("2, and allow user to open it outside of a shop with the filters ... size, which merchant,
starting rarity, search bar"):
- the cards on offer right now (shop, level-up, an event's items: read from memory) come first, framed in gold;
- below them, what the chosen merchant could stock for your hero - entering a shop picks that merchant - or every
  card with Merchant on Any; Search, Size, Rarity and Merchant narrow it, open or not in a shop.

Pictures come from cardart (no Pillow needed); a card without one yet shows a "no picture" box of the same shape.
"""
import json
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from . import screens
from .cardart import TIER_COLORS, CardArt, card_shape
from .data import CARDS_BY_GUID, MERCHANT_DATA, SHOP_CARDS, TIERS
from .merchants import possible_stock
from .theme import ACCENT, DIM, FG, FONT, GOOD, LOCKED_X, WARN, WINDOW_BG

TILE_BG = "#1d1a24"  # a card with no picture

CARD_HEIGHT = 96  # every card this tall, 1/2/3 slots wide like in game (see cardart.card_shape)
CARD_PAD = 4  # around each card
MIN_GAP = 2  # px between two cards when a row needs the room for one more (owner 2026-11-10: borders shrink, images
#   never; "a minimum border count of a couple pixels")
NORMAL_GAP = 4 * CARD_PAD  # between two cards when there's room (what each card had before)
ROW_PAD = 2  # px left and right of every row
REFLOW_DELAY_MS = 150  # a resize re-flows the rows once it stops, not at every pixel of the drag
HEADER_RESERVE = 170  # header text width left for the Locked only and X buttons beside it
SAVE_DELAY_MS = 500  # while you drag it, its position is saved once you stop, not on every move
FILTER_DELAY_MS = 250  # typing in the search box redraws once you pause
DEFAULT_WIDTH = 300
MAX_SHOWN = 300  # pictures drawn at once; more than that and the filters are needed (Tk slows down)

ANY = "Any"
SIZES = ("Small", "Medium", "Large")
# Merchants by the name you see (a name can belong to several encounters, e.g. a tutorial copy); debug ones never
# show up in real play.
MERCHANTS: Dict[str, List[dict]] = {}
for _merchant in MERCHANT_DATA.values():
    if not _merchant["name"].startswith("[DEBUG]"):
        MERCHANTS.setdefault(_merchant["name"], []).append(_merchant)


def guide_cards(cards: Iterable, hero: Optional[str], merchant: str, text: str, size: str,
                tier: str) -> List:
    """The cards the guide lists, by name: what `merchant` could stock while playing `hero` (Any: every card of
    your hero or Common, every card with no hero), narrowed by the search text (anywhere in the name, any case),
    size and starting rarity."""
    cards = list(cards)
    if merchant != ANY:
        pool = {c.guid: c for m in MERCHANTS.get(merchant, []) for c in possible_stock(m["stock"], hero or "", cards)}
        cards = list(pool.values())
    elif hero:
        cards = [c for c in cards if c.hero in (hero, "Common")]
    text = text.strip().lower()
    return sorted((c for c in cards if text in c.name.lower() and size in (ANY, c.size) and tier in (ANY, c.tier)),
                  key=lambda c: c.name.lower())


def _saved_rect(value) -> Optional[tuple]:
    """A saved position, or None if it isn't exactly four whole numbers (a hand-edited or damaged file)."""
    if isinstance(value, list) and len(value) == 4 and all(isinstance(v, int) for v in value):
        return tuple(value)
    return None


def rows_of(widths: List[int], room: int) -> List[Tuple[int, List[int]]]:
    """Cells of these widths, left to right, in rows of `room` px - laid out like justified text (owner, 2026-11-10:
    "Think of it similar to how text looks in a book"): a row takes every cell that fits with MIN_GAP between them;
    then, unless it's the last row, its gaps grow evenly until its first cell touches the left edge and its last the
    right. The last row (and a row of one) stays on the left with the normal gap, or less if that's all that fits.
    Returns [(cells in the row, the gaps between them)]; never a gap under MIN_GAP, nothing for no cells."""
    rows: List[List[int]] = []
    for width in widths:
        if rows and sum(rows[-1]) + width + MIN_GAP * len(rows[-1]) <= room:
            rows[-1].append(width)
        else:
            rows.append([width])  # also a cell wider than the room: on its own, it can't be helped
    laid = []
    for number, row in enumerate(rows):
        spaces, free = len(row) - 1, room - sum(row)
        if not spaces:
            laid.append((1, []))
            continue
        last = number == len(rows) - 1
        gap = min(NORMAL_GAP, free // spaces) if last else free // spaces
        extra = 0 if last else free - gap * spaces  # the odd pixels, one each to the first gaps
        laid.append((len(row), [max(MIN_GAP, gap + (k < extra)) for k in range(spaces)]))
    return laid


class ShopGuide:
    @classmethod
    def create(cls, tk, root, art_cache_dir: Optional[str], guide_file: Optional[str], area: tuple,
               on_art: Callable[[str], None], on_closed: Callable[[], None],
               on_close_click: Optional[Callable[[], None]] = None) -> Optional["ShopGuide"]:
        """The guide, or None when it's turned off (no art_cache_dir). on_close_click: what its X does (the overlay
        fades it out, like its button); default close()."""
        if not art_cache_dir:
            return None
        return cls(tk, root, art_cache_dir, guide_file, area, on_art, on_closed, on_close_click)

    def __init__(self, tk, root, art_cache_dir: str, guide_file: Optional[str], area: tuple,
                 on_art: Callable[[str], None], on_closed: Callable[[], None],
                 on_close_click: Optional[Callable[[], None]] = None) -> None:
        self.tk, self.guide_file, self.on_closed = tk, guide_file, on_closed
        close_click = on_close_click or self.close
        self.art = CardArt(art_cache_dir, CARD_HEIGHT, on_ready=on_art)
        self.art.preload(SHOP_CARDS)
        saved = self._load()
        self.hidden = bool(saved.get("hidden"))
        self.locked_only = bool(saved.get("locked_only"))  # show only the cards you may not buy
        # Until you move it, it follows the right strip; once moved it stays where you put it (user 2026-09-29:
        # "allow windows to leave the game").
        self.moved_to: Optional[tuple] = _saved_rect(saved.get("moved_to"))
        self.strip: Optional[tuple] = None  # (rect, monitor) of the right strip it follows
        self.fitted: Optional[str] = None  # the geometry our own placing last gave it
        self.placing = False  # True while we move it ourselves (those moves aren't the player dragging it)
        self.pending_save = self.pending_filter = None
        self.cards = SHOP_CARDS  # what it can list (tests give it a few)
        self.hero: Optional[str] = None  # the hero you're playing (or picked on the menu)
        self.locked: Set[str] = set()  # cards you may not hold right now
        self.offer: Optional[Tuple[str, Tuple[str, ...]]] = None  # (title, offered card guids) on screen right now
        # every card offered on this screen so far, bought ones included: always in the list (owner, 2026-10-01: a
        # bought card "should be in the list at the bottom ... otherwise it is missing from the list")
        self.pinned: Dict[str, None] = {}
        # (guid, locked) -> (canvas tag, x, y) of each place showing that card's picture right now (see refresh)
        self.cells: Dict[tuple, List[tuple]] = {}
        self.photos: Dict[tuple, object] = {}
        self.width = DEFAULT_WIDTH
        self.pending_reflow = None
        self.name_widths: Dict[str, int] = {}
        from tkinter import font as tkfont
        self.name_font = tkfont.Font(root=root, family=FONT, size=8)
        self.drawn = None  # what's on screen, so a redraw that changes nothing is skipped

        win = self.win = tk.Toplevel(root)
        win.title("Shop Guide - The Bazaar")
        win.configure(bg=WINDOW_BG)
        win.attributes("-topmost", True)
        win.attributes("-toolwindow", True)  # a small title bar with only X: nothing to minimise it by
        win.geometry(screens.geometry(area))
        win.withdraw()  # the overlay shows it, only while the game (or one of its windows) is in front
        win.protocol("WM_DELETE_WINDOW", close_click)
        screens.never_focus(win)  # showing it again (e.g. alt-tab back) must not take the keyboard from the game

        top = tk.Frame(win, bg=WINDOW_BG)
        top.pack(fill="x")
        tk.Button(top, text="X", command=close_click, bg=WINDOW_BG, fg=ACCENT, relief="flat", padx=6).pack(
            side="right")
        self.only = tk.Button(top, text=self.only_label(), command=self.toggle_locked_only, bg=WINDOW_BG, fg=ACCENT,
                              relief="flat", padx=6)
        self.only.pack(side="right")
        self.header = tk.Label(top, bg=WINDOW_BG, fg=ACCENT, font=(FONT, 12, "bold"), anchor="w", padx=10, pady=6,
                               justify="left", wraplength=area[2] - HEADER_RESERVE, text="Shop Guide")
        self.header.pack(side="left", fill="x")
        self.build_filters(win)
        self.canvas = tk.Canvas(win, bg=WINDOW_BG, highlightthickness=0)
        scroll = tk.Scrollbar(win, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        win.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Configure>", self.on_resize)
        win.bind("<Configure>", self.on_moved)

    def build_filters(self, win) -> None:
        """Search on its own line (the window is narrow), then Size, Rarity and Merchant."""
        tk = self.tk
        from tkinter import ttk
        label = dict(bg=WINDOW_BG, fg=FG, font=(FONT, 9))
        self.filters = {key: tk.StringVar(win, ANY) for key in ("size", "tier", "merchant")}
        self.filters["text"] = tk.StringVar(win, "")
        line = tk.Frame(win, bg=WINDOW_BG, padx=8)
        line.pack(fill="x")
        tk.Label(line, text="Search", **label).pack(side="left")
        self.search = tk.Entry(line, textvariable=self.filters["text"], font=(FONT, 10))
        self.search.pack(side="left", fill="x", expand=True, padx=(4, 0))
        # The guide never takes the keyboard from the game (never_focus) - except while you type in here.
        self.search.bind("<Button-1>", self.start_typing)
        for key in ("<Return>", "<Escape>", "<FocusOut>"):
            self.search.bind(key, self.stop_typing)
        line = tk.Frame(win, bg=WINDOW_BG, padx=8, pady=4)
        line.pack(fill="x")
        for key, title, values in (("size", "Size", (ANY, *SIZES)), ("tier", "Rarity", (ANY, *TIERS))):
            tk.Label(line, text=title, **label).pack(side="left")
            menu = tk.OptionMenu(line, self.filters[key], *values)
            menu.configure(font=(FONT, 9), highlightthickness=0, padx=2, pady=0)
            menu.pack(side="left", padx=(2, 6))
        tk.Label(line, text="Merchant", **label).pack(side="left")
        merchant = self.merchant_box = ttk.Combobox(line, textvariable=self.filters["merchant"], state="readonly",
                                                    height=20, values=(ANY, *sorted(MERCHANTS, key=str.lower)),
                                                    width=12, font=(FONT, 9))
        merchant.pack(side="left", fill="x", expand=True, padx=(2, 0))
        for var in self.filters.values():
            var.trace_add("write", lambda *_: self.filter_soon())

    def windows(self) -> List[int]:
        """Its window handles - the Merchant list opens in a window of its own - so using them doesn't count as
        leaving the game (the overlay would hide everything, the open list included)."""
        handles = [screens.window_handle(self.win)]
        try:
            path = str(self.win.tk.call("ttk::combobox::PopdownWindow", self.merchant_box))
            handles.append(int(self.win.tk.call("wm", "frame", path), 16))
        except Exception:  # an older Tk without it: the list just closes when the overlay hides
            pass
        return handles

    def start_typing(self, _event=None) -> None:
        screens.allow_focus(self.win, True)
        self.win.focus_force()
        self.search.focus_set()

    def stop_typing(self, _event=None) -> None:
        screens.allow_focus(self.win, False)

    def filter_soon(self) -> None:
        if self.pending_filter:
            self.win.after_cancel(self.pending_filter)
        self.pending_filter = self.win.after(FILTER_DELAY_MS, self.render)

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
        self.stop_typing()
        self.save()
        self.on_closed()  # the overlay hides it; the locked-card list may use the right strip now

    def show(self) -> None:
        self.hidden = False
        self.save()
        self.render()

    def only_label(self) -> str:
        return "Show all" if self.locked_only else "Locked only"

    def toggle_locked_only(self) -> None:
        self.locked_only = not self.locked_only
        self.save()
        self.only.configure(text=self.only_label())
        self.render()

    # --- what it shows ----------------------------------------------------------------------------------------

    def set_context(self, hero: Optional[str], locked: Iterable[str]) -> None:
        """Your hero and the cards you may not hold: both change what the guide lists and greys out."""
        self.hero, self.locked = hero, set(locked)
        self.render()

    def show_offer(self, value) -> None:
        """value: (title, offered card guids, merchant name or None) for the screen you're on, or None when you
        left it. A merchant sets the Merchant filter (and clears the others) so its stock is listed."""
        if not value:
            self.offer = None
        else:
            title, offered, merchant = value
            if not self.offer or self.offer[0] != title:  # a new screen: start again
                self.pinned = {}
            self.pinned.update(dict.fromkeys(offered))
            self.offer = (title, tuple(offered))
            if merchant in MERCHANTS and merchant != self.filters["merchant"].get():
                for key, var in self.filters.items():
                    var.set(merchant if key == "merchant" else ("" if key == "text" else ANY))
        self.render()

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

    def draw_picture(self, tag: str, card, locked: bool, x: float, y: float) -> None:
        """The card's picture at x, y (top left), or until it has one a box of its in-game shape in its tier colour
        (red if locked) saying "no picture"."""
        canvas, tags = self.canvas, (tag, tag + "pic")
        photo = self.picture(card, locked)
        if photo is not None:
            canvas.create_image(x, y, image=photo, anchor="nw", tags=tags)
            return
        width, height = card_shape(card, CARD_HEIGHT)
        canvas.create_rectangle(x + 1, y + 1, x + width - 2, y + height - 2, fill=TILE_BG, width=3,
                                outline=LOCKED_X if locked else TIER_COLORS.get(card.tier, DIM),
                                tags=tags + ("placeholder",))
        canvas.create_text(x + width / 2, y + height / 2, text="no\npicture", fill=DIM, font=(FONT, 7),
                           justify="center", tags=tags)

    def refresh(self, guid: str) -> None:
        """A card's picture arrived: swap it in where that card is shown, touching nothing else."""
        for locked in (False, True):
            self.photos.pop((guid, locked), None)
            for tag, x, y in self.cells.get((guid, locked), []):
                self.canvas.delete(tag + "pic")
                self.draw_picture(tag, CARDS_BY_GUID[guid], locked, x, y)

    def on_resize(self, event) -> None:
        """Rows are justified to the exact width (rows_of), so any change re-flows them - once the resize stops."""
        if event.width == self.width:
            return
        if self.pending_reflow:
            self.win.after_cancel(self.pending_reflow)
        self.pending_reflow = self.win.after(REFLOW_DELAY_MS, self.reflow, event.width)

    def reflow(self, width: int) -> None:
        self.pending_reflow = None
        if width != self.width and self.header.winfo_exists():
            self.width = width
            self.render(force=True)

    def cell_width(self, card, border: int) -> int:
        """A card's cell, exactly: its picture, or the longest word of its name if that's wider (a word can't wrap:
        159 names have one wider than a Small card, 2026-11-10), plus its frame."""
        key = card.guid
        if key not in self.name_widths:
            self.name_widths[key] = max(self.name_font.measure(word) for word in card.name.split()) + 4
        return max(card_shape(card, CARD_HEIGHT)[0], self.name_widths[key]) + 2 * border

    # --- drawing ----------------------------------------------------------------------------------------------

    def draw_section(self, y: float, title: str, color: str, cards: List, framed: bool) -> float:
        """One section from height y: its title, then its cards left to right in justified rows (rows_of), each as
        wide as its slots like on the board, its name wrapped under it. Canvas items, not widgets: a few hundred
        cards draw in a blink. Returns the height under it."""
        canvas = self.canvas
        title_id = canvas.create_text(6, y + 8, text=title, fill=color, font=(FONT, 11, "bold"), anchor="nw")
        y = canvas.bbox(title_id)[3] + 2
        border = 2 if framed else 0
        widths = [self.cell_width(card, border) for card in cards]
        queue = list(zip(cards, widths))
        for count, gaps in rows_of(widths, self.width - 2 * ROW_PAD):
            x, bottom = ROW_PAD, y
            for k in range(count):
                card, width = queue.pop(0)
                locked = card.guid in self.locked
                tag = f"cell{len(self.canvas.find_all())}"  # unique: every cell adds items
                top, inner = y + 3 + border, width - 2 * border
                picture_x = x + border + (inner - card_shape(card, CARD_HEIGHT)[0]) / 2
                self.draw_picture(tag, card, locked, picture_x, top)
                self.cells.setdefault((card.guid, locked), []).append((tag, picture_x, top))
                name = canvas.create_text(x + width / 2, top + CARD_HEIGHT, text=card.name, width=inner,
                                          justify="center", anchor="n", font=(FONT, 8),
                                          fill=DIM if locked else "#eeeeee", tags=tag)
                cell_bottom = canvas.bbox(name)[3] + border
                if framed:
                    canvas.create_rectangle(x + 1, y + 4, x + width - 1, cell_bottom, outline=ACCENT, width=border,
                                            tags=tag)
                bottom = max(bottom, cell_bottom + 3)
                x += width + (gaps[k] if k < len(gaps) else 0)
            y = bottom
        return y

    def render(self, force: bool = False) -> None:
        """Draws what's on offer, then the filtered list (allowed and locked, the shorter part on top).
        A silent refresh (owner, 2026-10-01: "please make it a silent refresh like before"): nothing changed, nothing
        drawn; otherwise the whole canvas is redrawn in one go (canvas items, owner 2026-11-11: "not so performance
        heavy") - no flicker - and the scroll only jumps to the top when you change a filter."""
        if self.pending_filter:
            self.win.after_cancel(self.pending_filter)
            self.pending_filter = None
        if not self.header.winfo_exists():  # a redraw queued while the window was being destroyed
            return
        if self.hidden:  # drawn when it's opened (show), not for nobody
            self.drawn = None
            return
        values = {key: var.get() for key, var in self.filters.items()}
        state = (self.offer, tuple(self.pinned), self.hero, frozenset(self.locked), self.locked_only,
                 tuple(sorted(values.items())))
        if state == self.drawn and not force:
            return
        filters_changed = not self.drawn or self.drawn[-1] != state[-1]
        self.drawn = state
        listed = guide_cards(self.cards, self.hero, values["merchant"], values["text"], values["size"],
                             values["tier"])
        # cards offered on this screen are listed whatever the merchant and the cap - unless you filter them out
        pinned = guide_cards([CARDS_BY_GUID[g] for g in self.pinned if g in CARDS_BY_GUID], None, ANY,
                             values["text"], values["size"], values["tier"])
        listed = pinned + [c for c in listed if c.guid not in self.pinned]
        total = len(listed)
        listed = sorted(listed[:max(MAX_SHOWN, len(pinned))], key=lambda c: c.name.lower())
        allowed = [c for c in listed if c.guid not in self.locked]
        locked = [c for c in listed if c.guid in self.locked]
        offered = [CARDS_BY_GUID[g] for g in (self.offer[1] if self.offer else ()) if g in CARDS_BY_GUID]

        where = values["merchant"] if values["merchant"] != ANY else "All cards" + (f" for {self.hero}" if self.hero else "")
        note = f"showing {MAX_SHOWN} of {total} - narrow it with the filters" if total > MAX_SHOWN else             f"{len(locked)} locked of {total}" if locked else f"{total}, nothing locked"
        self.header.configure(text=f"{self.offer[0] + '  |  ' if self.offer else ''}{where}: {note}")

        lists = [("allowed", f"You can buy ({len(allowed)})", GOOD, allowed),
                 ("locked", f"LOCKED - don't buy ({len(locked)})", WARN, locked)]
        if self.locked_only:  # just the cards to recognise and avoid
            lists = lists[1:]
        elif len(locked) < len(allowed):  # the shorter list on top, so it's seen without scrolling
            lists.reverse()
        wanted = [("offer", f"On offer now ({len(offered)})", ACCENT, offered, True)]
        wanted += [(key, title, color, cards, False) for key, title, color, cards in lists]
        # everything is drawn again: canvas items are cheap, and it all lands in one paint (no flicker)
        self.canvas.delete("all")
        self.cells = {}
        y = 0.0
        for _key, title, color, cards, framed in (b for b in wanted if b[3]):
            y = self.draw_section(y, title, color, cards, framed)
        self.canvas.configure(scrollregion=(0, 0, self.width, y + 6))
        if filters_changed:
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
        self.photos.clear()  # images are freed here, in Tk's own thread, not at exit from another
