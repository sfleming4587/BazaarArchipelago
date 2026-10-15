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
        with mock.patch.object(Reader, "_get", lambda self, obj, name: fields[name]),                 mock.patch.object(Reader, "_stat", return_value=7), mock.patch.object(Reader, "_container", return_value=()):
            snapshot = reader.snapshot()
        self.assertEqual((snapshot.level, snapshot.losses, snapshot.prestige), (7, None, 7))


class TestGameRunsAsAdministrator(unittest.TestCase):
    """The Tempo launcher starts the game as administrator (verified 2026-10-07): Windows refuses to let the client
    read it, which used to look like a game that's "still loading" forever."""

    def attach(self, refused: bool) -> None:
        with mock.patch.object(memreader, "game_pid", return_value=42), \
                mock.patch.object(memreader, "needs_admin", return_value=refused), \
                mock.patch.object(memreader, "find_module", return_value=None), \
                mock.patch.object(memreader.sys, "platform", "win32"):
            Reader().attach()

    def test_a_refused_game_asks_for_administrator_not_still_loading(self) -> None:
        with self.assertRaises(memreader.NeedsAdmin):
            self.attach(refused=True)

    def test_a_readable_game_without_mono_yet_is_still_loading(self) -> None:
        with self.assertRaises(NotReady) as caught:
            self.attach(refused=False)
        self.assertNotIsInstance(caught.exception, memreader.NeedsAdmin)


class TestBoardFlagsFoundAfterTheMenu(unittest.TestCase):
    """2026-10-14, watched live: attached at the main menu, the board's classes aren't set up yet, so its on-screen
    flags couldn't be learned - and weren't tried again until the game restarted (no stash padlocks, padlocks inside
    the loading screen). They're learned once a run's board has loaded."""

    def reader(self, learned) -> Reader:
        reader = Reader()
        reader.memory, reader.mono, reader.ui_paths, reader.prefs_path = mock.Mock(), mock.Mock(), None, None
        reader.ui_learn, reader.ui_tried = ("data", "base", {}), 100.0
        reader._learn_ui = mock.Mock(side_effect=learned)
        reader._learn_prefs = mock.Mock(return_value=7)
        return reader

    def test_tried_again_once_a_second_until_found_then_kept(self) -> None:
        paths = {"statics": {}, "drag": 0}
        reader = self.reader([None, paths])
        with mock.patch.object(memreader.time, "monotonic", return_value=100.5):
            reader.ui()
        self.assertEqual(reader._learn_ui.call_count, 0)  # not every read: once a second
        with mock.patch.object(memreader.time, "monotonic", return_value=101.0):
            reader.ui()
        with mock.patch.object(memreader.time, "monotonic", return_value=102.0), \
                mock.patch.object(Reader, "_get", return_value=0):
            reader.ui()
        self.assertEqual(reader._learn_ui.call_count, 2)
        self.assertIs(reader.ui_paths, paths)
        self.assertEqual(reader.prefs_path, 7)  # the hero preferences need the same thing
        with mock.patch.object(memreader.time, "monotonic", return_value=110.0), \
                mock.patch.object(Reader, "_get", return_value=0):
            reader.ui()
        self.assertEqual(reader._learn_ui.call_count, 2)  # found: never looked for again

    def test_the_class_search_runs_once(self) -> None:
        """Searching every class takes ~150 ms; ui() runs on the client's event loop."""
        reader = Reader()
        reader.mono, reader.memory, reader.ui_classes = mock.Mock(), mock.Mock(), ()
        reader.mono.find_class.side_effect = [1, 2]
        reader.mono.learn_static_blocks.return_value = False
        reader.mono.fields.return_value = []
        for _ in range(3):
            self.assertIsNone(reader._learn_ui(0, 0, {}))
        self.assertEqual(reader.mono.find_class.call_count, 2)


class TestInputManagerReplaced(unittest.TestCase):
    """2026-10-14, watched: when a run ends the game replaces its input manager; kept "until the game restarts", the
    hero panel no longer hid under the game's screens on the menu. A gone one is searched for again."""

    def test_a_gone_input_manager_is_found_again(self) -> None:
        reader = Reader()
        reader.memory, reader.mono = mock.Mock(), mock.Mock()
        reader.input_class, reader.input_manager, reader.input_searched = 77, 111, 0.0
        reader.mono.klass.side_effect = lambda obj: {111: 99, 222: 77}.get(obj, 55)  # 111 freed: not the class
        reader.mono.find_class.return_value = 77
        reader.mono.name.return_value = "InputContextStack"
        reader.mono.off = {"class_runtime_info": 0}
        reader.memory.find_pointer.return_value = [222]
        reader.memory.ptr.return_value = 1  # the class's vtable, whatever it is
        fields = {(222, "Context"): 5, (5, "_stack"): 6, (6, "_size"): 1}
        with mock.patch.object(Reader, "_get", lambda self, obj, name: fields.get((obj, name), 0)), \
                mock.patch.object(memreader.time, "monotonic", return_value=1000.0):
            self.assertEqual(reader.menu_layers(), 1)
        self.assertEqual(reader.input_manager, 222)


