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
    # The shortest time run any manager asked for this cycle (None: the runtime's usual chunk).
    chunk_hours: float | None = None
    # Notes managers leave each other, kept by the runtime across cycles and reloads (not restarts), e.g.
    # the house manager's "house_beds": beds it has planned, so the beds manager needn't place any.
    board: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # The planned base's cells, kept on the board, so every view this cycle keeps out of them (planner.py).
        self.snapshot.reserved = self.board.setdefault("reserved", set())

    def request_chunk(self, hours: float) -> None:
        """Ask for the next time run to be at most `hours` long, e.g. 0.1 while a fight is on."""
        self.chunk_hours = hours if self.chunk_hours is None else min(self.chunk_hours, hours)

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
    # Lower runs first each cycle: e.g. food (which makes the stockpile) before beds (placed beside it).
    priority: ClassVar[int] = 50
    # Event kinds this manager's on_event() deals with (see rimagent.events.RUN_KINDS).
    handles: ClassVar[tuple[str, ...]] = ()
    # Game alert types (get_events alerts[].type, e.g. "Alert_NeedColonistBeds") this manager owns.
    alerts: ClassVar[tuple[str, ...]] = ()

    def __init__(self) -> None:
        self.last_tick: int | None = None
        # For what the game can't tell you, such as which blueprints this manager placed (the map
        # shows only "blueprint", not what of or whose). Survives hot reloads, not a restart, so
        # check it against the game and cope with finding it empty.
        self.memory: dict[str, Any] = {}

    def due(self, tick: int) -> bool:
        return self.last_tick is None or tick - self.last_tick >= self.every_hours * TICKS_PER_HOUR

    def update(self, ctx: Context) -> None:
        pass

    def on_event(self, ctx: Context, event: Event) -> bool | None:
        """Return False to say the event wasn't handled after all."""
        return None
