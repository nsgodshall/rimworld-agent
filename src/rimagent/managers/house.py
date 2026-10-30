"""House: a bedroom for each colonist and a common room to eat and play in, in one row of rooms.

Where colonists sleep and eat is most of their mood early on (docs/reference/mood.md, rooms.md):
- Sleeping outdoors, or in an unfinished room, is "Slept outside" (-4).
- A shared bedroom is a barracks, -3 to -7 each every night: trial 6's one 3-bed house gave
  "Awful barracks" (-7). The same room for one is a bedroom, -2 to +2. So each colonist gets a 3x4 room.
- Eating without a table is -3; eating or playing in a decent room is +2 each.
- "Slept in the cold" (-4): a torch lamp heats a small room to 23 C without power.
- Recreation runs from -20 to +10: horseshoes and chess are two kinds, buildable without research.

Layout, north at the top; doors in the south wall open onto a doorstep row kept clear (in trial 6 a
door opened onto a fogged ancient wall, and Sparky starved inside):

    #####################
    #c..H.#B.L#B.L#B.L#      c chair  T table  H horseshoes pin  K chess table
    #cTTcK#b..#b..#b..#      B/b bed (head, foot)  L torch lamp
    #cTTc.#...#...#...#
    #....L#...#...#...#
    ###+######+###+###+#
    ....................     doorstep

It goes up in stages (`stages`): beds, table and chairs; then walls and doors; then recreation and lamps,
each placed again every pass until built (repeating a placement is alreadySatisfied). The game roofs enclosed rooms itself. Materials come
from stock (`materials.pick`). The plan is remembered: the map shows walls, not whose they are. The
house's beds are on the board (`house_beds`), so the beds manager doesn't put any outdoors.
"""

from __future__ import annotations

import uuid

from rimsdk import errors
from rimsdk.mapview import Rect

from ..manager import Context, Manager
from .beds import base_anchor
from .food import _chars, best_site
from .materials import SILVER, STEEL, WOOD, pick

WINDOW = 60          # side of the square around the base searched for a site (scan stitches views)
DEPTH = 4            # interior, north to south
BEDROOM_WIDTH = 3    # interior: 12 tiles, "rather tight" with a bed, never "cramped"
COMMON_WIDTH = 6     # interior: a 2x2 table, four chairs, horseshoes, chess, a lamp
STALL_HOURS = 24     # a stage waiting this long on a material that's run out switches to the other
STALL_SHORT = 20     # "run out": less than this much usable
MATERIAL_KEY = {"Bed": "beds", "Wall": "walls", "Door": "walls", "HorseshoesPin": "metal"}  # else furniture
MAX_PLACEMENTS = 50  # place_blueprint refuses more in one call (400 "At most 50 placements per call.")
# Comfortable is up to about 26 C; above it bedrooms give "Slept in the heat", and a heat wave brings
# heatstroke (docs/reference/rooms.md, threats.md). In the day-7 heat wave the bedrooms were 29-30 C at
# 20:00, their torch lamps adding to it.
HOT = 26.0  # trial 10 ended with "Slept in the heat" (-4) for everyone at 28: discomfort starts at 26


def plan(origin: tuple[int, int], bedrooms: int) -> dict:
    """Cells of every part of a house whose south-west outer corner is `origin`."""
    x0, z0 = origin
    width = COMMON_WIDTH + 2 + bedrooms * (BEDROOM_WIDTH + 1)
    top = z0 + DEPTH + 1
    walls = {(x, z) for x in range(x0, x0 + width) for z in (z0, top)}
    walls |= {(x, z) for z in range(z0, top + 1) for x in (x0, x0 + COMMON_WIDTH + 1)}
    common = Rect(x0 + 1, z0 + 1, COMMON_WIDTH, DEPTH)
    rooms = []
    for i in range(bedrooms):
        left = x0 + COMMON_WIDTH + 2 + i * (BEDROOM_WIDTH + 1)
        rooms.append(Rect(left, z0 + 1, BEDROOM_WIDTH, DEPTH))
        walls |= {(left + BEDROOM_WIDTH, z) for z in range(z0, top + 1)}
    doors = [(common.x + 2, z0)] + [(r.x + 1, z0) for r in rooms]
    c, cz, ctop = common.x, common.z, common.z + DEPTH - 1
    return {
        "outer": Rect(x0, z0, width, DEPTH + 2),
        "walls": sorted(walls - set(doors)),
        "doors": doors,
        "common": common,
        "bedrooms": rooms,
        "beds": [(r.x, ctop) for r in rooms],  # south-facing: covers (x, top) and (x, top - 1)
        "lamps": [(r.x + 2, ctop) for r in rooms] + [(c + 5, cz)],
        "table": (c + 1, cz + 1),               # Table2x2c by its south-west cell
        "chairs": [(c, cz + 1), (c, cz + 2), (c + 3, cz + 1), (c + 3, cz + 2)],
        "horseshoes": (c + 3, ctop),
        "chess": (c + 5, cz + 2),
        # Beauty and wealth for impressiveness: every bedroom was "awful" (-2) with a bed and a lamp alone.
        "end_tables": [(r.x + 2, ctop - 1) for r in rooms],
        "pots": [(r.x + 2, r.z + 1) for r in rooms] + [(c, cz), (c, ctop)],
        # Placed only while a room is hot (see HOT): a corner beside the doorway in each bedroom, the top row
        # of the common room left of the horseshoes.
        "coolers": [(r.x, r.z) for r in rooms] + [(c + 1, ctop)],
    }


