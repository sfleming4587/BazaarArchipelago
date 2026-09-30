"""
The Lock Bypass card picker (user, 2026-09-30): every card in the game with a search bar and filters (hero or
Common, size, starting rarity). Picking a locked card spends a Lock Bypass on it for the rest of the run.

It runs in the overlay's Tk thread and only shows what the client hands it (how many bypasses are ready, which
cards are locked this run); the choice goes back through on_pick, and the client decides whether it counts.
"""
from typing import Callable, Iterable, List, Optional, Set

from . import screens
from .data import CARDS, HEROES, TIERS
from .theme import ACCENT, DIM, FG, FONT, WARN, WINDOW_BG

ANY = "Any"
SIZES = ("Small", "Medium", "Large")
# (column, heading, width) of the list; adding a column is one entry here and one value in row()
COLUMNS = (("hero", "Hero", 110), ("size", "Size", 70), ("tier", "Rarity", 80), ("status", "", 80))
ROWS = 20


def filter_cards(cards: Iterable, text: str, hero: str, size: str, tier: str, locked_only: bool,
                 locked: Set[str]) -> List:
    """The cards the picker lists, by name. hero: a hero, "Common" or ANY; size and tier likewise; text matches
    anywhere in the name, ignoring case."""
    text = text.strip().lower()
    return sorted((c for c in cards
                   if text in c.name.lower()
                   and hero in (ANY, c.hero) and size in (ANY, c.size) and tier in (ANY, c.tier)
                   and (not locked_only or c.guid in locked)),
                  key=lambda c: c.name.lower())


def row(card, locked: Set[str]) -> tuple:
    return card.hero, card.size, card.tier, "LOCKED" if card.guid in locked else "allowed"


