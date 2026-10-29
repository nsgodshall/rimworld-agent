"""Supplies: the colony's own goods near the base are usable, and there is wood to build with.

A new colony's starting goods (wood, steel, components, silver, gear) lie forbidden where they
landed. In the first run, bed blueprints waited on "0 wood available, 300 forbidden" while all three
colonists stood idle. So this manager unforbids every item near the base (corpses aside).

Once the starting wood was used up, barricade and dining blueprints waited on wood that didn't exist
and the colonists stood idle again: nothing tells them to fell trees. So while wood is short, the
trees nearest the base (past the base itself, whose trees give the defenders cover) are marked
for chopping, a batch at a time.

It owns the idle-colonists alert: if colonists stay idle with nothing left to unforbid or chop, it
asks for code.
"""

from __future__ import annotations

from rimsdk.mapview import Rect

from ..manager import TICKS_PER_HOUR, Context, Manager
from .beds import base_anchor

RADIUS = 40          # cells around the base: the starting goods, not loot by distant ruins
SKIP = ["Corpses"]   # hauled to the stockpile they'd rot in
IDLE_ALERT = "Alert_ColonistsIdle"
IDLE_HOLD_HOURS = 12  # idle this long with nothing left to unforbid or chop: a gap in the code

WOOD = "WoodLog"
WOOD_TARGET = 300     # below this much wood, fell trees: beds, barricades and a dining set take ~300
CHOP_BATCH = 20       # trees marked per pass (designate takes up to 20 rects); a tree gives ~25 wood
KEEP_CLEAR = 8        # trees this close to the base stay: shooters gathering there use them as cover
SEARCH = (40, 80)     # squares around the base to look for trees in, the small one first


class SuppliesManager(Manager):
    name = "supplies"
    priority = 2  # first: what it unforbids (the starting steel) is what the house and research benches choose from
    every_hours = 2
    alerts = (IDLE_ALERT,)

    def __init__(self) -> None:
        super().__init__()
        self.idle_since: int | None = None  # harmless to lose on reload: the hold just restarts

    def update(self, ctx: Context) -> None:
        unforbade = self.unforbid(ctx)
        self.chop_wood(ctx)
        idle = next((a for a in ctx.snapshot.alerts if a.get("type") == IDLE_ALERT), None)
        if idle is None or unforbade:
            self.idle_since = None
            return
        # Marking trees doesn't reset the hold: chopping makes the alert go, and if colonists stay
        # idle with trees marked, something else is wrong.
        if self.idle_since is None:
            self.idle_since = ctx.tick
        elif ctx.tick - self.idle_since >= IDLE_HOLD_HOURS * TICKS_PER_HOUR:
            # Everyone idle is a gap in the code. Some idle is often just who they are (a colonist who
            # can't research, once the building's done): note it and carry on.
            idle_count = idle.get("culpritCount") or 1
            everyone = idle_count >= len(ctx.snapshot.colonists)
            ctx.raise_incident(
                "colonistsIdle", f"'{idle.get('label')}' for {IDLE_HOLD_HOURS}h with no forbidden goods "
                f"left near the base and wood felled as needed: the colonists need work this code doesn't give them.",
                "halt" if everyone else "warn", alert=idle, wood=self.wood(ctx))
            self.idle_since = ctx.tick  # report again only after another hold

    def unforbid(self, ctx: Context) -> int:
        anchor = base_anchor(ctx)
        if anchor is None:
            return 0
        things = ctx.rim.find_things(forbidden=True, x=anchor[0], z=anchor[1], radius=RADIUS,
                                     exclude_category=SKIP, limit=200).data.get("things") or []
        if not things:
            return 0
        ctx.rim.designate(kind="unforbid", thing_ids=[t["id"] for t in things])
        kinds = sorted({t.get("def") for t in things if t.get("def")})
        ctx.log(self.name, f"Unforbade {len(things)} stacks near the base: {', '.join(kinds)}.", near=list(anchor))
        return len(things)

    def wood(self, ctx: Context) -> int:
        resources = ctx.rim.list_resources().data.get("resources") or []
        return sum(r.get("count") or 0 for r in resources if r.get("defName") == WOOD)

    def chop_wood(self, ctx: Context) -> int:
        """Mark the trees nearest the base for felling while wood is short. Marking a tree already
        marked changes nothing, so the same nearest trees come back each pass until they're felled."""
        anchor = base_anchor(ctx)
        if anchor is None:
            return 0
        wood = self.wood(ctx)
        if wood >= WOOD_TARGET:
            return 0
        want = CHOP_BATCH * (2 if wood < WOOD_TARGET // 3 else 1)  # very short: twice the trees
        trees: list[tuple[int, int]] = []
        for side in SEARCH:
            view = ctx.snapshot.view(Rect.around(*anchor, side, side))
            tree = view.symbol_for("tree")
            trees = [xz for xz in view.find(tree)
                     if max(abs(xz[0] - anchor[0]), abs(xz[1] - anchor[1])) > KEEP_CLEAR] if tree else []
            if len(trees) >= want:
                break
        if not trees:
            return 0
        trees.sort(key=lambda xz: (xz[0] - anchor[0]) ** 2 + (xz[1] - anchor[1]) ** 2)
        batch = trees[:want]
        for i in range(0, len(batch), CHOP_BATCH):  # designate takes up to 20 rects a call
            ctx.rim.designate(kind="chopWood", rects=[Rect(x, z).to_api() for x, z in batch[i:i + CHOP_BATCH]])
        if self.memory.get("chop") == batch:
            return len(batch)  # the same trees as last pass, still being felled: no news
        self.memory["chop"] = batch
        ctx.log(self.name, f"Wood is short ({wood} of {WOOD_TARGET}): marked the {len(batch)} trees "
                f"nearest the base for chopping.", near=list(anchor), trees=[list(xz) for xz in batch])
        return len(batch)
