import struct
import unittest

from .. import unity

# The game's camera, read live 2026-10-14 (CardController.mainCamera): world -> clip, column-major.
MATRIX = (3.361368, 0.0, 0.0, 0.0, 0.0, -1e-06, -1.01005, -1.0, 0.0, 5.975765, -0.0, -0.0, 0.0, -0.6573, 47.374371,
          47.500004)


class Arena:
    """A fake process memory: structs laid out at addresses, read like the game's."""

    def __init__(self) -> None:
        self.data, self.next = {}, 0x1000

    def put(self, raw: bytes) -> int:
        address, self.next = self.next, self.next + ((len(raw) + 0x200) // 0x100) * 0x100
        self.data[address] = raw
        return address

    def read(self, address: int, size: int):
        for start, raw in self.data.items():
            if start <= address and address + size <= start + len(raw):
                return raw[address - start:address - start + size]
        return None

    def transform(self, parents, locals_, index: int) -> int:
        """A Transform at `index` of a hierarchy with these parent indices and local (pos, rot, scale) entries."""
        local = self.put(b"".join(struct.pack("<12f", *p, 0, *q, *s, 0) for p, q, s in locals_))
        parent = self.put(struct.pack(f"<{len(parents)}i", *parents))
        table = self.put(bytes(8 * len(parents)))
        hierarchy = self.put(bytes(0x18) + struct.pack("<QQQQ", local, parent, 0, table))
        return self.put(bytes(0x28) + struct.pack("<Qi", hierarchy, index) + bytes(0xA0))


class TestCardOnScreen(unittest.TestCase):
    def test_a_board_card_lands_inside_its_frame_in_the_screenshot(self) -> None:
        """Pasta, 2026-10-14: the game had its Rig at world (2.46, 0.467, -1.76) and its collider 1.39 x 0.2 x 3.2;
        the owner's screenshot framed the card at x 1073-1185, y 555-780 (the collider is the clickable area, a few
        px inside the gold frame)."""
        arena = Arena()
        rig = arena.transform([-1], [((2.46, 0.467, -1.76), (0, 0, 0, 1), (1, 1, 1))], 0)
        collider = arena.put(bytes(0x60) + struct.pack("<6f", 0.0, -0.007, -0.001, 1.39, 0.2, 3.2))
        left, top, right, bottom = unity.box_rect(arena.read, MATRIX, collider, rig)
        x0, y0, x1, y1 = left * 1920, top * 1080, right * 1920, bottom * 1080
        for got, frame, inside in ((x0, 1073, 1), (x1, 1185, -1), (y0, 555, 1), (y1, 780, -1)):
            self.assertTrue(0 <= (got - frame) * inside <= 10, (got, frame))

    def test_a_child_adds_to_its_parents_place_rotation_and_scale(self) -> None:
        turned = (0, 0, 0.7071068, 0.7071068)  # 90 degrees about z
        pos, _rot, scale = unity.compose([((1, 0, 0), turned, (2, 2, 2)), ((1, 0, 0), (0, 0, 0, 1), (1, 1, 1))])
        self.assertAlmostEqual(pos[0], 1, places=5)
        self.assertAlmostEqual(pos[1], 2, places=5)  # the parent's x axis is turned onto y, and doubled
        self.assertEqual(scale, (2, 2, 2))

    def test_an_unreadable_transform_is_no_place_not_a_wrong_one(self) -> None:
        self.assertIsNone(unity.world(Arena().read, 0x5000))


class TestHierarchy(unittest.TestCase):
    def test_children_are_the_direct_ones_and_stop_at_the_end_of_the_subtree(self) -> None:
        arena = Arena()
        parents = [-1, 0, 1, 0, -1, 4]  # 0 has children 1 and 3 (1 has 2); 4 is another root
        identity = ((0, 0, 0), (0, 0, 0, 1), (1, 1, 1))
        root = arena.transform(parents, [identity] * len(parents), 0)
        hierarchy = unity.ptr(arena.read, root + unity.TRANSFORM_HIERARCHY)
        table = unity.ptr(arena.read, hierarchy + unity.HIERARCHY_TRANSFORMS)
        arena.data[table] = struct.pack("<6Q", 100, 101, 102, 103, 104, 105)
        self.assertEqual(unity.children(arena.read, root), [101, 103])


class TestUiRect(unittest.TestCase):
    def test_a_box_on_the_screen_canvas_counts_from_the_top(self) -> None:
        """Canvas units are its pixels with y up (the tooltip canvas: 3840 x 2160 at scale 0.5 on 1920 x 1080)."""
        arena = Arena()
        box = arena.transform([-1], [((960, 540, 0), (0, 0, 0, 1), (0.5, 0.5, 1))], 0)
        raw = bytearray(arena.data[box])
        raw[unity.RECT_TRANSFORM_RECT:unity.RECT_TRANSFORM_RECT + 16] = struct.pack("<4f", -100, -50, 200, 100)
        arena.data[box] = bytes(raw)
        left, top, right, bottom = unity.ui_rect(arena.read, box, (1920, 1080))
        self.assertEqual(tuple(round(v) for v in (left * 1920, top * 1080, right * 1920, bottom * 1080)),
                         (910, 515, 1010, 565))


class TestFacesCamera(unittest.TestCase):
    """Owner, 2026-10-15: a padlock shows exactly while its card can be seen. The stash opens by flipping the shop's
    panel 180 degrees about x (recorded 2026-10-15: world position, rotation per card every ~20 ms)."""

    def faces(self, pos, rot) -> bool:
        return unity.faces_camera(MATRIX, (pos, rot, (1.0, 1.0, 1.0)))

    def test_your_board_faces_you_and_never_moves(self) -> None:
        self.assertTrue(self.faces((-0.820, 0.467, -1.760), (0.0, 0.0, 0.0, 1.0)))

    def test_shut_the_shop_faces_you_and_the_stash_is_turned_away(self) -> None:
        self.assertTrue(self.faces((3.290, 0.458, 1.725), (0.0, 0.0, 0.0, 1.0)))
        self.assertFalse(self.faces((-5.740, -0.242, 1.725), (-1.0, 0.0, 0.0, 0.0)))

    def test_open_the_stash_faces_you_and_the_shop_is_turned_away(self) -> None:
        self.assertTrue(self.faces((-5.740, 0.458, 1.725), (0.0, 0.0, 0.0, 1.0)))
        self.assertFalse(self.faces((3.290, -0.242, 1.725), (1.0, 0.0, 0.0, 0.0)))

    def test_mid_flip_each_card_shows_until_it_turns_edge_on(self) -> None:
        # t=1.655 s: the shop card has turned 48 degrees (still seen), the stash card is 132 degrees round (not yet)
        self.assertTrue(self.faces((3.290, 0.344, 1.983), (0.404, 0.0, 0.0, 0.915)))
        self.assertFalse(self.faces((-5.740, -0.128, 1.466), (-0.915, 0.0, 0.0, 0.404)))
        # t=1.717 s: past edge-on, they've swapped
        self.assertFalse(self.faces((3.290, -0.155, 1.955), (0.936, 0.0, 0.0, 0.352)))
        self.assertTrue(self.faces((-5.740, 0.371, 1.494), (-0.352, 0.0, 0.0, 0.936)))
