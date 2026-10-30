"""Read RimMCP's character map (get_map_view) by map coordinates instead of row/column indexes."""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import RimClient

# get_map_view's largest view.
MAX_VIEW = 40


@dataclass(frozen=True)
class Rect:
    """Cells x..x+width-1 by z..z+height-1, with (x, z) the south-west corner, as RimMCP's rects are."""

    x: int
    z: int
    width: int = 1
    height: int = 1

    def cells(self) -> Iterator[tuple[int, int]]:
        for z in range(self.z, self.z + self.height):
            for x in range(self.x, self.x + self.width):
                yield x, z

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return self.x + (self.width - 1) / 2, self.z + (self.height - 1) / 2

    def clamp(self, map_width: int, map_height: int) -> Rect:
        """The part of this rect inside a map of the given size."""
        x0, z0 = max(0, self.x), max(0, self.z)
        x1, z1 = min(map_width, self.x + self.width), min(map_height, self.z + self.height)
        return Rect(x0, z0, max(0, x1 - x0), max(0, z1 - z0))

    @classmethod
    def around(cls, x: float, z: float, width: int, height: int) -> Rect:
        return cls(round(x - (width - 1) / 2), round(z - (height - 1) / 2), width, height)

    def overlaps(self, other: Rect) -> bool:
        return not (
            other.x >= self.x + self.width or self.x >= other.x + other.width
            or other.z >= self.z + self.height or self.z >= other.z + other.height
        )

    def to_api(self) -> dict[str, int]:
        return {"x": self.x, "z": self.z, "width": self.width, "height": self.height}

    def grow(self, n: int) -> Rect:
        """This rect with `n` more cells on every side."""
        return Rect(self.x - n, self.z - n, self.width + 2 * n, self.height + 2 * n)


# A building's rotation as the way it faces. The live game turns a footprint rigidly about the building's
# cell: the simple research bench covers (-1..1, 0..1) facing north, (0..1, -1..1) facing east, (-1..1, -1..0)
# facing south and (-1..0, -1..1) facing west (check_placement), its researcher at (0,-1), (-1,0), (0,1), (1,0).
FACING = {"north": (0, 1), "east": (1, 0), "south": (0, -1), "west": (-1, 0)}


@dataclass(frozen=True)
class Frame:
    """Where a plan drawn north-up around its own (0, 0) lies on the map: mirrored east-west if `mirror`, then
    turned `turns` quarter turns clockwise, then moved so that its (0, 0) is map cell (x, z).

    The plans' rotatable buildings (beds, chairs, stove, bench) are all symmetric east-west facing north, so a
    mirrored one is the same building facing the mirrored way, and `rotation` says which. Tables, lamps and
    pots take only "north" (the game refuses the others): `rect` says where their cells go instead.
    """

    x: int = 0
    z: int = 0
    turns: int = 0
    mirror: bool = False

    def vector(self, dx: int, dz: int) -> tuple[int, int]:
        """An offset or direction in the plan, on the map."""
        if self.mirror:
            dx = -dx
        for _ in range(self.turns % 4):
            dx, dz = dz, -dx  # clockwise: north (0, 1) to east (1, 0)
        return dx, dz

    def cell(self, x: int, z: int) -> tuple[int, int]:
        dx, dz = self.vector(x, z)
        return self.x + dx, self.z + dz

    def rect(self, r: Rect) -> Rect:
        (ax, az), (bx, bz) = self.cell(r.x, r.z), self.cell(r.x + r.width - 1, r.z + r.height - 1)
        return Rect(min(ax, bx), min(az, bz), abs(bx - ax) + 1, abs(bz - az) + 1)

    def rotation(self, rotation: str) -> str:
        v = self.vector(*FACING[rotation])
        return next(name for name, d in FACING.items() if d == v)

    def moved(self, x: int, z: int) -> Frame:
        return Frame(x, z, self.turns, self.mirror)

    def to_list(self) -> list:
        return [self.x, self.z, self.turns, self.mirror]

    @classmethod
    def from_list(cls, data: list) -> Frame:
        return cls(int(data[0]), int(data[1]), int(data[2]) if len(data) > 2 else 0, bool(data[3]) if len(data) > 3 else False)


# The eight ways a plan can lie: four turns, each also mirrored.
ORIENTATIONS = [Frame(0, 0, turns, mirror) for mirror in (False, True) for turns in range(4)]


