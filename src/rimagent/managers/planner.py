"""Planner: where the whole base goes, decided once on the first day, so what's built early ends up indoors.

Each manager used to pick its own spot near the stockpile: in run 20261030-112346-s1 the house and wing stood
roofed, and everything else stood in the open by day 8: four stockpiles (everything in them deteriorating), the
stove, the research bench (rain and dark slow the work) and the butcher spot. Nothing could be walled in later,
because nothing had been left room for walls.

So the layout is fixed here, around one origin, before anything is placed. North at the top:

    #########################  ########
    #  common  #  bed #  bed #  # bed #  bed #     house (house.plan) and wing, doors south
    ###+######+####+####+#####  ###+####+###
    .......................................     doorstep row, kept clear
    #+####################+#######+####
    #  S  #  pantry  general  #  B  #           kitchen (S stove), store (two stockpiles),
    #     +                   +     #           workshop (B research bench): doors north,
    #L    #                   #     #           between the rooms, and one south from the store
    #############+##############
    .............                               doorstep

The stockpiles go in the store, the stove in the kitchen and the bench in the workshop from day one (food,
kitchen and research read `ctx.board["plan"]`); the house and wing take their origins from it. The core's walls,
doors and lamps (CoreManager) go up once the house's shell stands: colonists sleep indoors first.

The plan is remembered, and on a restart found again from the store's general stockpile, which is named after
the plan's origin. Its footprint is reserved: Snapshot.view shows open ground there as reserved, so fields,
barricades, dumps and beds placed by other managers keep out of it. Without a site, or in a colony that already
has a stockpile not placed by this, there's no plan and every manager places things as before.
"""

from __future__ import annotations

import re
from typing import Any

from rimsdk.mapview import Rect

from ..manager import Context, Manager
from .food import _chars, best_site
from .house import HouseManager, place, standing_materials
from .materials import STEEL, WOOD, pick

WINDOW = 70          # side of the square around the colonists searched for a site (scan stitches views)
ROOM_DEPTH = 6       # interior, north to south, of the kitchen, store and workshop
SIDE_WIDTH = 5       # interior width of the kitchen and of the workshop
STORE_WIDTH = 12     # interior width of the store: a pantry and a general stockpile, 6x6 each
CORE_WIDTH = 1 + SIDE_WIDTH + 1 + STORE_WIDTH + 1 + SIDE_WIDTH + 1  # 26
CORE_HEIGHT = ROOM_DEPTH + 2
LABEL = re.compile(r"Store (\d+),(\d+)")  # the general stockpile's name: the plan's origin


