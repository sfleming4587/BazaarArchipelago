"""
Windows shown above The Bazaar: a small alert box, and the Shop Guide (pictures of what a merchant can sell).

It's a separate window owned by the client; it never draws inside the game or touches its process.
It shows up over the game when The Bazaar runs borderless (the default "Fullscreen Window") or windowed,
not over exclusive fullscreen. Tk runs in its own thread; the client talks to it through thread-safe calls.
"""
import json
import os
import queue
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Set

BOARD_BG = "#16141c"
TILE = 76
COLUMNS = 7
FG = "#ffffff"
ACCENT = "#ffcf5a"
GOOD = "#9be39b"
WARN = "#ff8a8a"
MUTED = "#e6d5b8"
# background by how urgent a window is (user 2026-09-28: "not just red, correspondant to the severity")
SEVERITY = {"critical": "#5a0f14",  # checks blocked, DeathLink
            "warning": "#5c3f0c",  # locked cards on sale, a PvP question, a Sell Trap, a locked hero picked
            "info": "#1f2430",  # progress only
            "ok": "#173d24"}  # nothing locked here, an unlock arrived
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
PAD = 10
GAME_EXE = "thebazaar.exe"  # the overlay only shows while this is the active window
INDENT = 8  # names sit a little right of their letter
GAP = 12  # between columns


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


def _add_style(window, flags: int) -> None:
    if sys.platform != "win32":
        return
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = window_handle(window)
    user32.SetWindowLongW(hwnd, -20, user32.GetWindowLongW(hwnd, -20) | flags)  # GWL_EXSTYLE


def click_through(panel) -> None:
    """Mouse clicks pass through the window to the game underneath (Windows only; elsewhere a no-op)."""
    _add_style(panel, 0x80000 | 0x20)  # WS_EX_LAYERED | WS_EX_TRANSPARENT


def never_focus(window) -> None:
    """The window never takes the keyboard focus from the game, even when shown or clicked (its buttons still
    work). Windows only; elsewhere a no-op."""
    window.update_idletasks()
    _add_style(window, 0x08000000)  # WS_EX_NOACTIVATE


def window_handle(window) -> int:
    return int(window.wm_frame(), 16)


_exe_names: Dict[int, str] = {}


