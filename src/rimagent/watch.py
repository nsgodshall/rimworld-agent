"""A terminal view of the runtime as it plays: what it believes about the game, and what it does.

    uv run python -m rimagent watch              # follows the newest run in runs/
    uv run python -m rimagent watch runs/<dir>   # one run

It never calls the game. It reads the run's state.json (the runtime's picture of the colony, rewritten
each cycle) and tails its journal.jsonl (commands sent, events, warnings, incidents), so it shows the
controller's understanding, which can lag or differ from the game itself.

Keys: q quit, c toggle routine clock commands, f toggle following newer runs, ↑/↓ pick a colonist.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, RichLog, Static

TICKS_PER_HOUR = 2500
TICKS_PER_DAY = 24 * TICKS_PER_HOUR
STATUS_STYLE = {"cycle": "bold green", "advancing": "bold cyan", "escalating": "bold magenta",
                "halted": "bold white on red", "done": "bold white on blue"}
JOURNAL_STYLE = {"event": "yellow", "warning": "dark_orange", "incident": "bold red", "escalation": "magenta",
                 "manager": "green", "reload": "blue", "start": "bold blue", "stop": "bold blue", "run": "grey50"}


def newest_run(runs: Path) -> Path | None:
    dirs = [d for d in runs.iterdir() if (d / "journal.jsonl").exists()] if runs.is_dir() else []
    return max(dirs, key=lambda d: (d / "journal.jsonl").stat().st_mtime, default=None)


def days(tick: int | None) -> str:
    return "-" if tick is None else f"d{tick / TICKS_PER_DAY:.2f}"


def hours_until(tick: int | None, now: int | None) -> str:
    if tick is None or now is None:
        return "now"
    left = (tick - now) / TICKS_PER_HOUR
    return "due" if left <= 0 else f"{left:.1f}h"


def cat(*parts: Text | str) -> Text:
    """Join styled pieces. (Text("a", style=s) + Text("b") would style "b" with s too.)"""
    return Text.assemble(*parts)


def bar(level: float | None, width: int = 8) -> Text:
    if level is None:
        return Text("-" * width, style="grey50")
    filled = max(0, min(width, round(level * width)))
    style = "red" if level < 0.35 else "yellow" if level < 0.55 else "green"
    return cat(Text("█" * filled, style=style), Text("░" * (width - filled), style="grey35"), f" {level:.2f}")


def short_json(value: Any, limit: int) -> str:
    text = json.dumps(value, separators=(",", ":"), default=str) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[: limit - 1] + "…"


def command_line(entry: dict[str, Any]) -> Text:
    result = entry.get("result") or {}
    if result.get("error"):
        style, verdict = "red", result["error"]
    elif result.get("rejected") or result.get("rejectedCount"):
        style, verdict = "yellow", short_json({k: v for k, v in result.items() if k != "changed"}, 60)
    elif result.get("changed"):
        style, verdict = "green", short_json({k: v for k, v in result.items() if k != "changed"}, 60) or "changed"
    else:
        style, verdict = "grey62", "no change " + short_json({k: v for k, v in result.items() if k != "changed"}, 50)
    args = {k: v for k, v in (entry.get("args") or {}).items() if k not in ("requestId",)}
    return cat(Text(f"{entry.get('tick') or '':>7} ", style="grey50"),
               Text(f"{str(entry.get('actor'))[:16]:<16} ", style="cyan"),
               Text(f"{entry.get('tool'):<22} ", style="bold"),
               short_json(args, 70) + " ", Text("→ " + verdict, style=style))


def journal_line(entry: dict[str, Any]) -> Text:
    kind = entry.get("kind", "?")
    tick = entry.get("tick")
    body = entry.get("message") or entry.get("summary")
    if kind == "run":
        body = f"{entry.get('status')}/{entry.get('endReason')} after {entry.get('hours')}h, {entry.get('events', 0)} events"
    elif body is None:
        body = short_json({k: v for k, v in entry.items() if k not in ("t", "kind", "tick", "manager")}, 160)
    who = f"{entry['manager']}: " if entry.get("manager") else ""
    return cat(Text(f"{tick if isinstance(tick, int) else '':>7} ", style="grey50"),
               Text(f"{kind:<10} ", style=JOURNAL_STYLE.get(kind, "white")), Text(who, style="green"),
               Text(str(body), style="grey50" if kind == "run" else ""))


class Watch(App):
    CSS = """
    Screen { layout: vertical; }
    #status { height: 2; padding: 0 1; background: $panel; }
    #top { height: 12; }
    #middle { height: 1fr; min-height: 10; }
    #bottom { height: 1fr; min-height: 8; }
    .box { border: round $primary-darken-2; border-title-color: $text; padding: 0 1; }
    #colony { width: 34; }
    #colonists { width: 1fr; }
    #pawn { width: 46; }
    #managers { width: 3fr; }
    #alerts { width: 2fr; }
    #commands { width: 3fr; }
    #journal { width: 2fr; }
    DataTable { height: 1fr; }
    """
    BINDINGS = [("q", "quit", "quit"), ("c", "toggle_quiet", "clock cmds"), ("f", "toggle_follow", "follow newest")]

    def __init__(self, run_dir: Path | None, runs: Path = Path("runs")):
        super().__init__()
        self.runs = runs
        self.follow = run_dir is None
        self.run_dir = run_dir or newest_run(runs)
        self.offset = 0
        self.state: dict[str, Any] = {}
        self.state_mtime = 0.0
        self.show_quiet = False
        self.last_message: dict[str, tuple[int | None, str]] = {}
        self.selected: str | None = None
        self.counts = {"commands": 0, "errors": 0, "rejected": 0}

    def compose(self) -> ComposeResult:
        yield Static(id="status")
        with Horizontal(id="top"):
            yield Static(id="colony", classes="box")
            yield DataTable(id="colonists", classes="box", cursor_type="row", zebra_stripes=True)
            yield Static(id="pawn", classes="box")
        with Horizontal(id="middle"):
            yield DataTable(id="managers", classes="box", cursor_type="none", zebra_stripes=True)
            yield DataTable(id="alerts", classes="box", cursor_type="none")
        with Horizontal(id="bottom"):
            yield RichLog(id="commands", classes="box", max_lines=2000, wrap=False, auto_scroll=True)
            yield RichLog(id="journal", classes="box", max_lines=2000, wrap=True, auto_scroll=True)
        yield Footer()

    def on_mount(self) -> None:
        titles = {"colony": "Colony (as read this cycle)", "colonists": "Colonists", "pawn": "Colonist",
                  "managers": "Managers", "alerts": "Game alerts", "commands": "Commands sent to the game",
                  "journal": "Journal: events · runs · warnings · incidents"}
        for widget_id, title in titles.items():
            self.query_one(f"#{widget_id}").border_title = title
        self.query_one("#colonists", DataTable).add_columns("name", "pos", "mood", "job", "flags", "worst thoughts")
        self.query_one("#managers", DataTable).add_columns("pri", "manager", "every", "last", "next", "last said")
        self.query_one("#alerts", DataTable).add_columns("prio", "alert", "owner")
        self.refresh_all()
        self.set_interval(1.0, self.refresh_all)

    # --- actions ---------------------------------------------------------------------------

    def action_toggle_quiet(self) -> None:
        self.show_quiet = not self.show_quiet
        self.notify(f"Routine clock commands {'shown' if self.show_quiet else 'hidden'} (from now on).")

    def action_toggle_follow(self) -> None:
        self.follow = not self.follow
        self.notify(f"Following newer runs: {'on' if self.follow else 'off'}.")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "colonists" and event.row_key is not None:
            self.selected = event.row_key.value
            self.render_pawn()

    # --- refresh ---------------------------------------------------------------------------

    def refresh_all(self) -> None:
        if self.follow:
            newest = newest_run(self.runs)
            if newest is not None and newest != self.run_dir:
                self.switch_run(newest)
        if self.run_dir is None:
            self.query_one("#status", Static).update(f"No runs yet in {self.runs}/: start one with `rimagent run` or `eval`.")
            return
        self.read_journal()
        self.read_state()
        self.render_status()

    def switch_run(self, run_dir: Path) -> None:
        self.run_dir, self.offset, self.state, self.state_mtime = run_dir, 0, {}, 0.0
        self.last_message.clear()
        self.counts = {"commands": 0, "errors": 0, "rejected": 0}
        self.query_one("#commands", RichLog).clear()
        self.query_one("#journal", RichLog).clear()

    def read_journal(self) -> None:
        path = self.run_dir / "journal.jsonl"
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as f:
            f.seek(self.offset)
            chunk = f.read()
        complete = chunk[: chunk.rfind("\n") + 1]  # a line still being written waits for the next refresh
        self.offset += len(complete.encode("utf-8"))
        commands, journal = self.query_one("#commands", RichLog), self.query_one("#journal", RichLog)
        for raw in complete.splitlines():
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            kind = entry.get("kind")
            if kind == "command":
                self.counts["commands"] += 1
                result = entry.get("result") or {}
                self.counts["errors"] += bool(result.get("error"))
                self.counts["rejected"] += bool(result.get("rejected") or result.get("rejectedCount"))
                if self.show_quiet or not entry.get("quiet"):
                    commands.write(command_line(entry))
                continue
            if kind == "manager":
                self.last_message[entry.get("manager")] = (entry.get("tick"), entry.get("message", ""))
            journal.write(journal_line(entry))
        if complete:
            self.render_managers()

    def read_state(self) -> None:
        path = self.run_dir / "state.json"
        try:
            mtime = path.stat().st_mtime
            if mtime == self.state_mtime:
                return
            self.state, self.state_mtime = json.loads(path.read_text(encoding="utf-8")), mtime
        except (OSError, ValueError):
            return
        self.render_colony()
        self.render_colonists()
        self.render_pawn()
        self.render_managers()
        self.render_alerts()

    # --- panels ----------------------------------------------------------------------------

    def render_status(self) -> None:
        s = self.state
        status = s.get("status", "waiting")
        age = time.time() - s["updated"] if s.get("updated") else None
        stale = age is not None and age > 120 and status not in ("done", "halted")
        game_time = (s.get("game") or {}).get("time") or {}
        line1 = cat(Text(f" {status.upper()} ", style=STATUS_STYLE.get(status, "bold")))
        line1 += Text(f"  {self.run_dir.name if self.run_dir else '-'}", style="bold")
        line1 += Text(f"  tick {s.get('tick') or '-'} {days(s.get('tick'))}")
        if game_time:
            line1 += Text(f" ({game_time.get('quadrum')} {game_time.get('dayOfSeason')}, {game_time.get('hourOfDay')}h"
                          f"{', paused' if game_time.get('paused') else ''})", style="grey70")
        if s.get("startTick") is not None and s.get("targetTick"):
            span = max(1, s["targetTick"] - s["startTick"])
            done = ((s.get("tick") or s["startTick"]) - s["startTick"]) / span
            line1 += Text(f"  run {done:.0%} of {span / TICKS_PER_DAY:.1f}d")
        line1 += Text(f"  cycle {s.get('cycle', '-')}")
        if age is not None:
            line1 += Text(f"  updated {age:.0f}s ago", style="bold red" if stale else "grey50")
        if not self.follow:
            line1 += Text("  [pinned]", style="grey50")
        last = s.get("lastRun") or {}
        calls = s.get("calls") or {}
        chunk = s.get("requestedChunk")
        line2 = cat(Text(" chunk ", style="grey50"), f"{s.get('chunkHours', '-')}h")
        if chunk:
            line2 += Text(f" (asked {chunk}h)", style="cyan")
        line2 += cat(Text("  last run ", style="grey50"), Text(
            f"{last.get('status', '-')}/{last.get('endReason', '-')} {last.get('hoursElapsed', '-')}h"
            + (f" · {'; '.join(last['events'])}" if last.get("events") else "")))
        line2 += cat(Text("  escalations ", style="grey50"), Text(
            f"{s.get('escalations', 0)}/{s.get('maxEscalations', '-')}", style="magenta" if s.get("escalations") else ""))
        line2 += cat(Text("  stalled ", style="grey50"), Text(str(s.get("stalledRuns", 0))))
        line2 += cat(Text("  calls ", style="grey50"), Text(f"{calls.get('reads', 0)} reads · {calls.get('commands', 0)} cmds"))
        line2 += Text(f"  ({self.counts['rejected']} rejected, {self.counts['errors']} errors)",
                      style="yellow" if self.counts["errors"] or self.counts["rejected"] else "grey50")
        if s.get("pending"):
            line2 += Text(f"  pending: {'; '.join(s['pending'])}", style="yellow")
        self.query_one("#status", Static).update(line1 + Text("\n") + line2)

    def render_colony(self) -> None:
        c = self.state.get("colony") or {}
        food, mood, med, threats = c.get("food") or {}, c.get("mood") or {}, c.get("medical") or {}, c.get("threats") or {}
        stored = (food.get("storedNutrition") or {})
        t = Text()
        days_left = food.get("daysLeft")
        t += cat(Text("food   ", style="grey50"), Text(
            f"{days_left if days_left is not None else '-'}d", style="red" if (days_left or 0) < 2 else "green"))
        t += Text(f"  {stored.get('total', '-')} nut ({stored.get('meals', 0)} meals)\n")
        t += cat(Text("       ", style="grey50"), Text(f"eats {food.get('eatenPerDay', '-')}/day\n", style="grey70"))
        t += cat(Text("mood   ", style="grey50"), bar(mood.get("average")) + Text(f"  low {mood.get('lowMood', 0)}\n"))
        t += cat(Text("health ", style="grey50"), Text(
            f"downed {med.get('downed', 0)}  bleeding {med.get('bleeding', 0)}\n",
            style="red" if med.get("downed") or med.get("bleeding") else ""))
        t += cat(Text("threat ", style="grey50"), Text(
            f"hostile {threats.get('hostiles', 0)}  manhunt {threats.get('manhunters', 0)}\n",
            style="bold red" if threats.get("hostiles") or threats.get("manhunters") else ""))
        t += cat(Text("       ", style="grey50"), Text(f"predators {threats.get('predators', 0)}  fires {threats.get('fires', 0)}\n"))
        wires = [w for w in self.state.get("tripwires") or [] if w.get("since") is not None]
        if wires:
            t += cat(Text("trip   ", style="grey50"), Text(", ".join(f"{w['name']} since {w['since']}" for w in wires), style="red"))
        self.query_one("#colony", Static).update(t)

    def render_colonists(self) -> None:
        table = self.query_one("#colonists", DataTable)
        row = table.cursor_row
        table.clear()
        for p in self.state.get("colonists") or []:
            flags = " ".join(f for f, on in (("DRAFT", p.get("drafted")), ("DOWN", p.get("downed"))) if on)
            worst = ", ".join(f"{t['label']} {t['offset']:+g}" for t in (p.get("thoughts") or []) if t["offset"] < 0)[:60]
            pos = p.get("position")
            table.add_row(p.get("name") or "?", f"{pos[0]},{pos[1]}" if pos else "-", bar(p.get("mood"), 5),
                          (p.get("job") or "-")[:28], Text(flags, style="bold red"), Text(worst, style="dark_orange"),
                          key=p.get("id"))
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))

    def render_pawn(self) -> None:
        pawns = {p.get("id"): p for p in self.state.get("colonists") or []}
        p = pawns.get(self.selected) or next(iter(pawns.values()), None)
        widget = self.query_one("#pawn", Static)
        if p is None:
            widget.update("")
            return
        widget.border_title = f"Colonist: {p.get('name')}"
        t = Text()
        t += cat(Text("health ", style="grey50"), Text(f"{p.get('health', '-')}  pain {p.get('pain', '-')}"))
        if p.get("hediffs"):
            t += Text("  " + ", ".join(p["hediffs"]), style="red")
        needs = p.get("needs") or {}
        t += Text("\n")
        for i, (name, level) in enumerate(sorted(needs.items(), key=lambda kv: kv[1])):
            t += cat(Text(f"{name[:9]:<9}", style="grey50"), bar(level, 5), "  " if i % 2 == 0 else "\n")
        t += Text("\n")
        for thought in p.get("thoughts") or []:
            t += Text(f"{thought['offset']:+g} {thought['label']}  ", style="red" if thought["offset"] < 0 else "green")
        widget.update(t)

    def render_managers(self) -> None:
        table = self.query_one("#managers", DataTable)
        table.clear()
        now = self.state.get("tick")
        for m in self.state.get("managers") or []:
            said_tick, said = self.last_message.get(m["name"], (None, ""))
            every = "cycle" if not m.get("everyHours") else f"{m['everyHours']:g}h"
            table.add_row(str(m.get("priority")), Text(m["name"], style="bold"), every, days(m.get("lastTick")),
                          hours_until(m.get("nextTick"), now),
                          Text(f"{days(said_tick)} {said}"[:90] if said else (m.get("memory") or "")[:90], style="grey70"))

    def render_alerts(self) -> None:
        table = self.query_one("#alerts", DataTable)
        table.clear()
        order = {"Critical": 0, "High": 1, "Medium": 2}
        now = self.state.get("tick")
        for a in sorted(self.state.get("alerts") or [], key=lambda a: order.get(a.get("priority"), 3)):
            if a.get("claimedBy"):
                owner = Text(", ".join(a["claimedBy"]), style="green")
            elif a.get("unclaimedSince") is not None and now is not None:
                owner = Text(f"UNCLAIMED {(now - a['unclaimedSince']) / TICKS_PER_HOUR:.0f}h", style="bold red")
            else:
                owner = Text("unclaimed (noted)", style="dark_orange")
            prio = a.get("priority") or "-"
            table.add_row(Text(prio, style="red" if prio in ("Critical", "High") else ""),
                          (a.get("label") or a.get("type") or "?")[:40], owner)


def main(args: list[str]) -> int:
    run_dir = Path(args[0]) if args else None
    if run_dir is not None and not (run_dir / "journal.jsonl").exists():
        print(f"No journal.jsonl in {run_dir}.")
        return 2
    Watch(run_dir).run()
    return 0
