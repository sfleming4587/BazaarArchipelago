"""
Where the monitors are, and keeping windows on them (user, 2026-09-29: the overlay must "NEVER" go off screen).

Every overlay, tracker and pop-up position goes through clamp() before it's applied. Monitor areas come from
Windows in this same process and thread, so they're in the same coordinates as the windows being placed.
"""
import sys
from typing import List, Optional, Tuple

Rect = Tuple[int, int, int, int]  # x, y, width, height


def window_handle(window) -> int:
    """The Windows handle of a Tk window (its outer frame)."""
    return int(window.wm_frame(), 16)


def monitors() -> List[Rect]:
    """Every monitor's full area (Windows only; elsewhere an empty list)."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    found: List[Rect] = []
    user32 = ctypes.windll.user32

    def add(monitor, _dc, _rect, _data) -> bool:
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        # wrapped: a bare int is passed as a 32-bit C int, and a handle above that raised OverflowError and lost the
        # monitor (a player's log, 2026-10-06)
        if user32.GetMonitorInfoW(wintypes.HMONITOR(monitor), ctypes.byref(info)):
            r = info.rcMonitor
            found.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True
    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                  wintypes.LPARAM)(add)
    try:
        user32.EnumDisplayMonitors(None, None, callback, 0)
    except OSError:
        return []
    return found


def overlap(a: Rect, b: Rect) -> int:
    width = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    height = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0, width) * max(0, height)


def monitor_for(rect: Rect, screens: List[Rect]) -> Optional[Rect]:
    """The monitor showing most of `rect`, or None if it's on none of them."""
    best = max(screens, key=lambda screen: overlap(rect, screen), default=None)
    return best if best and overlap(rect, best) else None


def clamp(rect: Rect, area: Rect) -> Rect:
    """`rect` moved (and if needed shrunk) so all of it is inside `area`."""
    x, y, width, height = rect
    ax, ay, aw, ah = area
    width, height = max(1, min(width, aw)), max(1, min(height, ah))
    return max(ax, min(x, ax + aw - width)), max(ay, min(y, ay + ah - height)), width, height


def geometry(rect: Rect) -> str:
    """Tk geometry for a rect ("+-1920" is how Tk takes a monitor left of the main one)."""
    return f"{rect[2]}x{rect[3]}+{rect[0]}+{rect[1]}"


def visible_bounds(window) -> Optional[Rect]:
    """What Windows actually draws of a window (frame and title bar, without the invisible resize border),
    or None if it can't tell (not Windows, not shown yet)."""
    if sys.platform != "win32" or not window.winfo_ismapped():
        return None
    import ctypes
    from ctypes import wintypes
    rect = wintypes.RECT()
    hwnd = window_handle(window)
    try:
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)):  # 9: frame
            return None
    except (AttributeError, OSError):
        return None
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def settle(window, target: Rect, area: Rect) -> None:
    """Put a decorated window so what you see of it (title bar and frame included) is `target`, kept inside
    `area`. Tk sizes the inside of a window, so the frame is measured once it's shown and corrected for."""
    target = clamp(target, area)
    asked = target
    window.geometry(geometry(asked))
    for _ in range(3):  # Windows reports the frame a moment after a change: measure, correct, measure again
        window.update()
        seen = visible_bounds(window)
        if not seen or seen == target:
            return
        asked = (asked[0] + target[0] - seen[0], asked[1] + target[1] - seen[1],
                 max(1, asked[2] + target[2] - seen[2]), max(1, asked[3] + target[3] - seen[3]))
        window.geometry(geometry(asked))


def _add_style(window, flags: int) -> None:
    if sys.platform != "win32":
        return
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = window_handle(window)
    user32.SetWindowLongW(hwnd, -20, user32.GetWindowLongW(hwnd, -20) | flags)  # GWL_EXSTYLE


def click_through(window) -> None:
    """Mouse clicks pass through the window to whatever is underneath (Windows only; elsewhere a no-op)."""
    _add_style(window, 0x80000 | 0x20)  # WS_EX_LAYERED | WS_EX_TRANSPARENT


def never_focus(window) -> None:
    """The window never takes the keyboard focus from the game, even when shown or clicked (its buttons and title
    bar still work). Windows only; elsewhere a no-op."""
    window.update_idletasks()
    _add_style(window, 0x08000000)  # WS_EX_NOACTIVATE


def allow_focus(window, allowed: bool) -> None:
    """Lets a never_focus window take the keyboard for a moment (typing in a search box), then gives it back to
    the game. Windows only; elsewhere a no-op."""
    if sys.platform != "win32":
        return
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = window_handle(window)
    style = user32.GetWindowLongW(hwnd, -20)
    user32.SetWindowLongW(hwnd, -20, style & ~0x08000000 if allowed else style | 0x08000000)

