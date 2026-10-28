"""Managers: the colony's standing policies, each run on its own schedule and on the events it handles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from rimsdk import RimClient

from .events import Event
from .incidents import Incident
from .snapshot import Snapshot

if TYPE_CHECKING:
    from .journal import Journal

TICKS_PER_HOUR = 2500


@dataclass
class Context:
    """What a manager gets each cycle."""

    rim: RimClient
    snapshot: Snapshot
    journal: Journal
    incidents: list[Incident] = field(default_factory=list)

    @property
    def tick(self) -> int:
        return self.snapshot.tick

    def log(self, manager: str, message: str, **data: Any) -> None:
        self.journal.write("manager", manager=manager, message=message, tick=self.tick, **data)

    def raise_incident(self, kind: str, summary: str, severity: str = "halt", **details: Any) -> None:
        self.incidents.append(Incident(kind, summary, severity, self.tick, details))  # type: ignore[arg-type]


class Manager:
    """Subclass, set `name`, `every_hours` and maybe `handles`, and implement update() and/or on_event().

    Managers should read the game rather than remember: each update works out what's missing from
    the current state and does that, so running one twice, or after a reload, does no harm.
    """

    name: ClassVar[str] = "manager"
    every_hours: ClassVar[float] = 6.0
    # Event kinds this manager's on_event() deals with (see rimagent.events.RUN_KINDS).
    handles: ClassVar[tuple[str, ...]] = ()
    # Game alert types (get_events alerts[].type, e.g. "Alert_NeedColonistBeds") this manager owns.
    alerts: ClassVar[tuple[str, ...]] = ()

    def __init__(self) -> None:
        self.last_tick: int | None = None

    def due(self, tick: int) -> bool:
        return self.last_tick is None or tick - self.last_tick >= self.every_hours * TICKS_PER_HOUR

    def update(self, ctx: Context) -> None:
        pass

    def on_event(self, ctx: Context, event: Event) -> bool | None:
        """Return False to say the event wasn't handled after all."""
        return None
