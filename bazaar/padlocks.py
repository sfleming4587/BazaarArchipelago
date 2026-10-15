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
    option: Optional[int] = None  # an event option: its place in the measured layout, used only without a card


def to_screen(rect: Rect, window: tuple) -> Rect:
    """A rect in fractions of the game window, on screen."""
    x, y, w, h = window
    return x + rect[0] * w, y + rect[1] * h, x + rect[2] * w, y + rect[3] * h


def touches(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def coverings(ui, window: tuple) -> List[Tuple[Rect, Optional[str]]]:
    """What the game shows on top right now, on screen, each with the card it belongs to (or None): the tooltips'
    pieces, and the card that's lifted above the others - the one dragged, else the one hovered or right-clicked
    (enlarged). The tooltips are the hovered card's own (read only while one is hovered): they slide in over its
    padlock, which flashed it see-through (owner's clip, 2026-10-15), so they never fade that one."""
    out = [(to_screen(r, window), ui.hovered_card) for r in ui.tooltips]
    lifted = ui.dragged_card if ui.dragging else ui.hovered_card if ui.hovering else None
    if lifted in ui.cards:
        out.append((to_screen(ui.cards[lifted], window), lifted))
    return out


def covered(rect: Rect, covers: Sequence[Tuple[Rect, Optional[str]]], pad: float = 0,
            own: Optional[str] = None) -> bool:
    """Does something the game shows reach rect (padded)? A card's own picture never covers its own padlock."""
    padded = (rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad)
    return any(touches(padded, r) for r, card in covers if card is None or card != own)


def spot(padlock: Padlock, ui, window: tuple, size: float, options: Sequence[tuple] = ()) -> Optional[Rect]:
    """The padlock's square on screen: the centre of its card (from memory: event options and a right-clicked
    monster's items too, owner 2026-10-15), or of an event option with no card (measured); None when its card isn't
    on screen - never a guess (owner, 2026-10-14)."""
    if padlock.card is not None:
        rect = ui.cards.get(padlock.card) if ui is not None else None
        if not rect:
            return None
        left, top, right, bottom = to_screen(rect, window)
        centre = (left + right) / 2, (top + bottom) / 2
        x, y, w, h = window
        if not (x + size / 2 <= centre[0] <= x + w - size / 2 and y + size / 2 <= centre[1] <= y + h - size / 2):
            return None  # off the game window (sliding in or out): no art there, and never clamped to the edge
            # (owner, 2026-10-15: a padlock shows only where its card's art is)
    elif padlock.option is not None and padlock.option < len(options) and ui is not None:
        centre = options[padlock.option]
    else:
        return None
    return centre[0] - size / 2, centre[1] - size / 2, centre[0] + size / 2, centre[1] + size / 2


def alpha(padlock: Padlock, square: Optional[Rect], ui, covers, pad: float, turning_since: float, now: float) -> float:
    """How the padlock shows (ui must be readable: the overlay shows none otherwise)."""
    if square is None or ui.dialog:  # square None: its card isn't on screen or is turned away (memreader)
        return HIDDEN
    if ui.inspecting:  # the right-clicked card fills the screen: its padlock rides on it (an event's too), and so do
        # a right-clicked monster's items' (owner, 2026-10-15); nothing else can be seen or clicked
        shown = padlock.card == ui.hovered_card or padlock.card in dict(ui.monster_items)
        return SOLID if padlock.card is not None and shown else HIDDEN
    if padlock.place is not None and turning_since and now < turning_since + padlock.place * FLIP_STAGGER:
        return HIDDEN  # its card hasn't turned face-up yet
    return SEE_THROUGH if covered(square, covers, pad, padlock.card) else SOLID
