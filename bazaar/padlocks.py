"""Where each padlock goes and how it shows - pure rules, no windows and no memory reading (the overlay draws what
these say; memreader supplies the board's state). A padlock is art on its card (owner, 2026-10-14): it sits on the
card wherever the card is, and is hidden while the card can't be bought or clicked, see-through while something
the game shows reaches it, solid otherwise. See docs/OVERLAY.md."""
from typing import List, NamedTuple, Optional, Sequence, Tuple

Rect = Tuple[float, float, float, float]  # left, top, right, bottom

HIDDEN, SEE_THROUGH, SOLID = 0.0, 0.3, 1.0  # see-through: so the tooltip over it reads (user, 2026-10-01)
COVER_PAD = 6  # px at 1080p around a padlock that a covering must reach (owner: "some padding ... not a lot")
FLIP_STAGGER = 0.12  # s between the cards of a new row turning face-up, left to right (clips, 2026-10-14)


class Padlock(NamedTuple):
    card: Optional[str] = None  # the card's instance id: the padlock sits on that card, read from memory
    place: Optional[int] = None  # its place in a new row, which turns face-up left to right; None: not turning
    why: Optional[str] = None  # the item that unlocks it, shown under it in the right-click view (owner 2026-11-10)
    # not a padlock but an AP marker - the Archipelago logo on a square of this colour ("green": in logic, "yellow":
    # out of logic), on the card's top-right corner: a monster/PvP card with a check still to get (owner 2026-11-13)
    marker: Optional[str] = None
    # what's drawn at the card's centre when it isn't a marker: "lock" (the padlock), or "sell_trap" - the burning skull
    # on the card a Sell Trap wants sold (owner 2026-11-16: "The sell trap icon instead of padlock shoud be the skull
    # with flames")
    kind: str = "lock"


MARKER_INSET = 0.6  # an AP marker's centre, from its card's top-right corner, in marker sizes


def to_screen(rect: Rect, window: tuple) -> Rect:
    """A rect in fractions of the game window, on screen."""
    x, y, w, h = window
    return x + rect[0] * w, y + rect[1] * h, x + rect[2] * w, y + rect[3] * h


