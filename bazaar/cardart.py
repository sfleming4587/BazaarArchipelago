"""
Card pictures for the Shop Guide, made without Pillow (Archipelago's Windows installer leaves Pillow out).

The pictures come from Bazaar DB (bazaardb.gg), whose developer gave them to this project (2026-09-30). They're
shrunk by tools/make_card_art.py into one zip of <card guid>.webp files, attached to this repo's GitHub release
ART_SET; the client downloads that zip ONCE (one request, not one per card) into its cache and reads pictures from
it. A new picture set = a new release tag in ART_SET (its own cache folder, so nothing old is reused). The game's own
files are never read for art: its EULA forbids data mining (see DEVELOPERS.md, "Card data is frozen").

Each picture is decoded by SDL2_image, which Archipelago ships for its GUI (it reads AVIF, WebP, PNG), called
through ctypes - never by importing Kivy, which must be set up by Archipelago's GUI first. The picture is cropped
to the card's in-game shape, scaled, and kept on this PC as two small PNGs (normal, and locked: greyed with a red
cross) that Tk shows by itself. It's Tempo's art, so it is never bundled with the apworld. All shop cards are
preloaded in the background by ONE low-priority worker, so opening a shop never stalls the game.
"""
import ctypes
import ctypes.util
import itertools
import logging
import os
import queue
import shutil
import struct
import sys
import threading
import time
import urllib.request
import zipfile
import zlib
from typing import Callable, Dict, Iterable, Optional, Tuple

from .data import Card
from .theme import LOCKED_X

ART_SET = "card-art-1"  # the GitHub release holding the pictures; also this set's cache folder
ART_URL = f"https://github.com/sfleming4587/BazaarArchipelago/releases/download/{ART_SET}/card-art.zip"
USER_AGENT = "BazaarArchipelago-client (+https://github.com/sfleming4587/BazaarArchipelago)"
TIER_COLORS = {"Bronze": "#cd7f32", "Silver": "#c0c0c0", "Gold": "#ffd700", "Diamond": "#7fe7ff",
               "Legendary": "#c77dff"}
URGENT, PRELOAD = 0, 1
PRELOAD_PAUSE = 0.15  # seconds between background pictures, so preloading never competes with the game
LOCKED_DIM = 0.45  # a locked card's picture: grey at this brightness
CROSS_HALF_WIDTH = 2.5  # the red cross's half thickness, in pixels
CROSS_INSET = 6  # its ends stay this far from the corners
# Board slots a card takes: in game every card is the same height, and 1 / 2 / 3 slots wide (user 2026-09-29: show
# them at their real size so they're easier to find). tools/make_card_art.py already cuts each picture to its shape.
SLOTS = {"Small": 1, "Medium": 2, "Large": 3}
SDL_PIXELFORMAT_RGB24 = 0x17101803

logger = logging.getLogger("Client")
Pixels = Tuple[int, int, bytes]  # width, height, RGB bytes row by row


def card_shape(card: Card, height: int) -> tuple:
    """(width, height) of a card at this height: half a card height per slot, like the board."""
    return height * SLOTS.get(card.size, 2) // 2, height


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
                grey = int((rgb[i] * 299 + rgb[i + 1] * 587 + rgb[i + 2] * 114) / 1000 * LOCKED_DIM)
                out += bytes((grey, grey, grey))
    return width, height, bytes(out)


def png(image: Pixels) -> bytes:
    """An RGB PNG file, which Tk reads by itself."""
    width, height, rgb = image

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
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

    def decode(self, data: bytes) -> Pixels:
        loaded = self.img.IMG_Load_RW(self.sdl.SDL_RWFromConstMem(data, len(data)), 1)  # 1: it frees the stream
        if not loaded:
            raise OSError("SDL2_image couldn't read the picture")
        try:
            rgb = self.sdl.SDL_ConvertSurfaceFormat(loaded, SDL_PIXELFORMAT_RGB24, 0)
        finally:
            self.sdl.SDL_FreeSurface(loaded)
        if not rgb:
            raise OSError("SDL2 couldn't convert the picture")
        try:
            s = rgb.contents
            raw = ctypes.string_at(s.pixels, s.pitch * s.h)
            return s.w, s.h, b"".join(raw[y * s.pitch:y * s.pitch + s.w * 3] for y in range(s.h))
        finally:
            self.sdl.SDL_FreeSurface(rgb)


# --- the cache and its worker -------------------------------------------------------------------------------------

