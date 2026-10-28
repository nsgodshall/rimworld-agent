"""Incidents: situations the code couldn't handle, written down for whoever fixes the code next."""

from __future__ import annotations

import json
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from .events import Event

Severity = Literal["halt", "warn"]


@dataclass
class Incident:
    kind: str  # e.g. "unhandledEvent", "unhandledAlert", "managerError", "foodCritical", "blocked"
    summary: str
    severity: Severity = "halt"
    tick: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    # The event that caused it, delivered again after the code is fixed so new handlers see it.
    event: Event | None = None

    @property
    def key(self) -> str:
        """What makes two incidents 'the same problem' for repeat limits."""
        what = self.event.kind if self.event else self.details.get("alert", {}).get("type") or self.details.get("where")
        return f"{self.kind}:{what}"

    @classmethod
    def from_exception(cls, where: str, exc: BaseException, tick: int | None = None) -> Incident:
        return cls(
            "managerError",
            f"{where} raised {type(exc).__name__}: {exc}",
            tick=tick,
            details={"where": where, "traceback": "".join(traceback.format_exception(exc))},
        )


class IncidentLog:
    def __init__(self, directory: Path):
        self.directory = directory
        self.count = 0

    def write(self, incident: Incident, context: dict[str, Any]) -> Path:
        """Write <n>-<kind>.json (machine-readable) and .md (for the LLM or a person) and return the .md."""
        self.directory.mkdir(parents=True, exist_ok=True)
        self.count += 1
        stem = self.directory / f"{self.count:03d}-{incident.kind}"
        record = {"incident": asdict(incident), "context": context}
        stem.with_suffix(".json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
        md = [f"# {incident.kind}: {incident.summary}", "", f"- severity: {incident.severity}", f"- tick: {incident.tick}", ""]
        for key, value in incident.details.items():
            text = value if isinstance(value, str) else json.dumps(value, indent=1, default=str)
            md += [f"## {key}", "", "```", text.rstrip(), "```", ""]
        md += ["## context", "", "```json", json.dumps(context, indent=1, default=str), "```", ""]
        stem.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
        return stem.with_suffix(".md")


@dataclass
class Resolution:
    resume: bool
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


class Escalator(Protocol):
    def escalate(self, incident: Incident, report: Path) -> Resolution:
        """Deal with a halting incident (the game is paused) and say whether the runtime may resume."""
        ...


class HaltEscalator:
    """Stop and leave the report for a person."""

    def escalate(self, incident: Incident, report: Path) -> Resolution:
        return Resolution(False, f"Stopped for a person to read {report}.")
