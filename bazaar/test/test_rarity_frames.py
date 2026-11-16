"""Rarity frames on pop-up pictures (owner, 2026-11-13): cards and merchants/events show in the game's frame of
their rarity, and "NEVER show a card art outside the border"."""
import io
import os
import struct
import threading
import unittest
import zipfile
import zlib

from .. import cardart
from ..cardart import FRAMES, compose, frame_plan, frame_px, framed, picture_shape
from ..data import CARDS, EVENTS, TIERS

MAGENTA = bytes((255, 0, 255))


def ring(size: int = 20, margin: int = 3, border: int = 3) -> cardart.Pixels:
    """A test frame: see-through margin, an opaque ring, a see-through hole."""
    out = bytearray()
    for y in range(size):
        for x in range(size):
            d = min(x, y, size - 1 - x, size - 1 - y)
            out += bytes((200, 150, 50, 255)) if margin <= d < margin + border else bytes(4)
    return size, size, bytes(out)


def magenta_under(frame: cardart.Pixels, box) -> cardart.Pixels:
    plan = frame_plan(frame)
    width, height = box[2] - box[0], box[3] - box[1]
    return compose((width, height, MAGENTA * (width * height)), frame, box, plan), plan.away


class TestNeverOutsideTheBorder(unittest.TestCase):
    def test_art_only_inside_the_frame(self) -> None:
        frame = ring()
        (_, _, out), away = magenta_under(frame, (0, 0, 20, 20))  # art covers the whole picture
        for i in range(20 * 20):
            pixel, frame_pixel = out[i * 4:i * 4 + 4], frame[2][i * 4:i * 4 + 4]
            if away[i]:
                self.assertEqual(pixel, frame_pixel)  # outside: the frame's own see-through pixel, no art
            elif frame_pixel[3] == 0:
                self.assertEqual(pixel, MAGENTA + b"\xff")  # the hole: the art
            else:
                self.assertEqual(pixel, frame_pixel)  # the ring: the frame on top
        self.assertEqual(sum(away), 20 * 20 - 14 * 14)  # only the margin is outside; the hole is enclosed

    def test_every_shipped_frame_keeps_the_art_inside(self) -> None:
        """Each of the game's frames, at the size pop-ups make: art fills the
        middle and never shows where the frame is see-through outside."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow reads the shipped frames here (the client uses SDL2)")
        art = zipfile.ZipFile(os.path.join(os.path.dirname(__file__), "..", "data", "card-art.zip"))
        for tier in TIERS:
            for kind in FRAMES:
                with self.subTest(tier=tier, kind=kind):
                    size, box = frame_px(kind, 96)
                    picture = Image.open(io.BytesIO(art.read(f"frame-{tier}-{kind}.webp"))).convert("RGBA")
                    self.assertLessEqual(abs(picture.width / picture.height - size[0] / size[1]), 0.02)
                    frame = cardart.fit_rgba((picture.width, picture.height, picture.tobytes()), *size)
                    (width, height, out), away = magenta_under(frame, box)
                    leaks = [i for i in range(width * height) if away[i]
                             and out[i * 4:i * 4 + 4] != frame[2][i * 4:i * 4 + 4]]
                    self.assertEqual(leaks, [])
                    middle = ((box[1] + box[3]) // 2) * width + (box[0] + box[2]) // 2
                    self.assertEqual(out[middle * 4:middle * 4 + 4], MAGENTA + b"\xff")  # the art shows
                    shown = sum(out[i * 4:i * 4 + 4] == MAGENTA + b"\xff" for i in range(width * height))
                    self.assertGreater(shown, 0.5 * (box[2] - box[0]) * (box[3] - box[1]))  # the arch: ~53%


class TestFramedKeys(unittest.TestCase):
    def test_a_key_names_its_picture_and_frame(self) -> None:
        card = next(c for c in CARDS if c.size == "Small")
        self.assertEqual(framed(f"{card.guid}@Gold"), cardart.Art(card.guid, "Small", "Gold"))
        event = next(iter(EVENTS))
        self.assertEqual(framed(f"{event}@Diamond"), cardart.Art(event, "Encounter", "Diamond"))
        self.assertIs(framed(card.guid), next(c for c in CARDS if c.guid == card.guid))  # plain, as before
        self.assertEqual(framed("item-5"), cardart.Art("item-5"))
        self.assertAlmostEqual(picture_shape(f"{event}@Bronze"), (729 / 647), places=2)
        self.assertAlmostEqual(picture_shape(card.guid), 0.5)


def png_colour_type(data: bytes) -> int:
    return data[25]


class TestFramedPictureIsMade(unittest.TestCase):
    def test_worker_makes_one_see_through_picture_per_frame(self) -> None:
        import tempfile
        from unittest import mock
        card = next(c for c in CARDS if c.shop and c.size == "Medium")
        shipped = io.BytesIO()
        with zipfile.ZipFile(shipped, "w") as z:
            z.writestr(f"{card.guid}.webp", b"art")
            z.writestr("frame-Gold-Medium.webp", b"frame")
        frame = ring(40, 2, 4)

        class Decoder:
            def decode(self, data, alpha=False):
                return frame if alpha else (8, 8, MAGENTA * 64)
        ready = []
        event = threading.Event()
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cardart, "Decoder", Decoder), \
                mock.patch.object(cardart.pkgutil, "get_data", lambda *_: shipped.getvalue()):
            art = cardart.CardArt(folder, 40, on_ready=lambda key: (ready.append(key), event.set()))
            item = framed(f"{card.guid}@Gold")
            art.picture(item, False)
            event.wait(5)
            data = art.picture(item, False)
            plain = art.picture(card, False)  # the same card unframed: its own picture, asked for separately
            art.shutdown()
        self.assertEqual(ready[0], f"{card.guid}@Gold")
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(png_colour_type(data), 6)  # RGBA: see-through outside the frame
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), frame_px("Medium", 40)[0])
        self.assertIsNone(plain)  # not made yet: framed and plain are different pictures

    def test_plain_png_is_unchanged(self) -> None:
        data = cardart.png((2, 1, bytes((1, 2, 3, 4, 5, 6))))
        self.assertEqual(png_colour_type(data), 2)
        self.assertEqual(zlib.decompress(data[data.find(b"IDAT") + 4:data.find(b"IEND") - 8]),
                         b"\x00" + bytes((1, 2, 3, 4, 5, 6)))


if __name__ == "__main__":
    unittest.main()


class TestItemGuideCardsAreFramed(unittest.TestCase):
    """Owner, 2026-11-13: "Lets put borders in the item guide" - every card in its rarity's frame, locked ones too."""

    def test_guide_card_framed_in_both_versions(self) -> None:
        import tempfile
        from unittest import mock
        card = next(c for c in CARDS if c.shop and c.size == "Small")
        shipped = io.BytesIO()
        with zipfile.ZipFile(shipped, "w") as z:
            z.writestr(f"{card.guid}.webp", b"art")
            z.writestr(f"frame-{card.tier}-Small.webp", b"frame")
        frame = ring(40, 2, 4)

        class Decoder:
            def decode(self, data, alpha=False):
                return frame if alpha else (8, 8, MAGENTA * 64)
        ready, event = [], threading.Event()
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cardart, "Decoder", Decoder), \
                mock.patch.object(cardart.pkgutil, "get_data", lambda *_: shipped.getvalue()):
            art = cardart.CardArt(folder, 40, on_ready=lambda key: (ready.append(key), event.set()), frames=True)
            art.picture(card, False)
            event.wait(5)
            normal, locked = art.picture(card, False), art.picture(card, True)
            art.shutdown()
        self.assertEqual(ready[0], card.guid)  # the guide is told by guid, as before (ShopGuide.refresh)
        for data in (normal, locked):
            self.assertEqual(png_colour_type(data), 6)
            self.assertEqual(struct.unpack(">II", data[16:24]), frame_px("Small", 40)[0])
        self.assertNotEqual(normal, locked)
