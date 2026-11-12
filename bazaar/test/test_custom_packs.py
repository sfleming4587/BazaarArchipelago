"""Custom card packs (owner, 2026-11-10). Expected results are the owner's own words:
- "packs that all share 1 common build archetype", "close to 10" cards each.
- "allow those as options ... as their own card packs with the custom card pack option (Allow a drop down to turn on
  or off any card packs specifically including the legacy)" -> its own section, one switch per pack.
- Defaults: "On by default, off if easy"; Hardcore: "both on"."""
import json
import pkgutil
import unittest

from .. import data
from ..data import CARDS_BY_GUID, PACKS
from ..options import PACK_OPTIONS, PACK_SWITCHES, CustomCardPacks, option_groups, option_presets
from .bases import ALL_HEROES, BazaarTestBase

CUSTOM = [p for p in PACKS if p.custom]
LEGACY = [p for p in PACKS if not p.custom]


class TestCustomPackData(unittest.TestCase):
    def test_fourteen_packs_of_ten(self) -> None:
        self.assertEqual(len(CUSTOM), 14)
        self.assertTrue(all(len(p.cards) == 10 for p in CUSTOM))

    def test_names_match_their_guids(self) -> None:
        # the file keys cards by guid; a name that no longer matches means a patch changed the card (re-check it)
        raw = json.loads(pkgutil.get_data(data.__name__, "custom_packs.json").decode("utf-8"))
        for pack in raw["packs"]:
            for card in pack["cards"]:
                self.assertIn(card["guid"], CARDS_BY_GUID, card["name"])
                self.assertEqual(CARDS_BY_GUID[card["guid"]].name, card["name"])

    def test_cards_are_the_heros_own_shop_cards(self) -> None:
        for p in CUSTOM:
            for guid in p.cards:
                card = CARDS_BY_GUID[guid]
                self.assertEqual((card.hero, card.shop), (p.hero, True), f"{p.name}: {card.name}")
                self.assertNotEqual(card.tier, "Legendary", card.name)  # Legendary cards belong to Legendary Items
                self.assertFalse(card.ticket, card.name)  # tickets belong to Expedition Tickets

    def test_no_card_in_two_packs(self) -> None:
        guids = [g for p in PACKS for g in p.cards]
        self.assertEqual(len(guids), len(set(guids)))

    def test_ids_unique_and_apart_from_legacy(self) -> None:
        ids = [p.ap_id for p in PACKS]
        self.assertEqual(len(ids), len(set(ids)))
        # the extractor numbers legacy packs up from 100; custom packs start at 150 so the two never meet
        self.assertTrue(all(150 <= p.ap_id < 200 for p in CUSTOM))
        self.assertTrue(all(p.ap_id < 150 for p in LEGACY))

    def test_pack_names_are_not_card_names(self) -> None:
        names = {c.name for c in CARDS_BY_GUID.values()}
        # owner 2026-11-10 renamed "Stelle's Workshop" to Tinkerer's Toolbox for this; legacy Dooltron is the game's own
        self.assertFalse({p.name for p in CUSTOM} & names)


class TestCustomPackOptions(unittest.TestCase):
    def test_own_section_with_every_custom_pack(self) -> None:
        groups = {g.name: g.options for g in option_groups}
        switches = dict(zip(PACK_OPTIONS, PACK_SWITCHES.values()))
        custom = [switches[f"pack_{p.key.lower()}"] for p in CUSTOM]
        legacy = [switches[f"pack_{p.key.lower()}"] for p in LEGACY]
        self.assertEqual(groups["Custom Card Packs"], [CustomCardPacks, *custom])
        self.assertEqual(groups["Legacy Card Packs"][1:], legacy)

    def test_defaults_and_presets(self) -> None:
        self.assertTrue(CustomCardPacks.default)
        self.assertIs(option_presets["Casual"]["custom_card_packs"], False)
        self.assertIs(option_presets["Hardcore"]["custom_card_packs"], True)
        self.assertIs(option_presets["Hardcore"]["legacy_card_packs"], True)


def pack_items(test: BazaarTestBase) -> set:
    return {i.name for i in test.multiworld.itempool if i.player == test.player and i.name.startswith("Pack: ")}


class TestOnByDefault(BazaarTestBase):
    options = {**ALL_HEROES, "locked_cards_percent": 100}

    def test_every_custom_pack_and_no_legacy(self) -> None:
        self.assertEqual(pack_items(self), {f"Pack: {p.name}" for p in CUSTOM})

    def test_pack_cards_never_lock_singly(self) -> None:
        names = {i.name for i in self.multiworld.itempool if i.player == self.player}
        self.assertFalse({CARDS_BY_GUID[g].name for p in CUSTOM for g in p.cards} & names)


class TestOnlyIncludedHeroes(BazaarTestBase):
    options = {"include_stelle": True}  # base heroes + Stelle

    def test_dooley_and_stelle_packs_only(self) -> None:
        self.assertEqual(pack_items(self), {f"Pack: {p.name}" for p in CUSTOM if p.hero in ("Dooley", "Stelle")})


class TestCustomOff(BazaarTestBase):
    options = {**ALL_HEROES, "custom_card_packs": False, "legacy_card_packs": True}

    def test_legacy_only(self) -> None:
        self.assertEqual(pack_items(self), {f"Pack: {p.name}" for p in LEGACY})


class TestOneCustomPackUnticked(BazaarTestBase):
    options = {**ALL_HEROES, "pack_custom_stelle_swarm_protocol": False}

    def test_unticked_pack_left_out_and_its_cards_lock_singly(self) -> None:
        self.assertNotIn("Pack: Swarm Protocol", pack_items(self))
        self.assertIn("Pack: Skyward Bound", pack_items(self))
