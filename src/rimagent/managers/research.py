"""Research: a research bench by the base, and a project always chosen for it.

In the first run, once the barricades, beds and dining set were built and wood was stocked, all
three colonists stood idle for 12 hours: there was no research bench and no project, so nothing
was left to do. Research never runs out, so it is the colony's standing work.

get_research names what stops research (noProject, missingResearchBench). With no project, the
first available one in PREFER is chosen, else the cheapest available. With no bench, a wooden
simple bench is planned beside the stockpile.
"""

from __future__ import annotations

import math
import uuid

from rimsdk.mapview import Rect

from ..manager import Context, Manager
from .beds import base_anchor
from .food import _chars

BENCHES = ("SimpleResearchBench", "HiTechResearchBench")
BENCH = "SimpleResearchBench"  # 3x2, 75 wood and 25 steel, no power
STUFF = "WoodLog"
ROTATION = "north"
WINDOW = 20  # side of the square around the base anchor (check_placement's limit)
TRIES = 3
# Projects worth having early, in order: power storage and solar, indoor crops, cleaner surgery,
# then components and better weapons.
PREFER = ("Batteries", "SolarPanels", "Hydroponics", "SterileMaterials", "MicroelectronicsBasics",
          "Smithing", "RecurveBow", "Autodoors")


class ResearchManager(Manager):
    name = "research"
    priority = 35  # after the kitchen and dining set: the bench goes where they left room
    every_hours = 6
    alerts = ("Alert_NeedResearchProject",)

    def update(self, ctx: Context) -> None:
        research = ctx.rim.get_research(limit=1).data or {}
        blockers = {b.get("kind") for b in research.get("blockers") or []}
        if "noProject" in blockers:
            self.choose_project(ctx)
        if "missingResearchBench" in blockers:
            self.ensure_bench(ctx)

    def choose_project(self, ctx: Context) -> None:
        available = [p for page in ctx.rim.pages(ctx.rim.get_research, available_only=True, limit=200)
                     for p in page.data.get("projects") or [] if not p.get("finished")]
        if not available:
            ctx.raise_incident("noResearch", "No research project can be started.", "warn")
            return
        by_name = {p["defName"]: p for p in available}
        project = next((by_name[d] for d in PREFER if d in by_name), None) \
            or min(available, key=lambda p: (p.get("baseCost") or 0, p["defName"]))
        ctx.rim.set_research_project(project_def_name=project["defName"])
        ctx.log(self.name, f"Started researching {project.get('label') or project['defName']}.",
                project=project["defName"], cost=project.get("baseCost"))

    def ensure_bench(self, ctx: Context) -> None:
        buildings = [b for page in ctx.rim.pages(ctx.rim.list_buildings, limit=200)
                     for b in page.data.get("buildings") or []]
        if any((b.get("def") or {}).get("defName") in BENCHES for b in buildings):
            return  # built since get_research looked, or not in reach of it
        snap = ctx.snapshot
        anchor = base_anchor(ctx)
        if anchor is None:
            return
        window = Rect.around(*anchor, WINDOW, WINDOW).clamp(*snap.map_size)
        check = ctx.rim.check_placement(def_=BENCH, rotation=ROTATION, **window.to_api()).data or {}
        if not check.get("available", True):
            ctx.raise_incident("benchUnavailable", f"{BENCH} can't be built.", "warn", check=check)
            return
        building = check.get("building") or {}
        fp = building.get("footprintOffset") or {"x": -1, "z": 0, "width": 3, "height": 2}
        ic = building.get("interactionCellOffset")
        view = snap.view(window)
        good = _chars(view, "soil", "ground too poor")
        planned = view.symbol_for("blueprint") or "x"

        def footprint(x: int, z: int) -> list[tuple[int, int]]:
            return list(Rect(x + fp["x"], z + fp["z"], fp["width"], fp["height"]).cells())

        def usable(x: int, z: int) -> bool:
            """Open ground with a free interaction cell, or where our bench blueprint already stands."""
            cells = footprint(x, z) + ([(x + ic["x"], z + ic["z"])] if ic else [])
            return all(view.is_(c, good) for c in cells) or all(view.is_(c, planned) for c in footprint(x, z))

        # A fixed order, nearest the anchor first: next pass finds the same spot, where placing again
        # comes back alreadySatisfied instead of planning a second bench.
        spots = sorted(window.cells(), key=lambda c: (math.hypot(c[0] - anchor[0], c[1] - anchor[1]), c[1], c[0]))
        candidates = [s for s in spots if usable(*s)][:TRIES]
        for x, z in candidates:
            result = ctx.rim.place_blueprint(
                placements=[{"def": BENCH, "stuff": STUFF, "x": x, "z": z, "rotation": ROTATION}],
                request_id=uuid.uuid4().hex).data or {}
            (placed,) = result.get("results") or [{}]
            outcome = placed.get("outcome")
            if outcome == "applied":
                ctx.log(self.name, f"Placed a {BENCH} blueprint at ({x}, {z}).", blockers=result.get("blockers"))
                return
            if outcome == "alreadySatisfied":
                return
        if candidates:
            ctx.raise_incident("benchRejected", f"No {BENCH} blueprint took near {anchor}.", "warn", tried=candidates)
        else:
            ctx.raise_incident("noSite", f"No room for a research bench near {anchor}.", "warn", window=str(window))
