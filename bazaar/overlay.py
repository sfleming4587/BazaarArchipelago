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
from typing import Callable, Dict, List, Optional, Sequence, Set

from . import padlocks, screens
from .padlocks import Padlock
from .data import CARDS_BY_GUID
from .shop_guide import ShopGuide
from .theme import (ACCENT, BONE, DIM, FG, FLAMES, FONT, LOCKED_X, MUTED, OUTLINE, SEVERITY, TRAP_BG, TRAP_TITLE,
                    WARN)
from .tracker import Tracker

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
MAX_TOASTS = 8  # as many as fit above them, up to this many (owner, 2026-10-02: "as much as it can")
MAX_TOAST_PICTURES = 3  # an UNLOCKED pop-up shows this many of its cards' pictures; more become "+ N more"
MENU_WIDTH = 460  # the menu's centre panel, 1080p pixels (scaled with the window)
MENU_TILE = 100  # one hero's tile
MENU_COLUMNS = 4  # heroes per row, like the hero select
MENU_BAR_BG = "#3a3f4b"  # the empty part of a hero's check bar
POLL_MS = 250

# Padlocks on locked merchants/events (docs/ENCOUNTER-LOCKS.md): each option's centre at 1080p, (x from the window's
# centre, y from its top), by screen - "Choice-N" is the hourly choice with N options, "Line-N" an event's own options
# in a row. Measured 2026-10-02 on the owner's screenshots: the hourly 3 sit where the monster pick's do (Event3.jpg,
# owner: "they show the same positions the monsters are in"), 245 apart, the middle one 61 lower; the ticket day's 4
# keep that pitch and those heights (OffCenter4Event.jpg). A line is 282 apart (EventToEvents.webp) and centred
# whatever its count (owner, 2026-10-02: without the portal's extra bubble its events move to the centre, and other
# events can add such options too). A hourly count not listed gets no padlocks: its layout hasn't been measured.
CHOICE_ROWS = {"Choice-3": ((-245, 303), (0, 364), (245, 303)),
               "Choice-4": ((-367, 303), (-122, 364), (122, 364), (367, 303))}
LINE_PITCH, LINE_Y = 282, 420
FLICKER_MS = 140  # the Sell Trap's flames
# A flame's outline, as fractions of the skull's square (x right, y down); the inner flames are it shrunk upward.
FLAME = ((0.10, 1.0), (0.02, 0.55), (0.17, 0.30), (0.23, 0.46), (0.30, 0.10), (0.41, 0.36), (0.50, 0.0),
         (0.59, 0.36), (0.70, 0.10), (0.77, 0.46), (0.83, 0.30), (0.98, 0.55), (0.90, 1.0))
FADE_STEPS, FADE_MS = 6, 25  # opening and closing the Shop Guide: a short fade (owner: "a simple transition")
FLIP_SECONDS = 1.0  # new cards flip over first: if the game's reveal flag doesn't start by then, show anyway
FLIP_DELAY = 0.7  # a shop's first card turns face-up this long after the reveal flag (3 of 3 clips, 2026-10-14)
FLIP_EARLY = 0.5  # a reveal that began this long before new cards' padlocks came in is theirs (the client reads
# offers every 0.3 s; the game starts flipping 0.3 s after dealing, and an event's flip can be over 0.3 s later)
HOVER_MS = 2  # how often the Tk thread looks for a new board read (client.MEMORY_SECONDS, 60 a second); the padlocks
# move on each new read - one clock for both, so they don't drift against each other (owner 2026-10-15: padlocks
# looked ~20 fps). Needs the client's 1 ms timers (client.main): Windows otherwise rounds a Tk timer up to its
# ~15.6 ms tick (16 ran ~45 times a second, 8 ~64, measured 2026-10-15)
FOLLOW_SECONDS = 1 / 60  # ...and at least this often without a new read (the reader off, or a read that failed)
PADLOCK = 56  # the mark's size
MIN_PADLOCK = 24  # real pixels, however small the window
PADLOCK_KEY = "#010203"  # the padlock window's see-through colour
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


