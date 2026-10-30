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
NEEDS_TEND_ALERT = "Alert_ColonistNeedsTend"
MAX_TEND_WAIT_HOURS = 1  # someone "tending" this long while another still bleeds: send a second helper
RETEND_AFTER_HOURS = 4  # a patient found tended already (or untendable) is skipped this long
NEEDS_TEND_HOLD_HOURS = 2  # doctors get this long to tend on their own before someone is drafted to
STORE_EVERY_TICKS = 2 * 2500      # how often loose medicine is marked and rushed while the alert shows
SHORT_NOTE_EVERY_TICKS = 24 * 2500  # a real shortage is noted at most once a day


class MedicalManager(Manager):
    name = "medical"
    priority = 5  # after defense, before everything else
    every_hours = 0  # every cycle: bleeding can't wait for a schedule
    handles = ("injured", "downed")
    alerts = (LOW_MEDICINE_ALERT, NEEDS_TEND_ALERT)

    def __init__(self) -> None:
        super().__init__()
        self.unforbid_at: int | None = None
        self.tenders: dict[str, str] = {}  # drafted tender id -> patient id; harmless to lose on reload

    def update(self, ctx: Context) -> None:
        if self.unforbid_at is None or ctx.tick - self.unforbid_at >= UNFORBID_EVERY_TICKS:
            self.unforbid(ctx)
            self.unforbid_at = ctx.tick
        self.store_medicine(ctx)
        medical = ctx.snapshot.colony.get("medical") or {}
        untended = self.untended(ctx)
        if not self.tenders and not medical.get("bleeding") and not untended:
            return
        colonists = {pawn_id(p): p for p in ctx.rim.list_pawns(filter="colonists").data.get("pawns") or [] if not p.get("dead")}
        self.finish(ctx, colonists)
        if not (medical.get("bleeding") or untended) or engaging_threats(ctx):
            return  # nobody to tend, or a fight to finish first (defense's job)
        if medical.get("bleeding"):
            ctx.request_chunk(TEND_CHUNK_HOURS)
        tending = [p for p in colonists.values() if job_of(p) in TEND_JOBS]
        if tending:
            # Someone is tending already; but not for ever. In trial 24 Sparky bled for five hours after a raid with
            # nobody sent to him, and this is the one quiet way out of here: past an hour, send another helper.
            since = self.memory.setdefault("tending_since", ctx.tick)
            if ctx.tick - since < MAX_TEND_WAIT_HOURS * 2500:
                return
            ctx.log(self.name, f"{', '.join(p['name'] for p in tending)} tending for {(ctx.tick - since) / 2500:.1f}h "
                               "with someone still bleeding: sending another helper.")
            self.memory["tending_since"] = ctx.tick  # and give that one an hour too: not a helper every cycle
        else:
            self.memory.pop("tending_since", None)
        patients = [e["id"] for e in medical.get("examples") or [] if e.get("id") in colonists]
        patients += [pid for pid in untended if pid in colonists and pid not in patients]
        # Skip whoever was found tended already, or couldn't be tended, a little while ago. In trial 22 a tend
        # order came back alreadySatisfied every cycle; each time the helper was drafted again, never ate, and
        # the colonist who did need help (downed, starving) died.
        resting = self.memory.setdefault("tended_until", {})
        patients = [pid for pid in patients if resting.get(pid, 0) <= ctx.tick]
        patients.sort(key=lambda pid: not colonists[pid].get("downed"))  # the downed can't tend themselves
        # Helpers who aren't hurt come first, but a patient still on their feet can tend another. In run
        # 20261029-234707 all three colonists came out of a raid needing tending, Sparky downed, and nobody was
        # counted free: the runtime stopped while the two walking wounded ate berries.
        helpers = sorted((p for p in colonists.values() if not p.get("downed") and not p.get("drafted")
                          and p not in tending),
                         key=lambda p: pawn_id(p) in patients)
        pair = next(((h, colonists[pid]) for pid in patients for h in helpers if pawn_id(h) != pid), None)
        if pair is None:
            if not patients and medical.get("bleeding") and self.memory.get("quiet_noted") != ctx.tick // 2500:
                self.memory["quiet_noted"] = ctx.tick // 2500
                ctx.log(self.name, "Someone is bleeding but no patient is listed to tend.", medical=medical,
                        waiting=self.memory.get("tended_until"))
            if patients:
                ctx.raise_incident("noTender", f"{len(patients)} colonists need tending and nobody is free to.",
                                   "halt" if medical.get("bleeding") else "warn")
            return
        helper, patient = pair
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
            resting[pawn_id(patient)] = ctx.tick + RETEND_AFTER_HOURS * 2500
            ctx.log(self.name, f"{helper['name']} didn't tend {patient['name']} ({result.get('outcome')}: "
                               f"{result.get('reason')}); not again for {RETEND_AFTER_HOURS}h.")

    def untended(self, ctx: Context) -> list[str]:
        """Colonists the game says need treatment (Alert_ColonistNeedsTend) for NEEDS_TEND_HOLD_HOURS: doctors
        usually see to them, but in trial 13 Miyazaki lay 12 hours in bed with untended bruises and cracks."""
        alert = next((a for a in ctx.snapshot.alerts if a.get("type") == NEEDS_TEND_ALERT), None)
        if alert is None:
            self.memory.pop("needs_tend_since", None)
            return []
        since = self.memory.setdefault("needs_tend_since", ctx.tick)
        if ctx.tick - since < NEEDS_TEND_HOLD_HOURS * 2500:
            return []
        return [c["id"] for c in alert.get("culprits") or [] if c.get("id")]

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
        # An injury needs medicine and a doctor: update() sees to both on this cycle. A new injury also ends any
        # wait on that colonist (see RETEND_AFTER_HOURS): in trial 24 Sparky, waited on from an earlier tend,
        # was cut in a raid and bled to death over five hours with nobody sent to him.
        pid = (event.pawn or {}).get("id")
        if pid:
            self.memory.setdefault("tended_until", {}).pop(pid, None)
        return True


def job_of(pawn: dict[str, Any]) -> str | None:
    return (pawn.get("currentJob") or {}).get("defName")
