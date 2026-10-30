"""The clock loop: read, react, run time, repeat, and stop for help when the code is out of its depth."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rimsdk import RimClient, errors

from .events import Event, EventBus
from .incidents import Escalator, HaltEscalator, Incident, IncidentLog, Severity
from .journal import Journal
from .loader import ManagerLoader
from .manager import TICKS_PER_HOUR, Context, Manager
from .snapshot import Snapshot
from .telemetry import CommandLog, publish

# Severity of an event no manager handles. Anything not listed is only journaled.
UNHANDLED: dict[str, Severity] = {
    "death": "halt",
    "downed": "halt",
    "mentalBreak": "halt",
    "hostiles": "halt",
    "threatLetter": "halt",
    "injured": "warn",
    "lowFood": "warn",
    "letter": "warn",
}

# How long an unclaimed Critical/High alert may show before it counts as a gap in the code.
ALERT_HOLD_HOURS = 12
# Alerts the game rates below High that still mean the colony's code is missing something,
# with how many game hours each may show (unclaimed, continuously) before it halts.
GAP_ALERTS = {
    "Alert_NeedMealSource": 6,       # nowhere to cook: living on rations
    "Alert_ColonistsIdle": 6,        # nothing for colonists to do
    "Alert_NeedResearchProject": 6,  # a research bench stands unused
}
# The same problem (Incident.key) gets this many fixes before the runtime gives up on it.
MAX_REPEATS = 2
# Incidents new code can't fix (a window forcing a pause, the colony gone): these stop for a person.
NOT_CODE_PROBLEMS = {"blocked", "gameUnloaded", "colonyLost"}
# A window holding the game paused is closed by saving and loading again, this many times a run.
UNSTICK_SAVE = "rimagent-unstick"
MAX_UNSTICKS = 3
UNSTICK_SETTLE_SECONDS = 15


@dataclass
class Tripwire:
    """A state check that raises an incident once its condition has held for `hold_hours` of game time."""

    name: str
    check: Callable[[Snapshot], str | None]  # a summary while tripped, else None
    severity: Severity = "halt"
    hold_hours: float = 0.0
    since: int | None = None

    def evaluate(self, snap: Snapshot) -> Incident | None:
        summary = self.check(snap)
        if summary is None:
            self.since = None
            return None
        if self.since is None:
            self.since = snap.tick
        if snap.tick - self.since < self.hold_hours * TICKS_PER_HOUR:
            return None
        self.since = snap.tick  # report again only after another hold period
        return Incident(self.name, summary, self.severity, snap.tick)


def default_tripwires() -> list[Tripwire]:
    return [
        # Held a while: at a game's start the colonists are still in their drop pods.
        Tripwire("colonyLost", lambda s: None if s.colonists else "No living colonists on the map.", hold_hours=2),
        Tripwire(
            "foodCritical",
            lambda s: f"{s.food_days:.1f} days of stored food." if s.food_days is not None and s.food_days < 1 else None,
            # The game counts only stored food; give managers time to fix storage before calling it critical.
            hold_hours=12,
        ),
    ]


class Runtime:
    def __init__(
        self,
        rim: RimClient,
        run_dir: Path,
        *,
        loader: ManagerLoader | None = None,
        managers: list[Manager] | None = None,
        escalator: Escalator | None = None,
        tripwires: list[Tripwire] | None = None,
        chunk_hours: float = 2.0,
        speed: str | None = None,
        watch_alerts: bool = True,
        max_escalations: int = 5,
        observers: list[Callable[[Snapshot], None]] | None = None,
        echo: bool = True,
    ):
        self.rim = rim
        self.run_dir = run_dir
        self.journal = Journal(run_dir / "journal.jsonl", echo=echo)
        self.incident_log = IncidentLog(run_dir / "incidents")
        # A fixed manager list (tests) never reloads; otherwise managers come from, and follow, their files.
        if managers is not None:
            self.loader, self.managers = None, managers
        else:
            self.loader = loader or ManagerLoader()
            self.managers = self.loader.load()
        self.escalator = escalator or HaltEscalator()
        self.tripwires = tripwires if tripwires is not None else default_tripwires()
        self.chunk_hours = chunk_hours
        self.speed = speed
        self.pending: list[Event] = []
        self.history_cursor: str | None = None
        self.stalled_runs = 0
        self.bus = EventBus()
        self.watch_alerts = watch_alerts
        self.alert_since: dict[str, int] = {}
        self.alerts_reported: set[str] = set()
        self.max_escalations = max_escalations
        # Called with each cycle's snapshot after the managers ran (e.g. evaluation metrics).
        self.observers = observers or []
        self.requested_chunk: float | None = None
        self.escalations = 0
        self.escalated_keys: list[str] = []
        self.unsticks = 0
        # For watching (telemetry): who is calling the game now, and where the run is.
        self.actor = "runtime"
        self.tick: int | None = None
        self.cycles = 0
        self.start_tick: int | None = None
        self.target_tick: int | None = None
        self.last_run: dict[str, Any] | None = None
        self.last_snap: Snapshot | None = None
        self.pawn_details: dict[str, dict[str, Any]] = {}
        self.seen: dict[str, Any] = {}  # the latest colony, colonists and alerts any cycle read
        self.board: dict[str, Any] = {}  # Context.board: managers' notes to each other
        self.command_log = CommandLog(self)
        rim.call_hooks.append(self.command_log)

    # --- the loop --------------------------------------------------------------------------

    def run(self, hours: float, max_cycles: int | None = None) -> str:
        """Play for `hours` of game time. Returns why it stopped: done, halted, or an error kind."""
        start = self.rim.get_advance().data["time"]["tick"]
        target = start + hours * TICKS_PER_HOUR
        self.start_tick, self.target_tick, self.tick = start, round(target), start
        self.journal.write("start", tick=start, hours=hours, managers=[m.name for m in self.managers])
        self._skip_old_history()
        cycles = 0
        while True:
            cycles += 1
            self.cycles += 1
            snap = Snapshot(self.rim)
            self.tick, self.last_snap = snap.tick, snap
            if not self.cycle(snap):
                return self._stop("halted", snap.tick)
            publish(self, "cycle", snap)
            if snap.tick >= target or (max_cycles is not None and cycles >= max_cycles):
                return self._stop("done", snap.tick)
            if self.pending:
                continue  # an event re-delivered after a fix (say, a raid) is handled before time runs
            hours_left = (target - snap.tick) / TICKS_PER_HOUR
            chunk = min(self.chunk_hours, hours_left, self.requested_chunk or self.chunk_hours)
            if not self.advance(chunk):
                return self._stop("halted", snap.tick)

    def cycle(self, snap: Snapshot) -> bool:
        """React to pending events, run due managers, check tripwires. False means stop."""
        ctx = Context(self.rim, snap, self.journal, board=self.board)
        self._reload_if_changed(snap.tick)
        events, self.pending = self.pending + self._history_events(), []
        for event in events:
            self.dispatch(ctx, event)
        for manager in self.managers:
            if manager.due(snap.tick):
                self.actor = manager.name
                try:
                    manager.update(ctx)
                except errors.NotProcessing:
                    raise
                except Exception as exc:  # a manager bug is an incident, not a crash
                    ctx.incidents.append(Incident.from_exception(f"{manager.name}.update", exc, snap.tick))
                manager.last_tick = snap.tick
        self.actor = "runtime"
        for wire in self.tripwires:
            incident = wire.evaluate(snap)
            if incident:
                ctx.incidents.append(incident)
        if self.watch_alerts:
            self.check_alerts(ctx)
        for observe in self.observers:
            observe(snap)
        self.requested_chunk = ctx.chunk_hours
        return self.handle_incidents(ctx)

    def dispatch(self, ctx: Context, event: Event) -> None:
        self.journal.write("event", tick=event.tick, summary=event.describe(), source=event.source)
        handled = False
        for manager in self.managers:
            if event.kind in manager.handles:
                self.actor = f"{manager.name}:{event.kind}"
                try:
                    handled = manager.on_event(ctx, event) is not False or handled
                except Exception as exc:
                    ctx.incidents.append(Incident.from_exception(f"{manager.name}.on_event({event.kind})", exc, ctx.tick))
                    handled = True
        self.actor = "runtime"
        handled = self.bus.publish(event) or handled
        severity = UNHANDLED.get(event.kind)
        if not handled and severity:
            ctx.incidents.append(Incident(
                "unhandledEvent", f"No manager handles {event.describe()}", severity, event.tick,
                {"event": event.raw, "handlers": {m.name: list(m.handles) for m in self.managers}},
                event=event,
            ))

    def check_alerts(self, ctx: Context) -> None:
        """A Critical/High game alert, or one of GAP_ALERTS, that no manager claims and that keeps
        showing past its hold time is a gap in the code: halt so it gets a manager. Other unclaimed
        alerts are noted once."""
        snap = ctx.snapshot
        claimed = {a for m in self.managers for a in m.alerts}
        active = {a["type"]: a for a in snap.alerts if a.get("type")}
        for gone in set(self.alert_since) - set(active):
            del self.alert_since[gone]
        for kind, alert in active.items():
            if kind in claimed or kind in self.alerts_reported:
                continue
            since = self.alert_since.setdefault(kind, snap.tick)
            hold = GAP_ALERTS.get(kind, ALERT_HOLD_HOURS if alert.get("priority") in ("Critical", "High") else None)
            if hold is not None:
                if snap.tick - since >= hold * TICKS_PER_HOUR:
                    self.alerts_reported.add(kind)
                    ctx.incidents.append(Incident(
                        "unhandledAlert", f"'{alert.get('label')}' ({kind}) has shown for "
                        f"{(snap.tick - since) / TICKS_PER_HOUR:.0f}h and no manager claims it.",
                        "halt", snap.tick, {"alert": alert, "claimed": sorted(claimed)},
                    ))
            else:
                self.alerts_reported.add(kind)
                ctx.incidents.append(Incident("unhandledAlert", f"'{alert.get('label')}' ({kind}) is unclaimed.",
                                              "warn", snap.tick, {"alert": alert}))

    def advance(self, hours: float) -> bool:
        """Run game time; queue what happened as events. False when the game can't be run."""
        before = self.rim.get_advance().data["time"]["tick"]
        publish(self, "advancing", self.last_snap)
        try:
            run = self.rim.advance(max(hours, 0.01), speed=self.speed)
        except errors.Conflict as exc:
            # The game refused to change speed: a window forcing a pause, such as a scenario's intro.
            run = {"status": "interrupted", "endReason": f"refused: {exc.message}", "tick": before}
        self.journal.write(
            "run", tick=run.get("tick"), status=run.get("status"), endReason=run.get("endReason"),
            hours=run.get("hoursElapsed"), events=len(run.get("events") or []),
        )
        self.pending.extend(Event.from_run(e) for e in run.get("events") or [])
        self.tick = run.get("tick") or self.tick
        self.last_run = {"hours": round(hours, 2), **{k: run.get(k) for k in ("status", "endReason", "hoursElapsed", "tick")},
                         "events": [Event.from_run(e).describe() for e in run.get("events") or []][:5]}
        if run.get("status") != "interrupted":
            self.stalled_runs = 0
            return True

        reason = run.get("endReason")
        if reason == "gameUnloaded":
            return self._halt(Incident("gameUnloaded", "The colony was unloaded mid-run.", tick=run.get("tick")))
        # The player paused or changed speed, or a window forces a pause (letters, the scenario intro...).
        self.stalled_runs = self.stalled_runs + 1 if run.get("tick", before) <= before else 0
        if self.stalled_runs >= 3 and reason == "forcedPause" and self.unsticks < MAX_UNSTICKS and self._unstick():
            self.stalled_runs = 0
            return True
        if self.stalled_runs >= 3:
            return self._halt(Incident(
                "blocked", f"Time won't run: {self.stalled_runs} runs in a row ended '{reason}' without progress. "
                "Probably a window in game forces a pause, such as the one asking to name the settlement "
                "(it appears after a few days; RimMCP can't answer it).", tick=run.get("tick"), details={"run": run},
            ))
        time.sleep(2)
        return True

    def _unstick(self) -> bool:
        """Save the colony and load it again: loading closes every window. A window holding the game paused
        (trial 9: one RimMCP doesn't list, at day 10) ended runs that were going well. True if it reloaded."""
        self.unsticks += 1
        tick = self.tick
        try:
            op = self.rim.wait_operation(self.rim.save_game(name=UNSTICK_SAVE, overwrite=True, wait_seconds=30), timeout=300)
            if op.get("state") != "succeeded":
                raise errors.RimError(f"save {op.get('state')}: {op.get('message')}")
            op = self.rim.wait_operation(self.rim.load_game(name=UNSTICK_SAVE, discard_unsaved=True, wait_seconds=30),
                                         timeout=600)
            if op.get("state") != "succeeded":
                raise errors.RimError(f"load {op.get('state')}: {op.get('message')}")
            self.rim.wait_until_ready()
            # The reloaded game's history starts over: skip it, or old letters (a raid's) come back as new events.
            self._skip_old_history()
        except (errors.RimError, TimeoutError) as exc:
            self.journal.write("warning", tick=tick, summary=f"Couldn't save and reload past a forced pause: {exc}")
            return False
        self.journal.write("unstuck", tick=tick, summary=f"Time was held paused: saved as {UNSTICK_SAVE} and loaded it "
                           f"again, which closes game windows ({self.unsticks}/{MAX_UNSTICKS}).")
        time.sleep(UNSTICK_SETTLE_SECONDS)  # the game refuses time control for a moment after loading
        return True

    # --- incidents ---------------------------------------------------------------------------

    def handle_incidents(self, ctx: Context) -> bool:
        for incident in ctx.incidents:
            if incident.severity == "warn":
                self.journal.write("warning", tick=incident.tick, summary=f"{incident.kind}: {incident.summary}")
            elif not self._halt(incident, ctx.snapshot):
                return False
        return True

    def _halt(self, incident: Incident, snap: Snapshot | None = None) -> bool:
        """Pause, write the report, and let the escalator decide whether play goes on."""
        try:
            if not self.rim.get_advance().data["time"]["paused"]:
                self.rim.set_game_speed(speed="Paused")
        except errors.RimError:
            pass
        report = self.incident_log.write(incident, self._context(snap))
        self.journal.write("incident", tick=incident.tick, summary=f"{incident.kind}: {incident.summary}", report=str(report))

        if incident.kind in NOT_CODE_PROBLEMS:
            return False
        if self.escalations >= self.max_escalations:
            self.journal.write("escalation", tick=incident.tick, resume=False, summary=f"Escalation budget ({self.max_escalations}) used up.")
            return False
        if self.escalated_keys.count(incident.key) >= MAX_REPEATS:
            self.journal.write("escalation", tick=incident.tick, resume=False,
                               summary=f"{incident.key} came back after {MAX_REPEATS} fixes; a person should look.")
            return False
        self.escalations += 1
        self.escalated_keys.append(incident.key)
        self.journal.write("escalation", tick=incident.tick, summary=f"Escalating {incident.key} ({self.escalations}/{self.max_escalations})...")
        publish(self, "escalating", snap)
        self.actor = "escalation"
        try:
            resolution = self.escalator.escalate(incident, report)
        finally:
            self.actor = "runtime"
        self.journal.write("escalation", tick=incident.tick, resume=resolution.resume, summary=resolution.summary, **resolution.details)
        if resolution.resume:
            self._reload_if_changed(incident.tick or 0)
            if incident.event is not None:
                self.pending.append(incident.event)
        return resolution.resume

    def _context(self, snap: Snapshot | None) -> dict[str, Any]:
        context: dict[str, Any] = {"managers": [m.name for m in self.managers], "journal": str(self.journal.path)}
        if snap is not None:
            try:
                context["colony"] = snap.colony
            except errors.RimError as exc:
                context["colonyError"] = str(exc)
        return context

    def _stop(self, why: str, tick: int) -> str:
        self.journal.write("stop", tick=tick, reason=why)
        publish(self, why, self.last_snap)
        return why

    # --- plumbing ----------------------------------------------------------------------------

    def _reload_if_changed(self, tick: int) -> None:
        if self.loader is None or not self.loader.changed():
            return
        try:
            managers = self.loader.load(self.managers)
        except Exception as exc:  # a broken manager file keeps the old managers running, and is reported once
            if not getattr(self, "_reload_failed", False):
                self.journal.write("warning", tick=tick, summary=f"Reloading managers failed, keeping the old ones: "
                                   f"{type(exc).__name__}: {exc}")
            self._reload_failed = True
            return
        self._reload_failed = False
        self.managers = managers
        self.journal.write("reload", tick=tick, managers=[m.name for m in self.managers])

    def _skip_old_history(self) -> None:
        self.history_cursor = self.rim.get_events().data["history"].get("cursor")

    def _history_events(self) -> list[Event]:
        """History entries since the last cycle. Letters also arrive as run events, so only messages
        and dialogs come from here, plus letters that landed while no run was going."""
        if self.history_cursor is None:
            return []
        run_letters = {(e.tick, e.detail) for e in self.pending if e.kind in ("letter", "threatLetter")}
        events: list[Event] = []
        while True:
            history = self.rim.get_events(since=self.history_cursor).data["history"]
            if history.get("reset"):
                self.journal.write("warning", summary="History cursor came from another load; skipping old entries.")
            for raw in history.get("entries") or []:
                event = Event.from_history(raw)
                if event.kind == "letter" and (event.tick, event.detail) in run_letters:
                    continue
                events.append(event)
            self.history_cursor = history.get("cursor") or self.history_cursor
            if not history.get("more"):
                return events
