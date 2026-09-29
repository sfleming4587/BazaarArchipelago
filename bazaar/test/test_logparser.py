import os
import tempfile
import unittest

from ..logparser import (CardGained, CardSold, DayReached, EncounterEntered, EncounterLeft, FightStarted, HeroSelected,
                         LogParser,
                         MonsterFought, PvPFought, GameVersion, UnrecognizedRun,
                         LogTailer, RunEnded, RunStarted)

GUID = "d4c0cf1e-7856-4e40-877f-c77b34f596ed"


def run_events(lines):
    """Events without the hero-select screen's picks (tested on their own)."""
    return [e for e in LogParser().feed_all(lines) if not isinstance(e, HeroSelected)]


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
        events = [e for e in run_events(lines) if not isinstance(e, FightStarted)]
        self.assertEqual(events, [RunStarted("Dooley"), DayReached(1), PvPFought(1, False), DayReached(2),
                                  PvPFought(2, False), DayReached(3), PvPFought(3, False),
                                  RunEnded(victory=False, day=3)])

    def test_monster_fights(self) -> None:
        monster = "33333333-3333-3333-3333-333333333333"

        def fight(result: str, picked: bool = True) -> list:
            pick = [f"[x] [BoardManager] Card Purchased: InstanceId: com_abc - TemplateId{monster} - "
                    "Target:OpponentSocket_5 - SectionOpponent"] if picked else []
            return [state("ChoiceState", "CombatState"), *pick, state("CombatState", "ReplayState"),
                    state("ReplayState", result)]

        lines = RUN_START + fight("LootState") + fight("ChoiceState") + fight("LootState", picked=False)
        events = [e for e in LogParser().feed_all(lines) if isinstance(e, MonsterFought)]
        # the third fight came from an event (no hour-3 monster pick), so it doesn't count
        self.assertEqual(events, [MonsterFought(monster, 1, True), MonsterFought(monster, 1, False)])

    def test_victory(self) -> None:
        lines = RUN_START + pvp_day("EndRunVictoryState")
        self.assertEqual(LogParser().feed_all(lines)[-1], RunEnded(victory=True, day=1))

    def test_pve_fight_does_not_advance_day(self) -> None:
        lines = RUN_START + [state("ChoiceState", "CombatState"), state("CombatState", "ReplayState"),
                             state("ReplayState", "LootState")]
        self.assertEqual(run_events(lines), [RunStarted("Dooley"), DayReached(1), FightStarted(pvp=False)])

    def test_gains_bought_vs_reward(self) -> None:
        merchant, event = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"

        def pick(guid: str) -> str:
            return (f"[x] [BoardManager] Card Purchased: InstanceId: enc_abc - TemplateId{guid} - "
                    "Target:OpponentSocket_5 - SectionOpponent")

        def gain(instance: str) -> str:
            return (f"[x] [BoardManager] Card Purchased: InstanceId: {instance} - TemplateId{GUID} - "
                    "Target:PlayerSocket_3 - SectionPlayer")

        lines = RUN_START + [
            pick(merchant), state("ChoiceState", "EncounterState"), gain("itm_a"), state("EncounterState", "ChoiceState"),
            pick(event), state("ChoiceState", "EncounterState"), gain("itm_b"),
            state("ChoiceState", "LootState"), gain("itm_c"),
            "[x] [NetworkManager] [HttpGameClient] Command completed: type=SellCardCommand, requestId=9",
            "[x] [BoardManager] Sold Card itm_c for 1 gold.",
        ]
        events = [e for e in LogParser([merchant]).feed_all(lines) if isinstance(e, (CardGained, CardSold))]
        self.assertEqual(events, [CardGained(GUID, "itm_a", True), CardGained(GUID, "itm_b", False),
                                  CardGained(GUID, "itm_c", False), CardSold("itm_c")])

    def test_encounter_enter_and_leave(self) -> None:
        shop = "11111111-1111-1111-1111-111111111111"
        lines = RUN_START + [state("ChoiceState", "EncounterState"),
                             f"[x] [BoardManager] Card Purchased: InstanceId: enc_abc - TemplateId{shop} - "
                             "Target:OpponentSocket_5 - SectionOpponent",
                             state("EncounterState", "ChoiceState")]
        events = [e for e in LogParser().feed_all(lines) if isinstance(e, (EncounterEntered, EncounterLeft))]
        self.assertEqual(events, [EncounterEntered(shop), EncounterLeft()])

    def test_level_up_step_enter_and_leave(self) -> None:
        step = "44444444-4444-4444-4444-444444444444"
        lines = RUN_START + [state("EncounterState", "LevelUpState"),
                             f"[x] [BoardManager] Card Purchased: InstanceId: ste_abc - TemplateId{step} - "
                             "Target:OpponentSocket_5 - SectionOpponent",
                             state("LevelUpState", "ChoiceState")]
        events = [e for e in LogParser().feed_all(lines) if isinstance(e, (EncounterEntered, EncounterLeft))]
        # leaving the event that triggered the level-up closes its warning first
        self.assertEqual(events, [EncounterLeft(), EncounterEntered(step), EncounterLeft()])

    def test_fight_without_a_recognised_run_start_is_reported_once(self) -> None:
        # e.g. a patch renamed the run-start line: nothing counts, but the client can say why
        events = LogParser().feed_all(pvp_day("EndRunDefeatState") + pvp_day())
        self.assertEqual(events, [UnrecognizedRun()])

    def test_concede_and_version(self) -> None:
        lines = ["[x] [VersionShow]  Version: 1.0.12293-prod-windows-x64-a0455053 ", *RUN_START,
                 "[x] [NetworkManager] [HttpGameClient] Command completed: type=AbandonRunCommand, requestId=25",
                 state("ChoiceState", "EndRunDefeatState")]
        events = LogParser().feed_all(lines)
        self.assertEqual(events[0], GameVersion("1.0.12293"))
        self.assertEqual(events[-1], RunEnded(victory=False, day=1, conceded=True))

    def test_hero_picks_outside_a_run_only(self) -> None:
        pick = "[x] [RunConfigurationCache] RunConfigurationCache: Changing EHero to {}"
        lines = [pick.format("Vanessa"), pick.format("Hero8"), "[x] [StartRunAppState] Run initialization finalized.",
                 pick.format("Dooley")]
        picks = [e for e in LogParser().feed_all(lines) if isinstance(e, HeroSelected)]
        self.assertEqual(picks, [HeroSelected("Vanessa"), HeroSelected("The Dragons")])

    def test_dragons(self) -> None:
        lines = ["[x] [RunConfigurationCache] RunConfigurationCache: Changing EHero to Hero8",
                 "[x] [StartRunAppState] Run initialization finalized."]
        self.assertEqual(run_events(lines)[0], RunStarted("The Dragons"))

    def test_hero_alias(self) -> None:
        lines = ["[x] [RunConfigurationCache] RunConfigurationCache: Changing EHero to Pyg",
                 "[x] [StartRunAppState] Run initialization finalized."]
        self.assertEqual(run_events(lines)[0], RunStarted("Pygmalien"))


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
