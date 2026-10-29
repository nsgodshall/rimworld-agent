"""Kitchen: a stove by the stockpile with a bill to cook simple meals, and a butcher spot with a bill to
butcher what the hunters kill.

Hunting alone feeds no one: a kill is a corpse, and only butchering makes it meat the stove can cook. In run
20261029-114409 the pantry had ~25 animals hunted by day 5, every corpse still lying where it fell, and the
colony ran out of stored food with the rice half grown: there was no butcher spot. A spot costs nothing and
takes no work to build.
"""

from __future__ import annotations

import math
import uuid

from rimsdk.mapview import Rect

from ..manager import Context, Manager
from .beds import base_anchor
from .food import _chars, best_site

COOKERS = ("FueledStove", "ElectricStove", "Campfire")
# Tried in order: a fueled stove (steel, cooks indoors and faster), else a campfire (wood, no research).
BUILD = ("FueledStove", "Campfire")
BUTCHERS = ("ButcherSpot", "TableButcher")
BUTCHER_BUILD = ("ButcherSpot",)
ROTATION = "north"
RECIPE = "CookMealSimple"
CORPSE_STORE = (3, 3)  # a stockpile beside the butcher spot that takes fresh animal corpses
DUMP_SIZE = (4, 4)     # and one for rotten corpses, out of sight
DUMP_DISTANCE = 25
BUTCHER_RECIPE = "ButcherCorpseFlesh"  # "Butcher creature"; butchering has no count to target, so Forever
MEALS_PER_COLONIST = 10  # the bill's target: a few days of meals in store
WINDOW = 20  # side of the square around the base anchor (check_placement's limit)
TRIES = 3


