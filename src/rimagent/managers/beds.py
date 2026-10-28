"""Beds: one per colonist, in a row of wooden beds by the stockpile."""

from __future__ import annotations

import uuid

from rimsdk.mapview import Rect

from ..manager import Context, Manager
from .food import _chars, best_site

BED = "Bed"
STUFF = "WoodLog"
WINDOW = 20  # side of the square around the base anchor where beds go (check_placement's limit)


class BedsManager(Manager):
    name = "beds"
    # A day between passes: a wooden bed is under an hour's work, so blueprints left from the last
    # pass are normally built by then.
    every_hours = 24
    alerts = ("Alert_NeedColonistBeds",)

    def update(self, ctx: Context) -> None:
        snap = ctx.snapshot
        anchor = base_anchor(ctx)
        if anchor is None:
            return
        window = Rect.around(*anchor, WINDOW, WINDOW).clamp(*snap.map_size)

        built = ctx.rim.list_buildings(category="bed").data.get("buildings") or []
        if len(built) >= len(snap.colonists):
            return
        view = snap.view(window)
        # Beds not built yet are blueprints or frames: list_buildings doesn't show them, and the map shows
        # only that something is planned, not what. Near the stockpile, take them to be the beds placed
        # last pass (each bed covers two cells), so they aren't placed again while colonists get to them.
        planned = view.count(window, view.symbol_for("blueprint") or "x") // 2
        missing = len(snap.colonists) - len(built) - planned
        if missing <= 0:
            return

        # Free plain ground: not rich soil (fields), zones, trees, items or buildings.
        site = best_site(view, anchor, missing, 2, good=_chars(view, "soil", "ground too poor"), min_fill=1.0)
        if site is None:
            ctx.raise_incident("noSite", f"No room for {missing} beds near {anchor}.", "warn", window=str(window))
            return
        # A south-facing bed at (x, z) covers (x, z) and (x, z - 1).
        placements = [{"def": BED, "stuff": STUFF, "x": site.x + i, "z": site.z + 1, "rotation": "south"}
                      for i in range(missing)]
        result = ctx.rim.place_blueprint(placements=placements, request_id=uuid.uuid4().hex).data or {}
        rejected = [r for r in result.get("results") or [] if r.get("outcome") == "rejected"]
        ctx.log(self.name, f"Placed {result.get('applied', 0)} bed blueprints at {site}.",
                built=len(built), planned=planned, colonists=len(snap.colonists), blockers=result.get("blockers"))
        if rejected:
            ctx.raise_incident("bedsRejected", f"{len(rejected)} of {missing} bed blueprints were rejected.", "warn",
                               rejected=[{k: r.get(k) for k in ("x", "z", "reason")} for r in rejected])


def base_anchor(ctx: Context) -> tuple[int, int] | None:
    """The stockpile, which stays put, or else where the colonists are."""
    for zone in ctx.snapshot.zones_of("stockpile"):
        cell = zone.get("representativeCell")
        if cell:
            return int(cell["x"]), int(cell["z"])
    center = ctx.snapshot.base_center
    return (round(center[0]), round(center[1])) if center else None
