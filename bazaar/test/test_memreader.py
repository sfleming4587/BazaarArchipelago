import unittest
from unittest import mock

from .. import memreader
from ..memreader import NoAssemblies, NotReady, Reader, ReaderOff


class TestLoadingGame(unittest.TestCase):
    """2026-10-01: twice the reader looked a few seconds after launch, found no assembly list and switched off for
    the whole session. Soon after the first look at a game that's "still loading"; only later is it a failed check."""

    def attach(self, now: float) -> None:
        with mock.patch.object(memreader, "game_pid", return_value=42), \
                mock.patch.object(memreader, "find_module", return_value=(1, 2)), \
                mock.patch.object(memreader, "Memory"), \
                mock.patch.object(memreader, "Mono", side_effect=NoAssemblies("no list")), \
                mock.patch.object(memreader.time, "monotonic", return_value=now), \
                mock.patch.object(memreader.sys, "platform", "win32"):
            self.reader.attach()

    def setUp(self) -> None:
        self.reader = Reader()

    def test_a_missing_list_right_after_launch_is_still_loading(self) -> None:
        with self.assertRaises(NotReady):
            self.attach(1000)
        with self.assertRaises(NotReady):
            self.attach(1000 + memreader.LOADING_SECONDS - 1)

    def test_a_list_still_missing_long_after_is_a_failed_check(self) -> None:
        with self.assertRaises(NotReady):
            self.attach(1000)
        with self.assertRaises(ReaderOff) as caught:
            self.attach(1000 + memreader.LOADING_SECONDS + 1)
        self.assertNotIsInstance(caught.exception, NotReady)
