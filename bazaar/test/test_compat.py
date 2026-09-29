import pathlib
import tokenize
import unittest


class TestPython311(unittest.TestCase):
    def test_f_strings_never_reuse_their_own_quote(self) -> None:
        """Archipelago supports Python 3.11, where f"{d["key"]}" is a syntax error (it's only allowed from 3.12
        on, and 3.12+ can't be told to reject it). Such a line once made the overlay fail to load on 3.11."""
        if not hasattr(tokenize, "FSTRING_START"):
            self.skipTest("Python 3.11 would already fail to import such a file")
        for path in pathlib.Path(__file__).parents[1].rglob("*.py"):
            with open(path, "rb") as source:
                quotes = []  # the quote of each f-string we're inside
                for token in tokenize.tokenize(source.readline):
                    if token.type == tokenize.FSTRING_END:
                        quotes.pop()
                        continue
                    if token.type in (tokenize.STRING, tokenize.FSTRING_START):
                        quote = token.string.lstrip("rRbBuUfF")[:1]
                        self.assertFalse(quotes and quote == quotes[-1],
                                         f"{path.name}:{token.start[0]} reuses the f-string's quote (3.12+ only)")
                        if token.type == tokenize.FSTRING_START:
                            quotes.append(quote)
