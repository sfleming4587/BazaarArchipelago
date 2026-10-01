import asyncio
import os
import tempfile
import unittest
from unittest import mock

from NetUtils import NetworkItem, NetworkSlot, SlotType

from ..client import FLIP_SECONDS, BazaarContext, catch_up, dispatch
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
        self.ctx.caught_up = True  # as after watch_log's catch-up: tests feed events straight in
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
                await dispatch(self.ctx, event)
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


class TestPvPWins(ClientTestBase):
    """A mid-run PvP win is counted from the "Waiting for N exit tasks" line (no question any more)."""

    def test_win_signal_sends_the_check(self) -> None:
        self.play(RunStarted("Vanessa"), PvPFought(1, True))
        self.assertTrue(self.was_sent("Vanessa - Day 1 PvP Win"))

    def test_no_signal_is_a_loss(self) -> None:
        self.play(RunStarted("Vanessa"), PvPFought(1, False))
        self.assertFalse(self.was_sent("Vanessa - Day 1 PvP Win"))

    def test_win_while_holding_a_locked_card_is_not_sent(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", False), PvPFought(1, True))
        self.assertFalse(self.was_sent("Vanessa - Day 1 PvP Win"))


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
    def test_run_shows_hero_day_and_goal(self) -> None:
        self.play(RunStarted("Vanessa"), DayReached(2))
        text, warning, _ = self.ctx.status_line()
        self.assertFalse(warning)
        self.assertIn("Vanessa: day 2/15", text)
        self.assertNotIn("next", text)  # what's left to check is PopTracker's job
        self.assertIn("Goal 0/2", text)

    def test_picking_a_locked_hero_warns(self) -> None:
        self.play(HeroSelected("Dooley"))
        text, warning, big = self.ctx.status_line()
        self.assertTrue(warning and big)
        self.assertIn("DOOLEY IS LOCKED", text)
        self.assertIn("HEROES YOU CAN PLAY", text)
        self.assertNotIn("   Dooley", text)
        self.play(HeroSelected("Vanessa"))
        self.assertFalse(self.ctx.status_line()[1])

    def test_menu_lists_checks_done_and_in_logic(self) -> None:
        """Vanessa has no locked items in this test seed, so every check (days 1-15, PvP, 2 monsters a day,
        10 wins) is in logic: 15 * 4 + 1 = 61. Nothing done yet."""
        self.ctx.slot_data.update(logic={"day_10": 15, "diamond": 10, "legendary": 20}, lock_items=[])
        self.play(HeroSelected("Vanessa"))
        self.assertIn("   Vanessa   0 / 61", self.ctx.status_line()[0])
        self.ctx.checked_locations = {location_name_to_id[day_location("Vanessa", 1)]}
        self.assertIn("   Vanessa   1 / 61", self.ctx.status_line()[0])

    def test_locked_items_keep_late_checks_out_of_logic(self) -> None:
        """With 20 of Vanessa's cards locked and none received, day 8+ checks aren't in logic yet (days 1-7:
        reach, 2 monsters = 21, plus PvP days 1-6 = 6 -> 27)."""
        vanessa = [BASE_ID + c.ap_id for c in CARDS if c.hero == "Vanessa" and c.shop][:20]
        self.ctx.slot_data.update(logic={"day_10": 15, "diamond": 10, "legendary": 20}, lock_items=vanessa)
        self.play(HeroSelected("Vanessa"))
        self.assertIn("   Vanessa   0 / 27", self.ctx.status_line()[0])

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
        self.assertEqual(self.send(1, item_name_to_id["Spare Change"]), ["FOUND: Spare Change  (in your own world)"])

    def test_item_received_from_another_player_names_them(self) -> None:
        self.ctx.overlay = mock.Mock()
        self.ctx.slot = 1
        self.ctx.player_names = {1: "Me", 2: "Friend"}
        self.ctx.slot_info = {1: NetworkSlot("Me", GAME, SlotType.player),
                              2: NetworkSlot("Friend", "Other", SlotType.player)}
        self.ctx.on_print_json({"type": "ItemSend", "receiving": 1, "data": [{"text": "x"}],
                                "item": NetworkItem(item_name_to_id["Spare Change"], 1, 2, 0)})
        self.assertEqual([c.args[0] for c in self.ctx.overlay.toast.call_args_list],
                         ["RECEIVED: Spare Change  (from Friend)"])


class TestNewRunIsACleanSlate(ClientTestBase):
    def test_nothing_carries_over_after_a_lost_run(self) -> None:
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", False), PvPFought(1, False))
        self.ctx.on_deathlink({"time": 1.0, "source": "Friend", "cause": "Friend fell."})
        self.play(RunEnded(False, 1), RunStarted("Vanessa"))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertEqual(self.ctx.run["held"], {})

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
        self.play(RunStarted("Vanessa"), PvPFought(2, False), PvPFought(3, False), RunEnded(False, 3))
        self.assertEqual(len(self.deaths), 1)

    def test_losing_single_fights_never_sends(self) -> None:
        self.play(RunStarted("Vanessa"), PvPFought(1, False))  # lost: prestige lost, run goes on
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


class TestLockBypass(ClientTestBase):
    OTHER = next(c for c in CARDS if c.shop and c.hero == "Vanessa" and c.guid != LOCKED.guid)

    def setUp(self) -> None:
        super().setUp()
        self.ctx.slot_data["lock_items"].append(BASE_ID + self.OTHER.ap_id)

    def receive_bypass(self) -> None:
        self.ctx.items_received.append(NetworkItem(item_name_to_id["Lock Bypass"], 0, 0, 0))

    def test_a_bypass_is_never_used_by_itself(self) -> None:
        self.receive_bypass()
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", True))
        self.assertIn(LOCKED.name.upper(), self.ctx.blocked_reason())  # held and blocking, as without a bypass
        self.assertEqual(self.ctx.bypasses_ready(), 1)

    def test_held_card_and_its_copies_are_allowed_for_the_run(self) -> None:
        self.receive_bypass()
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", True), CardGained(LOCKED.guid, "itm_y", True))
        self.ctx.use_bypass(LOCKED.guid)
        self.play(DayReached(2))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertTrue(self.was_sent(day_location("Vanessa", 2)))
        self.assertEqual(self.ctx.bypasses_ready(), 0)
        self.play(CardSold("itm_x"), CardSold("itm_y"), CardGained(LOCKED.guid, "itm_z", True))  # sold and bought back
        self.assertIsNone(self.ctx.blocked_reason())

    def test_only_a_held_card_can_be_bypassed(self) -> None:
        """User, 2026-09-30: only when an item in your inventory is blocked."""
        self.receive_bypass()
        self.play(RunStarted("Vanessa"))
        self.ctx.use_bypass(LOCKED.guid)  # not held
        self.assertEqual(self.ctx.bypasses_ready(), 1)
        self.play(CardGained(LOCKED.guid, "itm_x", True))
        self.assertIsNotNone(self.ctx.blocked_reason())

    def test_one_bypass_covers_one_card(self) -> None:
        self.receive_bypass()
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", True),
                  CardGained(self.OTHER.guid, "itm_o", True))
        self.ctx.use_bypass(LOCKED.guid)
        self.ctx.use_bypass(self.OTHER.guid)  # none left: ignored
        reason = self.ctx.blocked_reason()
        self.assertIn(self.OTHER.name.upper(), reason)
        self.assertNotIn(LOCKED.name.upper(), reason)

    def test_new_run_locks_the_card_again_and_keeps_unused_bypasses(self) -> None:
        self.receive_bypass()
        self.receive_bypass()
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", True))
        self.ctx.use_bypass(LOCKED.guid)
        self.play(RunEnded(False, 3), RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_y", True))
        self.assertIsNotNone(self.ctx.blocked_reason())
        self.assertEqual(self.ctx.bypasses_ready(), 1)

    def test_spent_bypasses_survive_a_restart(self) -> None:
        self.receive_bypass()
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", True))
        self.ctx.use_bypass(LOCKED.guid)
        self.ctx.load_state()
        self.assertEqual(self.ctx.bypasses_ready(), 0)
        self.assertEqual(self.ctx.run["bypassed"], [LOCKED.guid])

    def test_held_card_gets_a_bypass_button_only_while_one_is_ready(self) -> None:
        self.ctx.overlay = mock.Mock()
        self.play(RunStarted("Vanessa"), CardGained(LOCKED.guid, "itm_x", True))
        self.assertIsInstance(self.ctx.overlay.show_locked.call_args[0][1][0], str)  # no bypass: plain line
        self.receive_bypass()
        self.ctx.refresh_held()  # what receiving items does
        text, guid = self.ctx.overlay.show_locked.call_args[0][1][0]
        self.assertIn("SELL OR USE BYPASS", text)
        self.assertEqual(guid, LOCKED.guid)

    def test_count_shows_on_the_status_line_whenever_there_is_one(self) -> None:
        self.assertNotIn("Bypass", self.ctx.status_line()[0])
        self.receive_bypass()
        self.receive_bypass()
        self.assertIn("Lock Bypasses: 2", self.ctx.status_line()[0])  # not in a run
        self.play(RunStarted("Vanessa"))
        self.assertIn("Lock Bypasses: 2", self.ctx.status_line()[0])


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


class TestRunIdentity(ClientTestBase):
    """Which run is which (review 2026-09-29): the log has no run ids, so a new run with the same hero must never
    inherit the old run's blocks or day, and a run resumed after a game restart must keep its real day."""

    def setUp(self) -> None:
        super().setUp()
        self.ctx.log_path = os.path.join(self.tmp.name, "Player.log")
        self.ctx.log_session = "10:00:00.000"
        self.ctx.slot = 1
        self.ctx.room_seed = "seed"

    def test_new_run_after_an_unseen_loss_starts_clean(self) -> None:
        self.play(RunStarted("Vanessa", 0), DayReached(1), DayReached(2))
        self.ctx.on_deathlink({"time": 1.0, "source": "Friend", "cause": "Friend fell."})
        # client closed; the run was lost; client opened again at the menu of the same game session
        self.parser.in_run = False
        self.await_(catch_up(self.ctx, self.parser, [RunStarted("Vanessa", 0), DayReached(1), RunEnded(False, 2)]))
        self.assertFalse(self.ctx.run["active"])
        self.play(RunStarted("Vanessa", 1), DayReached(1), DayReached(2))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertEqual(self.ctx.run["day"], 2)  # not the old run's day

    def test_same_hero_later_run_in_the_same_log_is_new(self) -> None:
        self.play(RunStarted("Vanessa", 0), DayReached(1))
        self.ctx.on_deathlink({"time": 1.0, "source": "Friend", "cause": "Friend fell."})
        self.play(RunStarted("Vanessa", 1), DayReached(1))
        self.assertIsNone(self.ctx.blocked_reason())

    def write_prev_log(self, lines) -> None:
        with open(os.path.join(self.tmp.name, "Player-prev.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(["[10:00:00.000] [Boot] start"] + lines) + "\n")

    def test_resumed_after_a_game_restart_keeps_the_real_day(self) -> None:
        self.play(RunStarted("Vanessa", 0), *[DayReached(d) for d in range(1, 7)])
        self.write_prev_log(["[10:00:01.000] [StartRunAppState] Run initialization finalized."])  # never finished
        self.ctx.log_session = "11:00:00.000"  # the game was restarted
        self.sent.clear()
        self.play(RunStarted("Vanessa", 0), DayReached(1), DayReached(2), PvPFought(2, True))
        self.assertEqual(self.ctx.run["day"], 7)
        self.assertTrue(self.was_sent(day_location("Vanessa", 7)))
        self.assertTrue(self.was_sent("Vanessa - Day 7 PvP Win"))
        self.assertFalse(self.was_sent("Vanessa - Day 2 PvP Win"))

    def test_after_a_restart_a_finished_old_run_means_a_new_run(self) -> None:
        self.play(RunStarted("Vanessa", 0), *[DayReached(d) for d in range(1, 7)])
        self.ctx.on_deathlink({"time": 1.0, "source": "Friend", "cause": "Friend fell."})
        self.write_prev_log(["[10:00:01.000] [StartRunAppState] Run initialization finalized.",
                             "[10:00:02.000] [AppState] State changed from [ChoiceState] to [EndRunDefeatState]"])
        self.ctx.log_session = "11:00:00.000"
        self.play(RunStarted("Vanessa", 0), DayReached(1))
        self.assertEqual(self.ctx.run["day"], 1)
        self.assertIsNone(self.ctx.blocked_reason())


class TestSessionHygiene(ClientTestBase):
    def test_a_dropped_connection_pauses_the_watcher(self) -> None:
        self.ctx.reset_server_state()
        self.assertEqual(self.ctx.slot_data, {})

    def test_leaving_a_room_forgets_its_checks_and_goal(self) -> None:
        self.ctx.locations_checked = {1, 2}
        self.ctx.goal_sent = self.ctx.finished_game = True
        self.await_(self.ctx.disconnect())
        self.assertEqual((self.ctx.locations_checked, self.ctx.goal_sent, self.ctx.finished_game), (set(), False, False))

    def test_state_file_is_replaced_whole(self) -> None:
        self.ctx.room_seed, self.ctx.slot = "seed", 1
        self.play(RunStarted("Vanessa"))
        self.ctx.save_state()
        folder = self.tmp.name
        self.assertTrue(os.path.exists(os.path.join(folder, "bazaar_client_state.json")))
        self.assertFalse(any(name.endswith(".tmp") for name in os.listdir(folder)))


class TestMissedRuns(ClientTestBase):
    """The client wasn't watching for a while (wifi out, client closed): what the game logged meanwhile still
    counts, as if it had been watching - but runs that ended meanwhile send no late DeathLink."""

    def setUp(self) -> None:
        super().setUp()
        self.ctx.log_path = os.path.join(self.tmp.name, "Player.log")
        self.ctx.log_session = "10:00:00.000"
        self.ctx.slot = 1
        self.ctx.room_seed = "seed"
        self.ctx.tags = self.ctx.tags | {"DeathLink"}
        self.ctx.send_death = mock.AsyncMock()

    def reconnect(self, past, in_run: bool) -> None:
        self.sent.clear()
        self.ctx.send_death.reset_mock()  # only what the reconnect itself sends
        self.parser = LogParser()
        self.parser.in_run, self.parser.runs_started = in_run, sum(isinstance(e, RunStarted) for e in past)
        self.await_(catch_up(self.ctx, self.parser, past))

    def test_run_that_ended_during_the_drop_still_counts(self) -> None:
        self.play(RunStarted("Vanessa", 0), DayReached(1))
        self.reconnect([RunStarted("Vanessa", 0), DayReached(1), DayReached(2), PvPFought(2, True), DayReached(3),
                        RunEnded(False, 3)], in_run=False)
        self.assertTrue(self.was_sent(day_location("Vanessa", 3)))
        self.assertTrue(self.was_sent("Vanessa - Day 2 PvP Win"))
        self.assertFalse(self.ctx.run["active"])
        self.ctx.send_death.assert_not_called()  # hours late: no DeathLink

    def test_later_runs_count_and_blocks_still_apply(self) -> None:
        self.play(RunStarted("Vanessa", 0), DayReached(1), RunEnded(False, 1))
        self.reconnect([RunStarted("Vanessa", 0), DayReached(1), RunEnded(False, 1),
                        RunStarted("Vanessa", 1), DayReached(1), CardGained(LOCKED.guid, "itm_x", False),
                        DayReached(2), RunEnded(False, 2),
                        RunStarted("Vanessa", 2), DayReached(1)], in_run=True)
        self.assertTrue(self.was_sent(day_location("Vanessa", 1)))
        self.assertFalse(self.was_sent(day_location("Vanessa", 2)))  # held a locked card
        self.assertTrue(self.ctx.run["active"])
        self.assertEqual(self.ctx.run["run_index"], 2)
        self.assertIsNone(self.ctx.blocked_reason())

    def test_first_connection_counts_only_the_run_in_progress(self) -> None:
        """Runs from before the seed's first connection could predate the seed."""
        past = [RunStarted("Vanessa", 0), DayReached(1), DayReached(2), RunEnded(False, 2),
                RunStarted("Vanessa", 1), DayReached(1)]
        self.reconnect(past, in_run=True)
        self.assertFalse(self.was_sent(day_location("Vanessa", 2)))
        self.assertTrue(self.was_sent(day_location("Vanessa", 1)))
        self.reconnect(past + [RunEnded(False, 1)], in_run=False)  # and they stay uncounted later
        self.assertFalse(self.was_sent(day_location("Vanessa", 2)))

    def test_game_restarted_during_the_drop(self) -> None:
        self.play(RunStarted("Vanessa", 0), DayReached(1))
        with open(os.path.join(self.tmp.name, "Player-prev.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(["[10:00:00.000] [Boot] start",
                               "[10:00:00.500] Changing EHero to Vanessa",
                               "[10:00:01.000] [StartRunAppState] Run initialization finalized.",
                               "[10:00:02.000] [AppState] State changed from [ChoiceState] to [PVPCombatState]",
                               "[10:00:03.000] [AppState] State changed from [PVPCombatState] to [ReplayState]",
                               "[10:00:04.000] [AppState] State changed from [ReplayState] to [ChoiceState]",
                               "[10:00:05.000] [AppState] State changed from [ChoiceState] to [EndRunDefeatState]"])
                    + "\n")
        self.ctx.log_session = "11:00:00.000"
        self.reconnect([RunStarted("Vanessa", 0), DayReached(1), DayReached(2)], in_run=True)
        self.assertTrue(self.was_sent(day_location("Vanessa", 2)))  # from the older log and the new run
        self.assertEqual(self.ctx.run["day"], 2)  # a new run, not the old one resumed
        self.ctx.send_death.assert_not_called()

    def test_missed_run_with_a_locked_hero_still_blocks(self) -> None:
        self.play(RunStarted("Vanessa", 0), DayReached(1), RunEnded(False, 1))
        self.reconnect([RunStarted("Vanessa", 0), DayReached(1), RunEnded(False, 1),
                        RunStarted("Dooley", 1), DayReached(1), DayReached(2), RunEnded(False, 2)], in_run=False)
        self.assertFalse(self.was_sent(day_location("Dooley", 2)))
        self.ctx.send_death.assert_not_called()


class TestReconnectCarriesOn(ClientTestBase):
    """Review 2026-09-30: a reconnect used to judge the whole run again with today's unlocks and alerts. The client
    now carries on from exactly where it stopped (ctx.position)."""

    def setUp(self) -> None:
        super().setUp()
        self.ctx.log_path = os.path.join(self.tmp.name, "Player.log")
        self.ctx.log_session = "10:00:00.000"
        self.ctx.slot = 1
        self.ctx.room_seed = "seed"
        self.ctx.tags = self.ctx.tags | {"DeathLink"}
        self.ctx.send_death = mock.AsyncMock()
        self.log: list = []  # every event of the current game session, as the log holds them

    def live(self, *events) -> None:
        """Events the client sees while watching (as watch_log feeds them)."""
        from ..client import count_event

        async def run():
            for event in events:
                self.log.append(event)
                count_event(self.ctx)
                await dispatch(self.ctx, event)
        self.await_(run())

    def reconnect(self, *unseen) -> None:
        """The connection dropped, the game logged `unseen`, and the client reads the whole log again."""
        self.log.extend(unseen)
        self.sent.clear()
        self.ctx.caught_up = False
        self.parser = LogParser()
        starts = [e for e in self.log if isinstance(e, RunStarted)]
        ends = [i for i, e in enumerate(self.log) if isinstance(e, RunEnded)]
        last_start = max(i for i, e in enumerate(self.log) if isinstance(e, RunStarted)) if starts else -1
        self.parser.in_run = bool(starts) and not any(i > last_start for i in ends)
        self.parser.runs_started = len(starts)
        self.await_(catch_up(self.ctx, self.parser, list(self.log)))
        self.ctx.caught_up = True
        self.ctx.receive_traps()

    def bypass(self) -> None:
        self.ctx.items_received.append(NetworkItem(item_name_to_id["Lock Bypass"], 0, 0, 0))

    def test_a_bypass_never_unblocks_the_days_before_it(self) -> None:
        self.bypass()
        self.live(RunStarted("Vanessa", 0), DayReached(1), CardGained(LOCKED.guid, "itm_x", True), DayReached(2),
                  DayReached(3))
        self.ctx.use_bypass(LOCKED.guid)
        self.live(DayReached(4))
        self.reconnect(DayReached(5))
        self.assertFalse(self.was_sent(day_location("Vanessa", 2)))
        self.assertFalse(self.was_sent(day_location("Vanessa", 3)))
        self.assertTrue(self.was_sent(day_location("Vanessa", 5)))

    def test_unblock_by_hand_survives_a_reconnect(self) -> None:
        self.live(RunStarted("Vanessa", 0), DayReached(1), CardGained(LOCKED.guid, "itm_x", True))
        self.ctx.clear_blocks()
        self.reconnect(DayReached(2))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertTrue(self.was_sent(day_location("Vanessa", 2)))

    def test_no_old_alerts_again(self) -> None:
        self.live(RunStarted("Vanessa", 0), DayReached(1), CardGained(LOCKED.guid, "itm_x", True), CardSold("itm_x"))
        self.ctx.overlay = mock.Mock()
        self.reconnect()
        toasts = [c.args[0] for c in self.ctx.overlay.toast.call_args_list]
        self.assertFalse([t for t in toasts if "SELL" in t or "NOT SENT" in t])

    def test_game_restart_then_reconnect_keeps_the_run(self) -> None:
        self.live(RunStarted("Vanessa", 0), *[DayReached(d) for d in range(1, 7)])
        with open(os.path.join(self.tmp.name, "Player-prev.log"), "w", encoding="utf-8") as f:
            f.write("[10:00:00.000] [Boot] start\n[10:00:01.000] [StartRunAppState] Run initialization finalized.\n")
        self.ctx.log_session, self.log = "11:00:00.000", []  # the game restarted: a new log
        self.live(RunStarted("Vanessa", 0), DayReached(1))  # the run resumed: log day 1 = its real day 6
        self.ctx.on_deathlink({"time": 1.0, "source": "Friend", "cause": "Friend fell."})
        self.reconnect(DayReached(2), PvPFought(2, True))
        self.assertTrue(self.ctx.run["deathlink_owed"])
        self.assertEqual(self.ctx.run["day"], 7)
        self.assertFalse(self.was_sent("Vanessa - Day 2 PvP Win"))

    def test_trap_received_during_a_drop_uses_todays_day(self) -> None:
        item = next(c for c in CARDS if c.shop and c.hero == "Common" and c.guid != LOCKED.guid)
        self.live(RunStarted("Vanessa", 0), DayReached(1), CardGained(item.guid, "itm_a", True))
        self.ctx.caught_up = False  # dropped: the trap arrives with the reconnect, before the log is read
        self.ctx.items_received.append(NetworkItem(item_name_to_id["Sell Trap"], 0, 0, 0))
        self.ctx.receive_traps()
        self.reconnect(*[DayReached(d) for d in range(2, 9)])
        self.assertEqual(self.ctx.run["traps"][0]["deadline"], 10)  # day 8 + 2
        self.assertTrue(self.was_sent(day_location("Vanessa", 8)))

    def test_run_started_during_a_drop_with_a_locked_card_is_conceded_without_a_deathlink(self) -> None:
        """User, 2026-09-30: "2 a, however dont count that as a deathlink"."""
        self.ctx.slot_data["death_link_on_concede"] = True
        self.live(RunStarted("Vanessa", 0), DayReached(1), RunEnded(False, 1))
        self.reconnect(RunStarted("Vanessa", 1), DayReached(1), CardGained(LOCKED.guid, "itm_x", True))
        self.ctx.send_death.reset_mock()  # run 0 was lost while watched: its DeathLink was right
        self.assertIn("CONCEDE", self.ctx.blocked_reason())
        self.live(CardSold("itm_x"), DayReached(2))
        self.assertFalse(self.was_sent(day_location("Vanessa", 2)))  # selling doesn't fix it
        self.live(RunEnded(False, 2, conceded=True))
        self.ctx.send_death.assert_not_called()


class TestUnknownHeroUnblock(ClientTestBase):
    def test_unblock_never_counts_a_hero_outside_the_seed(self) -> None:
        """Review 2026-09-30: this crashed the client (unknown check name) and kept crashing on every re-read."""
        self.play(RunStarted("Mak", 0))
        self.ctx.clear_blocks()
        self.play(DayReached(2), RunEnded(True, 10))
        self.assertEqual(self.sent, set())


class TestCommandsTakeTextAsTyped(ClientTestBase):
    def test_locked_with_a_two_word_hero(self) -> None:
        from ..client import BazaarCommandProcessor
        out = []
        commands = BazaarCommandProcessor(self.ctx)
        commands.output = out.append
        commands("/locked The Dragons")
        self.assertTrue(out)

    def test_logpath_keeps_backslashes_and_spaces_and_checks_the_file(self) -> None:
        from ..client import BazaarCommandProcessor
        folder = os.path.join(self.tmp.name, "Tempo Storm", "The Bazaar")
        os.makedirs(folder)
        path = os.path.join(folder, "Player.log")
        open(path, "w").close()
        commands = BazaarCommandProcessor(self.ctx)
        commands.output = lambda text: None
        before = self.ctx.log_path
        commands(r"/logpath C:\no\such folder\Player.log")
        self.assertEqual(self.ctx.log_path, before)
        commands(f"/logpath {path}")
        self.assertEqual(self.ctx.log_path, path)


class TestShopPadlocks(ClientTestBase):
    """With the memory reader on, only the locked cards actually on offer are named, and padlocked by position."""

    def setUp(self) -> None:
        super().setUp()
        from ..client import MERCHANT_DATA, SHOP_CARDS
        from ..merchants import possible_stock
        self.merchant = next(guid for guid, m in MERCHANT_DATA.items()
                             if LOCKED in possible_stock(m["stock"], "Vanessa", SHOP_CARDS))
        free = [c for c in SHOP_CARDS if c.hero == "Vanessa" and c.guid != LOCKED.guid][:2]
        self.row = [free[0], LOCKED, free[1]]
        self.ctx.overlay = mock.Mock()
        self.play(RunStarted("Vanessa"), DayReached(1))

    def snapshot(self, cards, encounter=None, state="Encounter"):
        from ..memreader import Offer, Snapshot
        return Snapshot(state, encounter or self.merchant,
                        tuple(Offer(f"itm_{c.guid}", c.guid, "Item") for c in cards))

    def enter(self) -> None:
        from ..logparser import EncounterEntered
        self.play(EncounterEntered(self.merchant))

    def test_only_the_locked_card_on_offer_is_named_and_padlocked(self) -> None:
        self.ctx.handle_snapshot(self.snapshot(self.row))
        self.enter()
        overlay = self.ctx.overlay
        overlay.show_padlocks.assert_called_with([c.size for c in self.row], [1], delay=FLIP_SECONDS)
        merchant, names, _verb = overlay.show_shop.call_args.args
        self.assertEqual(names, [LOCKED.name])
        self.assertTrue(overlay.show_shop.call_args.kwargs["exact"])

    def test_buying_it_takes_the_padlock_away(self) -> None:
        self.ctx.handle_snapshot(self.snapshot(self.row))
        self.enter()
        self.ctx.handle_snapshot(self.snapshot([self.row[0], self.row[2]]))
        # the cards left were already showing: no flip, no wait
        self.ctx.overlay.show_padlocks.assert_called_with([self.row[0].size, self.row[2].size], [], delay=0)
        self.assertEqual(self.ctx.overlay.show_shop.call_args.args[1], [])

    def test_an_unlock_arriving_in_the_shop_takes_its_padlock_away(self) -> None:
        self.ctx.handle_snapshot(self.snapshot(self.row))
        self.enter()
        unlock = NetworkItem(BASE_ID + LOCKED.ap_id, 0, 0, 0)
        self.ctx.items_received.append(unlock)
        self.ctx.on_package("ReceivedItems", {"index": 1, "items": [unlock]})
        self.ctx.overlay.show_padlocks.assert_called_with([c.size for c in self.row], [], delay=0)

    def test_without_memory_it_lists_everything_the_merchant_could_sell(self) -> None:
        self.enter()
        self.ctx.overlay.show_padlocks.assert_called_with([], [], delay=0)
        self.assertIn(LOCKED.name, self.ctx.overlay.show_shop.call_args.args[1])
        self.assertFalse(self.ctx.overlay.show_shop.call_args.kwargs["exact"])

    def test_a_reading_from_another_screen_is_not_trusted(self) -> None:
        self.ctx.handle_snapshot(self.snapshot(self.row, state="Choice"))
        self.enter()
        self.ctx.overlay.show_padlocks.assert_called_with([], [], delay=0)
        self.ctx.handle_snapshot(self.snapshot(self.row, encounter="00000000-0000-0000-0000-000000000000"))
        self.ctx.overlay.show_padlocks.assert_called_with([], [], delay=0)
        self.assertFalse(self.ctx.overlay.show_shop.call_args.kwargs["exact"])
