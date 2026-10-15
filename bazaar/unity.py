"""Where things are on screen, read from the game's own Unity objects (Unity 6000.3.11; found and checked against the
owner's screenshots 2026-10-14, see docs/MEMORY-READER.md "Positions"). Read-only, like memreader. Every function takes
a `read(address, size) -> bytes or None` and native addresses; the managed side (finding which objects) is
memreader's job. Rects are fractions of the game window: (left, top, right, bottom), y down."""
import math
import struct
from typing import Callable, List, Optional, Tuple

Read = Callable[[int, int], Optional[bytes]]
Rect = Tuple[float, float, float, float]

NATIVE = 0x10  # a UnityEngine.Object's m_CachedPtr: its native object
TRANSFORM_HIERARCHY, TRANSFORM_INDEX = 0x28, 0x30  # a Transform's place in its hierarchy
HIERARCHY_LOCAL, HIERARCHY_PARENTS, HIERARCHY_TRANSFORMS = 0x18, 0x20, 0x30  # per index: local TRS, parent, Transform*
LOCAL_STRIDE = 48  # position (4 floats), rotation (x y z w), scale (4 floats)
COMPONENT_GAMEOBJECT = 0x20
GAMEOBJECT_COMPONENTS, GAMEOBJECT_ACTIVE, GAMEOBJECT_NAME = 0x20, 0x46, 0x50  # components: (type, Component*) pairs
CAMERA_WORLD_TO_CLIP = 0xF0  # 4x4 floats, column-major
COLLIDER_CENTER, COLLIDER_SIZE = 0x60, 0x6C  # BoxCollider, local space
RECT_TRANSFORM_RECT = 0xB8  # RectTransform: x, y, width, height in its own (local) space
MAX_DEPTH = 64


def ptr(read: Read, address: int) -> int:
    raw = read(address, 8) if address else None
    return struct.unpack("<Q", raw)[0] if raw else 0


def i32(read: Read, address: int) -> Optional[int]:
    raw = read(address, 4) if address else None
    return struct.unpack("<i", raw)[0] if raw else None


def floats(read: Read, address: int, count: int) -> Optional[tuple]:
    raw = read(address, 4 * count) if address else None
    return struct.unpack(f"<{count}f", raw) if raw and len(raw) == 4 * count else None


def qmul(a: tuple, b: tuple) -> tuple:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def qrot(q: tuple, v: tuple) -> tuple:
    x, y, z, w = q
    vx, vy, vz = v
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx


def compose(chain: List[tuple]) -> tuple:
    """World (position, rotation, scale) from local (position, rotation, scale) entries, root first."""
    pos, rot, scale = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0)
    for p, q, s in chain:
        moved = qrot(rot, (p[0] * scale[0], p[1] * scale[1], p[2] * scale[2]))
        pos = (pos[0] + moved[0], pos[1] + moved[1], pos[2] + moved[2])
        rot, scale = qmul(rot, q), (scale[0] * s[0], scale[1] * s[1], scale[2] * s[2])
    return pos, rot, scale


def world(read: Read, transform: int) -> Optional[tuple]:
    """A native Transform's world (position, rotation, scale), by walking its parents; None if it makes no sense."""
    hierarchy, index = ptr(read, transform + TRANSFORM_HIERARCHY), i32(read, transform + TRANSFORM_INDEX)
    if not hierarchy or index is None:
        return None
    local, parents = ptr(read, hierarchy + HIERARCHY_LOCAL), ptr(read, hierarchy + HIERARCHY_PARENTS)
    chain = []
    while index is not None and index >= 0:
        values = floats(read, local + LOCAL_STRIDE * index, 12)
        if values is None or len(chain) >= MAX_DEPTH or not all(math.isfinite(v) for v in values):
            return None
        chain.append((values[0:3], values[4:8], values[8:11]))
        index = i32(read, parents + 4 * index)
    return compose(chain[::-1])


def project(matrix: tuple, point: tuple) -> Optional[Tuple[float, float]]:
    """A world point through a camera's world->clip matrix: (fraction across, fraction down) the game window."""
    x, y, z = point
    g = lambda i, j: matrix[j * 4 + i]  # noqa: E731 - column-major
    cx = g(0, 0) * x + g(0, 1) * y + g(0, 2) * z + g(0, 3)
    cy = g(1, 0) * x + g(1, 1) * y + g(1, 2) * z + g(1, 3)
    cw = g(3, 0) * x + g(3, 1) * y + g(3, 2) * z + g(3, 3)
    if abs(cw) < 1e-6:
        return None
    return (cx / cw + 1) / 2, 1 - (cy / cw + 1) / 2


def camera_matrix(read: Read, camera: int) -> Optional[tuple]:
    matrix = floats(read, camera + CAMERA_WORLD_TO_CLIP, 16)
    return matrix if matrix and all(math.isfinite(v) for v in matrix) else None


