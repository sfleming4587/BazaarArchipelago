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
import uuid
from typing import Dict, List, NamedTuple, Optional, Tuple

GAME_EXE = "TheBazaar.exe"
MONO_DLL = "mono-2.0-bdwgc.dll"
RUN_STATES = ("Choice", "Combat", "Encounter", "EndRunDefeat", "EndRunVictory", "LevelUp", "Loot", "NewRun",
              "Pedestal", "PVPCombat", "Shutdown")  # ERunState in declaration order, matched on screen 2026-09-30
ALLOWED_STATICS = ("<CurrentState>k__BackingField", "Entities", "<Run>k__BackingField")
LEVEL_STAT = 15  # your level among the player's stats (seen 2 -> 3 at the first level-up, 2026-09-30)
BLOCKED = ("seed", "rng", "random", "opponent", "steam", "store", "title", "account", "ticket", "token", "auth")
IDENT = re.compile(r"^[A-Za-z_<][\w<>`.\-|=$@]*$")
STRING, VALUETYPE = 0x0E, 0x11  # MonoTypeEnum


class ReaderOff(Exception):
    """A check failed: the reader stops instead of guessing."""


class NotReady(ReaderOff):
    """The game isn't running or is still loading: nothing wrong, try again later."""


class Offer(NamedTuple):
    instance: str  # the game's instance id, stable while the card exists
    template: Optional[str]  # the card's guid (the same guids as bazaar_data.json); its size comes from there
    kind: Optional[str]  # Item, Skill, EventEncounter, ...


class Snapshot(NamedTuple):
    state: Optional[str]  # one of RUN_STATES
    encounter: Optional[str]  # the guid of the merchant/event/monster you're at
    offers: Tuple[Offer, ...]  # in the game's own order
    level: Optional[int] = None  # your level (it sets how wide your board is)


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
    PROCESS_VM_READ, PROCESS_QUERY_LIMITED_INFORMATION = 0x10, 0x1000

    class _ProcessEntry(C.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                    ("th32DefaultHeapID", C.c_size_t), ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD),
                    ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", W.LONG), ("dwFlags", W.DWORD),
                    ("szExeFile", W.WCHAR * 260)]

    class _ModuleEntry(C.Structure):
        _fields_ = [("dwSize", W.DWORD), ("th32ModuleID", W.DWORD), ("th32ProcessID", W.DWORD),
                    ("GlblcntUsage", W.DWORD), ("ProccntUsage", W.DWORD), ("modBaseAddr", C.c_void_p),
                    ("modBaseSize", W.DWORD), ("hModule", W.HMODULE), ("szModule", W.WCHAR * 256),
                    ("szExePath", W.WCHAR * 260)]


