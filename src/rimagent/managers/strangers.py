"""Strangers: carry downed strangers (a transport pod's crash survivor, say) to a free bed.

A rescued stranger is tended and, healed, may ask to join: the colony wants two more colonists, and joiners
who just walk up are rare (none in fourteen days of trials 22-25), while pod crashes came in most runs. The
wing keeps beds free for them (house.WingManager). Never during a fight; one rescue at a time.
"""

from __future__ import annotations

from rimsdk import errors

from ..manager import Context, Manager
from .defense import BUSY_HELPING, engaging_threats, pawn_id


class StrangersManager(Manager):
    name = "strangers"
    priority = 6  # after defense and medical: colonists first
    every_hours = 1

    def update(self, ctx: Context) -> None:
        strangers = [p for p in ctx.rim.list_pawns(filter="others").data.get("pawns") or []
                     if p.get("downed") and not p.get("dead") and (p.get("def") or {}).get("defName", "Human") == "Human"]
        if not strangers or engaging_threats(ctx, radius=None):
            return
        colonists = ctx.snapshot.colonists
        if any((p.get("currentJob") or {}).get("defName") == "Rescue" for p in colonists):
            return  # one at a time
        helpers = [p for p in colonists if not p.get("downed") and not p.get("drafted")
                   and (p.get("currentJob") or {}).get("defName") not in BUSY_HELPING]
        waiting = self.memory.setdefault("refused_until", {})
        for stranger in strangers:
            sid = pawn_id(stranger)
            if waiting.get(sid, 0) > ctx.tick:
                continue
            for helper in helpers:
                try:
                    result = ctx.rim.order_pawn(pawn_id(helper), order="rescue", target_id=sid).data or {}
                except errors.RimError as exc:
                    result = {"outcome": "rejected", "reason": exc.message}
                if result.get("outcome") == "jobIssued":
                    ctx.log(self.name, f"{helper.get('name')} carries {stranger.get('name')} to a bed.", stranger=sid)
                    return
                if result.get("outcome") == "alreadySatisfied":  # in bed already
                    break
            # Nobody could (no free bed, or they can't carry): try again in a few hours.
            waiting[sid] = ctx.tick + 4 * 2500
            ctx.log(self.name, f"Couldn't rescue {stranger.get('name')} now: {result.get('reason')}.", stranger=sid)