class KitchenManager(Manager):
    name = "kitchen"
    priority = 25  # after food and beds: the stove goes where they left room
    every_hours = 6
    alerts = ("Alert_NeedMealSource",)

    def update(self, ctx: Context) -> None:
        buildings = [b for page in ctx.rim.pages(ctx.rim.list_buildings, limit=200)
                     for b in page.data.get("buildings") or []]
        of = lambda defs: [b for b in buildings if (b.get("def") or {}).get("defName") in defs]
        bills = None
        for found, build, recipe, mode, label in (
                (of(COOKERS), BUILD, RECIPE, "TargetCount", "stove or campfire"),
                (of(BUTCHERS), BUTCHER_BUILD, BUTCHER_RECIPE, "Forever", "butcher spot")):
            if not found:
                self.ensure_built(ctx, build, label)
                continue
            if bills is None:
                bills = ctx.rim.list_production().data.get("bills") or []
            if not any((b.get("recipe") or {}).get("defName") == recipe for b in bills):
                self.add_bill(ctx, found[0], recipe, mode)
            if recipe == BUTCHER_RECIPE:
                self.ensure_corpse_store(ctx, found[0])

    def ensure_corpse_store(self, ctx: Context, butcher: dict) -> None:
        """A small stockpile for fresh animal corpses beside the butcher spot. With nowhere that takes
        corpses, hunters leave kills where they fall: in trial 9, 31 lay across the map, rotted before anyone
        butchered them, and "Observed rotting corpse" (-6) hit the colonists who passed them."""
        zone_id = self.memory.get("corpse_zone")
        if zone_id and any(z.get("id") == zone_id for z in ctx.snapshot.zones_of("stockpile")):
            self.ensure_dump(ctx)
            return
        pos = butcher.get("position") or {}
        if "x" not in pos:
            return
        view = ctx.snapshot.view(Rect.around(pos["x"], pos["z"], 13, 13))
        site = best_site(view, (pos["x"], pos["z"]), *CORPSE_STORE, good=_chars(view, "soil", "ground too poor"), min_fill=1.0)
        if site is None:
            ctx.raise_incident("noCorpseStore", f"No room for a corpse stockpile by the butcher spot at {pos}.", "warn")
            return
        zone = (ctx.rim.set_zone(kind="stockpile", add=[site.to_api()], request_id=uuid.uuid4().hex).data or {}).get("zone") or {}
        if not zone.get("id"):
            return
        # Fresh animal corpses only: rotten ones can't be butchered, and smell up wherever they're carried.
        result = ctx.rim.set_storage(zone_id=zone["id"], disallow_all=True, allow=["CorpsesAnimal"],
                                     disallow=["AllowRotten"]).data or {}
        self.memory["corpse_zone"] = zone["id"]
        rejected = [e for e in result.get("entries") or [] if e.get("outcome") == "rejected"]  # ZoneCommandService
        ctx.log(self.name, f"Made a corpse stockpile {zone['id']} at {site} beside the butcher spot.", rejected=rejected)
        if rejected:
            ctx.raise_incident("corpseStoreFilter", f"The corpse stockpile's filter was partly refused.", "warn",
                               rejected=rejected)

    def ensure_dump(self, ctx: Context) -> None:
        """A low-priority stockpile for rotten corpses, out of sight of the base. Kills still rot in the
        fresh-corpse store before they're butchered (trial 10 ended with "Observed rotting corpse", -6,
        on two colonists); that store refuses rotten ones, so haulers carry them here."""
        zone_id = self.memory.get("dump_zone")
        if zone_id and any(z.get("id") == zone_id for z in ctx.snapshot.zones_of("stockpile")):
            return
        anchor = base_anchor(ctx)
        if anchor is None:
            return
        snap = ctx.snapshot
        width, height = snap.map_size
        # South of the stockpile: the house is planned north of it. Clamped to the map.
        center = (anchor[0], max(DUMP_SIZE[1], anchor[1] - DUMP_DISTANCE))
        view = snap.view(Rect.around(*center, 20, 20).clamp(width, height))
        site = best_site(view, center, *DUMP_SIZE, good=_chars(view, "soil", "ground too poor"), min_fill=0.9)
        if site is None:
            ctx.raise_incident("noCorpseDump", f"No room for a corpse dump near {center}.", "warn")
            return
        zone = (ctx.rim.set_zone(kind="stockpile", add=[site.to_api()], request_id=uuid.uuid4().hex).data or {}).get("zone") or {}
        if not zone.get("id"):
            return
        result = ctx.rim.set_storage(zone_id=zone["id"], priority="Low", disallow_all=True, allow=["Corpses", "AllowRotten"]).data or {}
        self.memory["dump_zone"] = zone["id"]
        rejected = [e for e in result.get("entries") or [] if e.get("outcome") == "rejected"]
        ctx.log(self.name, f"Made a corpse dump {zone['id']} at {site}, out of sight of the base.", rejected=rejected)

    def add_bill(self, ctx: Context, workbench: dict, recipe: str, mode: str) -> None:
        workbench_id = workbench["ids"]["id"]
        if mode == "TargetCount":
            target = MEALS_PER_COLONIST * max(1, len(ctx.snapshot.colonists))
            ctx.rim.add_bill_to_workshop(workbench_id, recipe_def_name=recipe, repeat_mode_def_name=mode,
                                         target_count=target, request_id=uuid.uuid4().hex)
            ctx.log(self.name, f"Added a bill to make {recipe} up to {target} at {workbench_id}.")
        else:
            ctx.rim.add_bill_to_workshop(workbench_id, recipe_def_name=recipe, repeat_mode_def_name=mode,
                                         request_id=uuid.uuid4().hex)
            ctx.log(self.name, f"Added a bill to do {recipe} forever at {workbench_id}.")

    def ensure_built(self, ctx: Context, defs: tuple[str, ...], label: str) -> None:
        snap = ctx.snapshot
        anchor = base_anchor(ctx)
        if anchor is None:
            return
        window = Rect.around(*anchor, WINDOW, WINDOW).clamp(*snap.map_size)
        view = snap.view(window)
        good = _chars(view, "soil", "ground too poor")
        planned = view.symbol_for("blueprint") or "x"
        # Where this manager placed each def: the map view shows every blueprint the same way, so a stove's
        # blueprint must not look like a place for the butcher spot.
        placed = self.memory.setdefault("placed", {})

        for def_ in defs:
            check = ctx.rim.check_placement(def_=def_, rotation=ROTATION, **window.to_api()).data or {}
            if not check.get("available", True):
                continue
            building = check.get("building") or {}
            fp = building.get("footprintOffset") or {"x": 0, "z": 0, "width": 1, "height": 1}
            ic = building.get("interactionCellOffset")
            mine = tuple(placed[def_]) if def_ in placed else None

            def footprint(x: int, z: int) -> Rect:
                return Rect(x + fp["x"], z + fp["z"], fp["width"], fp["height"])

            # check_placement lists only the 50 fits nearest the middle, which may all be in the stockpile;
            # the map view says where open ground is, and place_blueprint has the last word.
            def usable(x: int, z: int) -> bool:
                """Open ground, clear of zones and items, or where our blueprint already stands."""
                cells = list(footprint(x, z).cells()) + ([(x + ic["x"], z + ic["z"])] if ic else [])
                if all(view.is_(c, good) for c in cells):
                    return True
                if (x, z) == mine:
                    return True
                # The stove's blueprint, from before this manager remembered placements (or a restart).
                return def_ in BUILD and all(view.is_(c, planned) for c in footprint(x, z).cells())

            # A fixed order, nearest the anchor first: next pass finds the same spot, where placing again
            # comes back alreadySatisfied instead of planning a second one.
            spots = sorted(window.cells(), key=lambda c: (math.hypot(c[0] - anchor[0], c[1] - anchor[1]), c[1], c[0]))
            candidates = [s for s in spots if usable(*s)]
            if mine in candidates:
                candidates.remove(mine)
                candidates.insert(0, mine)
            candidates = candidates[:TRIES]
            for x, z in candidates:
                result = ctx.rim.place_blueprint(placements=[{"def": def_, "x": x, "z": z, "rotation": ROTATION}],
                                                 request_id=uuid.uuid4().hex).data or {}
                (done,) = result.get("results") or [{}]
                outcome = done.get("outcome")
                if outcome == "applied":
                    placed[def_] = [x, z]
                    ctx.log(self.name, f"Placed a {def_} blueprint at ({x}, {z}).", blockers=result.get("blockers"))
                    return
                if outcome == "alreadySatisfied":
                    return
            if candidates:
                ctx.raise_incident("blueprintRejected", f"No {def_} blueprint took near {anchor}.", "warn",
                                   tried=candidates)
                return
        ctx.raise_incident("noSite", f"No room for a {label} near {anchor}.", "warn", window=str(window))
