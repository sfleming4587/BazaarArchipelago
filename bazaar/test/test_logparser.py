import os
import tempfile
import unittest

from ..logparser import CardBought, DayReached, LogParser, LogTailer, RunEnded, RunStarted

GUID = "d4c0cf1e-7856-4e40-877f-c77b34f596ed"


def state(old: str, new: str) -> str:
    return f"[12:00:00.000] [AppState] State changed from [{old}] to [{new}]"


def pvp_day(result: str = "ChoiceState"):
    return [state("ChoiceState", "PVPCombatState"), state("PVPCombatState", "ReplayState"),
            state("ReplayState", result)]


RUN_START = [
    "[12:00:00.000] [RunConfigurationCache] RunConfigurationCache: Changing EHero to Vanessa",
    "[12:00:00.000] [RunConfigurationCache] RunConfigurationCache: Changing EHero to Dooley",
    state("null", "StartRunAppState"),
    state("StartRunAppState", "ChoiceState"),
    "[12:00:00.000] [StartRunAppState] Run initialization finalized.",
]


class TestLogParser(unittest.TestCase):
    def test_full_losing_run(self) -> None:
        lines = RUN_START + pvp_day() + pvp_day() + pvp_day("EndRunDefeatState")
        events = LogParser().feed_all(lines)
        self.assertEqual(events, [RunStarted("Dooley"), DayReached(1), DayReached(2), DayReached(3),
                                  RunEnded(victory=False, day=3)])

    def test_victory(self) -> None:
        lines = RUN_START + pvp_day("EndRunVictoryState")
        self.assertEqual(LogParser().feed_all(lines)[-1], RunEnded(victory=True, day=1))

    def test_pve_fight_does_not_advance_day(self) -> None:
        lines = RUN_START + [state("ChoiceState", "CombatState"), state("CombatState", "ReplayState"),
                             state("ReplayState", "LootState")]
        self.assertEqual(LogParser().feed_all(lines), [RunStarted("Dooley"), DayReached(1)])

    def test_purchases(self) -> None:
        buy = (f"[12:00:00.000] [BoardManager] Card Purchased: InstanceId: itm_Q0TQQjd - TemplateId{GUID} - "
               "Target:PlayerSocket_3 - SectionPlayer")
        encounter = ("[12:00:00.000] [BoardManager] Card Purchased: InstanceId: enc_CRcYdZa - "
                     f"TemplateId{GUID} - Target:OpponentSocket_5 - SectionOpponent")
        events = LogParser().feed_all(RUN_START + [buy, encounter])
        self.assertEqual([e for e in events if isinstance(e, CardBought)], [CardBought(GUID)])

    def test_nothing_outside_a_run(self) -> None:
        self.assertEqual(LogParser().feed_all(pvp_day("EndRunDefeatState")), [])

    def test_hero_alias(self) -> None:
        lines = ["[x] [RunConfigurationCache] RunConfigurationCache: Changing EHero to Pyg",
                 "[x] [StartRunAppState] Run initialization finalized."]
        self.assertEqual(LogParser().feed_all(lines)[0], RunStarted("Pygmalien"))


class TestLogTailer(unittest.TestCase):
    def test_partial_lines_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Player.log")
            tailer = LogTailer(path)
            self.assertEqual(tailer.read_new_lines(), [])
            with open(path, "wb") as f:
                f.write(b"\xef\xbb\xbfline one\r\nline t")
            self.assertEqual(tailer.read_new_lines(), ["line one"])
            with open(path, "ab") as f:
                f.write(b"wo\n")
            self.assertEqual(tailer.read_new_lines(), ["line two"])
            with open(path, "wb") as f:  # game restarted: log truncated
                f.write(b"new\n")
            self.assertIsNone(tailer.read_new_lines())
            self.assertEqual(tailer.read_new_lines(), ["new"])
