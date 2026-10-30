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

    call, _butcher = rim.called("place_blueprint")
    (stove,) = call["placements"]
    assert stove["def"] == "FueledStove" and stove["rotation"] == "north"
    stockpile = rim.zones[0]["representativeCell"]
    assert abs(stove["x"] - stockpile["x"]) <= 10 and abs(stove["z"] - stockpile["z"]) <= 10
    # Not on the stockpile: the footprint and interaction cell were open ground.
    assert [b["def"] for b in rim.blueprints] == ["FueledStove", "ButcherSpot"]


def test_a_planned_stove_is_not_placed_twice(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    KitchenManager().update(ctx_for(rim, tmp_path))
    KitchenManager().update(ctx_for(rim, tmp_path))
    # Fresh managers, as after a restart: the stove's blueprint is found on the map, not in memory.
    stove, _butcher, stove_again, _butcher_again = rim.called("place_blueprint")
    assert stove == stove_again and [b["def"] for b in rim.blueprints].count("FueledStove") == 1


def test_a_planned_butcher_spot_is_not_placed_twice(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    kitchen = KitchenManager()
    kitchen.update(ctx_for(rim, tmp_path))
    kitchen.update(ctx_for(rim, tmp_path))
    _stove, butcher, _stove_again, butcher_again = rim.called("place_blueprint")
    assert butcher == butcher_again and [b["def"] for b in rim.blueprints] == ["FueledStove", "ButcherSpot"]


def test_campfire_when_no_stove_can_be_built(tmp_path):
    rim = FakeRim()
    rim.unavailable = {"FueledStove"}
    FoodManager().update(ctx_for(rim, tmp_path))
    KitchenManager().update(ctx_for(rim, tmp_path))
    call, _butcher = rim.called("place_blueprint")
    assert call["placements"][0]["def"] == "Campfire"


def test_a_built_stove_gets_one_cooking_bill(tmp_path):
    rim = FakeRim()
    rim.buildings = [{"ids": {"id": "FueledStove7"}, "def": {"defName": "FueledStove"}},
                     {"ids": {"id": "ButcherSpot8"}, "def": {"defName": "ButcherSpot"}}]
    KitchenManager().update(ctx_for(rim, tmp_path))
    KitchenManager().update(ctx_for(rim, tmp_path))
    bill, butchering = rim.called("add_bill_to_workshop")
    assert bill["workshop_id"] == "FueledStove7" and bill["recipe_def_name"] == "CookMealSimple"
    assert bill["repeat_mode_def_name"] == "TargetCount" and bill["target_count"] == 30
    assert butchering["workshop_id"] == "ButcherSpot8"
    assert rim.called("place_blueprint") == []


def test_hunted_corpses_get_a_butcher_spot_and_a_forever_bill(tmp_path):
    # Run 20261029-114409: ~25 kills lay where they fell and stored food hit 0, as nothing could butcher them.
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    rim.buildings = [{"ids": {"id": "FueledStove7"}, "def": {"defName": "FueledStove"}}]
    rim.bills = [{"id": "Bill_CookMealSimple_0", "recipe": {"defName": "CookMealSimple"},
                  "workbench": {"ids": {"id": "FueledStove7"}}, "state": "active"}]
    kitchen = KitchenManager()
    kitchen.update(ctx_for(rim, tmp_path))
    (call,) = rim.called("place_blueprint")
    (spot,) = call["placements"]
    assert spot["def"] == "ButcherSpot"
    assert rim.called("add_bill_to_workshop") == []  # not until it's built

    rim.build_blueprints()
    kitchen.update(ctx_for(rim, tmp_path))
    kitchen.update(ctx_for(rim, tmp_path))
    (bill,) = rim.called("add_bill_to_workshop")
    assert bill["recipe_def_name"] == "ButcherCorpseFlesh" and bill["repeat_mode_def_name"] == "Forever"
    assert bill["workshop_id"].startswith("ButcherSpot")
    assert len(rim.called("place_blueprint")) == 1


def test_the_butcher_spot_is_not_put_on_the_stoves_blueprint(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    kitchen = KitchenManager()
    kitchen.update(ctx_for(rim, tmp_path))
    kitchen.update(ctx_for(rim, tmp_path))
    stove, butcher = rim.blueprints
    stove_cells = {(stove["x"] + dx, stove["z"]) for dx in (-1, 0, 1)}
    assert (butcher["x"], butcher["z"]) not in stove_cells


def test_no_room_is_a_warning(tmp_path):
    rim = FakeRim(cells=grid(100, 100, "^"))
    ctx = ctx_for(rim, tmp_path)
    KitchenManager().update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("noSite", "warn"), ("noSite", "warn")]
    assert rim.called("place_blueprint") == []


def test_need_meal_source_alert_no_longer_halts(tmp_path):
    rim = FakeRim()
    rim.alerts = [{"type": "Alert_NeedMealSource", "label": "Need meal source", "priority": "Medium"}]
    rt = Runtime(rim, tmp_path / "run", managers=[KitchenManager()], tripwires=[], echo=False)
    assert rt.run(24) == "done"


def test_a_stockpile_for_fresh_animal_corpses_beside_the_butcher_spot(tmp_path):
    """Trial 9: 31 kills lay where they fell and rotted ("Observed rotting corpse", -6)."""
    rim = FakeRim()
    rim.buildings = [{"ids": {"id": "Campfire1"}, "def": {"defName": "Campfire"}, "position": {"x": 50, "y": 0, "z": 50}},
                     {"ids": {"id": "ButcherSpot8"}, "def": {"defName": "ButcherSpot"}, "position": {"x": 55, "y": 0, "z": 50}}]
    kitchen = KitchenManager()
    kitchen.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    (zone,) = [c for c in rim.called("set_zone") if c["kind"] == "stockpile"]
    (storage,) = rim.called("set_storage")
    assert storage["disallow_all"] and storage["allow"] == ["CorpsesAnimal"] and storage["disallow"] == ["AllowRotten"]
    x, z = zone["add"][0]["x"], zone["add"][0]["z"]
    assert abs(x - 55) <= 6 and abs(z - 50) <= 6
    kitchen.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    fresh, dump = rim.called("set_storage")  # the second pass adds the dump for rotten ones
    assert dump["priority"] == "Low" and dump["allow"] == ["Corpses", "AllowRotten", "Chunks"]
    (_, dump_zone) = [c for c in rim.called("set_zone") if c["kind"] == "stockpile"]
    assert abs(dump_zone["add"][0]["z"] - 50) >= 15  # out of sight of the base
    kitchen.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    assert len(rim.called("set_storage")) == 2  # each made once


def test_the_butcher_spot_is_away_from_the_house(tmp_path):
    """Trials 20-21: corpses and blood by the butcher spot sat at the house's doorsteps."""
    import math

    rim = FakeRim()
    FoodManager().update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    KitchenManager().update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    (spot,) = [p for c in rim.called("place_blueprint") for p in c["placements"] if p["def"] == "ButcherSpot"]
    cell = rim.zones[0]["representativeCell"]
    assert math.hypot(spot["x"] - cell["x"], spot["z"] - cell["z"]) >= 7 and spot["z"] < cell["z"]


def test_a_fine_meal_bill_once_someone_cooks_well(tmp_path):
    rim = FakeRim()
    rim.buildings = [{"ids": {"id": "Campfire1"}, "def": {"defName": "Campfire"}, "position": {"x": 50, "y": 0, "z": 50}},
                     {"ids": {"id": "ButcherSpot8"}, "def": {"defName": "ButcherSpot"}, "position": {"x": 55, "y": 0, "z": 40}}]
    kitchen = KitchenManager()
    kitchen.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    assert "CookMealFine" not in [c["recipe_def_name"] for c in rim.called("add_bill_to_workshop")]
    rim.colonists[1]["skills"] = [{"defName": "Cooking", "label": "Cooking", "level": 7, "passion": "None"}]
    kitchen.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    fine = [c for c in rim.called("add_bill_to_workshop") if c["recipe_def_name"] == "CookMealFine"]
    assert len(fine) == 1 and fine[0]["workshop_id"] == "Campfire1"
