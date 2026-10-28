import json
import sys
import textwrap

import pytest

from rimagent import Context, Event, Incident, Manager, Runtime
from rimagent.escalate import ALLOWED_TOOLS, ClaudeEscalator
from rimagent.incidents import Resolution

from .fakegame import FakeRim

# --- ClaudeEscalator against a fake `claude` -----------------------------------------------

FAKE_CLAUDE = """\
#!{python}
import json, pathlib, sys
args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
pathlib.Path("prompt.txt").write_text(prompt)
pathlib.Path("args.json").write_text(json.dumps(args))
mode = pathlib.Path("mode.txt").read_text()
if mode in ("resume", "halt"):
    pathlib.Path("src/rimagent/managers/defense.py").write_text("# new manager\\n")
    print(json.dumps({{"type": "result", "result": "done", "total_cost_usd": 0.42, "session_id": "s1",
                      "structured_output": {{"action": mode, "summary": "Added defense.", "files": ["defense.py"]}}}}))
elif mode == "text":
    print(json.dumps({{"result": 'All set. {{"action": "resume", "summary": "via text", "files": []}}'}}))
else:
    print("not json")
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src" / "rimagent" / "managers").mkdir(parents=True)
    (tmp_path / "src" / "rimagent" / "managers" / "food.py").write_text("# food\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "runs" / "r" / "incidents").mkdir(parents=True)
    claude = tmp_path / "fake-claude"
    claude.write_text(FAKE_CLAUDE.format(python=sys.executable))
    claude.chmod(0o755)
    return tmp_path


def escalator(repo, mode, verify=("true",)):
    (repo / "mode.txt").write_text(mode)
    return ClaudeEscalator(claude=str(repo / "fake-claude"), repo=repo, verify=list(verify), budget_usd=1.5)


def report(repo):
    path = repo / "runs" / "r" / "incidents" / "001-unhandledEvent.md"
    path.write_text("# report")
    return path


RAID = Incident("unhandledEvent", "No manager handles hostiles", event=Event("hostiles", 10, "run", "Raid"))


def test_resume_after_a_verified_fix_records_the_diff_and_cost(repo):
    res = escalator(repo, "resume").escalate(RAID, report(repo))
    assert res.resume and res.summary == "Added defense."
    assert res.details["cost_usd"] == 0.42 and res.details["files"] == ["defense.py"]
    diff = (repo / "runs" / "r" / "incidents" / "001-unhandledEvent.diff").read_text()
    assert "+# new manager" in diff and "b/src/rimagent/managers/defense.py" in diff
    prompt = (repo / "prompt.txt").read_text()
    assert "runs/r/incidents/001-unhandledEvent.md" in prompt and "delivered again" in prompt


def test_session_is_sandboxed_and_capped(repo):
    escalator(repo, "resume").escalate(RAID, report(repo))
    args = json.loads((repo / "args.json").read_text())
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert args[args.index("--max-budget-usd") + 1] == "1.5"
    assert "Edit(./src/rimagent/managers/**)" in args and "Bash(uv run pytest:*)" in args
    assert not any(t.startswith(("Edit(./src/rimagent/**", "Bash(uv run python -m rimagent run --hours")) for t in ALLOWED_TOOLS)


def test_failing_tests_block_resume(repo):
    res = escalator(repo, "resume", verify=("false",)).escalate(RAID, report(repo))
    assert not res.resume and "fails" in res.summary


def test_halt_answer_stops(repo):
    res = escalator(repo, "halt").escalate(RAID, report(repo))
    assert not res.resume and res.summary == "Added defense."


def test_answer_in_result_text_is_accepted(repo):
    assert escalator(repo, "text").escalate(RAID, report(repo)).resume


def test_garbage_output_stops(repo):
    res = escalator(repo, "garbage").escalate(RAID, report(repo))
    assert not res.resume and "no usable answer" in res.summary


# --- the runtime around escalation ---------------------------------------------------------


class Defense(Manager):
    name = "defense"
    handles = ("hostiles",)

    def __init__(self):
        super().__init__()
        self.seen = []

    def on_event(self, ctx: Context, event: Event) -> None:
        self.seen.append((event.kind, ctx.tick))


class FixingEscalator:
    """Installs a manager, as a real fix would, and resumes."""

    def __init__(self, runtime_ref, manager=None):
        self.runtime_ref, self.manager, self.calls = runtime_ref, manager, []

    def escalate(self, incident, report):
        self.calls.append(incident.key)
        if self.manager is not None:
            self.runtime_ref[0].managers.append(self.manager)
        return Resolution(True, "fixed")


def make(tmp_path, rim, manager=None, **kw):
    ref = []
    esc = FixingEscalator(ref, manager)
    rt = Runtime(rim, tmp_path / "run", managers=[], tripwires=[], escalator=esc, echo=False, **kw)
    ref.append(rt)
    return rt, esc


def test_raid_is_redelivered_to_the_new_manager_before_time_runs(tmp_path):
    rim, defense = FakeRim(), Defense()
    rim.run_script = [{"status": "stopped", "tick": 300, "events": [{"kind": "hostiles", "tick": 300, "detail": "Raid"}]}]
    rt, esc = make(tmp_path, rim, defense)
    assert rt.run(4) == "done"
    assert esc.calls == ["unhandledEvent:hostiles"]
    assert defense.seen == [("hostiles", 300)]
    # Handled at tick 300, before the next time run.
    assert [c["hours"] for c in rim.called("advance")][0] == 2


def test_a_problem_that_keeps_coming_back_stops_the_runtime(tmp_path):
    rim = FakeRim()
    raid = {"status": "stopped", "events": [{"kind": "hostiles", "tick": 1, "detail": "Raid"}]}
    rim.run_script = [raid, raid, raid]
    rt, esc = make(tmp_path, rim)  # "fixes" that install nothing
    assert rt.run(24) == "halted"
    assert esc.calls == ["unhandledEvent:hostiles"] * 2


def test_escalation_budget(tmp_path):
    rim = FakeRim()
    rim.run_script = [{"events": [{"kind": k, "tick": 1}]} for k in ("hostiles", "death", "downed")]
    rt, esc = make(tmp_path, rim, max_escalations=2)
    assert rt.run(24) == "halted"
    assert len(esc.calls) == 2


def test_blocked_time_goes_to_a_person_not_the_llm(tmp_path, monkeypatch):
    monkeypatch.setattr("rimagent.runtime.time.sleep", lambda s: None)
    rim = FakeRim()
    rim.run_script = [{"status": "interrupted", "endReason": "paused", "tick": 0}] * 3
    rt, esc = make(tmp_path, rim)
    assert rt.run(24) == "halted" and esc.calls == []


BEDS = {"type": "Alert_NeedColonistBeds", "label": "Need colonist beds", "priority": "High"}


def test_unclaimed_high_alert_escalates_after_twelve_hours(tmp_path):
    rim = FakeRim()
    rim.alerts = [BEDS]
    rt, esc = make(tmp_path, rim, chunk_hours=4)
    rt.run(24)
    assert esc.calls == ["unhandledAlert:Alert_NeedColonistBeds"]
    record = json.loads(next((tmp_path / "run" / "incidents").glob("*.json")).read_text())
    assert record["incident"]["tick"] == 12 * 2500


def test_gap_alerts_escalate_despite_medium_priority(tmp_path):
    rim = FakeRim()
    rim.alerts = [{"type": "Alert_NeedMealSource", "label": "Need meal source", "priority": "Medium"}]
    rt, esc = make(tmp_path, rim, chunk_hours=2)
    rt.run(12)
    assert esc.calls == ["unhandledAlert:Alert_NeedMealSource"]
    record = json.loads(next((tmp_path / "run" / "incidents").glob("*.json")).read_text())
    assert record["incident"]["tick"] == 6 * 2500


def test_claimed_alert_and_medium_alert_do_not_escalate(tmp_path):
    class Beds(Manager):
        name = "beds"
        alerts = ("Alert_NeedColonistBeds",)

    rim = FakeRim()
    rim.alerts = [BEDS, {"type": "Alert_NeedJoySources", "label": "Need recreation", "priority": "Medium"}]
    rt = Runtime(rim, tmp_path / "run", managers=[Beds()], tripwires=[], echo=False, chunk_hours=4)
    assert rt.run(24) == "done"
    warnings = [json.loads(l) for l in rt.journal.path.read_text().splitlines() if '"warning"' in l]
    assert len(warnings) == 1 and "Alert_NeedJoySources" in warnings[0]["summary"]