def stages(p: dict, walls: str, furniture: str, beds: str | None = None, metal: str = STEEL) -> list[list[dict]]:
    """The house's placements in building order. Builders take blueprints in no particular order, so a
    stage is placed only once the one before is built: in trial 7, with everything placed at once, the
    beds waited behind 70 walls and everyone slept on the ground ("Slept on ground", -4) for two nights."""
    def put(def_, xz, stuff=None, rotation="north"):
        return {"def": def_, "x": xz[0], "z": xz[1], "rotation": rotation, **({"stuff": stuff} if stuff else {})}

    tx, _ = p["table"]
    daily = [put("Bed", xz, beds or furniture, "south") for xz in p["beds"]] + [put("Table2x2c", p["table"], furniture)]
    daily += [put("DiningChair", xz, furniture, "east" if xz[0] < tx else "west") for xz in p["chairs"]]
    shell = [put("Wall", xz, walls) for xz in p["walls"]] + [put("Door", xz, walls) for xz in p["doors"]]
    cx, cz = p["chess"]
    # Chess needs a seat beside it ("Chess table needs chairs" in trial 8): one south, one north, facing it.
    comforts = [put("HorseshoesPin", p["horseshoes"], metal), put("ChessTable", p["chess"], furniture),
                put("DiningChair", (cx, cz - 1), furniture, "north"), put("DiningChair", (cx, cz + 1), furniture, "south")]
    comforts += [put("TorchLamp", xz) for xz in p["lamps"]]
    comforts += [put("EndTable", xz, furniture) for xz in p["end_tables"]] + [put("PlantPot", xz, furniture) for xz in p["pots"]]
    return [daily, shell, comforts]


def placements(p: dict, walls: str, furniture: str, beds: str | None = None, metal: str = STEEL) -> list[dict]:
    return [item for stage in stages(p, walls, furniture, beds, metal) for item in stage]


def place(ctx: Context, items: list[dict]) -> tuple[list[dict], int]:
    """place_blueprint in calls of at most MAX_PLACEMENTS (a 3-bedroom house is ~60): (results in order, applied)."""
    results, applied = [], 0
    for i in range(0, len(items), MAX_PLACEMENTS):
        reply = ctx.rim.place_blueprint(placements=items[i:i + MAX_PLACEMENTS], request_id=uuid.uuid4().hex).data or {}
        results += reply.get("results") or []
        applied += reply.get("applied") or 0
    return results, applied


def cost(p: dict) -> tuple[int, int]:
    """(wall material, furniture material) a plan needs: wall 5, door 25; bed 45, table 50, chair 45, chess 70."""
    return 5 * len(p["walls"]) + 25 * len(p["doors"]), 45 * len(p["beds"]) + 50 + 45 * len(p["chairs"]) + 70


