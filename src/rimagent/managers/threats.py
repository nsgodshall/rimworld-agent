"""Threat letters: tell apart warnings that need nothing done from threats that need a response."""

from __future__ import annotations

from ..events import Event
from ..manager import Context, Manager

# Letters that warn about a danger which only wakes if the colony goes looking for it. Nothing here
# opens caskets or breaks ancient walls, so leaving the place alone is the whole response.
PASSIVE_WARNINGS = {
    "Ancient danger": "Ancient shrine nearby; leaving it sealed (no mining, deconstructing or opening caskets there).",
    # Answered by the house manager, from room temperatures rather than the letter (house.HOT).
    "Heat wave": "The house manager puts a passive cooler in every room while any is over 28 C.",
}


class ThreatsManager(Manager):
    name = "threats"
    every_hours = 24
    # History letters arrive as "letter" when no run was going, so take both and pick by label.
    handles = ("threatLetter", "letter")

    def on_event(self, ctx: Context, event: Event) -> bool:
        label = str(event.detail or "").strip()
        note = PASSIVE_WARNINGS.get(label)
        if note is None:
            # A raid, infestation, manhunters and so on: nothing here can answer those yet.
            return False
        target = _target(event)
        ctx.log(self.name, f"{label}: {note}", where=target, hostiles=ctx.snapshot.hostiles)
        return True


def _target(event: Event) -> str | None:
    for t in event.raw.get("targets") or ():
        pos = t.get("position") or {}
        if "x" in pos:
            return f"({pos['x']}, {pos['z']})"
    return None