def find_pid(exe: str) -> Optional[int]:
    if sys.platform != "win32":
        return None
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    entry = _ProcessEntry()
    entry.dwSize = C.sizeof(entry)
    try:
        ok = k32.Process32FirstW(snap, C.byref(entry))
        while ok:
            if entry.szExeFile.lower() == exe.lower():
                return entry.th32ProcessID
            ok = k32.Process32NextW(snap, C.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return None


def find_module(pid: int, name: str) -> Optional[Tuple[int, int]]:
    snap = k32.CreateToolhelp32Snapshot(0x8 | 0x10, pid)  # TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
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
        self.handle = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not self.handle:
            raise ReaderOff(f"can't open the game for reading (error {C.get_last_error()})")

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
        m = self.m
        for domain_off in range(0, 0x400, 8):
            assemblies = self._list(m.ptr(self.domain + domain_off), 600)
            if len(assemblies) < 5:
                continue
            for name_off in (0x10, 0x8, 0x18, 0x20):
                names = [m.cstr(m.ptr(a + name_off), 64) for a in assemblies]
                if "mscorlib" in names and "TheBazaarRuntime" in names:
                    image_off = self._image_offset(assemblies[names.index("TheBazaarRuntime")])
                    return {n: m.ptr(a + image_off) for n, a in zip(names, assemblies) if n}
        raise ReaderOff("the game's assembly list wasn't found")

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
        if blocked(name):
            raise ReaderOff(f"refused to read {name}")
        while c:
            for n, offset, static, code, data in self.fields(c):
                if n in (name, f"<{name}>k__BackingField") and not static:
                    return offset, code, data
            c = self.parent(c)
        raise ReaderOff(f"field {name} not found")

    def klass(self, obj: int) -> int:
        return self.m.ptr(self.m.ptr(obj)) if obj else 0

    def enum_names(self, c: int) -> List[str]:
        return [n for n, _o, static, _code, _data in self.fields(c) if static and n != "value__"]

    def static_data(self, c: int, expect: Dict[str, str]) -> int:
        """The class's static field block, found by needing at least two statics to hold an object of the
        expected class (K-mem2: one match can be a coincidence)."""
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
                    return data
        raise NotReady("static data not found (the game is still loading?)")


# --- the reader ---------------------------------------------------------------------------------------------------

class Reader:
    """attach() once per game start, then snapshot() as often as needed. Both raise ReaderOff."""

    def __init__(self) -> None:
        self.memory: Optional[Memory] = None

    def attached(self) -> bool:
        return self.memory is not None and self.memory.alive()

    def attach(self) -> None:
        self.close()
        if sys.platform != "win32":
            raise ReaderOff("only works on Windows")
        pid = find_pid(GAME_EXE)
        if not pid:
            raise NotReady("The Bazaar isn't running")
        module = find_module(pid, MONO_DLL)
        if not module:
            raise NotReady("the game is still loading")
        memory = Memory(pid)
        try:
            mono = Mono(memory, *module)
            data = mono.find_class("TheBazaarRuntime", "TheBazaar", "Data")
            mono.learn_parent(data)
            statics = {n: offset for n, offset, static, _c, _d in mono.fields(data) if static}
            base = mono.static_data(data, {"_dataInstance": "Data", "Entities": "Dictionary`2",
                                           "<CurrentState>k__BackingField": "RunState",
                                           "<Run>k__BackingField": "Run"})
        except ReaderOff:
            memory.close()
            raise
        except Exception as error:  # a read that made no sense: same as a failed check
            memory.close()
            raise ReaderOff(f"unexpected memory layout ({error!r})")
        self.memory, self.mono = memory, mono
        self.statics = {n: base + statics[n] for n in ALLOWED_STATICS if n in statics}
        if len(self.statics) != len(ALLOWED_STATICS):
            self.close()
            raise ReaderOff("TheBazaar.Data has changed")
        self.enums: Dict[int, List[str]] = {}

    def close(self) -> None:
        if self.memory:
            self.memory.close()
        self.memory = None

    def _get(self, obj: int, name: str):
        """An instance field's value: a pointer for objects, a str for strings/guids, an int (or its enum name)."""
        offset, code, data = self.mono.field(self.mono.klass(obj), name)
        m = self.memory
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
        if not self.memory:
            raise ReaderOff("not attached")
        try:
            return self._snapshot()
        except ReaderOff:
            raise
        except Exception as error:
            raise ReaderOff(f"unexpected memory layout ({error!r})")

    def _snapshot(self) -> Snapshot:
        m = self.memory
        state = m.ptr(self.statics["<CurrentState>k__BackingField"])
        if not state:
            return Snapshot(None, None, ())
        name = self._get(state, "StateName")
        if name is not None and name not in RUN_STATES:
            raise ReaderOff(f"unknown screen {name}")
        encounter = self._get(state, "CurrentEncounterId")
        selection = self._get(state, "SelectionSet")
        ids: List[str] = []
        if selection:
            items, size = self._get(selection, "_items"), self._get(selection, "_size") or 0
            ids = [m.mono_string(m.ptr(items + 0x20 + 8 * i)) for i in range(min(size, 20))]
        offers = []
        if ids:
            by_id = self._entities()
            for instance in ids:
                card = by_id.get(instance)
                if not card:
                    offers.append(Offer(instance, None, None))
                    continue
                offers.append(Offer(instance, self._get(card, "TemplateId"), self._get(card, "Type")))
        return Snapshot(name, encounter, tuple(offers), self._level())

    def _level(self) -> Optional[int]:
        """Your level, from Run.Player.Attributes (a Dictionary of stat -> value with 16-byte entries, K-mem3)."""
        m, run = self.memory, self.memory.ptr(self.statics["<Run>k__BackingField"])
        player = self._get(run, "Player") if run else 0
        stats = self._get(player, "Attributes") if player else 0
        if not stats:
            return None
        entries, count = self._get(stats, "_entries"), self._get(stats, "_count") or 0
        for i in range(min(count, 200)):
            entry = entries + 0x20 + 16 * i
            if (m.i32(entry) or -1) >= 0 and m.i32(entry + 8) == LEVEL_STAT:  # a used entry (hash code >= 0)
                return m.i32(entry + 12)
        return None
