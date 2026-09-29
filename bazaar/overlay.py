"""
Windows shown above The Bazaar: a small alert box, and the Shop Guide (pictures of what a merchant can sell).

It's a separate window owned by the client; it never draws inside the game or touches its process.
It shows up over the game when The Bazaar runs borderless (the default "Fullscreen Window") or windowed,
not over exclusive fullscreen. Tk runs in its own thread; the client talks to it through thread-safe calls.
"""
import json
import queue
import threading
import time
from typing import Callable, Dict, List, Optional

BOARD_BG = "#16141c"
TILE = 76
COLUMNS = 7
BG = "#5a0f14"
FG = "#ffffff"
ACCENT = "#ffcf5a"


# Where the overlay may draw: the strips left and right of the board, measured on a 1920x1080 shop screenshot
# (2026-09-28) and kept as fractions of the screen (x, y, width, height). It must never cover the board: the
# overlay takes the clicks where it sits, and a list over the board once stopped the player leaving a shop.
LEFT_AREA = (14 / 1920, 0.0, 349 / 1920, 1056 / 1080)
RIGHT_AREA = (1565 / 1920, 0.0, 341 / 1920, 950 / 1080)
FONT_SIZES = range(13, 9, -1)  # pixel sizes tried for the locked-card list, never below 10 px to stay readable
PAD = 10
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


def area_pixels(area: tuple, screen_w: int, screen_h: int) -> tuple:
    x, y, w, h = area
    return round(x * screen_w), round(y * screen_h), round(w * screen_w), round(h * screen_h)


