"""What the runtime knows and does, for watching it: `rimagent watch` reads both.

- Every call that changes the game goes in the journal as a "command" entry: who issued it (a
  manager, or the runtime itself), the tool, its arguments, and what the game said.
- After each cycle, and whenever the runtime's status changes, `state.json` in the run directory is
  rewritten with the runtime's picture of the game: the colony as this cycle read it, the managers'
  schedules and memory, alert claims and hold timers, tripwires, pending events.

The picture is the runtime's own: what it read this cycle, not a fresh look at the game.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any

from rimsdk import CallRecord, errors

from .manager import TICKS_PER_HOUR

if TYPE_CHECKING:
    from .runtime import Runtime
    from .snapshot import Snapshot

# Fields of a command's reply worth showing in a one-line log.
OUTCOME_KEYS = ("outcome", "applied", "alreadySatisfied", "rejectedCount", "status", "endReason", "reason",
                "previousPriority", "priority", "drafted", "speed", "alreadySatisfied")
# Routine clock commands, one per time run (ten an hour in a fight): marked so a viewer can hide them.
QUIET_COMMANDS = {"advance_time"}


def compact(value: Any, items: int = 3, text: int = 80) -> Any:
    """Arguments short enough for a log line: long lists cut to their first few items."""
    if isinstance(value, list):
        head = [compact(v, items, text) for v in value[:items]]
        return head + [f"…+{len(value) - items}"] if len(value) > items else head
    if isinstance(value, dict):
        return {k: compact(v, items, text) for k, v in value.items()}
    if isinstance(value, str) and len(value) > text:
        return value[:text] + "…"
    return value


def outcome(record: CallRecord) -> dict[str, Any]:
    if record.error:
        return {"error": record.error}
    result = record.result or {}
    data = result.get("data") if isinstance(result, dict) else None
    summary: dict[str, Any] = {"changed": result.get("changed")} if isinstance(result, dict) else {}
    if isinstance(data, dict):
        summary.update({k: data[k] for k in OUTCOME_KEYS if data.get(k) not in (None, [], {})})
        rejected = [r.get("reason") for r in data.get("results") or [] if isinstance(r, dict) and r.get("outcome") == "rejected"]
        if rejected:
            summary["rejected"] = sorted(set(filter(None, rejected)))[:3]
    return summary


class CommandLog:
    """RimClient call hook: journals game-changing calls, counts the rest."""

    def __init__(self, runtime: Runtime):
        self.runtime = runtime
        self.reads = 0
        self.commands = 0

    def __call__(self, record: CallRecord) -> None:
        if record.read_only:
            self.reads += 1
            return
        self.commands += 1
        rt = self.runtime
        rt.journal.write("command", tick=rt.tick, actor=rt.actor, tool=record.tool, args=compact(record.args),
                         result=outcome(record), ms=record.ms, quiet=record.tool in QUIET_COMMANDS or None)


def _cached(snap: Snapshot | None, name: str, seen: dict[str, Any] | None = None) -> Any:
    """A read this cycle's snapshot already made, else the last one seen; never a new call."""
    value = snap.__dict__.get(name) if snap is not None else None
    if seen is None:
        return value
    if value is not None:
        seen[name] = value
    return seen.get(name)


def colonist_view(pawn: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any]:
    detail = detail or {}
    mood = detail.get("mood") or {}
    health = detail.get("health") or {}
    job = pawn.get("currentJob") or {}
    return {
        "id": (pawn.get("ids") or {}).get("id"),
        "name": pawn.get("label") or pawn.get("name"),
        "position": [pawn["position"]["x"], pawn["position"]["z"]] if pawn.get("position") else None,
        "job": job.get("report") or job.get("label"),
        "drafted": pawn.get("drafted"),
        "downed": pawn.get("downed"),
        "mood": mood.get("level"),
        "thoughts": sorted(({"label": t.get("label"), "offset": t.get("moodOffset")} for t in mood.get("thoughts") or []
                            if t.get("moodOffset")), key=lambda t: t["offset"]),
        "needs": {n.get("label"): round(n.get("level", 0), 2) for n in detail.get("needs") or [] if n.get("label")},
        "health": health.get("summaryHealthPercent"),
        "pain": health.get("pain"),
        "hediffs": [h.get("label") for h in health.get("hediffs") or []][:6],
    }


def pawn_details(snap: Snapshot, seen: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each colonist's mood, needs and health: one get_pawn each, read for watching only."""
    details = {}
    for pawn in _cached(snap, "colonists", seen) or []:
        pawn_id = (pawn.get("ids") or {}).get("id")
        try:
            details[pawn_id] = snap.rim.get_pawn(pawn_id, detail="normal").data
        except errors.RimError:
            pass
    return details


def build_state(rt: Runtime, status: str, snap: Snapshot | None) -> dict[str, Any]:
    colony = _cached(snap, "colony", rt.seen) or {}
    colonists = _cached(snap, "colonists", rt.seen) or []
    alerts = _cached(snap, "alerts", rt.seen) or []
    details = rt.pawn_details
    claims: dict[str, list[str]] = {}
    for m in rt.managers:
        for a in m.alerts:
            claims.setdefault(a, []).append(m.name)
    tick = rt.tick
    return {
        "updated": time.time(),
        "run": rt.run_dir.name,
        "pid": os.getpid(),
        "status": status,
        "cycle": rt.cycles,
        "tick": tick,
        "startTick": rt.start_tick,
        "targetTick": rt.target_tick,
        "chunkHours": rt.chunk_hours,
        "requestedChunk": rt.requested_chunk,
        "speed": rt.speed,
        "lastRun": rt.last_run,
        "stalledRuns": rt.stalled_runs,
        "escalations": rt.escalations,
        "maxEscalations": rt.max_escalations,
        "escalatedKeys": rt.escalated_keys,
        "pending": [e.describe() for e in rt.pending],
        "calls": {"reads": rt.command_log.reads, "commands": rt.command_log.commands},
        "game": {"time": colony.get("time"), "map": (colony.get("map") or {}).get("label")},
        "colony": {k: colony.get(k) for k in ("food", "mood", "medical", "threats", "power", "resources") if k in colony},
        "colonists": [colonist_view(p, details.get((p.get("ids") or {}).get("id"))) for p in colonists],
        "alerts": [{
            "type": a.get("type"), "label": a.get("label"), "priority": a.get("priority"),
            "claimedBy": claims.get(a.get("type"), []),
            "unclaimedSince": rt.alert_since.get(a.get("type")),
            "reported": a.get("type") in rt.alerts_reported,
            "culprits": a.get("culpritCount"),
        } for a in alerts],
        "managers": [{
            "name": m.name, "priority": m.priority, "everyHours": m.every_hours, "lastTick": m.last_tick,
            "nextTick": None if m.last_tick is None else m.last_tick + round(m.every_hours * TICKS_PER_HOUR),
            "handles": list(m.handles), "alerts": list(m.alerts),
            "memory": json.dumps(m.memory, default=str)[:400] if m.memory else None,
        } for m in rt.managers],
        "tripwires": [{"name": w.name, "since": w.since, "holdHours": w.hold_hours} for w in rt.tripwires],
    }


def publish(rt: Runtime, status: str, snap: Snapshot | None = None) -> None:
    """Rewrite state.json atomically; never let watching break playing."""
    try:
        if status == "cycle" and snap is not None:
            rt.pawn_details = pawn_details(snap, rt.seen)
        state = build_state(rt, status, snap)
        path = rt.run_dir / "state.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError, errors.RimError) as exc:
        rt.journal.write("warning", summary=f"Couldn't publish state.json: {exc}")
