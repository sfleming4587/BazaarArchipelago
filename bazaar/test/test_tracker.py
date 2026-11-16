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
        self.ctx.slot_data["logic"] = {"day_10": 15, "last_day": 15, "diamond": 10, "legendary": 20}
        vanessa = [BASE_ID + c.ap_id for c in CARDS if c.hero == "Vanessa" and c.shop][:20]
        self.ctx.slot_data["lock_items"] = vanessa

    def status(self, hero: str, kind: str, day: int) -> str:
        return next(c[4] for c in self.ctx.tracker_data()[hero]["checks"] if c[0] == kind and c[1] == day)

    def test_colours(self) -> None:
        self.ctx.stored_data[self.ctx.sent_key()] = [location_name_to_id[day_location("Vanessa", 1)]]
        self.assertEqual(self.status("Vanessa", "day", 1), "done")
        self.assertEqual(self.status("Vanessa", "day", 2), "green")  # days 1-7 need no cards
        self.assertEqual(self.status("Vanessa", "day", 9), "yellow")  # needs cards Vanessa doesn't have yet
        self.assertEqual(self.status("Dooley", "day", 1), "red")  # Dooley is locked in this test seed

    def test_heroes_outside_the_seed(self) -> None:
        data = self.ctx.tracker_data()
        self.assertEqual(len(data), 8)
        self.assertFalse(data["Karnok"]["in_seed"])
        self.assertTrue(data["Vanessa"]["in_seed"])

    def test_counts_are_the_menu_panels(self) -> None:
        """Owner, 2026-11-13: "the 0/n checks and how many cards unlocked per character shown on the tracker as well" -
        the same numbers as the menu's hero panel, from one place (client.hero_counts)."""
        self.ctx.stored_data[self.ctx.sent_key()] = [location_name_to_id[day_location("Vanessa", 1)]]
        tracker = self.ctx.tracker_data()
        for hero, info in tracker.items():
            if info["in_seed"]:  # exactly the menu panel's numbers (menu_data reads hero_counts too)
                self.assertEqual({k: info[k] for k in ("done", "total", "cards", "cards_unlocked")},
                                 self.ctx.hero_counts(hero), hero)
        self.assertEqual(tracker["Vanessa"]["done"], 1)
        self.assertEqual(tracker["Vanessa"]["cards_unlocked"], tracker["Vanessa"]["cards"] - 20)  # 20 locked
        self.assertNotIn("total", tracker["Karnok"])  # not in the seed: no counts


class TestTrackerWindow(unittest.TestCase):
    """Owner, 2026-11-13: an icon on each square (PvP swords, day sunrise, monster jaw, 10 wins trophy) and the counts
    under each hero's card."""

    def test_icons_and_counts(self) -> None:
        import tkinter
        from ..data import HEROES
        from ..tracker import SQUARES, TrackedCheck, Tracker, icon_masks
        self.assertLessEqual({kind for kind, *_ in SQUARES}, set(icon_masks()["icons"]))  # every square has its icon
        root = tkinter.Tk()
        try:
            root.withdraw()
            tracker = Tracker(tkinter, root, lambda: (0, 0, 1920, 1080))
            checks = [TrackedCheck(kind, 1, "Bronze", kind, "green") for kind, *_ in SQUARES]
            tracker.update({h: {"in_seed": h == "Vanessa", "unlocked": True, "checks": checks, "done": 3, "total": 30,
                                "cards": 140, "cards_unlocked": 12} for h in HEROES})
            tracker.open()
            root.update_idletasks()
            canvas = tracker.canvases["Vanessa"]
            for kind, *_ in SQUARES:  # the square and its icon, both tagged as the square (hover works)
                self.assertEqual(len(canvas.find_withtag(kind)), 2, kind)
                self.assertTrue(canvas.itemcget(tracker.icons["Vanessa", kind], "image"), kind)  # drawn
            self.assertEqual(tracker.counts["Vanessa"].cget("text"), "3 / 30 checks  ·  12 / 140 cards")
            self.assertEqual(tracker.counts["Dooley"].cget("text"), "")  # not in the seed
            tracker.close()
        finally:
            root.destroy()


