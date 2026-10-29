"""Defense: keep colonists armed, gather and fight when hostiles come near, rescue the downed after.

The tactic: as soon as live hostiles are anywhere on the map, draft everyone who can fight and hold
near the base (the stockpile), each shooter on a
cell with cover (a tree, rock, wall or building) between them and the raiders, melee fighters a few
cells behind; undraft once no live hostile is near. In the first raid test, three colonists standing
together in the open went down in seconds. In the second, the raiders were still far from the base
when a colonist working across the map walked into them, so the code no longer waits for hostiles
to come near: colonists come home. Chokepoints and retreats are for later.

Between fights it fortifies: a short line of wooden barricades on each side of the base, a few cells
out, so shooters gathering there find cover whichever way the raid comes from. That also answers the
game's "Need defenses" alert (Alert_NeedDefenses), which wants a turret, trap, sandbags or barricade.
Sandbags take cloth or leather, which an early colony often lacks; barricades take wood.
"""

from __future__ import annotations

import uuid
from typing import Any

from rimsdk import errors

from ..events import Event
from ..manager import Context, Manager
from rimsdk.mapview import MapView, Rect

from .beds import base_anchor
from .materials import STEEL, pick

ENGAGE_RADIUS = None      # hostiles this many cells from the base trigger the defense; None: anywhere
COMBAT_CHUNK_HOURS = 0.1  # time runs while fighting: 250 ticks, about 4 seconds at Normal speed
MAX_COMBAT_HOURS = 8      # drafted this long means the fight isn't going the way this code expects
COVER_SEARCH = 10         # cells around the base searched for covered positions
SPACING = 2               # least distance between two fighters' cells
TEND_JOBS = {"TendPatient"}
BUSY_HELPING = {"Rescue", *TEND_JOBS, "TakeToBedToOperate"}
SPREAD = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)]
# Map-view meanings (legend text prefixes) that stop bullets, and that a pawn can stand on.
COVER = ("tree", "natural rock", "wall", "other building", "blueprint or unfinished building")
STANDABLE = ("soil", "rich soil", "ground too poor", "stockpile zone", "growing zone")
# Fortification: a barricade line this long on each side of the base, this many cells out.
BARRICADE = "Barricade"
BARRICADE_STUFF = "WoodLog"
FORTIFICATIONS = {"Barricade", "Sandbags"}
SEGMENT = 5  # covered cells for three shooters, SPACING apart
FORT_DISTANCES = range(4, 9)
FORT_SHIFTS = (0, 1, -1, 2, -2)
SIDES = ((0, 1), (1, 0), (0, -1), (-1, 0))
FORTIFY_EVERY = 24 * 2500


