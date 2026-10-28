"""Read RimMCP's character map (get_map_view) by map coordinates instead of row/column indexes."""

from __future__ import annotations

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


def scan(rim: RimClient, area: Rect, **kwargs: Any) -> MapView:
    """Read an area of any size by stitching get_map_view tiles (each at most 40x40)."""
    view = MapView({}, {})
    for z in range(area.z, area.z + area.height, MAX_VIEW):
        for x in range(area.x, area.x + area.width, MAX_VIEW):
            w = min(MAX_VIEW, area.x + area.width - x)
            h = min(MAX_VIEW, area.z + area.height - z)
            view = view.merge(MapView.from_data(rim.get_map_view(x=x, z=z, width=w, height=h, **kwargs).data))
    return view
