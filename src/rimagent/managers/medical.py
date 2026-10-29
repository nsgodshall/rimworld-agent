"""Medical: keep medicine usable, and get bleeding colonists tended before they bleed out.

RimWorld's doctors tend the wounded on their own, but only with medicine they may use, and only
when they're awake and free. In the first raid test, starting medicine lay forbidden while one
colonist bled to death, and the doctor slept while another did. So this manager unforbids medicine,
and while anyone bleeds (and no fight is on), drafts a colonist and orders a tend, again and again,
until the bleeding stops.

Low medicine (Alert_LowMedicine) counts only medicine in storage, under 2 a colonist. In run
20261029-143226 it showed for 13h with 31 medicine lying unforbidden two cells from a near-empty
stockpile: three days in, nobody had got round to hauling the starting goods. Medicine left outside
also rots. So while the alert shows, loose medicine is marked for hauling and the biggest stack is
hauled now. With none loose either, the colony really is short: that's noted, not stopped for.
"""

from __future__ import annotations

from typing import Any

from rimsdk import errors

from ..events import Event
from ..manager import Context, Manager
from .defense import TEND_JOBS, engaging_threats, pawn_id
from .pantry import rush_hauling

UNFORBID_EVERY_TICKS = 2 * 2500
TEND_CHUNK_HOURS = 0.1
LOW_MEDICINE_ALERT = "Alert_LowMedicine"
STORE_EVERY_TICKS = 2 * 2500      # how often loose medicine is marked and rushed while the alert shows
SHORT_NOTE_EVERY_TICKS = 24 * 2500  # a real shortage is noted at most once a day


class MedicalManager(Manager):
    name = "medical"
    priority = 5  # after defense, before everything else
    every_hours = 0  # every cycle: bleeding can't wait for a schedule
    handles = ("injured",)
    alerts = (LOW_MEDICINE_ALERT,)

    def __init__(self) -> None:
        super().__init__()
        self.unforbid_at: int | None = None
        self.tenders: dict[str, str] = {}  # drafted tender id -> patient id; harmless to lose on reload

    def update(self, ctx: Context) -> None:
        if self.unforbid_at is None or ctx.tick - self.unforbid_at >= UNFORBID_EVERY_TICKS:
            self.unforbid(ctx)
            self.unforbid_at = ctx.tick
        self.store_medicine(ctx)
        medical =ctx.snapshot.colony.get("medical") or {}
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

    def store_medicine(self, ctx: Context) -> None:
        """While Low medicine shows, get loose medicine into storage. The alert counts only stored medicine."""
        alert = next((a for a in ctx.snapshot.alerts if a.get("type") == LOW_MEDICINE_ALERT), None)
        last = self.memory.get("stored_at")
        if alert is None or (last is not None and 0 <= ctx.tick - last < STORE_EVERY_TICKS):
            return
        self.memory["stored_at"] = ctx.tick
        loose = ctx.rim.find_things(category="Medicine", forbidden=False, in_storage=False).data.get("things") or []
        if not loose:
            last_note = self.memory.get("short_noted_at")
            if last_note is None or not 0 <= ctx.tick - last_note < SHORT_NOTE_EVERY_TICKS:
                self.memory["short_noted_at"] = ctx.tick
                ctx.raise_incident("medicineShort", "Low medicine, and no loose medicine left to store: "
                                   "doctors will tend without it.", "warn", alert=alert)
            return
        ctx.rim.designate(kind="haul", thing_ids=[m["id"] for m in loose][:300])
        rushed = [] if ctx.snapshot.hostiles else rush_hauling(
            ctx, sorted(loose, key=lambda m: -(m.get("count") or 0))[:1])
        ctx.log(self.name, f"Low medicine: marked {len(loose)} loose medicine stacks for hauling; "
                f"{len(rushed)} hauled now.", units=sum(m.get("count") or 0 for m in loose), rushed=rushed)

    def on_event(self, ctx: Context, event: Event) -> bool:
        # An injury needs medicine and a doctor: update() sees to both on this cycle.
        return True


def job_of(pawn: dict[str, Any]) -> str | None:
    return (pawn.get("currentJob") or {}).get("defName")
