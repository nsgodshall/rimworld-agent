"""Supplies: the colony's own goods near the base are usable, so colonists have something to build with.

A new colony's starting goods (wood, steel, components, silver, gear) lie forbidden where they
landed. In the first run, bed blueprints waited on "0 wood available, 300 forbidden" while all three
colonists stood idle. So this manager unforbids every item near the base (corpses aside), and owns
the idle-colonists alert: if colonists stay idle with nothing left to unforbid, it asks for code.
"""

from __future__ import annotations

from ..manager import TICKS_PER_HOUR, Context, Manager
from .beds import base_anchor

RADIUS = 40          # cells around the base: the starting goods, not loot by distant ruins
SKIP = ["Corpses"]   # hauled to the stockpile they'd rot in
IDLE_ALERT = "Alert_ColonistsIdle"
IDLE_HOLD_HOURS = 12  # idle this long with nothing left to unforbid: a gap in the code


class SuppliesManager(Manager):
    name = "supplies"
    priority = 15  # after food has made the stockpile
    every_hours = 2
    alerts = (IDLE_ALERT,)

    def __init__(self) -> None:
        super().__init__()
        self.idle_since: int | None = None  # harmless to lose on reload: the hold just restarts

    def update(self, ctx: Context) -> None:
        unforbade = self.unforbid(ctx)
        idle = next((a for a in ctx.snapshot.alerts if a.get("type") == IDLE_ALERT), None)
        if idle is None or unforbade:
            self.idle_since = None
            return
        if self.idle_since is None:
            self.idle_since = ctx.tick
        elif ctx.tick - self.idle_since >= IDLE_HOLD_HOURS * TICKS_PER_HOUR:
            ctx.raise_incident(
                "colonistsIdle", f"'{idle.get('label')}' for {IDLE_HOLD_HOURS}h with no forbidden goods "
                f"left near the base: the colonists need work this code doesn't give them.",
                alert=idle)

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
