"""Planner: where the whole base goes, decided once on the first day, so what's built early ends up indoors.

Each manager used to pick its own spot near the stockpile: in run 20261030-112346-s1 the house and wing stood
roofed, and everything else stood in the open by day 8: four stockpiles (everything in them deteriorating), the
stove, the research bench (rain and dark slow the work) and the butcher spot. Nothing could be walled in later,
because nothing had been left room for walls.

So the layout is fixed here, drawn north-up around its own (0, 0), the core's south-west corner:

    #############################
    #common#bed#bed#bed##bed#bed#    house (house.plan: common room, 3 bedrooms) and wing (2, its own walls)
    #      #   #   #   ##   #   #
    ###+#####+###+###+####+###+##
    ..*.*...*.*.*.*.*.*..*.*.*.*.    the street, three rows: plant pots (*) either side of each doorstep
    .............................    (GardenManager), the middle row kept clear
    *.*..........*.*..........*.*
    #+############+############+#
    # SSS  #  stockpiles #  BBB #    kitchen (S stove), store (two stockpiles), workshop (B research bench)
    #      +             +      #
    ##############+##############
                  .                  the back door: fields, butcher spot, dump and graves lie that way

Core and house row are both 29 wide, the store's doors on the middle line, the kitchen and workshop mirror
images: a base that reads as one building. The stockpiles go in the store, the stove in the kitchen and the bench
in the workshop from day one (food, kitchen and research read `ctx.board["plan"]`); the house and wing take
their origins and frame from it. The core's walls, doors and lamps (CoreManager) go up once the house's shell
stands: colonists sleep indoors first.

Where it goes is a search (best_frame): each of the eight ways to lay the plan (four turns, mirrored or not) at
every place in an 80x80 view, each scored in constant time with summed-area tables (mapview.Counts). A site must
be clear ground (trees and loose items allowed) within a cell of every wall, and walkable from the colonists.
Its score: walking distance (not a straight line: a river or a ridge between counts), trees to fell, rich soil
built over, open ground around it to grow into, farmland behind the back door, and distance from the map edge.

The plan is remembered, and on a restart found again from the store's general stockpile, named after the frame
("Store 34,46 r1m": origin, quarter turns, mirrored). Its footprint is reserved: Snapshot.view shows open
ground there as reserved, so fields, barricades, dumps and beds placed by other managers keep out of it. Without
a site, or in a colony that already has a stockpile not placed by this, there's no plan and every manager places
things as before.
"""

from __future__ import annotations

import re
from typing import Any

from rimsdk.mapview import ORIENTATIONS, Counts, Frame, MapView, Rect, walking

from ..manager import Context, Manager
from .food import _chars
from .house import (
    BEDROOMS,
    WING_BEDROOMS,
    HouseManager,
    place,
    plan,
    standing_materials,
)
from .materials import STEEL, WOOD, WOOD_RESERVE, pick

WINDOW = 80          # side of the square around the colonists searched for a site: 2x2 map views
ROOM_DEPTH = 6       # interior, north to south, of the kitchen, store and workshop
SIDE_WIDTH = 6       # interior width of the kitchen and of the workshop
STORE_WIDTH = 13     # interior width of the store: a pantry 6x6 and a general stockpile 7x6
PANTRY_WIDTH = 6
CORE_WIDTH = 1 + SIDE_WIDTH + 1 + STORE_WIDTH + 1 + SIDE_WIDTH + 1  # 29: as wide as the house and wing
CORE_HEIGHT = ROOM_DEPTH + 2
STREET = 3           # rows between the core and the house: the doorsteps, and a clear row between them
HOUSES_Z = CORE_HEIGHT + STREET
MIDDLE = CORE_WIDTH // 2  # the store's doors, and the plan's line of symmetry
# What must be clear ground: every building and a cell round them (doorsteps, a way round); and what's reserved,
# a second cell round that.
INNER = Rect(-1, -1, CORE_WIDTH + 2, HOUSES_Z + 6 + 2)
FOOTPRINT = INNER.grow(1)
BACK = Rect(-1, -21, CORE_WIDTH + 2, 19)  # behind the back door, where the fields go
FIELDS = (MIDDLE, -10)                    # the fields' anchor: just behind the footprint
BUTCHER = (3, -5)                         # the butcher spot: behind the kitchen, beside the fields
LABEL = re.compile(r"Store (\d+),(\d+) r([0-3])(m?)")  # the general stockpile's name: the plan's frame