class DefenseManager(Manager):
    name = "defense"
    priority = 0  # a fight comes first
    every_hours = 0  # every cycle: it must notice a fight, and its end, at once
    handles = ("hostiles", "threatLetter", "downed")
    alerts = ("Alert_NeedDefenses",)  # answered by fortify()

    def __init__(self) -> None:
        super().__init__()
        self.combat_since: int | None = None  # a timer, not memory: losing it on reload is harmless
        self.armed_at: int | None = None
        self.fortified_at: int | None = None

    def update(self, ctx: Context) -> None:
        threats = engaging_threats(ctx)
        if threats:
            self.fight(ctx, threats)
        else:
            self.stand_down(ctx)
            # Carry the downed to bed once nobody bleeds: tending (managers/medical.py) comes first.
            bleeding = (ctx.snapshot.colony.get("medical") or {}).get("bleeding")
            if not bleeding and any(p.get("downed") for p in ctx.snapshot.colonists):
                self.rescue(ctx)
            if self.armed_at is None or ctx.tick - self.armed_at >= 12 * 2500:
                self.arm(ctx)
                self.armed_at = ctx.tick
            if self.fortified_at is None or ctx.tick - self.fortified_at >= FORTIFY_EVERY:
                self.fortify(ctx)
                self.fortified_at = ctx.tick

    def on_event(self, ctx: Context, event: Event) -> bool:
        threats = engaging_threats(ctx)
        if event.kind == "downed":
            # Downed in a fight: rescued once it's over. Otherwise now.
            if not threats:
                self.rescue(ctx)
            return True
        if threats:
            self.fight(ctx, threats)
            return True
        # Raiders arrive at the map edge, out of reach: this manager has them once they're visible
        # anywhere, and fights when they come near. A threat letter with no hostiles on the map
        # (a quest's warning, a coming siege...) isn't something this code understands.
        return event.kind == "hostiles" or bool(engaging_threats(ctx, radius=None))

    # --- fighting ----------------------------------------------------------------------------

    def fight(self, ctx: Context, threats: list[dict[str, Any]]) -> None:
        anchor = base_anchor(ctx)
        if anchor is None:
            return
        if self.combat_since is None:
            self.combat_since = ctx.tick
            ctx.log(self.name, f"{len(threats)} hostiles on the map: drafting everyone home.",
                    threats=[describe(t) for t in threats][:10])
        elif ctx.tick - self.combat_since >= MAX_COMBAT_HOURS * 2500:
            ctx.raise_incident("longFight", f"Drafted for {MAX_COMBAT_HOURS}h against {len(threats)} hostiles.",
                               threats=[describe(t) for t in threats][:10])
        ctx.request_chunk(COMBAT_CHUNK_HOURS)

        pawns = ctx.rim.list_pawns(filter="colonists", include=["gear"]).data.get("pawns") or []
        fighters = [p for p in pawns if not p.get("downed") and not p.get("dead")]
        shooters = [p for p in fighters if has_gun(p)]
        spots = positions(ctx.snapshot.view(Rect.around(*anchor, 2 * COVER_SEARCH + 1, 2 * COVER_SEARCH + 1)),
                          anchor, centroid(threats), len(shooters), len(fighters) - len(shooters))
        for pawn, spot in zip(shooters + [p for p in fighters if not has_gun(p)], spots):
            pid = pawn_id(pawn)
            if not pawn.get("drafted"):
                try:
                    ctx.rim.set_pawn_drafted(pid, drafted=True)
                except errors.RimError as exc:  # e.g. incapable of violence
                    ctx.log(self.name, f"Couldn't draft {pawn['name']}: {exc.message}")
                    continue
            pos = pawn.get("position") or {}
            # Only move pawns that are out of place: a move order interrupts their shooting.
            if abs(pos.get("x", spot[0]) - spot[0]) > 1 or abs(pos.get("z", spot[1]) - spot[1]) > 1:
                ctx.rim.order_pawn(pid, order="move", x=spot[0], z=spot[1])

    def stand_down(self, ctx: Context) -> None:
        # Colonists drafted to tend (managers/medical.py) stay drafted until they're done.
        drafted = [p for p in ctx.snapshot.colonists if p.get("drafted")
                   and (p.get("currentJob") or {}).get("defName") not in TEND_JOBS]
        if self.combat_since is None and not drafted:
            return
        for pawn in drafted:
            ctx.rim.set_pawn_drafted(pawn_id(pawn), drafted=False)
        if self.combat_since is not None:
            ctx.log(self.name, f"No hostiles near after {(ctx.tick - self.combat_since) / 2500:.1f}h: undrafted {len(drafted)}.")
        self.combat_since = None

    def rescue(self, ctx: Context) -> None:
        # Read afresh: the snapshot predates this cycle's undrafting, and a fight can add colonists
        # (RimWorld's "man in black" joins when everyone is down).
        colonists = [p for p in ctx.rim.list_pawns(filter="colonists").data.get("pawns") or [] if not p.get("dead")]
        # In bed (LayDown) already: the doctors take it from there.
        downed = [p for p in colonists if p.get("downed") and (p.get("currentJob") or {}).get("defName") != "LayDown"]
        if not downed:
            return
        able = [p for p in colonists if not p.get("downed") and not p.get("drafted")]
        if not able:
            ctx.raise_incident("noRescuer", f"{len(downed)} colonists downed and nobody can carry them.")
            return
        # Leave anyone already carrying or tending to it; the rest wait for the next cycle.
        free = [p for p in able if (p.get("currentJob") or {}).get("defName") not in BUSY_HELPING]
        for patient, helper in zip(downed, free):
            result = ctx.rim.order_pawn(pawn_id(helper), order="rescue", target_id=pawn_id(patient), request_id=uuid.uuid4().hex)
            ctx.log(self.name, f"{helper['name']} rescues {patient['name']}.", result=(result.data or {}).get("outcome"))

    # --- arming ------------------------------------------------------------------------------

    def arm(self, ctx: Context) -> None:
        """Give every unarmed colonist a weapon lying on the map, guns first."""
        pawns = ctx.rim.list_pawns(filter="colonists", include=["gear"]).data.get("pawns") or []
        unarmed = [p for p in pawns if not p.get("dead") and not p.get("downed")
                   and not ((p.get("gear") or {}).get("equipment"))]
        if not unarmed:
            return
        weapons = ctx.rim.find_things(category="Weapons").data.get("things") or []
        # Guns (Gun_*) before melee weapons; most early raids shoot.
        weapons.sort(key=lambda t: (not str(t.get("def", "")).startswith("Gun_"), str(t.get("def"))))
        forbidden = [t["id"] for t in weapons if t.get("forbidden")]
        if forbidden:
            ctx.rim.designate(kind="unforbid", thing_ids=forbidden)
        for pawn, weapon in zip(unarmed, weapons):
            result = ctx.rim.order_pawn(pawn_id(pawn), order="equip", target_id=weapon["id"], queue=True,
                                        request_id=uuid.uuid4().hex)
            ctx.log(self.name, f"{pawn['name']} equips {weapon.get('def')}.", result=(result.data or {}).get("outcome"))

    # --- fortifying --------------------------------------------------------------------------

    def fortify(self, ctx: Context) -> None:
        """A barricade line on each side of the base that has none: the cover positions() looks for."""
        anchor = base_anchor(ctx)
        if anchor is None:
            return
        built = {(b["position"]["x"], b["position"]["z"])
                 for page in ctx.rim.pages(ctx.rim.list_buildings, limit=200)
                 for b in page.data.get("buildings") or []
                 if (b.get("def") or {}).get("defName") in FORTIFICATIONS and "x" in (b.get("position") or {})}
        view = ctx.snapshot.view(Rect.around(*anchor, 2 * COVER_SEARCH + 1, 2 * COVER_SEARCH + 1))
        placements = []
        for side in SIDES:
            if sum(c in built for c in side_area(anchor, side)) >= SEGMENT:
                continue
            line = barricade_line(view, anchor, side, built)
            if line is None:
                ctx.log(self.name, f"No room for barricades on side {side} of the base.")
                continue
            placements += [{"def": BARRICADE, "x": x, "z": z} for x, z in line if (x, z) not in built]
        if not placements:
            return
        # Steel when wood is short (trial 6 ran out of wood). Chosen once, so repeats are alreadySatisfied.
        stuff = self.memory.setdefault("barricade_stuff", pick(ctx, 5 * len(placements), (BARRICADE_STUFF, STEEL)))
        placements = [{**p, "stuff": stuff} for p in placements]
        result = ctx.rim.place_blueprint(placements=placements, request_id=uuid.uuid4().hex).data or {}
        if result.get("applied"):
            rejected = [{k: r.get(k) for k in ("x", "z", "reason")}
                        for r in result.get("results") or [] if r.get("outcome") == "rejected"]
            ctx.log(self.name, f"Placed {result['applied']} barricade blueprints around the base.",
                    rejected=rejected, blockers=result.get("blockers"))


