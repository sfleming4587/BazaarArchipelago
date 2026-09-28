import unittest

from ..overlay import letter_columns


class TestLetterColumns(unittest.TestCase):
    def test_small_letters_stack(self) -> None:
        self.assertEqual(letter_columns(["Bass", "amp", "Cymbal"], rows=7), [["A", "amp", "B", "Bass", "C", "Cymbal"]])

    def test_letter_moves_to_next_column_when_full(self) -> None:
        names = ["Anchor", "Apple", "Axe", "Bolas", "Brick", "Bugle"]
        self.assertEqual(letter_columns(names, rows=5),
                         [["A", "Anchor", "Apple", "Axe"], ["B", "Bolas", "Brick", "Bugle"]])

    def test_big_letter_keeps_its_own_column(self) -> None:
        names = [f"S{i}" for i in range(9)] + ["Tail"]
        columns = letter_columns(names, rows=7)
        self.assertEqual(columns[0][0], "S")
        self.assertEqual(len(columns[0]), 10)
        self.assertEqual(columns[1], ["T", "Tail"])


class TestShopGuideWithoutPillow(unittest.TestCase):
    def test_guide_turns_itself_off(self) -> None:
        """Archipelago's Windows installer leaves Pillow out: no pictures means no Shop Guide, alerts still work."""
        import sys
        import tempfile
        import time
        from unittest import mock
        from ..overlay import Overlay
        with mock.patch.dict(sys.modules, {"PIL": None}), tempfile.TemporaryDirectory() as tmp:
            overlay = Overlay(art_cache_dir=tmp)
            for _ in range(40):
                if overlay.shop_guide_unavailable:
                    break
                time.sleep(0.05)
            self.assertTrue(overlay.available)
            self.assertTrue(overlay.shop_guide_unavailable)
            overlay.close()
            overlay.thread.join(timeout=5)