class TestShopGuideCardShapes(unittest.TestCase):
    """User 2026-09-29: Item Guide cards at their in-game size (1/2/3 slots), cropped, never stretched."""

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
    """The picture worker, with the shipped set and the decoder faked: one zip of <guid>.webp for every card."""

    @staticmethod
    def picture_set(guids) -> bytes:
        import io
        import zipfile
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            for guid in guids:
                z.writestr(f"{guid}.webp", b"webp bytes")
        return data.getvalue()

    def run_worker(self, shipped, decoder, old_files=()) -> tuple:
        import tempfile
        import threading
        from unittest import mock
        from .. import cardart
        card = next(c for c in CARDS if c.shop and c.size == "Medium")
        ready = threading.Event()
        reads = []

        def fake_get_data(package, resource):
            reads.append(resource)
            return shipped(card)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(cardart, "Decoder", decoder), \
                mock.patch.object(cardart.pkgutil, "get_data", fake_get_data):
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
                      os.path.exists(art._missing(card.guid)), reads, sorted(os.listdir(folder)))
            art.shutdown()
        return result

    def test_picture_from_the_set_is_saved_in_both_versions(self) -> None:
        from unittest import mock
        decoder = mock.MagicMock(return_value=mock.MagicMock(decode=lambda data: (8, 8, bytes([16]) * 192)))
        ready, working, normal, locked_path, _, reads, _ = self.run_worker(
            lambda card: self.picture_set([card.guid]), decoder)
        self.assertTrue(ready and working)
        self.assertTrue(normal.startswith(b"\x89PNG") and locked_path.startswith(b"\x89PNG"))  # from memory
        self.assertNotEqual(normal, locked_path)
        self.assertEqual(reads, ["data/card-art.zip"])  # the shipped set, read once

    def test_card_the_set_lacks_is_remembered(self) -> None:
        from unittest import mock
        _, working, normal, _, missing, _, _ = self.run_worker(
            lambda card: self.picture_set(["someone-else"]), mock.MagicMock())
        self.assertTrue(missing and working)
        self.assertIsNone(normal)

    def test_unreadable_set_means_name_tiles(self) -> None:
        from unittest import mock
        _, working, normal, _, missing, _, _ = self.run_worker(lambda card: None, mock.MagicMock())
        self.assertFalse(working)
        self.assertFalse(missing)
        self.assertIsNone(normal)

    def test_damaged_picture_is_not_fatal(self) -> None:
        """Review 2026-09-30: a damaged picture killed the worker for good."""
        from unittest import mock
        decoder = mock.MagicMock(return_value=mock.MagicMock(decode=lambda d: (8, 8, bytes(192))))

        def damaged(card):
            data = bytearray(self.picture_set([card.guid]))
            data[data.find(b"webp bytes")] ^= 1  # one flipped bit: Bad CRC
            return bytes(data)
        _, working, normal, _, _, _, _ = self.run_worker(damaged, decoder)
        self.assertFalse(working)  # name tiles, and it says so in the log file
        self.assertIsNone(normal)

    def test_shipped_set_is_in_the_world(self) -> None:
        """The real zip is in the apworld and holds a picture for most shop cards."""
        import io
        import pkgutil
        import zipfile
        from .. import cardart
        names = set(zipfile.ZipFile(io.BytesIO(pkgutil.get_data(cardart.__package__, "data/card-art.zip"))).namelist())
        shop = [c for c in CARDS if c.shop]
        self.assertGreater(sum(f"{c.guid}.webp" in names for c in shop), len(shop) * 0.9)

    def test_pictures_from_older_sources_are_cleared(self) -> None:
        from unittest import mock
        from ..cardart import ART_SET
        *_, left = self.run_worker(lambda card: self.picture_set([]), mock.MagicMock(),
                                   old_files=("abc_48x96.png", "abc.missing"))
        self.assertEqual(left, [ART_SET])

    def test_no_sdl2_means_name_tiles(self) -> None:
        from unittest import mock
        _, working, normal, _, _, downloads, _ = self.run_worker(mock.MagicMock(),
                                                                 mock.MagicMock(side_effect=OSError("x")))
        self.assertEqual(downloads, [])  # nothing downloaded that couldn't be shown
        self.assertFalse(working)
        self.assertIsNone(normal)