def engaging_threats(ctx: Context, radius: int | None = ENGAGE_RADIUS) -> list[dict[str, Any]]:
    """Live hostile pawns within `radius` cells of the base (None: anywhere): raiders, mechanoids,
    insects, manhunters. Not predators that merely roam (threatKind "animal"), fires, or the downed."""
    if not ctx.snapshot.colony.get("threats", {}).get("total"):
        return []
    anchor = base_anchor(ctx)
    if anchor is None:
        return []
    near = []
    for t in ctx.rim.list_threats().data.get("threats") or []:
        if t.get("kind") != "pawn" or t.get("downed") or t.get("threatKind") == "animal":
            continue
        pos = t.get("position") or {}
        if radius is None or ("x" in pos and max(abs(pos["x"] - anchor[0]), abs(pos["z"] - anchor[1])) <= radius):
            near.append(t)
    return near


def positions(view: MapView, anchor: tuple[int, int], enemy: tuple[float, float], shooters: int, melee: int) -> list[tuple[int, int]]:
    """Cells for the shooters, nearest the base first, each with cover on its side facing the enemy,
    then cells for melee fighters three cells behind the base. Falls back to a tight group."""
    cover = "".join(s for s, text in view.legend.items() if text.startswith(COVER))
    ground = "".join(s for s, text in view.legend.items() if text.startswith(STANDABLE))
    dx, dz = _sign(enemy[0] - anchor[0]), _sign(enemy[1] - anchor[1])
    covered = sorted(
        (xz for xz, ch in view.cells.items()
         if ch in ground and view.is_((xz[0] + dx, xz[1] + dz), cover) and (dx or dz)),
        key=lambda xz: (abs(xz[0] - anchor[0]) + abs(xz[1] - anchor[1]), xz),
    )
    # Two cells apart at least: raiders throw grenades, and one shouldn't catch two colonists.
    spots: list[tuple[int, int]] = []
    for xz in covered:
        if len(spots) == shooters:
            break
        if all(max(abs(xz[0] - s[0]), abs(xz[1] - s[1])) >= SPACING for s in spots):
            spots.append(xz)
    spread = [(anchor[0] + SPACING * sx, anchor[1] + SPACING * sz) for sx, sz in SPREAD]
    spots += [s for s in spread if s not in spots][: shooters - len(spots)]
    back = (anchor[0] - 3 * dx, anchor[1] - 3 * dz)
    spots += [(back[0] + SPACING * sx, back[1] + SPACING * sz) for sx, sz in SPREAD[:melee]]
    return spots


