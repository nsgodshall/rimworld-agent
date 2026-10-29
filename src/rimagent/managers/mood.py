"""Mood: answer mental breaks, and keep moods up with a place to eat.

A broken colonist can't be drafted or ordered; the player can only wait it out or deal with what
the break does. Most breaks (sad wandering, crying, a food binge, an insulting spree, a tantrum)
end on their own and harm little, so they are waited out. Breaks that hurt or lose colonists
(berserk, fire starting, giving up and leaving, a drug binge, ...) are left unhandled, so the
runtime stops for code that deals with them.

Before a break, the game warns with break-risk alerts: Alert_MinorBreakRisk, and one alert for
major and extreme, Alert_MajorOrExtremeBreakRisk (there is no Alert_MajorBreakRisk; claiming that
name left the real alert unclaimed in run 20261029-074313, where Sparky, starving behind a blocked
door, sat at major risk). The cheapest lasting lift is a dining table with a chair per colonist: it
ends "Ate without table" and gives comfort. So there is always one by the stockpile, and the worst
thoughts and emptiest needs of colonists at risk are logged (hunger shows as a need, not a thought).
Extreme risk (mood under 5%) can mean berserk rages and needs more than this, so it stops the run.
"""

from __future__ import annotations

import uuid

from rimsdk.mapview import Rect

from ..events import Event
from ..manager import Context, Manager
from .beds import base_anchor
from .defense import pawn_id
from .food import _chars, best_site

# Mental state defNames (list_pawns mentalState) that pass on their own and need no response.
WAIT_OUT = frozenset({
    "Wander_Sad", "Wander_OwnRoom", "Wander_Psychotic", "Wander_Psychotic_Short", "WanderConfused",
    "Crying", "Giggling", "Roaming", "PanicFlee", "IdeoChange", "CorpseObsession",
    "Binging_Food", "InsultingSpree", "TargetedInsultingSpree", "SocialFighting",
    "Tantrum", "BedroomTantrum", "TargetedTantrum",
})

BREAK_RISK = ("Alert_MinorBreakRisk", "Alert_MajorOrExtremeBreakRisk")
EXTREME = 0.05  # mood under which a normal pawn is at extreme break risk (traits shift it)
LOW_NEED = 0.15  # needs at or below this are logged with the thoughts
TABLE = "Table2x2c"  # footprint offset (0, 0), 2x2: position is its south-west cell
CHAIR = "DiningChair"
STUFF = "WoodLog"
WINDOW = 20  # side of the square around the base anchor (check_placement's limit)
# Seats around a table at (tx, tz), each facing it, one per side in turn: (dx, dz, rotation).
SEATS = (
    (0, -1, "north"), (1, 2, "south"), (-1, 1, "east"), (2, 0, "west"),
    (1, -1, "north"), (0, 2, "south"), (-1, 0, "east"), (2, 1, "west"),
)