class CardPicker:
    """The window. Built on first open, then hidden and shown again."""

    def __init__(self, tk, root, screen: Callable[[], tuple], on_pick: Callable[[str], None]) -> None:
        self.tk, self.root, self.screen, self.on_pick = tk, root, screen, on_pick
        self.win = None
        self.ready = 0  # Lock Bypasses ready
        self.locked: Set[str] = set()  # cards locked in this run
        self.vars: dict = {}
        self.tree = self.button = self.note = None

    def update(self, ready: int, locked: Set[str]) -> None:
        """New bypass count and locked cards; the picker closes when none is ready (e.g. the run ended)."""
        self.ready, self.locked = ready, set(locked)
        if not self.is_open():
            return
        if not ready:
            self.close()
        else:
            self.refresh()

    def is_open(self) -> bool:
        return bool(self.win) and self.win.state() == "normal"

    def toggle(self) -> None:
        if self.is_open():
            self.close()
        else:
            self.open()

    def windows(self) -> List[int]:
        """Its window handle, so using it doesn't count as leaving the game."""
        return [screens.window_handle(self.win)] if self.win is not None and self.win.winfo_exists() else []

    def open(self) -> None:
        if not self.win:
            self.build()
            self.win.update_idletasks()
            area, width, height = self.screen(), self.win.winfo_reqwidth(), self.win.winfo_reqheight()
            x, y = area[0] + (area[2] - width) // 2, area[1] + (area[3] - height) // 4
            self.win.geometry(screens.geometry(screens.clamp((x, y, width, height), area)))
        self.refresh()
        self.win.deiconify()
        self.win.lift()
        self.vars["entry"].focus_set()

    def close(self) -> None:
        if self.win:
            self.win.withdraw()

    def build(self) -> None:
        tk = self.tk
        from tkinter import ttk
        win = self.win = tk.Toplevel(self.root)
        win.title("The Bazaar - Lock Bypass")
        win.configure(bg=WINDOW_BG, padx=10, pady=8)
        win.attributes("-topmost", True)  # above the game, which runs borderless
        win.protocol("WM_DELETE_WINDOW", self.close)
        label = dict(bg=WINDOW_BG, fg=FG, font=(FONT, 10))
        tk.Label(win, text="Pick a locked card: it's yours for the rest of this run, upgrades included.",
                 **{**label, "fg": ACCENT, "font": (FONT, 11, "bold")}).pack(anchor="w", pady=(0, 6))

        bar = tk.Frame(win, bg=WINDOW_BG)
        bar.pack(fill="x")
        text = self.vars["text"] = tk.StringVar(win)
        tk.Label(bar, text="Search", **label).pack(side="left")
        self.vars["entry"] = tk.Entry(bar, textvariable=text, width=22, font=(FONT, 10))
        self.vars["entry"].pack(side="left", padx=(4, 10))
        for key, title, values in (("hero", "Hero", (ANY, "Common", *HEROES)), ("size", "Size", (ANY, *SIZES)),
                                   ("tier", "Rarity", (ANY, *TIERS))):
            var = self.vars[key] = tk.StringVar(win, ANY)
            tk.Label(bar, text=title, **label).pack(side="left")
            menu = tk.OptionMenu(bar, var, *values)
            menu.configure(font=(FONT, 9), highlightthickness=0, width=max(len(v) for v in values) - 2)
            menu.pack(side="left", padx=(4, 10))
        locked_only = self.vars["locked_only"] = tk.BooleanVar(win, False)
        tk.Checkbutton(bar, text="Locked only", variable=locked_only, selectcolor=WINDOW_BG,
                       activebackground=WINDOW_BG, activeforeground=FG, **label).pack(side="left")

        style = ttk.Style(win)
        style.theme_use("clam")  # the only built-in theme that honours these colours (nothing else here uses ttk)
        style.configure("Picker.Treeview", background=WINDOW_BG, fieldbackground=WINDOW_BG, foreground=FG,
                        rowheight=22, font=(FONT, 10))
        style.configure("Picker.Treeview.Heading", font=(FONT, 10, "bold"))
        body = tk.Frame(win, bg=WINDOW_BG)
        body.pack(fill="both", expand=True, pady=6)
        tree = self.tree = ttk.Treeview(body, style="Picker.Treeview", columns=[c for c, _, _ in COLUMNS],
                                        height=ROWS, selectmode="browse")
        tree.heading("#0", text="Card", anchor="w")
        tree.column("#0", width=240)
        for column, heading, width in COLUMNS:
            tree.heading(column, text=heading, anchor="w")
            tree.column(column, width=width, anchor="w")
        tree.tag_configure("allowed", foreground=DIM)
        tree.tag_configure("locked", foreground=WARN)
        scroll = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        tree.bind("<<TreeviewSelect>>", lambda _: self.selection_changed())

        foot = tk.Frame(win, bg=WINDOW_BG)
        foot.pack(fill="x")
        self.note = tk.Label(foot, text="", **label)
        self.note.pack(side="left")
        self.button = tk.Button(foot, text="Use Lock Bypass", font=(FONT, 10, "bold"), state="disabled",
                                command=self.pick)
        self.button.pack(side="right")
        for key in ("text", "hero", "size", "tier", "locked_only"):
            self.vars[key].trace_add("write", lambda *_: self.refresh())

    def refresh(self) -> None:
        v = self.vars
        cards = filter_cards(CARDS, v["text"].get(), v["hero"].get(), v["size"].get(), v["tier"].get(),
                             v["locked_only"].get(), self.locked)
        tree = self.tree
        tree.delete(*tree.get_children())
        for card in cards:
            tree.insert("", "end", iid=card.guid, text=card.name, values=row(card, self.locked),
                        tags=("locked" if card.guid in self.locked else "allowed",))
        self.selection_changed()

    def selected(self) -> Optional[str]:
        chosen = self.tree.selection() if self.tree else ()
        return chosen[0] if chosen else None

    def selection_changed(self) -> None:
        guid = self.selected()
        usable = guid in self.locked
        self.button.configure(state="normal" if usable else "disabled")
        ready = f"{self.ready} Lock Bypass{'es' if self.ready != 1 else ''} ready."
        self.note.configure(text=ready if usable or not guid else f"{ready} That card isn't locked this run.")

    def pick(self) -> None:
        guid = self.selected()
        if guid in self.locked:
            self.on_pick(guid)
            self.close()
