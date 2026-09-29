import asyncio
import os
import tempfile
import unittest
from unittest import mock

from NetUtils import NetworkItem, NetworkSlot, SlotType

from ..client import BazaarContext, catch_up, dispatch
from ..data import CARDS
from ..items import BASE_ID, GAME, item_name_to_id
from ..locations import day_location, location_name_to_id, monster_location, win_location
from ..logparser import (CardGained, CardSold, DayReached, HeroSelected, LogParser, MonsterFought, PvPFought,
                         RunEnded, RunStarted)

LOCKED = next(c for c in CARDS if c.shop and c.hero == "Vanessa")
BRONZE_MONSTER = "bb1e3506-3735-4669-be90-915a55a7ee05"  # Fanged Inglet


class ClientTestBase(unittest.TestCase):
    heroes_owned = ("Vanessa",)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch("Utils.user_path", lambda *parts: os.path.join(self.tmp.name, *parts))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.loop = asyncio.new_event_loop()  # CommonContext starts background tasks, so it needs a running loop
        self.addCleanup(self.close_loop)

        async def make() -> BazaarContext:
            return BazaarContext()
        self.ctx = self.loop.run_until_complete(make())
        self.ctx.slot_data = {"heroes": ["Vanessa", "Dooley"], "max_day": 15, "heroes_required": 2,
                              "pvp_win_checks": True, "lock_items": [BASE_ID + LOCKED.ap_id],
                              "monster_tiers": {str(d): ["Bronze", "Silver"] for d in range(1, 16)}}
        self.ctx.items_received = [NetworkItem(item_name_to_id[f"Hero: {h}"], 0, 0, 0) for h in self.heroes_owned]
        self.sent: set = set()

        async def fake_check(ids):
            self.sent |= set(ids)
            return set(ids)
        self.ctx.check_locations = fake_check
        self.ctx.send_msgs = mock.AsyncMock()
        self.parser = LogParser()

    def close_loop(self) -> None:
        for task in asyncio.all_tasks(self.loop):
            task.cancel()
        self.loop.run_until_complete(asyncio.sleep(0))
        self.loop.close()

    def await_(self, coroutine):
        return self.loop.run_until_complete(coroutine)

    def play(self, *events) -> None:
        async def run():
            for event in events:
                await dispatch(self.ctx, event, self.parser, first_run_in_log=False)
        self.await_(run())

    def was_sent(self, name: str) -> bool:
        return location_name_to_id[name] in self.sent


