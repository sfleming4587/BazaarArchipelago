"""
The Item Guide: card pictures at their in-game sizes, locked ones greyed out with a red cross. A real window you can
drag anywhere (other monitors too); until you move it, it follows the strip right of the board. Runs in the
overlay's Tk thread and only renders what it's given.

Owner, 2026-10-01 ("2, and allow user to open it outside of a shop with the filters ... size, which merchant,
starting rarity, search bar"):
- the cards on offer right now (shop, level-up, an event's items: read from memory) are always in the lists (no
  section of their own since 2026-11-13, owner: "remove 'On offer now' portion of the guide");
- what the chosen merchant could stock for your hero - entering a shop picks that merchant - or every
  card with Merchant on Any; Search, Size, Rarity, Hero and Merchant narrow it, open or not in a shop. The Hero
  filter starts on your hero, or on Any for a merchant that can deal other heroes' cards (owner, 2026-11-13).

Pictures come from cardart (no Pillow needed); a card without one yet shows a "no picture" box of the same shape.
"""
import collections
import json
import threading
import time
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from . import screens
from .cardart import TIER_COLORS, CardArt, card_shape, frame_offset
from .data import CARDS_BY_GUID, ENCOUNTERS, HEROES, MERCHANT_DATA, SHOP_CARDS, TIERS
from .merchants import deals_any_hero, possible_stock
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
WARM_MS, WARM_BUDGET = 25, 0.004  # warm(): at most 4 ms of picture building every 25 ms
MAX_SHOWN = 300  # pictures drawn at once; more than that and the filters are needed (Tk slows down)

ANY = "Any"
SIZES = ("Small", "Medium", "Large")
# Merchants by their lock (data.Encounter's ap_id, never by name - owner 2026-11-16): each one's stocks, one per copy
# of it (tutorial copies too); the debug merchants are in no encounter, so they never show up.
MERCHANTS: Dict[int, List[dict]] = {e.ap_id: [MERCHANT_DATA[g]["stock"] for g in e.guids if g in MERCHANT_DATA]
                                    for e in ENCOUNTERS if e.merchant}
MERCHANT_NAMES: Dict[int, str] = {e.ap_id: e.name for e in ENCOUNTERS if e.ap_id in MERCHANTS}
# the Merchant filter's choices, in the order it lists them: None is Any
MERCHANT_CHOICES: Tuple[Optional[int], ...] = (None, *sorted(MERCHANTS, key=lambda m: MERCHANT_NAMES[m].lower()))


_POOLS: Dict[tuple, list] = {}  # merchant_pool's answers: they depend only on the merchant, the hero and the cards


def merchant_pool(merchant: int, hero: str, cards: list) -> list:
    """What `merchant` could stock while playing `hero`: worked out once per merchant and hero (it took ~180 ms -
    9,400 stock checks - on every redraw of the guide, measured 2026-11-12)."""
    key = (merchant, hero, tuple(c.guid for c in cards))
    if key not in _POOLS:
        pool = {c.guid: c for stock in MERCHANTS.get(merchant, []) for c in possible_stock(stock, hero, cards)}
        _POOLS[key] = list(pool.values())
    return _POOLS[key]


def default_hero(merchant: Optional[int], playing: Optional[str]) -> str:
    """The Hero filter's starting value (owner, 2026-11-13): the hero you're playing - but Any for a merchant that can
    deal other heroes' cards (merchants.deals_any_hero, e.g. The Antiquarian), and Any when no hero is known."""
    if not playing or any(deals_any_hero(stock) for stock in MERCHANTS.get(merchant, [])):
        return ANY
    return playing


