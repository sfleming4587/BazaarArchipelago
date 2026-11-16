"""
Padlocks that keep up with moving cards: one game frame behind, at the game's frame rate, and costing nothing while
nothing moves (owner 2026-11-12: "1 frame behind and matching the refresh rate"; "WAY too much cpu load").

The overlay's Tk thread works out which padlocks show and how see-through each is, from each board read (60 a
second). Where each one sits is this module's: it moves the padlock windows straight through Windows, from its own
thread, and only while a card moves does it look again - every FOLLOW_TICK, at where the cards are that instant
(memreader.Reader.positions: a handful of reads). Measured 2026-11-12: a Tk timer every 2 ms cost 15% of a core by
itself, a thread like this one 2-4%; a window move costs ~0.6 ms wherever it's made, so one only happens when the
padlock's square changed. Nothing in the game can tell us its cards moved (that would take code inside the game),
so while they move, it asks often; still, it waits.
"""
import threading
import time
from typing import Callable, Dict, NamedTuple, Optional, Sequence, Tuple

from . import padlocks, screens

FOLLOW_TICK = 0.002  # s between looks while cards move: several per game frame (144 a second = 6.9 ms)
MOVING_SECONDS = 0.25  # ...and for this long after the last padlock moved (a still card ends it)
SWP_FLAGS = 0x0001 | 0x0004 | 0x0010 | 0x0200  # SWP_NOSIZE | NOZORDER | NOACTIVATE | NOOWNERZORDER: only moved


class Plan(NamedTuple):
    """What the Tk thread wants followed: each padlock (padlocks.Padlock) and its window's handle, the board read they
    were placed from, the game window, the padlock's size, and the monitor they're kept on."""
    locks: Tuple[padlocks.Padlock, ...]
    handles: Tuple[int, ...]
    ui: object  # memreader.BoardUI
    window: tuple
    size: int
    area: tuple


def move_window(handle: int, x: int, y: int) -> None:
    import ctypes
    user32 = ctypes.windll.user32
    user32.SetWindowPos(ctypes.c_void_p(handle), None, x, y, 0, 0, SWP_FLAGS)


class Follower:
    """positions: the reader's Reader.positions (or None: then padlocks sit where each board read put them).
    move(handle, x, y): how a window is moved (move_window; tests record instead)."""

    def __init__(self, positions: Callable[[], Optional[Callable[[Sequence[str]], Dict[str, tuple]]]],
                 move: Callable[[int, int, int], None] = move_window) -> None:
        self.positions, self.move = positions, move
        self.plan: Optional[Plan] = None
        self.placed: Dict[int, tuple] = {}  # window handle -> where it was last put (x, y)
        self.woken = threading.Event()
        self.stopped = False

    def follow(self, plan: Optional[Plan]) -> None:
        """From the Tk thread, when what it wants changed: placed by the follower thread at once, and followed from
        there while it moves. Only that thread ever places: a window move waits for the Tk thread (it owns the
        window), so the Tk thread must never wait for the follower - it did, on a shared lock, and both froze
        (2026-11-12, the owner's first try)."""
        self.plan = plan
        self.woken.set()

    def stop(self) -> None:
        self.stopped = True
        self.woken.set()

    def run(self) -> None:
        """The follower thread: asleep until a padlock moves, then a look every FOLLOW_TICK until all are still."""
        while not self.stopped:
            self.woken.wait()
            self.woken.clear()
            until = time.perf_counter() + MOVING_SECONDS
            while not self.stopped and time.perf_counter() < until:
                self.woken.clear()  # a newer plan while following: this loop takes it up
                plan = self.plan
                ui = plan.ui if plan is not None else None
                if plan is not None and self.step(plan) or ui is not None and (ui.dragging or ui.stash_moving):
                    until = time.perf_counter() + MOVING_SECONDS
                time.sleep(FOLLOW_TICK)

    def step(self, plan: Plan) -> bool:
        """Each padlock to its card's square now (padlocks.spot): where the card is this instant if the reader can
        say, else where the board read had it. Only cards that read placed - whether a card is there at all is the
        board read's call. True if a window moved."""
        ui, positions = plan.ui, self.positions()
        if ui is None:
            return False
        cards = [lock.card for lock in plan.locks if lock.card in ui.cards]
        here = positions(cards) if positions is not None and cards else None
        if here:
            ui = ui._replace(cards={**ui.cards, **{card: here[card] for card in cards if card in here}})
        moved = False
        for lock, handle in zip(plan.locks, plan.handles):
            if plan is not self.plan:
                return moved  # the Tk thread has a newer one
            square = padlocks.spot(lock, ui, plan.window, plan.size)
            if square is None:
                continue  # hidden by padlock_look
            spot = screens.clamp((round(square[0]), round(square[1]), plan.size, plan.size), plan.area)[:2]
            if self.placed.get(handle) != spot:
                self.placed[handle] = spot
                self.move(handle, *spot)
                moved = True
        return moved