def touches(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class Cover(NamedTuple):
    rect: Rect  # on screen
    card: Optional[str] = None  # the card it belongs to (None: no card's)
    tooltip: bool = False  # a piece of that card's tooltip (else the card's own lifted picture)


def coverings(ui, window: tuple, keyword_tray: bool = True) -> List[Cover]:
    """What the game shows on top right now, on screen, each with the card it belongs to (or None): the tooltips'
    pieces, and the card that's lifted above the others - the one dragged, else the one hovered or right-clicked
    (enlarged). The tooltips are the hovered card's own (read only while one is hovered): they slide in over its
    padlock, which flashed it see-through (owner's clip, 2026-10-15), so they never fade that one (an AP marker's
    do: covered, own_tooltip).
    keyword_tray=False: without the keyword tray at the bottom left (what fades the Item Guide, BoardUI.keyword_tray)."""
    skip = None if keyword_tray else getattr(ui, "keyword_tray", None)
    out = [Cover(to_screen(r, window), ui.hovered_card, True) for r in ui.tooltips if r != skip]
    lifted = ui.dragged_card if ui.dragging else ui.hovered_card if ui.hovering else None
    if lifted in ui.cards:
        out.append(Cover(to_screen(ui.cards[lifted], window), lifted))
    return out


def covered(rect: Rect, covers: Sequence[Tuple], pad: float = 0, own: Optional[str] = None,
            own_tooltip: bool = False) -> bool:
    """Does something the game shows reach rect (padded)? covers: Cover-shaped tuples. A card's own picture never
    covers its own padlock; its own tooltip does only with own_tooltip (an AP marker, owner 2026-11-13: "Almost
    impossible to get hit by its own tooltip but might as well code it in there")."""
    padded = (rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad)
    return any(touches(padded, c.rect) for c in (Cover(*c) for c in covers)
               if c.card is None or c.card != own or (own_tooltip and c.tooltip))


def spot(padlock: Padlock, ui, window: tuple, size: float) -> Optional[Rect]:
    """The padlock's square on screen: the centre of its card (from memory: event options and a right-clicked
    monster's items too, owner 2026-10-15); None when its card isn't on screen - never a guess (owner, 2026-10-14)."""
    rect = ui.cards.get(padlock.card) if ui is not None and padlock.card is not None else None
    if not rect:
        return None
    left, top, right, bottom = to_screen(rect, window)
    centre = (left + right) / 2, (top + bottom) / 2
    if padlock.marker:  # the card's top-right corner (owner 2026-11-13: "Top-right corner"), just inside it
        width, height = getattr(ui, "sizes", {}).get(padlock.card, (0.0, 0.0))  # an event option is placed as a point
        if right - left < 1 and width:  # (memreader.BoardUI.sizes): its box around that live centre
            right, top = centre[0] + width * window[2] / 2, centre[1] - height * window[3] / 2
        centre = right - size * MARKER_INSET, top + size * MARKER_INSET
    x, y, w, h = window
    if not (x + size / 2 <= centre[0] <= x + w - size / 2 and y + size / 2 <= centre[1] <= y + h - size / 2):
        return None  # off the game window (sliding in or out): no art there, and never clamped to the edge
        # (owner, 2026-10-15: a padlock shows only where its card's art is)
    return centre[0] - size / 2, centre[1] - size / 2, centre[0] + size / 2, centre[1] + size / 2


def alpha(padlock: Padlock, square: Optional[Rect], ui, covers, pad: float, turning_since: float, now: float,
          windows: Sequence[Rect] = ()) -> float:
    """How the padlock shows (ui must be readable: the overlay shows none otherwise). windows: our own windows on
    screen (the tracker, the Item Guide): its card can't be seen under one, so it hides there (owner, 2026-11-11)."""
    return look(padlock, square, ui, covers, pad, turning_since, now, windows)[0]


def look(padlock: Padlock, square: Optional[Rect], ui, covers, pad: float, turning_since: float, now: float,
         windows: Sequence[Rect] = ()) -> Tuple[float, str]:
    """alpha's answer and the rule that gave it, for the client's log file (2026-11-12: padlocks went missing on the
    owner's other PC with no way to tell why)."""
    if square is None:  # its card isn't on screen or is turned away (memreader)
        return HIDDEN, "card not placed"
    if ui.dialog:
        return HIDDEN, "dialog"
    if any(touches(square, w) for w in windows):
        return HIDDEN, "under our window"
    if ui.inspecting:  # the right-clicked card fills the screen: its padlock rides on it (an event's too), and so do
        # a right-clicked monster's items' (owner, 2026-10-15); nothing else can be seen or clicked
        shown = padlock.card == ui.hovered_card or padlock.card in dict(ui.monster_items)
        return (SOLID, "right-click view, its card") if padlock.card is not None and shown \
            else (HIDDEN, "right-click view")
    if padlock.place is not None and turning_since and now < turning_since + padlock.place * FLIP_STAGGER:
        return HIDDEN, "flipping"  # its card hasn't turned face-up yet
    hit = covered(square, covers, pad, padlock.card, own_tooltip=bool(padlock.marker))
    return (SEE_THROUGH, "covered") if hit else (SOLID, "solid")


def inspected(locks, squares, ui, window: tuple) -> Optional[Tuple[str, float, float]]:
    """The right-clicked card's "Locked behind" line (owner, 2026-11-10): (text, centre x, top y) on screen, just under
    the card's art - its rect from memory, or under its padlock for an event (memory has the event as a point). None
    when nothing locked is being inspected. squares: each lock's padlock square on screen (spot)."""
    if ui is None or not ui.inspecting or ui.dialog:
        return None
    for lock, square in zip(locks, squares):
        if lock.card is not None and lock.card == ui.hovered_card and lock.why and square is not None:
            rect = ui.cards.get(lock.card)
            if rect is None:
                return None
            left, top, right, bottom = to_screen(rect, window)
            if bottom - top < square[3] - square[1]:  # a point: under the padlock instead
                return f"Locked behind: {lock.why}", (square[0] + square[2]) / 2, square[3]
            return f"Locked behind: {lock.why}", (left + right) / 2, bottom
    return None
