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


def test_a_colonist_left_untended_gets_a_drafted_tender(tmp_path):
    """Trial 13: Miyazaki lay 12 hours with untended bruises and cracks, not bleeding."""
    rim = FakeRim()
    rim.alerts = [{"type": "Alert_ColonistNeedsTend", "label": "Medical treatment needed", "priority": "High",
                   "culprits": [{"id": "HumanB", "label": "B"}], "culpritCount": 1}]
    manager = MedicalManager()
    manager.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    assert [c for c in rim.called("order_pawn") if c["order"] == "tend"] == []  # doctors get two hours first
    rim.tick += 3 * 2500
    manager.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    tends = [c for c in rim.called("order_pawn") if c["order"] == "tend"]
    assert [(c["pawn_id"], c["target_id"]) for c in tends] == [("HumanA", "HumanB")]


def test_when_everyone_is_hurt_a_walking_patient_tends_the_downed(tmp_path):
    """Run 20261029-234707: after a raid all three colonists needed tending, one downed and bleeding; the
    runtime stopped because no unhurt colonist was left to tend."""
    rim = FakeRim()
    rim.colonists[2]["downed"] = True
    rim.medical = {"downed": 1, "bleeding": 1, "examples": [{"id": "HumanC", "name": "C", "downed": True},
                                                            {"id": "HumanA", "name": "A", "downed": False}]}
    rim.alerts = [{"type": "Alert_ColonistNeedsTend", "label": "Medical treatment needed", "priority": "High",
                   "culprits": [{"id": "HumanB", "label": "B"}], "culpritCount": 1}]
    manager = MedicalManager()
    manager.memory["needs_tend_since"] = rim.tick - 3 * 2500
    ctx = Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))
    manager.update(ctx)
    assert ctx.incidents == []
    tends = [(c["pawn_id"], c["target_id"]) for c in rim.called("order_pawn") if c["order"] == "tend"]
    assert tends == [("HumanA", "HumanC")]


def test_a_lone_downed_colonist_still_stops_the_runtime(tmp_path):
    rim = FakeRim()
    rim.colonists = rim.colonists[:1]
    rim.colonists[0]["downed"] = True
    rim.medical = {"downed": 1, "bleeding": 1, "examples": [{"id": "HumanA", "name": "A", "downed": True}]}
    ctx = Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))
    MedicalManager().update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("noTender", "halt")]


def test_a_patient_found_tended_is_not_retried_every_cycle(tmp_path):
    """Trial 22: tend came back alreadySatisfied each cycle; the helper was drafted again and again, never ate,
    and the colonist who did need help died."""
    from rimsdk import Result

    rim = FakeRim()
    rim.medical = {"downed": 0, "bleeding": 2, "examples": [{"id": "HumanB"}, {"id": "HumanC"}]}
    real = rim.order_pawn

    def order(pawn_id, *, order, target_id=None, **kw):
        if order == "tend" and target_id == "HumanB":
            rim._record("order_pawn", pawn_id=pawn_id, order=order, target_id=target_id)
            return Result({"changed": False, "data": {"order": order, "outcome": "alreadySatisfied", "reason": None}})
        return real(pawn_id, order=order, target_id=target_id, **kw)

    rim.order_pawn = order
    manager = MedicalManager()
    manager.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    rim.tick += 250
    manager.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    targets = [c["target_id"] for c in rim.called("order_pawn") if c["order"] == "tend"]
    assert targets == ["HumanB", "HumanC"]


def test_a_new_injury_ends_the_wait_on_that_colonist(tmp_path):
    """Trial 24: Sparky was waited on from an earlier tend, then cut in a raid, and bled out untended."""
    from rimagent import Event

    rim = FakeRim()
    rim.medical = {"downed": 1, "bleeding": 1, "examples": [{"id": "HumanC", "downed": True}]}
    manager = MedicalManager()
    manager.memory["tended_until"] = {"HumanC": rim.tick + 10 * 2500}
    ctx = Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))
    manager.on_event(ctx, Event("injured", rim.tick, "run", "bleeding", {"id": "HumanC", "name": "C"}))
    manager.update(ctx)
    assert [c["target_id"] for c in rim.called("order_pawn") if c["order"] == "tend"] == ["HumanC"]


def test_a_long_tend_gets_one_more_helper_an_hour_not_one_a_cycle(tmp_path):
    rim = FakeRim()
    rim.medical = {"downed": 0, "bleeding": 1, "examples": [{"id": "HumanC"}]}
    rim.colonists[0]["currentJob"] = {"defName": "TendPatient", "report": "tending to C."}
    manager = MedicalManager()
    for _ in range(12):  # 1.2 hours of 0.1-hour cycles
        manager.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
        rim.tick += 250
    sent = [c for c in rim.called("order_pawn") if c["order"] == "tend"]
    assert len(sent) == 1
