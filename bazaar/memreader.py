"""
Reads what The Bazaar's shop is offering right now from the game's memory (see docs/MEMORY-READER.md).

READ-ONLY: the game is opened with PROCESS_VM_READ only - nothing is ever written, injected or hooked. Only the
player's own run is read: static TheBazaar.Data.<CurrentState> (the screen, the encounter, the offered cards) and
Data.Entities (to look the offered cards up). Nothing about seeds, other players or accounts (owner's rules,
2026-09-30): anything with a blocked word in its name is refused.

No Mono offset is hard-coded. Each one is found by probing and checked against names that must be there; if any
check fails the reader turns itself off (ReaderOff) instead of guessing. It's never re-engineered automatically
after a patch (owner, 2026-09-30). Windows only, no Archipelago imports, so it's testable on its own.
"""
import re
import struct
import sys
import time
import uuid
from typing import Dict, List, NamedTuple, Optional, Tuple

from . import unity

GAME_EXE = "TheBazaar.exe"
GAME_WINDOW = ("UnityWndClass", "The Bazaar")  # the game's main window: class and title (seen 2026-10-01)
MONO_DLL = "mono-2.0-bdwgc.dll"
RUN_STATES = ("Choice", "Combat", "Encounter", "EndRunDefeat", "EndRunVictory", "LevelUp", "Loot", "NewRun",
              "Pedestal", "PVPCombat", "Shutdown")  # ERunState in declaration order, matched on screen 2026-09-30
ALLOWED_STATICS = ("<CurrentState>k__BackingField", "Entities", "<Run>k__BackingField")
# The board's own on-screen state, read for the padlocks (owner, 2026-10-01: "apply those useful flags as the
# triggers"). Optional: if any of it can't be found (a patch), ui() says None and the padlocks fall back.
UI_STATICS = ("<TransitionIn>k__BackingField", "<TooltipParentComponent>k__BackingField")
LEVEL_STAT = 15  # your level among the player's stats (seen 2 -> 3 at the first level-up, 2026-09-30)
PRESTIGE_STAT = 9  # 25 at a run's start, down on every PvP loss, 0 when the run is lost (2026-09-30)
# Named exceptions to BLOCKED: your own character-select settings, not RNG (owner, 2026-10-01: Random must warn
# when it can roll a locked hero). Nothing else with a blocked word in its name is ever read.
ALLOWED_NAMES = ("_randomHeroEnabled", "_heroExcludedFromRandom")
BLOCKED = ("seed", "rng", "random", "opponent", "steam", "store", "title", "account", "ticket", "token", "auth")
IDENT = re.compile(r"^[A-Za-z_<][\w<>`.\-|=$@]*$")
STRING, VALUETYPE = 0x0E, 0x11  # MonoTypeEnum


class ReaderOff(Exception):
    """A check failed: the reader stops instead of guessing."""


class NotReady(ReaderOff):
    """The game isn't running or is still loading: nothing wrong, try again later."""


class NeedsAdmin(ReaderOff):
    """The game runs as administrator and this client doesn't, so Windows won't let it read the game (the Tempo
    launcher starts it that way, verified 2026-10-07). Not a patch: the client offers to restart as administrator."""


class NoAssemblies(ReaderOff):
    """The game's assembly list isn't there: still loading, or (if it stays that way) a patch."""


# How long after a launch a missing assembly list still means "loading" (2026-10-01: twice the reader looked a few
# seconds after launch, found no list and switched off for the whole session).
LOADING_SECONDS = 120
SNAPSHOT_GRACE = 10.0  # a snapshot failing this long in a row turns the reader off (see Reader.snapshot)
GEAR_SEARCH_SECONDS = 30.0  # a missing settings gear is searched for at most this often (find_gear)
INPUT_SEARCH_SECONDS = 30.0  # a gone input manager is searched for again at once, then at most this often (menu_layers)
UI_RETRY_SECONDS = 1.0  # how often the board's on-screen flags are looked for again until found (see Reader.ui)
# During one board read, memory is fetched in aligned blocks of this size and kept until the read ends: a card's fields
# and its transforms' neighbours sit together, and each fetch is a call into Windows (2026-10-15: ~50 per card, 0.7 ms
# a card; a 144 Hz frame is 6.9 ms). A power of two that divides a page, so a block never spans an unreadable page.
READ_BLOCK = 4096  # one page: measured best of 256 / 1024 / 4096 (2026-10-15, 13 cards: 4.5 / 4.3 / 4.0 ms a read)
FIGHTS = ("Combat", "PVPCombat")
# The merchant's side of the board, read only off fights and only for the cards on offer to you (owner, 2026-10-14:
# "no need to look at the other players information... just what pertains to our user"). Their names hold "opponent",
# which BLOCKED refuses everywhere else.
OFFER_SOCKETS = ("opponentItemSockets", "opponentSkillSockets")
# The event options on a choice screen: a List of EncounterSocketController (recorded 2026-10-15); same rules
EVENT_SOCKETS = "_opponentBoardSocketControllers"
# A right-clicked monster shows its board in the tooltip's MonsterBoardTooltip (recorded 2026-10-15, its items' rects
# matched the owner's video to the pixel). Read only for a monster's card - never a PvP opponent's (they have their
# own view, and the reader never looks at other players).
MONSTER_CARD, MONSTER = "CombatEncounterCard", "TCombatantMonster"
# A tooltip's pieces that cover what's under them (2026-10-14, matched on 4 cards in both views). ⚠️ Chosen by name:
# Unity's switch (unity.active) hides only some of them, and the bottom box can be empty yet "on"; the keyword boxes
# go by the right-click flag (see _tooltip_pieces).
TOOLTIP_PIECES = ("Tags", "Box_Header", "Box_Active_Effect", "Box_Passive_Effect")
TOOLTIP_PIECE_CHILDREN = {"Box_Active_Effect": ("Active_TooltipClock",)}


class Offer(NamedTuple):
    instance: str  # the game's instance id, stable while the card exists
    template: Optional[str]  # the card's guid (the same guids as bazaar_data.json); its size comes from there
    kind: Optional[str]  # Item, Skill, EventEncounter, ...


class BoardUI(NamedTuple):
    """What the board is doing on screen right now (each found 2026-10-01 by watching it while the owner played)."""
    hovering: bool  # a card's tooltip is showing (TooltipParentComponent._cardTooltipController._currentCard)
    dragging: bool  # a card is being dragged (CardController.IsAnyCardDragging, static)
    inventory: bool  # your stash is open over the board (BoardManager.activeStorageToy.toyOpen)
    dialog: bool  # the Esc menu or another dialog is open (BoardManager.DialogOpen)
    revealing: bool  # new cards are flipping over (BoardManager._isRevealing)
    stash_moving: bool = False  # your stash is sliding open or shut (BoardManager.StorageMoving)
    # Where things are on screen, from the game's own objects (bazaar/unity.py), as fractions of the game window
    # (left, top, right, bottom). tooltips: the visible pieces of the tooltips showing now (see _tooltip_pieces).
    tooltips: Tuple[Tuple[float, float, float, float], ...] = ()
    dealing: bool = False  # new cards are being dealt: a reroll's old cards dissolve now (BoardManager._cardsBeingDealt)
    hovered_card: Optional[str] = None  # the instance id of the card whose tooltip shows (or is right-clicked)
    dragged_card: Optional[str] = None  # the instance id of the card being dragged
    inspecting: bool = False  # a right-click inspect view is open (_cardTooltipController.isLocked, 2026-10-14)
    # each card's rect by instance id while it faces you: your board, your stash, and what's on offer (not in fights)
    cards: Dict[str, Tuple[float, float, float, float]] = {}
    # the items on a right-clicked monster's board: (key, template guid); their rects are in cards under the key
    monster_items: Tuple[Tuple[str, Optional[str]], ...] = ()
    gear: Optional[Tuple[float, float, float, float]] = None  # the settings gear at the top right (find_gear)


