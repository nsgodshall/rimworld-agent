"""Pantry: food lying about goes into storage, and hunters go out before the stores run dry.

The game counts only stored food. In run 20261029-074313 the colony had 48 survival meals, but 46 of
them lay where they landed (10 three cells from the stockpile, the rest across the map) while
everyone chopped and built: hauling is the last work a simple-mode colonist picks. Stored food
read 0.3 days and the run stopped. Nothing raw was in store either, so the stove's bill had nothing
to cook until the rice came in.

A starving colonist (Alert_StarvationColonists) is told to eat the nearest food. One with "No path" to it
is trapped: in the same run Sparky was shut in the house, whose door opened onto an ancient wall. The
house manager moves such a door; if a colonist is still trapped a day later, the run stops for help.

Hunting runs out. In run 20261029-114409 every safe animal on the map was shot by day 4; with no butcher
spot all 27 corpses rotted, and from then on nothing more was marked while stored food sat at 0. So while
food is short, ripe wild berries near the base are marked for harvest too (they keep, and need no butcher
or cook), and a few more small animals count as game.

Low food (Alert_LowFood: stored human food under 4 nutrition per colonist) is this manager's too: it is
what the hauling and hunting below answer, and while it shows, loose food is hauled now rather than when
someone gets round to it. In the same run the alert showed for 14h at 3 days stored, with 62 rice
lying in the field after harvest.
"""

from __future__ import annotations

import math
import uuid

from rimsdk import errors

from ..manager import Context, Manager

LOOSE_LIMIT = 50              # food stacks outside storage looked at per pass, nearest the base first
RUSH_BELOW_DAYS = 2.0         # below this much stored food, an awake colonist hauls the nearest stack now
RUSH_STACKS = 2               # stacks rushed per pass, each by a different colonist
RUSH_OPTION = "Prioritize hauling"
RESTING_JOBS = ("LayDown",)   # asleep or resting: leave them be
STARVING_ALERT = "Alert_StarvationColonists"
LOW_FOOD_ALERT = "Alert_LowFood"  # also rushes hauling, whatever the days left
EAT_OPTION = "Consume"        # list_pawn_actions on food: "Consume packaged survival meal", or "...: No path"
TRAPPED_HALT_HOURS = 24       # a starving colonist with no path to food this long needs a person
HUNT_BELOW_DAYS = 8.0         # hunt while stored food is under this: from day one, as the rations (~7 days) outlast the first harvest by little
HUNT_AT_ONCE = 2              # animals marked for hunting at any one time
# Game that seldom fights back and doesn't bring its herd: no boomalopes, boars, muffalo or predators.
GAME = ("Deer", "Elk", "Caribou", "Ibex", "Gazelle", "Alpaca", "Dromedary", "Emu", "Ostrich", "Capybara",
        "Turkey", "Duck", "Goose", "Hare", "Snowhare", "Squirrel", "Chinchilla", "Iguana",
        "Raccoon", "Rat", "Marmot", "GuineaPig", "Tortoise")
FORAGE_BELOW_DAYS = 5.0       # ripe wild berries near the base are picked while stored food is under this
FORAGE_PLANT = "Plant_Berry"
FORAGE_RADIUS = 60            # cells around the base: four 60x60 rects, designate's largest
DESIGNATE_MAX_CELLS = 3600    # designate rejects a call whose rects cover more cells than this, all told