def faces_camera(matrix: tuple, placed: tuple) -> bool:
    """Is a card's face turned toward the camera? Cards lie in their local x-z plane, and unrotated they face it
    (your board, the shop, an open stash: recorded 2026-10-15 - the stash opens by flipping the shop's panel 180
    degrees about x, its cards on the back). So: does its face wind on screen the way it would unrotated?"""
    pos, rot, _scale = placed

    def winding(q: tuple) -> float:
        points = []
        for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            corner = qrot(q, (sx, 0.0, sz))
            point = project(matrix, (pos[0] + corner[0], pos[1] + corner[1], pos[2] + corner[2]))
            if point is None:
                return 0.0
            points.append(point)
        return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))

    return winding(rot) * winding((0.0, 0.0, 0.0, 1.0)) > 0


def box_rect(read: Read, matrix: tuple, collider: int, transform: int,
             placed: Optional[tuple] = None) -> Optional[Rect]:
    """A BoxCollider's 8 corners, placed by its transform (or `placed`, its world pose already read) and projected:
    the box's rect on screen."""
    center, size = floats(read, collider + COLLIDER_CENTER, 3), floats(read, collider + COLLIDER_SIZE, 3)
    placed = placed or world(read, transform)
    if not center or not size or not placed:
        return None
    pos, rot, scale = placed
    points = []
    for sx in (-0.5, 0.5):
        for sy in (-0.5, 0.5):
            for sz in (-0.5, 0.5):
                corner = qrot(rot, ((center[0] + size[0] * sx) * scale[0], (center[1] + size[1] * sy) * scale[1],
                                    (center[2] + size[2] * sz) * scale[2]))
                point = project(matrix, (pos[0] + corner[0], pos[1] + corner[1], pos[2] + corner[2]))
                if point is None:
                    return None
                points.append(point)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def ui_rect(read: Read, rect_transform: int, canvas: Tuple[float, float]) -> Optional[Rect]:
    """A RectTransform on a screen-space canvas (its world units are the canvas's pixels, y up) as fractions of
    the canvas (width, height)."""
    placed, rect = world(read, rect_transform), floats(read, rect_transform + RECT_TRANSFORM_RECT, 4)
    if not placed or not rect or not canvas[0] or not canvas[1]:
        return None
    (px, py, _), _, (sx, sy, _) = placed
    x, y, w, h = rect
    left, right, bottom, top = px + x * sx, px + (x + w) * sx, py + y * sy, py + (y + h) * sy
    return left / canvas[0], 1 - top / canvas[1], right / canvas[0], 1 - bottom / canvas[1]


def canvas_size(read: Read, rect_transform: int) -> Tuple[float, float]:
    """A canvas's size in its world units (its rect times its scale)."""
    placed, rect = world(read, rect_transform), floats(read, rect_transform + RECT_TRANSFORM_RECT, 4)
    if not placed or not rect:
        return 0.0, 0.0
    return abs(rect[2] * placed[2][0]), abs(rect[3] * placed[2][1])


def game_object(read: Read, component: int) -> int:
    return ptr(read, component + COMPONENT_GAMEOBJECT)


def transform_of(read: Read, component: int) -> int:
    """A component's GameObject's Transform (always the GameObject's first component)."""
    go = game_object(read, component)
    return ptr(read, ptr(read, go + GAMEOBJECT_COMPONENTS) + 8) if go else 0


def name_of(read: Read, transform: int, cstr: Callable[[int], Optional[str]]) -> Optional[str]:
    go = game_object(read, transform)
    return cstr(ptr(read, go + GAMEOBJECT_NAME)) if go else None


def active(read: Read, transform: int) -> bool:
    """The GameObject's own switch. ⚠️ Only some pieces are hidden this way (the sell box is; the keyword boxes and
    an empty bottom box are not - 2026-10-14)."""
    raw = read(game_object(read, transform) + GAMEOBJECT_ACTIVE, 1)
    return bool(raw and raw[0])


def children(read: Read, transform: int, scan: int = 400) -> List[int]:
    """A Transform's direct children (they follow it in its hierarchy's index order)."""
    hierarchy, index = ptr(read, transform + TRANSFORM_HIERARCHY), i32(read, transform + TRANSFORM_INDEX)
    if not hierarchy or index is None:
        return []
    parents, table = ptr(read, hierarchy + HIERARCHY_PARENTS), ptr(read, hierarchy + HIERARCHY_TRANSFORMS)
    out, k = [], index + 1
    while k <= index + scan:
        chunk = read(parents + 4 * k, 4 * 64)  # the hierarchy's end can be unreadable: then entry by entry
        values = struct.unpack("<64i", chunk) if chunk else (i32(read, parents + 4 * k),)
        for parent in values:
            if parent is None or parent < index:  # past this transform's subtree (or the hierarchy's end)
                return out
            if parent == index:
                out.append(ptr(read, table + 8 * k))
            k += 1
    return out
