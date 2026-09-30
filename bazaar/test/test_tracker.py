import os
import unittest

from ..screens import clamp, monitor_for
from ..tracker import square_status
from .test_client import ClientTestBase
from ..data import CARDS
from ..items import BASE_ID
from ..locations import day_location, location_name_to_id


class TestNeverOffScreen(unittest.TestCase):
    """User 2026-09-29: an overlay window must NEVER go off screen - every position goes through clamp()."""
    SCREEN = (0, 0, 2560, 1440)

    def test_inside_stays_put(self) -> None:
        self.assertEqual(clamp((100, 100, 300, 200), self.SCREEN), (100, 100, 300, 200))

    def test_every_side_is_pulled_back(self) -> None:
        for rect in [(-500, 10, 300, 200), (2500, 10, 300, 200), (10, -80, 300, 200), (10, 1400, 300, 200),
                     (-9999, -9999, 300, 200), (9999, 9999, 300, 200)]:
            with self.subTest(rect=rect):
                x, y, w, h = clamp(rect, self.SCREEN)
                self.assertTrue(0 <= x and x + w <= 2560 and 0 <= y and y + h <= 1440)

    def test_too_big_is_shrunk(self) -> None:
        self.assertEqual(clamp((0, 0, 4000, 3000), self.SCREEN), (0, 0, 2560, 1440))

    def test_second_monitor_left_of_the_main_one(self) -> None:
        self.assertEqual(clamp((-2000, 50, 300, 200), (-1920, 0, 1920, 1080)), (-1920, 50, 300, 200))

    def test_game_on_no_monitor_is_not_trusted(self) -> None:
        self.assertIsNone(monitor_for((5000, 5000, 1920, 1080), [self.SCREEN]))
        self.assertEqual(monitor_for((2000, 0, 1920, 1080), [self.SCREEN, (2560, 0, 1920, 1080)]),
                         (2560, 0, 1920, 1080))


class TestSquareColour(unittest.TestCase):
    def test_best_check_left_wins(self) -> None:  # user: "Best check left"
        self.assertEqual(square_status(["red", "yellow", "done"]), "yellow")
        self.assertEqual(square_status(["red", "green"]), "green")
        self.assertEqual(square_status(["done", "done"]), "done")
        self.assertIsNone(square_status([]))