def draw_columns(tk, parent, columns: List[List[str]], font, bold, column_width: Callable[[List[str]], int],
                 line_height: int) -> None:
    """One canvas of positioned text: hundreds of separate label widgets took Tk seconds to lay out."""
    if not columns:
        return
    widths = [column_width(column) for column in columns]
    canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0, width=sum(widths),
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

    def toast(self, text: str, seconds: float = 6) -> None:
        """A short message at the bottom of the alert box that disappears by itself."""
        self.commands.put(("toast", (text, time.monotonic() + seconds)))

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
        # closed, to the rest of a long list.
        panels = [root, tk.Toplevel(root), tk.Toplevel(root)]
        for panel in panels:
            panel.withdraw()
            panel.overrideredirect(True)
            panel.attributes("-topmost", True)
            panel.attributes("-alpha", 0.93)
            panel.configure(bg=BG, highlightthickness=2, highlightbackground=ACCENT)
        shop_first, shop_second = panels[1], panels[2]
        left = area_pixels(LEFT_AREA, root.winfo_screenwidth(), root.winfo_screenheight())
        right = area_pixels(RIGHT_AREA, root.winfo_screenwidth(), root.winfo_screenheight())
        inner_w = left[2] - 2 * PAD - 4  # minus padding and the border
        state = {"locked": None, "deathlink": None, "shop": None, "pvp": {}, "toasts": []}
        # what each window shows now, to skip redraws that change nothing
        drawn = {"alerts": None, "shop": None, "alerts_height": 0}
        widths: Dict[tuple, int] = {}  # (font size, text) -> pixels; measuring hundreds of names is the slow part
        board = self._make_board(tk, root, right)

        def swap(panel):
            """A fresh content frame for the panel. The old one is destroyed only after the new one is packed, so
            the window never shows up empty in between (no flicker)."""
            old = [child for child in panel.winfo_children() if type(child) is tk.Frame]  # not other windows
            new = tk.Frame(panel, bg=BG, padx=PAD, pady=PAD)
            return new, lambda: (new.pack(fill="both", expand=True), [child.destroy() for child in old])

        def place(moves: list, panel, x: int, y: int, width: int, max_height: int) -> int:
            """Fixed width, height as needed but never past its space: a panel can't spill onto anything else.
            The move is only queued (see render) and its height returned."""
            panel.update_idletasks()
            height = min(panel.winfo_reqheight(), max_height)
            moves.append((panel, f"{width}x{height}+{x}+{y}"))
            return height

        def render() -> None:
            # Windows are laid out first and all moved together at the end, so one never sits on another while
            # the next is still being worked out.
            moves: list = []
            alerts = (state["deathlink"], state["locked"], tuple(state["pvp"].items()),
                      tuple(text for text, _ in state["toasts"]))
            if alerts != drawn["alerts"]:
                drawn["alerts"] = alerts
                drawn["alerts_height"] = render_alerts(moves)
            shop = (state["shop"], drawn["alerts_height"], board["hidden"])
            if shop != drawn["shop"]:
                drawn["shop"] = shop
                render_shop(moves, drawn["alerts_height"])
            for panel, geometry in sorted(moves, key=lambda move: move[0] is root):  # the alert box grows last
                if geometry is None:
                    panel.withdraw()
                elif panel.state() != "normal" or panel.geometry() != geometry:  # leave an unchanged window alone
                    panel.geometry(geometry)
                    panel.deiconify()
                    panel.lift()

        def render_alerts(moves: list) -> int:
            """Draws the alert box; returns its height (0 when hidden)."""
            if not (state["deathlink"] or state["locked"] or state["pvp"] or state["toasts"]):
                moves.append((root, None))
                return 0
            frame, show = swap(root)
            if state["deathlink"]:
                tk.Label(frame, text="DEATHLINK", fg=ACCENT, bg=BG, font=("Segoe UI", 16, "bold")).pack(anchor="w")
                tk.Label(frame, text=state["deathlink"], fg=FG, bg=BG, font=("Segoe UI", 11),
                         wraplength=inner_w, justify="left").pack(anchor="w")
                tk.Label(frame, text="Abandon your current run (Settings > Abandon Run).", fg=FG, bg=BG,
                         font=("Segoe UI", 11, "bold"), wraplength=inner_w, justify="left").pack(anchor="w",
                                                                                                pady=(2, 6))
                tk.Button(frame, text="Done", command=lambda: dismiss_deathlink()).pack(anchor="e")
            if state["locked"]:
                title, cards = state["locked"]
                tk.Label(frame, text=title, fg=ACCENT, bg=BG, font=("Segoe UI", 14, "bold"), wraplength=inner_w,
                         justify="left").pack(anchor="w", pady=(6 if state["deathlink"] else 0, 2 if cards else 0))
                for text in cards:  # cleared automatically when the log says it was sold
                    tk.Label(frame, text=text, fg=FG, bg=BG, font=("Segoe UI", 11), wraplength=inner_w,
                             justify="left").pack(anchor="w")
            if state["pvp"]:
                tk.Label(frame, text="Did you win the PvP fight?", fg=ACCENT, bg=BG,
                         font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(6 if frame.winfo_children() else 0, 2))
                for key, text in state["pvp"].items():
                    row = tk.Frame(frame, bg=BG)
                    row.pack(fill="x", pady=1)
                    tk.Label(row, text=text, fg=FG, bg=BG, font=("Segoe UI", 11), wraplength=inner_w - 110,
                             justify="left").pack(side="left")
                    tk.Button(row, text="Lost", command=lambda k=key: answer(k, False)).pack(side="right", padx=(6, 0))
                    tk.Button(row, text="Won", command=lambda k=key: answer(k, True)).pack(side="right", padx=(12, 0))
            for text, _ in state["toasts"]:
                tk.Label(frame, text=text, fg="#9be39b", bg=BG, font=("Segoe UI", 11, "bold"), wraplength=inner_w,
                         justify="left").pack(anchor="w", pady=(4, 0))
            show()
            return place(moves, root, left[0], left[1], left[2], left[3] // 2)  # bottom half: the shop list

        def render_shop(moves: list, alerts_height: int) -> None:
            if not state["shop"]:
                moves += [(shop_first, None), (shop_second, None)]
                return
            merchant, names, verb = state["shop"]
            # the left strip under the alerts first, then the right strip
            first_top = left[1] + alerts_height + 4 if alerts_height else left[1]
            first = (left[0], first_top, left[2], left[3] - first_top)
            first_frame, show_first = swap(shop_first)
            if names:
                advice = "don't buy them" if verb == "sell" else "pick something else"
                text, color = f"{merchant} may {verb} these LOCKED cards - {advice}:", ACCENT
            else:
                text, color = f"{merchant}: nothing here is locked for you. Shop freely!", "#9be39b"
            tk.Label(first_frame, text=text, fg=color, bg=BG, font=("Segoe UI", 11, "bold"), wraplength=inner_w,
                     justify="left").pack(anchor="w", pady=(0, 4))
            if verb == "sell" and board["hidden"] is not None and board["hidden"]:
                tk.Button(first_frame, text="Show pictures", command=lambda: (board["show"](), render())).pack(
                    anchor="w", pady=(0, 4))
            first_frame.update_idletasks()
            header_height = first_frame.winfo_reqheight() + 4
            guide_open = board["hidden"] is False  # the right strip is the Shop Guide's while it's open
            areas = [(inner_w, first[3] - header_height)]
            if not guide_open:
                areas.append((right[2] - 2 * PAD - 4, right[3] - 2 * PAD - 4))
            placed, missing, font, bold = [[] for _ in areas], 0, None, None
            for size in FONT_SIZES:  # the biggest text that fits; else the smallest, saying what's left out
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
            draw_columns(tk, first_frame, placed[0], font, bold, width, line_height)
            if missing and guide_open:
                tk.Label(first_frame, text=f"+{missing} more locked cards - see the Shop Guide", fg=ACCENT, bg=BG,
                         font=bold, wraplength=inner_w, justify="left").pack(anchor="w")
            show_first()
            place(moves, shop_first, *first)
            if len(placed) > 1 and (placed[1] or missing):
                second_frame, show_second = swap(shop_second)
                draw_columns(tk, second_frame, placed[1], font, bold, width, line_height)
                if missing:
                    tk.Label(second_frame, text=f"+{missing} more locked cards (no room to show them)", fg=ACCENT,
                             bg=BG, font=bold, wraplength=right[2] - 2 * PAD - 4, justify="left").pack(anchor="w")
                show_second()
                place(moves, shop_second, *right)
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
                if kind == "toast":
                    state["toasts"] = (state["toasts"] + [value])[-4:]  # at most 4 at a time
                    changed = True
                    continue
                state[kind] = value
                changed = True
            now = time.monotonic()
            if any(expires <= now for _, expires in state["toasts"]):
                state["toasts"] = [t for t in state["toasts"] if t[1] > now]
                changed = True
            if changed:
                render()
            else:
                for panel in panels:  # games sometimes steal topmost; keep reasserting
                    if panel.state() == "normal":
                        panel.attributes("-topmost", True)
            root.after(250, poll)

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
        off = dict(render=lambda value, keep_scroll=False: None, refresh=lambda guid: None, show=lambda: None)
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
        win = tk.Toplevel(root)
        win.title("Shop Guide - The Bazaar")
        win.overrideredirect(True)  # no title bar or border, which would reach past the strip
        win.configure(bg=BOARD_BG)
        win.attributes("-topmost", True)
        win.geometry("{2}x{3}+{0}+{1}".format(*area))
        if info["hidden"]:
            win.withdraw()

        def close() -> None:
            win.withdraw()
            info["hidden"] = True
            self._save_guide({"hidden": True})
            self.commands.put(("redraw", None))  # the shop list may use the right strip now

        def show() -> None:
            info["hidden"] = False
            win.geometry("{2}x{3}+{0}+{1}".format(*area))
            win.deiconify()
            win.lift()
            self._save_guide({"hidden": False})

        top = tk.Frame(win, bg=BOARD_BG)
        top.pack(fill="x")
        tk.Button(top, text="X", command=close, bg=BOARD_BG, fg=ACCENT, relief="flat", padx=6).pack(side="right")
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
            elif locked_first:
                note = f"{len(locked)} locked (top)"
            else:
                note = f"{len(allowed)} you can buy (top)"
            header.configure(text=f"{title}  |  {note}")
            sections = [(f"You can buy ({len(allowed)})", "#9be39b", allowed, False),
                        (f"LOCKED - don't buy ({len(locked)})", "#ff6b6b", locked, True)]
            if locked_first:
                sections.reverse()
            row = 0
            for label, color, cards, is_locked in sections:
                row = section(label, color, sorted(cards, key=lambda c: c.name), is_locked, row)
            if not keep_scroll:
                canvas.yview_moveto(0)

        info.update(render=render, refresh=refresh, show=show)
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
