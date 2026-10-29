from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers.pantry import HUNT_AT_ONCE, PantryManager

from .fakegame import FakeRim


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def meal(n, x, z, count=1):
    # As find_things shows a stack outside storage (run 20261029-074313).
    return {"id": f"MealSurvivalPack{n}", "def": "MealSurvivalPack", "label": "Packaged survival meal",
            "x": x, "z": z, "count": count, "forbidden": False, "inStorage": False}


def animal(def_, n, x, z):
    return {"ids": {"id": f"{def_}{n}"}, "def": {"defName": def_}, "role": "wildAnimal",
            "dead": False, "downed": False, "position": {"x": x, "y": 0, "z": z}}


def colony(food_days):
    rim = FakeRim()
    rim.zones = [{"id": "zone:0:0", "kind": "stockpile", "cellCount": 36}]
    rim.food = {"eatenPerDay": 5.6, "daysLeft": food_days}
    return rim


def test_loose_food_is_marked_for_hauling(tmp_path):
    rim = colony(food_days=6.0)
    rim.loose_food = [meal(1, 52, 50, 10), meal(2, 20, 90, 2)]
    PantryManager().update(ctx_for(rim, tmp_path))
    assert rim.called("designate") == [{"kind": "haul", "thing_ids": ["MealSurvivalPack1", "MealSurvivalPack2"]}]
    assert rim.called("choose_pawn_action") == []  # plenty in store: no need to pull anyone off their work


def test_critical_food_gets_hauled_now_by_awake_colonists(tmp_path):
    """The incident: 0.3 days stored, 10 meals three cells from the stockpile, nobody hauling."""
    rim = colony(food_days=0.3)
    rim.loose_food = [meal(1, 52, 50, 10), meal(2, 20, 90, 2), meal(3, 90, 10)]
    rim.colonists[0]["currentJob"] = {"defName": "LayDown", "label": "LayDown", "report": "resting."}
    rim.colonists[1]["position"] = {"x": 21, "y": 0, "z": 89}
    PantryManager().update(ctx_for(rim, tmp_path))

    orders = rim.called("choose_pawn_action")
    # Two stacks, each by a different awake colonist, the nearest one taking the far stack; the sleeper is left be.
    assert [(o["target_id"], o["option"]) for o in orders] == [("MealSurvivalPack1", "2"), ("MealSurvivalPack2", "2")]
    assert {o["pawn_id"] for o in orders} == {"HumanB", "HumanC"}
    assert orders[1]["pawn_id"] == "HumanB"


def test_low_food_alert_is_claimed_and_rushes_hauling(tmp_path):
    """Incident 004: Alert_LowFood showed 14h at 3 days stored, harvested rice lying in the field."""
    assert "Alert_LowFood" in PantryManager.alerts
    rim = colony(food_days=3.0)
    rim.loose_food = [{**meal(1, 52, 50, 12), "id": "RawRice1", "def": "RawRice", "label": "Rice"}]
    rim.alerts = [{"type": "Alert_LowFood", "label": "Low food", "priority": "High"}]
    PantryManager().update(ctx_for(rim, tmp_path))
    assert [o["target_id"] for o in rim.called("choose_pawn_action")] == ["RawRice1"]


def test_no_rush_while_hostiles_are_on_the_map(tmp_path):
    rim = colony(food_days=0.3)
    rim.loose_food = [meal(1, 52, 50, 10)]
    rim.threats = [{"threatKind": "hostile"}]
    PantryManager().update(ctx_for(rim, tmp_path))
    assert rim.called("designate") and not rim.called("choose_pawn_action")


def test_short_food_marks_the_nearest_safe_game_for_hunting(tmp_path):
    rim = colony(food_days=3.0)
    rim.animals = [animal("Boomalope", 1, 51, 51), animal("WildBoar", 2, 50, 52), animal("Alpaca", 3, 60, 60),
                   animal("Ibex", 4, 55, 50), animal("Hare", 5, 90, 90)]
    pantry = PantryManager()
    pantry.update(ctx_for(rim, tmp_path))
    assert rim.hunting == {"Ibex4", "Alpaca3"}

    # Still hunting them: nothing more is marked.
    pantry.update(ctx_for(rim, tmp_path))
    assert len(rim.called("designate_animal")) == HUNT_AT_ONCE

    # One is shot: the next nearest takes its place.
    rim.animals = [a for a in rim.animals if a["ids"]["id"] != "Ibex4"]
    pantry.update(ctx_for(rim, tmp_path))
    assert rim.called("designate_animal")[-1] == {"pawn_id": "Hare5", "action": "hunt"}


def test_no_hunting_with_food_in_store(tmp_path):
    rim = colony(food_days=8.0)
    rim.animals = [animal("Alpaca", 1, 55, 55)]
    PantryManager().update(ctx_for(rim, tmp_path))
    assert rim.called("designate_animal") == []


def starving(rim, pawn_id):
    # As get_events shows it (run 20261029-074313, incident 002).
    rim.alerts = [{"type": "Alert_StarvationColonists", "label": "Starvation", "priority": "High",
                   "culprits": [{"id": pawn_id, "label": pawn_id, "mapId": "0"}], "culpritCount": 1}]


def test_a_starving_colonist_is_told_to_eat(tmp_path):
    rim = colony(food_days=6.0)
    rim.stored_food = [{**meal(1, 52, 50, 7), "inStorage": True}]
    starving(rim, "HumanB")
    PantryManager().update(ctx_for(rim, tmp_path))
    assert [(o["pawn_id"], o["target_id"], o["option"]) for o in rim.called("choose_pawn_action")] == \
        [("HumanB", "MealSurvivalPack1", "1")]


def test_a_starving_colonist_with_no_path_to_food_warns_then_halts(tmp_path):
    rim = colony(food_days=6.0)
    rim.stored_food = [{**meal(1, 52, 50, 7), "inStorage": True}]
    rim.no_path = {"HumanB"}
    starving(rim, "HumanB")
    pantry = PantryManager()
    ctx = ctx_for(rim, tmp_path)
    pantry.update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("trapped", "warn")]
    rim.tick += 12 * 2500
    ctx = ctx_for(rim, tmp_path)
    pantry.update(ctx)
    assert ctx.incidents == []  # time for the way out (the house manager moves a blocked door)
    rim.tick += 12 * 2500
    ctx = ctx_for(rim, tmp_path)
    pantry.update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("trapped", "halt")]
    assert rim.called("choose_pawn_action") == []
    # Out and fed: forgotten.
    rim.alerts = []
    pantry.update(ctx_for(rim, tmp_path))
    assert pantry.memory["trapped"] == {}