class TestTrackerData(ClientTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.ctx.slot_data["logic"] = {"day_10": 15, "diamond": 10, "legendary": 20}
        vanessa = [BASE_ID + c.ap_id for c in CARDS if c.hero == "Vanessa" and c.shop][:20]
        self.ctx.slot_data["lock_items"] = vanessa

    def status(self, hero: str, kind: str, day: int) -> str:
        return next(c[4] for c in self.ctx.tracker_data()[hero]["checks"] if c[0] == kind and c[1] == day)

    def test_colours(self) -> None:
        self.ctx.checked_locations = {location_name_to_id[day_location("Vanessa", 1)]}
        self.assertEqual(self.status("Vanessa", "day", 1), "done")
        self.assertEqual(self.status("Vanessa", "day", 2), "green")  # days 1-7 need no cards
        self.assertEqual(self.status("Vanessa", "day", 9), "yellow")  # needs cards Vanessa doesn't have yet
        self.assertEqual(self.status("Dooley", "day", 1), "red")  # Dooley is locked in this test seed

    def test_heroes_outside_the_seed(self) -> None:
        data = self.ctx.tracker_data()
        self.assertEqual(len(data), 8)
        self.assertFalse(data["Karnok"]["in_seed"])
        self.assertTrue(data["Vanessa"]["in_seed"])


class TestShopGuideCardShapes(unittest.TestCase):
    """User 2026-09-29: Shop Guide cards at their in-game size (1/2/3 slots), cropped, never stretched."""

    def test_shapes_follow_board_slots(self) -> None:
        from ..cardart import card_shape
        small, medium, large = (next(c for c in CARDS if c.size == size) for size in ("Small", "Medium", "Large"))
        self.assertEqual(card_shape(small, 96), (48, 96))
        self.assertEqual(card_shape(medium, 96), (96, 96))
        self.assertEqual(card_shape(large, 96), (144, 96))

    def test_art_is_cropped_not_stretched(self) -> None:
        from ..cardart import fit
        size = 144
        square = bytearray(bytes((255, 0, 0)) * size * size)  # red, with a blue diagonal
        for x in range(size):
            square[(x * size + x) * 3:(x * size + x) * 3 + 3] = bytes((0, 0, 255))
        width, height, rgb = fit((size, size, bytes(square)), 144, 96)
        self.assertEqual((width, height, len(rgb)), (144, 96, 144 * 96 * 3))
        blue = [(x, y) for y in range(96) for x in range(144) if rgb[(y * 144 + x) * 3 + 2] > 200]
        slopes = {round((b[1] - a[1]) / (b[0] - a[0]), 1) for a, b in zip(blue, blue[1:]) if b[0] != a[0]}
        self.assertEqual(slopes, {1.0})  # stretching would change the angle; cropping keeps 45 degrees

    def test_shrinking_averages(self) -> None:
        from ..cardart import fit
        checker = bytes(v for i in range(4 * 4) for v in ((255,) * 3 if (i % 4 + i // 4) % 2 else (0,) * 3))
        self.assertEqual(fit((4, 4, checker), 2, 2)[2], bytes([127] * 12))

    def test_locked_is_grey_with_a_red_cross(self) -> None:
        from ..cardart import locked
        from ..theme import LOCKED_X
        width, height, rgb = locked((96, 96, bytes((255, 255, 255)) * 96 * 96))
        red = bytes(int(LOCKED_X[i:i + 2], 16) for i in (1, 3, 5))
        self.assertEqual(rgb[(48 * 96 + 48) * 3:(48 * 96 + 48) * 3 + 3], red)  # the middle is on the cross
        self.assertEqual(rgb[(2 * 96 + 48) * 3:(2 * 96 + 48) * 3 + 3], bytes([int(255 * 0.45)] * 3))

    def test_png_reads_back_through_sdl2(self) -> None:
        """Our PNG writer and the SDL2 decoder agree (the decoder is what reads the downloaded WebP pictures)."""
        from ..cardart import Decoder, png
        try:
            decoder = Decoder()
        except OSError:
            self.skipTest("no SDL2_image here")
        image = (3, 2, bytes(range(18)))
        self.assertEqual(decoder.decode(png(image)), image)


class TestCardArtWorker(unittest.TestCase):
    """The picture worker, with the download and the decoder faked: one zip of <guid>.webp for every card."""

    @staticmethod
    def picture_set(guids) -> bytes:
        import io
        import zipfile
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            for guid in guids:
                z.writestr(f"{guid}.webp", b"webp bytes")
        return data.getvalue()

    def run_worker(self, respond, decoder, old_files=()) -> tuple:
        import tempfile
        import threading
        from unittest import mock
        from .. import cardart
        card = next(c for c in CARDS if c.shop and c.size == "Medium")
        ready = threading.Event()
        downloads = []

        def fake_urlopen(request, timeout):
            downloads.append(request.full_url)
            return respond(card)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cardart, "Decoder", decoder),                 mock.patch.object(cardart.urllib.request, "urlopen", fake_urlopen):
            for name in old_files:
                open(os.path.join(folder, name), "w").close()
            art = cardart.CardArt(folder, 96, on_ready=lambda guid: ready.set())
            art.picture(card, False)
            ready.wait(3)
            for _ in range(60):  # a failure has no callback: wait for the worker to settle
                if ready.is_set() or not art.working or os.path.exists(art._missing(card.guid)):
                    break
                ready.wait(0.05)
            result = (ready.is_set(), art.working, art.picture(card, False), art.picture(card, True),
                      os.path.exists(art._missing(card.guid)), downloads, sorted(os.listdir(folder)))
            art.shutdown()
        return result

    def response(self, data: bytes):
        from unittest import mock
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = data
        return response

    def test_picture_from_the_set_is_saved_in_both_versions(self) -> None:
        from unittest import mock
        decoder = mock.MagicMock(return_value=mock.MagicMock(decode=lambda data: (8, 8, bytes([16]) * 192)))
        ready, working, normal, locked_path, _, downloads, _ = self.run_worker(
            lambda card: self.response(self.picture_set([card.guid])), decoder)
        self.assertTrue(ready and working)
        self.assertTrue(normal.endswith("_96x96.png") and locked_path.endswith("_96x96_locked.png"))
        self.assertEqual(len(downloads), 1)  # the whole set, once

    def test_card_the_set_lacks_is_remembered(self) -> None:
        from unittest import mock
        _, working, normal, _, missing, _, _ = self.run_worker(
            lambda card: self.response(self.picture_set(["someone-else"])), mock.MagicMock())
        self.assertTrue(missing and working)
        self.assertIsNone(normal)

    def test_failed_download_means_name_tiles_this_session(self) -> None:
        from unittest import mock

        def offline(card):
            raise OSError("offline")
        _, working, normal, _, missing, _, _ = self.run_worker(offline, mock.MagicMock())
        self.assertFalse(working)
        self.assertFalse(missing)  # asked again next session
        self.assertIsNone(normal)

    def test_damaged_download_is_thrown_away_not_fatal(self) -> None:
        """Review 2026-09-30: a damaged picture killed the worker for good and the zip stayed on disk."""
        import tempfile
        import time
        from unittest import mock
        from .. import cardart
        card = next(c for c in CARDS if c.shop)
        data = bytearray(self.picture_set([card.guid]))
        data[data.find(b"webp bytes")] ^= 1  # one flipped bit: Bad CRC
        decoder = mock.MagicMock(return_value=mock.MagicMock(decode=lambda d: (8, 8, bytes(192))))
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cardart, "Decoder", decoder),                 mock.patch.object(cardart.urllib.request, "urlopen", lambda r, timeout: self.response(bytes(data))):
            art = cardart.CardArt(folder, 96, on_ready=lambda guid: None)
            art.picture(card, False)
            for _ in range(60):
                if not art.working:
                    break
                time.sleep(0.05)
            self.assertFalse(art.working)  # name tiles this session, and it says so in the log file
            self.assertFalse(os.path.exists(os.path.join(folder, cardart.ART_SET, "card-art.zip")))  # fetched again
            art.shutdown()

    def test_pictures_from_older_sources_are_cleared(self) -> None:
        from unittest import mock
        from ..cardart import ART_SET
        *_, left = self.run_worker(lambda card: self.response(self.picture_set([])), mock.MagicMock(),
                                   old_files=("abc_48x96.png", "abc.missing"))
        self.assertEqual(left, [ART_SET])

    def test_no_sdl2_means_name_tiles(self) -> None:
        from unittest import mock
        _, working, normal, _, _, downloads, _ = self.run_worker(mock.MagicMock(),
                                                                 mock.MagicMock(side_effect=OSError("x")))
        self.assertEqual(downloads, [])  # nothing downloaded that couldn't be shown
        self.assertFalse(working)
        self.assertIsNone(normal)
