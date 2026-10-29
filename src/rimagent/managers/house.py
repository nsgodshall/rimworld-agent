"""House: a walled bedroom with a bed per colonist, so nobody sleeps outside.

The beds manager puts beds down outdoors on day one, which is quick, but every colonist then wakes
to "Slept outside" (-4) and "Slept in the cold" (-4). This plans one room near the base: wooden
walls, a door in the south wall, beds along the north wall. The game roofs an enclosed room by
itself. Once the indoor beds are built, each colonist is given one and the outdoor beds come down.

The room's place is remembered (`self.memory`): the map shows walls, not whose they are. After a
restart the memory is empty and a second house would be planned, so a run keeps one runtime.

The door needs open ground outside it. In run 20261029-074313 the house went up against an ancient
structure's wall (fogged when the site was picked), its door opened onto that wall, and Sparky,
inside when the last wall went up, starved 8 cells from 22 stored meals ("No path"). A site now
keeps a clear row south of the house, and a door that opens onto a wall or rock is moved to a side
that's open: the wall there is taken down, then a door goes in its place.
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
# What a doorway can't open onto (get_map_view legend meanings).
BLOCKING = ("wall", "natural rock", "unexplored", "water", "deep water")


def doors(outer: Rect) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """(door, the cell outside it) at the middle of each side: south first, north (behind the beds) last."""
    top, right = outer.z + outer.height - 1, outer.x + outer.width - 1
    mid_x, mid_z = outer.x + outer.width // 2, outer.z + outer.height // 2
    return [((mid_x, outer.z), (mid_x, outer.z - 1)), ((right, mid_z), (right + 1, mid_z)),
            ((outer.x, mid_z), (outer.x - 1, mid_z)), ((mid_x, top), (mid_x, top + 1))]


def layout(outer: Rect, beds: int, door: tuple[int, int] | None = None) -> list[dict]:
    """Walls round `outer`, a door (mid-south unless given), and `beds` south-facing beds along the north wall."""
    door = door or doors(outer)[0][0]
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
        door = self._check_door(ctx, outer, house)
        if door is None:
            return
        self._move_in(ctx, outer, colonists)
        if house.get("door"):
            self._put_door(ctx, tuple(house["door"]))
        # Repeating the same placements is safe (alreadySatisfied), and puts back any that were refused
        # or destroyed. Only while the house isn't finished: a pass is a handful of calls.
        if not self.memory.get("built"):
            result = ctx.rim.place_blueprint(placements=layout(outer, house["beds"], door),
                                             request_id=uuid.uuid4().hex).data or {}
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
        # Plain free ground only: no fields, zones, trees, items, buildings or blueprints. One row more
        # than the house, south of it: the doorstep stays clear.
        site = best_site(view, anchor, outer_w, outer_h + 1, good=_chars(view, "soil", "ground too poor"), min_fill=1.0)
        if site is None:
            ctx.raise_incident("noHouseSite", f"No free {outer_w}x{outer_h} ground for a house near {anchor}.", "warn")
            return None
        self.memory["house"] = {"outer": [site.x, site.z + 1, outer_w, outer_h], "beds": beds}
        return self.memory["house"]

    def _check_door(self, ctx: Context, outer: Rect, house: dict) -> tuple[int, int] | None:
        """The house's door, moved to another side if what's outside it blocks the way."""
        door = tuple(house.get("door") or doors(outer)[0][0])
        view = ctx.snapshot.view(Rect(outer.x - 1, outer.z - 1, outer.width + 2, outer.height + 2))
        blocking = "".join(view.symbol_for(m) or "" for m in BLOCKING)
        outside = dict(doors(outer)).get(door)
        if outside is None or not view.is_(outside, blocking):
            return door
        moved = next((d for d, out in doors(outer) if d != door and view[out] is not None and not view.is_(out, blocking)), None)
        if moved is None:
            ctx.raise_incident("houseSealed", f"Every side of the house at {outer} opens onto a wall or rock.", "halt",
                               door=door)
            return None
        house["door"] = list(moved)
        ctx.log(self.name, f"The door at {door} opens onto {view.legend.get(view[outside], view[outside])}: "
                           f"moving it to {moved}.", outer=str(outer))
        return moved

    def _put_door(self, ctx: Context, door: tuple[int, int]) -> None:
        """A moved door: the wall standing there comes down first, then the door blueprint goes in."""
        walls = [b for page in ctx.rim.pages(ctx.rim.list_buildings, category=WALL, limit=200)
                 for b in page.data.get("buildings") or []
                 if (b.get("def") or {}).get("defName") == WALL and (b["position"]["x"], b["position"]["z"]) == door]
        if walls:
            ctx.rim.designate(kind="deconstruct", thing_ids=[w["ids"]["id"] for w in walls])
            ctx.log(self.name, f"Taking down the wall at {door} for the door.")
            return
        result = ctx.rim.place_blueprint(placements=[{"def": DOOR, "stuff": STUFF, "x": door[0], "z": door[1],
                                                      "rotation": "north"}], request_id=uuid.uuid4().hex).data or {}
        if result.get("applied"):
            ctx.log(self.name, f"Placed a door blueprint at {door}.")
        for r in result.get("results") or []:
            if r.get("outcome") == "rejected":
                ctx.raise_incident("doorRejected", f"The house's door at {door} was refused: {r.get('reason')}", "warn")

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
