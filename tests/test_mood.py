from rimagent import Context, Event, Snapshot
from rimagent.journal import Journal
from rimagent.managers.mood import MoodManager

from .fakegame import FakeRim


def break_event(state_label: str) -> Event:
    return Event("mentalBreak", 37266, "run", state_label, {"id": "HumanA", "name": "A"})


def context(rim: FakeRim, tmp_path) -> Context:
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def test_a_harmless_break_is_waited_out(tmp_path):
    rim = FakeRim()
    rim.colonists[0]["mentalState"] = "Wander_Sad"  # as list_pawns reports it
    assert MoodManager().on_event(context(rim, tmp_path), break_event("Sad wandering")) is True
    assert rim.called("set_pawn_drafted") == []


def test_a_break_already_over_is_handled(tmp_path):
    rim = FakeRim()
    assert MoodManager().on_event(context(rim, tmp_path), break_event("Sad wandering")) is True


def test_a_dangerous_break_is_left_unhandled(tmp_path):
    rim = FakeRim()
    rim.colonists[0]["mentalState"] = "Berserk"
    assert MoodManager().on_event(context(rim, tmp_path), break_event("Berserk")) is False


def test_break_risk_alerts_are_claimed_but_not_extreme():
    assert {"Alert_MinorBreakRisk", "Alert_MajorBreakRisk"} <= set(MoodManager.alerts)
    assert "Alert_ExtremeBreakRisk" not in MoodManager.alerts


def placed(rim: FakeRim, def_: str) -> list[dict]:
    return [p for call in rim.called("place_blueprint") for p in call["placements"] if p["def"] == def_]


def test_a_table_and_a_chair_per_colonist_are_planned_once(tmp_path):
    rim = FakeRim()
    MoodManager().update(context(rim, tmp_path))
    (table,) = placed(rim, "Table2x2c")
    chairs = placed(rim, "DiningChair")
    assert len(chairs) == 3
    table_cells = {(table["x"] + i, table["z"] + j) for i in (0, 1) for j in (0, 1)}
    for c in chairs:  # each chair beside the table, not on it
        assert (c["x"], c["z"]) not in table_cells
        assert min(abs(c["x"] - tx) + abs(c["z"] - tz) for tx, tz in table_cells) == 1

    # Next pass, still unbuilt: the same spots again, so nothing new is planned.
    rim.calls.clear()
    MoodManager().update(context(rim, tmp_path))
    assert len(rim.blueprints) == 4
    assert placed(rim, "Table2x2c") == [table]


def test_chairs_follow_the_built_table(tmp_path):
    rim = FakeRim()
    MoodManager().update(context(rim, tmp_path))
    rim.build_blueprints()
    rim.calls.clear()
    MoodManager().update(context(rim, tmp_path))
    assert rim.called("place_blueprint") == []  # all three seated

    rim.colonists.append({**rim.colonists[0], "ids": {"id": "HumanD"}, "name": "D"})
    MoodManager().update(context(rim, tmp_path))
    (chair,) = placed(rim, "DiningChair")
    table = next(b for b in rim.buildings if b["def"]["defName"] == "Table2x2c")["position"]
    assert placed(rim, "Table2x2c") == []
    assert abs(chair["x"] - table["x"]) <= 2 and abs(chair["z"] - table["z"]) <= 2


def test_a_blocked_seat_gives_way_to_the_next(tmp_path):
    rim = FakeRim()
    MoodManager().update(context(rim, tmp_path))
    rim.build_blueprints()
    table = next(b for b in rim.buildings if b["def"]["defName"] == "Table2x2c")["position"]
    rim.colonists.append({**rim.colonists[0], "ids": {"id": "HumanD"}, "name": "D"})
    rim.cells[(table["x"] + 2, table["z"])] = "t"  # a tree where the fourth seat would go
    rim.calls.clear()
    MoodManager().update(context(rim, tmp_path))
    assert len(rim.called("place_blueprint")) == 2
    assert len([b for b in rim.blueprints if b["def"] == "DiningChair"]) == 1


def test_colonists_at_risk_have_their_worst_thoughts_logged(tmp_path):
    rim = FakeRim()
    rim.colonists[0]["mood"] = {"level": 0.47, "thoughts": [  # as get_pawn reports them
        {"defName": "Catharsis", "label": "Catharsis", "moodOffset": 40},
        {"defName": "SleptOutside", "label": "Slept outside", "moodOffset": -4},
        {"defName": "AteWithoutTable", "label": "Ate without table", "moodOffset": -3},
    ]}
    rim.alerts = [{"type": "Alert_MinorBreakRisk", "label": "Minor break risk", "priority": "High",
                   "culprits": [{"id": "HumanA", "label": "A"}], "culpritCount": 1}]
    ctx = context(rim, tmp_path)
    MoodManager().update(ctx)
    lines = (tmp_path / "j.jsonl").read_text()
    assert "Slept outside -4" in lines and "Ate without table -3" in lines and "Catharsis" not in lines
