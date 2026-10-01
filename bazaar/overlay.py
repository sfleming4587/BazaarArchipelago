"""
Windows shown above The Bazaar: the alert box, the locked-card list, pop-ups, the Shop Guide and the tracker.

They're separate windows owned by the client; they never draw inside the game or touch its process. They show over
the game when it runs borderless (the default "Fullscreen Window") or windowed, not over exclusive fullscreen.
Tk runs in its own thread; the client only talks to it through the command queue (the Overlay methods).

Rules (user, 2026-09-28/29): beside the board, never on it; never overlapping each other; never off screen;
only while the game is the active window; never taking the keyboard from the game; redrawing only what changed.
"""
import logging
import queue
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Set

from . import screens
from .shop_guide import ShopGuide
from .theme import ACCENT, DIM, FG, FONT, GOOD, LOCKED_X, MUTED, OUTLINE, SEVERITY, WARN
from .tracker import Tracker

logger = logging.getLogger("Client")
FILE_ONLY = {"NoStream": True, "skip_gui": True}  # to the client's log file, not its window

# see-through enough to read the game's tooltips behind (the list lets the mouse through, so they do show)
ALERT_ALPHA = 0.8
# The locked-card list: only its background is see-through (a backdrop window at this opacity under it); its
# text stays fully solid (user 2026-09-28: at 60% for the whole window the names were hard to read).
LIST_ALPHA = 0.55

# Where the overlay may draw: the strips left and right of the board, measured on a 1920x1080 shop screenshot
# (2026-09-28). It must never cover the board: the overlay takes the clicks where it sits, and a list over the
# board once stopped the player leaving a shop. Measured in 1080p pixels and scaled to the game window's real
# size, so it works at any resolution, windowed or fullscreen, on any monitor.
MARGIN = 14  # from the window's left and right edges
LEFT_END = 960 - 363  # the left strip ends this far left of the window's centre (the board starts there)
RIGHT_START = 1565 - 960  # the right strip starts this far right of the centre
LEFT_BOTTOM = 1056
RIGHT_BOTTOM = 950  # above the settings gear in the bottom-right corner

FONT_SIZES = range(13, 9, -1)  # 1080p pixel sizes tried for the locked-card list (scaled with the window)
MIN_FONT = 10  # never smaller than this many real pixels, however small the window (user rule: text >= 10 px)
POINT_TO_PX = 4 / 3  # Tk points to pixels at 96 dpi (the overlay's other text is sized in points)
PAD = 10  # inside every panel
BORDER = 2  # every panel's gold border
WINDOW_GAP = 4  # between two panels that sit on top of each other
INDENT = 8  # names sit a little right of their letter
GAP = 12  # between columns
ALERT_SHARE = 2  # the alert box takes at most 1/2 of the left strip (the rest is the list's)
MAX_ALERT_LINES = 6  # held cards / trap lines shown in it; more become "+ N more" (review 2026-09-30)
TOAST_SHARE = 3  # pop-ups take at most 1/3 of the right strip
MAX_TOASTS = 4
MENU_WIDTH = 460  # the menu's centre panel, 1080p pixels (scaled with the window)
MENU_TILE = 100  # one hero's tile
MENU_COLUMNS = 4  # heroes per row, like the hero select
MENU_BAR_BG = "#3a3f4b"  # the empty part of a hero's check bar
POLL_MS = 250

# Padlocks on the locked cards a shop is offering (user, 2026-10-01): placed by proportion of the game window, a
# small mark at each card's centre, never covering the card. The row is centred across the window, about a third
# down; a card is 1, 2 or 3 slots wide by its size. 1080p pixels, scaled like the strips.
# Measured 2026-10-01 on the owner's shop screenshot (Small, Large, Small): the three centres matched within 1 px.
# Cards sit on a slot grid, so a card's width is its slots times the slot pitch (the thin gap is inside the pitch).
SHOP_ROW_Y = 0.398  # the cards' centres, as a share of the window's height
SLOT_WIDTH = 113  # the slot pitch: a Small card plus the gap after it
# The extra space between two cards, by the screen (memory's state name) showing the row. Measured on the owner's
# screenshots 2026-10-01: a shop's cards touch; a level-up's Small cards sit 181 px apart (113 + 68). A screen not
# listed here gets no padlocks: its layout hasn't been measured.
ROW_GAPS = {"Encounter": 0, "LevelUp": 68, "Stash": 0, "Loot": 0}
# Screens only measured with one card (a loot's single card sits centred, owner's screenshot 2026-10-01): with more
# than one, the spacing is unknown, so no padlocks rather than misplaced ones.
ONE_CARD_ONLY = {"Loot"}
CARD_HEIGHT = 220  # measured on the same screenshot (the cards' frames, y 322-541 at 1080p)
YOUR_ROW = (548, 785)  # your own board's cards, top and bottom (their tooltips can open over the shop row too)
BOARD_SLOTS = {1: 4, 2: 6, 3: 8}  # your board's width by level (owner, 2026-10-01); 10 from level 4 on
HOVERED_ALPHA = 0.3  # a padlock while a card is hovered: see-through, so the tooltip reads (user, 2026-10-01)
FADE_STEPS, FADE_MS = 6, 25  # opening and closing the Shop Guide: a short fade (owner: "a simple transition")
FLIP_SECONDS = 1.0  # new cards flip over first: if the game's reveal flag doesn't start by then, show anyway
FLIP_MAX = 3.0  # and never wait longer than this for a reveal to end
HOVER_MS = 60  # how often the mouse is checked while padlocks are up
SLOTS = {"Small": 1, "Medium": 2, "Large": 3, "Empty": 1}  # Empty: a free slot in a row laid out by slot (the stash)
STASH_SLOTS = 10  # the stash is always 10 slots wide, over the shop row (owner's screenshot, 2026-10-01)
PADLOCK = 56  # the mark's size
MIN_PADLOCK = 24  # real pixels, however small the window
PADLOCK_KEY = "#010203"  # the padlock window's see-through colour
MIN_GAME_WINDOW = 100  # a client area smaller than this is minimised or not laid out yet