# The site's score (best_frame): per cell of walking from the colonists, of each kind of ground in the way, of
# room around. A cell of walking costs as much as a tree and a half: the old search's straight-line 0.8.
WALK, TREE, RICH, ITEM = 0.8, 0.5, 1.0, 0.2
ROOM, ROOM_REACH = 0.02, 10  # each cell of open ground within ROOM_REACH (1400 cells: up to 28)
FARMLAND = 0.03              # each cell of soil behind the back door (589 cells: up to 18)
EDGE, EDGE_REACH = 1.0, 12   # raids walk in from the map edge
# Pots go up only with this much wood in hand beyond the reserve: they're for looks, after everything else.
GARDEN_SPARE = 400


def layout(frame: Frame) -> dict[str, Any]:
    """Every part of the base, where `frame` lays it on the map. Rects and cells are map cells; "house" and
    "wing" are origins in the plan, for house.plan with the same frame."""
    kitchen = Rect(1, 1, SIDE_WIDTH, ROOM_DEPTH)
    store = Rect(SIDE_WIDTH + 2, 1, STORE_WIDTH, ROOM_DEPTH)
    workshop = Rect(store.x + STORE_WIDTH + 1, 1, SIDE_WIDTH, ROOM_DEPTH)
    top, east = CORE_HEIGHT - 1, CORE_WIDTH - 1
    walls = {(x, z) for x in range(CORE_WIDTH) for z in (0, top)}
    walls |= {(x, z) for z in range(CORE_HEIGHT) for x in (0, kitchen.x + SIDE_WIDTH, store.x + STORE_WIDTH, east)}
    middle = 3
    north_doors = [(kitchen.x, top), (MIDDLE, top), (workshop.x + SIDE_WIDTH - 1, top)]
    doors = north_doors + [
        (MIDDLE, 0),                 # south: haulers from the fields, and out to the butcher spot
        (store.x - 1, middle),       # kitchen <-> store
        (workshop.x - 1, middle),    # workshop <-> store
    ]
    house, wing = (0, HOUSES_Z), (20, HOUSES_Z)  # the house is 20 wide (3 bedrooms), the wing 9 (2)
    # A FueledStove facing north covers (x-1..x+1, z) and its cook stands at (x, z-1); the simple research
    # bench covers (x-1..x+1, z..z+1), its researcher at (x, z-1) (check_placement in game). Both against the
    # north wall, clear of the door in the corner beside them, mirror images of each other, and a lamp beside
    # each (the bench's is research.light_bench's).
    stove, bench = (kitchen.x + 2, top - 1), (east - 3, top - 2)
    # Plant pots beside each doorstep on the street (the cells in front of the doors stay clear).
    house_doors = plan(house, BEDROOMS)["doors"] + plan(wing, WING_BEDROOMS, common_room=False)["doors"]
    fronts = {(x, top + 1) for x, _ in north_doors} | {(x, z - 1) for x, z in house_doors}
    garden = sorted({(x + dx, z) for x, z in fronts for dx in (-1, 1)} - fronts)
    cell = frame.cell
    return {
        "frame": frame.to_list(),
        "origin": [frame.x, frame.z],
        "label": f"Store {frame.x},{frame.z} r{frame.turns}{'m' if frame.mirror else ''}",  # see recall
        "core": frame.rect(Rect(0, 0, CORE_WIDTH, CORE_HEIGHT)),
        "kitchen": frame.rect(kitchen),
        "store": frame.rect(store),
        "workshop": frame.rect(workshop),
        "pantry": frame.rect(Rect(store.x, store.z, PANTRY_WIDTH, ROOM_DEPTH)),  # beside the kitchen
        "general": frame.rect(Rect(store.x + PANTRY_WIDTH, store.z, STORE_WIDTH - PANTRY_WIDTH, ROOM_DEPTH)),
        "stove": cell(*stove),
        "stove_rotation": frame.rotation("north"),
        "bench": cell(*bench),
        "bench_rotation": frame.rotation("north"),
        "bench_lamp": cell(bench[0] - 2, top - 1),
        "lamps": [cell(stove[0] + 2, top - 1)],
        "walls": sorted(cell(*xz) for xz in walls - set(doors)),
        "doors": [cell(*xz) for xz in doors],
        "house": house,
        "wing": wing,
        "street": frame.rect(Rect(0, CORE_HEIGHT, CORE_WIDTH, STREET)),
        "garden": [cell(*xz) for xz in garden],
        "footprint": frame.rect(FOOTPRINT),
        "away": frame.vector(0, -1),  # out of the back door: where ugly work goes (kitchen, graves)
        "fields": cell(*FIELDS),
        "butcher": cell(*BUTCHER),
    }


