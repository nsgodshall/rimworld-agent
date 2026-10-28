from rimagent import Context, Runtime, Snapshot
from rimagent.journal import Journal
from rimagent.managers.food import FoodManager
from rimagent.managers.kitchen import KitchenManager

from .fakegame import FakeRim, grid


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def test_a_stove_is_planned_beside_the_stockpile(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    KitchenManager().update(ctx_for(rim, tmp_path))

    (call,) = rim.called("place_blueprint")
    (stove,) = call["placements"]
    assert stove["def"] == "FueledStove" and stove["rotation"] == "north"
    stockpile = rim.zones[0]["representativeCell"]
    assert abs(stove["x"] - stockpile["x"]) <= 10 and abs(stove["z"] - stockpile["z"]) <= 10
    # Not on the stockpile: the footprint and interaction cell were open ground.
    assert len(rim.blueprints) == 1


def test_a_planned_stove_is_not_placed_twice(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    KitchenManager().update(ctx_for(rim, tmp_path))
    KitchenManager().update(ctx_for(rim, tmp_path))
    first, second = rim.called("place_blueprint")
    assert first == second and len(rim.blueprints) == 1


def test_campfire_when_no_stove_can_be_built(tmp_path):
    rim = FakeRim()
    rim.unavailable = {"FueledStove"}
    FoodManager().update(ctx_for(rim, tmp_path))
    KitchenManager().update(ctx_for(rim, tmp_path))
    (call,) = rim.called("place_blueprint")
    assert call["placements"][0]["def"] == "Campfire"


def test_a_built_stove_gets_one_cooking_bill(tmp_path):
    rim = FakeRim()
    rim.buildings = [{"ids": {"id": "FueledStove7"}, "def": {"defName": "FueledStove"}}]
    KitchenManager().update(ctx_for(rim, tmp_path))
    KitchenManager().update(ctx_for(rim, tmp_path))
    (bill,) = rim.called("add_bill_to_workshop")
    assert bill["workshop_id"] == "FueledStove7" and bill["recipe_def_name"] == "CookMealSimple"
    assert bill["repeat_mode_def_name"] == "TargetCount" and bill["target_count"] == 30
    assert rim.called("place_blueprint") == []


def test_no_room_is_a_warning(tmp_path):
    rim = FakeRim(cells=grid(100, 100, "^"))
    ctx = ctx_for(rim, tmp_path)
    KitchenManager().update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("noSite", "warn")]
    assert rim.called("place_blueprint") == []


def test_need_meal_source_alert_no_longer_halts(tmp_path):
    rim = FakeRim()
    rim.alerts = [{"type": "Alert_NeedMealSource", "label": "Need meal source", "priority": "Medium"}]
    rt = Runtime(rim, tmp_path / "run", managers=[KitchenManager()], tripwires=[], echo=False)
    assert rt.run(24) == "done"
