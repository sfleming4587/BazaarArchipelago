from test.bases import WorldTestBase

from ..options import INCLUDE_HERO_OPTIONS

ALL_HEROES = {option: True for option in INCLUDE_HERO_OPTIONS}  # every hero in the seed (a new hero joins by itself)


class BazaarTestBase(WorldTestBase):
    game = "The Bazaar"

    def pool_items(self) -> list:
        """This player's items in the pool."""
        return [i for i in self.multiworld.itempool if i.player == self.player]

    def pool_names(self) -> list:
        return [i.name for i in self.pool_items()]