class MapView:
    """A grid of one character per cell. `view[x, z]` is the character at map cell (x, z), or None off the view."""

    def __init__(self, cells: dict[tuple[int, int], str], legend: dict[str, str]):
        self.cells = cells
        self.legend = legend

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> MapView:
        ox, oz = data["origin"]["x"], data["origin"]["z"]
        rows = data["rows"]
        height = data.get("height", len(rows))
        cells = {}
        # rows[0] is the north edge: z = origin.z + height - 1.
        for i, row in enumerate(rows):
            z = oz + height - 1 - i
            for j, ch in enumerate(row):
                cells[(ox + j, z)] = ch
        return cls(cells, dict(data.get("legend") or {}))

    def __getitem__(self, xz: tuple[int, int]) -> str | None:
        return self.cells.get(xz)

    def merge(self, other: MapView) -> MapView:
        return MapView({**self.cells, **other.cells}, {**self.legend, **other.legend})

    def count(self, rect: Rect, chars: str) -> int:
        """Cells of `rect` showing one of `chars`; cells off the view never match."""
        return sum(1 for xz in rect.cells() if self.is_(xz, chars))

    def is_(self, xz: tuple[int, int], chars: str) -> bool:
        """Whether the cell shows one of `chars` (not `"" in chars`, which is always true)."""
        ch = self.cells.get(xz)
        return ch is not None and ch in chars

    def find(self, chars: str) -> list[tuple[int, int]]:
        return [xz for xz, ch in self.cells.items() if ch in chars]

    def symbol_for(self, meaning: str) -> str | None:
        """The legend symbol whose meaning starts with `meaning`, e.g. symbol_for("rich soil")."""
        for symbol, text in self.legend.items():
            if text.startswith(meaning):
                return symbol
        return None


class Counts:
    """How many cells of any rect show one of `chars`, in four lookups: a summed-area table over the view.
    Cells off the view never match, as in MapView.count."""

    def __init__(self, view: MapView, chars: str):
        xs = [x for x, _ in view.cells] or [0]
        zs = [z for _, z in view.cells] or [0]
        self.x0, self.z0 = min(xs), min(zs)
        self.width, self.height = max(xs) - self.x0 + 1, max(zs) - self.z0 + 1
        # sums[j][i]: matching cells with x < x0 + i and z < z0 + j
        sums = [[0] * (self.width + 1) for _ in range(self.height + 1)]
        for j in range(self.height):
            row, below, run = sums[j + 1], sums[j], 0
            for i in range(self.width):
                run += view.is_((self.x0 + i, self.z0 + j), chars)
                row[i + 1] = below[i + 1] + run
        self.sums = sums

    def __call__(self, rect: Rect) -> int:
        i0, j0 = max(0, rect.x - self.x0), max(0, rect.z - self.z0)
        i1, j1 = min(self.width, rect.x + rect.width - self.x0), min(self.height, rect.z + rect.height - self.z0)
        if i1 <= i0 or j1 <= j0:
            return 0
        s = self.sums
        return s[j1][i1] - s[j0][i1] - s[j1][i0] + s[j0][i0]


def walking(view: MapView, start: tuple[float, float], passable: str) -> dict[tuple[int, int], float]:
    """Walking distance from `start` to every cell of the view a pawn can reach over `passable` cells: a step
    costs 1, a diagonal 1.41, and a diagonal can't cut the corner of something impassable (as pawns move).
    Starts from the passable cell nearest `start`."""
    ok = {c for c, ch in view.cells.items() if ch in passable}
    if not ok:
        return {}
    sx, sz = start
    first = min(ok, key=lambda c: ((c[0] - sx) ** 2 + (c[1] - sz) ** 2, c))
    dist = {first: 0.0}
    heap = [(0.0, first)]
    while heap:
        d, (x, z) = heapq.heappop(heap)
        if d > dist[(x, z)]:
            continue
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nxt = (x + dx, z + dz)
            if nxt not in ok or (dx and dz and ((x + dx, z) not in ok or (x, z + dz) not in ok)):
                continue
            nd = d + (1.41 if dx and dz else 1.0)
            if nd < dist.get(nxt, math.inf):
                dist[nxt] = nd
                heapq.heappush(heap, (nd, nxt))
    return dist


def scan(rim: RimClient, area: Rect, **kwargs: Any) -> MapView:
    """Read an area of any size by stitching get_map_view tiles (each at most 40x40)."""
    view = MapView({}, {})
    for z in range(area.z, area.z + area.height, MAX_VIEW):
        for x in range(area.x, area.x + area.width, MAX_VIEW):
            w = min(MAX_VIEW, area.x + area.width - x)
            h = min(MAX_VIEW, area.z + area.height - z)
            view = view.merge(MapView.from_data(rim.get_map_view(x=x, z=z, width=w, height=h, **kwargs).data))
    return view