def letter_columns(names: List[str], rows: int) -> List[List[str]]:
    """
    Names grouped under their first letter; each letter starts a heading line. Letters stack in a column while
    they fit in `rows` lines, otherwise the letter starts the next column. A letter longer than a whole column
    carries on in the next one under its heading again.
    """
    groups: Dict[str, List[str]] = {}
    for name in sorted(names, key=str.lower):
        groups.setdefault(name[0].upper(), []).append(name)
    rows = max(rows, 2)  # a heading and at least one name
    columns: List[List[str]] = [[]]
    for letter, members in groups.items():
        if columns[-1] and len(columns[-1]) + 1 + len(members) > rows:
            columns.append([])
        while members:
            if len(columns[-1]) >= rows - 1:
                columns.append([])
            room = rows - len(columns[-1]) - 1
            columns[-1] += [letter] + members[:room]
            members = members[room:]
    return columns


def fit_columns(names: List[str], areas: List[tuple], column_width: Callable[[List[str]], int],
                line_height: int) -> tuple:
    """
    Lays the names out as letter columns over the areas ((width, height) in pixels), filling the first area
    before the next. Returns (columns per area, how many names didn't fit).
    """
    remaining = sorted(names, key=str.lower)
    placed: List[List[List[str]]] = []
    for width, height in areas:
        placed.append([])
        rows = height // line_height
        if rows < 2 or not remaining:
            continue
        used = 0
        for column in letter_columns(remaining, rows):
            used += column_width(column)
            if used > width:
                break
            placed[-1].append(column)
        taken = sum(1 for column in placed[-1] for line in column if len(line) > 1)
        remaining = remaining[taken:]
    return placed, len(remaining)


def fit_names(names: List[str], areas: List[tuple], sizes: List[int], measurer: Callable) -> tuple:
    """
    The biggest text size (sizes, biggest first) at which the names fit the areas, else the smallest.
    measurer(size) -> (line width function, line height). Returns (size, columns per area, how many didn't fit,
    column width function, line height).
    """
    for size in sizes:
        line_width, line_height = measurer(size)

        def column_width(column: List[str], line_width=line_width) -> int:
            return max(line_width(line) for line in column) + GAP
        placed, missing = fit_columns(names, areas, column_width, line_height)
        if not missing:
            break
    return size, placed, missing, column_width, line_height


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


def card_centres(x: int, y: int, w: int, h: int, sizes: List[Optional[str]], gap: float = 0) -> Optional[List[tuple]]:
    """
    Screen centre (x, y) of each card in a shop row of these sizes, left to right, for a game window at x, y of
    size w x h. None if any size is unknown: a guessed width would put every padlock after it on the wrong card.
    """
    if not sizes or any(size not in SLOTS for size in sizes):
        return None
    across = min(h / 1080, w / 1920)  # the board's scale, as in strips()
    widths = [SLOTS[size] * SLOT_WIDTH * across for size in sizes]
    gap *= across
    left = x + w / 2 - (sum(widths) + gap * (len(widths) - 1)) / 2
    centres = []
    for width in widths:
        centres.append((round(left + width / 2), round(y + h * SHOP_ROW_Y)))
        left += width + gap
    return centres


def card_rects(x: int, y: int, w: int, h: int, sizes: List[Optional[str]], gap: float = 0,
               level: Optional[int] = None) -> List[tuple]:
    """Where hovering shows a card's tooltip (left, top, right, bottom): each offered card, and your own board at
    its width for your level, as if full (where your cards sit isn't read; owner, 2026-10-01). Empty if an offered
    card's size is unknown."""
    centres = card_centres(x, y, w, h, sizes, gap)
    if not centres:
        return []
    across = min(h / 1080, w / 1920)
    half_height, mid = CARD_HEIGHT * across / 2, x + w / 2
    rects = [(round(cx - SLOTS[size] * SLOT_WIDTH * across / 2), round(cy - half_height),
              round(cx + SLOTS[size] * SLOT_WIDTH * across / 2), round(cy + half_height))
             for (cx, cy), size in zip(centres, sizes) if size != "Empty"]
    board = BOARD_SLOTS.get(level or 0, 10) * SLOT_WIDTH * across / 2  # unknown level: the widest board
    return rects + [(round(mid - board), y + round(YOUR_ROW[0] * h / 1080), round(mid + board),
                     y + round(YOUR_ROW[1] * h / 1080))]


def mouse_on(rects: List[tuple]) -> bool:
    """Is the mouse on one of the rects, or is its left button held (dragging a card shows its tooltip anywhere)?
    Windows only; elsewhere always False."""
    if sys.platform != "win32" or not rects:
        return False
    import ctypes
    from ctypes import wintypes
    point = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
        return False
    held = ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000  # VK_LBUTTON
    return bool(held) or any(r[0] <= point.x < r[2] and r[1] <= point.y < r[3] for r in rects)


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


