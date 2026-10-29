"""One cycle's view of the colony: each read happens at most once, on first use."""

from __future__ import annotations

from functools import cached_property
from typing import Any

from rimsdk import RimClient
from rimsdk.mapview import MapView, Rect, scan


class Snapshot:
    def __init__(self, rim: RimClient):
        self.rim = rim

    @cached_property
    def colony(self) -> dict[str, Any]:
        return self.rim.get_colony_status().data

    @cached_property
    def tick(self) -> int:
        return self.colony["time"]["ticksGame"]

    @cached_property
    def map_size(self) -> tuple[int, int]:
        size = self.colony["map"]["size"]
        return size["x"], size["z"]

    @cached_property
    def colonists(self) -> list[dict[str, Any]]:
        pawns = self.rim.list_pawns(filter="colonists").data["pawns"]
        return [p for p in pawns if not p.get("dead")]

    @cached_property
    def base_center(self) -> tuple[float, float] | None:
        """Mean colonist position: until there's a real base, the colony is wherever its people are."""
        spots = [p["position"] for p in self.colonists if p.get("position")]
        if not spots:
            return None
        return sum(p["x"] for p in spots) / len(spots), sum(p["z"] for p in spots) / len(spots)

    @cached_property
    def zones(self) -> list[dict[str, Any]]:
        return self.rim.list_zones().data["zones"]

    def zones_of(self, kind: str) -> list[dict[str, Any]]:
        return [z for z in self.zones if z.get("kind") == kind]

    @cached_property
    def food_days(self) -> float | None:
        """Days of stored food at the current eating rate; None before anyone has eaten."""
        food = self.colony.get("food") or {}
        return food.get("daysLeft") if food.get("eatenPerDay") else None

    @cached_property
    def alerts(self) -> list[dict[str, Any]]:
        """The game's active alerts: type, label, priority (Critical/High/Medium), culprits."""
        return self.rim.get_events().data.get("alerts") or []

    @cached_property
    def resources(self) -> dict[str, int]:
        """Stock counts by defName (list_resources): what there is to build with."""
        rows = self.rim.list_resources().data.get("resources") or []
        return {r["defName"]: r.get("count", 0) for r in rows if r.get("defName")}

    @cached_property
    def hostiles(self) -> int:
        return (self.colony.get("threats") or {}).get("hostiles", 0)

    def view(self, area: Rect) -> MapView:
        """The character map of an area, clamped to the map (not cached: managers change it)."""
        return scan(self.rim, area.clamp(*self.map_size))
