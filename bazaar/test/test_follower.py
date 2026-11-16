import threading
import time
import unittest

from .. import follower
from ..memreader import BoardUI
from ..padlocks import Padlock

WINDOW = (0, 0, 1000, 1000)
AREA = (0, 0, 1000, 1000)


def board(cards: dict, dragging: bool = False) -> BoardUI:
    return BoardUI(False, dragging, False, False, False, cards=cards)


class Recorder:
    def __init__(self) -> None:
        self.moves = []

    def __call__(self, handle: int, x: int, y: int) -> None:
        self.moves.append((handle, x, y))


def place(f: follower.Follower, plan: follower.Plan) -> None:
    """What the follower thread does once woken (Follower.run): the Tk thread hands over, the follower places."""
    f.follow(plan)
    f.step(plan)


class TestFollowerStep(unittest.TestCase):
    """Owner 2026-11-12: padlocks one game frame behind their cards, and cheap - so a window moves only when its card's
    square changed, from where the card is this instant when the reader can say."""

    def plan(self, ui, locks=("a", "b")) -> follower.Plan:
        return follower.Plan(tuple(Padlock(card=c) for c in locks), tuple(range(1, len(locks) + 1)), ui, WINDOW, 40,
                             AREA)

    def test_a_padlock_moves_once_per_new_square_and_not_when_still(self) -> None:
        moves = Recorder()
        f = follower.Follower(lambda: None, moves)
        ui = board({"a": (0.1, 0.1, 0.2, 0.3), "b": (0.5, 0.5, 0.6, 0.7)})
        place(f, self.plan(ui))
        self.assertEqual(moves.moves, [(1, 130, 180), (2, 530, 580)])  # card centres minus half the padlock
        place(f, self.plan(ui))  # the same squares again: nothing moves
        self.assertEqual(len(moves.moves), 2)
        place(f, self.plan(board({"a": (0.2, 0.1, 0.3, 0.3), "b": (0.5, 0.5, 0.6, 0.7)})))
        self.assertEqual(moves.moves[2:], [(1, 230, 180)])  # only the card that moved

    def test_where_the_card_is_now_wins_over_the_board_read(self) -> None:
        moves = Recorder()
        now = {"a": (0.3, 0.1, 0.4, 0.3)}
        f = follower.Follower(lambda: lambda cards: {c: now[c] for c in cards if c in now}, moves)
        place(f, self.plan(board({"a": (0.1, 0.1, 0.2, 0.3)}), ("a",)))
        self.assertEqual(moves.moves, [(1, 330, 180)])

    def test_never_on_a_card_the_board_read_says_is_gone(self) -> None:
        moves = Recorder()
        asked = []
        f = follower.Follower(lambda: lambda cards: asked.append(list(cards)) or {"b": (0.5, 0.5, 0.6, 0.7)}, moves)
        place(f, self.plan(board({"a": (0.1, 0.1, 0.2, 0.3)})))  # b: not placed by the board read (sold, turned)
        self.assertEqual(asked, [["a"]])
        self.assertEqual(moves.moves, [(1, 130, 180)])

    def test_an_older_plan_never_moves_anything(self) -> None:
        moves = Recorder()
        f = follower.Follower(lambda: None, moves)
        old = self.plan(board({"a": (0.1, 0.1, 0.2, 0.3)}), ("a",))
        place(f, self.plan(board({"a": (0.5, 0.1, 0.6, 0.3)}), ("a",)))
        self.assertFalse(f.step(old))
        self.assertEqual(moves.moves, [(1, 530, 180)])


class TestFollowerThread(unittest.TestCase):
    def test_the_tk_thread_never_waits_for_a_move(self) -> None:
        """A window move waits for the Tk thread (it owns the window). The first version had the Tk thread wait for
        the follower in turn - on a shared lock - and the overlay froze in the owner's first try (2026-11-12)."""
        entered, release = threading.Event(), threading.Event()

        def move(_handle, _x, _y):
            entered.set()
            release.wait(2)  # like a move held up until the Tk thread pumps its messages

        f = follower.Follower(lambda: None, move)
        thread = threading.Thread(target=f.run, daemon=True)
        thread.start()
        try:
            plan = follower.Plan((Padlock(card="a"),), (7,), board({"a": (0.1, 0.1, 0.2, 0.3)}), WINDOW, 40, AREA)
            f.follow(plan)
            self.assertTrue(entered.wait(1))
            start = time.perf_counter()
            f.follow(plan._replace(ui=board({"a": (0.3, 0.1, 0.4, 0.3)})))  # the Tk thread, mid-move
            self.assertLess(time.perf_counter() - start, 0.05)
        finally:
            release.set()
            f.stop()
            thread.join(1)

    def test_follows_while_the_card_moves_then_sleeps(self) -> None:
        """Moving: a look every FOLLOW_TICK, each new place moved to. Still for MOVING_SECONDS: asleep, no reads."""
        moves = Recorder()
        reads = []
        place = {"x": 0.1}

        def positions(cards):
            reads.append(time.perf_counter())
            return {"a": (place["x"], 0.1, place["x"] + 0.1, 0.3)}

        f = follower.Follower(lambda: positions, moves)
        thread = threading.Thread(target=f.run, daemon=True)
        thread.start()
        try:
            plan = follower.Plan((Padlock(card="a"),), (7,), board({"a": (0.0, 0.1, 0.1, 0.3)}), WINDOW, 40, AREA)
            for step in range(20):  # the card slides for ~0.1 s
                place["x"] = 0.1 + step * 0.01
                if step == 0:
                    f.follow(plan)
                time.sleep(0.005)
            time.sleep(follower.MOVING_SECONDS + 0.1)
            settled = len(reads)
            time.sleep(0.2)
            self.assertEqual(len(reads), settled, "it kept reading after the card stopped")
            xs = [x for _h, x, _y in moves.moves]
            self.assertGreaterEqual(len(set(xs)), 15, "it missed most of the slide")
            self.assertEqual(xs[-1], round((0.1 + 19 * 0.01 + 0.05) * 1000) - 20)
        finally:
            f.stop()
            thread.join(1)


if __name__ == "__main__":
    unittest.main()