class MoodManager(Manager):
    name = "mood"
    priority = 30  # after food, beds and kitchen: the table goes where they left room
    every_hours = 6  # break risk is checked within hours; the dining pass is a read when it's done
    handles = ("mentalBreak",)
    alerts = BREAK_RISK

    def on_event(self, ctx: Context, event: Event) -> bool:
        who = (event.pawn or {}).get("id")
        colonists = ctx.rim.list_pawns(filter="colonists").data.get("pawns") or []
        pawn = next((p for p in colonists if pawn_id(p) == who), None)
        state = (pawn or {}).get("mentalState")
        name = (event.pawn or {}).get("name") or who
        if pawn is None or not state:
            ctx.log(self.name, f"{name}'s break ({event.detail}) is already over.")
            return True
        if state in WAIT_OUT:
            ctx.log(self.name, f"{name} is {event.detail} ({state}); waiting it out.", state=state)
            return True
        ctx.log(self.name, f"{name} is {event.detail} ({state}); no code for that break.", state=state)
        return False

    def update(self, ctx: Context) -> None:
        if not ctx.board.get("house_dining"):  # the house's common room has the table and chairs
            self.ensure_dining(ctx)
        self.report_risks(ctx)

    def ensure_dining(self, ctx: Context) -> None:
        snap = ctx.snapshot
        seats = min(len(SEATS), len(snap.colonists))
        if not seats:
            return
        buildings = [b for page in ctx.rim.pages(ctx.rim.list_buildings, limit=200)
                     for b in page.data.get("buildings") or []]

        def built(def_: str) -> list[tuple[int, int]]:
            return [(int(b["position"]["x"]), int(b["position"]["z"])) for b in buildings
                    if (b.get("def") or {}).get("defName") == def_ and b.get("position")]

        tables = built(TABLE)
        placements = []
        if tables:
            tx, tz = tables[0]
        else:
            anchor = base_anchor(ctx)
            if anchor is None:
                return
            window = Rect.around(*anchor, WINDOW, WINDOW).clamp(*snap.map_size)
            view = snap.view(window)
            # Our own blueprints count as room, so a set planned last pass and not built yet is found
            # again; placing it again then comes back alreadySatisfied instead of a second table.
            good = _chars(view, "soil", "ground too poor") + (view.symbol_for("blueprint") or "x")
            site = best_site(view, anchor, 4, 4, good=good, min_fill=1.0)
            if site is None:
                ctx.raise_incident("noSite", f"No room for a dining table near {anchor}.", "warn", window=str(window))
                return
            tx, tz = site.x + 1, site.z + 1
            placements.append({"def": TABLE, "stuff": STUFF, "x": tx, "z": tz, "rotation": "north"})

        chairs = set(built(CHAIR))
        spots = [{"def": CHAIR, "stuff": STUFF, "x": tx + dx, "z": tz + dz, "rotation": rot} for dx, dz, rot in SEATS]
        seated = [s for s in spots if (s["x"], s["z"]) in chairs]
        free = [s for s in spots if (s["x"], s["z"]) not in chairs]
        want = max(0, seats - len(seated))
        placements += free[:want]
        if not placements:
            return

        result, rejected = self.place(ctx, placements)
        applied = result.get("applied", 0)
        # A seat that's blocked (a wall, a bed) gives way to the next one round the table.
        retry = free[want:][:sum(p["def"] == CHAIR for p in rejected)]
        if retry:
            again, still = self.place(ctx, retry)
            applied += again.get("applied", 0)
            rejected = [p for p in rejected if p["def"] != CHAIR] + still
        if applied:
            ctx.log(self.name, f"Placed {applied} dining blueprints around a table at ({tx}, {tz}).",
                    seats=seats, chairs=len(seated), blockers=result.get("blockers"))
        if rejected:
            ctx.raise_incident("diningRejected", f"{len(rejected)} dining blueprints were rejected near ({tx}, {tz}).",
                               "warn", rejected=rejected)

    @staticmethod
    def place(ctx: Context, placements: list[dict]) -> tuple[dict, list[dict]]:
        """place_blueprint's reply, and the placements it rejected with the reason (results come in order)."""
        result = ctx.rim.place_blueprint(placements=placements, request_id=uuid.uuid4().hex).data or {}
        rejected = [{"def": p["def"], "x": p["x"], "z": p["z"], "reason": r.get("reason")}
                    for p, r in zip(placements, result.get("results") or []) if r.get("outcome") == "rejected"]
        return result, rejected

    def report_risks(self, ctx: Context) -> None:
        """Log what pulls down the mood of each colonist at break risk, for whoever reads the journal;
        stop the run for one at extreme risk."""
        for alert in ctx.snapshot.alerts:
            if alert.get("type") not in BREAK_RISK:
                continue
            for culprit in alert.get("culprits") or []:
                pawn = ctx.rim.get_pawn(culprit["id"]).data or {}
                mood = pawn.get("mood") or {}
                level = mood.get("level", 0)
                worst = sorted((t for t in mood.get("thoughts") or [] if (t.get("moodOffset") or 0) < 0),
                               key=lambda t: t["moodOffset"])[:4]
                details = {"alert": alert.get("type"), "mood": round(level, 3),
                           "thoughts": [f"{t.get('label')} {t['moodOffset']:+g}" for t in worst],
                           "needs": [f"{n.get('label')} {n.get('level', 0):.2f}" for n in pawn.get("needs") or []
                                     if n.get("defName") != "Mood" and n.get("level", 1) <= LOW_NEED]}
                ctx.log(self.name, f"{culprit.get('label')} is at {alert.get('label', '').lower()} "
                        f"(mood {level:.2f}).", **details)
                if level < EXTREME:
                    ctx.raise_incident("extremeBreakRisk", f"{culprit.get('label')} is at extreme break risk "
                                       f"(mood {level:.2f}); no code for that.", "halt", pawn=culprit["id"], **details)