class TestSnapshotGrace(unittest.TestCase):
    """2026-10-14 sweep: a reading caught half-made at a run's end turned the reader off for the whole session
    (the class of the input manager bug). Failures read as "no screen" while they last under SNAPSHOT_GRACE."""

    def test_a_passing_failure_is_no_screen_and_a_lasting_one_turns_the_reader_off(self) -> None:
        reader = Reader()
        reader.memory = mock.Mock()
        with mock.patch.object(Reader, "_snapshot", side_effect=KeyError("half-made")):
            with mock.patch.object(memreader.time, "monotonic", return_value=100.0):
                self.assertEqual(reader.snapshot(), memreader.Snapshot(None, None, ()))
            with mock.patch.object(memreader.time, "monotonic", return_value=100.0 + memreader.SNAPSHOT_GRACE - 1):
                self.assertEqual(reader.snapshot(), memreader.Snapshot(None, None, ()))
            with mock.patch.object(memreader.time, "monotonic", return_value=100.0 + memreader.SNAPSHOT_GRACE + 1):
                with self.assertRaises(ReaderOff):
                    reader.snapshot()

    def test_a_good_reading_resets_the_clock(self) -> None:
        reader = Reader()
        reader.memory = mock.Mock()
        good = memreader.Snapshot("Encounter", None, ())
        with mock.patch.object(memreader.time, "monotonic", return_value=100.0), \
                mock.patch.object(Reader, "_snapshot", side_effect=KeyError("half-made")):
            reader.snapshot()
        with mock.patch.object(Reader, "_snapshot", return_value=good):
            self.assertEqual(reader.snapshot(), good)
        with mock.patch.object(memreader.time, "monotonic", return_value=100.0 + memreader.SNAPSHOT_GRACE + 1), \
                mock.patch.object(Reader, "_snapshot", side_effect=KeyError("half-made")):
            self.assertEqual(reader.snapshot(), memreader.Snapshot(None, None, ()))  # a new failure, a new grace


class TestFieldLookupsAreRemembered(unittest.TestCase):
    """2026-10-15: one board read took 4-6 ms (3 cards), mostly re-walking class chains; a 144 Hz frame is 6.9 ms."""

    def mono(self, walked):
        mono = memreader.Mono.__new__(memreader.Mono)
        mono.field_index = {}
        mono.fields = lambda c: walked.append(c) or ([("Rig", 0x18, False, 0x12, 0)] if c == 2 else [])
        mono.parent = lambda c: 2 if c == 1 else 0
        return mono

    def test_a_field_is_found_through_the_parents_once(self) -> None:
        walked = []
        mono = self.mono(walked)
        for _ in range(3):
            self.assertEqual(mono.field(1, "Rig"), (0x18, 0x12, 0))
        self.assertEqual(walked, [1, 2])

    def test_a_blocked_name_is_still_refused(self) -> None:
        mono = self.mono([])
        mono.field_index[1, "opponentItemSockets"] = (0x18, 0x12, 0)
        with self.assertRaises(ReaderOff):
            mono.field(1, "opponentItemSockets")


class TestBoardReadFetchesBlocks(unittest.TestCase):
    """2026-10-15: a board read made ~50 calls into Windows per card (0.7 ms a card); a 144 Hz frame is 6.9 ms."""

    def setUp(self) -> None:
        patcher = mock.patch.object(memreader, "READ_BLOCK", 256)  # small blocks keep the made-up memory short
        patcher.start()
        self.addCleanup(patcher.stop)

    def memory(self, fetched, unreadable=()):
        memory = memreader.Memory.__new__(memreader.Memory)
        memory.blocks = None
        game = bytes(range(256)) * 4  # addresses 0x10000.. hold these bytes

        def fetch(address, size):
            fetched.append((address, size))
            if any(address <= u < address + size for u in unreadable):
                return None
            start = address - 0x10000
            return game[start:start + size]
        memory._fetch = fetch
        return memory

    def test_reads_in_one_block_fetch_it_once_and_give_the_same_bytes(self) -> None:
        fetched = []
        memory = self.memory(fetched)
        memory.blocks = {}
        self.assertEqual(memory.read(0x10008, 8), bytes(range(8, 16)))
        self.assertEqual(memory.read(0x100F8, 8), bytes(range(0xF8, 0x100)))
        self.assertEqual(fetched, [(0x10000, 256)])

    def test_a_read_across_two_blocks_or_out_of_one_unreadable_is_fetched_as_asked(self) -> None:
        fetched = []
        memory = self.memory(fetched, unreadable=(0x10180,))
        memory.blocks = {}
        self.assertEqual(memory.read(0x100FC, 8), bytes([0xFC, 0xFD, 0xFE, 0xFF, 0, 1, 2, 3]))
        self.assertEqual(memory.read(0x10108, 4), bytes(range(8, 12)))  # its block can't be read whole: as asked
        self.assertEqual(fetched, [(0x100FC, 8), (0x10100, 256), (0x10108, 4)])

    def test_off_outside_a_board_read(self) -> None:
        fetched = []
        memory = self.memory(fetched)
        memory.read(0x10008, 8)
        memory.read(0x10008, 8)
        self.assertEqual(fetched, [(0x10008, 8)] * 2)  # live values every time
