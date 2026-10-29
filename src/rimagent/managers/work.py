"""Work: every colonist does every kind of work they're capable of.

A new colony's colonists start with work they're poor at switched off, and nothing switched it back
on: in trial 4, Sparky (no hauling or cleaning in him) had only construction and warden on and stood
idle whenever nothing was being built, and Bishop never sowed or harvested. Idle hands are worse
than unskilled ones, so this turns everything a colonist can do on, at the simple-mode priority 3
(which keeps the colony out of manual priorities).
"""

from __future__ import annotations

from rimsdk import errors

from ..manager import Context, Manager

PRIORITY = 3  # what the work tab's checkbox sets; any other value switches the colony to manual priorities
WORKERS = ("colonist", "slave")


class WorkManager(Manager):
    name = "work"
    priority = 3  # early: work settings shape what everything placed later gets done
    every_hours = 12  # catches colonists who join later

    def update(self, ctx: Context) -> None:
        pawns = ctx.rim.list_work(detail="normal").data.get("pawns") or []
        for pawn in pawns:
            if pawn.get("role") not in WORKERS:
                continue
            off = [w["defName"] for w in pawn.get("work") or [] if not w.get("disabled") and not w.get("active")]
            enabled, refused = [], []
            for work_type in off:
                try:
                    ctx.rim.set_pawn_work_priority(pawn["id"], work_type, priority=PRIORITY)
                    enabled.append(work_type)
                except errors.Conflict as exc:  # can't do it after all, or doesn't work at all
                    refused.append(f"{work_type}: {exc.message}")
            if enabled:
                ctx.log(self.name, f"{pawn.get('name')} now does {', '.join(enabled)}.", pawn=pawn["id"])
            if refused:
                ctx.raise_incident("workRefused", f"{pawn.get('name')}: the game refused {len(refused)} work types.",
                                   "warn", pawn=pawn["id"], refused=refused)
