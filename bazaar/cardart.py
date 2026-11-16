"""
Card pictures for the Item Guide, made without Pillow (Archipelago's Windows installer leaves Pillow out).

The pictures come from Bazaar DB (bazaardb.gg), whose developer gave them to this project (2026-09-30). They're
shrunk by tools/make_card_art.py into one zip of <card guid>.webp files, data/card-art.zip, shipped inside the
apworld: nothing is downloaded (owner, 2026-10-02: only what Archipelago strictly needs leaves the network). A new
picture set = a new zip and a new ART_SET (its own cache folder, so nothing old is reused).

Each picture is decoded by SDL2_image, which Archipelago ships for its GUI (it reads AVIF, WebP, PNG), called
through ctypes - never by importing Kivy, which must be set up by Archipelago's GUI first. The picture is cropped
to the card's in-game shape, scaled, and kept on this PC as two small PNGs (normal, and locked: greyed with a red
cross) that Tk shows by itself. All shop cards are
preloaded in the background by ONE low-priority worker, so opening a shop never stalls the game.
"""
import ctypes
import ctypes.util
import io
import itertools
import logging
import os
import pkgutil
import queue
import shutil
import struct
import sys
import threading
import time
import zipfile
import zlib
from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple

from .data import CARDS_BY_GUID, Card
from .theme import LOCKED_X

ART_SET = "card-art-7"  # the picture set in data/card-art.zip; also its cache folder (4: 12 blank
# pictures replaced; 5: every picture 192 px tall; 6: item symbols centred again, 2026-11-12; 7: Small/Large
# paintings squeezed whole into the card like the game, not cropped, 2026-11-13)
# Legendary, owner 2026-10-07: "a bright vibrant red, with a tinge of gold" - warmer than theme.LOCKED_X's crimson
TIER_COLORS = {"Bronze": "#cd7f32", "Silver": "#c0c0c0", "Gold": "#ffd700", "Diamond": "#7fe7ff",
               "Legendary": "#ff4510"}
URGENT, PRELOAD = 0, 1
PRELOAD_PAUSE = 0.15  # seconds between pictures DECODED in the background, so preloading never competes with the game
# (reading one already made needs no pause)
LOCKED_DIM = 0.45  # a locked card's picture: grey at this brightness
LUMA = (299, 587, 114)  # per mille of red, green, blue in a pixel's brightness (ITU-R BT.601)
CROSS_HALF_WIDTH = 2.5  # the red cross's half thickness, in pixels
CROSS_INSET = 6  # its ends stay this far from the corners
# Board slots a card takes: in game every card is the same height, and 1 / 2 / 3 slots wide (user 2026-09-29: show
# them at their real size so they're easier to find). tools/make_card_art.py already cuts each picture to its shape.
SLOTS = {"Small": 1, "Medium": 2, "Large": 3}
SDL_PIXELFORMAT_RGB24 = 0x17101803
SDL_PIXELFORMAT_RGBA32 = 0x16762004  # R, G, B, A bytes in memory (ABGR8888 on little-endian Windows)

logger = logging.getLogger("Client")
Pixels = Tuple[int, int, bytes]  # width, height, RGB (or RGBA, see fit_rgba) bytes row by row
Box = Tuple[float, float, float, float]  # left, top, right, bottom


class Frame(NamedTuple):
    """How the game draws a card in its rarity frame, as fractions of the card (x from the left, y from the top).
    The frame picture covers `frame`; ours (data/card-art.zip frame-<rarity>-<kind>.webp) is cut to `canvas`, the part
    holding any of it; the card's picture fills `art`, under the frame, never outside its outline (owner,
    2026-11-13: "NEVER show a card art outside the border")."""
    aspect: float  # the card's width / height
    art: Box
    frame: Box
    canvas: Box