class TestBlocking(ClientTestBase):
    def test_holding_a_locked_card_blocks_checks_until_sold(self) -> None:
        self.play(RunStarted("Vanessa"), DayReached(1), CardGained(LOCKED.guid, "itm_x", False), DayReached(2),
                  MonsterFought(BRONZE_MONSTER, 2, True))
        self.assertTrue(self.was_sent(day_location("Vanessa", 1)))
        self.assertFalse(self.was_sent(day_location("Vanessa", 2)))
        self.assertFalse(self.was_sent(monster_location("Vanessa", 2, "Bronze")))
        self.assertIn("UNTIL", self.ctx.blocked_reason())

        self.play(CardSold("itm_x"), DayReached(3))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertTrue(self.was_sent(day_location("Vanessa", 3)))

    def test_victory_while_holding_sends_nothing(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", False), PvPFought(10, True),
                  RunEnded(True, 10))
        self.assertFalse(self.was_sent(win_location("Vanessa")))

    def test_unlock_while_holding_unblocks(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", False))
        self.ctx.items_received.append(NetworkItem(BASE_ID + LOCKED.ap_id, 0, 0, 0))
        self.ctx.refresh_held()
        self.assertIsNone(self.ctx.blocked_reason())


class TestDeathLink(ClientTestBase):
    def test_received_deathlink_shuts_off_checks_including_the_current_fight(self) -> None:
        self.play(RunStarted("Vanessa"), DayReached(1))
        self.ctx.on_deathlink({"time": 1.0, "source": "Friend", "cause": "Friend fell."})
        self.play(MonsterFought(BRONZE_MONSTER, 1, True), PvPFought(1, True), DayReached(2), RunEnded(True, 2))
        self.assertEqual(self.sent, {location_name_to_id[day_location("Vanessa", 1)]})

    def test_next_run_counts_again(self) -> None:
        self.play(RunStarted("Vanessa"))
        self.ctx.on_deathlink({"time": 1.0, "source": "Friend", "cause": "Friend fell."})
        self.play(RunEnded(False, 1), RunStarted("Vanessa"), DayReached(1))
        self.assertTrue(self.was_sent(day_location("Vanessa", 1)))


class TestLockedHero(ClientTestBase):
    def test_locked_hero_blocks_everything(self) -> None:
        self.play(RunStarted("Dooley"), DayReached(1), MonsterFought(BRONZE_MONSTER, 1, True), PvPFought(1, True),
                  RunEnded(True, 1))
        self.assertEqual(self.sent, set())
        self.assertIn("DOOLEY IS LOCKED", self.ctx.blocked_reason() or "DOOLEY IS LOCKED")


class TestPvPAnswers(ClientTestBase):
    def answer(self, key: str) -> None:
        self.ctx.ui_events.put(("pvp", key, True))
        self.await_(self.ctx.drain_ui_events())

    def test_cannot_answer_a_question_that_was_never_asked(self) -> None:
        self.play(RunStarted("Vanessa"))
        self.answer("Vanessa|4")
        self.assertEqual(self.sent - {location_name_to_id[day_location("Vanessa", 1)]}, set())

    def test_answer_for_a_fight_fought_while_blocked_is_refused(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", False), PvPFought(1, None),
                  CardSold("itm_x"))
        self.answer("Vanessa|1")
        self.assertFalse(self.was_sent("Vanessa - Day 1 PvP Win"))

    def test_honest_answer_is_sent(self) -> None:
        self.play(RunStarted("Vanessa"), PvPFought(1, None))
        self.answer("Vanessa|1")
        self.assertTrue(self.was_sent("Vanessa - Day 1 PvP Win"))


class TestCatchUp(ClientTestBase):
    def test_catch_up_keeps_log_order(self) -> None:
        """Starting the client mid-run must block the same checks live play would have blocked."""
        past = [RunStarted("Vanessa"), DayReached(1), CardGained(LOCKED.guid, "itm_x", False), DayReached(2)]
        self.parser.in_run, self.parser.hero, self.parser.day = True, "Vanessa", 2
        self.await_(catch_up(self.ctx, self.parser, past))
        self.assertTrue(self.was_sent(day_location("Vanessa", 1)))
        self.assertFalse(self.was_sent(day_location("Vanessa", 2)))

    def test_run_outside_logic_at_start_needs_a_concede(self) -> None:
        """A run already holding a locked card when the client starts can't be fixed by selling, only conceded,
        and conceding it sends no DeathLink."""
        self.ctx.tags = self.ctx.tags | {"DeathLink"}
        self.ctx.slot_data["death_link_on_concede"] = True
        self.ctx.send_death = mock.AsyncMock()
        past = [RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", False)]
        self.parser.in_run, self.parser.hero, self.parser.day = True, "Vanessa", 1
        self.await_(catch_up(self.ctx, self.parser, past))
        self.play(CardSold("itm_x"), DayReached(2))
        self.assertIn("CONCEDE", self.ctx.blocked_reason())
        self.assertFalse(self.was_sent(day_location("Vanessa", 2)))
        self.play(RunEnded(False, 2, conceded=True), RunStarted("Vanessa"), DayReached(1))
        self.ctx.send_death.assert_not_called()
        self.assertTrue(self.was_sent(day_location("Vanessa", 1)))

    def test_clean_run_at_start_keeps_counting(self) -> None:
        past = [RunStarted("Vanessa"), DayReached(1)]
        self.parser.in_run, self.parser.hero, self.parser.day = True, "Vanessa", 1
        self.await_(catch_up(self.ctx, self.parser, past))
        self.assertIsNone(self.ctx.blocked_reason())


class TestSavedState(ClientTestBase):
    def test_a_new_seed_does_not_inherit_the_old_seeds_run(self) -> None:
        """The free-Dragons-check bug: saved state was keyed on seed_name, which CommonClient never sets."""
        self.ctx.slot = 1
        self.ctx.on_package("RoomInfo", {"seed_name": "old"})
        self.play(RunStarted("Vanessa"))
        self.ctx.save_state()
        self.ctx.on_package("RoomInfo", {"seed_name": "new"})
        self.ctx.load_state()
        self.assertEqual(self.ctx.run, {})


class TestStatusLine(ClientTestBase):
    def test_run_shows_progress_and_next_check(self) -> None:
        self.play(RunStarted("Vanessa"), DayReached(2))
        text, warning = self.ctx.status_line()
        self.assertFalse(warning)
        self.assertIn("Vanessa: day 2/15", text)
        self.assertIn("next: reach day 3", text)
        self.assertIn("Goal 0/2", text)

    def test_picking_a_locked_hero_warns(self) -> None:
        self.play(HeroSelected("Dooley"))
        text, warning = self.ctx.status_line()
        self.assertTrue(warning)
        self.assertIn("DOOLEY IS LOCKED", text)
        self.assertIn("You can play: Vanessa", text)
        self.play(HeroSelected("Vanessa"))
        self.assertFalse(self.ctx.status_line()[1])

    def test_buying_a_locked_card_says_sell_it_now(self) -> None:
        self.ctx.overlay = mock.Mock()
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", True))
        texts = [c.args[0] for c in self.ctx.overlay.toast.call_args_list if c.kwargs.get("warning")]
        self.assertEqual(texts, [f"SELL IT NOW: {LOCKED.name} is locked"])

    def test_blocked_check_pops_up_at_once(self) -> None:
        self.ctx.overlay = mock.Mock()
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", False), DayReached(2))
        texts = [c.args[0] for c in self.ctx.overlay.toast.call_args_list if c.args[0].startswith("CHECK NOT SENT")]
        self.assertEqual(texts, [f"CHECK NOT SENT: {day_location('Vanessa', 2)}"])


class TestItemPopUps(ClientTestBase):
    def send(self, receiving: int, item_id: int) -> list:
        self.ctx.overlay = mock.Mock()
        self.ctx.slot = 1
        self.ctx.player_names = {1: "Me", 2: "Friend"}
        self.ctx.slot_info = {1: NetworkSlot("Me", GAME, SlotType.player),
                              2: NetworkSlot("Friend", "Other", SlotType.player)}
        self.ctx.on_print_json({"type": "ItemSend", "receiving": receiving, "data": [{"text": "x"}],
                                "item": NetworkItem(item_id, 1, 1, 0)})
        return [c.args[0] for c in self.ctx.overlay.toast.call_args_list]

    def test_item_sent_to_another_player_pops_up(self) -> None:
        texts = self.send(2, 123)
        self.assertEqual(len(texts), 1)
        self.assertTrue(texts[0].startswith("SENT: ") and texts[0].endswith(" to Friend"))

    def test_own_unlock_is_not_announced_twice(self) -> None:
        self.assertEqual(self.send(1, BASE_ID + LOCKED.ap_id), [])  # the UNLOCKED pop-up covers it

    def test_own_filler_pops_up(self) -> None:
        self.assertEqual(self.send(1, item_name_to_id["Spare Change"]), ["FOUND: Spare Change"])


class TestNewRunIsACleanSlate(ClientTestBase):
    def test_nothing_carries_over_after_a_lost_run(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", False), PvPFought(1, None))
        self.ctx.on_deathlink({"time": 1.0, "source": "Friend", "cause": "Friend fell."})
        self.play(RunEnded(False, 1), RunStarted("Vanessa"))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertEqual(self.ctx.run["held"], {})
        self.assertEqual(self.ctx.pvp_questions, {})

    def test_nothing_carries_over_when_the_old_run_ended_unseen(self) -> None:
        """e.g. the run was conceded while the client was closed: the next run start still resets everything."""
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", False), RunStarted("Vanessa"),
                  DayReached(1))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertTrue(self.was_sent(day_location("Vanessa", 1)))


class TestDeathLinkTriggers(ClientTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.ctx.tags = self.ctx.tags | {"DeathLink"}
        self.deaths = []

        async def fake_death(text=""):
            self.deaths.append(text)
        self.ctx.send_death = fake_death

    def test_concede_does_not_send_when_turned_off(self) -> None:
        self.ctx.slot_data["death_link_on_concede"] = False
        self.play(RunStarted("Vanessa"), RunEnded(False, 3, conceded=True))
        self.assertEqual(self.deaths, [])

    def test_concede_sends_when_enabled(self) -> None:
        self.ctx.slot_data["death_link_on_concede"] = True
        self.play(RunStarted("Vanessa"), RunEnded(False, 3, conceded=True))
        self.assertEqual(len(self.deaths), 1)

    def test_run_lost_sends_once(self) -> None:
        self.play(RunStarted("Vanessa"), PvPFought(2, None), PvPFought(3, False), RunEnded(False, 3))
        self.assertEqual(len(self.deaths), 1)

    def test_losing_single_fights_never_sends(self) -> None:
        self.play(RunStarted("Vanessa"), PvPFought(1, None))
        self.ctx.ui_events.put(("pvp", "Vanessa|1", False))  # answered "Lost": prestige lost, run goes on
        self.await_(self.ctx.drain_ui_events())
        self.assertEqual(self.deaths, [])

    def test_conceding_because_of_a_received_deathlink_never_echoes(self) -> None:
        self.ctx.slot_data["death_link_on_concede"] = True
        self.play(RunStarted("Vanessa"))
        self.ctx.on_deathlink({"time": 1.0, "source": "Friend", "cause": "Friend fell."})
        self.play(RunEnded(False, 1, conceded=True))
        self.assertEqual(self.deaths, [])


class TestPatchTolerance(ClientTestBase):
    def test_unknown_monster_counts_as_bronze(self) -> None:
        self.play(RunStarted("Vanessa"), MonsterFought("99999999-9999-9999-9999-999999999999", 1, True))
        self.assertTrue(self.was_sent(monster_location("Vanessa", 1, "Bronze")))
        self.assertFalse(self.was_sent(monster_location("Vanessa", 1, "Silver")))
        self.assertIn("monster", self.ctx.notices_shown)

    def test_unknown_card_is_never_locked(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained("99999999-9999-9999-9999-999999999999", "itm_new", True),
                  DayReached(2))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertIn("card", self.ctx.notices_shown)

    def test_newer_game_version_warns_once(self) -> None:
        from ..logparser import GameVersion
        self.play(GameVersion("9.9.99999"), GameVersion("9.9.99999"))
        self.assertIn("version", self.ctx.notices_shown)


class TestSellTraps(ClientTestBase):
    ITEM = next(c for c in CARDS if c.shop and c.hero == "Common" and c.guid != LOCKED.guid)

    def receive_trap(self) -> None:
        self.ctx.items_received.append(NetworkItem(item_name_to_id["Sell Trap"], 0, 0, 0))
        self.ctx.receive_traps()

    def test_trap_gives_two_days_then_blocks_until_sold(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_a", False), DayReached(2))
        self.receive_trap()  # day 2 + 2 days: sell before day 4 starts
        self.assertEqual(self.ctx.run["traps"][0]["deadline"], 4)
        self.play(MonsterFought(BRONZE_MONSTER, 2, True), DayReached(3))  # nothing blocked yet (no fight cost)
        self.assertTrue(self.was_sent(monster_location("Vanessa", 2, "Bronze")))
        self.assertTrue(self.was_sent(day_location("Vanessa", 3)))
        self.play(DayReached(4))  # the day's own check still counts, then the block starts
        self.assertTrue(self.was_sent(day_location("Vanessa", 4)))
        self.assertIn(self.ITEM.name.upper(), self.ctx.blocked_reason())
        self.play(MonsterFought(BRONZE_MONSTER, 4, True))
        self.assertFalse(self.was_sent(monster_location("Vanessa", 4, "Bronze")))
        self.play(CardSold("itm_a"), DayReached(5))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertTrue(self.was_sent(day_location("Vanessa", 5)))

    def test_trap_with_nothing_held_is_dodged(self) -> None:
        self.play(RunStarted("Vanessa"))
        self.receive_trap()
        self.play(CardGained(self.ITEM.guid, "itm_b", False), DayReached(9))
        self.assertEqual(self.ctx.run["traps"], [])
        self.assertIsNone(self.ctx.blocked_reason())

    def test_trap_between_runs_is_dodged(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_a", False), RunEnded(False, 1))
        self.receive_trap()
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_b", False), DayReached(9))
        self.assertEqual(self.ctx.run["traps"], [])

    def test_traps_are_not_repeated_when_items_are_resent(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_a", False))
        self.receive_trap()
        self.ctx.receive_traps()  # e.g. reconnect: the server resends everything
        self.assertEqual(len(self.ctx.run["traps"]), 1)

    def test_new_run_clears_old_traps(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_a", False))
        self.receive_trap()
        self.play(RunEnded(False, 1), RunStarted("Vanessa"), DayReached(9))
        self.assertIsNone(self.ctx.blocked_reason())


class TestUnblockCommand(ClientTestBase):
    def test_unblock_needs_confirm_and_then_clears_everything(self) -> None:
        from ..client import BazaarCommandProcessor
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", False))
        self.ctx.on_deathlink({"time": 1.0, "source": "Friend", "cause": "Friend fell."})
        commands = BazaarCommandProcessor(self.ctx)
        commands("/unblock")
        self.assertIsNotNone(self.ctx.blocked_reason())
        commands("/unblock confirm")
        self.assertIsNone(self.ctx.blocked_reason())
        self.play(DayReached(2))
        self.assertTrue(self.was_sent(day_location("Vanessa", 2)))


class TestHints(ClientTestBase):
    def test_hint_for_a_locked_card_is_shown(self) -> None:
        self.ctx.team, self.ctx.slot = 0, 1
        self.ctx.player_names = {1: "Me", 2: "Friend"}
        self.ctx.location_names.lookup_in_slot = lambda location, slot=None: "Crossroads Chest"
        self.ctx.stored_data["_read_hints_0_1"] = [
            {"receiving_player": 1, "finding_player": 2, "location": 77, "item": BASE_ID + LOCKED.ap_id,
             "found": False}]
        self.assertEqual(self.ctx.locked_card_hints(), {LOCKED.guid: "Friend's Crossroads Chest"})
        self.ctx.stored_data["_read_hints_0_1"][0]["found"] = True  # once found, it's no longer a pointer
        self.assertEqual(self.ctx.locked_card_hints(), {})


class TestWhereNeedsAHint(ClientTestBase):
    def test_where_without_a_hint_reveals_nothing_and_asks_nothing(self) -> None:
        from ..client import BazaarCommandProcessor
        self.ctx.team, self.ctx.slot = 0, 1
        self.ctx.stored_data["_read_hints_0_1"] = []
        said = []
        self.ctx.send_msgs = mock.AsyncMock(side_effect=lambda msgs: said.extend(msgs))
        BazaarCommandProcessor(self.ctx)(f"/where {LOCKED.name}")
        self.assertEqual(said, [])  # no automatic !hint
