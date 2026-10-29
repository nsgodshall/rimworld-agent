import asyncio
import json

from rimsdk import RimClient
from rimagent import Runtime
from rimagent.journal import Journal
from rimagent.managers.beds import BedsManager
from rimagent.managers.food import FoodManager
from rimagent.telemetry import CommandLog
from rimagent.watch import Watch

from .conftest import FakeTransport
from .fakegame import FakeRim


class Stub:
    """The runtime attributes CommandLog reads."""

    def __init__(self, path):
        self.journal, self.tick, self.actor = Journal(path, echo=False), 100, "beds"


def entries(path, kind):
    return [e for e in map(json.loads, path.read_text().splitlines()) if e["kind"] == kind]


def test_commands_are_journalled_with_who_sent_them_and_reads_only_counted(tmp_path):
    fake = FakeTransport(lambda m, p, b: {"changed": True, "data": {"applied": 2, "rejectedCount": 1, "results": [
        {"outcome": "applied"}, {"outcome": "applied"}, {"outcome": "rejected", "reason": "Space already occupied."}]}})
    rim, stub = RimClient(fake), Stub(tmp_path / "j.jsonl")
    log = CommandLog(stub)
    rim.call_hooks.append(log)
    rim.get_colony_status()
    rim.place_blueprint(placements=[{"def": "Wall", "x": i, "z": 0} for i in range(5)])
    (cmd,) = entries(tmp_path / "j.jsonl", "command")
    assert (cmd["actor"], cmd["tool"], cmd["tick"]) == ("beds", "place_blueprint", 100)
    assert len(cmd["args"]["placements"]) == 4 and cmd["args"]["placements"][-1] == "…+2"  # cut for the log
    assert cmd["result"] == {"changed": True, "applied": 2, "rejectedCount": 1, "rejected": ["Space already occupied."]}
    assert (log.reads, log.commands) == (1, 1)


def test_a_refused_command_is_logged_with_the_error(tmp_path):
    from rimsdk import errors

    def refuse(m, p, b):
        raise errors.Conflict("Pawn cannot do this work type.", status=409)

    rim, stub = RimClient(FakeTransport(refuse)), Stub(tmp_path / "j.jsonl")
    rim.call_hooks.append(CommandLog(stub))
    try:
        rim.set_pawn_work_priority("Human1", "Art", priority=3)
    except errors.Conflict:
        pass
    (cmd,) = entries(tmp_path / "j.jsonl", "command")
    assert cmd["result"] == {"error": "Conflict: Pawn cannot do this work type."}


def run_once(tmp_path):
    rim = FakeRim()
    rt = Runtime(rim, tmp_path / "run", managers=[FoodManager(), BedsManager()], tripwires=[], echo=False)
    assert rt.run(2) == "done"
    return rt


def test_the_runtime_publishes_its_picture_of_the_game(tmp_path):
    rt = run_once(tmp_path)
    state = json.loads((tmp_path / "run" / "state.json").read_text())
    assert state["status"] == "done" and state["cycle"] >= 1
    assert [m["name"] for m in state["managers"]] == ["food", "beds"]
    assert state["managers"][1]["memory"]  # beds remembers what it planned
    assert {c["name"] for c in state["colonists"]} == {"A", "B", "C"}
    assert state["lastRun"]["status"] == "completed"
    assert state["startTick"] == 0 and state["targetTick"] == 5000


def test_the_watch_view_renders_a_run(tmp_path):
    run_once(tmp_path)
    run_dir = tmp_path / "run"
    with (run_dir / "journal.jsonl").open("a") as f:
        f.write(json.dumps({"kind": "command", "tick": 5, "actor": "beds", "tool": "place_blueprint",
                            "args": {"placements": [{"def": "Bed"}]}, "result": {"changed": True, "applied": 1}}) + "\n")

    async def check():
        app = Watch(run_dir, runs=tmp_path)
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause()
            assert app.query_one("#colonists").row_count == 3
            assert app.query_one("#managers").row_count == 2
            assert app.counts["commands"] == 1
            assert "DONE" in str(app.query_one("#status").render())

    asyncio.run(check())
