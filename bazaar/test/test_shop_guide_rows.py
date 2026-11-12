"""Shop Guide rows (owner, 2026-11-10): "Shrink the borders of the cards to a minimum border count of a couple pixels.
DONT SHRINK THE IMAGE JUST THE BORDERS IN BETWEEN THE ROW"; "Think of it similar to how text looks in a book ... if it
is unable then the spaces expand to make the left most word touch the left border and the right most word touch the
right most border"; "make sure it wont break on any edge cases... AKA 0,1 item, etc. all small"."""
import random
import unittest

from ..shop_guide import MIN_GAP, NORMAL_GAP, rows_of

SMALL, MEDIUM, LARGE = 48, 96, 144


def spans(widths, room):
    """Each row's total width, as laid out."""
    out, k = [], 0
    for count, gaps in rows_of(widths, room):
        out.append(sum(widths[k:k + count]) + sum(gaps))
        k += count
    return out


class TestRows(unittest.TestCase):
    def test_nothing_and_one(self) -> None:
        self.assertEqual(rows_of([], 300), [])
        self.assertEqual(rows_of([MEDIUM], 300), [(1, [])])

    def test_three_mediums_fit_where_two_did(self) -> None:
        """The owner's screenshot: about 306 px of room held 2 Medium cards; it holds 3 with smaller gaps."""
        self.assertEqual(rows_of([MEDIUM] * 3, 306), [(3, [9, 9])])  # a last row: 18 px left, under NORMAL_GAP each

    def test_full_rows_touch_both_edges(self) -> None:
        widths = [MEDIUM] * 7
        rows = rows_of(widths, 306)
        self.assertEqual([count for count, _ in rows], [3, 3, 1])
        self.assertEqual(spans(widths, 306)[:2], [306, 306])  # left edge to right edge, like justified text

    def test_last_row_stays_left_with_the_normal_gap(self) -> None:
        self.assertEqual(rows_of([MEDIUM] * 5, 400), [(4, [6, 5, 5]), (1, [])])  # a full row: justified to 400
        self.assertEqual(rows_of([MEDIUM] * 6, 400)[-1], (2, [NORMAL_GAP]))  # not stretched to the right edge

    def test_all_small(self) -> None:
        widths = [SMALL] * 30
        for room in (200, 306, 451, 700):
            rows = rows_of(widths, room)
            self.assertEqual(sum(c for c, _ in rows), 30)
            for total in spans(widths, room)[:-1]:
                self.assertEqual(total, room)

    def test_a_card_wider_than_the_room_gets_its_own_row(self) -> None:
        self.assertEqual(rows_of([SMALL, LARGE, SMALL], 100), [(1, []), (1, []), (1, [])])

    def test_odd_pixels_go_to_the_first_gaps(self) -> None:
        count, gaps = rows_of([SMALL] * 4 + [LARGE], 4 * SMALL + 3 * MIN_GAP + 2)[0]  # 2 px over for 3 gaps
        self.assertEqual((count, gaps), (4, [3, 3, 2]))

    def test_random_rows_never_break(self) -> None:
        rng = random.Random(1110)
        for _ in range(3000):
            widths = [rng.choice((SMALL, MEDIUM, LARGE, rng.randint(40, 160))) for _ in range(rng.randint(0, 25))]
            room = rng.randint(30, 800)
            rows = rows_of(widths, room)
            self.assertEqual(sum(c for c, _ in rows), len(widths))  # every card, once, in order
            totals = spans(widths, room)
            for n, ((count, gaps), total) in enumerate(zip(rows, totals)):
                self.assertEqual(len(gaps), count - 1)
                self.assertTrue(all(g >= MIN_GAP for g in gaps))
                if count > 1:
                    self.assertLessEqual(total, room)  # only a lone over-wide card may pass the edge
                    if n < len(rows) - 1:
                        self.assertEqual(total, room)
                    else:
                        self.assertTrue(all(g <= NORMAL_GAP for g in gaps))
            # greedy: a row could not have taken the next row's first card even at MIN_GAP
            k = 0
            for count, _ in rows[:-1]:
                row = widths[k:k + count]
                self.assertGreater(sum(row) + widths[k + count] + MIN_GAP * count, room)
                k += count


class TestRealWindow(unittest.TestCase):
    """Drawn in a real guide: nothing spills past the room, and every name fits its cell (cells measured, not
    guessed: 159 names have a word wider than a Small card, 2026-11-10)."""
    def test_rows_touch_both_edges(self) -> None:
        import tempfile
        import tkinter

        from ..data import CARDS
        from ..shop_guide import ROW_PAD, ShopGuide
        cards = [c for c in CARDS if c.shop][:40]  # mixed sizes and long names
        root = tkinter.Tk()
        try:
            guide = ShopGuide.create(tkinter, root, tempfile.mkdtemp(), None, (0, 0, 330, 600),
                                     on_art=lambda guid: None, on_closed=lambda: None)
            canvas = guide.canvas
            for width in (330, 251, 418):
                guide.width = width
                canvas.delete("all")
                guide.cells = {}
                bottom = guide.draw_section(0, "Test", "#ffffff", cards, framed=False)
                root.update()
                self.assertGreater(bottom, 0)
                rows = {}
                for (guid, _locked), places in guide.cells.items():
                    for tag, _x, top in places:
                        x0, _y0, x1, _y1 = canvas.bbox(tag)
                        self.assertGreaterEqual(x0, ROW_PAD - 1, (width, guid))
                        self.assertLessEqual(x1, width - ROW_PAD + 1, (width, guid))
                        rows.setdefault(top, []).append((x0, x1))
                tops = sorted(rows)
                self.assertGreater(len(tops), 1)
                for top in tops[:-1]:  # a full row spans the room: its first cell at the left, its last at the right
                    if len(rows[top]) > 1:
                        self.assertLessEqual(min(x0 for x0, _ in rows[top]), ROW_PAD + 8, (width, top))
                        self.assertGreaterEqual(max(x1 for _, x1 in rows[top]), width - ROW_PAD - 8, (width, top))
            guide.shutdown()
        finally:
            root.destroy()