class HeroPrefs(NamedTuple):
    """Your character-select settings (PlayerPreferences.data)."""
    random: bool  # Random is picked
    excluded: frozenset  # heroes you've excluded from Random, by the game's own name (The Dragons are "Hero8")


class Snapshot(NamedTuple):
    state: Optional[str]  # one of RUN_STATES
    encounter: Optional[str]  # the guid of the merchant/event/monster you're at
    offers: Tuple[Offer, ...]  # in the game's own order
    level: Optional[int] = None  # your level (it sets how wide your board is)
    stash: Tuple[Tuple[int, Optional[str], Optional[str]], ...] = ()  # your stash: (first slot 0-9, template, instance id)
    losses: Optional[int] = None  # Run.Losses: PvP fights lost this run, up the moment the fight's replay ends
    prestige: Optional[int] = None  # 0 or less: the run is lost (docs/MEMORY-READER.md, "A lost run is known ...")
    day: Optional[int] = None  # Run.Day: the game's own day, right after a game restart too
    victories: Optional[int] = None  # Run.Victories: PvP fights won this run
    board: Tuple[Tuple[int, Optional[str], Optional[str]], ...] = ()  # your board, like stash (Run.Player.Hand)


def blocked(name: Optional[str]) -> bool:
    return any(word in (name or "").lower() for word in BLOCKED)


# --- the process ------------------------------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes as C
    import ctypes.wintypes as W

    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = W.HANDLE
    k32.OpenProcess.restype = W.HANDLE
    k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.CloseHandle.argtypes = [W.HANDLE]
    u32 = C.WinDLL("user32", use_last_error=True)
    u32.FindWindowW.restype = W.HWND
    PROCESS_VM_READ, PROCESS_QUERY_INFORMATION, PROCESS_QUERY_LIMITED_INFORMATION = 0x10, 0x400, 0x1000

    class _Region(C.Structure):  # MEMORY_BASIC_INFORMATION
        _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p), ("AllocationProtect", W.DWORD),
                    ("PartitionId", W.WORD), ("RegionSize", C.c_size_t), ("State", W.DWORD), ("Protect", W.DWORD),
                    ("Type", W.DWORD)]
    k32.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.POINTER(_Region), C.c_size_t]

    class _ModuleEntry(C.Structure):
        _fields_ = [("dwSize", W.DWORD), ("th32ModuleID", W.DWORD), ("th32ProcessID", W.DWORD),
                    ("GlblcntUsage", W.DWORD), ("ProccntUsage", W.DWORD), ("modBaseAddr", C.c_void_p),
                    ("modBaseSize", W.DWORD), ("hModule", W.HMODULE), ("szModule", W.WCHAR * 256),
                    ("szExePath", W.WCHAR * 260)]


def game_window() -> Optional[Tuple[int, int]]:
    """(window handle, process id) of The Bazaar, or None if it isn't open. Owner, 2026-10-01: the client must not
    touch anything outside the game, so it never lists or opens other programs: it asks Windows for the one window
    with the game's class and title, and only opens that window's process to confirm it's TheBazaar.exe."""
    if sys.platform != "win32":
        return None
    hwnd = u32.FindWindowW(GAME_WINDOW[0], GAME_WINDOW[1])
    if not hwnd:
        return None
    pid = W.DWORD()
    u32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    process = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not process:
        return None
    try:
        name, size = C.create_unicode_buffer(1024), W.DWORD(1024)
        ok = k32.QueryFullProcessImageNameW(process, 0, name, C.byref(size))
        exe = name.value.replace("/", "\\").rsplit("\\", 1)[-1] if ok else ""
    finally:
        k32.CloseHandle(process)
    return (hwnd, pid.value) if exe.lower() == GAME_EXE.lower() else None


def game_pid() -> Optional[int]:
    found = game_window()
    return found[1] if found else None


ERROR_ACCESS_DENIED = 5


def needs_admin(pid: int) -> bool:
    """Windows refuses to let this client open the game for reading (the rights Memory asks for) because the game
    runs as administrator and the client doesn't."""
    handle = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if handle:
        k32.CloseHandle(handle)
        return False
    return C.get_last_error() == ERROR_ACCESS_DENIED and not C.windll.shell32.IsUserAnAdmin()


def find_module(pid: int, name: str) -> Optional[Tuple[int, int]]:
    snap = k32.CreateToolhelp32Snapshot(0x8 | 0x10, pid)  # TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
    if not snap or snap == C.c_void_p(-1).value:  # INVALID_HANDLE_VALUE: the game is starting or closing (2026-10-06)
        return None
    entry = _ModuleEntry()
    entry.dwSize = C.sizeof(entry)
    try:
        ok = k32.Module32FirstW(snap, C.byref(entry))
        while ok:
            if entry.szModule.lower() == name.lower():
                return entry.modBaseAddr, entry.modBaseSize
            ok = k32.Module32NextW(snap, C.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return None


class Memory:
    """Reads another process's memory. Every read that can't be done returns None (or 0 for a pointer)."""

    def __init__(self, pid: int) -> None:
        # read-only: reading memory, and (QUERY_INFORMATION) listing its regions to find one object once
        self.handle = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION,
                                      False, pid)
        if not self.handle:
            raise ReaderOff(f"can't open the game for reading (error {C.get_last_error()})")
        self.blocks: Optional[dict] = None  # READ_BLOCK-aligned address -> bytes, only during one read (Reader.ui)

    def close(self) -> None:
        if self.handle:
            k32.CloseHandle(self.handle)
            self.handle = None

    def alive(self) -> bool:
        code = W.DWORD()
        return bool(k32.GetExitCodeProcess(self.handle, C.byref(code))) and code.value == 259  # STILL_ACTIVE

    def read(self, address: int, size: int) -> Optional[bytes]:
        if not address or address < 0x10000 or address > 0x7FFFFFFFFFFF:
            return None
        if self.blocks is not None:
            base = address & ~(READ_BLOCK - 1)
            if address + size <= base + READ_BLOCK:
                if base not in self.blocks:
                    self.blocks[base] = self._fetch(base, READ_BLOCK)
                block = self.blocks[base]
                if block is not None:
                    return block[address - base:address - base + size]
        return self._fetch(address, size)

    def _fetch(self, address: int, size: int) -> Optional[bytes]:
        buffer, got = C.create_string_buffer(size), C.c_size_t()
        if not k32.ReadProcessMemory(self.handle, C.c_void_p(address), buffer, size, C.byref(got)) \
                or got.value != size:
            return None
        return buffer.raw

    def ptr(self, address: int) -> int:
        data = self.read(address, 8)
        return struct.unpack("<Q", data)[0] if data else 0

    def i32(self, address: int) -> Optional[int]:
        data = self.read(address, 4)
        return struct.unpack("<i", data)[0] if data else None

    def u32(self, address: int) -> Optional[int]:
        data = self.read(address, 4)
        return struct.unpack("<I", data)[0] if data else None

    def cstr(self, address: int, size: int = 128) -> Optional[str]:
        data = self.read(address, size) or self.read(address, 32)
        if data is None:
            return None
        try:
            return data.split(b"\0", 1)[0].decode("ascii")
        except UnicodeDecodeError:
            return None

    def find_pointer(self, value: int) -> List[int]:
        """Every 8-byte-aligned address in the game's private read-write memory holding `value` - how an object
        nothing static points to is found by its class's vtable (a few seconds; done once, objects don't move)."""
        key, found, address, region = struct.pack("<Q", value), [], 0, _Region()
        while k32.VirtualQueryEx(self.handle, C.c_void_p(address), C.byref(region), C.sizeof(region)):
            base, size = region.BaseAddress or 0, region.RegionSize
            if region.State == 0x1000 and region.Type == 0x20000 and region.Protect in (0x04, 0x40):  # committed RW
                for offset in range(0, size, 1 << 22):
                    chunk = self.read(base + offset, min(1 << 22, size - offset)) or b""
                    i = chunk.find(key)
                    while i >= 0:
                        if i % 8 == 0:
                            found.append(base + offset + i)
                        i = chunk.find(key, i + 1)
            address = base + size
            if address >= 0x7FFFFFFFFFFF:
                break
        return found

    def mono_string(self, obj: int) -> Optional[str]:
        """A System.String: length at +0x10, UTF-16 text at +0x14."""
        length = self.i32(obj + 0x10) if obj else None
        if length is None or not 0 <= length < 4096:
            return None
        data = self.read(obj + 0x14, length * 2)
        return data.decode("utf-16-le", "replace") if data is not None else None


