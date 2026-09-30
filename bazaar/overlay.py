"""
Windows shown above The Bazaar: the alert box, the locked-card list, pop-ups, the Shop Guide and the tracker.

They're separate windows owned by the client; they never draw inside the game or touch its process. They show over
the game when it runs borderless (the default "Fullscreen Window") or windowed, not over exclusive fullscreen.
Tk runs in its own thread; the client only talks to it through the command queue (the Overlay methods).

Rules (user, 2026-09-28/29): beside the board, never on it; never overlapping each other; never off screen;
only while the game is the active window; never taking the keyboard from the game; redrawing only what changed.
"""
import logging
import os
import queue
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Set

from . import screens
from .shop_guide import ShopGuide
from .theme import ACCENT, FG, FONT, GOOD, MUTED, SEVERITY, WARN
from .card_picker import CardPicker
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
MIN_FONT = 9  # never smaller than this many real pixels, however small the window
POINT_TO_PX = 4 / 3  # Tk points to pixels at 96 dpi (the overlay's other text is sized in points)
PAD = 10  # inside every panel
BORDER = 2  # every panel's gold border
WINDOW_GAP = 4  # between two panels that sit on top of each other
INDENT = 8  # names sit a little right of their letter
GAP = 12  # between columns
ALERT_SHARE = 2  # the alert box takes at most 1/2 of the left strip (the rest is the list's)
TOAST_SHARE = 3  # pop-ups take at most 1/3 of the right strip
MAX_TOASTS = 4
POLL_MS = 250
GAME_EXE = "thebazaar.exe"  # the overlay only shows while this is the active window
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
    The process name is looked up every time: Windows reuses process ids, so a cache could name the wrong program.
    """
    if sys.platform != "win32":
        return True, None
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    hwnd = user32.GetAncestor(user32.GetForegroundWindow(), 2)  # GA_ROOT
    if not hwnd:
        return False, None
    if hwnd in own:
        return None, None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ""
    process = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if process:
        buffer, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
            name = os.path.basename(buffer.value).lower()
        kernel32.CloseHandle(process)
    if name != GAME_EXE:
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
        self.on_bypass_pick: Optional[Callable[[str], None]] = None  # the client: spend a Lock Bypass on a card
        self.commands: "queue.Queue" = queue.Queue()
        self.available = True  # False if the windows can't open (no tkinter, or Tk can't start)
        self.ready = threading.Event()  # set once the windows are up (or failed to come up)
        self.thread = threading.Thread(target=self._run, name="bazaar overlay", daemon=True)
        self.thread.start()

    # --- called from the client ---------------------------------------------------------------------------------

    def show_locked(self, title: Optional[str], cards: List[str], blocked: bool = False) -> None:
        """The alert box's banner and the lines under it (held locked cards, Sell Traps). title=None hides it.
        blocked: checks are blocked (critical, red) rather than just a warning (a Sell Trap coming up)."""
        self.commands.put(("locked", (title, list(cards), blocked) if title else None))

    def show_shop(self, merchant: Optional[str], locked: List[str], verb: str = "sell") -> None:
        """Show which locked cards a merchant could sell (or an event could offer). merchant=None hides it."""
        self.commands.put(("shop", (merchant, list(locked), verb) if merchant else None))

    def show_board(self, title: Optional[str], allowed: list, locked: list) -> None:
        """Shop Guide: allowed cards in colour first, locked cards greyed out below. title=None hides it."""
        self.commands.put(("board", (title, list(allowed), list(locked)) if title else None))

    def toast(self, text: str, seconds: float = 6, warning: bool = False) -> None:
        """A short pop-up (bottom right) that disappears by itself."""
        self.commands.put(("toast", (text, time.monotonic() + seconds, warning)))

    def show_status(self, text: Optional[str], warning: bool = False, big: bool = False) -> None:
        """The bottom of the alert box: run progress, or (big) the heroes you may pick on the menu. None hides it."""
        self.commands.put(("status", (text, warning, big) if text else None))

    def show_tracker_data(self, data: Dict[str, dict]) -> None:
        """What the tracker shows (see tracker.Tracker.update); sent whenever items or checks change."""
        self.commands.put(("tracker", data))

    def toggle_tracker(self) -> None:
        self.commands.put(("tracker_toggle", None))

    def show_bypass(self, ready: int, locked) -> None:
        """Lock Bypasses ready in this run (0 = none, or not in a run) and the cards locked this run: the alert box
        gets a Lock Bypass button that opens the card picker."""
        self.commands.put(("bypass", (ready, frozenset(locked)) if ready else None))

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
        self.alert_box, self.shop_first, self.shop_second, self.toast_box = \
            root, tk.Toplevel(root), tk.Toplevel(root), tk.Toplevel(root)
        self.panels = [self.alert_box, self.shop_first, self.shop_second, self.toast_box]
        self.click_through = {self.shop_first, self.shop_second, self.toast_box}  # nothing to click in these
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

        self.layout: dict = {}  # the strips for where the game window is now (see relayout)
        self.relayout((0, 0, root.winfo_screenwidth(), root.winfo_screenheight()))  # until the game is seen
        self.state = {"locked": None, "deathlink": None, "shop": None, "toasts": [], "status": None,
                      "bypass": None}
        self.list_hidden = False  # the player hid the locked-card list (until they show it again)
        # what each window shows now, to skip redraws that change nothing
        self.drawn: dict = {"alerts": None, "shop": None, "toasts": None, "alerts_height": 0, "toasts_height": 0}
        self.wanted: set = set()  # windows that have something to show (shown only while the game is in front)
        self.game_in_front = not overlay.only_over_game
        self.widths: Dict[tuple, int] = {}  # (font size, text) -> pixels; measuring hundreds of names is slow
        self.fonts: tuple = ()  # Tk drops a font once Python lets go of it
        self.rendering = self.render_again = False
        self.guide = ShopGuide.create(
            tk, root, overlay.art_cache_dir, overlay.guide_file, self.layout["right"],
            on_art=lambda guid: overlay.commands.put(("art", guid)),
            on_closed=lambda: overlay.commands.put(("redraw", None)))
        self.tracker = Tracker(tk, root, lambda: self.layout["screen"])
        self.picker = CardPicker(tk, root, lambda: self.layout["screen"],
                                 lambda guid: overlay.on_bypass_pick and overlay.on_bypass_pick(guid))
        self.handlers: Dict[str, Callable] = {
            "art": lambda guid: self.guide and self.guide.refresh(guid),
            "board": lambda value: self.guide and self.guide.render(value),
            "redraw": lambda _: True,
            "tracker": self.new_tracker_data,
            "tracker_toggle": lambda _: self.tracker.toggle(),
            "toast": self.new_toast,
            "bypass": self.new_bypass,
            **{kind: (lambda value, kind=kind: self.set_state(kind, value))
               for kind in ("locked", "deathlink", "shop", "status")},
        }

    def run(self) -> None:
        self.sync_visibility()  # an open Shop Guide shows from the start (while the game is in front)
        self.root.after(POLL_MS, self.poll)
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
        """Show what has something to show, but only while The Bazaar (or one of these windows) is in front."""
        guide = self.guide.win if self.guide else None
        for window in self.panels + ([guide] if guide else []):
            show = self.game_in_front and (not self.guide.hidden if window is guide else window in self.wanted)
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
        self.tracker.set_visible(self.game_in_front)

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
        x, y, width, height = layout["right"]  # the right strip above the pop-ups
        right = (x, y, width, height - (drawn["toasts_height"] + WINDOW_GAP if drawn["toasts_height"] else 0))
        if self.guide:
            self.guide.fit(screens.clamp(right, layout["screen"]), layout["screen"])
        buttons = self.buttons()
        alerts = (state["deathlink"], state["locked"], state["status"], tuple(label for label, _ in buttons))
        if alerts != drawn["alerts"]:
            drawn["alerts"] = alerts
            drawn["alerts_height"] = self.render_alerts(moves, buttons)
        guide_hidden = self.guide.hidden if self.guide else True
        shop = (state["shop"], drawn["alerts_height"], guide_hidden, right, self.list_hidden)
        if shop != drawn["shop"]:
            drawn["shop"] = shop
            self.render_shop(moves, drawn["alerts_height"], right)
        for panel, rect in sorted(moves, key=lambda move: move[0] is self.alert_box):  # alert box grows last
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
        (user: "on the permanent top-left overlay"), the Lock Bypass card picker while one is ready, the Shop Guide
        when it's closed, and hiding the list."""
        state = self.state
        buttons = [("Tracker", self.tracker.toggle)] if self.tracker.data else []
        if state["bypass"]:
            buttons.append(("Lock Bypass", self.picker.toggle))
        if state["shop"] and self.guide and self.guide.hidden:
            buttons.append(("Pictures", self.guide.show))
        if state["shop"] and state["shop"][1]:
            buttons.append(("Show list" if self.list_hidden else "Hide list", self.toggle_list))
        return buttons

    def toggle_list(self) -> None:
        self.list_hidden = not self.list_hidden

    def alert_severity(self) -> str:
        state = self.state
        if state["deathlink"] or (state["locked"] and state["locked"][2]):
            return "critical"
        if state["locked"] or (state["status"] and state["status"][1]):
            return "warning"  # a Sell Trap to deal with, a locked hero picked
        return "info"

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

    def render_alerts(self, moves: list, buttons: list) -> int:
        """Draws the alert box; returns its height (0 when hidden)."""
        tk, state, inner_w, f = self.tk, self.state, self.layout["inner_w"], self.font
        if not (state["deathlink"] or state["locked"] or state["status"] or buttons):
            moves.append((self.alert_box, None))
            return 0
        bg = SEVERITY[self.alert_severity()]
        frame, show = self.swap(self.alert_box, bg)
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
            for text in cards:  # cleared automatically when the log says it was sold
                tk.Label(frame, text=text, fg=FG, bg=bg, font=f(11), wraplength=inner_w,
                         justify="left").pack(anchor="w")
        # last line: the status text with the buttons on its right; the buttons get a row of their own only when
        # that would squeeze the text below half the width
        if state["status"] or buttons:
            row = tk.Frame(frame, bg=bg)
            row.pack(fill="x", pady=(4, 0) if frame.winfo_children()[:-1] else 0)
            bar = tk.Frame(row, bg=bg)
            for label, action in buttons:
                tk.Button(bar, text=label, font=f(8), padx=3, pady=0,
                          command=lambda a=action: (a(), self.render())).pack(side="left", padx=(4, 0))
            bar.update_idletasks()
            room = inner_w - (bar.winfo_reqwidth() + 8 if buttons else 0)
            own_row = bool(state["status"]) and room < inner_w // 2
            if buttons:
                bar.pack(side="bottom" if own_row else "right", anchor="e", pady=(4, 0) if own_row else 0)
            if state["status"]:
                text, warning, big = state["status"]
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
        merchant, names, verb = state["shop"]
        bg = SEVERITY["warning" if names else "ok"]
        first = below(layout["left"], alerts_height)  # the left strip under the alerts first, then the right strip
        first_frame, show_first = self.swap(self.shop_first, bg)
        if names:
            advice = "don't buy them" if verb == "sell" else "pick something else"
            tk.Label(first_frame, text=f"{merchant} may {verb} these LOCKED cards - {advice}:", fg=ACCENT, bg=bg,
                     font=f(11, "bold"), wraplength=layout["inner_w"], justify="left").pack(anchor="w", pady=(0, 4))
        else:  # nothing locked: just a small tick
            tk.Label(first_frame, text=f"✔  {merchant}: buy freely", fg=GOOD, bg=bg, font=f(11, "bold"),
                     wraplength=layout["inner_w"], justify="left").pack(anchor="w")
        first_frame.update_idletasks()
        areas = [(layout["inner_w"], first[3] - first_frame.winfo_reqheight() - WINDOW_GAP)]
        if not self.guide or self.guide.hidden:  # the right strip is the Shop Guide's while it's open
            areas.append((right[2] - 2 * (PAD + BORDER), right[3] - 2 * (PAD + BORDER)))
        sizes = sorted({max(MIN_FONT, round(size * layout["k"])) for size in FONT_SIZES}, reverse=True)
        _, placed, missing, column_width, line_height = fit_names(names, areas, sizes, self.measurer)
        font, bold = self.fonts
        if missing:  # e.g. Make a Wish, which can deal almost any item: a partial A-to-D list would mislead
            placed = [[] for _ in areas]
            tk.Label(first_frame, text=f"Could be any of {len(names)} locked cards - too many to list. If you take "
                                       f"a locked one, sell it before your next fight.", fg=FG, bg=bg, font=f(10),
                     wraplength=layout["inner_w"], justify="left").pack(anchor="w")
        else:
            draw_columns(tk, first_frame, placed[0], font, bold, column_width, line_height, bg)
        show_first()
        self.place(moves, self.shop_first, first)
        if len(placed) > 1 and placed[1]:
            second_frame, show_second = self.swap(self.shop_second, bg)
            draw_columns(tk, second_frame, placed[1], font, bold, column_width, line_height, bg)
            show_second()
            self.place(moves, self.shop_second, right)
        else:
            moves.append((self.shop_second, None))

    def dismiss_deathlink(self) -> None:
        self.state["deathlink"] = None
        self.render()

    # --- commands and the loop --------------------------------------------------------------------------------

    def set_state(self, kind: str, value) -> bool:
        self.state[kind] = value
        return True

    def new_toast(self, value) -> bool:  # (text, expires, warning)
        self.state["toasts"] = (self.state["toasts"] + [value])[-MAX_TOASTS:]
        return True

    def new_bypass(self, value) -> bool:  # (ready, locked guids) or None
        changed = value != self.state["bypass"]
        self.state["bypass"] = value
        self.picker.update(*(value or (0, set())))
        return changed

    def new_tracker_data(self, data) -> bool:
        first = not self.tracker.data
        self.tracker.update(data)
        return first  # the Tracker button appears once there's something to track

    def own_windows(self) -> Set[int]:
        windows = self.panels + list(self.backdrops.values()) + ([self.guide.win] if self.guide else [])
        return {screens.window_handle(w) for w in windows} | set(self.tracker.windows()) | set(self.picker.windows())

    def poll(self) -> None:
        """Runs every POLL_MS in the Tk thread. An error is logged and the loop carries on - a stopped loop would
        leave the windows frozen for the rest of the session."""
        try:
            if self.tick() == "quit":
                return
        except Exception:
            logger.exception("Overlay error (it keeps going)")
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
                self.root.destroy()
                return "quit"
            changed = bool(self.handlers[kind](value)) or changed
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
