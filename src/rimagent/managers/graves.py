"""Graves: a colonist who dies is buried, out of sight of the base.

In run 20261030-002116 Sparky bled to death while being tended, and the runtime stopped: no code handled a
death. Nothing can undo one, but the body shouldn't lie about the base ("Observed corpse", -4, then rotting,
-6) or in the corpse dump. A grave takes it: the game's graves accept colonist corpses and outrank stockpiles,
so haulers carry the body there once the grave is dug (no materials, 800 work).

Raiders' corpses aren't buried: the kitchen's corpse dump takes them. So only the colonists whose deaths this
manager heard of get a grave, matched to their corpse by the name it's labelled with ("Sparky, Builder (dead)").
"""

from __future__ import annotations

import re
import uuid

from rimsdk.mapview import Rect

from ..events import Event
from ..manager import Context, Manager
from .beds import away_from_base, base_anchor
from .kitchen import DUMP_DISTANCE

CORPSE = "Corpse_Human"
GRAVE = "Grave"
# The window searched for a grave spot: just beyond the corpse dump (itself out of the store's back door).
WINDOW = (20, 10)


def short_name(name: str) -> str:
    """The name a corpse is labelled with: the nickname of "Parker 'Sparky' Strobeck", else the whole name."""
    nick = re.search(r"'([^']+)'", name)
    return nick.group(1) if nick else name


def is_corpse_of(label: str, name: str) -> bool:
    short = short_name(name)
    return label.startswith(f"{short},") or label.startswith(f"{short} (dead)")


class GravesManager(Manager):
    name = "graves"
    every_hours = 6
    priority = 60
    handles = ("death",)

    def on_event(self, ctx: Context, event: Event) -> bool | None:
        who = (event.pawn or {}).get("name") or "A colonist"
        left = len(ctx.snapshot.colonists)
        ctx.log(self.name, f"{who} died ({event.detail}); {left} colonists left.")
        if event.pawn and event.pawn.get("name"):
            dead = self.memory.setdefault("dead", {})
            dead.setdefault(event.pawn["name"], None)  # name -> grave spot [x, z] once placed
        self.bury(ctx)
        return True

    def update(self, ctx: Context) -> None:
        self.bury(ctx)

    def bury(self, ctx: Context) -> None:
        dead: dict[str, list[int] | None] = self.memory.get("dead") or {}
        if not dead:
            return
        corpses = (ctx.rim.find_things(def_=CORPSE, limit=200).data or {}).get("things") or []
        for name in list(dead):
            corpse = next((c for c in corpses if is_corpse_of(c.get("label") or "", name)), None)
            if corpse is None:
                # Buried (a corpse in a grave isn't on the map), or gone: nothing more to do.
                del dead[name]
                ctx.log(self.name, f"{name}'s corpse is no longer on the map; done with them.")
                continue
            if corpse.get("forbidden"):
                ctx.rim.designate(kind="unforbid", thing_ids=[corpse["id"]])
            spot = dead[name] or self.find_spot(ctx, taken=[s for s in dead.values() if s])
            if spot is None:
                ctx.raise_incident("noGraveSpot", f"No room for a grave for {name} south of the base.", "warn")
                continue
            result = ctx.rim.place_blueprint(placements=[{"def": GRAVE, "x": spot[0], "z": spot[1]}],
                                             request_id=uuid.uuid4().hex).data or {}
            (done,) = result.get("results") or [{}]
            if done.get("outcome") == "rejected":
                dead[name] = None  # try another spot next time
                ctx.log(self.name, f"A grave at {tuple(spot)} for {name} was refused: {done.get('reason')}")
                continue
            if dead[name] is None:
                ctx.log(self.name, f"Placed a grave for {name} at {tuple(spot)}.")
            dead[name] = list(spot)

    def find_spot(self, ctx: Context, taken: list[list[int]]) -> list[int] | None:
        anchor = base_anchor(ctx)
        if anchor is None:
            return None
        width, height = ctx.snapshot.map_size
        w, h = WINDOW
        # Its far side DUMP_DISTANCE + 7 + h cells away, as wide as it is across the way out.
        cx, cz = away_from_base(ctx, anchor, DUMP_DISTANCE + 7 + h // 2, margin=h // 2)
        across = (ctx.board.get("plan") or {}).get("away", (0, -1))[0] != 0
        window = (Rect(cx - h // 2, cz - w // 2, h, w) if across else Rect(cx - w // 2, cz - h // 2, w, h)).clamp(width, height)
        check = ctx.rim.check_placement(def_=GRAVE, **window.to_api()).data or {}
        for fit in check.get("fits") or []:
            spot = [fit["x"], fit["z"]]
            # Graves side by side, not on one another (2 cells tall, so a column apart is enough).
            if all(spot[0] != t[0] or abs(spot[1] - t[1]) > 2 for t in taken):
                return spot
        return None