def event_row(screen: Optional[str]) -> Optional[tuple]:
    """Each option's centre at 1080p on an event screen ("Choice-N" or "Line-N"), left to right; None when that
    layout isn't known."""
    kind, _, count = (screen or "").partition("-")
    if kind == "Line" and count.isdigit() and int(count) > 0:
        return tuple(((i - (int(count) - 1) / 2) * LINE_PITCH, LINE_Y) for i in range(int(count)))
    return CHOICE_ROWS.get(screen)


def event_centres(x: int, y: int, w: int, h: int, screen: str) -> List[tuple]:
    """Screen centre (x, y) of each option on an event choice screen (see event_row), left to right."""
    across = min(h / 1080, w / 1920)
    return [(round(x + w / 2 + dx * across), round(y + h * cy / 1080)) for dx, cy in event_row(screen)]



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


class Overlay:
    """The client's handle on the windows: every method only queues a command for the Tk thread."""

    def __init__(self, art_cache_dir: Optional[str] = None, guide_file: Optional[str] = None) -> None:
        self.only_over_game = True  # False shows the windows whatever is in front (tests)
        self.game_window: Optional[tuple] = None  # tests: pretend the game's client area is here (x, y, w, h)
        self.guide_file = guide_file  # where the Shop Guide remembers whether it's closed and where you put it
        self.art_cache_dir = art_cache_dir
        self.on_bypass: Optional[Callable[[str], None]] = None  # the client: use a Lock Bypass on a held card
        self.latest_board_ui = None  # the newest board flags (see show_board_ui)
        self.commands: "queue.Queue" = queue.Queue()
        self.available = True  # False if the windows can't open (no tkinter, or Tk can't start)
        self.ready = threading.Event()  # set once the windows are up (or failed to come up)
        self.thread = threading.Thread(target=self._run, name="bazaar overlay", daemon=True)
        self.thread.start()

    # --- called from the client ---------------------------------------------------------------------------------

    def show_locked(self, title: Optional[str], cards: list, blocked: bool = False, trap: bool = False) -> None:
        """The alert box's banner and the lines under it (held locked cards, Sell Traps). title=None hides it.
        A line is text, or (text, card guid) to give it a "Use Bypass" button (a Lock Bypass is ready).
        blocked: checks are blocked (critical, red) rather than just a warning (a Sell Trap coming up).
        trap: a Sell Trap is behind it - drawn as a skull in flames."""
        self.commands.put(("locked", (title, list(cards), blocked, trap) if title else None))

    def show_padlocks(self, locks: Sequence[Padlock], reveal: bool = False, options: Optional[str] = None) -> None:
        """The padlocks on what's offered: each on its card (padlocks.Padlock), or on an event option at its spot
        of the measured layout `options` (an event_row key). None hides them at once. reveal: new cards, so they
        wait until each has turned face-up."""
        value = (tuple(locks), options) if locks else None
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

    def show_board(self, title: Optional[str], offered: List[str], merchant: Optional[str]) -> None:
        """Shop Guide: what's on offer on screen (card guids, first, framed in gold) and the merchant you're at (its
        stock is listed below). title=None: you left; the guide keeps its list and filters."""
        self.commands.put(("board", (title, tuple(offered), merchant) if title else None))

    def guide_context(self, hero: Optional[str], locked) -> None:
        """Shop Guide: your hero and the cards you may not hold (greyed out with a red cross)."""
        self.commands.put(("guide_context", (hero, frozenset(locked))))

    def toggle_guide(self) -> None:
        self.commands.put(("guide_toggle", None))

    def toast(self, text: str, seconds: float = 6, warning: bool = False, trap: bool = False,
              cards: Sequence[str] = ()) -> None:
        """A short pop-up (bottom right) that disappears by itself. trap: a Sell Trap's, with its skull. cards: guids
        whose pictures it shows (an unlock's)."""
        self.commands.put(("toast", (text, time.monotonic() + seconds, warning, trap, tuple(cards))))

    def show_menu_covered(self, covered: bool) -> None:
        """One of the game's own screens is open over the menu (or not): picked up every HOVER_MS by the Tk thread,
        like the board's flags, so the hero panel goes and comes back with the game's screens."""
        self.latest_menu_covered = covered

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
        self.overlay, self.tk, self.root = overlay, tk, root
        root.withdraw()
        # No two windows overlap: the alert box (root) takes the top of the left strip, the locked-card list goes
        # right under it, and the right strip belongs to the Shop Guide - or, while the guide is closed, to the
        # rest of a long list. Pop-ups (toasts) stack up from the bottom of the right strip, which then shrinks.
        # Owner, 2026-10-01: "The shop guide is always going to be the whole left column": the alert box (root) is
        # now just its header (status and buttons); DeathLink, held locked cards and Sell Traps are the notices box at
        # the top of the right column, the pop-ups at the bottom. The locked-card list that sat between them went
        # (owner, 2026-10-01: the padlocks on the cards themselves say it).
        # On the menu (no run, no board) the heroes you may play sit in the centre (owner, 2026-10-01).
        self.alert_box, self.notice_box, self.toast_box, self.menu_box = \
            root, tk.Toplevel(root), tk.Toplevel(root), tk.Toplevel(root)
        self.panels = [self.alert_box, self.notice_box, self.toast_box, self.menu_box]
        # nothing to click in these (the menu panel must never block the game's menu buttons)
        self.click_through = {self.toast_box, self.menu_box}
        for panel in self.panels:
            panel.withdraw()
            panel.overrideredirect(True)
            panel.attributes("-topmost", True)
            panel.attributes("-alpha", ALERT_ALPHA)
            panel.configure(bg=SEVERITY["info"], highlightthickness=BORDER, highlightbackground=ACCENT)
            screens.never_focus(panel)
        self.padlocks: list = []  # one small click-through window per padlock, made as needed and reused
        self.padlocks_wanted = 0  # how many of them are in use
        self.pending_padlocks = None  # (padlocks, since, wait for the reveal) while new cards are still flipping
        self.reveal_started = False  # the game's reveal began since those padlocks came in
        self.reveal_began = -FLIP_EARLY  # when the game's current (or last) reveal began
        self.reveal_ended = -FLIP_EARLY  # when the game's last reveal ended
        self.stagger_from = 0.0  # new padlocks show left to right from then, padlocks.FLIP_STAGGER apart (0: all at once)
        self.locks: List[Padlock] = []  # the padlocks shown now: what's offered (or the stash), then your board
        self.lock_squares: List[Optional[tuple]] = []  # each one's square on screen now (None: its card isn't)
        self.option_centres: List[tuple] = []  # an event screen's measured option centres (Padlock.option)
        self.padlock_alphas: List[float] = []  # each padlock's alpha now (see padlock_alpha)
        self.board_ui = None  # memreader.BoardUI, or None (unreadable: no padlocks, nothing says the art is there)
        self.overlay_faded = 1.0  # every other window's fade now (see overlay_factor)
        self.followed = (None, 0.0)  # (board read, when) the padlocks and fades last followed (see fade_padlocks)
        self.guide_fading = False  # the Shop Guide is fading in or out (a second click waits for it)

        self.layout: dict = {}  # the strips for where the game window is now (see relayout)
        self.relayout((0, 0, root.winfo_screenwidth(), root.winfo_screenheight()))  # until the game is seen
        self.state = {"locked": None, "deathlink": None, "toasts": [], "status": None,
                      "padlocks": None, "board_padlocks": None, "menu": None}
        self.hero_pictures: Dict[str, object] = {}  # the menu panel's portraits (Tk drops an image Python lets go)
        self.toast_pictures: Dict[tuple, object] = {}  # UNLOCKED pop-ups' card pictures, (guid, halved) -> image
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
        self.game_in_front = not overlay.only_over_game
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
            "tracker_toggle": lambda _: self.tracker.toggle(),
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

    def faded_windows(self) -> list:
        """(window, its own alpha) for every overlay window the fade scales."""
        out = [(self.alert_box, ALERT_ALPHA), (self.notice_box, ALERT_ALPHA), (self.toast_box, ALERT_ALPHA),
               (self.menu_box, ALERT_ALPHA)]
        if self.guide and not self.guide_fading:
            out.append((self.guide.win, 1.0))
        if self.tracker.win is not None and self.tracker.win.winfo_exists():
            out.append((self.tracker.win, 1.0))
        return out

    def padlock_alpha(self, i: int, covers: List[tuple]) -> float:
        """Padlock i by the rules in padlocks.py; none while the board's flags can't be read (owner, 2026-10-15: a
        padlock shows only where its card's art is - was: event options followed the mouse, 2026-10-01)."""
        if self.board_ui is None:
            return padlocks.HIDDEN
        return padlocks.alpha(self.locks[i], self.lock_squares[i], self.board_ui, covers,
                              padlocks.COVER_PAD * self.layout["k"], self.stagger_from, time.monotonic())

    def covers(self) -> List[tuple]:
        return padlocks.coverings(self.board_ui, self.layout["window"]) if self.board_ui is not None else []

    def fade_padlocks(self) -> None:
        """Every HOVER_MS: on a new board read (or FOLLOW_SECONDS without one, or after a render) each padlock and
        window follows what covers it; one still waiting checks if it's due."""
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
            if not rendered and ui is self.followed[0] and now - self.followed[1] < FOLLOW_SECONDS:
                self.root.after(HOVER_MS, self.fade_padlocks)
                return
            self.followed = (ui, now)
            self.place_padlocks()  # they ride on their cards: dragged, sliding, enlarged
            covers = self.covers()
            self.apply_padlock_alphas(covers)
            factor = self.overlay_factor()
            if factor != self.overlay_faded:
                if (factor == 0) != (self.overlay_faded == 0):
                    self.sync_visibility()  # hidden, not just see-through: an invisible window still takes clicks
                self.overlay_faded = factor
            for window, own in self.faded_windows():
                alpha = own * factor
                if alpha and covers and window.winfo_ismapped():
                    x, y = window.winfo_rootx(), window.winfo_rooty()
                    if padlocks.covered((x, y, x + window.winfo_width(), y + window.winfo_height()), covers):
                        alpha *= padlocks.SEE_THROUGH
                if abs(float(window.attributes("-alpha")) - alpha) > 0.001:  # others set it too (the guide's fade)
                    window.attributes("-alpha", alpha)
        except Exception:
            logger.exception("Overlay error (it keeps going)", extra=FILE_ONLY)
        self.root.after(HOVER_MS, self.fade_padlocks)

    def apply_padlock_alphas(self, covers: List[tuple]) -> None:
        alphas = [self.padlock_alpha(i, covers) for i in range(self.padlocks_wanted)]
        for i, alpha in enumerate(alphas):
            if i >= len(self.padlock_alphas) or self.padlock_alphas[i] != alpha:
                self.padlocks[i].attributes("-alpha", alpha)
        self.padlock_alphas = alphas

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
            if show and window.state() != "normal":
                window.deiconify()
                window.lift()
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
        # the notices first (they matter more), then the pop-ups take all the room left under them
        right = layout["right"]
        notices = (state["deathlink"], state["locked"], right)
        if notices != drawn["notices"]:
            drawn["notices"] = notices
            drawn["notices_height"] = self.render_notices(moves, right)
        toasts = (tuple((text, warning, trap, cards) for text, _, warning, trap, cards in state["toasts"]),
                  drawn["notices_height"])
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
        (user: "on the permanent top-left overlay"), the Shop Guide when it's closed, and hiding the list."""
        state = self.state
        buttons = [("Tracker", self.tracker.toggle)] if self.tracker.data else []
        if self.guide:  # any time, not only in a shop; the same button closes it (owner, 2026-10-01)
            buttons.append(("Shop Guide" if self.guide.hidden else "Hide guide", self.toggle_guide))
        if state["menu"]:
            buttons.append(("Show heroes" if self.menu_hidden else "Hide heroes", self.toggle_menu))
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
            bar = tk.Canvas(tile, width=bar_width, height=bar_height, bg=MENU_BAR_BG, highlightthickness=0)
            bar.pack(pady=(2, 0))
            # the checks you've got with this hero, of all of them (owner, 2026-10-01: "that bar should represent
            # how many checks I have gotten with her")
            bar.create_rectangle(0, 0, round(bar_width * hero["done"] / max(1, hero["total"])), bar_height,
                                 fill=ACCENT, width=0)
            tk.Label(tile, text=f"{hero['done']} / {hero['total']} checks", fg=MUTED, bg=bg, font=f(9)).pack()
            cards.pack()
        bypasses = f"   ·   Lock Bypasses: {data['bypasses']}" if data["bypasses"] else ""
        tk.Label(frame, text=f"Goal: {data['won']} / {data['required']} heroes won{bypasses}", fg=MUTED, bg=bg,
                 font=f(10)).pack(pady=(6, 0))
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

    def toast_picture(self, guid: str):
        """A card's picture for an UNLOCKED pop-up (the Shop Guide's, halved on small windows); None while there
        isn't one yet - the "art" command redraws the pop-up once it's made."""
        card = CARDS_BY_GUID.get(guid)
        if not (self.guide and card):
            return None
        small = self.layout["k"] < 0.9
        key = (guid, small)
        if key not in self.toast_pictures:
            picture = self.guide.picture(card, False)
            if picture is None:
                return None
            self.toast_pictures[key] = picture.subsample(2) if small else picture
        return self.toast_pictures[key]

    def render_toasts(self, moves: list) -> int:
        """Pop-ups at the bottom of the right strip, newest at the bottom; returns their height."""
        tk, layout = self.tk, self.layout
        if not self.state["toasts"]:
            moves.append((self.toast_box, None))
            return 0
        frame, show = self.swap(self.toast_box, SEVERITY["info"])
        wrap = layout["right"][2] - 2 * (PAD + BORDER) - 16
        rows = []  # newest first, packed up from the bottom
        for text, _, warning, trap, cards in reversed(self.state["toasts"]):
            if trap:
                row = tk.Frame(frame, bg=TRAP_BG, padx=6, pady=4)
                row.pack(side="bottom", fill="x", pady=2)
                rows.append(row)
                skull = draw_skull(tk, row, max(32, round(44 * layout["k"])), TRAP_BG)
                skull.pack(side="left", padx=(0, 6))
                tk.Label(row, text=text, fg=TRAP_TITLE, bg=TRAP_BG, font=self.font(11, "bold"),
                         wraplength=wrap - skull.winfo_reqwidth() - 12, justify="left").pack(side="left", anchor="w")
                continue
            bg = SEVERITY["critical" if warning else "ok"]
            row = tk.Frame(frame, bg=bg)
            row.pack(side="bottom", fill="x", pady=2)
            rows.append(row)
            tk.Label(row, text=text, fg=FG, bg=bg, font=self.font(11, "bold"), wraplength=wrap, justify="left",
                     padx=8, pady=4).pack(anchor="w")
            pictures = [p for p in (self.toast_picture(guid) for guid in cards) if p is not None]
            if pictures:
                strip = tk.Frame(row, bg=bg, padx=8)
                strip.pack(anchor="w", pady=(0, 6))
                for picture in pictures[:MAX_TOAST_PICTURES]:
                    tk.Label(strip, image=picture, bg=bg, bd=0).pack(side="left", padx=(0, 4))
                if len(cards) > MAX_TOAST_PICTURES:
                    tk.Label(strip, text=f"+ {len(cards) - MAX_TOAST_PICTURES} more", fg=FG, bg=bg,
                             font=self.font(10, "bold")).pack(side="left", padx=(4, 0))
        show()
        # all the room the notices above leave (owner, 2026-10-02); whole pop-ups that don't fit go, oldest first
        x, y, width, strip_height = layout["right"]
        notices = self.drawn["notices_height"]
        room = strip_height - (notices + WINDOW_GAP if notices else 0)
        self.toast_box.update_idletasks()
        while len(rows) > 1 and self.toast_box.winfo_reqheight() > room:
            rows.pop().destroy()
            self.toast_box.update_idletasks()
        height = min(self.toast_box.winfo_reqheight(), room)
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
        trap = bool(state["locked"] and state["locked"][3])
        bg = TRAP_BG if trap else SEVERITY[self.notice_severity()]
        frame, show = self.swap(self.notice_box, bg)
        if state["deathlink"]:
            tk.Label(frame, text="DEATHLINK", fg=ACCENT, bg=bg, font=f(16, "bold")).pack(anchor="w")
            tk.Label(frame, text=state["deathlink"], fg=FG, bg=bg, font=f(11), wraplength=inner_w,
                     justify="left").pack(anchor="w")
            tk.Label(frame, text="Concede your current run.", fg=FG, bg=bg,
                     font=f(11, "bold"), wraplength=inner_w, justify="left").pack(anchor="w", pady=(2, 6))
        if state["locked"]:
            title, cards, blocked, _ = state["locked"]
            head = tk.Frame(frame, bg=bg)
            head.pack(fill="x", pady=(6 if state["deathlink"] else 0, 2 if cards else 0))
            room = inner_w
            if trap:  # owner, 2026-10-01: "more menacing ... like a skull with a flame behind it"
                skull = draw_skull(tk, head, max(40, round(64 * self.layout["k"])), bg)
                skull.pack(side="left", padx=(0, 8))
                room -= skull.winfo_reqwidth() + 8
            tk.Label(head, text=title, fg=(WARN if blocked else TRAP_TITLE) if trap else ACCENT, bg=bg,
                     font=f(16 if trap else 14, "bold"), wraplength=room, justify="left").pack(side="left", anchor="w")
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

    def render_padlocks(self) -> None:
        """The padlocks wanted now: one window each, sized for the game window (placed by place_padlocks)."""
        layout, value = self.layout, self.state["padlocks"]
        locks, options = value or ((), None)
        self.locks = list(locks) + list(self.state["board_padlocks"] or ())
        window = layout["window"]
        self.option_centres = event_centres(*window, options) if event_row(options) else []
        size = max(MIN_PADLOCK, round(PADLOCK * layout["k"]))
        while len(self.padlocks) < len(self.locks):
            self.padlocks.append(self.new_padlock())
        for padlock in self.padlocks[:len(self.locks)]:
            if padlock.drawn_size != size:
                self.draw_padlock(padlock, size)
        self.padlocks_wanted = len(self.locks)
        self.place_padlocks()
        self.padlock_alphas = []  # set afresh: a moved padlock may be covered (or not) where it is now
        self.apply_padlock_alphas(self.covers())

    def place_padlocks(self) -> None:
        """Each padlock on its card, wherever the card is now (padlocks.spot)."""
        size = max(MIN_PADLOCK, round(PADLOCK * self.layout["k"]))
        self.lock_squares = [padlocks.spot(lock, self.board_ui, self.layout["window"], size, self.option_centres)
                             for lock in self.locks]
        for padlock, square in zip(self.padlocks, self.lock_squares):
            if square is None:
                continue  # hidden by padlock_alpha
            spot = screens.clamp((round(square[0]), round(square[1]), size, size), self.layout["screen"])
            if getattr(padlock, "spot", None) != spot:
                padlock.spot = spot
                padlock.geometry(screens.geometry(spot))

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

    @staticmethod
    def draw_padlock(padlock, s: int) -> None:
        canvas = padlock.canvas
        canvas.delete("all")
        canvas.configure(width=s, height=s)
        padlock_shape(canvas, 0, 0, s)
        padlock.drawn_size = s

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
        FLIP_SECONDS (or the flag can't be read), after FLIP_SECONDS. A dialog still hides them (padlock_alpha)."""
        if not self.pending_padlocks:
            return False
        value, since, reveal = self.pending_padlocks
        ui, now = self.board_ui, time.monotonic()
        if ui and ui.revealing or self.reveal_began >= since - FLIP_EARLY:
            self.reveal_started = True
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
        """A card's pictures are ready: the guide shows them, and so does a pop-up still waiting for them."""
        if self.guide:
            self.guide.refresh(guid)
        if any(guid in t[4] for t in self.state["toasts"]):
            self.drawn["toasts"] = None
            return True
        return False

    def new_toast(self, value) -> bool:  # (text, expires, warning, trap, card guids)
        self.state["toasts"] = (self.state["toasts"] + [value])[-MAX_TOASTS:]
        return True

    def new_tracker_data(self, data) -> bool:
        first = not self.tracker.data
        self.tracker.update(data)
        return first  # the Tracker button appears once there's something to track

    def own_windows(self) -> Set[int]:
        windows = self.panels + self.padlocks
        return {screens.window_handle(w) for w in windows} | set(self.tracker.windows()) |             set(self.guide.windows() if self.guide else [])

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
        while True:
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
        if any(t[1] <= now for t in self.state["toasts"]):
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

    def keep_on_top(self) -> None:
        """Games sometimes take the top spot; the shown windows claim it back."""
        for panel in self.panels:
            if panel.state() == "normal":
                panel.attributes("-topmost", True)
        if self.guide and self.guide.win.state() == "normal":
            self.guide.win.attributes("-topmost", True)
        for padlock in self.padlocks:
            if padlock.state() == "normal":
                padlock.attributes("-topmost", True)
