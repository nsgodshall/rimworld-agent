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
- While stored food is short, food work comes first: cooking (which butchers too), hunting and growing at 1,
  hauling (which stores the harvest and fuels the stove) at 2. In run 20261029-114409 stored food sat at 0
  for a day with rice ripe in the field, a butcher spot and a stove waiting for fuel, while all three
  colonists felled trees.
- While usable wood is under 50, felling trees (plant cutting) goes to 2 for everyone.
- Two evening hours are recreation (`schedule`).
"""

from __future__ import annotations

from rimsdk import errors

from ..manager import Context, Manager

WORKERS = ("colonist", "slave")
EMERGENCY = ("Firefighter", "Patient", "PatientBedRest")
FOOD_SHORT_DAYS = 2.0  # stored food under this many days puts food work first
FOOD_WORK = {"Cooking": 1, "Hunting": 1, "Growing": 1, "Hauling": 2}
# With no wood, every build waits: in trial 9 the house's walls and the research bench stood as blueprints at
# 0 wood while one colonist felled trees. Under this much usable wood, felling goes to 2 for everyone.
WOOD_SHORT = 50
WOOD_WORK = {"PlantCutting": 2}
JOY_HOURS = (20, 22)  # evening, before the default 22:00 bedtime
# Work type -> the skill it uses (for passions and for choosing the doctor and researcher).
SKILL = {"Doctor": "Medicine", "Research": "Intellectual", "Cooking": "Cooking", "Construction": "Construction",
         "Growing": "Plants", "PlantCutting": "Plants", "Mining": "Mining", "Hunting": "Shooting",
         "Crafting": "Crafting", "Smithing": "Crafting", "Tailoring": "Crafting", "Art": "Artistic",
         "Handling": "Animals", "Warden": "Social"}


def skills_of(pawn: dict) -> dict[str, dict]:
    return {s["defName"]: s for s in pawn.get("skills") or [] if s.get("defName")}


def wanted(pawns: list[dict], skills: dict[str, dict[str, dict]], food_short: bool = False,
           wood_short: bool = False) -> dict[tuple[str, str], int]:
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
            if food_short and work_type in FOOD_WORK:
                out[(pid, work_type)] = min(out[(pid, work_type)], FOOD_WORK[work_type])
            if wood_short and work_type in WOOD_WORK:
                out[(pid, work_type)] = min(out[(pid, work_type)], WOOD_WORK[work_type])
    return out


class WorkManager(Manager):
    name = "work"
    priority = 3  # early: work settings shape what everything placed later gets done
    every_hours = 2  # food work goes first soon after the stores run short; also catches colonists who join

    def update(self, ctx: Context) -> None:
        pawns = [p for p in ctx.rim.list_work(detail="normal").data.get("pawns") or [] if p.get("role") in WORKERS]
        skills = {p["id"]: skills_of(ctx.rim.get_pawn(p["id"], detail="normal").data or {}) for p in pawns}
        current = {(p["id"], w["defName"]): w.get("priority", 0) for p in pawns for w in p.get("work") or []}
        names = {p["id"]: p.get("name") for p in pawns}
        changed: dict[str, list[str]] = {}
        days = ctx.snapshot.food_days
        food_short = days is not None and days < FOOD_SHORT_DAYS
        wood_short = ctx.snapshot.usable("WoodLog") < WOOD_SHORT
        for (pid, work_type), priority in sorted(wanted(pawns, skills, food_short, wood_short).items()):
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
        self.schedule(ctx, pawns)

    def schedule(self, ctx: Context, pawns: list[dict]) -> None:
        """Two evening hours for recreation. With work always on offer, recreation slid to "unfulfilled"
        (-5) and below; it's worth -20 to +10 (docs/reference/mood.md), and the house has horseshoes and chess."""
        start, end = JOY_HOURS
        for p in pawns:
            hours = {h.get("hour"): h.get("assignment") for h in (p.get("schedule") or {}).get("hours") or []}
            if all(hours.get(h) == "Joy" for h in range(start, end)):
                continue
            try:
                ctx.rim.set_pawn_assignment(p["id"], "schedule", assignments=[
                    {"startHour": start, "endHour": end, "assignmentDefName": "Joy"}])
            except (errors.BadRequest, errors.Conflict) as exc:
                ctx.raise_incident("scheduleRefused", f"{p.get('name')}: {exc.message}", "warn", pawn=p["id"])
                continue
            ctx.log(self.name, f"{p.get('name')} has recreation from {start}:00 to {end}:00.", pawn=p["id"])
