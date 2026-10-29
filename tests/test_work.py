from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers.work import WorkManager

from .fakegame import FakeRim


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def switch(rim, pawn, work_type, **kw):
    next(w for w in rim.work[pawn] if w["defName"] == work_type).update(**kw)


def test_work_switched_off_is_turned_on_and_incapable_work_left_alone(tmp_path):
    """Trial 4: Sparky had only construction on (he can't haul or clean) and stood idle."""
    rim = FakeRim()
    for w in ("Growing", "PlantCutting", "Mining"):
        switch(rim, "HumanC", w, active=False, priority=0)
    for w in ("Hauling", "Cleaning"):
        switch(rim, "HumanC", w, disabled=True, active=False, priority=0)
    WorkManager().update(ctx_for(rim, tmp_path))
    calls = rim.called("set_pawn_work_priority")
    assert {(c["pawn_id"], c["work_type_def_name"], c["priority"]) for c in calls} == {
        ("HumanC", "Growing", 3), ("HumanC", "PlantCutting", 3), ("HumanC", "Mining", 3)}


def test_nothing_to_do_when_everything_is_on(tmp_path):
    rim = FakeRim()
    manager = WorkManager()
    switch(rim, "HumanA", "Doctor", active=False, priority=0)
    manager.update(ctx_for(rim, tmp_path))
    manager.update(ctx_for(rim, tmp_path))  # running twice does no harm
    assert len(rim.called("set_pawn_work_priority")) == 1


def test_a_refusal_is_a_warning(tmp_path):
    rim = FakeRim()
    entry = next(w for w in rim.work["HumanB"] if w["defName"] == "Art")
    entry.update(active=False, priority=0)
    real = rim.set_pawn_work_priority

    def refuse(pawn_id, work_type, **kw):
        entry["disabled"] = True  # the game knows better than the listing did
        return real(pawn_id, work_type, **kw)

    rim.set_pawn_work_priority = refuse
    ctx = ctx_for(rim, tmp_path)
    WorkManager().update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("workRefused", "warn")]
