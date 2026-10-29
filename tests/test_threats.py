from rimagent import Runtime
from rimagent.managers.threats import ThreatsManager

from .fakegame import FakeRim


def run(tmp_path, events):
    rim = FakeRim()
    rim.run_script = [{"status": "stopped", "endReason": events[0]["kind"], "events": events}]
    rt = Runtime(rim, tmp_path / "run", managers=[ThreatsManager()], tripwires=[], echo=False)
    return rt.run(4)


def test_ancient_danger_is_noted_and_play_continues(tmp_path):
    assert run(tmp_path, [{"kind": "threatLetter", "tick": 17812, "detail": "Ancient danger"}]) == "done"
    assert not (tmp_path / "run" / "incidents").exists()
    assert "Ancient danger" in (tmp_path / "run" / "journal.jsonl").read_text()


def test_a_heat_wave_is_left_to_the_house_and_play_continues(tmp_path):
    assert run(tmp_path, [{"kind": "threatLetter", "tick": 395002, "detail": "Heat wave"}]) == "done"
    assert not (tmp_path / "run" / "incidents").exists()


def test_other_threat_letters_still_halt(tmp_path):
    assert run(tmp_path, [{"kind": "threatLetter", "tick": 300, "detail": "Raid"}]) == "halted"
