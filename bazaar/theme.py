"""Colours and fonts shared by every window the client shows (overlay, Shop Guide, tracker)."""
FONT = "Segoe UI"

FG = "#ffffff"
ACCENT = "#ffcf5a"  # headings, letters, the windows' borders
GOOD = "#9be39b"  # all good: nothing locked, cards you can buy
WARN = "#ff8a8a"  # something wrong: a locked hero picked, locked cards
MUTED = "#e6d5b8"  # quiet text: the progress line
DIM = "#8a8a8a"  # done, greyed out
WINDOW_BG = "#16141c"  # the Shop Guide and the tracker
LOCKED_X = "#e0303a"  # the red cross over a locked card's picture, the padlock on a locked card in a shop
OUTLINE = "#1a0406"  # around the padlock, so it shows on light cards too

# background by how urgent a window is (user 2026-09-28: "not just red, correspondant to the severity")
SEVERITY = {"critical": "#5a0f14",  # checks blocked, DeathLink
            "warning": "#5c3f0c",  # locked cards on sale, a Sell Trap, a locked hero picked
            "info": "#1f2430",  # progress only
            "ok": "#173d24"}  # nothing locked here, an unlock arrived
