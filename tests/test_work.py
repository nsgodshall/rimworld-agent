from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers.work import WorkManager

from .fakegame import FakeRim


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def switch(rim, pawn, work_type, **kw):
    next(w for w in rim.work[pawn] if w["defName"] == work_type).update(**kw)


def skilled(rim, pawn, **levels):
    """Skills as get_pawn shows them (fixtures/live/pawn_normal.json): level and passion."""
    rim.pawn(pawn)["skills"] = [{"defName": k, "label": k, "level": v[0] if isinstance(v, tuple) else v,
                                 "passion": v[1] if isinstance(v, tuple) else "None"} for k, v in levels.items()]


def priorities(rim, pawn):
    return {w["defName"]: w["priority"] for w in rim.work[pawn]}


def test_work_switched_off_is_turned_on_and_incapable_work_left_alone(tmp_path):
    """Trial 4: Sparky had only construction on (he can't haul or clean) and stood idle."""
    rim = FakeRim()
    rim.resources = [{"defName": "WoodLog", "count": 400}]
    for w in ("Growing", "PlantCutting", "Mining"):
        switch(rim, "HumanC", w, active=False, priority=0)
    switch(rim, "HumanC", "Hauling", disabled=True, active=False, priority=0)
    WorkManager().update(ctx_for(rim, tmp_path))
    c = priorities(rim, "HumanC")
    assert c["Growing"] == c["PlantCutting"] == c["Mining"] == 3 and c["Hauling"] == 0
    assert not [x for x in rim.called("set_pawn_work_priority")
                if x["work_type_def_name"] == "Hauling" and x["pawn_id"] == "HumanC"]  # incapable: left alone


def test_the_best_researcher_researches_first_and_emergencies_come_before_everything(tmp_path):
    """Trials 1-6 finished no research: it's last in the game's work order."""
    rim = FakeRim()
    skilled(rim, "HumanA", Intellectual=2, Medicine=1)
    skilled(rim, "HumanB", Intellectual=9, Medicine=0)
    skilled(rim, "HumanC", Intellectual=0, Medicine=7)
    WorkManager().update(ctx_for(rim, tmp_path))
    assert priorities(rim, "HumanB")["Research"] == 1 and priorities(rim, "HumanA")["Research"] == 3
    assert priorities(rim, "HumanC")["Doctor"] == 1 and priorities(rim, "HumanA")["Doctor"] == 3
    assert all(priorities(rim, p)["Firefighter"] == priorities(rim, p)["PatientBedRest"] == 1
               for p in ("HumanA", "HumanB", "HumanC"))


def test_passions_come_second(tmp_path):
    rim = FakeRim()
    skilled(rim, "HumanA", Plants=(5, "Major"), Cooking=(8, "None"))
    WorkManager().update(ctx_for(rim, tmp_path))
    a = priorities(rim, "HumanA")
    assert a["Growing"] == a["PlantCutting"] == 2 and a["Cooking"] == 3


def test_short_food_puts_food_work_first_and_plenty_puts_it_back(tmp_path):
    """Run 20261029-114409: 0 days stored, rice ripe and a butcher spot waiting, everyone felling trees."""
    rim = FakeRim()
    skilled(rim, "HumanA", Intellectual=9, Cooking=(2, "Major"))
    rim.food = {"eatenPerDay": 4.8, "daysLeft": 0.0}
    manager = WorkManager()
    manager.update(ctx_for(rim, tmp_path))
    a = priorities(rim, "HumanA")
    assert a["Cooking"] == a["Hunting"] == a["Growing"] == 1 and a["Hauling"] == 2
    assert a["Research"] == 1 and a["Construction"] == 3 and a["Firefighter"] == 1

    rim.food = {"eatenPerDay": 4.8, "daysLeft": 6.0}
    manager.update(ctx_for(rim, tmp_path))
    a = priorities(rim, "HumanA")
    assert a["Cooking"] == 2 and a["Hunting"] == a["Growing"] == 3 and a["Hauling"] == 2  # hauling is always 2


def test_settled_priorities_are_not_set_again(tmp_path):
    rim = FakeRim()
    manager = WorkManager()
    manager.update(ctx_for(rim, tmp_path))
    calls = len(rim.called("set_pawn_work_priority"))
    manager.update(ctx_for(rim, tmp_path))
    assert len(rim.called("set_pawn_work_priority")) == calls


def test_a_refusal_is_a_warning(tmp_path):
    rim = FakeRim()
    entry = next(w for w in rim.work["HumanB"] if w["defName"] == "Art")
    entry.update(active=False, priority=0)
    real = rim.set_pawn_work_priority

    def refuse(pawn_id, work_type, **kw):
        if work_type == "Art":
            entry["disabled"] = True  # the game knows better than the listing did
        return real(pawn_id, work_type, **kw)

    rim.set_pawn_work_priority = refuse
    ctx = ctx_for(rim, tmp_path)
    WorkManager().update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("workRefused", "warn")]


def test_two_evening_hours_of_recreation_once(tmp_path):
    rim = FakeRim()
    manager = WorkManager()
    manager.update(ctx_for(rim, tmp_path))
    manager.update(ctx_for(rim, tmp_path))
    assert len(rim.called("set_pawn_assignment")) == 3
    assert all(rim.schedules[p][19] == rim.schedules[p][21] == "Joy" and rim.schedules[p][18] == "Anything"
               for p in ("HumanA", "HumanB", "HumanC"))


def test_with_no_wood_everyone_fells_trees(tmp_path):
    """Trial 9: walls and the research bench waited at 0 wood while one colonist chopped."""
    rim = FakeRim()
    rim.resources = [{"defName": "WoodLog", "count": 10}]
    WorkManager().update(ctx_for(rim, tmp_path))
    assert all(priorities(rim, p)["PlantCutting"] == 2 for p in ("HumanA", "HumanB", "HumanC"))
    rim.resources = [{"defName": "WoodLog", "count": 400}]
    WorkManager().update(ctx_for(rim, tmp_path))
    assert all(priorities(rim, p)["PlantCutting"] == 3 for p in ("HumanA", "HumanB", "HumanC"))


def test_building_comes_first_while_the_house_is_going_up(tmp_path):
    """Trial 16: the best builder researched (first at equal priority) while everyone slept outside."""
    rim = FakeRim()
    skilled(rim, "HumanB", Intellectual=9)
    WorkManager().update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False), board={"house_stage": 1}))
    assert all(priorities(rim, p)["Construction"] == 1 for p in ("HumanA", "HumanB", "HumanC"))
    assert priorities(rim, "HumanB")["Research"] == 2  # building first; research next
    WorkManager().update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False), board={"house_stage": 3}))
    assert priorities(rim, "HumanA")["Construction"] == 3