# --- the Mono runtime ---------------------------------------------------------------------------------------------

class Mono:
    """Finds the Mono runtime's struct offsets by probing; each is checked against names that must be found.
    The traps hit finding them (K-mem1..5) are in docs/MEMORY-READER.md."""

    def __init__(self, memory: Memory, base: int, size: int) -> None:
        self.m, self.lo, self.hi = memory, base, base + size
        self.off: Dict[str, int] = {}
        self.domain = self._root_domain()
        self.images = self._images()
        self.field_cache: Dict[int, list] = {}
        # (class, name) -> field: a lookup walks the class's parents, each step several reads - and the board is
        # read every frame (2026-10-15: one read of it took 4-6 ms with 3 cards, a 144 Hz frame is 6.9 ms)
        self.field_index: Dict[tuple, tuple] = {}

    def _export(self, name: str) -> int:
        m, base = self.m, self.lo
        nt = base + (m.u32(base + 0x3C) or 0)
        exports = base + (m.u32(nt + 0x88) or 0)
        count = m.u32(exports + 0x18) or 0
        functions, names, ordinals = (base + (m.u32(exports + k) or 0) for k in (0x1C, 0x20, 0x24))
        for i in range(count):
            if m.cstr(base + (m.u32(names + 4 * i) or 0), 64) == name:
                ordinal = struct.unpack("<H", m.read(ordinals + 2 * i, 2) or b"\0\0")[0]
                return base + (m.u32(functions + 4 * ordinal) or 0)
        raise ReaderOff(f"export {name} not found")

    def _root_domain(self) -> int:
        function = self._export("mono_get_root_domain")
        code = self.m.read(function, 32) or b""
        i = code.find(b"\x48\x8b\x05")  # mov rax, [rip + disp32]
        if i < 0:
            raise ReaderOff("mono_get_root_domain has unexpected code")
        domain = self.m.ptr(function + i + 7 + struct.unpack("<i", code[i + 3:i + 7])[0])
        if not domain:
            raise NotReady("the game is still loading")
        return domain

    def _list(self, head: int, cap: int) -> List[int]:
        out, node = [], head
        while node and len(out) < cap:
            out.append(self.m.ptr(node))
            node = self.m.ptr(node + 8)
        return out

    def _images(self) -> Dict[str, int]:
        m, loading = self.m, False
        for domain_off in range(0, 0x400, 8):
            assemblies = self._list(m.ptr(self.domain + domain_off), 600)
            if len(assemblies) < 5:
                continue
            for name_off in (0x10, 0x8, 0x18, 0x20):
                names = [m.cstr(m.ptr(a + name_off), 64) for a in assemblies]
                if "mscorlib" in names and "TheBazaarRuntime" in names:
                    image_off = self._image_offset(assemblies[names.index("TheBazaarRuntime")])
                    return {n: m.ptr(a + image_off) for n, a in zip(names, assemblies) if n}
                loading = loading or "mscorlib" in names
        # the list is there but the game's own code isn't loaded yet (seen 2026-10-01, a few seconds after launch)
        if loading:
            raise NotReady("the game is still loading")
        raise NoAssemblies("the game's assembly list wasn't found")

    def _image_offset(self, assembly: int) -> int:
        m = self.m
        for off in range(0x8, 0x100, 8):
            image = m.ptr(assembly + off)
            for name_off in range(0, 0x60, 8):
                s = m.cstr(m.ptr(image + name_off), 260)
                if s and (s == "TheBazaarRuntime" or s.endswith("TheBazaarRuntime.dll")):
                    return off
        raise ReaderOff("MonoAssembly.image not found")

    def _class_cache(self, image: int) -> Tuple[int, int]:
        m = self.m
        if "class_cache" in self.off:
            o = self.off["class_cache"]
            return m.i32(image + o + 0x18) or 0, m.ptr(image + o + 0x20)
        for o in range(0x100, 0x1000, 8):
            if not all(self.lo <= m.ptr(image + o + k) < self.hi for k in (0, 8, 16)):
                continue
            size, count, table = m.i32(image + o + 0x18), m.i32(image + o + 0x1C), m.ptr(image + o + 0x20)
            if size and 0 < size < 1 << 20 and count and 0 < count < 1 << 20 and table:
                self.off["class_cache"] = o
                return size, table
        raise ReaderOff("MonoImage.class_cache not found")

    def _learn_class_offsets(self, heads: Dict[int, int], size: int) -> None:
        m = self.m
        for o in range(0x20, 0x80, 8):
            named = sum(1 for c in heads if IDENT.match(m.cstr(m.ptr(c + o)) or "") and m.cstr(m.ptr(c + o + 8)) is not None)
            if named >= 0.9 * len(heads):
                self.off.update(class_name=o, class_namespace=o + 8)
                break
        else:
            raise ReaderOff("MonoClass.name not found")
        for o in range(0x10, 0x200, 4):  # type_token: 0x02xxxxxx, and token % size == its bucket
            tokens = {c: m.u32(c + o) or 0 for c in heads}
            if all(t >> 24 == 2 and t & 0xFFFFFF for t in tokens.values()) and \
                    sum(1 for c, b in heads.items() if tokens[c] % size == b) >= 0.9 * len(heads):
                self.off["class_token"] = o
                break
        else:
            raise ReaderOff("MonoClass.type_token not found")
        token = self.off["class_token"]
        for o in range(0x80, 0x300, 8):  # next_class_cache: the next class in the same bucket
            links = [(m.ptr(c + o), b) for c, b in heads.items()]
            linked = [(p, b) for (p, b), c in zip(links, heads) if p and p != c]  # K-mem1: skip self-pointers
            if len(linked) >= 3 and all((m.u32(p + token) or 0) % size == b and (m.u32(p + token) or 0) >> 24 == 2
                                        for p, b in linked):
                self.off["class_next"] = o
                return
        raise ReaderOff("MonoClass.next_class_cache not found")

    def classes(self, image: int) -> List[int]:
        size, table = self._class_cache(image)
        heads = {}
        for bucket in range(size):
            c = self.m.ptr(table + 8 * bucket)
            if c:
                heads[c] = bucket
        if "class_next" not in self.off:
            self._learn_class_offsets(heads, size)
        out: List[int] = []
        for c in heads:
            seen = set()
            while c and c not in seen and len(out) < 200000:
                seen.add(c)
                out.append(c)
                c = self.m.ptr(c + self.off["class_next"])
        return out

    def name(self, c: int) -> Optional[str]:
        return self.m.cstr(self.m.ptr(c + self.off["class_name"])) if c else None

    def namespace(self, c: int) -> Optional[str]:
        return self.m.cstr(self.m.ptr(c + self.off["class_namespace"])) if c else None

    def find_class(self, image: str, namespace: str, name: str) -> int:
        if image not in self.images:
            raise ReaderOff(f"assembly {image} not found")
        for c in self.classes(self.images[image]):
            if self.name(c) == name and self.namespace(c) == namespace:
                return c
        raise ReaderOff(f"class {namespace}.{name} not found")

    def learn_parent(self, c: int) -> None:
        """c must derive directly from System.Object."""
        for o in range(0x20, 0x100, 8):
            p = self.m.ptr(c + o)
            if p and self.name(p) == "Object" and self.namespace(p) == "System":
                self.off["class_parent"] = o
                return
        raise ReaderOff("MonoClass.parent not found")

    def parent(self, c: int) -> int:
        p = self.m.ptr(c + self.off["class_parent"])
        return 0 if not p or (self.name(p) == "Object" and self.namespace(p) == "System") else p

    def fields(self, c: int) -> list:
        """[(name, offset, static, type code, type data)] declared on c (not inherited)."""
        if c in self.field_cache:
            return self.field_cache[c]
        m = self.m
        if "class_fields" not in self.off:
            for o in range(0x60, 0x200, 8):
                array = m.ptr(c + o)
                if array and m.ptr(array + 0x10) == c and m.ptr(array + 0x30) == c and \
                        IDENT.match(m.cstr(m.ptr(array + 8)) or ""):
                    self.off["class_fields"] = o
                    break
            else:
                raise ReaderOff(f"MonoClass.fields not found on {self.name(c)}")
        array, out = m.ptr(c + self.off["class_fields"]), []
        for i in range(1000):
            entry = array + 0x20 * i
            if not array or m.ptr(entry + 0x10) != c:
                break
            mono_type = m.ptr(entry)
            bits = m.u32(mono_type + 8) or 0
            out.append((m.cstr(m.ptr(entry + 8)), m.i32(entry + 0x18), bool(bits & 0x10), (bits >> 16) & 0xFF,
                        m.ptr(mono_type)))
        self.field_cache[c] = out
        return out

    def field(self, c: int, name: str) -> tuple:
        """(offset, type code, type data) of an instance field of c or a class it derives from (K-mem5: found
        through the object's own class, which may live in another assembly)."""
        if blocked(name) and name not in ALLOWED_NAMES:
            raise ReaderOff(f"refused to read {name}")
        if (c, name) in self.field_index:
            return self.field_index[c, name]
        start = c
        while c:
            for n, offset, static, code, data in self.fields(c):
                if n in (name, f"<{name}>k__BackingField") and not static:
                    self.field_index[start, name] = offset, code, data
                    return offset, code, data
            c = self.parent(c)
        raise ReaderOff(f"field {name} not found")

    def klass(self, obj: int) -> int:
        return self.m.ptr(self.m.ptr(obj)) if obj else 0

    def is_a(self, obj: int, name: str) -> bool:
        """The object's class is `name` or derives from it. False for anything unreadable (a torn-down object)."""
        try:
            c = self.klass(obj)
            for _ in range(16):  # a garbage parent chain must not loop
                if not c:
                    return False
                if self.name(c) == name:
                    return True
                c = self.parent(c)
        except Exception:
            pass
        return False

    def enum_names(self, c: int) -> List[str]:
        return [n for n, _o, static, _code, _data in self.fields(c) if static and n != "value__"]

    def static_data(self, c: int, expect: Dict[str, str]) -> int:
        """The class's static field block, found by needing at least two statics to hold an object of the
        expected class (K-mem2: one match can be a coincidence). Remembers where it was (see static_block)."""
        m = self.m
        statics = {n: offset for n, offset, static, _c, _d in self.fields(c) if static}
        for info_off in range(0x60, 0x200, 8):
            info = m.ptr(c + info_off)
            vtable = m.ptr(info + 8) if info and info != c else 0  # K-mem1: a MonoClass starts with self-pointers
            if not (vtable and vtable != c and m.ptr(vtable) == c):
                continue
            for vtable_off in range(0x28, 0x1000, 8):
                data = m.ptr(vtable + vtable_off)
                if data and sum(1 for n, want in expect.items() if n in statics and
                                self.name(self.klass(m.ptr(data + statics[n]))) == want) >= 2:
                    self.off.update(class_runtime_info=info_off, static_slot=vtable_off)
                    return data
        raise NotReady("static data not found (the game is still loading?)")

    def learn_static_blocks(self, known: int, check) -> bool:
        """Where any class's statics are: after its vtable's method slots, vt->vtable[klass->vtable_size]
        (K-mem6: a fixed slot only looked right because Data and AnalyticsManager have the same number of
        methods). The method count's place in MonoClass is found from the class whose block is `known`, and
        accepted only if `check(static_block)` agrees on other classes. False if nothing passes."""
        m = self.m
        for at in range(0x10, 0x140, 2):
            count = struct.unpack("<H", m.read(known + at, 2) or b"\0\0")[0]
            array = self.off["static_slot"] - 8 * count
            if 0 < count < 4000 and 0x20 <= array <= 0x80:
                self.off.update(method_count=at, method_array=array)
                if check(self.static_block):
                    return True
        self.off.pop("method_count", None)
        return False

    def static_block(self, c: int) -> int:
        """A class's static field block (0 if the class has none set up yet). Needs learn_static_blocks."""
        m = self.m
        vtable = m.ptr(m.ptr(c + self.off["class_runtime_info"]) + 8)
        if not vtable or m.ptr(vtable) != c:
            return 0
        count = struct.unpack("<H", m.read(c + self.off["method_count"], 2) or b"\0\0")[0]
        return m.ptr(vtable + self.off["method_array"] + 8 * count)