def guide_cards(cards: Iterable, hero: Optional[str], merchant: Optional[int], text: str, size: str,
                tier: str, playing: Optional[str] = None) -> List:
    """The cards the guide lists, by name: `hero`'s cards and Common ones (None or Any: every hero's), and with a
    merchant (its MERCHANTS key; None: Any) only what it could stock while playing `hero` (Any: while playing
    `playing`, the hero you're on - so
    another hero's cards it can deal show up), narrowed by the search text (anywhere in the name, any case), size
    and starting rarity."""
    cards = list(cards)
    hero = None if hero == ANY else hero
    if merchant is not None:
        cards = merchant_pool(merchant, hero or playing or "", cards)
    if hero:
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
        self.art = CardArt(art_cache_dir, CARD_HEIGHT, on_ready=on_art, frames=True)  # rarity frames, 2026-11-13
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
        self.cell_count = 0  # draw_section's cell tags
        self.to_warm: "collections.deque" = collections.deque()  # cards whose pictures warm() builds ahead
        self.pools_for: Optional[str] = None  # the hero whose merchant stock warm_pools works out
        self.warming = False
        self.width = DEFAULT_WIDTH
        self.pending_reflow = None
        self.name_widths: Dict[str, int] = {}
        from tkinter import font as tkfont
        self.name_font = tkfont.Font(root=root, family=FONT, size=8)
        self.drawn = None  # what's on screen, so a redraw that changes nothing is skipped

        win = self.win = tk.Toplevel(root)
        win.title("Item Guide - The Bazaar")
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
                               justify="left", wraplength=area[2] - HEADER_RESERVE, text="Item Guide")
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
        """Search on its own line (the window is narrow), then Size and Rarity, then Hero and Merchant."""
        tk = self.tk
        from tkinter import ttk
        label = dict(bg=WINDOW_BG, fg=FG, font=(FONT, 9))
        self.filters = {key: tk.StringVar(win, ANY) for key in ("size", "tier", "hero", "merchant")}
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
        line = tk.Frame(win, bg=WINDOW_BG, padx=8)
        line.pack(fill="x", pady=(0, 4))
        tk.Label(line, text="Hero", **label).pack(side="left")
        menu = tk.OptionMenu(line, self.filters["hero"], ANY, *HEROES)
        menu.configure(font=(FONT, 9), highlightthickness=0, padx=2, pady=0)
        menu.pack(side="left", padx=(2, 6))
        tk.Label(line, text="Merchant", **label).pack(side="left")
        merchant = self.merchant_box = ttk.Combobox(line, textvariable=self.filters["merchant"], state="readonly",
                                                    height=20, values=[MERCHANT_NAMES.get(m, ANY) for m in MERCHANT_CHOICES],
                                                    width=12, font=(FONT, 9))
        merchant.pack(side="left", fill="x", expand=True, padx=(2, 0))
        # picking a merchant (or walking into one) puts the Hero filter back to its default for that merchant
        self.filters["merchant"].trace_add("write", lambda *_: self.reset_hero())
        for var in self.filters.values():
            var.trace_add("write", lambda *_: self.filter_soon())

    def reset_hero(self) -> None:
        self.filters["hero"].set(default_hero(self.merchant(), self.hero))

    def merchant(self) -> Optional[int]:
        """The Merchant filter's merchant (a MERCHANTS key), None for Any: by its place in the list, never its name."""
        index = self.merchant_box.current()
        return MERCHANT_CHOICES[index] if index > 0 else None

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
        if hero != self.hero:  # a new hero: build its cards' pictures ahead of time (warm)
            mine = [c for c in self.cards if c.hero in (hero, "Common", None)]  # yours first, then any shop card
            self.to_warm = collections.deque(mine + [c for c in self.cards if c.hero not in (hero, "Common", None)])
            if not self.warming:
                self.warming = True
                self.win.after(WARM_MS, self.warm)
            # every merchant's stock for this hero, worked out in the background (pure data, cached in _POOLS): the
            # first time a merchant was shown it cost ~34 ms on the window's thread (2026-11-12)
            self.pools_for = hero
            threading.Thread(target=self.warm_pools, args=(hero, list(self.cards)), name="bazaar merchant stock",
                             daemon=True).start()
            self.hero = hero
            self.reset_hero()
        self.hero, self.locked = hero, set(locked)
        self.render()

    def warm_pools(self, hero: Optional[str], cards: list) -> None:
        """Every merchant's stock for this hero (on a background thread); it stops as soon as another hero is picked
        (clicking through the menu's heroes started one per click, each ~1 s of work)."""
        for merchant in MERCHANTS:
            if self.pools_for != hero:
                return
            merchant_pool(merchant, hero or "", cards)

    def warm(self) -> None:
        """Your hero's card pictures, built a few ms at a time (WARM_BUDGET every WARM_MS) so a merchant's list draws
        at once: building ~300 of them on the spot froze the overlay (2026-11-12: 180 ms from memory, 3.9 s when
        each was a file). A picture not read yet waits its turn (the worker reads them in the background)."""
        start = time.perf_counter()
        while self.to_warm and time.perf_counter() - start < WARM_BUDGET:
            card = self.to_warm[0]
            if self.picture(card, card.guid in self.locked) is None and card.guid not in self.art.absent \
                    and self.art.working:
                break  # not read yet: try again next round
            self.cell_width(card, 0)  # its name measured too (draw_section)
            self.to_warm.popleft()
        self.warming = bool(self.to_warm)
        if self.warming:
            self.win.after(WARM_MS, self.warm)

    def show_offer(self, value) -> None:
        """value: (title, offered card guids, merchant (a MERCHANTS key) or None) for the screen you're on, or None
        when you left it. A merchant sets the Merchant filter (and clears the others) so its stock is listed."""
        if not value:
            self.offer = None
        else:
            title, offered, merchant = value
            if not self.offer or self.offer[0] != title:  # a new screen: start again
                self.pinned = {}
            self.pinned.update(dict.fromkeys(offered))
            self.offer = (title, tuple(offered))
            if merchant in MERCHANTS and merchant != self.merchant():
                for key, var in self.filters.items():
                    if key not in ("hero", "merchant"):  # the Hero filter follows the merchant (reset_hero)
                        var.set("" if key == "text" else ANY)
                self.merchant_box.current(MERCHANT_CHOICES.index(merchant))
        self.render()

    # --- pictures ---------------------------------------------------------------------------------------------

    def picture(self, card, locked: bool):
        """The card's picture, or None if it has none (yet)."""
        key = (card.guid, locked)
        if key not in self.photos:
            data = self.art.picture(card, locked)
            if not data:
                return None
            try:  # master: this window's Tk, never whichever Tk happened to start first in the process
                self.photos[key] = self.tk.PhotoImage(data=data, master=self.win)  # from memory (CardArt.picture)
            except self.tk.TclError:  # an unreadable file: the placeholder
                return None
        return self.photos[key]

    def draw_picture(self, tag: str, card, locked: bool, x: float, y: float) -> None:
        """The card's picture at x, y (top left), or until it has one a box of its in-game shape in its tier colour
        (red if locked) saying "no picture"."""
        canvas, tags = self.canvas, (tag, tag + "pic")
        photo = self.picture(card, locked)
        if photo is not None:  # in its rarity's frame, which reaches a little past the card (cardart.FRAMES)
            dx, dy = frame_offset(card, CARD_HEIGHT)
            canvas.create_image(x + dx, y + dy, image=photo, anchor="nw", tags=tags)
            return
        width, height = card_shape(card, CARD_HEIGHT)
        canvas.create_rectangle(x + 1, y + 1, x + width - 2, y + height - 2, fill=TILE_BG, width=3,
                                outline=LOCKED_X if locked else TIER_COLORS.get(card.tier, DIM),
                                tags=tags + ("placeholder",))
        canvas.create_text(x + width / 2, y + height / 2, text="no\npicture", fill=DIM, font=(FONT, 7),
                           justify="center", tags=tags)

    def refresh(self, guid: str) -> None:
        """A card's picture arrived: swap it in where that card is shown, touching nothing else. A picture already
        built stays (its content never changes): dropping it undid warm() - 199 pictures rebuilt on the first
        merchant (2026-11-12)."""
        for locked in (False, True):
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
        # as wide as what's drawn: the card in its frame, which reaches a little past the card (2026-11-13)
        return max(card_shape(self.art.drawn(card), CARD_HEIGHT)[0], self.name_widths[key]) + 2 * border

    # --- drawing ----------------------------------------------------------------------------------------------

    def draw_section(self, y: float, title: str, color: str, cards: List) -> float:
        """One section from height y: its title, then its cards left to right in justified rows (rows_of), each as
        wide as its slots like on the board, its name wrapped under it. Canvas items, not widgets: a few hundred
        cards draw in a blink. Returns the height under it."""
        canvas = self.canvas
        title_id = canvas.create_text(6, y + 8, text=title, fill=color, font=(FONT, 11, "bold"), anchor="nw")
        y = canvas.bbox(title_id)[3] + 2
        border = 0
        widths = [self.cell_width(card, border) for card in cards]
        queue = list(zip(cards, widths))
        for count, gaps in rows_of(widths, self.width - 2 * ROW_PAD):
            x, bottom = ROW_PAD, y
            for k in range(count):
                card, width = queue.pop(0)
                locked = card.guid in self.locked
                self.cell_count += 1  # a unique tag per cell (counting the canvas's items each time cost ~O(n^2))
                tag = f"cell{self.cell_count}"
                top, inner = y + 3 + border, width - 2 * border
                picture_x = x + border + (inner - card_shape(card, CARD_HEIGHT)[0]) / 2
                self.draw_picture(tag, card, locked, picture_x, top)
                self.cells.setdefault((card.guid, locked), []).append((tag, picture_x, top))
                name = canvas.create_text(x + width / 2, top + CARD_HEIGHT, text=card.name, width=inner,
                                          justify="center", anchor="n", font=(FONT, 8),
                                          fill=DIM if locked else "#eeeeee", tags=tag)
                cell_bottom = canvas.bbox(name)[3] + border
                bottom = max(bottom, cell_bottom + 3)
                x += width + (gaps[k] if k < len(gaps) else 0)
            y = bottom
        return y

    def render(self, force: bool = False) -> None:
        """Draws what's on offer, then the filtered list (what you can buy, then what's locked).
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
        listed = guide_cards(self.cards, values["hero"], self.merchant(), values["text"], values["size"],
                             values["tier"], playing=self.hero)
        # cards offered on this screen are listed whatever the merchant and the cap - unless you filter them out
        pinned = guide_cards([CARDS_BY_GUID[g] for g in self.pinned if g in CARDS_BY_GUID], None, None,
                             values["text"], values["size"], values["tier"])
        listed = pinned + [c for c in listed if c.guid not in self.pinned]
        total = len(listed)
        listed = sorted(listed[:max(MAX_SHOWN, len(pinned))], key=lambda c: c.name.lower())
        allowed = [c for c in listed if c.guid not in self.locked]
        locked = [c for c in listed if c.guid in self.locked]

        hero = values["hero"] if values["hero"] != ANY else None
        merchant = self.merchant()
        where = ((MERCHANT_NAMES[merchant] if merchant is not None else "All cards")
                 + (f" for {hero}" if hero else "" if merchant is not None else " for any hero"))
        note = f"showing {MAX_SHOWN} of {total} - narrow it with the filters" if total > MAX_SHOWN else \
            f"{len(locked)} locked of {total}" if locked else f"{total}, nothing locked"
        self.header.configure(text=f"{self.offer[0] + '  |  ' if self.offer else ''}{where}: {note}")

        lists = [("allowed", f"You can buy ({len(allowed)})", GOOD, allowed),
                 ("locked", f"LOCKED - don't buy ({len(locked)})", WARN, locked)]
        if self.locked_only:  # just the cards to recognise and avoid
            lists = lists[1:]
        # "You can buy" always above "Locked" (owner, 2026-11-13; was the shorter list on top). No "On offer now"
        # section above them (owner, 2026-11-13: "remove 'On offer now' portion of the guide"): the cards on screen
        # are still always in these lists (pinned)
        wanted = lists
        # everything is drawn again: canvas items are cheap, and it all lands in one paint (no flicker)
        self.canvas.delete("all")
        self.cells = {}
        y = 0.0
        for _key, title, color, cards in (b for b in wanted if b[3]):
            y = self.draw_section(y, title, color, cards)
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