def best_frame(view: MapView, center: tuple[float, float], map_size: tuple[int, int]) -> tuple[Frame, dict] | None:
    """The best place and way to lay the plan in `view` for colonists around `center` (see the module's
    docstring), with its score's terms; None if it fits nowhere."""
    plain = _chars(view, "soil", "ground too poor")
    rich = _chars(view, "rich soil")
    tree = view.symbol_for("tree") or "t"
    # What moves or is hauled off: items, animals and the colonists themselves. The landing site is strewn with
    # the drop pods' items: in the replay of s1 (run 20261030-121711) no 31x18 block within 35 cells was free.
    passing = "".join(s for s, text in view.legend.items() if text.startswith(("item", "animal")) or "(Human" in text)
    walkable = plain + rich + tree + passing + "".join(
        s for s, text in view.legend.items() if text.startswith(("stockpile", "growing", "blueprint")))
    good, trees, riches, items = (Counts(view, c) for c in (plain + rich + tree + passing, tree, rich, passing))
    open_, farmland = Counts(view, plain + rich + tree), Counts(view, _chars(view, "soil", "rich soil"))
    steps = walking(view, center, walkable)
    width, height = map_size
    best: tuple[float, Frame, dict] | None = None
    for turned in ORIENTATIONS:
        inner0, room0, back0 = (turned.rect(r) for r in (INNER, INNER.grow(ROOM_REACH), BACK))
        door0 = turned.cell(MIDDLE, 3)  # the middle of the store
        area = inner0.area
        for z in range(good.z0, good.z0 + good.height - inner0.height + 1):
            for x in range(good.x0, good.x0 + good.width - inner0.width + 1):
                dx, dz = x - inner0.x, z - inner0.z
                inner = Rect(x, z, inner0.width, inner0.height)
                if good(inner) < area:
                    continue
                walk = steps.get((door0[0] + dx, door0[1] + dz))
                if walk is None:
                    continue  # not walkable from where the colonists are
                room = Rect(room0.x + dx, room0.z + dz, room0.width, room0.height)
                back = Rect(back0.x + dx, back0.z + dz, back0.width, back0.height)
                edge = min(x, z, width - (x + inner.width), height - (z + inner.height))
                terms = {"walk": round(walk, 1), "trees": trees(inner), "rich": riches(inner), "items": items(inner),
                         "room": open_(room) - open_(inner), "farmland": farmland(back), "edge": edge}
                score = (-WALK * walk - TREE * terms["trees"] - RICH * terms["rich"] - ITEM * terms["items"]
                         + ROOM * terms["room"] + FARMLAND * terms["farmland"] - EDGE * max(0, EDGE_REACH - edge))
                if best is None or score > best[0]:
                    best = (score, turned.moved(dx, dz), {**terms, "score": round(score, 1)})
    return (best[1], best[2]) if best else None


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
        plan's frame ("Store 34,46 r1m"): the name is saved with the game. None for a colony whose stockpiles
        weren't placed by a plan (managers then place things as before), and for the first planner's ("Store
        34,46"), whose layout was another."""
        if self.memory.get("frame"):
            return layout(Frame.from_list(self.memory["frame"]))
        for zone in ctx.snapshot.zones_of("stockpile"):
            m = LABEL.fullmatch(zone.get("label") or "")
            if m:
                p = layout(Frame(int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) == "m"))
                self.memory["frame"] = p["frame"]
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
        view = ctx.snapshot.view(Rect.around(center[0], center[1], WINDOW, WINDOW))
        found = best_frame(view, center, ctx.snapshot.map_size)
        if found is None:
            self.memory["none"] = True
            ctx.raise_incident("noBaseSite", f"No free {INNER.width}x{INNER.height} ground for the base near "
                               f"({center[0]:.0f}, {center[1]:.0f}), any way round: managers place things as before.", "warn")
            return None
        frame, terms = found
        p = layout(frame)
        self.memory["frame"] = p["frame"]
        # Trees in the footprint come down now: wood for the beds, and nothing in the way of walls or stockpiles.
        ctx.rim.designate(kind="chopWood", rects=[p["footprint"].to_api()])
        ctx.log(self.name, f"Planned the base: core {p['core']} (kitchen, store, workshop), {frame.turns} quarter "
                           f"turns{', mirrored' if frame.mirror else ''}, back door facing {p['away']}.",
                footprint=str(p["footprint"]), **terms)
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
            # What the house is walled in, if there's enough: one material all round.
            first = ctx.board.get("base_walls", STEEL)
            core = {"walls": pick(ctx, need, (first, WOOD if first == STEEL else STEEL))}
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