# The game's 2D cards (cardframes/cardui bundles, read 2026-11-13, patch 1.0.13175): CardPreviewItem_P (Small),
# CardPreviewItem_Medium_PV, CardPreviewItem_Large_PV - CardImage and FrameContainer anchors; CardPreview_Encounter_P
# for merchants and events - the frame fills the card, the picture sits in Image_1, clipped to the arch
# (EncounterFrame_Interior_TUI), cut out of each frame when the pictures are made. Large's frame
# sprite is 1024 wide with the frame in pixels 147-877: its canvas is that part (x -0.005 to 1.005) and a little
# room for the edge.
FRAMES: Dict[str, Frame] = {
    "Small": Frame(0.5, (0.049, 0.0278, 0.951, 0.963), (-0.0223, -0.0231, 1.0223, 1.0139),
                   (-0.0223, -0.0231, 1.0223, 1.0139)),
    "Medium": Frame(1.0, (0.0312, 0.0278, 0.9688, 0.963), (-0.0289, -0.0231, 1.0289, 1.0139),
                    (-0.0289, -0.0231, 1.0289, 1.0139)),
    "Large": Frame(1.5, (0.0163, 0.0231, 0.9837, 0.9676), (-0.2077, -0.0231, 1.2077, 1.0139),
                   (-0.012, -0.0231, 1.012, 1.0139)),
    "Encounter": Frame(729 / 647, (0.053, 0.0046, 0.943, 1.0046), (0.0, 0.0, 1.0, 1.0), (0.0, 0.0, 1.0, 1.0)),
}
OUTSIDE_ALPHA = 128  # a frame pixel less opaque than this, reached from the picture's edge, is outside the frame


class Art(NamedTuple):
    """Any picture in the set that isn't a card: a merchant's, event's or level-up step's (by its guid) or an item's
    symbol ("item-<id>"); square, like an encounter card (owner, 2026-11-12: pictures for all unlockables).
    With `frame` (a rarity), the picture in the game's frame of that rarity, `size` being its FRAMES kind."""
    guid: str
    size: str = "Medium"
    frame: Optional[str] = None


def framed(key: str):
    """What a pop-up picture key shows: "<guid>@<rarity>" is that card's, merchant's or event's picture in the frame
    of that rarity (owner, 2026-11-13); a card's guid its plain picture; anything else a picture in the set."""
    guid, _, rarity = key.partition("@")
    card = CARDS_BY_GUID.get(guid)
    if rarity:
        return Art(guid, card.size if card else "Encounter", rarity)
    return card or Art(guid)


def frame_px(kind: str, height: int) -> tuple:
    """(width, height) of a framed picture whose card is `height` tall, and its art box in pixels in it."""
    frame = FRAMES[kind]
    left, top, right, bottom = frame.canvas
    width = round((right - left) * frame.aspect * height)
    box = (round((frame.art[0] - left) * frame.aspect * height), round((frame.art[1] - top) * height),
           round((frame.art[2] - left) * frame.aspect * height), round((frame.art[3] - top) * height))
    return (width, round((bottom - top) * height)), box


def card_shape(card, height: int) -> tuple:
    """(width, height) of a card at this height: half a card height per slot, like the board; a framed picture's
    (Art with a frame) is its frame's, the card part `height` tall."""
    if getattr(card, "frame", None):
        return frame_px(card.size, height)[0]
    return height * SLOTS.get(card.size, 2) // 2, height


def frame_offset(card, height: int) -> tuple:
    """Where a framed picture's top left sits from its card's top left (the frame reaches a little past the card)."""
    frame = FRAMES[card.size]
    return round(frame.canvas[0] * frame.aspect * height), round(frame.canvas[1] * height)


SHAPE_HEIGHT = 1000  # px: picture_shape measures at this height only for its ratio (big, so rounding barely moves it)


def picture_shape(key: str) -> float:
    """A pop-up picture's width / height before it's made, from its key (see framed)."""
    item = framed(key)
    width, height = card_shape(item, SHAPE_HEIGHT)
    return width / height


# --- pure picture helpers (no Tk, no SDL) -----------------------------------------------------------------------

