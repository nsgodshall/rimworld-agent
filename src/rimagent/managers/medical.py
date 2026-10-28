"""Medical: keep medicine usable, and get bleeding colonists tended before they bleed out.

RimWorld's doctors tend the wounded on their own, but only with medicine they may use, and only
when they're awake and free. In the first raid test, starting medicine lay forbidden while one
colonist bled to death, and the doctor slept while another did. So this manager unforbids medicine,
and while anyone bleeds (and no fight is on), drafts a colonist and orders a tend, again and again,
until the bleeding stops.
"""

from __future__ import annotations

from typing import Any

from rimsdk import errors

from ..events import Event
from ..manager import Context, Manager
from .defense import TEND_JOBS, engaging_threats, pawn_id

UNFORBID_EVERY_TICKS = 2 * 2500
TEND_CHUNK_HOURS = 0.1


class MedicalManager(Manager):
    name = "medical"
    priority = 5  # after defense, before everything else
    every_hours = 0  # every cycle: bleeding can't wait for a schedule
    handles = ("injured",)

    def __init__(self) -> None:
        super().__init__()
        self.unforbid_at: int | None = None
        self.tenders: dict[str, str] = {}  # drafted tender id -> patient id; harmless to lose on reload

    def update(self, ctx: Context) -> None:
        if self.unforbid_at is None or ctx.tick - self.unforbid_at >= UNFORBID_EVERY_TICKS:
            self.unforbid(ctx)
            self.unforbid_at = ctx.tick
        medical = ctx.snapshot.colony.get("medical") or {}
        if not self.tenders and not medical.get("bleeding"):
            return
        colonists = {pawn_id(p): p for p in ctx.rim.list_pawns(filter="colonists").data.get("pawns") or [] if not p.get("dead")}
        self.finish(ctx, colonists)
        if not medical.get("bleeding") or engaging_threats(ctx):
            return  # nobody bleeding, or a fight to finish first (defense's job)
        ctx.request_chunk(TEND_CHUNK_HOURS)
        if any(job_of(p) in TEND_JOBS for p in colonists.values()):
            return  # someone is already tending
        patients = [e["id"] for e in medical.get("examples") or [] if e.get("id") in colonists]
        helpers = [p for p in colonists.values()
                   if not p.get("downed") and not p.get("drafted") and pawn_id(p) not in patients]
        if not patients or not helpers:
            if patients:
                ctx.raise_incident("noTender", f"{len(patients)} colonists bleeding and nobody free to tend them.")
            return
        helper, patient = helpers[0], colonists[patients[0]]
        try:
            ctx.rim.set_pawn_drafted(pawn_id(helper), drafted=True)
            result = ctx.rim.order_pawn(pawn_id(helper), order="tend", target_id=pawn_id(patient)).data or {}
        except errors.RimError as exc:
            ctx.log(self.name, f"{helper['name']} can't tend {patient['name']}: {exc.message}")
            ctx.rim.set_pawn_drafted(pawn_id(helper), drafted=False)
            return
        if result.get("outcome") == "jobIssued":
            self.tenders[pawn_id(helper)] = pawn_id(patient)
            ctx.log(self.name, f"{helper['name']} tends {patient['name']}.")
        else:
            ctx.rim.set_pawn_drafted(pawn_id(helper), drafted=False)
            ctx.log(self.name, f"{helper['name']} can't tend {patient['name']}: {result.get('reason')}")

    def finish(self, ctx: Context, colonists: dict[str, dict[str, Any]]) -> None:
        """Undraft tenders whose tending is over, so they go back to work (or to bed)."""
        for tender in list(self.tenders):
            pawn = colonists.get(tender)
            if pawn is None or job_of(pawn) not in TEND_JOBS:
                if pawn is not None and pawn.get("drafted"):
                    ctx.rim.set_pawn_drafted(tender, drafted=False)
                del self.tenders[tender]

    def unforbid(self, ctx: Context) -> None:
        meds = ctx.rim.find_things(category="Medicine", forbidden=True).data.get("things") or []
        if meds:
            ctx.rim.designate(kind="unforbid", thing_ids=[m["id"] for m in meds][:300])
            ctx.log(self.name, f"Unforbade {len(meds)} medicine stacks.", units=sum(m.get("count") or 0 for m in meds))

    def on_event(self, ctx: Context, event: Event) -> bool:
        # An injury needs medicine and a doctor: update() sees to both on this cycle.
        return True


def job_of(pawn: dict[str, Any]) -> str | None:
    return (pawn.get("currentJob") or {}).get("defName")
