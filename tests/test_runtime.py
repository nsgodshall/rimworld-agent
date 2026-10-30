import json
import os
import sys
import textwrap

import pytest

from rimagent import Context, Event, Manager, Runtime
from rimagent.loader import ManagerLoader
from rimagent.runtime import Tripwire

from .fakegame import FakeRim


class Recorder(Manager):
    name = "recorder"
    every_hours = 2
    handles = ("lowFood",)

    def __init__(self):
        super().__init__()
        self.updates, self.events = [], []

    def update(self, ctx: Context) -> None:
        self.updates.append(ctx.tick)

    def on_event(self, ctx: Context, event: Event) -> None:
        self.events.append(event.kind)


class Broken(Manager):
    name = "broken"

    def update(self, ctx: Context) -> None:
        raise KeyError("pawns")


def runtime(rim, tmp_path, managers, **kw):
    return Runtime(rim, tmp_path / "run", managers=managers, tripwires=kw.pop("tripwires", []), echo=False, **kw)


def journal(rt):
    return [json.loads(line) for line in rt.journal.path.read_text().splitlines()]


def test_runs_chunks_until_the_hours_are_played(tmp_path):
    rim, rec = FakeRim(), Recorder()
    rt = runtime(rim, tmp_path, [rec], chunk_hours=2)
    assert rt.run(6) == "done"
    assert [c["hours"] for c in rim.called("advance")] == [2, 2, 2]
    assert rec.updates == [0, 5000, 10000, 15000]
    assert [e["kind"] for e in journal(rt)][-1] == "stop"


def test_handled_event_reaches_its_manager_without_incident(tmp_path):
    rim, rec = FakeRim(), Recorder()
    rim.run_script = [{"status": "stopped", "endReason": "lowFood", "events": [{"kind": "lowFood", "tick": 100}]}]
    rt = runtime(rim, tmp_path, [rec])
    assert rt.run(4) == "done"
    assert rec.events == ["lowFood"]
    assert not (tmp_path / "run" / "incidents").exists()


def test_unhandled_raid_halts_pauses_and_writes_a_report(tmp_path):
    rim = FakeRim()
    rim.run_script = [{"status": "stopped", "endReason": "hostiles", "paused": True,
                       "events": [{"kind": "hostiles", "tick": 300, "detail": "Raid: 4 pirates"}]}]
    rim.paused = False
    rt = runtime(rim, tmp_path, [Recorder()])
    assert rt.run(24) == "halted"
    reports = sorted((tmp_path / "run" / "incidents").glob("*.md"))
    assert [r.name for r in reports] == ["001-unhandledEvent.md"]
    assert "Raid: 4 pirates" in reports[0].read_text()
    assert rim.called("set_game_speed") == [{"speed": "Paused"}]


def test_warnings_are_journaled_and_play_continues(tmp_path):
    rim = FakeRim()
    rim.run_script = [{"events": [{"kind": "injured", "tick": 10, "pawn": {"name": "A"}}]}]
    rt = runtime(rim, tmp_path, [])
    assert rt.run(4) == "done"
    assert any(e["kind"] == "warning" and "injured" in e["summary"] for e in journal(rt))


def test_manager_exception_becomes_an_incident_with_traceback(tmp_path):
    rt = runtime(FakeRim(), tmp_path, [Broken()])
    assert rt.run(4) == "halted"
    record = json.loads(next((tmp_path / "run" / "incidents").glob("*.json")).read_text())
    assert record["incident"]["kind"] == "managerError"
    assert "KeyError" in record["incident"]["details"]["traceback"]


def test_stalled_time_halts_as_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr("rimagent.runtime.time.sleep", lambda s: None)
    rim = FakeRim()
    rim.run_script = [{"status": "interrupted", "endReason": "paused", "tick": 0}] * 3
    rt = runtime(rim, tmp_path, [])
    assert rt.run(24) == "halted"
    assert (tmp_path / "run" / "incidents" / "001-blocked.md").exists()


def test_a_window_holding_the_game_paused_is_closed_by_saving_and_reloading(tmp_path, monkeypatch):
    """Trial 9 was going well (89.1) when a window RimMCP doesn't list held the game paused at day 10."""
    monkeypatch.setattr("rimagent.runtime.time.sleep", lambda s: None)
    rim = FakeRim()
    rim.run_script = [{"status": "interrupted", "endReason": "forcedPause", "tick": 0}] * 3
    rt = runtime(rim, tmp_path, [])
    assert rt.run(4) == "done"
    assert rim.called("save_game") == [{"name": "rimagent-unstick", "overwrite": True}]
    assert rim.called("load_game")[0]["discard_unsaved"] is True
    assert not (tmp_path / "run" / "incidents").exists()


def test_a_window_that_keeps_coming_back_still_halts(tmp_path, monkeypatch):
    monkeypatch.setattr("rimagent.runtime.time.sleep", lambda s: None)
    rim = FakeRim()
    rim.run_script = [{"status": "interrupted", "endReason": "forcedPause", "tick": 0}] * 12
    rt = runtime(rim, tmp_path, [])
    assert rt.run(4) == "halted"
    assert len(rim.called("load_game")) == 3
    assert (tmp_path / "run" / "incidents" / "001-blocked.md").exists()