def draw_columns(tk, parent, columns: List[List[str]], font, bold, column_width: Callable[[List[str]], int],
                 line_height: int, bg: str) -> None:
    """One canvas of positioned text: hundreds of separate label widgets took Tk seconds to lay out."""
    if not columns:
        return
    widths = [column_width(column) for column in columns]
    canvas = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0, width=sum(widths),
                       height=max(len(column) for column in columns) * line_height)
    canvas.pack(anchor="w")
    x = 0
    for column, width in zip(columns, widths):
        for y, line in enumerate(column):
            if len(line) == 1:  # a letter heading
                canvas.create_text(x, y * line_height, text=line, fill=ACCENT, font=bold, anchor="nw")
            else:
                canvas.create_text(x + INDENT, y * line_height, text=line, fill=FG, font=font, anchor="nw")
        x += width


class Overlay:
    """The client's handle on the windows: every method only queues a command for the Tk thread."""

    def __init__(self, art_cache_dir: Optional[str] = None, guide_file: Optional[str] = None) -> None:
        self.only_over_game = True  # False shows the windows whatever is in front (tests)
        self.game_window: Optional[tuple] = None  # tests: pretend the game's client area is here (x, y, w, h)
        self.guide_file = guide_file  # where the Shop Guide remembers whether it's closed and where you put it
        self.art_cache_dir = art_cache_dir
        self.on_bypass: Optional[Callable[[str], None]] = None  # the client: use a Lock Bypass on a held card
        self.commands: "queue.Queue" = queue.Queue()
        self.available = True  # False if the windows can't open (no tkinter, or Tk can't start)
        self.ready = threading.Event()  # set once the windows are up (or failed to come up)
        self.thread = threading.Thread(target=self._run, name="bazaar overlay", daemon=True)
        self.thread.start()

    # --- called from the client ---------------------------------------------------------------------------------

    def show_locked(self, title: Optional[str], cards: list, blocked: bool = False) -> None:
        """The alert box's banner and the lines under it (held locked cards, Sell Traps). title=None hides it.
        A line is text, or (text, card guid) to give it a "Use Bypass" button (a Lock Bypass is ready).
        blocked: checks are blocked (critical, red) rather than just a warning (a Sell Trap coming up)."""
        self.commands.put(("locked", (title, list(cards), blocked) if title else None))

    def show_shop(self, merchant: Optional[str], locked: List[str], verb: str = "sell", exact: bool = False) -> None:
        """Show which locked cards a merchant could sell (or an event could offer). merchant=None hides it.
        exact: these are the locked cards actually on offer right now (read from the game), not every possible one."""
        self.commands.put(("shop", (merchant, list(locked), verb, exact) if merchant else None))

    def show_padlocks(self, screen: Optional[str], sizes: List[Optional[str]], locked: List[int], reveal: bool = False,
                      level: Optional[int] = None) -> None:
        """A padlock on each locked card on offer: the screen showing them (a ROW_GAPS key), sizes of the row's
        cards left to right (gaps included), and the positions (0-based) of the locked ones. No locked positions
        hides them (at once). reveal: these are new cards, so wait until they've flipped over. level: yours."""
        measured = screen in ROW_GAPS and not (screen in ONE_CARD_ONLY and len(sizes) > 1)
        value = (screen, tuple(sizes), tuple(locked), level) if locked and measured else None
        self.commands.put(("padlocks", (value, time.monotonic(), reveal and value is not None)))

    def show_board_ui(self, ui) -> None:
        """The board's on-screen flags (memreader.BoardUI), or None when they can't be read: then the padlocks
        fall back to the mouse's position and a fixed wait."""
        self.commands.put(("board_ui", ui))

    def show_board(self, title: Optional[str], offered: List[str], merchant: Optional[str]) -> None:
        """Shop Guide: what's on offer on screen (card guids, first, framed in gold) and the merchant you're at (its
        stock is listed below). title=None: you left; the guide keeps its list and filters."""
        self.commands.put(("board", (title, tuple(offered), merchant) if title else None))

    def guide_context(self, hero: Optional[str], locked) -> None:
        """Shop Guide: your hero and the cards you may not hold (greyed out with a red cross)."""
        self.commands.put(("guide_context", (hero, frozenset(locked))))

    def toggle_guide(self) -> None:
        self.commands.put(("guide_toggle", None))

    def toast(self, text: str, seconds: float = 6, warning: bool = False) -> None:
        """A short pop-up (bottom right) that disappears by itself."""
        self.commands.put(("toast", (text, time.monotonic() + seconds, warning)))

    def show_menu(self, data: Optional[dict]) -> None:
        """The menu's centre panel (see client.menu_data); None hides it."""
        self.commands.put(("menu", data))

    def show_status(self, text: Optional[str], warning: bool = False, big: bool = False) -> None:
        """The bottom of the alert box: run progress, or (big) the heroes you may pick on the menu. None hides it."""
        self.commands.put(("status", (text, warning, big) if text else None))

    def show_tracker_data(self, data: Dict[str, dict]) -> None:
        """What the tracker shows (see tracker.Tracker.update); sent whenever items or checks change."""
        self.commands.put(("tracker", data))

    def toggle_tracker(self) -> None:
        self.commands.put(("tracker_toggle", None))

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
        import tkinter.font as tkfont
        self.overlay, self.tk, self.tkfont, self.root = overlay, tk, tkfont, root
        root.withdraw()
        # No two windows overlap: the alert box (root) takes the top of the left strip, the locked-card list goes
        # right under it, and the right strip belongs to the Shop Guide - or, while the guide is closed, to the
        # rest of a long list. Pop-ups (toasts) stack up from the bottom of the right strip, which then shrinks.
        # Owner, 2026-10-01: "The shop guide is always going to be the whole left column": the alert box (root) is
        # now just its header (status and buttons); DeathLink, held locked cards and Sell Traps are the notices box at
        # the top of the right column, the locked-card list under them, the pop-ups at the bottom.
        # On the menu (no run, no board) the heroes you may play sit in the centre (owner, 2026-10-01).
        self.alert_box, self.notice_box, self.shop_first, self.shop_second, self.toast_box, self.menu_box = \
            root, tk.Toplevel(root), tk.Toplevel(root), tk.Toplevel(root), tk.Toplevel(root), tk.Toplevel(root)
        self.panels = [self.alert_box, self.notice_box, self.shop_first, self.shop_second, self.toast_box,
                       self.menu_box]
        # nothing to click in these (the menu panel must never block the game's menu buttons)
        self.click_through = {self.shop_first, self.shop_second, self.toast_box, self.menu_box}
        for panel in self.panels:
            panel.withdraw()
            panel.overrideredirect(True)
            panel.attributes("-topmost", True)
            panel.attributes("-alpha", 1.0 if panel in (self.shop_first, self.shop_second) else ALERT_ALPHA)
            panel.configure(bg=SEVERITY["info"], highlightthickness=BORDER, highlightbackground=ACCENT)
            screens.never_focus(panel)
        # the list's see-through background: a plain window right under each list window, same size
        self.backdrops = {}
        for panel in (self.shop_first, self.shop_second):
            backdrop = self.backdrops[panel] = tk.Toplevel(root)
            backdrop.withdraw()
            backdrop.overrideredirect(True)
            backdrop.attributes("-topmost", True)
            backdrop.attributes("-alpha", LIST_ALPHA)
            screens.never_focus(backdrop)

        self.padlocks: list = []  # one small click-through window per padlock, made as needed and reused
        self.padlocks_wanted = 0  # how many of them are in use
        self.pending_padlocks = None  # (padlocks, since, wait for the reveal) while new cards are still flipping
        self.reveal_started = False  # the game's reveal began since those padlocks came in
        self.board_ui = None  # memreader.BoardUI, or None (unreadable: fall back to the mouse)
        self.padlock_cards: List[tuple] = []  # where hovering makes the padlocks see-through (see card_rects)
        self.padlocks_faded = 1.0  # the padlocks' alpha now (see padlock_alpha)
        self.overlay_faded = 1.0  # every other window's fade now (see overlay_factor)
        self.guide_fading = False  # the Shop Guide is fading in or out (a second click waits for it)

        self.layout: dict = {}  # the strips for where the game window is now (see relayout)
        self.relayout((0, 0, root.winfo_screenwidth(), root.winfo_screenheight()))  # until the game is seen
        self.state = {"locked": None, "deathlink": None, "shop": None, "toasts": [], "status": None,
                      "padlocks": None, "menu": None}
        self.hero_pictures: Dict[str, object] = {}  # the menu panel's portraits (Tk drops an image Python lets go)
        self.list_hidden = False  # the player hid the locked-card list (until they show it again)
        # what each window shows now, to skip redraws that change nothing
        self.drawn: dict = {"alerts": None, "notices": None, "shop": None, "toasts": None, "alerts_height": 0,
                            "notices_height": 0, "toasts_height": 0, "padlocks": None}
        self.wanted: set = set()  # windows that have something to show (shown only while the game is in front)
        self.game_in_front = not overlay.only_over_game
        self.widths: Dict[tuple, int] = {}  # (font size, text) -> pixels; measuring hundreds of names is slow
        self.fonts: tuple = ()  # Tk drops a font once Python lets go of it
        self.rendering = self.render_again = False
        self.guide = ShopGuide.create(
            tk, root, overlay.art_cache_dir, overlay.guide_file, self.layout["right"],
            on_art=lambda guid: overlay.commands.put(("art", guid)),
            on_closed=lambda: overlay.commands.put(("redraw", None)),
            on_close_click=lambda: overlay.commands.put(("guide_toggle", None)))
        self.tracker = Tracker(tk, root, lambda: self.layout["screen"])
        self.handlers: Dict[str, Callable] = {
            "art": lambda guid: self.guide and self.guide.refresh(guid),
            "board": lambda value: self.guide and self.guide.show_offer(value),
            "guide_context": lambda value: self.guide and self.guide.set_context(*value),
            "guide_toggle": self.toggle_guide,
            "redraw": lambda _: True,
            "tracker": self.new_tracker_data,
            "tracker_toggle": lambda _: self.tracker.toggle(),
            "toast": self.new_toast,
            **{kind: (lambda value, kind=kind: self.set_state(kind, value))
               for kind in ("locked", "deathlink", "shop", "status", "menu")},
            "padlocks": self.new_padlocks,
            "board_ui": self.new_board_ui,
        }

    def overlay_factor(self) -> float:
        """How visible the whole overlay is, by the game's own flags - the padlocks' rules (owner, 2026-10-01:
        "infact the entire overlay should follow those rules"): hidden under a dialog (Esc menu) or while your
        stash slides, 30% while a card's tooltip shows or a card is dragged. 1 when the flags can't be read."""
        ui = self.board_ui
        if ui is None:
            return 1.0
        if ui.dialog or ui.stash_moving:
            return 0.0
        return HOVERED_ALPHA if ui.hovering or ui.dragging else 1.0

    def faded_windows(self) -> list:
        """(window, its own alpha) for every overlay window the fade scales."""
        out = [(self.alert_box, ALERT_ALPHA), (self.notice_box, ALERT_ALPHA), (self.toast_box, ALERT_ALPHA),
               (self.menu_box, ALERT_ALPHA),
               (self.shop_first, 1.0),
               (self.shop_second, 1.0)] + [(backdrop, LIST_ALPHA) for backdrop in self.backdrops.values()]
        if self.guide and not self.guide_fading:
            out.append((self.guide.win, 1.0))
        if self.tracker.win is not None and self.tracker.win.winfo_exists():
            out.append((self.tracker.win, 1.0))
        return out

    def padlock_alpha(self) -> float:
        """By the game's own flags (owner, 2026-10-01): hidden while a dialog (Esc menu) covers the board or your
        stash slides open or shut, see-through while a card's tooltip shows or a card is dragged. Unreadable flags:
        by the mouse."""
        ui = self.board_ui
        if ui is None:  # the mouse, but only while the game is in front (owner: nothing outside the game)
            return HOVERED_ALPHA if self.game_in_front and mouse_on(self.padlock_cards) else 1.0
        if ui.dialog or ui.stash_moving:  # the client swaps to the stash's own padlocks once it's open
            return 0.0
        return HOVERED_ALPHA if ui.hovering or ui.dragging else 1.0

    def fade_padlocks(self) -> None:
        """Every HOVER_MS: the padlocks' see-through-ness follows padlock_alpha; one still waiting checks if it's due."""
        try:
            if self.pending_padlocks and self.show_due_padlocks():
                self.render()
            alpha = self.padlock_alpha() if self.padlocks_wanted else 1.0
            if alpha != self.padlocks_faded:
                self.padlocks_faded = alpha
                for padlock in self.padlocks:
                    padlock.attributes("-alpha", alpha)
            factor = self.overlay_factor()
            if factor != self.overlay_faded:
                if (factor == 0) != (self.overlay_faded == 0):
                    self.sync_visibility()  # hidden, not just see-through: an invisible window still takes clicks
                self.overlay_faded = factor
                for window, own in self.faded_windows():
                    window.attributes("-alpha", own * factor)
        except Exception:
            logger.exception("Overlay error (it keeps going)", extra=FILE_ONLY)
        self.root.after(HOVER_MS, self.fade_padlocks)

    def run(self) -> None:
        # laid out once now: with the game exactly on the primary screen no later tick sees a "move", and an open
        # Shop Guide showed at its unsettled size over the game's corner (review 2026-09-30)
        self.render()
        self.root.after(POLL_MS, self.poll)
        self.root.after(HOVER_MS, self.fade_padlocks)
        self.root.mainloop()

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
        if panel in self.backdrops:  # the colour goes on the backdrop; in the list window it turns see-through
            self.backdrops[panel].configure(bg=bg)
            panel.attributes("-transparentcolor", bg)
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

    def sync_visibility(self) -> None:
        """Show what has something to show, but only while The Bazaar (or one of these windows) is in front - and
        not while the game's own flags hide the overlay (a fully faded window would still catch clicks)."""
        guide = self.guide.win if self.guide else None
        front = self.game_in_front and self.overlay_factor() > 0
        for window in self.panels + ([guide] if guide else []):
            show = front and (not self.guide.hidden if window is guide else window in self.wanted)
            layers = [self.backdrops[window], window] if window in self.backdrops else [window]  # bottom to top
            if show and window.state() != "normal":
                for layer in layers:
                    layer.deiconify()
                    layer.lift()
                    if window in self.click_through:
                        screens.click_through(layer)
                if window is guide:
                    self.guide.place_on_screen(self.layout["screen"])  # needs it shown to measure its frame
            elif not show and window.state() == "normal":
                for layer in layers:
                    layer.withdraw()
        for i, padlock in enumerate(self.padlocks):
            show = front and i < self.padlocks_wanted
            if show and padlock.state() != "normal":
                padlock.deiconify()
                padlock.lift()
                screens.click_through(padlock)  # the card under it must stay clickable, tooltip and all
            elif not show and padlock.state() == "normal":
                padlock.withdraw()
        self.tracker.set_visible(front)

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
        toasts = tuple((text, warning) for text, _, warning in state["toasts"])
        if toasts != drawn["toasts"]:
            drawn["toasts"] = toasts
            drawn["toasts_height"] = self.render_toasts(moves)
        x, y, width, height = layout["right"]  # the right column above the pop-ups
        right = (x, y, width, height - (drawn["toasts_height"] + WINDOW_GAP if drawn["toasts_height"] else 0))
        notices = (state["deathlink"], state["locked"], right)
        if notices != drawn["notices"]:
            drawn["notices"] = notices
            drawn["notices_height"] = self.render_notices(moves, right)
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
        guide_hidden = self.guide.hidden if self.guide else True
        shop = (state["shop"], drawn["alerts_height"], drawn["notices_height"], guide_hidden, right, self.list_hidden)
        if shop != drawn["shop"]:
            drawn["shop"] = shop
            self.render_shop(moves, drawn["alerts_height"], below(right, drawn["notices_height"]))
        padlocks = (state["padlocks"], layout["window"])
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
                if panel in self.backdrops:
                    self.backdrops[panel].geometry(geometry)
        self.sync_visibility()

    def buttons(self) -> list:
        """(label, action) for the buttons in the alert box (the list and pop-ups let clicks through): the tracker
        (user: "on the permanent top-left overlay"), the Shop Guide when it's closed, and hiding the list."""
        state = self.state
        buttons = [("Tracker", self.tracker.toggle)] if self.tracker.data else []
        if self.guide:  # any time, not only in a shop; the same button closes it (owner, 2026-10-01)
            buttons.append(("Shop Guide" if self.guide.hidden else "Hide guide", self.toggle_guide))
        if state["shop"] and state["shop"][1]:
            buttons.append(("Show list" if self.list_hidden else "Hide list", self.toggle_list))
        return buttons

    def toggle_guide(self, _=None) -> bool:
        """Opens or closes the Shop Guide with a short fade (owner, 2026-10-01: "a simple transition")."""
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

    def toggle_list(self) -> None:
        self.list_hidden = not self.list_hidden

    def render_menu(self, moves: list) -> None:
        """On the menu: a grid of hero tiles like the game's hero select - portrait, name, a bar of checks done
        (gold) and ready to do (green) out of all of them - the picked hero framed gold (red when it can't be
        played), locked heroes dimmed; a warning banner on top, the goal at the bottom. In the centre of the game
        window and click-through, so it never blocks the menu (owner, 2026-10-01)."""
        tk, f, layout, data = self.tk, self.font, self.layout, self.state["menu"]
        if not data:
            moves.append((self.menu_box, None))
            return
        k = layout["k"]
        bg = SEVERITY["info"]
        frame, show = self.swap(self.menu_box, bg)
        tk.Label(frame, text="HEROES IN THIS MULTIWORLD", fg=ACCENT, bg=bg, font=f(15, "bold")).pack(pady=(0, 6))
        if data["warning"]:
            tk.Label(frame, text=data["warning"], fg=FG, bg=SEVERITY["critical"], font=f(12, "bold"),
                     padx=10, pady=6, wraplength=round(MENU_WIDTH * k)).pack(fill="x", pady=(0, 8))
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
            if not hero["unlocked"]:
                tk.Label(tile, text="LOCKED", fg=WARN, bg=bg, font=f(9, "bold")).pack(pady=(2, 0))
                continue
            bar = tk.Canvas(tile, width=bar_width, height=bar_height, bg=MENU_BAR_BG, highlightthickness=0)
            bar.pack(pady=(2, 0))
            total = max(1, hero["total"])
            done_w = round(bar_width * hero["done"] / total)
            ready_w = round(bar_width * hero["ready"] / total)
            bar.create_rectangle(0, 0, done_w, bar_height, fill=ACCENT, width=0)
            bar.create_rectangle(done_w, 0, done_w + ready_w, bar_height, fill=GOOD, width=0)
            tk.Label(tile, text=f"{hero['done']}/{hero['total']}  ({hero['ready']} ready)", fg=MUTED, bg=bg,
                     font=f(8)).pack()
        bypasses = f"   ·   Lock Bypasses: {data['bypasses']}" if data["bypasses"] else ""
        tk.Label(frame, text=f"Goal: {data['won']} / {data['required']} heroes won{bypasses}", fg=MUTED, bg=bg,
                 font=f(10)).pack(pady=(6, 0))
        tk.Label(frame, text="gold: checks done   green: ready to do now", fg=DIM, bg=bg, font=f(8)).pack()
        show()
        self.menu_box.update_idletasks()
        width, height = self.menu_box.winfo_reqwidth(), self.menu_box.winfo_reqheight()
        x, y, w, h = layout["window"]
        moves.append((self.menu_box, (x + (w - width) // 2, y + (h - height) // 2, width, height)))

    def hero_picture(self, hero: str, k: float):
        """The hero's portrait for the menu panel (the tracker's cards), sized for the window; None if missing."""
        key = (hero, k < 0.9)
        if key not in self.hero_pictures:
            from .tracker import card_image
            self.hero_pictures[key] = card_image(self.tk, self.root, hero, half=True)
            if self.hero_pictures[key] is not None and k < 0.9:
                self.hero_pictures[key] = self.hero_pictures[key].subsample(2)
        return self.hero_pictures[key]

    def render_toasts(self, moves: list) -> int:
        """Pop-ups at the bottom of the right strip, newest at the bottom; returns their height."""
        tk, layout = self.tk, self.layout
        if not self.state["toasts"]:
            moves.append((self.toast_box, None))
            return 0
        frame, show = self.swap(self.toast_box, SEVERITY["info"])
        for text, _, warning in self.state["toasts"]:
            tk.Label(frame, text=text, fg=FG, bg=SEVERITY["critical" if warning else "ok"],
                     font=self.font(11, "bold"), wraplength=layout["right"][2] - 2 * (PAD + BORDER) - 16,
                     justify="left", padx=8, pady=4).pack(fill="x", pady=2)
        show()
        self.toast_box.update_idletasks()
        x, y, width, strip_height = layout["right"]
        height = min(self.toast_box.winfo_reqheight(), strip_height // TOAST_SHARE)
        moves.append((self.toast_box, (x, y + strip_height - height, width, height)))
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
        bg = SEVERITY[self.notice_severity()]
        frame, show = self.swap(self.notice_box, bg)
        if state["deathlink"]:
            tk.Label(frame, text="DEATHLINK", fg=ACCENT, bg=bg, font=f(16, "bold")).pack(anchor="w")
            tk.Label(frame, text=state["deathlink"], fg=FG, bg=bg, font=f(11), wraplength=inner_w,
                     justify="left").pack(anchor="w")
            tk.Label(frame, text="Abandon your current run (Settings > Abandon Run).", fg=FG, bg=bg,
                     font=f(11, "bold"), wraplength=inner_w, justify="left").pack(anchor="w", pady=(2, 6))
            tk.Button(frame, text="Done", command=self.dismiss_deathlink).pack(anchor="e")
        if state["locked"]:
            title, cards, _ = state["locked"]
            tk.Label(frame, text=title, fg=ACCENT, bg=bg, font=f(14, "bold"), wraplength=inner_w,
                     justify="left").pack(anchor="w", pady=(6 if state["deathlink"] else 0, 2 if cards else 0))
            if len(cards) > MAX_ALERT_LINES:  # the box would grow past its share and hide its own buttons
                cards = cards[:MAX_ALERT_LINES - 1] + [f"+ {len(cards) - MAX_ALERT_LINES + 1} more"]
            for line in cards:  # cleared automatically when the log says it was sold
                text, guid = line if isinstance(line, tuple) else (line, None)
                if not guid:
                    tk.Label(frame, text=text, fg=FG, bg=bg, font=f(11), wraplength=inner_w,
                             justify="left").pack(anchor="w")
                    continue
                card = tk.Frame(frame, bg=bg)
                card.pack(fill="x")
                use = tk.Button(card, text="Use Bypass", font=f(9, "bold"), padx=4, pady=0,
                                command=lambda g=guid: self.overlay.on_bypass and self.overlay.on_bypass(g))
                use.pack(side="right", anchor="n", padx=(4, 0))
                use.update_idletasks()
                tk.Label(card, text=text, fg=FG, bg=bg, font=f(11), wraplength=inner_w - use.winfo_reqwidth() - 8,
                         justify="left").pack(side="left", anchor="w")
        show()
        x, y, width, height = right
        return self.place(moves, self.notice_box, (x, y, width, height // ALERT_SHARE))

    def render_alerts(self, moves: list, buttons: list) -> int:
        """The left column's header: the status line with the buttons (Shop Guide, Tracker, the list) on its right;
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
            text, warning, big = status
            tk.Label(row, text=text, fg=WARN if warning else (FG if big else MUTED), bg=bg,
                     font=f(12 if big else 11 if warning else 10, "bold" if warning or big else "normal"),
                     wraplength=inner_w if own_row else room, justify="left").pack(side="left", anchor="w")
        show()
        x, y, width, strip_height = self.layout["left"]
        return self.place(moves, self.alert_box, (x, y, width, strip_height // ALERT_SHARE))

    def measurer(self, size: int) -> tuple:
        """(line width, line height) at a pixel size, for fit_names; widths are cached (the slow part)."""
        font = self.tkfont.Font(root=self.root, family=FONT, size=-size)
        bold = self.tkfont.Font(root=self.root, family=FONT, size=-size, weight="bold")
        self.fonts = (font, bold)

        def line_width(line: str) -> int:
            if (size, line) not in self.widths:
                self.widths[size, line] = bold.measure(line) if len(line) == 1 else font.measure(line) + INDENT
            return self.widths[size, line]
        return line_width, font.metrics("linespace")

    def render_shop(self, moves: list, alerts_height: int, right: tuple) -> None:
        tk, state, layout, f = self.tk, self.state, self.layout, self.font
        if not state["shop"] or (self.list_hidden and state["shop"][1]):
            moves += [(self.shop_first, None), (self.shop_second, None)]
            return
        merchant, names, verb, exact = state["shop"]
        bg = SEVERITY["warning" if names else "ok"]
        # the right strip first (the left one is the Shop Guide's, owner 2026-10-01), then under the alert box
        # while the guide is closed
        first, inner = right, right[2] - 2 * (PAD + BORDER)  # right: the column under the notices
        second = below(layout["left"], alerts_height)
        first_frame, show_first = self.swap(self.shop_first, bg)
        if names:
            advice = "don't buy them" if verb == "sell" else "pick something else"
            what = f"{merchant} is offering" if exact else f"{merchant} may {verb}"  # exact: padlocked on screen
            tk.Label(first_frame, text=f"{what} these LOCKED cards - {advice}:", fg=ACCENT, bg=bg,
                     font=f(11, "bold"), wraplength=inner, justify="left").pack(anchor="w", pady=(0, 4))
        else:  # nothing locked: just a small tick
            tk.Label(first_frame, text=f"✔  {merchant}: buy freely", fg=GOOD, bg=bg, font=f(11, "bold"),
                     wraplength=inner, justify="left").pack(anchor="w")
        first_frame.update_idletasks()
        areas = [(inner, first[3] - first_frame.winfo_reqheight() - WINDOW_GAP)]
        if not self.guide or self.guide.hidden:  # under the alert box is the Shop Guide's while it's open
            areas.append((layout["inner_w"], second[3] - 2 * (PAD + BORDER)))
        sizes = sorted({max(MIN_FONT, round(size * layout["k"])) for size in FONT_SIZES}, reverse=True)
        _, placed, missing, column_width, line_height = fit_names(names, areas, sizes, self.measurer)
        font, bold = self.fonts
        if missing:  # e.g. Make a Wish, which can deal almost any item: a partial A-to-D list would mislead
            placed = [[] for _ in areas]
            tk.Label(first_frame, text=f"Could be any of {len(names)} locked cards - too many to list. If you take "
                                       f"a locked one, sell it before your next fight.", fg=FG, bg=bg, font=f(10),
                     wraplength=inner, justify="left").pack(anchor="w")
        else:
            draw_columns(tk, first_frame, placed[0], font, bold, column_width, line_height, bg)
        show_first()
        self.place(moves, self.shop_first, first)
        if len(placed) > 1 and placed[1]:
            second_frame, show_second = self.swap(self.shop_second, bg)
            draw_columns(tk, second_frame, placed[1], font, bold, column_width, line_height, bg)
            show_second()
            self.place(moves, self.shop_second, second)
        else:
            moves.append((self.shop_second, None))

    def render_padlocks(self) -> None:
        """Moves a padlock onto the centre of each locked card on offer (see card_centres)."""
        layout, value = self.layout, self.state["padlocks"]
        screen, sizes, locked, level = value or (None, (), (), None)
        gap = ROW_GAPS.get(screen, 0)
        centres = card_centres(*layout["window"], sizes, gap) if value else None
        self.padlock_cards = card_rects(*layout["window"], sizes, gap, level) if value else []
        spots = [centres[i] for i in locked if i < len(centres)] if centres else []
        size = max(MIN_PADLOCK, round(PADLOCK * layout["k"]))
        while len(self.padlocks) < len(spots):
            self.padlocks.append(self.new_padlock())
        for padlock, (x, y) in zip(self.padlocks, spots):
            if padlock.drawn_size != size:
                self.draw_padlock(padlock, size)
            padlock.geometry(screens.geometry(screens.clamp((x - size // 2, y - size // 2, size, size),
                                                            layout["screen"])))
        self.padlocks_wanted = len(spots)

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
        padlock.attributes("-alpha", self.padlocks_faded)
        return padlock

    @staticmethod
    def draw_padlock(padlock, s: int) -> None:
        canvas = padlock.canvas
        canvas.delete("all")
        canvas.configure(width=s, height=s)
        padlock_shape(canvas, 0, 0, s)
        padlock.drawn_size = s

    def dismiss_deathlink(self) -> None:
        self.state["deathlink"] = None
        self.render()

    # --- commands and the loop --------------------------------------------------------------------------------

    def set_state(self, kind: str, value) -> bool:
        self.state[kind] = value
        return True

    def new_padlocks(self, value) -> bool:  # (padlocks, since, wait for the reveal)
        self.pending_padlocks, self.reveal_started = value, False
        if not self.show_due_padlocks() and self.state["padlocks"]:
            self.state["padlocks"] = None  # the old cards' padlocks go at once (user: they lingered on a reroll)
        return True

    def new_board_ui(self, ui) -> bool:
        self.board_ui = ui
        return self.show_due_padlocks()

    def show_due_padlocks(self) -> bool:
        """The latest padlocks once they may show (a newer command replaces one still waiting). New cards: once
        the game's reveal has started and ended; if it hasn't started within FLIP_SECONDS (or can't be read), after
        FLIP_SECONDS; never later than FLIP_MAX."""
        if not self.pending_padlocks:
            return False
        value, since, reveal = self.pending_padlocks
        waited, ui = time.monotonic() - since, self.board_ui
        if ui and ui.revealing:
            self.reveal_started = True
        if reveal and waited < FLIP_MAX:
            if self.reveal_started and ui and ui.revealing:
                return False
            if not self.reveal_started and waited < FLIP_SECONDS:
                return False
        self.state["padlocks"], self.pending_padlocks = value, None
        return True

    def new_toast(self, value) -> bool:  # (text, expires, warning)
        self.state["toasts"] = (self.state["toasts"] + [value])[-MAX_TOASTS:]
        return True

    def new_tracker_data(self, data) -> bool:
        first = not self.tracker.data
        self.tracker.update(data)
        return first  # the Tracker button appears once there's something to track

    def own_windows(self) -> Set[int]:
        windows = self.panels + list(self.backdrops.values()) + self.padlocks
        return {screens.window_handle(w) for w in windows} | set(self.tracker.windows()) |             set(self.guide.windows() if self.guide else [])

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
        while True:
            try:
                kind, value = overlay.commands.get_nowait()
            except queue.Empty:
                break
            if kind == "quit":
                if self.guide:
                    self.guide.shutdown()
                self.hero_pictures.clear()  # images are freed here, in Tk's own thread, not at exit from another
                self.root.destroy()
                return "quit"
            changed = bool(self.handlers[kind](value)) or changed
        changed = self.show_due_padlocks() or changed
        now = time.monotonic()
        if any(expires <= now for _, expires, _ in self.state["toasts"]):
            self.state["toasts"] = [t for t in self.state["toasts"] if t[1] > now]
            changed = True
        game, window = game_in_front(self.own_windows()) if overlay.only_over_game else (True, overlay.game_window)
        if window and window != self.layout["window"]:  # the game window moved, was resized or changed resolution
            self.relayout(window)
            self.drawn.update(alerts=None, shop=None, toasts=None)  # everything is laid out again
            changed = True
        if game is not None and game != self.game_in_front:
            self.game_in_front = game
            self.sync_visibility()
        if self.guide and self.game_in_front and not self.guide.hidden and self.guide.win.state() == "iconic":
            self.guide.win.deiconify()  # Windows minimised it along with something else: it belongs on screen
        if changed:
            self.render()
        else:
            self.keep_on_top()

    def keep_on_top(self) -> None:
        """Games sometimes take the top spot; the shown windows claim it back (the list's text above its backdrop)."""
        for panel in self.panels:
            if panel.state() == "normal":
                for layer in ([self.backdrops[panel]] if panel in self.backdrops else []) + [panel]:
                    layer.attributes("-topmost", True)
        if self.guide and self.guide.win.state() == "normal":
            self.guide.win.attributes("-topmost", True)
        for padlock in self.padlocks:
            if padlock.state() == "normal":
                padlock.attributes("-topmost", True)
