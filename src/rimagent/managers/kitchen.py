"""Kitchen: a stove by the stockpile, and a bill to cook simple meals on it."""

from __future__ import annotations

import math
import uuid

from rimsdk.mapview import Rect

from ..manager import Context, Manager
from .beds import base_anchor
from .food import _chars

COOKERS = ("FueledStove", "ElectricStove", "Campfire")
# Tried in order: a fueled stove (steel, cooks indoors and faster), else a campfire (wood, no research).
BUILD = ("FueledStove", "Campfire")
ROTATION = "north"
RECIPE = "CookMealSimple"
MEALS_PER_COLONIST = 10  # the bill's target: a few days of meals in store
WINDOW = 20  # side of the square around the base anchor (check_placement's limit)
TRIES = 3


class KitchenManager(Manager):
    name = "kitchen"
    priority = 25  # after food and beds: the stove goes where they left room
    every_hours = 6
    alerts = ("Alert_NeedMealSource",)

    def update(self, ctx: Context) -> None:
        cookers = [b for page in ctx.rim.pages(ctx.rim.list_buildings, limit=200)
                   for b in page.data.get("buildings") or [] if (b.get("def") or {}).get("defName") in COOKERS]
        if cookers:
            self.ensure_bill(ctx, cookers[0])
        else:
            self.ensure_stove(ctx)

    def ensure_bill(self, ctx: Context, cooker: dict) -> None:
        # A new stove has no bills. Only cooking is set up so far, so any bill at all means it's done.
        if ctx.rim.list_production().data.get("bills"):
            return
        target = MEALS_PER_COLONIST * max(1, len(ctx.snapshot.colonists))
        ctx.rim.add_bill_to_workshop(cooker["ids"]["id"], recipe_def_name=RECIPE, repeat_mode_def_name="TargetCount",
                                     target_count=target, request_id=uuid.uuid4().hex)
        ctx.log(self.name, f"Added a bill to cook {RECIPE} up to {target} at {cooker['ids']['id']}.")

    def ensure_stove(self, ctx: Context) -> None:
        snap = ctx.snapshot
        anchor = base_anchor(ctx)
        if anchor is None:
            return
        window = Rect.around(*anchor, WINDOW, WINDOW).clamp(*snap.map_size)
        view = snap.view(window)
        good = _chars(view, "soil", "ground too poor")
        planned = view.symbol_for("blueprint") or "x"

        for def_ in BUILD:
            check = ctx.rim.check_placement(def_=def_, rotation=ROTATION, **window.to_api()).data or {}
            if not check.get("available", True):
                continue
            building = check.get("building") or {}
            fp = building.get("footprintOffset") or {"x": 0, "z": 0, "width": 1, "height": 1}
            ic = building.get("interactionCellOffset")

            def footprint(x: int, z: int) -> Rect:
                return Rect(x + fp["x"], z + fp["z"], fp["width"], fp["height"])

            # check_placement lists only the 50 fits nearest the middle, which may all be in the stockpile;
            # the map view says where open ground is, and place_blueprint has the last word.
            def usable(x: int, z: int) -> bool:
                """Open ground, clear of zones and items, or where our blueprint already stands."""
                cells = list(footprint(x, z).cells()) + ([(x + ic["x"], z + ic["z"])] if ic else [])
                if all(view.is_(c, good) for c in cells):
                    return True
                return all(view.is_(c, planned) for c in footprint(x, z).cells())

            # A fixed order, nearest the anchor first: next pass finds the same spot, where placing again
            # comes back alreadySatisfied instead of planning a second stove.
            spots = sorted(window.cells(), key=lambda c: (math.hypot(c[0] - anchor[0], c[1] - anchor[1]), c[1], c[0]))
            candidates = [s for s in spots if usable(*s)][:TRIES]
            for x, z in candidates:
                result = ctx.rim.place_blueprint(placements=[{"def": def_, "x": x, "z": z, "rotation": ROTATION}],
                                                 request_id=uuid.uuid4().hex).data or {}
                (placed,) = result.get("results") or [{}]
                outcome = placed.get("outcome")
                if outcome == "applied":
                    ctx.log(self.name, f"Placed a {def_} blueprint at ({x}, {z}).", blockers=result.get("blockers"))
                    return
                if outcome == "alreadySatisfied":
                    return
            if candidates:
                ctx.raise_incident("stoveRejected", f"No {def_} blueprint took near {anchor}.", "warn",
                                   tried=candidates)
                return
        ctx.raise_incident("noSite", f"No room for a stove or campfire near {anchor}.", "warn", window=str(window))
