from rimagent import Context, Runtime, Snapshot
from rimagent.journal import Journal
from rimagent.managers.beds import BedsManager
from rimagent.managers.food import FoodManager

from .fakegame import FakeRim, grid


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def test_a_bed_per_colonist_beside_the_stockpile(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    BedsManager().update(ctx_for(rim, tmp_path))

    (call,) = rim.called("place_blueprint")
    beds = call["placements"]
    assert len(beds) == 3
    assert all(b["def"] == "Bed" and b["rotation"] == "south" for b in beds)
    stockpile = rim.zones[0]["representativeCell"]
    assert all(abs(b["x"] - stockpile["x"]) <= 10 and abs(b["z"] - stockpile["z"]) <= 10 for b in beds)
    assert len(rim.blueprints) == 3


def test_pending_blueprints_are_not_placed_again(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    beds = BedsManager()
    beds.update(ctx_for(rim, tmp_path))
    beds.update(ctx_for(rim, tmp_path))
    assert len(rim.called("place_blueprint")) == 1


def test_half_built_beds_are_counted_once(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    beds = BedsManager()
    beds.update(ctx_for(rim, tmp_path))
    rim.build_blueprints(1)  # one built, two still blueprints
    beds.update(ctx_for(rim, tmp_path))
    rim.build_blueprints()
    beds.update(ctx_for(rim, tmp_path))
    assert len(rim.called("place_blueprint")) == 1 and len(rim.beds) == 3


def test_rejected_blueprints_are_reported(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    real = rim.place_blueprint
    def refuse(**kw):
        result = real(**kw)
        result.data["results"][0].update(outcome="rejected", reason="Space already occupied.")
        return result
    rim.place_blueprint = refuse
    ctx = ctx_for(rim, tmp_path)
    BedsManager().update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("bedsRejected", "warn")]


def test_only_missing_beds_are_added(tmp_path):
    rim = FakeRim()
    rim.beds = [{"id": "Bed1", "position": {"x": 0, "y": 0, "z": 0}}, {"id": "Bed2", "position": {"x": 1, "y": 0, "z": 0}}]
    BedsManager().update(ctx_for(rim, tmp_path))
    (call,) = rim.called("place_blueprint")
    assert len(call["placements"]) == 1


def test_no_room_is_a_warning(tmp_path):
    rim = FakeRim(cells=grid(100, 100, "^"))
    ctx = ctx_for(rim, tmp_path)
    BedsManager().update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("noSite", "warn")]
    assert rim.called("place_blueprint") == []


def test_need_beds_alert_no_longer_halts(tmp_path):
    rim = FakeRim()
    rim.alerts = [{"type": "Alert_NeedColonistBeds", "label": "Need colonist beds", "priority": "High"}]
    rt = Runtime(rim, tmp_path / "run", managers=[BedsManager()], tripwires=[], echo=False)
    assert rt.run(24) == "done"


def test_other_blueprints_are_not_taken_for_beds(tmp_path):
    """Trial 2: defense's barricade blueprints were counted as planned beds, so none were placed."""
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    anchor = rim.zones[0]["representativeCell"]
    for dx in range(-2, 13):
        rim.cells[(anchor["x"] + dx, anchor["z"] + 6)] = "x"  # a barricade line's blueprints
    BedsManager().update(ctx_for(rim, tmp_path))
    (call,) = rim.called("place_blueprint")
    assert len(call["placements"]) == 3


def test_planned_beds_are_remembered_across_a_reload(tmp_path):
    from rimagent.loader import ManagerLoader

    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    loader = ManagerLoader()
    beds = next(m for m in loader.load() if m.name == "beds")
    beds.update(ctx_for(rim, tmp_path))
    reloaded = next(m for m in loader.load([beds]) if m.name == "beds")
    reloaded.update(ctx_for(rim, tmp_path))
    assert len(rim.called("place_blueprint")) == 1