def layout(origin: tuple[int, int]) -> dict[str, Any]:
    """Every part of the base whose core's south-west outer corner is `origin`."""
    x0, z0 = origin
    kitchen = Rect(x0 + 1, z0 + 1, SIDE_WIDTH, ROOM_DEPTH)
    store = Rect(x0 + SIDE_WIDTH + 2, z0 + 1, STORE_WIDTH, ROOM_DEPTH)
    workshop = Rect(store.x + STORE_WIDTH + 1, z0 + 1, SIDE_WIDTH, ROOM_DEPTH)
    top = z0 + CORE_HEIGHT - 1
    east = x0 + CORE_WIDTH - 1
    walls = {(x, z) for x in range(x0, east + 1) for z in (z0, top)}
    walls |= {(x, z) for z in range(z0, top + 1) for x in (x0, kitchen.x + SIDE_WIDTH, store.x + STORE_WIDTH, east)}
    middle = z0 + 3
    doors = [
        (store.x + 5, top),          # north, onto the doorstep row the house shares
        (store.x + 6, z0),           # south: haulers from the fields, and out to the butcher spot
        (store.x - 1, middle),       # kitchen <-> store
        (workshop.x - 1, middle),    # workshop <-> store
        (kitchen.x, top),            # kitchen north, beside the stove
        (workshop.x, top),           # workshop north, beside the bench
    ]
    house_origin = (x0, top + 2)  # the doorstep row (top + 1) between
    return {
        "origin": [x0, z0],
        "label": f"Store {x0},{z0}",  # what the food manager names the general stockpile (see recall)
        "core": Rect(x0, z0, CORE_WIDTH, CORE_HEIGHT),
        "kitchen": kitchen,
        "store": store,
        "workshop": workshop,
        "pantry": Rect(store.x, store.z, STORE_WIDTH // 2, ROOM_DEPTH),
        "general": Rect(store.x + STORE_WIDTH // 2, store.z, STORE_WIDTH // 2, ROOM_DEPTH),
        # A FueledStove facing north covers (x-1..x+1, z) and its cook stands at (x, z-1); the simple research
        # bench covers (x-1..x+1, z..z+1), its researcher at (x, z-1) (check_placement in game). Both against the
        # north wall, clear of the doors beside them.
        "stove": (kitchen.x + 2, top - 1),
        "bench": (workshop.x + 2, top - 2),
        "lamps": [(kitchen.x + SIDE_WIDTH - 1, kitchen.z)],  # the bench has its own (research.light_bench)
        "walls": sorted(walls - set(doors)),
        "doors": doors,
        "house": house_origin,
        # The house is 20 wide (house.plan with 3 bedrooms); the wing's own walls start beside it, not on its
        # east wall: two blueprints of different materials on one cell would be a replacement.
        "wing": (house_origin[0] + 20, house_origin[1]),
        # With a row of margin: the store's south doorstep, and room to walk round.
        "footprint": Rect(x0 - 1, z0 - 2, 31, 18),
    }


class PlannerManager(Manager):
    name = "planner"
    priority = 1  # before everything that places anything (after defense)
    every_hours = 1

    def update(self, ctx: Context) -> None:
        p = ctx.board.get("plan")
        if p is None:
            p = self.recall(ctx) or self.choose(ctx)
        if p is None:
            return
        ctx.board["plan"] = p
        reserved = ctx.board.setdefault("reserved", set())
        if not reserved:
            reserved.update(p["footprint"].cells())
        ctx.snapshot.reserved = reserved

    def recall(self, ctx: Context) -> dict[str, Any] | None:
        """The plan, from memory or from the store's general stockpile, which the food manager names after the
        plan's origin ("Store 34,46"): the name is saved with the game. None for a colony whose stockpiles
        weren't placed by a plan (managers then place things as before)."""
        if self.memory.get("origin"):
            return layout(tuple(self.memory["origin"]))
        for zone in ctx.snapshot.zones_of("stockpile"):
            m = LABEL.fullmatch(zone.get("label") or "")
            if m:
                p = layout((int(m.group(1)), int(m.group(2))))
                self.memory["origin"] = p["origin"]
                ctx.log(self.name, f"Found the base plan again from the store at {p['store']}.")
                return p
        return None

    def choose(self, ctx: Context) -> dict[str, Any] | None:
        if self.memory.get("none"):
            return None
        if ctx.snapshot.zones_of("stockpile"):  # too late: things are placed already
            self.memory["none"] = True
            ctx.log(self.name, "This colony's stockpiles weren't placed by a plan: managers place things as before.")
            return None
        center = ctx.snapshot.base_center
        if center is None:
            return None
        cx, cz = round(center[0]), round(center[1])
        view = ctx.snapshot.view(Rect.around(cx, cz, WINDOW, WINDOW))
        foot = layout((0, 0))["footprint"]
        plain = _chars(view, "soil", "ground too poor")
        # Open ground or trees (the builders cut those), and what moves or is hauled off: items, animals and the
        # colonists themselves. Not rock, water, buildings or fog. The landing site is strewn with the drop pods'
        # items: in the replay of s1 (run 20261030-121711) no 31x18 block within 35 cells was free of them.
        # Open ground scores higher, and rich soil is left for the fields.
        passing = "".join(sym for sym, text in view.legend.items() if text.startswith(("item", "animal")) or "(Human" in text)
        site = best_site(view, (cx, cz), foot.width, foot.height, good=plain + _chars(view, "rich soil") +
                         (view.symbol_for("tree") or "t") + passing, bonus=plain, min_fill=1.0)
        if site is None:
            self.memory["none"] = True
            ctx.raise_incident("noBaseSite", f"No free {foot.width}x{foot.height} ground for the base near "
                               f"({cx}, {cz}): managers place things as before.", "warn")
            return None
        p = layout((site.x - foot.x, site.z - foot.z))
        self.memory["origin"] = p["origin"]
        # Trees in the footprint come down now: wood for the beds, and nothing in the way of walls or stockpiles.
        ctx.rim.designate(kind="chopWood", rects=[p["footprint"].to_api()])
        ctx.log(self.name, f"Planned the base: core {p['core']} (kitchen, store, workshop), house at {p['house']}, "
                           f"wing at {p['wing']}.", footprint=str(p["footprint"]))
        return p


class CoreManager(HouseManager):
    """The walls, doors and lamps of the plan's kitchen, store and workshop, once the house's shell stands.

    Built the way the house is (house.HouseManager): walls of what's in stock, placed again each pass until
    built, a stall switches the waiting blueprints to the other material, and what stands is never placed again
    in another material.
    """

    name = "core"
    priority = 9  # after the house (8): its shell first
    every_hours = 3
    alerts = ()
    STAGE_KEY = "core_stage"

    def update(self, ctx: Context) -> None:
        p = ctx.board.get("plan")
        if p is None or ctx.board.get("house_stage", 0) < 2:
            return  # the house's walls first: sleeping outdoors costs more than things weathering
        core = self.memory.get("core")
        if core is None:
            need = 5 * len(p["walls"]) + 25 * len(p["doors"])
            core = {"walls": pick(ctx, need, (STEEL, WOOD))}
            self.memory["core"] = core
            ctx.log(self.name, f"Walling in the kitchen, store and workshop at {p['core']} with {core['walls']}.",
                    needs=need)
        if self.memory.get("built"):
            ctx.board[self.STAGE_KEY] = 2
            return

        def put(def_: str, xz: tuple[int, int], stuff: str | None = None) -> dict:
            return {"def": def_, "x": xz[0], "z": xz[1], "rotation": "north", **({"stuff": stuff} if stuff else {})}

        stages = [[put("Wall", xz, core["walls"]) for xz in p["walls"]] + [put("Door", xz, core["walls"]) for xz in p["doors"]],
                  [put("TorchLamp", xz) for xz in p["lamps"]]]
        overrides = core.get("overrides") or {}
        standing = standing_materials(ctx)
        results, applied = [], 0
        for number, stage in enumerate(stages):
            ctx.board[self.STAGE_KEY] = number
            stage = [{**item, "stuff": overrides.get(f"{item['def']}@{item['x']},{item['z']}", item.get("stuff"))}
                     if item.get("stuff") else item for item in stage]
            stage = [{**item, "stuff": standing[(item["def"], item["x"], item["z"])]}
                     if standing.get((item["def"], item["x"], item["z"])) and item.get("stuff") else item for item in stage]
            stage_results, stage_applied = place(ctx, stage)
            results, applied = results + stage_results, applied + stage_applied
            if not all(r.get("state") == "built" for r in stage_results):
                self._unstall(ctx, core, number, stage_results)
                break
            self.memory.setdefault("stage_since", {}).pop(str(number), None)
        if applied:
            ctx.log(self.name, f"Placed {applied} blueprints for the kitchen, store and workshop.")
        rejected = [{k: r.get(k) for k in ("def", "x", "z", "reason")} for r in results if r.get("outcome") == "rejected"]
        if rejected and rejected != self.memory.get("rejected"):
            ctx.raise_incident("coreRejected", f"{len(rejected)} blueprints of the kitchen, store and workshop were "
                               f"refused at {p['core']}.", "warn", rejected=rejected[:10])
        self.memory["rejected"] = rejected
        if len(results) == sum(map(len, stages)) and all(r.get("outcome") == "alreadySatisfied" and r.get("state") == "built"
                                                          for r in results):
            self.memory["built"] = True
            ctx.board[self.STAGE_KEY] = 2
            ctx.log(self.name, f"The kitchen, store and workshop at {p['core']} are walled in.")