class PantryManager(Manager):
    name = "pantry"
    priority = 12  # after food, which makes the stockpile
    every_hours = 2  # a stack left lying costs days of stored food
    alerts = (STARVING_ALERT, LOW_FOOD_ALERT)

    def update(self, ctx: Context) -> None:
        snap = ctx.snapshot
        self.feed_starving(ctx)
        if snap.base_center is None or not snap.zones_of("stockpile"):
            return
        self.store_food(ctx)
        self.hunt(ctx)
        self.forage(ctx)

    # --- starving colonists -------------------------------------------------------------------

    def feed_starving(self, ctx: Context) -> None:
        snap = ctx.snapshot
        starving = [c["id"] for a in snap.alerts if a.get("type") == STARVING_ALERT for c in a.get("culprits") or []]
        # Pawn id -> the tick they were first found with no path to food.
        trapped = {pid: t for pid, t in (self.memory.get("trapped") or {}).items() if pid in starving}
        self.memory["trapped"] = trapped
        pawns = {p["ids"]["id"]: p for p in snap.colonists if p.get("ids")}
        for pawn_id in starving:
            pawn = pawns.get(pawn_id)
            if pawn is None or not pawn.get("position") or pawn.get("drafted") or pawn.get("downed"):
                continue  # drafted in a fight, or downed: defense and medical see to them
            x, z = pawn["position"]["x"], pawn["position"]["z"]
            food = ctx.rim.find_things(category="Foods", forbidden=False, x=x, z=z, limit=1).data.get("things") or []
            if not food:
                continue  # nothing to eat at all: hauling, hunting and the fields see to that
            try:
                menu = ctx.rim.list_pawn_actions(pawn_id, target_id=food[0]["id"]).data or {}
                option = next((o for o in menu.get("options") or [] if o.get("text", "").startswith(EAT_OPTION)), None)
                if option is None:
                    continue
                if option.get("disabled"):
                    if "No path" in option["text"]:
                        self.trapped(ctx, pawn_id, food[0], trapped)
                    continue
                trapped.pop(pawn_id, None)
                ctx.rim.choose_pawn_action(pawn_id, target_id=food[0]["id"], revision=menu["revision"],
                                           option=option["id"], request_id=uuid.uuid4().hex)
            except (errors.BadRequest, errors.Conflict, errors.NotFound):
                continue  # the food or the menu changed under us: next pass tries again
            ctx.log(self.name, f"{pawn_id} is starving: told to eat {food[0]['id']}.")

    def trapped(self, ctx: Context, pawn_id: str, food: dict, trapped: dict) -> None:
        first = trapped.setdefault(pawn_id, ctx.tick)
        hours = (ctx.tick - first) / 2500
        details = {"pawn": pawn_id, "food": food["id"], "hours": round(hours, 1)}
        if hours >= TRAPPED_HALT_HOURS:
            ctx.raise_incident("trapped", f"{pawn_id} is starving with no path to food for {hours:.0f}h.", "halt", **details)
        elif first == ctx.tick:
            ctx.raise_incident("trapped", f"{pawn_id} is starving with no path to food.", "warn", **details)

    # --- storage -----------------------------------------------------------------------------

    def store_food(self, ctx: Context) -> None:
        snap = ctx.snapshot
        bx, bz = (round(c) for c in snap.base_center)
        loose = ctx.rim.find_things(category="Foods", forbidden=False, in_storage=False, x=bx, z=bz,
                                    limit=LOOSE_LIMIT).data.get("things") or []
        if not loose:
            return
        # A standing order: colonists haul these when they get round to hauling, however far out they are.
        ctx.rim.designate(kind="haul", thing_ids=[t["id"] for t in loose])
        days = snap.food_days
        low = days is not None and days < RUSH_BELOW_DAYS or any(a.get("type") == LOW_FOOD_ALERT for a in snap.alerts)
        if not low or snap.hostiles:
            ctx.log(self.name, f"Marked {len(loose)} food stacks for hauling.", foodDays=days)
            return
        rushed = rush_hauling(ctx, loose[:RUSH_STACKS])
        ctx.log(self.name, f"Marked {len(loose)} food stacks for hauling; {len(rushed)} hauled now.",
                foodDays=days, rushed=rushed)

    # --- hunting -----------------------------------------------------------------------------

    def hunt(self, ctx: Context) -> None:
        snap = ctx.snapshot
        days = snap.food_days
        if days is None or days >= HUNT_BELOW_DAYS:
            return
        animals = [a for a in ctx.rim.list_pawns(filter="wildAnimals", limit=200).data.get("pawns") or []
                   if not a.get("dead") and not a.get("downed") and a.get("position")]
        alive = {a["ids"]["id"] for a in animals}
        # No read shows hunt designations: remember ours, and forget the ones that died (were hunted).
        marked = [pid for pid in self.memory.get("hunting", []) if pid in alive]
        bx, bz = snap.base_center
        game = sorted((a for a in animals if (a.get("def") or {}).get("defName") in GAME and a["ids"]["id"] not in marked),
                      key=lambda a: math.hypot(a["position"]["x"] - bx, a["position"]["z"] - bz))
        added = []
        for animal in game[:max(0, HUNT_AT_ONCE - len(marked))]:
            try:
                ctx.rim.designate_animal(animal["ids"]["id"], action="hunt")
            except (errors.BadRequest, errors.Conflict, errors.NotFound) as exc:
                ctx.log(self.name, f"Couldn't mark {animal['ids']['id']} for hunting: {exc}")
                continue
            marked.append(animal["ids"]["id"])
            added.append(animal["ids"]["id"])
        self.memory["hunting"] = marked
        if added:
            ctx.log(self.name, f"Food is short ({days:.1f} days): marked {', '.join(added)} for hunting.",
                    hunting=marked)

    # --- foraging ----------------------------------------------------------------------------

    def forage(self, ctx: Context) -> None:
        snap = ctx.snapshot
        days = snap.food_days
        if days is None or days >= FORAGE_BELOW_DAYS:
            return
        # Only ripe plants take the order, and repeats come back alreadySatisfied: safe to ask every pass.
        width, height = snap.map_size
        bx, bz = (round(c) for c in snap.base_center)
        x0, z0 = max(0, bx - FORAGE_RADIUS), max(0, bz - FORAGE_RADIUS)
        x1, z1 = min(width, bx + FORAGE_RADIUS), min(height, bz + FORAGE_RADIUS)
        rects = [{"x": x, "z": z, "width": min(FORAGE_RADIUS, x1 - x), "height": min(FORAGE_RADIUS, z1 - z)}
                 for x in range(x0, x1, FORAGE_RADIUS) for z in range(z0, z1, FORAGE_RADIUS)]
        # The cell limit is per call, not per rect (run 20261029-114409 stopped on four rects in one call).
        batches: list[list[dict]] = []
        for rect in rects:
            cells = rect["width"] * rect["height"]
            if not batches or sum(r["width"] * r["height"] for r in batches[-1]) + cells > DESIGNATE_MAX_CELLS:
                batches.append([])
            batches[-1].append(rect)
        applied = 0
        for batch in batches:
            try:
                result = ctx.rim.designate(kind="harvest", rects=batch, def_name=FORAGE_PLANT).data or {}
            except errors.BadRequest as exc:
                ctx.log(self.name, f"Couldn't mark wild berries for harvest: {exc}", rects=batch)
                continue
            applied += result.get("applied") or 0
        if applied:
            ctx.log(self.name, f"Food is short ({days:.1f} days): marked {applied} wild berry bushes for harvest.",
                    foodDays=days)


