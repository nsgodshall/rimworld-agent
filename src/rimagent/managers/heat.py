"""Heatstroke: walk badly heatstruck colonists into the coolest room and keep them there until they recover.

In a heat wave it's 40+ C outdoors (43 C on day 9, trial 9) while the house's passive coolers keep the
rooms at 17-22 C (house._cool). Colonists still work outside and catch heatstroke, which "gets worse until
death" with exposure, but "recovery is quick once in a cool area" (get_def Heatstroke). The game names
its stage in the label, "Heatstroke (initial)"; from moderate on (severity 0.2; then serious 0.35,
extreme 0.62, death at 1) this manager drafts the colonist into the coolest enclosed room and holds them
there until it's back below minor (0.04). The mild stages are left alone: they fade by themselves
indoors, and the alert shows for them too (both culprits on day 9 were "initial", resting indoors).

Drafted colonists don't eat or sleep, so a hold lasts at most MAX_HOLD_HOURS. Defense undrafts everyone
when no hostiles are near; it leaves the colonists on the board's "cooling" list alone. During a fight
defense has everyone: nothing here then.
"""

from __future__ import annotations

from typing import Any

from rimsdk import errors

from ..manager import Context, Manager
from .defense import engaging_threats, pawn_id

ALERT = "Alert_Heatstroke"
MODERATE = 0.2       # stage thresholds of Heatstroke; from here on, get them cool
RECOVERED = 0.04     # below minor: back to work
COMFORTABLE = 26.0   # docs/reference/rooms.md: comfortable for most pawns up to about 26 C
MAX_HOLD_HOURS = 8
BAD_STAGES = ("moderate", "serious", "extreme")


def heatstroke(pawn: dict[str, Any]) -> float:
    """The pawn's heatstroke severity (list_pawns detail=normal: health.hediffs), 0 without it."""
    worst = 0.0
    for h in (pawn.get("health") or {}).get("hediffs") or ():
        if h.get("defName") == "Heatstroke":
            severity = h.get("severity") or 0.0
            if any(stage in (h.get("label") or "").lower() for stage in BAD_STAGES):
                severity = max(severity, MODERATE)
            worst = max(worst, severity)
    return worst


def room_cell(room: dict[str, Any]) -> tuple[int, int] | None:
    """A cell inside the room, from its id ("room:0:139,143:Bedroom": map, a cell of the room, role)."""
    try:
        x, z = (room.get("id") or "").split(":")[2].split(",")
        return int(x), int(z)
    except (IndexError, ValueError):
        return None


class HeatManager(Manager):
    name = "heat"
    priority = 6  # after defense and medical
    every_hours = 0  # every cycle: cheap until the alert shows
    alerts = (ALERT,)

    def update(self, ctx: Context) -> None:
        cooling: dict[str, int] = self.memory.setdefault("cooling", {})  # pawn id -> tick the hold began
        alerted = any(a.get("type") == ALERT for a in ctx.snapshot.alerts)
        if not cooling and not alerted:
            ctx.board["cooling"] = []
            return
        if engaging_threats(ctx):
            return  # defense drafts everyone for the fight; the hold resumes after it
        pawns = {pawn_id(p): p for p in ctx.rim.list_pawns(filter="colonists", detail="normal").data.get("pawns") or []
                 if not p.get("dead")}
        self._release(ctx, pawns, cooling)
        sick = [p for pid, p in pawns.items() if pid not in cooling and not p.get("downed") and heatstroke(p) >= MODERATE]
        if sick:
            self._cool_down(ctx, sick, cooling)
        ctx.board["cooling"] = sorted(cooling)

    def _release(self, ctx: Context, pawns: dict[str, dict[str, Any]], cooling: dict[str, int]) -> None:
        for pid, since in list(cooling.items()):
            pawn = pawns.get(pid)
            severity = heatstroke(pawn) if pawn else 0.0
            held = (ctx.tick - since) / 2500
            if pawn is not None and not pawn.get("downed") and severity >= RECOVERED and held < MAX_HOLD_HOURS:
                continue
            del cooling[pid]
            if pawn is None:
                continue
            if pawn.get("drafted"):
                ctx.rim.set_pawn_drafted(pid, drafted=False)
            if severity >= RECOVERED and not pawn.get("downed"):
                ctx.raise_incident("heatstrokeLingers", f"{pawn.get('name')} still has heatstroke ({severity:.2f}) "
                                   f"after {held:.0f}h in the coolest room; let go to eat and sleep.", "warn")
            else:
                ctx.log(self.name, f"{pawn.get('name')} has cooled down ({severity:.2f}): back to work.")

    def _cool_down(self, ctx: Context, sick: list[dict[str, Any]], cooling: dict[str, int]) -> None:
        rooms = (ctx.rim.get_environment().data.get("rooms") or {}).get("items") or []
        cool = sorted((r for r in rooms if not r.get("usesOutdoorTemperature") and room_cell(r)
                       and (r.get("temperatureC") or 99) < COMFORTABLE), key=lambda r: r["temperatureC"])
        if not cool:
            ctx.raise_incident("noCoolRoom", f"{len(sick)} colonists heatstruck and no enclosed room under "
                               f"{COMFORTABLE:.0f} C to cool them in.", "warn",
                               pawns=[(p.get("name"), round(heatstroke(p), 2)) for p in sick])
            return
        room = cool[0]
        x, z = room_cell(room)
        for pawn in sick:
            pid = pawn_id(pawn)
            try:
                if not pawn.get("drafted"):
                    ctx.rim.set_pawn_drafted(pid, drafted=True)
                result = ctx.rim.order_pawn(pid, order="move", x=x, z=z).data or {}
            except errors.RimError as exc:
                ctx.log(self.name, f"Couldn't move {pawn.get('name')} somewhere cool: {exc.message}")
                ctx.rim.set_pawn_drafted(pid, drafted=False)
                continue
            if result.get("outcome") not in ("jobIssued", "alreadySatisfied"):
                ctx.log(self.name, f"Couldn't move {pawn.get('name')} somewhere cool: {result.get('reason')}")
                ctx.rim.set_pawn_drafted(pid, drafted=False)
                continue
            cooling[pid] = ctx.tick
            ctx.log(self.name, f"{pawn.get('name')} has heatstroke ({heatstroke(pawn):.2f}): resting in the "
                               f"{room.get('role')} at {room['temperatureC']:.0f} C.", where=f"({x}, {z})")