def _line(anchor: tuple[int, int], side: tuple[int, int], dist: int, shift: int) -> list[tuple[int, int]]:
    """SEGMENT cells across `side`, `dist` cells out from the anchor and `shift` cells along."""
    (dx, dz), (px, pz) = side, (side[1], side[0])
    return [(anchor[0] + dist * dx + (shift + k) * px, anchor[1] + dist * dz + (shift + k) * pz)
            for k in range(-(SEGMENT // 2), SEGMENT - SEGMENT // 2)]


def side_area(anchor: tuple[int, int], side: tuple[int, int]) -> set[tuple[int, int]]:
    return {c for d in FORT_DISTANCES for s in FORT_SHIFTS for c in _line(anchor, side, d, s)}


def barricade_line(view: MapView, anchor: tuple[int, int], side: tuple[int, int],
                   built: set[tuple[int, int]]) -> list[tuple[int, int]] | None:
    """The nearest line on `side` that is open ground (not fields, zones, items or trees), or already
    planned or built. A fixed order, so the next pass finds the line it planned last time."""
    open_ = "".join(s for s, text in view.legend.items() if text.startswith(("soil", "ground too poor")))
    planned = view.symbol_for("blueprint") or "x"
    for dist in FORT_DISTANCES:
        for shift in FORT_SHIFTS:
            line = _line(anchor, side, dist, shift)
            if all(c in built or view.is_(c, open_ + planned) for c in line):
                return line
    return None


def centroid(threats: list[dict[str, Any]]) -> tuple[float, float]:
    cells = [t["position"] for t in threats if "x" in (t.get("position") or {})]
    return sum(c["x"] for c in cells) / len(cells), sum(c["z"] for c in cells) / len(cells)


def _sign(v: float) -> int:
    return (v > 0.5) - (v < -0.5)


def has_gun(pawn: dict[str, Any]) -> bool:
    return any(str((e.get("def") or {}).get("defName", "")).startswith("Gun_") for e in (pawn.get("gear") or {}).get("equipment") or [])


def pawn_id(pawn: dict[str, Any]) -> str:
    return (pawn.get("ids") or {}).get("id") or pawn["name"]


def describe(threat: dict[str, Any]) -> str:
    pos = threat.get("position") or {}
    return f"{threat.get('name') or threat.get('label')} ({threat.get('threatKind')}) at ({pos.get('x')}, {pos.get('z')})"
