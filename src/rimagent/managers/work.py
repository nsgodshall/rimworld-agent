"""Work: every colonist does every kind of work they can, emergencies first, research gets done.

- A new colony's colonists start with work they're poor at switched off, and nothing switched it back on:
  in trial 4 Sparky (no hauling or cleaning in him) had only construction and warden on and stood idle
  whenever nothing was being built, and Bishop never sowed or harvested. So everything a colonist can do
  is on: idle hands are worse than unskilled ones.
- With everything at one priority, colonists work in the game's fixed order, where research comes last:
  in trials 1-6 the colony's one researcher finished nothing in a week. So the colony uses manual
  priorities (docs/reference/work.md, after the wiki's starter setup):
  1  firefighting, being a patient and bed rest, for everyone; doctoring for the best doctor
  2  research for the best researcher; work a colonist has a passion for (passion work also lifts mood)
  3  everything else they can do
"""

from __future__ import annotations

from rimsdk import errors

from ..manager import Context, Manager

WORKERS = ("colonist", "slave")
EMERGENCY = ("Firefighter", "Patient", "PatientBedRest")
# Work type -> the skill it uses (for passions and for choosing the doctor and researcher).
SKILL = {"Doctor": "Medicine", "Research": "Intellectual", "Cooking": "Cooking", "Construction": "Construction",
         "Growing": "Plants", "PlantCutting": "Plants", "Mining": "Mining", "Hunting": "Shooting",
         "Crafting": "Crafting", "Smithing": "Crafting", "Tailoring": "Crafting", "Art": "Artistic",
         "Handling": "Animals", "Warden": "Social"}


def skills_of(pawn: dict) -> dict[str, dict]:
    return {s["defName"]: s for s in pawn.get("skills") or [] if s.get("defName")}


def wanted(pawns: list[dict], skills: dict[str, dict[str, dict]]) -> dict[tuple[str, str], int]:
    """(pawn id, work type) -> priority, for every work type each pawn can do."""
    capable = {p["id"]: [w["defName"] for w in p.get("work") or [] if not w.get("disabled")] for p in pawns}

    def best(work_type: str) -> str | None:
        able = [pid for pid, types in capable.items() if work_type in types]
        return max(able, key=lambda pid: skills[pid].get(SKILL[work_type], {}).get("level", 0), default=None)

    leads = {("Doctor", best("Doctor")), ("Research", best("Research"))}
    out = {}
    for pid, types in capable.items():
        for work_type in types:
            passion = skills[pid].get(SKILL.get(work_type, ""), {}).get("passion") not in (None, "None")
            if work_type in EMERGENCY or (work_type == "Doctor" and ("Doctor", pid) in leads):
                out[(pid, work_type)] = 1
            elif (work_type == "Research" and ("Research", pid) in leads) or passion:
                out[(pid, work_type)] = 2
            else:
                out[(pid, work_type)] = 3
    return out


class WorkManager(Manager):
    name = "work"
    priority = 3  # early: work settings shape what everything placed later gets done
    every_hours = 12  # catches colonists who join later

    def update(self, ctx: Context) -> None:
        pawns = [p for p in ctx.rim.list_work(detail="normal").data.get("pawns") or [] if p.get("role") in WORKERS]
        skills = {p["id"]: skills_of(ctx.rim.get_pawn(p["id"], detail="normal").data or {}) for p in pawns}
        current = {(p["id"], w["defName"]): w.get("priority", 0) for p in pawns for w in p.get("work") or []}
        names = {p["id"]: p.get("name") for p in pawns}
        changed: dict[str, list[str]] = {}
        for (pid, work_type), priority in sorted(wanted(pawns, skills).items()):
            if current.get((pid, work_type)) == priority:
                continue
            try:
                ctx.rim.set_pawn_work_priority(pid, work_type, priority=priority)
            except errors.Conflict as exc:  # can't do it after all, or doesn't work at all
                ctx.raise_incident("workRefused", f"{names[pid]}: the game refused {work_type}: {exc.message}", "warn",
                                   pawn=pid)
                continue
            changed.setdefault(pid, []).append(f"{work_type} {priority}")
        for pid, items in changed.items():
            ctx.log(self.name, f"{names[pid]}: {', '.join(items)}.", pawn=pid)
