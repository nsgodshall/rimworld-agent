from rimagent import Context, Event, Snapshot
from rimagent.journal import Journal
from rimagent.managers.medical import MedicalManager

from .fakegame import FakeRim


def test_forbidden_medicine_is_unforbidden_and_injuries_are_handled(tmp_path):
    rim = FakeRim()
    rim.medicine = [{"id": "Med1", "def": "MedicineIndustrial", "count": 25, "forbidden": True},
                    {"id": "Med2", "def": "MedicineIndustrial", "count": 5, "forbidden": False}]
    ctx = Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))
    manager = MedicalManager()
    assert manager.on_event(ctx, Event("injured", 1, "run", "bleeding")) is True
    manager.update(ctx)
    assert rim.called("designate") == [{"kind": "unforbid", "thing_ids": ["Med1"]}]


def test_a_bleeding_colonist_gets_a_drafted_tender_until_the_tending_is_done(tmp_path):
    rim = FakeRim()
    rim.colonists[0]["downed"] = True
    rim.medical = {"downed": 1, "bleeding": 1, "examples": [{"id": "HumanA", "name": "A", "downed": True}]}
    manager = MedicalManager()
    ctx = Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))
    manager.update(ctx)
    assert rim.called("set_pawn_drafted") == [{"pawn_id": "HumanB", "drafted": True}]
    assert [(c["pawn_id"], c["order"], c["target_id"]) for c in rim.called("order_pawn")] == [("HumanB", "tend", "HumanA")]
    assert ctx.chunk_hours == 0.1

    rim.colonists[1]["currentJob"] = {"defName": "TendPatient"}  # still tending: leave B to it
    manager.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    assert len(rim.called("order_pawn")) == 1

    rim.colonists[1]["currentJob"] = {"defName": "Wait_Combat"}  # done, bleeding stopped
    rim.medical = {"downed": 1, "bleeding": 0, "examples": []}
    manager.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    assert rim.called("set_pawn_drafted")[-1] == {"pawn_id": "HumanB", "drafted": False}
    assert manager.tenders == {}
