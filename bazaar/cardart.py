"""
Card pictures for the Shop Guide.

Art is downloaded from howbazaar.gg's public image CDN (same card ids as the game) and cached on this PC only as
small thumbnails - it's Tempo's art, so it is never bundled with the apworld. All shop cards are preloaded in the
background at startup by ONE low-priority worker, so opening a shop never triggers a burst of downloads/decoding.
Cards the CDN doesn't have yet (new heroes lag behind) get a generated tile with the card's name and tier.
"""
import io
import itertools
import os
import queue
import threading
import time
import urllib.request
from typing import Callable, Dict, Iterable

from .data import Card

ART_URL = "https://howbazaar-images.b-cdn.net/images/items/{guid}.avif"
USER_AGENT = "BazaarArchipelago-client (+https://github.com/sfleming4587/BazaarArchipelago)"
TIER_COLORS = {"Bronze": "#cd7f32", "Silver": "#c0c0c0", "Gold": "#ffd700", "Diamond": "#7fe7ff",
               "Legendary": "#c77dff"}
URGENT, PRELOAD = 0, 1
# Board slots a card takes: in game every card is the same height, and 1 / 2 / 3 slots wide (user 2026-09-29: show
# them at their real size so they're easier to find). The CDN art is a square painting; the game shows a crop of it.
SLOTS = {"Small": 1, "Medium": 2, "Large": 3}


def card_shape(card: Card, height: int) -> tuple:
    """(width, height) of a card at this height: half a card height per slot, like the board."""
    return height * SLOTS.get(card.size, 2) // 2, height
PRELOAD_PAUSE = 0.15  # seconds between background downloads, so preloading never competes with the game


class CardArt:
    def __init__(self, cache_dir: str, height: int, on_ready: Callable[[str], None]) -> None:
        self.cache_dir = cache_dir
        self.height = height  # every card's height in the guide
        self.size = height * 3 // 2  # the square kept on disk: enough for the widest (3-slot) card
        self.on_ready = on_ready  # called from the worker thread with the card guid once its thumbnail is on disk
        self.jobs: "queue.PriorityQueue" = queue.PriorityQueue()
        self.order = itertools.count()
        self.queued: set = set()
        self.lock = threading.Lock()
        self.memory: Dict[str, "object"] = {}
        self.stopped = False
        os.makedirs(cache_dir, exist_ok=True)
        threading.Thread(target=self._work, name="bazaar art", daemon=True).start()

    def _png(self, guid: str) -> str:
        return os.path.join(self.cache_dir, f"{guid}_sq{self.size}.png")

    def _missing(self, guid: str) -> str:
        return os.path.join(self.cache_dir, f"{guid}.missing")

    def _have(self, guid: str) -> bool:
        return os.path.exists(self._png(guid)) or os.path.exists(self._missing(guid))

    def preload(self, cards: Iterable[Card]) -> None:
        for card in cards:
            if not self._have(card.guid):
                self._queue(card.guid, PRELOAD)

    def image(self, card: Card):
        """The card at its in-game shape (1/2/3 slots wide): its art cropped from the middle, never stretched - or,
        until the art is downloaded, a name tile of that shape (and fetch the art first)."""
        from PIL import Image, ImageOps
        if card.guid in self.memory:
            return self.memory[card.guid]
        path = self._png(card.guid)
        if os.path.exists(path):
            try:
                img = ImageOps.fit(Image.open(path).convert("RGB"), card_shape(card, self.height), Image.LANCZOS)
                self.memory[card.guid] = img
                return img
            except OSError:
                pass  # unreadable; fall back to a tile this time
        if not os.path.exists(self._missing(card.guid)):
            self._queue(card.guid, URGENT)
        return self.tile(card)

    def _queue(self, guid: str, priority: int) -> None:
        with self.lock:
            if guid in self.queued and priority == PRELOAD:
                return
            self.queued.add(guid)
        self.jobs.put((priority, next(self.order), guid))

    def _work(self) -> None:
        from PIL import Image
        while not self.stopped:
            priority, _, guid = self.jobs.get()
            if self.stopped:
                return
            if self._have(guid):
                continue
            try:
                request = urllib.request.Request(ART_URL.format(guid=guid), headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = response.read()
                temp = self._png(guid) + ".part"
                Image.open(io.BytesIO(data)).convert("RGB").resize((self.size, self.size)).save(temp, format="PNG")
                os.replace(temp, self._png(guid))  # atomic, so the window never reads a half-written file
                self.on_ready(guid)
            except Exception as error:
                # 404 = the CDN doesn't have this card (yet); remember so we don't ask again
                if getattr(error, "code", None) == 404:
                    open(self._missing(guid), "w").close()
            if priority == PRELOAD:
                time.sleep(PRELOAD_PAUSE)

    def tile(self, card: Card):
        """A generated placeholder: the card name on a frame in its tier colour."""
        from PIL import Image, ImageDraw, ImageFont
        key = f"tile:{card.guid}"
        if key in self.memory:
            return self.memory[key]
        width, size = card_shape(card, self.height)
        img = Image.new("RGB", (width, size), "#1d1a24")
        draw = ImageDraw.Draw(img)
        draw.rectangle([1, 1, width - 2, size - 2], outline=TIER_COLORS.get(card.tier, "#888888"), width=3)
        try:
            font = ImageFont.truetype("segoeuib.ttf", max(9, size // 9))
        except OSError:
            font = ImageFont.load_default()
        lines, line = [], ""
        for word in card.name.split():
            if line and draw.textlength(f"{line} {word}", font=font) > width - 8:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
        height = size // 8 + 2
        y = (size - height * len(lines)) / 2
        for text in lines:
            draw.text(((width - draw.textlength(text, font=font)) / 2, y), text, fill="white", font=font)
            y += height
        self.memory[key] = img
        return img

    def shutdown(self) -> None:
        self.stopped = True
        self.jobs.put((URGENT, -1, ""))  # wake the worker so it can exit