class HouseManager(Manager):
    name = "house"
    priority = 8  # first pick of open ground, before the fields (food, 10) and beds (20), which defers to it
    every_hours = 3
    alerts = ("Alert_NeedJoySources",)  # horseshoes and chess: two kinds of recreation

    def update(self, ctx: Context) -> None:
        colonists = ctx.snapshot.colonists
        if not colonists:
            return
        house = self.memory.get("house") or self._plan(ctx, len(colonists))
        if house is None:
            return
        p = plan(tuple(house["origin"]), house["bedrooms"])
        ctx.board["house_beds"] = house["bedrooms"]
        ctx.board["house_dining"] = True
        beds = ctx.rim.list_buildings(category="bed").data.get("buildings") or []
        self._move_in(ctx, p, colonists, beds)
        self._cool(ctx, p)
        if self.memory.get("built"):
            ctx.board["house_stage"] = 3  # finished
            return
        results, applied = [], 0
        # The horseshoes pin takes metal only: steel, or silver once the steel is gone (trial 12's last stage
        # waited at 0 steel). Chosen when the last stage is first placed, then kept.
        if ctx.board.get("house_stage", 0) >= 2 and "metal" not in house:
            house["metal"] = pick(ctx, 10, (STEEL, SILVER))
        metal = house.get("metal", STEEL)
        for number, stage in enumerate(stages(p, house["walls"], house["furniture"], house.get("beds"), metal)):
            ctx.board["house_stage"] = number  # what's being built: others wait for wood (see stages())
            stage_results, stage_applied = place(ctx, stage)
            results, applied = results + stage_results, applied + stage_applied
            if not all(r.get("state") == "built" for r in stage_results):
                self._unstall(ctx, house, number, stage_results)
                break  # the next stage waits until this one stands
            self.memory.setdefault("stage_since", {}).pop(str(number), None)
        rejected = [{k: r.get(k) for k in ("def", "x", "z", "reason")} for r in results if r.get("outcome") == "rejected"]
        if applied:
            ctx.log(self.name, f"Placed {applied} house blueprints at {p['outer']}.", rejected=len(rejected))
        if rejected and rejected != self.memory.get("rejected"):
            ctx.raise_incident("houseRejected", f"{len(rejected)} house blueprints were refused at {p['outer']}.",
                               "warn", rejected=rejected[:10])
        self.memory["rejected"] = rejected
        # Finished: every stage placed, and every placement already there and built (not a blueprint or frame).
        if len(results) == len(placements(p, house["walls"], house["furniture"], house.get("beds"), metal)) and all(r.get("outcome") == "alreadySatisfied" and r.get("state") == "built" for r in results):
            self.memory["built"] = True
            ctx.log(self.name, f"The house at {p['outer']} is finished.")

    def _unstall(self, ctx: Context, house: dict, number: int, results: list[dict]) -> None:
        """A stage waiting over STALL_HOURS on a material that's run out goes to the other one. Trial 15 chose
        steel beds while steel looked plentiful; the stove and research bench took it first, and two beds
        (and every later stage, walls included) waited eleven days. Untouched blueprints are cancelled and
        placed again next pass in the new material; frames, which hold material already, are left."""
        since = self.memory.setdefault("stage_since", {}).setdefault(str(number), ctx.tick)
        if ctx.tick - since < STALL_HOURS * 2500:
            return
        waiting = [r for r in results if r.get("state") == "blueprint" and r.get("stuff") and r.get("id")]
        switched = []
        for key in {MATERIAL_KEY.get(r.get("def"), "furniture") for r in waiting}:
            stuff = house.get(key) or house["furniture"]
            alt = {STEEL: WOOD, WOOD: STEEL, SILVER: STEEL}.get(stuff)
            if alt is None or ctx.snapshot.usable(stuff) >= STALL_SHORT or ctx.snapshot.usable(alt) <= ctx.snapshot.usable(stuff):
                continue
            ids = [r["id"] for r in waiting if MATERIAL_KEY.get(r.get("def"), "furniture") == key and r.get("stuff") == stuff]
            if not ids:
                continue
            ctx.rim.designate(kind="cancel", thing_ids=ids[:300])
            house[key] = alt
            switched.append(f"{len(ids)} {key} from {stuff} to {alt}")
        if switched:
            self.memory["stage_since"][str(number)] = ctx.tick
            ctx.log(self.name, f"Stage {number} waited {(ctx.tick - since) / 2500:.0f}h for material: switched "
                               f"{'; '.join(switched)}.")

    def _plan(self, ctx: Context, bedrooms: int) -> dict | None:
        snap = ctx.snapshot
        anchor = base_anchor(ctx)
        if anchor is None:
            return None
        size = plan((0, 0), bedrooms)["outer"]
        width, height = size.width, size.height + 1  # and the doorstep row
        view = snap.view(Rect.around(*anchor, WINDOW, WINDOW))
        # Free ground: no fields, zones, items, buildings, blueprints, rock or fog. Builders cut trees in
        # the way, so trees are allowed, but open ground scores higher.
        plain = _chars(view, "soil", "ground too poor")
        site = best_site(view, anchor, width, height, good=plain + (view.symbol_for("tree") or "t"), bonus=plain,
                         min_fill=1.0)
        if site is None:
            ctx.raise_incident("noHouseSite", f"No free {width}x{height} ground for a house near {anchor}.", "warn")
            return None
        p = plan((site.x, site.z + 1), bedrooms)
        walls_need, furniture_need = cost(p)
        spent: dict[str, int] = {}
        # Beds first and in steel if there's enough: they're wanted the first night, while wood goes
        # everywhere early (trial 8 had 0-33 wood for two days, and no beds).
        house = {"origin": [site.x, site.z + 1], "bedrooms": bedrooms,
                 "beds": pick(ctx, 45 * bedrooms, (STEEL, WOOD), spent),
                 "walls": pick(ctx, walls_need, (STEEL, WOOD), spent),  # steel walls leave wood for fuel
                 "furniture": pick(ctx, furniture_need - 45 * bedrooms, (WOOD, STEEL), spent)}
        self.memory["house"] = house
        ctx.log(self.name, f"Planned {bedrooms} bedrooms and a common room at {p['outer']}: walls of "
                           f"{house['walls']}, furniture of {house['furniture']}.", needs=[walls_need, furniture_need])
        return house

    def _cool(self, ctx: Context, p: dict) -> None:
        """A passive cooler (50 wood, wood fuel, no power) in every room once an enclosed room is over HOT.
        Placed again every pass while hot (alreadySatisfied once there); never taken down: it only cools
        above about 15 C, so it does no harm in the cold."""
        rooms = (ctx.rim.get_environment().data.get("rooms") or {}).get("items") or []
        hot = [r for r in rooms if not r.get("usesOutdoorTemperature") and (r.get("temperatureC") or 0) > HOT]
        if not hot:
            return
        items = [{"def": "PassiveCooler", "x": x, "z": z, "rotation": "north"} for x, z in p["coolers"]]
        results, applied = place(ctx, items)
        if applied:
            ctx.log(self.name, f"Placed {applied} passive coolers: {len(hot)} rooms over {HOT:.0f} C.",
                    hottest=round(max(r["temperatureC"] for r in hot), 1))
        rejected = [{k: r.get(k) for k in ("x", "z", "reason")} for r in results if r.get("outcome") == "rejected"]
        if rejected and rejected != self.memory.get("coolers_rejected"):
            ctx.raise_incident("coolerRejected", f"{len(rejected)} passive coolers were refused in the house.",
                               "warn", rejected=rejected)
        self.memory["coolers_rejected"] = rejected

    def _move_in(self, ctx: Context, p: dict, colonists: list[dict], beds: list[dict]) -> None:
        """Each colonist owns the bed in their own bedroom; once all have one, beds outside come down."""
        rooms = [set(r.cells()) for r in p["bedrooms"]]

        def room_of(bed: dict) -> int | None:
            xz = (bed["position"]["x"], bed["position"]["z"])
            return next((i for i, cells in enumerate(rooms) if xz in cells), None)

        indoor = {room_of(b): b for b in beds if room_of(b) is not None}
        if not indoor:
            return
        assigned = self.memory.setdefault("assigned", {})
        for i, colonist in enumerate(sorted(colonists, key=lambda c: c["ids"]["id"])):
            pawn_id, bed = colonist["ids"]["id"], indoor.get(i)
            if bed is None or assigned.get(pawn_id) == bed["ids"]["id"]:
                continue
            try:
                ctx.rim.assign_owner(bed["ids"]["id"], pawn_id=pawn_id)
            except errors.Conflict as exc:
                ctx.raise_incident("bedRefused", f"{pawn_id} can't have bed {bed['ids']['id']}: {exc.message}", "warn")
                continue
            assigned[pawn_id] = bed["ids"]["id"]
            ctx.log(self.name, f"{colonist.get('name')} has their own bedroom now.", bed=bed["ids"]["id"])
        if len(indoor) >= len(colonists):
            outdoor = sorted(b["ids"]["id"] for b in beds if room_of(b) is None)
            if outdoor and outdoor != self.memory.get("deconstructing"):
                ctx.rim.designate(kind="deconstruct", thing_ids=outdoor)
                ctx.log(self.name, f"Taking down {len(outdoor)} beds outside the house.")
            self.memory["deconstructing"] = outdoor
