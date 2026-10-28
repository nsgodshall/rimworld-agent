"""Game events, from time runs (what stopped or happened during advance) and the History feed."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Kinds an advance run reports: its stopOn conditions.
RUN_KINDS = ("death", "downed", "injured", "mentalBreak", "hostiles", "lowFood", "threatLetter", "letter")


@dataclass(frozen=True)
class Event:
    kind: str
    tick: int | None
    source: str  # "run" (advance_time) or "history" (get_events)
    detail: Any = None
    pawn: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_run(cls, raw: dict[str, Any]) -> Event:
        return cls(raw["kind"], raw.get("tick"), "run", raw.get("detail"), raw.get("pawn"), raw)

    @classmethod
    def from_history(cls, raw: dict[str, Any]) -> Event:
        # History entries are letters, messages and dialogs; their label is the text the player saw.
        return cls(raw.get("kind", "history"), raw.get("tick"), "history", raw.get("label"), None, raw)

    def describe(self) -> str:
        who = f" ({self.pawn.get('name')})" if self.pawn else ""
        return f"{self.kind}{who} at tick {self.tick}: {self.detail}"


Handler = Callable[[Event], bool | None]


class EventBus:
    """Handlers subscribe to a kind, or "*" for all. A handler returning False means it didn't handle it."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, kind: str, handler: Handler) -> None:
        self._handlers[kind].append(handler)

    def clear(self) -> None:
        self._handlers.clear()

    def publish(self, event: Event) -> bool:
        """Deliver to every matching handler; True when at least one handled it."""
        handled = False
        for handler in [*self._handlers.get(event.kind, ()), *self._handlers.get("*", ())]:
            if handler(event) is not False:
                handled = True
        return handled