class CardArt:
    def __init__(self, cache_dir: str, height: int, on_ready: Callable[[str], None]) -> None:
        self.cache_dir = os.path.join(cache_dir, ART_SET)
        self.height = height  # every card's height in the guide
        self.on_ready = on_ready  # called from the worker thread with the card guid once its pictures are on disk
        self.working = True  # False once decoding turned out impossible on this PC: name tiles only from then on
        self.jobs: "queue.PriorityQueue" = queue.PriorityQueue()
        self.order = itertools.count()
        self.queued: Dict[str, Card] = {}
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

    def path(self, card: Card, is_locked: bool) -> str:
        width, height = card_shape(card, self.height)
        return os.path.join(self.cache_dir, f"{card.guid}_{width}x{height}{'_locked' if is_locked else ''}.png")

    def _missing(self, guid: str) -> str:
        return os.path.join(self.cache_dir, f"{guid}.missing")

    def _have(self, card: Card) -> bool:
        return os.path.exists(self.path(card, True)) or os.path.exists(self._missing(card.guid))

    def preload(self, cards: Iterable[Card]) -> None:
        for card in cards:
            if not self._have(card):
                self._queue(card, PRELOAD)

    def picture(self, card: Card, is_locked: bool) -> Optional[str]:
        """The card's picture file, or None until there is one (then it's fetched first; on_ready says when)."""
        path = self.path(card, is_locked)
        if os.path.exists(path):
            return path
        if self.working and not os.path.exists(self._missing(card.guid)):
            self._queue(card, URGENT)
        return None

    def _queue(self, card: Card, priority: int) -> None:
        with self.lock:
            if card.guid in self.queued and priority == PRELOAD:
                return
            self.queued[card.guid] = card
        self.jobs.put((priority, next(self.order), card.guid))

    def _save(self, card: Card, pixels: Pixels) -> None:
        shaped = fit(pixels, *card_shape(card, self.height))
        for is_locked, image in ((False, shaped), (True, locked(shaped))):  # locked last: _have() looks for it
            temp = self.path(card, is_locked) + ".part"
            with open(temp, "wb") as f:
                f.write(png(image))
            os.replace(temp, self.path(card, is_locked))  # atomic: the window never reads a half-written file

    def _give_up(self, why: str) -> None:
        from .overlay import FILE_ONLY  # here, not at the top: overlay imports this module
        self.working = False
        logger.info(f"Shop Guide: {why}; cards show as name tiles.", extra=FILE_ONLY)

    def _pictures(self) -> Optional[zipfile.ZipFile]:
        """The picture set, downloaded once and kept (None if that failed: name tiles, tried again next session)."""
        path = self.zip_path = os.path.join(self.cache_dir, "card-art.zip")
        if not os.path.exists(path):
            try:
                request = urllib.request.Request(ART_URL, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = response.read()
                with open(path + ".part", "wb") as f:
                    f.write(data)
                os.replace(path + ".part", path)  # atomic: a cut-off download is never taken for the set
            except Exception as error:
                self._give_up(f"card pictures couldn't be downloaded ({error})")
                return None
        try:
            return zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            os.remove(path)  # damaged: downloaded again next session
            self._give_up("the card picture download was damaged")
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
            priority, _, guid = self.jobs.get()
            if self.stopped:
                return
            card = self.queued[guid]
            if self._have(card):
                continue
            try:
                data = pictures.read(f"{guid}.webp")
            except KeyError:  # the set has no picture of this card; don't look again
                open(self._missing(guid), "w").close()
                continue
            except (zipfile.BadZipFile, zlib.error, OSError) as error:  # the download is damaged: fetch it again
                pictures.close()
                try:
                    os.remove(self.zip_path)
                except OSError:
                    pass
                self._give_up(f"the card picture download is damaged ({error}); it's fetched again next time")
                return
            try:
                self._save(card, decoder.decode(data))
            except OSError as error:
                if not decoded_any:  # none ever worked: this PC's SDL2 can't read the format, so stop trying
                    self._give_up(f"card pictures can't be decoded here ({error})")
                    return
                continue  # one bad picture: a name tile this time
            decoded_any = True
            self.on_ready(guid)
            if priority == PRELOAD:
                time.sleep(PRELOAD_PAUSE)

    def shutdown(self) -> None:
        self.stopped = True
        self.jobs.put((URGENT, -1, ""))  # wake the worker so it can exit
