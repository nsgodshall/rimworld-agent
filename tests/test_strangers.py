from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers.strangers import StrangersManager

from .fakegame import FakeRim


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def survivor(downed=True):
    return {"ids": {"id": "Human900"}, "name": "Wild", "def": {"defName": "Human"}, "downed": downed, "dead": False,
            "position": {"x": 70, "y": 0, "z": 70}}


def test_a_downed_crash_survivor_is_carried_to_a_bed(tmp_path):
    rim = FakeRim()
    rim.strangers = [survivor()]
    StrangersManager().update(ctx_for(rim, tmp_path))
    assert [(c["order"], c["target_id"]) for c in rim.called("order_pawn")] == [("rescue", "Human900")]


def test_strangers_on_their_feet_are_left_alone(tmp_path):
    rim = FakeRim()
    rim.strangers = [survivor(downed=False)]
    StrangersManager().update(ctx_for(rim, tmp_path))
    assert rim.called("order_pawn") == []
