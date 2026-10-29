"""House: a walled bedroom with a bed per colonist, so nobody sleeps outside.

The beds manager puts beds down outdoors on day one, which is quick, but every colonist then wakes
to "Slept outside" (-4) and "Slept in the cold" (-4). This plans one room near the base: wooden
walls, a door in the south wall, beds along the north wall. The game roofs an enclosed room by
itself. Once the indoor beds are built, each colonist is given one and the outdoor beds come down.

The room's place is remembered (`self.memory`): the map shows walls, not whose they are. After a
restart the memory is empty and a second house would be planned, so a run keeps one runtime.
"""

from __future__ import annotations

import uuid

from rimsdk import errors
from rimsdk.mapview import Rect

from ..manager import Context, Manager
from .beds import BED, STUFF, base_anchor
from .food import _chars, best_site

WALL, DOOR = "Wall", "Door"
WINDOW = 40         # side of the square around the base searched for a site
INTERIOR_DEPTH = 4  # north to south: a bed (2 cells) and room to walk past it


def layout(outer: Rect, beds: int) -> list[dict]:
    """Walls round `outer`, a door mid-south, and `beds` south-facing beds along the north wall."""
    door = (outer.x + outer.width // 2, outer.z)
    top, right = outer.z + outer.height - 1, outer.x + outer.width - 1
    walls = [(x, z) for x, z in outer.cells() if x in (outer.x, right) or z in (outer.z, top)]
    placements = [{"def": DOOR if c == door else WALL, "stuff": STUFF, "x": c[0], "z": c[1], "rotation": "north"}
                  for c in walls]
    # A south-facing bed at (x, z) covers (x, z) and (x, z - 1); a free column either side.
    placements += [{"def": BED, "stuff": STUFF, "x": outer.x + 2 + i, "z": top - 1, "rotation": "south"}
                   for i in range(beds)]
    return placements


def interior(outer: Rect) -> Rect:
    return Rect(outer.x + 1, outer.z + 1, outer.width - 2, outer.height - 2)


class HouseManager(Manager):
    name = "house"
    priority = 22  # after beds (day-one beds outdoors), before the kitchen and dining set take the space
    every_hours = 6

    def update(self, ctx: Context) -> None:
        snap = ctx.snapshot
        colonists = snap.colonists
        if not colonists:
            return
        house = self.memory.get("house")
        if house is None:
            house = self._plan(ctx, len(colonists))
            if house is None:
                return
        outer = Rect(*house["outer"])
        self._move_in(ctx, outer, colonists)
        # Repeating the same placements is safe (alreadySatisfied), and puts back any that were refused
        # or destroyed. Only while the house isn't finished: a pass is a handful of calls.
        if not self.memory.get("built"):
            result = ctx.rim.place_blueprint(placements=layout(outer, house["beds"]), request_id=uuid.uuid4().hex).data or {}
            rejected = [r for r in result.get("results") or [] if r.get("outcome") == "rejected"]
            if result.get("applied"):
                ctx.log(self.name, f"Placed {result['applied']} house blueprints at {outer}.")
            if rejected:
                ctx.raise_incident("houseRejected", f"{len(rejected)} house blueprints were refused at {outer}.", "warn",
                                   rejected=[{k: r.get(k) for k in ("def", "x", "z", "reason")} for r in rejected][:10])

    def _plan(self, ctx: Context, beds: int) -> dict | None:
        snap = ctx.snapshot
        anchor = base_anchor(ctx)
        if anchor is None:
            return None
        outer_w, outer_h = beds + 4, INTERIOR_DEPTH + 2  # walls, a free column each side of the beds
        view = snap.view(Rect.around(*anchor, WINDOW, WINDOW))
        # Plain free ground only: no fields, zones, trees, items, buildings or blueprints.
        site = best_site(view, anchor, outer_w, outer_h, good=_chars(view, "soil", "ground too poor"), min_fill=1.0)
        if site is None:
            ctx.raise_incident("noHouseSite", f"No free {outer_w}x{outer_h} ground for a house near {anchor}.", "warn")
            return None
        self.memory["house"] = {"outer": [site.x, site.z, site.width, site.height], "beds": beds}
        return self.memory["house"]

    def _move_in(self, ctx: Context, outer: Rect, colonists: list[dict]) -> None:
        inside = interior(outer)
        beds = ctx.rim.list_buildings(category="bed").data.get("buildings") or []
        indoor = sorted((b for b in beds if (b["position"]["x"], b["position"]["z"]) in set(inside.cells())),
                        key=lambda b: b["position"]["x"])
        if len(indoor) < len(colonists):
            return  # not built yet: keep sleeping where they do
        self.memory["built"] = True
        # Nothing shows who owns which bed, so give each colonist theirs; assigning again is alreadySatisfied.
        pairs = {c["ids"]["id"]: b["ids"]["id"] for c, b in zip(sorted(colonists, key=lambda c: c["ids"]["id"]), indoor)}
        if self.memory.get("assigned") != pairs:
            for pawn_id, bed_id in pairs.items():
                try:
                    ctx.rim.assign_owner(bed_id, pawn_id=pawn_id)
                except errors.Conflict as exc:
                    ctx.raise_incident("bedRefused", f"{pawn_id} can't have bed {bed_id}: {exc.message}", "warn")
                    return
            self.memory["assigned"] = pairs
            ctx.log(self.name, f"{len(pairs)} colonists moved into the house at {outer}.")
        outdoor = [b["ids"]["id"] for b in beds if b not in indoor]
        if outdoor:
            ctx.rim.designate(kind="deconstruct", thing_ids=outdoor)
            ctx.log(self.name, f"Taking down {len(outdoor)} beds outside the house.")
