"""Food: somewhere to store it, nothing edible left forbidden, and enough fields to keep everyone fed."""

from __future__ import annotations

import math
import uuid

from rimsdk.mapview import MapView, Rect

from ..events import Event
from ..manager import Context, Manager

GROW_CELLS_PER_COLONIST = 60  # rice, cooked: 36 and 45 left stores near 2 days, and hungry colonists ate raw rice where they stood
CROP = "Plant_Rice"
STOCKPILE_SIZE = (6, 6)
PANTRY_SIZE = (6, 6)  # food only, preferred (ensure_pantry)
SEARCH_RADIUS = 30  # cells around the colonists to look for zone sites
FIELD_SEARCH_RADIUS = 60  # fields look farther when nothing fits within SEARCH_RADIUS


class FoodManager(Manager):
    name = "food"
    priority = 10  # makes the stockpile other managers build around
    every_hours = 6
    handles = ("lowFood",)

    def update(self, ctx: Context) -> None:
        snap = ctx.snapshot
        if snap.base_center is None:
            return
        self.ensure_stockpile(ctx)
        self.ensure_pantry(ctx)
        self.unforbid_food(ctx)
        self.ensure_fields(ctx)

    def on_event(self, ctx: Context, event: Event) -> bool:
        # Low food mostly means food sits outside storage or fields are short: both are what update() fixes.
        self.update(ctx)
        ctx.log(self.name, "Low food: re-checked storage and fields.", foodDays=ctx.snapshot.food_days)
        return True

    # --- storage -----------------------------------------------------------------------------

    def ensure_stockpile(self, ctx: Context) -> None:
        if ctx.snapshot.zones_of("stockpile"):
            return
        plan = ctx.board.get("plan")
        if plan is not None:
            site = plan["general"]  # in the store (managers/planner.py)
        else:
            view = self._view(ctx)
            width, height = STOCKPILE_SIZE
            # Plain or poor ground: save rich soil for crops.
            site = best_site(view, ctx.snapshot.base_center, width, height, good=_chars(view, "soil", "ground too poor"), min_fill=0.8)
        if site is None:
            ctx.raise_incident("noSite", "No room for a stockpile near the colonists.", "warn")
            return
        result = ctx.rim.set_zone(kind="stockpile", add=[site.to_api()], request_id=uuid.uuid4().hex)
        zone = (result.data or {}).get("zone") or {}
        if plan is not None and zone.get("id"):  # named so the plan is found again after a restart (planner.recall)
            ctx.rim.set_zone(zone_id=zone["id"], label=plan["label"])
        ctx.snapshot.__dict__.pop("zones", None)  # read again: the pantry goes beside this one, this pass
        ctx.log(self.name, f"Created stockpile {zone.get('id')} at {site}.", cells=zone.get("cellCount"))

    def ensure_pantry(self, ctx: Context) -> None:
        """A stockpile for food only, preferred over the general one. The general stockpile takes everything
        (wood, steel, apparel...) and fills up: at the end of trial 19 685 rice and berries lay in 70 stacks
        outside storage, 203 inside, and stored food read 3.6 days."""
        zones = ctx.snapshot.zones_of("stockpile")
        if not zones:
            return  # the general one first: it's the base's anchor (beds.base_anchor)
        # Found by what it takes (list_zones shows each stockpile's accepts): only food.
        if any(((z.get("stockpile") or {}).get("accepts") or {}).get("all") == ["Foods"] for z in zones):
            return
        plan = ctx.board.get("plan")
        if plan is not None:
            site = plan["pantry"]  # the store's other half
        else:
            view = self._view(ctx)
            width, height = PANTRY_SIZE
            cell = zones[0].get("representativeCell") or {}
            anchor = (cell["x"], cell["z"]) if "x" in cell else ctx.snapshot.base_center
            site = best_site(view, anchor, width, height, good=_chars(view, "soil", "ground too poor"), min_fill=0.8)
        if site is None:
            ctx.raise_incident("noPantrySite", "No room for a food stockpile near the base.", "warn")
            return
        zone = (ctx.rim.set_zone(kind="stockpile", add=[site.to_api()], request_id=uuid.uuid4().hex).data or {}).get("zone") or {}
        if not zone.get("id"):
            return
        result = ctx.rim.set_storage(zone_id=zone["id"], priority="Preferred", disallow_all=True, allow=["Foods"]).data or {}
        rejected = [e for e in result.get("entries") or [] if e.get("outcome") == "rejected"]
        ctx.log(self.name, f"Made a food stockpile {zone['id']} at {site}.", rejected=rejected)

    def unforbid_food(self, ctx: Context) -> None:
        things = ctx.rim.find_things(category="Foods", forbidden=True).data.get("things") or []
        if not things:
            return
        ids = [t["id"] for t in things][:300]
        ctx.rim.designate(kind="unforbid", thing_ids=ids)
        ctx.log(self.name, f"Unforbade {len(ids)} food stacks.")

    # --- fields ------------------------------------------------------------------------------

    def ensure_fields(self, ctx: Context) -> None:
        snap = ctx.snapshot
        fields = snap.zones_of("growing")
        have = sum(z.get("cellCount", 0) for z in fields)
        want = GROW_CELLS_PER_COLONIST * len(snap.colonists)
        if want - have < GROW_CELLS_PER_COLONIST // 2:
            return

        cells = want - have
        width = math.ceil(math.sqrt(cells))
        height = math.ceil(cells / width)
        site = None
        # Behind the store's back door in a base plan (managers/planner.py chose a site with farmland there),
        # else by the colonists.
        plan = ctx.board.get("plan") or {}
        anchor = tuple(plan["fields"]) if plan.get("fields") else snap.base_center
        # Farther out when nothing fits near: desert soil lies in patches (start desert1: the one big enough
        # began 30 cells east of the base). A far field costs hauling; no field costs the colony.
        for radius in (SEARCH_RADIUS, FIELD_SEARCH_RADIUS):
            view = self._view(ctx, radius, anchor)
            site = best_site(view, anchor, width, height, good=_chars(view, "soil", "rich soil"),
                             bonus=_chars(view, "rich soil"), min_fill=0.85)
            if site is not None:
                break
        if site is None:
            ctx.raise_incident("noSite", f"No {width}x{height} farmland within {FIELD_SEARCH_RADIUS} cells of the colonists.", "warn")
            return
        result = ctx.rim.set_zone(kind="growing", add=[site.to_api()], request_id=uuid.uuid4().hex)
        zone = (result.data or {}).get("zone") or {}
        if zone.get("id"):
            ctx.rim.set_growing_zone(zone_id=zone["id"], plant=CROP, allow_sow=True, allow_cut=True)
        ctx.log(self.name, f"Created field {zone.get('id')} at {site} for {CROP}.", cells=zone.get("cellCount"), wanted=cells)

    def _view(self, ctx: Context, radius: int = SEARCH_RADIUS, center: tuple[float, float] | None = None) -> MapView:
        x, z = center or ctx.snapshot.base_center
        side = 2 * radius
        return ctx.snapshot.view(Rect.around(x, z, side, side))


