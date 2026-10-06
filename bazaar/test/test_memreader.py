import unittest
from unittest import mock

from .. import memreader
from ..memreader import NoAssemblies, NotReady, Reader, ReaderOff


class TestLoadingGame(unittest.TestCase):
    """2026-10-01: twice the reader looked a few seconds after launch, found no assembly list and switched off for
    the whole session. Soon after the first look at a game that's "still loading"; only later is it a failed check."""

    def attach(self, now: float, error: Exception = NoAssemblies("no list")) -> None:
        with mock.patch.object(memreader, "game_pid", return_value=42), \
                mock.patch.object(memreader, "find_module", return_value=(1, 2)), \
                mock.patch.object(memreader, "Memory"), \
                mock.patch.object(memreader, "Mono", side_effect=error), \
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

    def test_any_failed_check_right_after_launch_is_still_loading(self) -> None:
        """2026-10-02: "MonoImage.class_cache not found" 5 s after launch turned the reader off for the session;
        it attached fine once the game had loaded."""
        for error in (ReaderOff("MonoImage.class_cache not found"), ValueError("half-written")):
            self.reader = Reader()
            with self.assertRaises(NotReady):
                self.attach(1000, error)
            with self.assertRaises(ReaderOff) as caught:
                self.attach(1000 + memreader.LOADING_SECONDS + 1, error)
            self.assertNotIsInstance(caught.exception, NotReady)


class TestRunTornDown(unittest.TestCase):
    """2026-10-02 (and a friend's v0.9.0 game): "field Attributes not found" 8 s after a concede switched the reader
    off for the session - padlocks were gone until the client restarted."""

    def test_a_run_mid_change_reads_as_no_level_and_stash_not_a_failed_check(self) -> None:
        reader = Reader()
        reader.memory, reader.mono = mock.Mock(), mock.Mock()
        reader.statics = {"<CurrentState>k__BackingField": 1, "<Run>k__BackingField": 2}
        reader.memory.ptr.return_value = 1
        reader.mono.is_a.return_value = True
        fields = {"StateName": "Encounter", "CurrentEncounterId": "guid", "SelectionSet": 0}
        with mock.patch.object(Reader, "_get", lambda self, obj, name: fields[name]),                 mock.patch.object(Reader, "_stat", side_effect=ReaderOff("field Attributes not found")):
            snapshot = reader.snapshot()
        self.assertEqual(snapshot, memreader.Snapshot("Encounter", "guid", (), None, ()))

    def test_a_losses_read_failure_keeps_level_and_stash(self) -> None:
        """Review 2026-10-06: a patch renaming Run.Losses must only cost the DeathLink-on-loss."""
        reader = Reader()
        reader.memory, reader.mono = mock.Mock(), mock.Mock()
        reader.statics = {"<CurrentState>k__BackingField": 1, "<Run>k__BackingField": 2}
        reader.memory.ptr.return_value = 1
        reader.mono.is_a.return_value = True
        fields = {"StateName": "Encounter", "CurrentEncounterId": "guid", "SelectionSet": 0}
        with mock.patch.object(Reader, "_get", lambda self, obj, name: fields[name]),                 mock.patch.object(Reader, "_stat", return_value=7), mock.patch.object(Reader, "_stash", return_value=()):
            snapshot = reader.snapshot()
        self.assertEqual((snapshot.level, snapshot.losses, snapshot.prestige), (7, None, 7))
