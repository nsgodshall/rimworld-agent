"""Defense: keep colonists armed, gather and fight when hostiles come near, rescue the downed after.

The tactic is deliberately plain: draft everyone who can fight, stand them together at the base
(the stockpile) so they shoot together, and undraft once no live hostile is near. Better tactics,
such as cover, chokepoints or retreats, are for later managers to add.
"""

from __future__ import annotations

import uuid
from typing import Any

from rimsdk import errors

from ..events import Event
from ..manager import Context, Manager
from .beds import base_anchor

ENGAGE_RADIUS = 45        # cells from the base within which hostiles are fought
COMBAT_CHUNK_HOURS = 0.1  # time runs while fighting: 250 ticks, about 4 seconds at Normal speed
MAX_COMBAT_HOURS = 8      # drafted this long means the fight isn't going the way this code expects
SPREAD = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)]


class DefenseManager(Manager):
    name = "defense"
    every_hours = 0  # every cycle: it must notice a fight, and its end, at once
    handles = ("hostiles", "threatLetter", "downed")

    def __init__(self) -> None:
        super().__init__()
        self.combat_since: int | None = None  # a timer, not memory: losing it on reload is harmless
        self.armed_at: int | None = None

    def update(self, ctx: Context) -> None:
        threats = engaging_threats(ctx)
        if threats:
            self.fight(ctx, threats)
        else:
            self.stand_down(ctx)
            if self.armed_at is None or ctx.tick - self.armed_at >= 12 * 2500:
                self.arm(ctx)
                self.armed_at = ctx.tick

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
            ctx.log(self.name, f"{len(threats)} hostiles within {ENGAGE_RADIUS} cells: drafting.",
                    threats=[describe(t) for t in threats][:10])
        elif ctx.tick - self.combat_since >= MAX_COMBAT_HOURS * 2500:
            ctx.raise_incident("longFight", f"Drafted for {MAX_COMBAT_HOURS}h against {len(threats)} hostiles.",
                               threats=[describe(t) for t in threats][:10])
        ctx.request_chunk(COMBAT_CHUNK_HOURS)

        fighters = [p for p in ctx.snapshot.colonists if not p.get("downed")]
        for i, pawn in enumerate(fighters):
            pid = pawn_id(pawn)
            if not pawn.get("drafted"):
                try:
                    ctx.rim.set_pawn_drafted(pid, drafted=True)
                except errors.RimError as exc:  # e.g. incapable of violence
                    ctx.log(self.name, f"Couldn't draft {pawn['name']}: {exc.message}")
                    continue
            dx, dz = SPREAD[i % len(SPREAD)]
            spot = (anchor[0] + dx, anchor[1] + dz)
            pos = pawn.get("position") or {}
            # Only move pawns that are out of place: a move order interrupts their shooting.
            if abs(pos.get("x", spot[0]) - spot[0]) > 2 or abs(pos.get("z", spot[1]) - spot[1]) > 2:
                ctx.rim.order_pawn(pid, order="move", x=spot[0], z=spot[1])

    def stand_down(self, ctx: Context) -> None:
        drafted = [p for p in ctx.snapshot.colonists if p.get("drafted")]
        if self.combat_since is None and not drafted:
            return
        for pawn in drafted:
            ctx.rim.set_pawn_drafted(pawn_id(pawn), drafted=False)
        if self.combat_since is not None:
            ctx.log(self.name, f"No hostiles near after {(ctx.tick - self.combat_since) / 2500:.1f}h: undrafted {len(drafted)}.")
        self.combat_since = None
        self.rescue(ctx)

    def rescue(self, ctx: Context) -> None:
        colonists = ctx.snapshot.colonists
        downed = [p for p in colonists if p.get("downed")]
        helpers = [p for p in colonists if not p.get("downed") and not p.get("drafted")]
        for patient, helper in zip(downed, helpers):
            result = ctx.rim.order_pawn(pawn_id(helper), order="rescue", target_id=pawn_id(patient), request_id=uuid.uuid4().hex)
            ctx.log(self.name, f"{helper['name']} rescues {patient['name']}.", result=(result.data or {}).get("outcome"))
        if len(downed) > len(helpers):
            ctx.raise_incident("noRescuer", f"{len(downed)} colonists downed and only {len(helpers)} can carry them.")

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


def pawn_id(pawn: dict[str, Any]) -> str:
    return (pawn.get("ids") or {}).get("id") or pawn["name"]


def describe(threat: dict[str, Any]) -> str:
    pos = threat.get("position") or {}
    return f"{threat.get('name') or threat.get('label')} ({threat.get('threatKind')}) at ({pos.get('x')}, {pos.get('z')})"