def rush_hauling(ctx: Context, stacks: list[dict]) -> list[str]:
    """Each stack gets the nearest awake, free colonist's right-click "Prioritize hauling"."""
    positions = {p["ids"]["id"]: p.get("position") for p in ctx.snapshot.colonists if p.get("ids")}
    free = [p["id"] for p in ctx.rim.list_work(detail="normal").data.get("pawns") or []
            if p.get("role") == "colonist" and not p.get("drafted") and not p.get("downed")
            and (p.get("currentJob") or {}).get("defName") not in RESTING_JOBS and positions.get(p["id"])]
    rushed = []
    for stack in stacks:
        free.sort(key=lambda pid: math.hypot(positions[pid]["x"] - stack["x"], positions[pid]["z"] - stack["z"]))
        for pawn_id in free:
            try:
                menu = ctx.rim.list_pawn_actions(pawn_id, target_id=stack["id"]).data or {}
                option = next((o for o in menu.get("options") or []
                               if o.get("text", "").startswith(RUSH_OPTION) and not o.get("disabled")), None)
                if option is None:
                    continue
                ctx.rim.choose_pawn_action(pawn_id, target_id=stack["id"], revision=menu["revision"],
                                           option=option["id"], request_id=uuid.uuid4().hex)
            except (errors.BadRequest, errors.Conflict, errors.NotFound):
                continue  # the stack or the menu changed under us: next pass tries again
            rushed.append(f"{pawn_id}: {option['text']}")
            free.remove(pawn_id)
            break
    return rushed
