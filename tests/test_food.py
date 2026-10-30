from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers.food import GROW_CELLS_PER_COLONIST, FoodManager, best_site
from rimsdk.mapview import MapView, Rect

from .fakegame import FakeRim, grid


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def test_best_site_prefers_rich_soil_near_center():
    cells = grid(60, 60, ".")
    for x in range(40, 50):
        for z in range(40, 50):
            cells[(x, z)] = ":"
    view = MapView(cells, {})
    site = best_site(view, (30, 30), 10, 10, good=".:", bonus=":")
    assert site == Rect(40, 40, 10, 10)
    # Without the bonus, the nearest plain soil wins.
    assert best_site(view, (30, 30), 10, 10, good=".:") == Rect(25, 25, 10, 10)


def test_best_site_rejects_rock():
    view = MapView(grid(20, 20, "^"), {})
    assert best_site(view, (10, 10), 5, 5, good=".") is None


def test_fresh_colony_gets_storage_food_unforbidden_and_a_rice_field(tmp_path):
    rim = FakeRim()
    rim.forbidden_food = ["Meal1", "Meal2"]
    FoodManager().update(ctx_for(rim, tmp_path))

    stockpile, pantry, field = rim.called("set_zone")  # the general stockpile, one for food only, the field
    assert stockpile["kind"] == pantry["kind"] == "stockpile" and field["kind"] == "growing"
    s, p, f = (Rect(**z["add"][0]) for z in (stockpile, pantry, field))
    assert not s.overlaps(f) and not p.overlaps(f) and not s.overlaps(p)
    assert f.area >= GROW_CELLS_PER_COLONIST * 3
    assert rim.called("designate") == [{"kind": "unforbid", "thing_ids": ["Meal1", "Meal2"]}]
    assert rim.called("set_growing_zone")[0]["plant"] == "Plant_Rice"


def test_second_pass_changes_nothing(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    before = len(rim.calls)
    FoodManager().update(ctx_for(rim, tmp_path))
    assert rim.calls[before:] == []


def test_fields_grow_with_the_colony(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    rim.colonists = rim.colonists + [{"name": n, "position": {"x": 50, "y": 0, "z": 50}} for n in ("D", "E")]
    FoodManager().update(ctx_for(rim, tmp_path))
    fields = [z for z in rim.zones if z["kind"] == "growing"]
    assert len(fields) == 2
    assert sum(z["cellCount"] for z in fields) >= GROW_CELLS_PER_COLONIST * 5


def test_no_farmland_is_a_warning_not_a_crash(tmp_path):
    rim = FakeRim(cells=grid(100, 100, "^"))
    ctx = ctx_for(rim, tmp_path)
    FoodManager().update(ctx)
    assert {i.kind for i in ctx.incidents} == {"noSite"}
    assert all(i.severity == "warn" for i in ctx.incidents)


def test_a_food_only_stockpile_beside_the_general_one(tmp_path):
    """Trial 19: the general stockpile filled with everything; 685 food lay outside storage, 203 inside."""
    rim = FakeRim()
    food = FoodManager()
    food.update(ctx_for(rim, tmp_path))
    food.update(ctx_for(rim, tmp_path))
    stockpiles = [c for c in rim.called("set_zone") if c["kind"] == "stockpile"]
    assert len(stockpiles) == 2
    (storage,) = rim.called("set_storage")
    assert storage["priority"] == "Preferred" and storage["disallow_all"] and storage["allow"] == ["Foods"]
    assert rim.zones[0]["id"] != storage["zone_id"]  # the general one stays first: the base's anchor
    food.update(ctx_for(rim, tmp_path))
    assert len(rim.called("set_storage")) == 1