def game_in_front(own: Set[int]) -> tuple:
    """
    (in front, window) - in front: True while The Bazaar is the active window (Windows only; elsewhere always
    True), None when one of our own windows is (that says nothing about the game, so the caller keeps what it
    had). window: the game's client area (x, y, width, height) on screen while it's in front, else None.
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
    if pid.value not in _exe_names:
        name = ""
        process = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if process:
            buffer, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                name = os.path.basename(buffer.value).lower()
            kernel32.CloseHandle(process)
        _exe_names[pid.value] = name
    if _exe_names[pid.value] != GAME_EXE:
        return False, None
    rect, corner = wintypes.RECT(), wintypes.POINT(0, 0)
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    user32.ClientToScreen(hwnd, ctypes.byref(corner))
    if rect.right < 100 or rect.bottom < 100:  # minimised or not laid out yet
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
    def __init__(self, art_cache_dir: Optional[str] = None, on_pvp: Optional[Callable[[str, bool], None]] = None,
                 guide_file: Optional[str] = None) -> None:
        self.only_over_game = True  # False shows the windows whatever is in front (tests)
        self.game_window: Optional[tuple] = None  # tests: pretend the game's client area is here (x, y, w, h)
        self.guide_file = guide_file  # where the Shop Guide remembers its position, size and whether it's closed
        self.on_pvp = on_pvp  # called from the Tk thread with (question key, won)
        self.art_cache_dir = art_cache_dir
        self.commands: "queue.Queue" = queue.Queue()
        self.available = True  # False if tkinter is missing: no alert window at all
        self.shop_guide_unavailable = False  # True if Pillow is missing: no card pictures
        self.thread = threading.Thread(target=self._run, name="bazaar overlay", daemon=True)
        self.thread.start()

    # --- called from the client ---------------------------------------------------------------------------------

    def show_locked(self, title: Optional[str], cards: List[str]) -> None:
        """The "CHECKS ARE BLOCKED ..." banner and the locked cards causing it. title=None hides it."""
        self.commands.put(("locked", (title, list(cards)) if title else None))

    def show_shop(self, merchant: Optional[str], locked: List[str], verb: str = "sell") -> None:
        """Show which locked cards a merchant could sell (or an event could offer). merchant=None hides it."""
        self.commands.put(("shop", (merchant, list(locked), verb) if merchant else None))

    def show_board(self, title: Optional[str], allowed: list, locked: list) -> None:
        """Shop Guide: allowed cards in colour first, locked cards greyed out below. title=None hides it."""
        self.commands.put(("board", (title, list(allowed), list(locked)) if title else None))

    def ask_pvp(self, questions: Dict[str, str]) -> None:
        """questions: key -> text such as "Vanessa day 3". Each gets Won / Lost buttons. Empty dict hides them."""
        self.commands.put(("pvp", dict(questions)))

    def toast(self, text: str, seconds: float = 6, warning: bool = False) -> None:
        """A short message at the bottom of the alert box that disappears by itself."""
        self.commands.put(("toast", (text, time.monotonic() + seconds, warning)))

    def show_status(self, text: Optional[str], warning: bool = False) -> None:
        """One line at the bottom of the alert box: run progress, or which heroes you may pick. None hides it."""
        self.commands.put(("status", (text, warning) if text else None))

    def show_deathlink(self, text: Optional[str]) -> None:
        self.commands.put(("deathlink", text))

    def close(self) -> None:
        self.commands.put(("quit", None))

    # --- Tk thread ----------------------------------------------------------------------------------------------

    def _run(self) -> None:
        try:
            import tkinter as tk
        except ImportError:
            self.available = False
            return
        import tkinter.font as tkfont
        root = tk.Tk()
        root.withdraw()
        # No two overlay windows overlap: the alert box (root) takes the top of the left strip, the locked-card
        # list goes right under it, and the right strip belongs to the Shop Guide - or, while the guide is
        # closed, to the rest of a long list. Pop-ups (toasts) stack up from the bottom of the right strip,
        # which then shrinks for the others.
        alert_box, shop_first, shop_second, toast_box = root, tk.Toplevel(root), tk.Toplevel(root), tk.Toplevel(root)
        panels = [alert_box, shop_first, shop_second, toast_box]
        for panel in panels:
            panel.withdraw()
            panel.overrideredirect(True)
            panel.attributes("-topmost", True)
            panel.attributes("-alpha", 1.0 if panel in (shop_first, shop_second) else ALERT_ALPHA)
            panel.configure(bg=SEVERITY["info"], highlightthickness=2, highlightbackground=ACCENT)
            never_focus(panel)
        # the list's see-through background: a plain window right under each list window, same size
        backdrops = {}
        for panel in (shop_first, shop_second):
            backdrop = backdrops[panel] = tk.Toplevel(root)
            backdrop.withdraw()
            backdrop.overrideredirect(True)
            backdrop.attributes("-topmost", True)
            backdrop.attributes("-alpha", LIST_ALPHA)
            never_focus(backdrop)

        g: dict = {}  # the strips for where the game window is now (see relayout)

        def relayout(window: tuple) -> None:
            left, right, k = strips(*window)
            g.update(window=window, left=left, right=right, k=k, inner_w=left[2] - 2 * PAD - 4)

        def f(size: float, weight: str = "normal") -> tuple:
            """A font of `size` points at 1080p, scaled with the game window."""
            return ("Segoe UI", -max(MIN_FONT, round(size * 4 / 3 * g["k"])), weight)

        relayout((0, 0, root.winfo_screenwidth(), root.winfo_screenheight()))  # until the game is seen
        state = {"locked": None, "deathlink": None, "shop": None, "pvp": {}, "toasts": [], "status": None,
                 "list_hidden": False}  # the player hid the locked-card list (until they show it again)
        # what each window shows now, to skip redraws that change nothing
        drawn: dict = {"alerts": None, "shop": None, "toasts": None, "alerts_height": 0, "toasts_height": 0}
        wanted: set = set()  # windows that have something to show (shown only while the game is in front)
        front = {"game": not self.only_over_game}
        widths: Dict[tuple, int] = {}  # (font size, text) -> pixels; measuring hundreds of names is the slow part
        board = self._make_board(tk, root, g["right"])

        def swap(panel, bg: str):
            """A fresh content frame for the panel. The old one is destroyed only after the new one is packed, so
            the window never shows up empty in between (no flicker)."""
            old = [child for child in panel.winfo_children() if type(child) is tk.Frame]  # not other windows
            new = tk.Frame(panel, bg=bg, padx=PAD, pady=PAD)
            panel.configure(bg=bg)
            if panel in backdrops:  # the colour goes on the backdrop; in the list window it turns see-through
                backdrops[panel].configure(bg=bg)
                panel.attributes("-transparentcolor", bg)
            return new, lambda: (new.pack(fill="both", expand=True), [child.destroy() for child in old])

        def place(moves: list, panel, x: int, y: int, width: int, max_height: int) -> int:
            """Fixed width, height as needed but never past its space: a panel can't spill onto anything else.
            The move is only queued (see render) and its height returned."""
            panel.update_idletasks()
            height = min(panel.winfo_reqheight(), max_height)
            moves.append((panel, f"{width}x{height}+{x}+{y}"))
            return height

        def sync_visibility() -> None:
            """Show what has something to show, but only while The Bazaar (or one of these windows) is in front."""
            guide = board.get("win")
            for window in panels + ([guide] if guide else []):
                show = front["game"] and (board["hidden"] is False if window is guide else window in wanted)
                layers = [backdrops[window], window] if window in backdrops else [window]  # bottom to top
                if show and window.state() != "normal":
                    for layer in layers:
                        layer.deiconify()
                        layer.lift()
                        if window in (shop_first, shop_second, toast_box):
                            click_through(layer)  # nothing to click in these: never catch the game's clicks
                elif not show and window.state() == "normal":
                    for layer in layers:
                        layer.withdraw()

        def render() -> None:
            # Windows are laid out first and all moved together at the end, so one never sits on another while
            # the next is still being worked out.
            moves: list = []
            toasts = tuple((text, warning) for text, _, warning in state["toasts"])
            if toasts != drawn["toasts"]:
                drawn["toasts"] = toasts
                drawn["toasts_height"] = render_toasts(moves)
            right_height = g["right"][3] - (drawn["toasts_height"] + 4 if drawn["toasts_height"] else 0)
            board["fit"](*g["right"][:3], right_height)
            alerts = (state["deathlink"], state["locked"], tuple(state["pvp"].items()), state["status"],
                      tuple(label for label, _ in shop_buttons()))
            if alerts != drawn["alerts"]:
                drawn["alerts"] = alerts
                drawn["alerts_height"] = render_alerts(moves)
            shop = (state["shop"], drawn["alerts_height"], board["hidden"], right_height, state["list_hidden"])
            if shop != drawn["shop"]:
                drawn["shop"] = shop
                render_shop(moves, drawn["alerts_height"], right_height)
            for panel, geometry in sorted(moves, key=lambda move: move[0] is alert_box):  # alert box grows last
                if geometry is None:
                    wanted.discard(panel)
                else:
                    wanted.add(panel)
                    if panel.geometry() != geometry:  # leave an unchanged window alone
                        panel.geometry(geometry)
                        if panel in backdrops:
                            backdrops[panel].geometry(geometry)
            sync_visibility()

        def shop_buttons() -> list:
            """(label, action) for the buttons shown while at a shop. They live in the alert box, since the list
            lets clicks through: open the Shop Guide when it's closed, and hide or show the locked-card list."""
            buttons = []
            if state["shop"] and state["shop"][2] == "sell" and board["hidden"]:
                buttons.append(("Pictures", board["show"]))  # opens the Shop Guide
            if state["shop"] and state["shop"][1]:
                buttons.append(("Show list" if state["list_hidden"] else "Hide list", toggle_list))
            return buttons

        def toggle_list() -> None:
            state["list_hidden"] = not state["list_hidden"]

        def alert_severity() -> str:
            if state["deathlink"] or (state["locked"] and state["locked"][0].startswith("CHECKS ARE BLOCKED")):
                return "critical"
            if state["locked"] or state["pvp"] or (state["status"] and state["status"][1]):
                return "warning"  # a Sell Trap to deal with, a question to answer, a locked hero picked
            return "info"

        def render_toasts(moves: list) -> int:
            """Pop-ups at the bottom of the right strip, newest at the bottom; returns their height."""
            if not state["toasts"]:
                moves.append((toast_box, None))
                return 0
            frame, show = swap(toast_box, SEVERITY["info"])
            for text, _, warning in state["toasts"]:
                bg = SEVERITY["critical" if warning else "ok"]
                tk.Label(frame, text=text, fg=FG, bg=bg, font=f(11, "bold"), wraplength=g["right"][2] - 40,
                         justify="left", padx=8, pady=4).pack(fill="x", pady=2)
            show()
            toast_box.update_idletasks()
            height = min(toast_box.winfo_reqheight(), g["right"][3] // 3)
            x, y, width, strip_height = g["right"]
            moves.append((toast_box, f"{width}x{height}+{x}+{y + strip_height - height}"))
            return height

        def render_alerts(moves: list) -> int:
            """Draws the alert box; returns its height (0 when hidden)."""
            if not (state["deathlink"] or state["locked"] or state["pvp"] or state["status"] or shop_buttons()):
                moves.append((alert_box, None))
                return 0
            bg = SEVERITY[alert_severity()]
            frame, show = swap(alert_box, bg)
            if state["deathlink"]:
                tk.Label(frame, text="DEATHLINK", fg=ACCENT, bg=bg, font=f(16, "bold")).pack(anchor="w")
                tk.Label(frame, text=state["deathlink"], fg=FG, bg=bg, font=f(11),
                         wraplength=g["inner_w"], justify="left").pack(anchor="w")
                tk.Label(frame, text="Abandon your current run (Settings > Abandon Run).", fg=FG, bg=bg,
                         font=f(11, "bold"), wraplength=g["inner_w"], justify="left").pack(anchor="w",
                                                                                                pady=(2, 6))
                tk.Button(frame, text="Done", command=lambda: dismiss_deathlink()).pack(anchor="e")
            if state["locked"]:
                title, cards = state["locked"]
                tk.Label(frame, text=title, fg=ACCENT, bg=bg, font=f(14, "bold"), wraplength=g["inner_w"],
                         justify="left").pack(anchor="w", pady=(6 if state["deathlink"] else 0, 2 if cards else 0))
                for text in cards:  # cleared automatically when the log says it was sold
                    tk.Label(frame, text=text, fg=FG, bg=bg, font=f(11), wraplength=g["inner_w"],
                             justify="left").pack(anchor="w")
            if state["pvp"]:
                tk.Label(frame, text="Did you win the PvP fight?", fg=ACCENT, bg=bg,
                         font=f(13, "bold")).pack(anchor="w", pady=(6 if frame.winfo_children() else 0, 2))
                for key, text in state["pvp"].items():
                    row = tk.Frame(frame, bg=bg)
                    row.pack(fill="x", pady=1)
                    tk.Label(row, text=text, fg=FG, bg=bg, font=f(11), wraplength=g["inner_w"] - 110,
                             justify="left").pack(side="left")
                    tk.Button(row, text="Lost", command=lambda k=key: answer(k, False)).pack(side="right", padx=(6, 0))
                    tk.Button(row, text="Won", command=lambda k=key: answer(k, True)).pack(side="right", padx=(12, 0))
            # last line: the status text with the shop buttons on its right; the buttons get a row of their own
            # only when that would squeeze the text below half the width
            row = tk.Frame(frame, bg=bg)
            if state["status"] or shop_buttons():
                row.pack(fill="x", pady=(4, 0) if frame.winfo_children()[:-1] else 0)
            buttons = tk.Frame(row, bg=bg)
            for label, action in shop_buttons():
                tk.Button(buttons, text=label, font=f(8), padx=3, pady=0,
                          command=lambda a=action: (a(), render())).pack(side="left", padx=(4, 0))
            buttons.update_idletasks()
            room = g["inner_w"] - (buttons.winfo_reqwidth() + 8 if shop_buttons() else 0)
            own_row = bool(state["status"]) and room < g["inner_w"] // 2
            if shop_buttons():
                buttons.pack(side="bottom" if own_row else "right", anchor="e", pady=(4, 0) if own_row else 0)
            if state["status"]:
                text, warning = state["status"]
                tk.Label(row, text=text, fg=WARN if warning else MUTED, bg=bg,
                         font=f(11 if warning else 10, "bold" if warning else "normal"),
                         wraplength=g["inner_w"] if own_row else room, justify="left").pack(side="left", anchor="w")
            show()
            x, y, width, strip_height = g["left"]
            return place(moves, alert_box, x, y, width, strip_height // 2)  # bottom half: the shop list

        def render_shop(moves: list, alerts_height: int, right_height: int) -> None:
            if not state["shop"] or (state["list_hidden"] and state["shop"][1]):
                moves += [(shop_first, None), (shop_second, None)]
                return
            merchant, names, verb = state["shop"]
            bg = SEVERITY["warning" if names else "ok"]
            # the left strip under the alerts first, then the right strip
            first_top = g["left"][1] + alerts_height + 4 if alerts_height else g["left"][1]
            first = (g["left"][0], first_top, g["left"][2], g["left"][3] - first_top)
            first_frame, show_first = swap(shop_first, bg)
            if names:
                advice = "don't buy them" if verb == "sell" else "pick something else"
                tk.Label(first_frame, text=f"{merchant} may {verb} these LOCKED cards - {advice}:", fg=ACCENT, bg=bg,
                         font=f(11, "bold"), wraplength=g["inner_w"], justify="left").pack(anchor="w",
                                                                                                pady=(0, 4))
            else:  # nothing locked: just a small tick
                tk.Label(first_frame, text=f"✔  {merchant}: buy freely", fg=GOOD, bg=bg,
                         font=f(11, "bold"), wraplength=g["inner_w"], justify="left").pack(anchor="w")
            first_frame.update_idletasks()
            header_height = first_frame.winfo_reqheight() + 4
            guide_open = board["hidden"] is False  # the right strip is the Shop Guide's while it's open
            areas = [(g["inner_w"], first[3] - header_height)]
            if not guide_open:
                areas.append((g["right"][2] - 2 * PAD - 4, right_height - 2 * PAD - 4))
            placed, missing, font, bold = [[] for _ in areas], 0, None, None
            sizes = sorted({max(MIN_FONT, round(size * g["k"])) for size in FONT_SIZES}, reverse=True)
            for size in sizes:  # the biggest text that fits; else the smallest, saying what's left out
                font = tkfont.Font(root=root, family="Segoe UI", size=-size)
                bold = tkfont.Font(root=root, family="Segoe UI", size=-size, weight="bold")

                def measure(line: str, size=size, font=font, bold=bold) -> int:
                    if (size, line) not in widths:
                        widths[size, line] = bold.measure(line) if len(line) == 1 else font.measure(line) + INDENT
                    return widths[size, line]

                def width(column: List[str]) -> int:
                    return max(measure(line) for line in column) + GAP
                placed, missing = fit_columns(names, areas, width, font.metrics("linespace"))
                if not missing:
                    break
            state["fonts"] = (font, bold)  # Tk drops a font once Python lets go of it
            line_height = font.metrics("linespace")
            draw_columns(tk, first_frame, placed[0], font, bold, width, line_height, bg)
            if missing and guide_open:
                tk.Label(first_frame, text=f"+{missing} more locked cards - see the Shop Guide", fg=ACCENT, bg=bg,
                         font=bold, wraplength=g["inner_w"], justify="left").pack(anchor="w")
            show_first()
            place(moves, shop_first, *first)
            if len(placed) > 1 and (placed[1] or missing):
                second_frame, show_second = swap(shop_second, bg)
                draw_columns(tk, second_frame, placed[1], font, bold, width, line_height, bg)
                if missing:
                    tk.Label(second_frame, text=f"+{missing} more locked cards (no room to show them)", fg=ACCENT,
                             bg=bg, font=bold, wraplength=g["right"][2] - 2 * PAD - 4, justify="left").pack(anchor="w")
                show_second()
                place(moves, shop_second, g["right"][0], g["right"][1], g["right"][2], right_height)
            else:
                moves.append((shop_second, None))

        def answer(key: str, won: bool) -> None:
            state["pvp"].pop(key, None)
            render()
            if self.on_pvp:
                self.on_pvp(key, won)

        def dismiss_deathlink() -> None:
            state["deathlink"] = None
            render()

        def own_windows() -> Set[int]:
            guide = board.get("win")
            return {window_handle(w) for w in panels + list(backdrops.values()) + ([guide] if guide else [])}

        def poll() -> None:
            changed = False
            while True:
                try:
                    kind, value = self.commands.get_nowait()
                except queue.Empty:
                    break
                if kind == "quit":
                    if board["art"]:
                        board["art"].shutdown()
                    root.destroy()
                    return
                if kind == "art":
                    board["refresh"](value)
                    continue
                if kind == "board":
                    board["render"](value)
                    continue
                if kind == "redraw":
                    changed = True
                    continue
                if kind == "toast":  # (text, expires, warning)
                    state["toasts"] = (state["toasts"] + [value])[-4:]  # at most 4 at a time
                    changed = True
                    continue
                state[kind] = value
                changed = True
            now = time.monotonic()
            if any(expires <= now for _, expires, _ in state["toasts"]):
                state["toasts"] = [t for t in state["toasts"] if t[1] > now]
                changed = True
            if self.only_over_game:
                game, window = game_in_front(own_windows())
            else:
                game, window = True, self.game_window
            if window and window != g["window"]:  # the game window moved, was resized or changed resolution
                relayout(window)
                drawn.update(alerts=None, shop=None, toasts=None)  # everything is laid out again
                changed = True
            if game is not None and game != front["game"]:
                front["game"] = game
                sync_visibility()
            if changed:
                render()
            else:
                for panel in panels:  # games sometimes steal topmost; keep reasserting
                    if panel.state() == "normal":
                        for layer in ([backdrops[panel]] if panel in backdrops else []) + [panel]:  # text on top
                            layer.attributes("-topmost", True)
            root.after(250, poll)

        sync_visibility()  # an open Shop Guide shows from the start (while the game is in front)
        root.after(250, poll)
        root.mainloop()

    def _make_board(self, tk, root, area: tuple) -> dict:
        """
        The Shop Guide window. It opens in the right strip beside the board (`area`: x, y, width, height), where
        no other overlay goes while it's open; its columns follow its width. Closing it keeps it closed, also
        next session, until "Show pictures" is pressed.
        """
        from .cardart import CardArt
        from .data import CARDS
        info: dict = {"art": None, "shown": None, "shown_guids": set(), "photos": {}, "columns": COLUMNS,
                      "hidden": None, "stale": False}
        off = dict(render=lambda value, keep_scroll=False: None, refresh=lambda guid: None, show=lambda: None,
                   fit=lambda x, y, width, height: None, win=None)
        if not self.art_cache_dir:  # Shop Guide turned off
            info.update(off)
            return info
        try:
            from PIL import ImageDraw, ImageEnhance, ImageOps, ImageTk
        except ImportError:
            # Archipelago's Windows installer leaves out Pillow, which the card pictures need (they're AVIF).
            # Without pictures the guide would only repeat the shop warning, so it stays off.
            self.shop_guide_unavailable = True
            info.update(off)
            return info
        info["art"] = CardArt(self.art_cache_dir, TILE, on_ready=lambda guid: self.commands.put(("art", guid)))
        info["art"].preload(c for c in CARDS if c.shop)

        saved = self._load_guide()
        info["hidden"] = bool(saved.get("hidden"))
        info["locked_only"] = bool(saved.get("locked_only"))  # show only the cards you may not buy

        def persist() -> None:
            self._save_guide({"hidden": info["hidden"], "locked_only": info["locked_only"]})
        win = tk.Toplevel(root)
        win.title("Shop Guide - The Bazaar")
        win.overrideredirect(True)  # no title bar or border, which would reach past the strip
        win.configure(bg=BOARD_BG)
        win.attributes("-topmost", True)
        win.geometry("{2}x{3}+{0}+{1}".format(*area))
        win.withdraw()  # shown by the overlay's render, only while the game is in front
        never_focus(win)

        def fit(x: int, y: int, width: int, height: int) -> None:
            """The right strip minus any pop-ups below it."""
            geometry = f"{width}x{height}+{x}+{y}"
            if win.geometry() != geometry:
                win.geometry(geometry)
                header.configure(wraplength=width - 60)

        def close() -> None:
            info["hidden"] = True
            persist()
            self.commands.put(("redraw", None))  # hides it, and the shop list may use the right strip now

        def show() -> None:
            info["hidden"] = False
            persist()

        top = tk.Frame(win, bg=BOARD_BG)
        top.pack(fill="x")
        tk.Button(top, text="X", command=close, bg=BOARD_BG, fg=ACCENT, relief="flat", padx=6).pack(side="right")

        def toggle_locked_only() -> None:
            info["locked_only"] = not info["locked_only"]
            persist()
            only.configure(text="Show all" if info["locked_only"] else "Locked only")
            if info["shown"]:
                render(info["shown"])
        only = tk.Button(top, text="Show all" if info["locked_only"] else "Locked only", command=toggle_locked_only,
                         bg=BOARD_BG, fg=ACCENT, relief="flat", padx=6)
        only.pack(side="right")
        header = tk.Label(top, bg=BOARD_BG, fg=ACCENT, font=("Segoe UI", 12, "bold"), anchor="w", padx=10, pady=6,
                          justify="left", wraplength=area[2] - 60,
                          text="Shop Guide: open a merchant to see what it can sell")
        header.pack(side="left", fill="x")
        canvas = tk.Canvas(win, bg=BOARD_BG, highlightthickness=0)
        scroll = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BOARD_BG)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        def on_resize(event) -> None:
            columns = max(1, (event.width - 10) // (TILE + 14))
            if columns != info["columns"]:
                info["columns"] = columns
                if info["shown"]:
                    render(info["shown"], keep_scroll=True)

        canvas.bind("<Configure>", on_resize)

        def picture(card, locked: bool):
            key = (card.guid, locked)
            if key in info["photos"]:
                return info["photos"][key]
            art = info["art"]
            if art is None or ImageTk is None:
                return None
            img = art.image(card)
            if locked:
                img = ImageEnhance.Brightness(ImageOps.grayscale(img).convert("RGB")).enhance(0.45)
                draw = ImageDraw.Draw(img)
                draw.line([6, 6, TILE - 7, TILE - 7], fill="#e0303a", width=5)
                draw.line([6, TILE - 7, TILE - 7, 6], fill="#e0303a", width=5)
            info["photos"][key] = ImageTk.PhotoImage(img)  # cached: Tk needs the reference kept alive anyway
            return info["photos"][key]

        def refresh(guid: str) -> None:
            """Real art arrived for a card: redraw only if that card is on screen right now."""
            info["photos"].pop((guid, False), None)
            info["photos"].pop((guid, True), None)
            if guid in info["shown_guids"]:
                info["stale"] = True
                win.after(300, redraw_if_stale)  # batch several arrivals into one redraw

        def redraw_if_stale() -> None:
            if info["stale"] and info["shown"]:
                info["stale"] = False
                render(info["shown"], keep_scroll=True)

        def section(title: str, color: str, cards: list, locked: bool, row: int) -> int:
            if not cards:
                return row
            columns = info["columns"]
            tk.Label(inner, text=title, bg=BOARD_BG, fg=color, font=("Segoe UI", 11, "bold")).grid(
                row=row, column=0, columnspan=columns, sticky="w", padx=6, pady=(8, 2))
            row += 1
            for i, card in enumerate(cards):
                cell = tk.Frame(inner, bg=BOARD_BG)
                cell.grid(row=row + i // columns, column=i % columns, padx=4, pady=3, sticky="n")
                photo = picture(card, locked)
                if photo:
                    tk.Label(cell, image=photo, bg=BOARD_BG).pack()
                tk.Label(cell, text=card.name, bg=BOARD_BG, fg="#777777" if locked else "#eeeeee",
                         font=("Segoe UI", 8), wraplength=TILE + 6, justify="center").pack()
            return row + (len(cards) + columns - 1) // columns

        def render(value, keep_scroll: bool = False) -> None:
            if not value:  # left the shop: keep showing it, just say it's the last one
                if info["shown"]:
                    header.configure(text=f"Last shop: {info['shown'][0]}")
                return
            info["shown"] = value
            for child in inner.winfo_children():
                child.destroy()
            title, allowed, locked = value
            info["shown_guids"] = {c.guid for c in allowed} | {c.guid for c in locked}
            locked_first = len(locked) < len(allowed)  # put the shorter list on top so it's seen without scrolling
            if not locked:
                note = "nothing locked here"
            elif info["locked_only"]:
                note = f"{len(locked)} locked"
            elif locked_first:
                note = f"{len(locked)} locked (top)"
            else:
                note = f"{len(allowed)} you can buy (top)"
            header.configure(text=f"{title}  |  {note}")
            sections = [(f"You can buy ({len(allowed)})", "#9be39b", allowed, False),
                        (f"LOCKED - don't buy ({len(locked)})", "#ff6b6b", locked, True)]
            if info["locked_only"]:  # just the cards to recognise and avoid
                sections = sections[1:]
            elif locked_first:
                sections.reverse()
            row = 0
            for label, color, cards, is_locked in sections:
                row = section(label, color, sorted(cards, key=lambda c: c.name), is_locked, row)
            if not keep_scroll:
                canvas.yview_moveto(0)

        info.update(render=render, refresh=refresh, show=show, fit=fit, win=win)
        return info

    def _load_guide(self) -> dict:
        try:
            with open(self.guide_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, TypeError, ValueError):
            return {}

    def _save_guide(self, data: dict) -> None:
        try:
            with open(self.guide_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except (OSError, TypeError):
            pass