class GardenManager(Manager):
    """Plant pots beside every door on the street, once the house and the core stand and wood is plentiful.

    Colonists' beauty need is the average beauty of what they see (docs/reference/mood.md: pretty +5 to gorgeous
    +15), and the street is where everyone walks: between bedrooms, common room, kitchen and store. Flowers either
    side of each doorstep, the same on both sides of the street, and the middle row left clear.
    """

    name = "garden"
    priority = 40  # after everything that builds what the colony needs
    every_hours = 6

    def update(self, ctx: Context) -> None:
        p = ctx.board.get("plan")
        if p is None or not p.get("garden") or self.memory.get("done"):
            return
        if ctx.board.get("house_stage", 0) < 3 or ctx.board.get("core_stage", 0) < 2:
            return
        if not self.memory.get("started"):
            if ctx.snapshot.usable(WOOD) < WOOD_RESERVE + GARDEN_SPARE:
                return
            self.memory["started"] = True  # placed again every pass from now on, until built
        items = [{"def": "PlantPot", "x": x, "z": z, "rotation": "north", "stuff": WOOD} for x, z in p["garden"]]
        results, applied = place(ctx, items)
        if applied:
            ctx.log(self.name, f"Placed {applied} plant pots along the street {p.get('street')}.")
        rejected = [{k: r.get(k) for k in ("x", "z", "reason")} for r in results if r.get("outcome") == "rejected"]
        if rejected and rejected != self.memory.get("rejected"):
            ctx.raise_incident("gardenRejected", f"{len(rejected)} plant pots were refused along the street.", "warn",
                               rejected=rejected[:10])
        self.memory["rejected"] = rejected
        placed = [r for r in results if r.get("outcome") != "rejected"]
        if placed and all(r.get("outcome") == "alreadySatisfied" and r.get("state") == "built" for r in placed):
            self.memory["done"] = True
            ctx.log(self.name, "The street's plant pots are built.")