def test_refused_time_control_is_blocked_not_a_crash(tmp_path, monkeypatch):
    from rimsdk import errors

    monkeypatch.setattr("rimagent.runtime.time.sleep", lambda s: None)
    rim = FakeRim()

    def refuse(hours, **kw):
        raise errors.Conflict("RimWorld is not accepting time control right now.", status=409)

    rim.advance = refuse
    rt = runtime(rim, tmp_path, [])
    assert rt.run(24) == "halted"
    report = (tmp_path / "run" / "incidents" / "001-blocked.md").read_text()
    assert "not accepting time control" in report


def test_one_interruption_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr("rimagent.runtime.time.sleep", lambda s: None)
    rim = FakeRim()
    rim.run_script = [{"status": "interrupted", "endReason": "speedChanged", "tick": 1}]
    assert runtime(rim, tmp_path, []).run(2) == "done"


def test_tripwire_waits_for_its_hold_time(tmp_path):
    rim = FakeRim()
    rim.food = {"eatenPerDay": 5.6, "daysLeft": 0.5}
    wire = Tripwire("foodCritical", lambda s: "low" if s.food_days < 1 else None, hold_hours=12)
    rt = runtime(rim, tmp_path, [], tripwires=[wire], chunk_hours=4)
    assert rt.run(24) == "halted"
    record = json.loads(next((tmp_path / "run" / "incidents").glob("*.json")).read_text())
    assert record["incident"]["tick"] == 12 * 2500


def test_history_messages_become_events(tmp_path):
    rim, seen = FakeRim(), []
    rt = runtime(rim, tmp_path, [])
    rt.bus.subscribe("message", lambda e: seen.append(e.detail))
    rim.history = [{"kind": "message", "tick": 1, "label": "Hikari is hungry."}]
    rt._skip_old_history()  # the runtime ignores history from before it started...
    rim.history = [{"kind": "message", "tick": 2, "label": "A trader is here."}]
    rt.run(2)  # ...and picks up what arrives after
    assert seen == ["A trader is here."]


def test_loader_hot_reloads_changed_managers(tmp_path, monkeypatch):
    pkg = tmp_path / "hotmgrs"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    source = textwrap.dedent("""
        from rimagent import Manager
        class M(Manager):
            name = "m"
            every_hours = {hours}
    """)
    (pkg / "m.py").write_text(source.format(hours=1))
    monkeypatch.syspath_prepend(str(tmp_path))
    loader = ManagerLoader("hotmgrs")
    first = loader.load()
    assert [type(m).every_hours for m in first] == [1] and not loader.changed()
    first[0].last_tick = 777
    (pkg / "m.py").write_text(source.format(hours=5))
    stat = (pkg / "m.py").stat()
    os.utime(pkg / "m.py", (stat.st_atime, stat.st_mtime + 10))
    assert loader.changed()
    second = loader.load(first)
    assert [type(m).every_hours for m in second] == [5]
    assert second[0].last_tick == 777  # the schedule survives the reload
    sys.modules.pop("hotmgrs.m", None)


def test_loader_orders_managers_by_priority():
    names = [m.name for m in ManagerLoader().load()]
    assert names.index("defense") < names.index("food") < names.index("beds")


def test_a_reload_sees_new_names_in_the_modules_a_manager_imports(tmp_path, monkeypatch):
    """Trial 12 crashed: house.py was reloaded before materials.py, and imported a name only the new one had."""
    import os
    import sys
    import time as _time

    from rimagent.loader import ManagerLoader

    pkg = tmp_path / "trialpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "zhelper.py").write_text("OLD = 1\n")
    (pkg / "alpha.py").write_text(
        "from rimagent.manager import Manager\nfrom .zhelper import OLD\n\nclass Alpha(Manager):\n    name = 'alpha'\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    loader = ManagerLoader("trialpkg")
    assert [m.name for m in loader.load()] == ["alpha"]
    later = _time.time() + 5
    (pkg / "zhelper.py").write_text("OLD = 1\nNEW = 2\n")
    (pkg / "alpha.py").write_text(
        "from rimagent.manager import Manager\nfrom .zhelper import NEW\n\nclass Alpha(Manager):\n    name = 'alpha2'\n")
    for f in ("zhelper.py", "alpha.py"):
        os.utime(pkg / f, (later, later))
    assert loader.changed()
    assert [m.name for m in loader.load()] == ["alpha2"]
    for name in [m for m in sys.modules if m.startswith("trialpkg")]:
        del sys.modules[name]


def test_an_incident_naming_its_alert_by_type_has_a_key():
    """Trial 25 crashed: the mood manager's extremeBreakRisk incident gave alert as a string."""
    from rimagent.incidents import Incident

    assert Incident("extremeBreakRisk", "x", details={"alert": "Alert_MajorOrExtremeBreakRisk"}).key == \
        "extremeBreakRisk:Alert_MajorOrExtremeBreakRisk"