class TestEveryItemHasRealArt(unittest.TestCase):
    """2026-11-12 (owner: "images are not loading correctly for a number of items, they just show a blank color"):
    12 pictures in card-art.zip were tier-coloured boxes from a source whose images had failed. Every card must
    have a picture, and none may be blank (tools/make_card_art.blank - the one rule, also used when adding)."""

    def test_every_item_has_a_picture_and_none_is_blank(self) -> None:
        import io
        import os
        import sys
        import zipfile
        try:
            from PIL import Image, ImageChops
        except ImportError:
            self.skipTest("Pillow is only needed to check the art set (a developer's machine)")
        tools = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "tools")  # past the junction
        if not os.path.isfile(os.path.join(tools, "make_card_art.py")):
            self.skipTest("the art tools aren't here (an installed apworld)")
        sys.path.insert(0, tools)
        try:
            from make_card_art import blank
        finally:
            sys.path.remove(tools)
        from ..items import ENCOUNTER_UNLOCKS, EVENT_RARITY_ID, HERO_ITEM_IDS, UNLOCKS, item_name_to_id
        data = os.path.join(os.path.dirname(__file__), "..", "data")
        art = zipfile.ZipFile(os.path.join(data, "card-art.zip"))
        names = set(art.namelist())
        # owner 2026-11-12: pictures for ALL unlockables - each item's own picture(s), or a generic symbol
        without = []
        for name, item in item_name_to_id.items():
            if item in HERO_ITEM_IDS:
                hero = HERO_ITEM_IDS[item].lower().replace(" ", "_")
                ok = os.path.isfile(os.path.join(data, "heroes", f"{hero}.png"))
            elif item in ENCOUNTER_UNLOCKS or item in UNLOCKS:  # merchants, events, level-ups; cards, packs, groups
                ok = all(f"{guid}.webp" in names for guid in ENCOUNTER_UNLOCKS.get(item) or UNLOCKS[item])
            elif item == EVENT_RARITY_ID:  # its events, each pictured above
                ok = True
            else:  # no card behind it: its symbol (tools/make_item_symbols.py)
                ok = f"item-{item}.webp" in names
            if not ok:
                without.append(name)
        self.assertEqual(without, [])
        # owner 2026-11-12: "dont publish 'every single photo' online, just the ones we use" - nothing else ships
        used = {f"{guid}.webp" for guids in list(ENCOUNTER_UNLOCKS.values()) + list(UNLOCKS.values()) for guid in guids}
        used |= {f"item-{item}.webp" for item in item_name_to_id.values()}
        # owner 2026-11-13: each rarity's frame, for cards of every size and for merchants/events (cardart.FRAMES)
        from ..cardart import FRAMES
        from ..data import TIERS
        used |= {f"frame-{tier}-{kind}.webp" for tier in TIERS for kind in FRAMES}
        self.assertEqual(sorted(names - used), [])
        # (a frame is see-through in the middle by design: blank() is for pictures)
        self.assertEqual([n for n in sorted(names) if not n.startswith("frame-")
                          and blank(Image.open(io.BytesIO(art.read(n))))], [])
        # owner 2026-11-12 ("the icon in the middle is small and sitting on the top left corner"): a symbol's icon
        # sits in the middle of its tile and fills it (drawn on make_item_symbols' fixed grid, whatever the size)
        cramped = []
        for name in sorted(n for n in names if n.startswith("item-")):
            picture = Image.open(io.BytesIO(art.read(name))).convert("RGB")
            size = picture.width
            inside = picture.crop((size // 8, size // 8, size - size // 8, size - size // 8))  # past the tile's border
            fill = Image.new("RGB", inside.size, inside.getpixel((0, 0)))
            icon = ImageChops.difference(inside, fill).convert("L").point(lambda v: 255 if v > 24 else 0).getbbox()
            middle = ((icon[0] + icon[2]) / 2 / inside.width, (icon[1] + icon[3]) / 2 / inside.height)
            if abs(middle[0] - 0.5) > 0.15 or abs(middle[1] - 0.5) > 0.15 or icon[2] - icon[0] < 0.5 * inside.width:
                cramped.append(name)
        self.assertEqual(cramped, [])


class TestCheckBar(unittest.TestCase):
    """Owner 2026-11-13: the Tracker shows a hero's check progress "similar to the hero guide on the main menu" - one
    bar drawing for both (tracker.check_bar / fill_bar)."""

    class Bar(dict):
        def coords(self, tag, *points):
            self["coords"] = points

    def test_the_bar_fills_by_checks_done_of_all(self) -> None:
        from ..tracker import fill_bar
        bar = self.Bar(width=100, height=6)
        fill_bar(bar, 25, 100)
        self.assertEqual(bar["coords"], (0, 0, 25, 6))
        fill_bar(bar, 0, 0)  # no checks at all: empty, never a division by zero
        self.assertEqual(bar["coords"], (0, 0, 0, 6))
        fill_bar(bar, 7, 7)
        self.assertEqual(bar["coords"], (0, 0, 100, 6))


class TestIconsAreTheSquaresShadow(unittest.TestCase):
    """Owner 2026-11-16: the icon "a shade darker than the background of the squares color and kind of like a shadow
    of what it is supposed to be"; the Sell Trap marker "the skull with flames"."""

    def test_an_icon_is_its_squares_colour_darker_and_see_through_around_it(self) -> None:
        from ..tracker import COLORS, ICON_SHADE, icon_pixels
        width, height, rgba = icon_pixels("win", COLORS["green"], 26)
        self.assertEqual((width, height), (26, 26))
        solid = [rgba[i:i + 3] for i in range(0, len(rgba), 4) if rgba[i + 3] == 255]
        self.assertTrue(solid)  # the trophy is there
        shade = bytes(round(int(COLORS["green"][i:i + 2], 16) * ICON_SHADE) for i in (1, 3, 5))
        self.assertTrue(all(px == shade for px in solid))  # all of it in the square's colour, darker
        self.assertEqual(rgba[3], 0)  # the corner: see-through, the square shows

    def test_every_square_and_the_sell_trap_have_an_icon(self) -> None:
        from ..tracker import SQUARES, icon_pixels
        for kind in [kind for kind, *_ in SQUARES] + ["sell_trap"]:
            self.assertIsNotNone(icon_pixels(kind, "#808080", 20), kind)
        self.assertIsNone(icon_pixels("no such square", "#808080", 20))