def fit(image: Pixels, width: int, height: int) -> Pixels:
    """Scale to cover width x height without stretching, crop the middle, average the source pixels under each
    target pixel (so shrinking stays smooth)."""
    src_w, src_h, rgb = image
    scale = max(width / src_w, height / src_h)
    left, top = (src_w - width / scale) / 2, (src_h - height / scale) / 2

    def spans(start: float, count: int, limit: int) -> list:
        return [(int(start + i / scale), max(int(start + i / scale) + 1, min(limit, int(start + (i + 1) / scale))))
                for i in range(count)]
    columns, rows = spans(left, width, src_w), spans(top, height, src_h)
    out = bytearray()
    for y0, y1 in rows:
        for x0, x1 in columns:
            r = g = b = 0
            for y in range(y0, y1):
                row = rgb[(y * src_w + x0) * 3:(y * src_w + x1) * 3]
                r, g, b = r + sum(row[0::3]), g + sum(row[1::3]), b + sum(row[2::3])
            n = (y1 - y0) * (x1 - x0)
            out += bytes((r // n, g // n, b // n))
    return width, height, bytes(out)


def locked(image: Pixels) -> Pixels:
    """Greyed out with a red cross: a card you may not buy."""
    width, height, rgb = image
    cross = tuple(int(LOCKED_X[i:i + 2], 16) for i in (1, 3, 5))
    ends = ((CROSS_INSET, CROSS_INSET, width - 1 - CROSS_INSET, height - 1 - CROSS_INSET),
            (CROSS_INSET, height - 1 - CROSS_INSET, width - 1 - CROSS_INSET, CROSS_INSET))
    lines = [(x0, y0, x1 - x0, y1 - y0, ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5) for x0, y0, x1, y1 in ends]
    out = bytearray()
    for y in range(height):
        for x in range(width):
            on_cross = any(CROSS_INSET <= x <= width - 1 - CROSS_INSET and
                           abs((x - x0) * dy - (y - y0) * dx) / length <= CROSS_HALF_WIDTH
                           for x0, y0, dx, dy, length in lines)
            if on_cross:
                out += bytes(cross)
            else:
                i = (y * width + x) * 3
                grey = int(sum(c * w for c, w in zip(rgb[i:i + 3], LUMA)) / sum(LUMA) * LOCKED_DIM)
                out += bytes((grey, grey, grey))
    return width, height, bytes(out)


def fit_rgba(image: Pixels, width: int, height: int) -> Pixels:
    """fit for an RGBA picture, stretched to width x height (a frame fills its box like the game's): colours are
    averaged weighted by how opaque they are, so see-through pixels never darken an edge."""
    src_w, src_h, rgba = image
    sx, sy = src_w / width, src_h / height

    def spans(count: int, step: float, limit: int) -> list:
        return [(int(i * step), max(int(i * step) + 1, min(limit, int((i + 1) * step)))) for i in range(count)]
    columns, rows = spans(width, sx, src_w), spans(height, sy, src_h)
    out = bytearray()
    for y0, y1 in rows:
        for x0, x1 in columns:
            r = g = b = a = 0
            for y in range(y0, y1):
                row = rgba[(y * src_w + x0) * 4:(y * src_w + x1) * 4]
                alphas = row[3::4]
                r += sum(map(int.__mul__, row[0::4], alphas))
                g += sum(map(int.__mul__, row[1::4], alphas))
                b += sum(map(int.__mul__, row[2::4], alphas))
                a += sum(alphas)
            n = (y1 - y0) * (x1 - x0)
            out += bytes((r // a, g // a, b // a, a // n)) if a else bytes(4)
    return width, height, bytes(out)


def outside(frame: Pixels) -> bytearray:
    """1 for each pixel outside the frame: less opaque than OUTSIDE_ALPHA and reached from the picture's edge
    without crossing the frame. The hole in the middle is enclosed, so it isn't outside."""
    width, height, rgba = frame
    out = bytearray(width * height)
    clear = lambda i: rgba[i * 4 + 3] < OUTSIDE_ALPHA
    todo = [i for i in itertools.chain(range(width), range((height - 1) * width, height * width),
                                       range(0, height * width, width), range(width - 1, height * width, width))
            if clear(i)]
    for i in todo:
        out[i] = 1
    while todo:
        i = todo.pop()
        x = i % width
        for j in ((i - 1) if x else -1, (i + 1) if x < width - 1 else -1, i - width, i + width):
            if 0 <= j < width * height and not out[j] and clear(j):
                out[j] = 1
                todo.append(j)
    return out


class FramePlan(NamedTuple):
    """What a frame does to each pixel, worked out once per frame and size (frame_plan) so composing a picture is a
    few slice copies - pixel by pixel it held Python's lock long enough to slow the Item Guide (2026-11-13)."""
    away: bytearray  # 1 outside the frame (see outside): the frame's own pixel, never art
    holes: List[Tuple[int, int]]  # (first pixel, count) runs inside it where the frame is fully see-through: art
    blends: List[int]  # pixels inside it where the frame is partly see-through: frame over art


def frame_plan(frame: Pixels) -> FramePlan:
    width, height, rgba = frame
    away = outside(frame)
    holes: List[Tuple[int, int]] = []
    blends: List[int] = []
    for y in range(height):
        run = None
        for i in range(y * width, (y + 1) * width):
            hole = not away[i] and rgba[i * 4 + 3] == 0
            if hole and run is None:
                run = i
            elif not hole and run is not None:
                holes.append((run, i - run))
                run = None
            if not away[i] and 0 < rgba[i * 4 + 3] < 255:
                blends.append(i)
        if run is not None:
            holes.append((run, (y + 1) * width - run))
    return FramePlan(away, holes, blends)


def compose(art: Pixels, frame: Pixels, box: Tuple[int, int, int, int], plan: FramePlan) -> Pixels:
    """The card's picture (RGB, already the art box's size) under its frame (RGBA), as RGBA: outside the frame
    (plan.away) only the frame's own pixels, so the art never shows past its outline (owner, 2026-11-13); inside it,
    the frame over the art (over black where the art box doesn't reach)."""
    width, height, rgba = frame
    art_w, art_h, rgb = art
    left, top, right, bottom = box
    under = bytearray(width * height * 3)  # the art where its box is, black elsewhere
    x0, x1 = max(left, 0), min(right, width)
    for y in range(max(top, 0), min(bottom, height)):
        a = ((y - top) * art_w + x0 - left) * 3
        under[(y * width + x0) * 3:(y * width + x1) * 3] = rgb[a:a + (x1 - x0) * 3]
    out = bytearray(rgba)
    for first, count in plan.holes:
        o, u = first * 4, first * 3
        for c in range(3):
            out[o + c:o + count * 4:4] = under[u + c:u + count * 3:3]
        out[o + 3:o + count * 4:4] = bytes((255,)) * count
    for i in plan.blends:
        o, u, alpha = i * 4, i * 3, rgba[i * 4 + 3]
        for c in range(3):
            out[o + c] = (rgba[o + c] * alpha + under[u + c] * (255 - alpha)) // 255
        out[o + 3] = 255
    return width, height, bytes(out)


def png(image: Pixels) -> bytes:
    """An RGB or RGBA PNG file, which Tk reads by itself (see-through where an RGBA picture is)."""
    width, height, pixels = image
    channels = len(pixels) // (width * height)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    stride = width * channels
    rows = b"".join(b"\x00" + pixels[y * stride:(y + 1) * stride] for y in range(height))
    colour = 6 if channels == 4 else 2
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


# --- decoding through Archipelago's own SDL2_image ----------------------------------------------------------------

class _Surface(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint32), ("format", ctypes.c_void_p), ("w", ctypes.c_int), ("h", ctypes.c_int),
                ("pitch", ctypes.c_int), ("pixels", ctypes.c_void_p)]


def _sdl_folders() -> Iterable[str]:
    """Where SDL2_image.dll is: an installed Archipelago keeps it in lib/ beside the exe; a source checkout has it
    in the kivy_deps.sdl2 package (importing that only names folders, it doesn't start Kivy)."""
    here = os.path.dirname(sys.executable)
    yield os.path.join(here, "lib")
    yield here
    try:
        from kivy_deps import sdl2  # type: ignore
        yield from sdl2.dep_bins
    except ImportError:
        pass


class Decoder:
    """AVIF / WebP / PNG bytes -> RGB pixels. Raises OSError if SDL2_image can't be found or can't read the image."""

    def __init__(self) -> None:
        folder = next((f for f in _sdl_folders() if os.path.isfile(os.path.join(f, "SDL2_image.dll"))), None)
        if folder:  # a full path, so Windows finds SDL2.dll and the codecs beside it
            self.sdl = ctypes.CDLL(os.path.join(folder, "SDL2.dll"))
            self.img = ctypes.CDLL(os.path.join(folder, "SDL2_image.dll"))
        else:
            sdl, img = ctypes.util.find_library("SDL2"), ctypes.util.find_library("SDL2_image")
            if not (sdl and img):
                raise OSError("SDL2_image not found")
            self.sdl, self.img = ctypes.CDLL(sdl), ctypes.CDLL(img)
        self.sdl.SDL_RWFromConstMem.restype = ctypes.c_void_p
        self.sdl.SDL_RWFromConstMem.argtypes = [ctypes.c_char_p, ctypes.c_int]
        self.img.IMG_Load_RW.restype = ctypes.POINTER(_Surface)
        self.img.IMG_Load_RW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.sdl.SDL_ConvertSurfaceFormat.restype = ctypes.POINTER(_Surface)
        self.sdl.SDL_ConvertSurfaceFormat.argtypes = [ctypes.POINTER(_Surface), ctypes.c_uint32, ctypes.c_uint32]
        self.sdl.SDL_FreeSurface.argtypes = [ctypes.POINTER(_Surface)]

    def decode(self, data: bytes, alpha: bool = False) -> Pixels:
        """RGB pixels, or RGBA with `alpha` (a frame)."""
        loaded = self.img.IMG_Load_RW(self.sdl.SDL_RWFromConstMem(data, len(data)), 1)  # 1: it frees the stream
        if not loaded:
            raise OSError("SDL2_image couldn't read the picture")
        try:
            rgb = self.sdl.SDL_ConvertSurfaceFormat(loaded, SDL_PIXELFORMAT_RGBA32 if alpha else SDL_PIXELFORMAT_RGB24, 0)
        finally:
            self.sdl.SDL_FreeSurface(loaded)
        if not rgb:
            raise OSError("SDL2 couldn't convert the picture")
        try:
            s = rgb.contents
            raw, row = ctypes.string_at(s.pixels, s.pitch * s.h), s.w * (4 if alpha else 3)
            return s.w, s.h, b"".join(raw[y * s.pitch:y * s.pitch + row] for y in range(s.h))
        finally:
            self.sdl.SDL_FreeSurface(rgb)


# --- the cache and its worker -------------------------------------------------------------------------------------

def _file_only() -> dict:
    from .overlay import FILE_ONLY  # here, not at the top: overlay imports this module
    return FILE_ONLY

class CardArt:
    def __init__(self, cache_dir: str, height: int, on_ready: Callable[[str], None], frames: bool = False) -> None:
        self.cache_dir = os.path.join(cache_dir, ART_SET)
        self.height = height  # every card's height in the guide
        self.frames = frames  # every card in its rarity's frame, locked or not (the Item Guide, owner 2026-11-13)
        self.on_ready = on_ready  # called from the worker thread with the picture's key (key()) once it's in memory
        self.loaded: Dict[str, bytes] = {}  # picture file path -> its PNG bytes, read or made by the worker (picture)
        self.absent: set = set()  # guids the set has no picture of
        self.working = True  # False once decoding turned out impossible on this PC: name tiles only from then on
        self.jobs: "queue.PriorityQueue" = queue.PriorityQueue()
        self.order = itertools.count()
        self.queued: Dict[str, Card] = {}  # by key()
        self.frame_cache: Dict[tuple, tuple] = {}  # (rarity, kind, size) -> (frame pixels, frame_plan()), on the worker
        self.lock = threading.Lock()
        self.stopped = False
        os.makedirs(self.cache_dir, exist_ok=True)
        for old in os.listdir(cache_dir):  # pictures from earlier sets or sources (the folder is ours alone)
            path = os.path.join(cache_dir, old)
            if old == ART_SET:
                continue
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    os.remove(path)
                except OSError:  # in use somewhere: it's only a stale picture, try again next time
                    pass
        threading.Thread(target=self._work, name="bazaar art", daemon=True).start()

    @staticmethod
    def key(card) -> str:
        """The picture's key: the guid, plus "@<rarity>" when it's framed (as pop-ups name it, framed())."""
        frame = getattr(card, "frame", None)
        return f"{card.guid}@{frame}" if frame else card.guid

    @staticmethod
    def versions(card) -> tuple:
        """Locked or not: a pop-up's framed picture (Art with a frame) is only ever shown unlocked."""
        return (False,) if getattr(card, "frame", None) else (False, True)

    def drawn(self, card):
        """What's drawn for it: with `frames`, a card in its (starting) rarity's frame."""
        if self.frames and isinstance(card, Card):
            return Art(card.guid, card.size, card.tier)
        return card

    def path(self, card: Card, is_locked: bool) -> str:
        drawn = self.drawn(card)
        width, height = card_shape(drawn, self.height)
        return os.path.join(self.cache_dir, f"{self.key(drawn)}_{width}x{height}{'_locked' if is_locked else ''}.png")

    def _missing(self, guid: str) -> str:
        return os.path.join(self.cache_dir, f"{guid}.missing")

    def _have(self, card: Card) -> bool:
        """All its pictures are in memory, or the set has none."""
        return card.guid in self.absent or self.path(card, self.versions(card)[-1]) in self.loaded

    def preload(self, cards: Iterable[Card]) -> None:
        for card in cards:
            if not self._have(card):
                self._queue(card, PRELOAD)

    def picture(self, card: Card, is_locked: bool) -> Optional[bytes]:
        """The card's picture as PNG bytes, from memory; None until it's there - then it's read (or made) first, on
        the worker thread, and on_ready says when. Opening a file costs ~7 ms on the window's thread (Windows' file
        checks), decoding from memory 0.6 ms: the Item Guide's first merchant took 3.9 s (measured 2026-11-12)."""
        path = self.path(card, is_locked)
        data = self.loaded.get(path)
        if data is not None:
            return data
        if not self.working:  # no worker (no decoder on this PC): pictures made earlier are still read
            try:
                with open(path, "rb") as f:
                    data = self.loaded[path] = f.read()
                return data
            except OSError:
                return None
        if card.guid not in self.absent:
            self._queue(card, URGENT)
        return None

    def _queue(self, card: Card, priority: int) -> None:
        key = self.key(card)
        with self.lock:
            if key in self.queued and priority == PRELOAD:
                return
            self.queued[key] = card
        self.jobs.put((priority, next(self.order), key))

    def _frame(self, rarity: str, kind: str, size: tuple, pictures: zipfile.ZipFile, decoder: "Decoder") -> tuple:
        """The frame at this size and what's outside it (on the worker; kept for the next picture)."""
        cached = self.frame_cache.get((rarity, kind, size))
        if cached is None:
            frame = fit_rgba(decoder.decode(pictures.read(f"frame-{rarity}-{kind}.webp"), alpha=True), *size)
            cached = self.frame_cache[(rarity, kind, size)] = (frame, frame_plan(frame))
        return cached

    def _save(self, card: Card, pixels: Pixels, pictures: zipfile.ZipFile, decoder: "Decoder") -> None:
        drawn = self.drawn(card)
        if getattr(drawn, "frame", None):  # in its rarity's frame (owner, 2026-11-13)
            size, box = frame_px(drawn.size, self.height)
            frame, away = self._frame(drawn.frame, drawn.size, size, pictures, decoder)
            art = fit(pixels, box[2] - box[0], box[3] - box[1])
            versions = [(is_locked, compose(locked(art) if is_locked else art, frame, box, away))
                        for is_locked in self.versions(card)]  # locked last: _have() looks for it
        else:
            shaped = fit(pixels, *card_shape(card, self.height))
            versions = ((False, shaped), (True, locked(shaped)))  # locked last: _have() looks for it
        for is_locked, image in versions:
            data, path = png(image), self.path(card, is_locked)
            temp = path + ".part"
            with open(temp, "wb") as f:
                f.write(data)
            os.replace(temp, path)  # atomic: a later session never reads a half-written file
            self.loaded[path] = data

    def _read(self, card: Card) -> bool:
        """Its pictures from earlier sessions into memory, if they're there (on the worker thread)."""
        try:
            pictures = []
            for is_locked in self.versions(card):
                with open(self.path(card, is_locked), "rb") as f:
                    pictures.append((self.path(card, is_locked), f.read()))
        except OSError:
            return False
        self.loaded.update(pictures)  # locked last, as _have() looks for it
        return True

    def _give_up(self, why: str) -> None:
        self.working = False
        logger.info(f"Item Guide: {why}; cards show as name tiles.", extra=_file_only())

    def _pictures(self) -> Optional[zipfile.ZipFile]:
        """The picture set shipped in the apworld (None if it can't be read: name tiles)."""
        try:
            return zipfile.ZipFile(io.BytesIO(pkgutil.get_data(__package__, "data/card-art.zip") or b""))
        except (OSError, zipfile.BadZipFile) as error:
            self._give_up(f"the card pictures couldn't be read ({error})")
            return None

    def _work(self) -> None:
        """The worker thread. Nothing may kill it silently (review 2026-09-30): any error ends in name tiles and a
        line in the client's log file."""
        try:
            self._make_pictures()
        except Exception as error:
            self._give_up(f"card pictures stopped ({error!r})")

    def _make_pictures(self) -> None:
        try:
            decoder = Decoder()
        except OSError as error:
            self._give_up(f"no card pictures on this PC ({error})")
            return
        pictures = self._pictures()
        if pictures is None:
            return
        decoded_any = False
        while not self.stopped:
            priority, _, key = self.jobs.get()
            if self.stopped:
                return
            card = self.queued[key]
            guid = card.guid
            if self._have(card):
                continue
            if os.path.exists(self._missing(guid)):  # an earlier session found the set has none
                self.absent.add(guid)
                continue
            if self._read(card):  # made in an earlier session: just read (no pause, no decoding)
                self.on_ready(key)
                continue
            try:
                data = pictures.read(f"{guid}.webp")
            except KeyError:  # the set has no picture of this card; don't look again
                open(self._missing(guid), "w").close()
                self.absent.add(guid)
                continue
            except (zipfile.BadZipFile, zlib.error, OSError) as error:  # the shipped set is damaged
                self._give_up(f"the card pictures are damaged ({error})")
                return
            try:
                self._save(card, decoder.decode(data), pictures, decoder)
            except KeyError as error:  # no frame of this rarity in the set: this picture shows as a name tile
                logger.info(f"Item Guide: no frame {error} for {key}.", extra=_file_only())
                continue
            except OSError as error:
                if not decoded_any:  # none ever worked: this PC's SDL2 can't read the format, so stop trying
                    self._give_up(f"card pictures can't be decoded here ({error})")
                    return
                continue  # one bad picture: a name tile this time
            decoded_any = True
            self.on_ready(key)
            if priority == PRELOAD:
                time.sleep(PRELOAD_PAUSE)

    def shutdown(self) -> None:
        self.stopped = True
        self.jobs.put((URGENT, -1, ""))  # wake the worker so it can exit