# --- the reader ---------------------------------------------------------------------------------------------------

class Reader:
    """attach() once per game start, then snapshot() as often as needed. Both raise ReaderOff."""

    def __init__(self) -> None:
        self.memory: Optional[Memory] = None
        self.first_look: Tuple[int, float] = (0, 0.0)  # (game pid, when the reader first looked at it)
        self.failing_since = 0.0  # when snapshots started failing (0: they aren't)
        self.offers_now: Tuple[Optional[str], frozenset] = (None, frozenset())  # (screen, offer ids), last snapshot
        self.camera: tuple = ()  # the cards' camera, last read (see _card_rects)

    def attached(self) -> bool:
        return self.memory is not None and self.memory.alive()

    def attach(self) -> None:
        self.close()
        if sys.platform != "win32":
            raise ReaderOff("only works on Windows")
        pid = game_pid()
        if not pid:
            raise NotReady("The Bazaar isn't running")
        # Checked first: a refused module list looks just like a game that's still loading (a player's log, 2026-10-06)
        if needs_admin(pid):
            raise NeedsAdmin("The Bazaar runs as administrator")
        module = find_module(pid, MONO_DLL)
        if not module:
            raise NotReady("the game is still loading")
        memory = Memory(pid)
        if self.first_look[0] != pid:
            self.first_look = (pid, time.monotonic())
        try:
            mono = Mono(memory, *module)
            data = mono.find_class("TheBazaarRuntime", "TheBazaar", "Data")
            mono.learn_parent(data)
            statics = {n: offset for n, offset, static, _c, _d in mono.fields(data) if static}
            base = mono.static_data(data, {"_dataInstance": "Data", "Entities": "Dictionary`2",
                                           "<CurrentState>k__BackingField": "RunState",
                                           "<Run>k__BackingField": "Run"})
        except Exception as error:  # a failed check, or a read that made no sense
            memory.close()
            # Early on, the game may still be filling these structures in (2026-10-02: "class_cache not found" 5 s
            # after "still loading" turned the reader off for the session; it attached fine once loaded).
            if time.monotonic() - self.first_look[1] < LOADING_SECONDS:
                raise NotReady("the game is still loading")
            if isinstance(error, ReaderOff):
                raise
            raise ReaderOff(f"unexpected memory layout ({error!r})")
        self.memory, self.mono = memory, mono
        self.statics = {n: base + statics[n] for n in ALLOWED_STATICS if n in statics}
        if len(self.statics) != len(ALLOWED_STATICS):
            self.close()
            raise ReaderOff("TheBazaar.Data has changed")
        self.enums: Dict[int, List[str]] = {}
        self.ui_learn, self.ui_tried, self.ui_classes = (data, base, statics), time.monotonic(), ()
        self.ui_paths = self._learn_ui(data, base, statics)
        self.board_path = base + statics["<TransitionIn>k__BackingField"] if "<TransitionIn>k__BackingField" in statics \
            else 0
        self.prefs_path = self._learn_prefs()
        self.input_manager = self.input_class = 0  # found when first needed (menu_layers)
        self.gear_button: tuple = ()  # (dialog, its class, the button's Transform, its canvas): find_gear
        self.gear_searched = -GEAR_SEARCH_SECONDS
        self.input_searched = -INPUT_SEARCH_SECONDS  # when the input manager was last searched for

    def _learn_prefs(self) -> Optional[int]:
        """Where PlayerPreferences keeps its data (a static), or None if this game version doesn't match."""
        try:
            prefs = self.mono.find_class("TheBazaarRuntime", "", "PlayerPreferences")
            offset = next(o for n, o, st, _c, _d in self.mono.fields(prefs) if st and n == "data")
            block = self.mono.static_block(prefs) if "method_count" in self.mono.off else 0
            return block + offset if block else None
        except (ReaderOff, StopIteration):
            return None

    def menu_layers(self) -> Optional[int]:
        """How many of the game's own screens are open over the board or menu (settings, stores, chests, character
        select ...): the size of InputManager.Context, the game's stack of input layers - each screen pushes
        "Modal" and pops it when it closes (watched 2026-10-01 with the owner). None if it can't be read. The
        input manager is found by a search (nothing static points to it) and kept while it lives. ⚠️ 2026-10-14: the
        game replaces it when a run ends and it's back on the menu - kept "until the game restarts", the hero panel
        stopped hiding under the game's screens after every run. So a gone one is searched for again, at most every
        INPUT_SEARCH_SECONDS (a search reads a few GB, ~17 s)."""
        if not self.memory:
            return None
        mono, m = self.mono, self.memory
        try:
            if self.input_manager and mono.klass(self.input_manager) != self.input_class:
                self.input_manager = None  # gone: replaced at a run's end
            if not self.input_manager and time.monotonic() - self.input_searched >= INPUT_SEARCH_SECONDS:
                self.input_searched = time.monotonic()
                self.input_class = mono.find_class("TheBazaarRuntime", "TheBazaar.Inputs", "InputManager")
                vtable = m.ptr(m.ptr(self.input_class + mono.off["class_runtime_info"]) + 8)
                for obj in m.find_pointer(vtable) if vtable else []:
                    context = self._get(obj, "Context")
                    if context and mono.name(mono.klass(context)) == "InputContextStack":
                        self.input_manager = obj
                        break
            if not self.input_manager:
                return None
            stack = self._get(self._get(self.input_manager, "Context"), "_stack")
            return self._get(stack, "_size") if stack else None
        except Exception:
            return None

    def board_open(self) -> Optional[bool]:
        """Is the game showing a run's board? False on the main menu - even with a run open behind "Resume": the
        game drops its board there (Data.<TransitionIn> empty, back the moment Resume is pressed; watched
        2026-10-14). None when it can't be read."""
        if not self.memory or not self.board_path:
            return None
        try:
            return bool(self.memory.ptr(self.board_path))
        except Exception:
            return None

    def menu_layers_now(self) -> Optional[int]:
        """menu_layers without ever searching (a tenth of a millisecond): None until a search has found the input
        manager, or once it's gone. Cheap enough for the client's fast loop, so the hero panel keeps up with the
        game's screens (owner, 2026-10-14: it took "an extra second to go away")."""
        if not self.memory or not self.input_manager:
            return None
        try:
            if self.mono.klass(self.input_manager) != self.input_class:
                return None
            stack = self._get(self._get(self.input_manager, "Context"), "_stack")
            return self._get(stack, "_size") if stack else None
        except Exception:
            return None

    def hero_prefs(self) -> Optional[HeroPrefs]:
        """Random on or off, and the heroes excluded from it; None if it can't be read."""
        if not self.memory or not self.prefs_path:
            return None
        m = self.memory
        try:
            data = m.ptr(self.prefs_path)
            if not data:
                return None
            table = self._get(data, "_heroExcludedFromRandom")
            excluded = set()
            if table:  # a Dictionary<string, bool>: 24-byte entries (K-mem3)
                entries, count = self._get(table, "_entries"), self._get(table, "_count") or 0
                for i in range(min(count, 50)):
                    entry = entries + 0x20 + 24 * i
                    if (m.i32(entry) or -1) >= 0 and (m.read(entry + 16, 1) or b"\0")[0] == 1:
                        excluded.add(m.mono_string(m.ptr(entry + 8)))
            return HeroPrefs(bool(self._get(data, "_randomHeroEnabled")), frozenset(excluded))
        except Exception:
            return None

    def _learn_ui(self, data: int, base: int, statics: Dict[str, int]) -> Optional[dict]:
        """Where the board's on-screen flags are (see BoardUI), or None if this game version doesn't match."""
        mono, m = self.mono, self.memory
        try:
            if not self.ui_classes:  # a search of every class (~150 ms): once, since ui() retries it on the event loop
                self.ui_classes = (mono.find_class("TheBazaarRuntime", "", "BoardManager"),
                                   mono.find_class("TheBazaarRuntime", "", "CardController"))
            board, cards = self.ui_classes
            board_statics = {n: o for n, o, st, _c, _d in mono.fields(board) if st}
            card_statics = {n: o for n, o, st, _c, _d in mono.fields(cards) if st}
            drag = card_statics["<IsAnyCardDragging>k__BackingField"]

            def check(block) -> bool:  # two classes must make sense through the same rule
                token = mono.name(mono.klass(m.ptr(block(board) + board_statics["CancellationToken"])))
                dragging = (m.read(block(cards) + drag, 1) or b"\xff")[0]
                return token == "CancellationTokenSource" and dragging in (0, 1)
            if not mono.learn_static_blocks(data, check):
                return None
            return {"statics": {n: base + statics[n] for n in UI_STATICS}, "drag": mono.static_block(cards) + drag,
                    "dragged": mono.static_block(cards) + card_statics["<DraggedCard>k__BackingField"]}
        except (ReaderOff, KeyError):
            return None

    def ui(self) -> Optional[BoardUI]:
        """The board's on-screen state now, or None if it can't be read (not learned, not on the board)."""
        if self.memory and not self.ui_paths and time.monotonic() - self.ui_tried >= UI_RETRY_SECONDS:
            # 2026-10-14: at the main menu the board's classes aren't set up yet, so learning them fails there;
            # it works once a run's board has loaded (watched live). Learned once, kept for the session.
            self.ui_tried = time.monotonic()
            self.ui_paths = self._learn_ui(*self.ui_learn)
            if self.ui_paths and not self.prefs_path:
                self.prefs_path = self._learn_prefs()  # needs what _learn_ui found (the static blocks)
        if not self.memory or not self.ui_paths:
            return None
        m, paths = self.memory, self.ui_paths
        m.blocks = {}  # READ_BLOCK: fetched once per read
        try:
            transition = m.ptr(paths["statics"]["<TransitionIn>k__BackingField"])
            board = self._get(transition, "_boardManager") if transition else 0
            if not board:
                return None
            toy = self._get(board, "activeStorageToy")
            tooltips = m.ptr(paths["statics"]["<TooltipParentComponent>k__BackingField"])
            tooltip = self._get(tooltips, "_cardTooltipController") if tooltips else 0
            card = self._get(tooltip, "_currentCard") if tooltip else 0
            hovering = bool(card)
            dragging = (m.read(paths["drag"], 1) or b"\0")[0] == 1
            dragged = m.ptr(paths["dragged"]) if dragging else 0
            inventory = bool(toy and self._get(toy, "toyOpen"))
            inspecting = bool(tooltip and self._get(tooltip, "isLocked"))
            cards = self._card_rects(board)
            monster = self._monster_board(tooltip, card) if inspecting and card else ()
            cards.update((key, rect) for key, _template, rect in monster)
            return BoardUI(hovering=hovering,
                           dragging=dragging,
                           inventory=inventory,
                           dialog=bool(self._get(board, "DialogOpen")),
                           revealing=bool(self._get(board, "_isRevealing")),
                           stash_moving=bool(self._get(board, "StorageMoving")),
                           tooltips=self._tooltip_pieces(tooltips, inspecting) if hovering else (),
                           dealing=bool(self._get(board, "_cardsBeingDealt")),
                           hovered_card=self._instance_id(card), dragged_card=self._instance_id(dragged),
                           inspecting=inspecting,
                           cards=cards, monster_items=tuple((key, template) for key, template, _rect in monster),
                           gear=self._gear_rect())
        except Exception:  # a read that made no sense this time: the padlocks fall back for now
            return None
        finally:
            m.blocks = None

    def gear_wanted(self) -> bool:
        """Is it time to search for the settings gear (on the board, not found, not searched lately)?"""
        return bool(self.memory and not self.gear_button and self.board_open()
                    and time.monotonic() - self.gear_searched >= GEAR_SEARCH_SECONDS)

    def find_gear(self) -> None:
        """Find the settings gear at the board's top right: FightMenuDialog.SettingButton, a "Btn_Settings" in the
        HUD's 1920x1080 "Buttons" canvas (found 2026-10-15 while the owner's run sat open; its rect matched the gear
        on a capture of the game window to the pixel). Nothing static points to the dialog, so it's searched for like
        the input manager (a few GB, ~17 s; on a worker thread); several exist, the live one's button is switched on.
        Kept while it lives (_gear_rect)."""
        self.gear_searched = time.monotonic()
        mono, m = self.mono, self.memory
        read = m.read
        try:
            dialog_class = mono.find_class("TheBazaarRuntime", "", "FightMenuDialog")
            vtable = m.ptr(m.ptr(dialog_class + mono.off["class_runtime_info"]) + 8)
            for obj in m.find_pointer(vtable) if vtable else []:
                if mono.klass(obj) != dialog_class:
                    continue
                button = self._get(obj, "SettingButton")
                transform = unity.transform_of(read, self._native(button)) if button else 0
                if not transform or not unity.active(read, transform):
                    continue
                canvases = [t for t in unity.ancestors(read, transform) if unity.canvas_size(read, t)[0] >= 1]
                if canvases:  # the outermost one with a size is the screen's canvas (the root's reads ~1e-44)
                    self.gear_button = (obj, dialog_class, transform, canvases[-1])
                    return
        except Exception:
            pass

    def _gear_rect(self) -> Optional[Tuple[float, float, float, float]]:
        """The settings gear as fractions of the game window, while the dialog that owns it lives."""
        if not self.gear_button:
            return None
        dialog, dialog_class, transform, canvas = self.gear_button
        read = self.memory.read
        if self.mono.klass(dialog) != dialog_class or not unity.active(read, transform):
            self.gear_button = ()  # replaced (a new run, the menu): searched for again
            return None
        return unity.ui_rect(read, transform, unity.canvas_size(read, canvas))

    def _instance_id(self, card: int) -> Optional[str]:
        """A card's instance id (an object field holding a String)."""
        if not card:
            return None
        value = self._get(card, "InstanceId")
        return self.memory.mono_string(value) if isinstance(value, int) else value

    def _native(self, obj: int) -> int:
        return self.memory.ptr(obj + unity.NATIVE) if obj else 0

    def _card_rects(self, board: int) -> Dict[str, Tuple[float, float, float, float]]:
        """Each card's rect on screen, by instance id, only while its art can be seen (owner, 2026-10-15: "padlocks
        are to only be seen if the art for what it is supposed to be on top of is there"): switched on and its face
        turned toward you (unity.faces_camera). Your board; your stash (shut, its cards face away under the shop;
        they turn into view as it flips open); what's on offer only off fights, and only the offered cards
        (OFFER_SOCKETS). Through the camera the cards themselves use (CardController.mainCamera). Event options
        too (EVENT_SOCKETS), as a point: the centre of their art, which rides into the big view when one's
        right-clicked (recorded 2026-10-15: within 2 px of the measured spots, and on the big art's centre)."""
        read, out, matrix = self.memory.read, {}, None
        state, offered = self.offers_now
        fields = ["playerItemSockets", "playerStorageSockets"]
        sources = [self._get(board, f) for f in fields]
        if state not in FIGHTS and offered:
            sources += [self._offer_sockets(board, f) for f in OFFER_SOCKETS]
        sockets_lists = [(s, self.memory.i32(s + 0x18) or 0, s) for s in sources if s]  # arrays: length, items
        events = self._offer_sockets(board, EVENT_SOCKETS) if state not in FIGHTS and offered else 0
        if events:  # a List: _items, _size
            sockets_lists.append((self._get(events, "_items"), self._get(events, "_size") or 0, None))
        for items, count, source in sockets_lists:
            for i in range(min(count, 20) if items else 0):
                socket = self.memory.ptr(items + 0x20 + 8 * i)
                controller = self._get(socket, "CardController") if socket else 0
                if not controller:
                    continue
                card = self._instance_id(self._get(controller, "CardData"))
                if not card or source not in sources[:len(fields)] and card not in offered:
                    continue
                if matrix is None:
                    matrix = unity.camera_matrix(read, self._native(self._get(controller, "mainCamera"))) or ()
                    self.camera = matrix or self.camera
                if source is None:  # an event option: no Rig of its own, its socket moves (flips with the stash)
                    # ⚠️ unverified that an option's controller has the camera: then the last one seen (the camera
                    # doesn't move between screens as far as we've seen)
                    matrix = matrix or self.camera
                    transform = unity.transform_of(read, self._native(socket))
                    placed = unity.world(read, transform) if matrix and unity.active(read, transform) else None
                    facing = placed and unity.faces_camera(matrix, placed)  # the socket says which way it faces
                    art = unity.world(read, unity.transform_of(read, self._native(controller))) if facing else None
                    point = unity.project(matrix, art[0]) if art else None
                    if point:
                        out[card] = (point[0], point[1], point[0], point[1])
                    continue
                if not unity.active(read, unity.transform_of(read, self._native(controller))):
                    continue  # switched off: a sold card, the frame before it leaves its slot (recorded 2026-10-15)
                rig = self._native(self._get(controller, "Rig"))
                placed = unity.world(read, rig) if matrix else None
                if not placed or not unity.faces_camera(matrix, placed):
                    continue  # turned away: the shop's under an open stash, a shut stash's under the shop
                rect = unity.box_rect(read, matrix, self._native(self._get(controller, "BoxCollider")), rig, placed)
                if rect:
                    out[card] = rect
        return out

    def _monster_board(self, tooltip: int, card: int) -> Tuple[Tuple[str, Optional[str], tuple], ...]:
        """The items on a right-clicked monster's board, while its view is on: (key, template guid, rect)."""
        read = self.memory.read
        template = self._get(card, "Template") if self.mono.name(self.mono.klass(card)) == MONSTER_CARD else 0
        combatant = self._get(template, "CombatantType") if template else 0
        if not combatant or self.mono.name(self.mono.klass(combatant)) != MONSTER:
            return ()
        view = self._get(tooltip, "_monsterBoardTooltip")
        if not view or not unity.active(read, unity.transform_of(read, self._native(view))):
            return ()
        canvas = unity.canvas_size(read, self._native(self._get(tooltip, "_canvasForWorldBounds")))
        shown = self._get(view, "_activeCards")  # a List
        items, size = (self._get(shown, "_items"), self._get(shown, "_size") or 0) if shown else (0, 0)
        out = []
        for i in range(min(size, 20) if items else 0):
            item = self.memory.ptr(items + 0x20 + 8 * i)
            transform = unity.transform_of(read, self._native(item)) if item else 0
            rect = unity.ui_rect(read, transform, canvas) if transform and unity.active(read, transform) else None
            data = self._get(item, "_clientCard") if rect else 0
            if data:
                out.append((f"monster:{i}", self._get(data, "TemplateId"), rect))
        return tuple(out)

    def _offer_sockets(self, board: int, name: str) -> int:
        """One of OFFER_SOCKETS, past BLOCKED (see there); only called off fights."""
        c = self.mono.klass(board)
        while c:
            for n, offset, static, _code, _data in self.mono.fields(c):
                if n == name and not static:
                    return self.memory.ptr(board + offset)
            c = self.mono.parent(c)
        return 0

    def _tooltip_pieces(self, parent: int, inspecting: bool) -> Tuple[Tuple[float, float, float, float], ...]:
        """The visible pieces of the card tooltips showing now, as fractions of the game window: TOOLTIP_PIECES (and
        their children named in TOOLTIP_PIECE_CHILDREN: the cooldown clock), the sell box while Unity has it on, and
        the keyword box - the big one beside a right-clicked card, else the tray at the bottom left (each keeps its
        last rect while the other shows, so the right-click flag picks; matched 2026-10-14)."""
        read, out = self.memory.read, []
        cstr = lambda a: self.memory.cstr(a, 64)  # noqa: E731
        for name in ("_cardTooltipController", "_secondaryCardTooltipController"):
            tip = self._get(parent, name)
            if not tip or not self._get(tip, "_currentCard"):
                continue
            canvas = unity.canvas_size(read, self._native(self._get(tip, "_canvasForWorldBounds")))
            root = self._native(self._get(tip, "rectTransform"))
            mains = [c for c in unity.children(read, root) if unity.name_of(read, c, cstr) == "Tooltip_Main"]
            for piece in unity.children(read, mains[0]) if mains else []:
                piece_name = unity.name_of(read, piece, cstr)
                if piece_name not in TOOLTIP_PIECES:
                    continue
                out.append(unity.ui_rect(read, piece, canvas))
                wanted = TOOLTIP_PIECE_CHILDREN.get(piece_name, ())
                out += [unity.ui_rect(read, c, canvas) for c in unity.children(read, piece)
                        if unity.name_of(read, c, cstr) in wanted]
            sell = self._get(tip, "_sellPriceParent")
            sell_transform = unity.transform_of(read, self._native(sell)) if sell else 0
            if sell_transform and unity.active(read, sell_transform):
                out.append(unity.ui_rect(read, sell_transform, canvas))
            legend = self._get(tip, "_legendTooltipComponent" if inspecting else "_legendTrayTooltipComponent")
            legend_transform = unity.transform_of(read, self._native(legend)) if legend else 0
            if legend_transform:
                backgrounds = [c for c in unity.children(read, legend_transform)
                               if unity.name_of(read, c, cstr) == "Background"]
                out.append(unity.ui_rect(read, backgrounds[0] if backgrounds else legend_transform, canvas))
        return tuple(r for r in out if r)

    def close(self) -> None:
        if self.memory:
            self.memory.close()
        self.memory = None

    def _get(self, obj: int, name: str):
        """An instance field's value: a pointer for objects, a str for strings/guids, an int (or its enum name)."""
        offset, code, data = self.mono.field(self.mono.klass(obj), name)
        m = self.memory
        if code == 0x02:  # bool
            return (m.read(obj + offset, 1) or b"\0")[0] == 1
        if code == STRING:
            return m.mono_string(m.ptr(obj + offset))
        # An enum's name is taken by its position in the declaration. ⚠️ That's only right when its values count from
        # 0: ECardType does (Item, Skill, EventEncounter matched the screen), ECardSize doesn't (it read one size too
        # big, 2026-10-01), so sizes come from bazaar_data.json instead.
        if code == VALUETYPE and self.mono.name(self.mono.parent(data) or 0) == "Enum":
            names = self.enums.setdefault(data, self.mono.enum_names(data))
            value = m.i32(obj + offset)
            return names[value] if value is not None and 0 <= value < len(names) else None
        if code == VALUETYPE and self.mono.name(data) == "Guid":
            raw = m.read(obj + offset, 16)
            return str(uuid.UUID(bytes_le=raw)) if raw else None
        if code in (0x08, 0x09):  # int, uint
            return m.i32(obj + offset)
        return m.ptr(obj + offset)

    def _entities(self) -> Dict[str, int]:
        """Instance id -> card object, from Data.Entities (a Dictionary with 24-byte entries, K-mem3)."""
        m, entities = self.memory, self.memory.ptr(self.statics["Entities"])
        if not entities:
            return {}
        entries, count = self._get(entities, "_entries"), self._get(entities, "_count") or 0
        out = {}
        for i in range(min(count, 5000)):
            entry = entries + 0x20 + 24 * i
            key, value = m.ptr(entry + 8), m.ptr(entry + 16)
            if key and value:
                out[m.mono_string(key)] = value
        return out

    def snapshot(self) -> Snapshot:
        """What's on screen now. A failed read is "no screen" while it lasts under SNAPSHOT_GRACE: the game swaps its
        objects around a run's end and a reading can catch one half-made (2026-10-02, and the same class of bug as
        the input manager, 2026-10-14). Only a failure that lasts turns the reader off (a patch: attach's checks
        catch most of those first)."""
        if not self.memory:
            raise ReaderOff("not attached")
        try:
            snapshot = self._snapshot()
        except Exception as error:
            now = time.monotonic()
            self.failing_since = self.failing_since or now
            if now - self.failing_since < SNAPSHOT_GRACE:
                return Snapshot(None, None, ())
            if isinstance(error, ReaderOff):
                raise
            raise ReaderOff(f"unexpected memory layout ({error!r})")
        self.failing_since = 0.0
        return snapshot

    def _snapshot(self) -> Snapshot:
        m = self.memory
        state = m.ptr(self.statics["<CurrentState>k__BackingField"])
        # Not a RunState: the static was caught mid-change - once, right after a concede (2026-10-01), it pointed at
        # an object without StateName and the reader switched off for the session. That's no patch (attach checks the
        # static's type), so it's read as "no screen" and the next look tries again.
        if not state or not self.mono.is_a(state, "RunState"):
            return Snapshot(None, None, ())
        name = self._get(state, "StateName")
        # An unknown name ("0" for a moment at a run start, 2026-10-01; or a screen a patch added) is "no screen" too:
        # nothing gets padlocked there, nothing wrong is shown, and the next look tries again.
        if name is not None and name not in RUN_STATES:
            return Snapshot(None, None, ())
        encounter = self._get(state, "CurrentEncounterId")
        selection = self._get(state, "SelectionSet")
        ids: List[str] = []
        if selection:
            items, size = self._get(selection, "_items"), self._get(selection, "_size") or 0
            ids = [m.mono_string(m.ptr(items + 0x20 + 8 * i)) for i in range(min(size, 20))]
        offers = []
        self.offers_now = (name, frozenset(ids))  # ui() places these cards (only these) off fights
        if ids:
            by_id = self._entities()
            for instance in ids:
                card = by_id.get(instance)
                if not card:
                    offers.append(Offer(instance, None, None))
                    continue
                offers.append(Offer(instance, self._get(card, "TemplateId"), self._get(card, "Type")))
        return Snapshot(name, encounter, tuple(offers), *self._run_parts())

    def _run_parts(self) -> tuple:
        """Your level, stash, losses, prestige, day, victories and board, or None/() for any that make no sense this
        time. They're read through the Run, which
        the game tears down and replaces around a run's end: 8 s after a concede (2026-10-02) Run.Player had no
        Attributes for a moment, and the reader switched off for the whole game session - no padlocks until the
        client restarted. So a failed read here never turns the reader off: the next look tries again. Losses is
        read on its own (with day and victories), so a patch that renames it never costs level or stash."""
        try:
            run = self.memory.ptr(self.statics["<Run>k__BackingField"])
            counts = tuple(self._get(run, name) if run else None for name in ("Losses", "Day", "Victories"))
        except Exception:
            counts = (None, None, None)
        losses, day, victories = counts
        try:
            ids: Dict[int, str] = {}
            stash, board = self._container("Stash", ids), self._container("Hand", ids)
            return self._stat(LEVEL_STAT), stash, losses, self._stat(PRESTIGE_STAT), day, victories, board
        except Exception:
            return None, (), losses, None, day, victories, ()

    def _container(self, which: str, ids: Dict[int, str]) -> Tuple[Tuple[int, Optional[str], Optional[str]], ...]:
        """Your stash ("Stash") or board ("Hand", owner 2026-10-07: "we should be able to read the board"): its cards
        and the slot each starts in, from Run.Player.<which>.Container.Sockets (10 slots; a card fills one per slot it
        covers). Cards can sit in any slot and move freely (owner, 2026-10-01). Only your own cards are read. `ids`
        caches Data.Entities' instance ids for the reading (only read when a container isn't empty)."""
        m, run = self.memory, self.memory.ptr(self.statics["<Run>k__BackingField"])
        player = self._get(run, "Player") if run else 0
        box = self._get(player, which) if player else 0
        container = self._get(box, "Container") if box else 0
        sockets = self._get(container, "Sockets") if container else 0
        if not sockets:
            return ()
        out, seen = [], set()
        for slot in range(min(m.i32(sockets + 0x18) or 0, 10)):
            card = m.ptr(sockets + 0x20 + 8 * slot)
            if card and card not in seen:
                seen.add(card)
                if not ids:  # instance ids are the Entities keys
                    ids.update({obj: instance for instance, obj in self._entities().items()})
                out.append((slot, self._get(card, "TemplateId"), ids.get(card)))
        return tuple(out)

    def _stat(self, stat: int) -> Optional[int]:
        """One of your stats, from Run.Player.Attributes (a Dictionary of stat -> value with 16-byte entries, K-mem3)."""
        m, run = self.memory, self.memory.ptr(self.statics["<Run>k__BackingField"])
        player = self._get(run, "Player") if run else 0
        stats = self._get(player, "Attributes") if player else 0
        if not stats:
            return None
        entries, count = self._get(stats, "_entries"), self._get(stats, "_count") or 0
        for i in range(min(count, 200)):
            entry = entries + 0x20 + 16 * i
            if (m.i32(entry) or -1) >= 0 and m.i32(entry + 8) == stat:  # a used entry (hash code >= 0)
                return m.i32(entry + 12)
        return None