def _chars(view: MapView, *meanings: str) -> str:
    """Legend symbols for the given meanings, falling back to RimMCP's usual ones."""
    defaults = {"soil": ".", "rich soil": ":", "ground too poor": "_"}
    return "".join(view.symbol_for(m) or defaults.get(m, "") for m in meanings)


def best_site(
    view: MapView,
    center: tuple[float, float],
    width: int,
    height: int,
    *,
    good: str,
    bonus: str = "",
    min_fill: float = 0.85,
) -> Rect | None:
    """The width x height rect with the most `good` cells (bonus cells count 1.5x), nearest `center`."""
    if not view.cells:
        return None
    xs = [x for x, _ in view.cells]
    zs = [z for _, z in view.cells]
    cx, cz = center
    best, best_score = None, -math.inf
    for z in range(min(zs), max(zs) - height + 2):
        for x in range(min(xs), max(xs) - width + 2):
            rect = Rect(x, z, width, height)
            fill = view.count(rect, good)
            if fill < min_fill * rect.area:
                continue
            rx, rz = rect.center
            # Keep clear of where the colonists stand, but close by.
            distance = math.hypot(rx - cx, rz - cz)
            score = fill + 0.5 * view.count(rect, bonus) - 0.8 * distance
            if score > best_score:
                best, best_score = rect, score
    return best
