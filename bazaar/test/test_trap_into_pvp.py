"""Sell Traps join the PvP run lock (owner, 2026-11-10): "I want the permanently closing the run on sell traps similar
to how everything else needs to be sold by the pvp fight to prevent the lock happening (The flames)"; "The sell trap
wording just has to say "At the start of day 3" -> "Before the end of day 2"". So a trap's item must be gone before the
PvP fight of the day before its deadline; taking it in locks the run; its monster fight that day still counts."""
from unittest import mock

from NetUtils import NetworkItem

from ..items import item_name_to_id
from ..locations import monster_location, pvp_location
from ..logparser import CardGained, CardSold, DayReached, FightStarted, MonsterFought, PvPFought, RunStarted
from .test_client import BRONZE_MONSTER, TestSellTraps


class TestSellTrapIntoPvP(TestSellTraps):
    PVP, MONSTER_FIGHT = FightStarted(True), FightStarted(False)

    def trapped_on_day_2(self) -> None:  # 2 days: before the end of day 3
        self.ctx.overlay = mock.Mock()
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_a", False), DayReached(2))
        self.receive_trap()

    def test_wording(self) -> None:
        self.trapped_on_day_2()
        toasts = [c.args[0] for c in self.ctx.overlay.toast.call_args_list]
        self.assertTrue(any(f"Sell {self.ITEM.name} before the end of day 3" in t for t in toasts), toasts)

    def test_earlier_pvp_fights_are_fine(self) -> None:
        self.trapped_on_day_2()
        self.play(MonsterFought(BRONZE_MONSTER, 2, True), self.PVP, PvPFought(2, True), DayReached(3))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertTrue(self.was_sent(pvp_location("Vanessa", 2)))

    def test_last_day_monster_counts_then_flames_then_pvp_locks_the_run(self) -> None:
        self.trapped_on_day_2()
        self.play(MonsterFought(BRONZE_MONSTER, 2, True), self.PVP, PvPFought(2, True), DayReached(3),
                  self.MONSTER_FIGHT, MonsterFought(BRONZE_MONSTER, 3, True))
        self.assertTrue(self.was_sent(monster_location("Vanessa", 3, "Bronze")))  # not due yet: still counts
        self.ctx.handle_snapshot(self.ctx.memory)  # redraw the notice
        self.assertTrue(self.ctx.overlay.show_locked.call_args.kwargs["danger"])  # hours 4-5: the flames
        self.play(self.PVP, PvPFought(3, True))
        self.assertIn("INTO A PVP FIGHT", self.ctx.blocked_reason())
        self.assertFalse(self.was_sent(pvp_location("Vanessa", 3)))
        self.play(CardSold("itm_a"), DayReached(4))
        self.assertIn("INTO A PVP FIGHT", self.ctx.blocked_reason())  # selling afterwards doesn't bring it back

    def test_sold_before_the_last_pvp_fight_the_run_carries_on(self) -> None:
        self.trapped_on_day_2()
        self.play(DayReached(3), MonsterFought(BRONZE_MONSTER, 3, True), CardSold("itm_a"), self.PVP,
                  PvPFought(3, True), DayReached(4))
        self.assertIsNone(self.ctx.blocked_reason())
        self.assertTrue(self.was_sent(pvp_location("Vanessa", 3)))

    def test_a_trap_after_the_pvp_fight_starts_tomorrow(self) -> None:
        """Owner 2026-11-10: "if it came after the PVP fight then it should be treated as the next day hour 1"."""
        self.ctx.overlay = mock.Mock()
        self.play(RunStarted("Vanessa"), CardGained(self.ITEM.guid, "itm_a", False), DayReached(2), self.PVP,
                  PvPFought(2, True))
        self.receive_trap()
        self.assertEqual(self.ctx.run["traps"][0]["deadline"], 5)  # day 3 + 2 days: before the end of day 4
        toasts = [c.args[0] for c in self.ctx.overlay.toast.call_args_list]
        self.assertTrue(any("before the end of day 4" in t for t in toasts), toasts)
        self.play(DayReached(3), self.PVP, PvPFought(3, True))
        self.assertIsNone(self.ctx.blocked_reason())  # day 3's fight isn't its last one any more

    def test_no_lock_bypass_for_a_run_lost_to_a_sell_trap(self) -> None:
        """Owner 2026-11-10: "Lets make it so it cant be used with a sell trap period"."""
        self.trapped_on_day_2()
        self.play(DayReached(3), self.PVP, PvPFought(3, True))
        self.ctx.items_received.append(NetworkItem(item_name_to_id["Lock Bypass"], 0, 0, 0))
        self.assertEqual(self.ctx.blocked_reason().split(": ")[-1], "CONCEDE THIS RUN")
        self.ctx.use_bypass("forfeit")
        self.assertIn("INTO A PVP FIGHT", self.ctx.blocked_reason())
        self.assertEqual(self.ctx.bypasses_ready(), 1)  # not spent
        self.ctx.handle_snapshot(self.ctx.memory)
        lines = self.ctx.overlay.show_locked.call_args.args[1]
        self.assertFalse([line for line in lines if isinstance(line, tuple)])  # no Use Bypass button

