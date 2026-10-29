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


LOW_MEDICINE = {"type": "Alert_LowMedicine", "label": "Low medicine", "priority": "High"}


def loose_medicine(n, x, z, count):
    # As find_things shows a stack outside storage (run 20261029-143226).
    return {"id": f"MedicineIndustrial{n}", "def": "MedicineIndustrial", "label": "Medicine",
            "x": x, "z": z, "count": count, "forbidden": False, "inStorage": False}


def test_low_medicine_gets_loose_medicine_hauled(tmp_path):
    """Incident 001 of run 20261029-143226: Low medicine for 13h, 31 medicine lying by the stockpile."""
    assert "Alert_LowMedicine" in MedicalManager.alerts
    rim = FakeRim()
    rim.alerts = [LOW_MEDICINE]
    rim.medicine = [loose_medicine(7760, 124, 138, 5), loose_medicine(45210, 125, 137, 25),
                    {**loose_medicine(1, 120, 140, 3), "inStorage": True}]
    manager = MedicalManager()
    manager.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    assert {"kind": "haul", "thing_ids": ["MedicineIndustrial7760", "MedicineIndustrial45210"]} in rim.called("designate")
    # The biggest stack is hauled now, by one colonist.
    assert [(o["target_id"], o["option"]) for o in rim.called("choose_pawn_action")] == [("MedicineIndustrial45210", "2")]

    # The next cycle, an hour on, leaves the colonists to it.
    rim.tick += 2500
    manager.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    assert len(rim.called("choose_pawn_action")) == 1


def test_low_medicine_with_none_to_store_is_noted_not_stopped_for(tmp_path):
    rim = FakeRim()
    rim.alerts = [LOW_MEDICINE]
    rim.medicine = []
    ctx = Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))
    MedicalManager().update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("medicineShort", "warn")]
    assert not rim.called("choose_pawn_action")


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
