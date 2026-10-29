from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers.beds import BedsManager
from rimagent.managers.food import FoodManager
from rimagent.managers.house import HouseManager

from .fakegame import FakeRim


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def placed(rim):
    (call, *_) = rim.called("place_blueprint")
    return call["placements"]


def test_a_walled_room_with_a_door_and_a_bed_each(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    rim.calls = []
    HouseManager().update(ctx_for(rim, tmp_path))
    plan = placed(rim)
    walls = {(p["x"], p["z"]) for p in plan if p["def"] in ("Wall", "Door")}
    beds = [p for p in plan if p["def"] == "Bed"]
    assert sum(p["def"] == "Door" for p in plan) == 1 and len(beds) == 3
    xs, zs = [x for x, _ in walls], [z for _, z in walls]
    # Walls are the whole ring of a 7x6 rect: an enclosed room.
    assert (max(xs) - min(xs) + 1, max(zs) - min(zs) + 1) == (7, 6) and len(walls) == 2 * 7 + 2 * 4
    for b in beds:  # inside, both cells
        assert min(xs) < b["x"] < max(xs) and min(zs) < b["z"] - 1 and b["z"] < max(zs)


def test_planned_once_then_repeated_in_place_until_built(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    rim.calls = []
    house = HouseManager()
    house.update(ctx_for(rim, tmp_path))
    house.update(ctx_for(rim, tmp_path))
    first, second = rim.called("place_blueprint")
    assert first["placements"] == second["placements"]
    assert len(rim.blueprints) == 22 + 3


def test_once_built_colonists_get_indoor_beds_and_outdoor_ones_come_down(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    BedsManager().update(ctx_for(rim, tmp_path))
    rim.build_blueprints()  # the day-one beds outdoors
    house = HouseManager()
    house.update(ctx_for(rim, tmp_path))
    assert rim.called("assign_owner") == []  # nothing indoors yet
    rim.build_blueprints()
    rim.calls = []
    house.update(ctx_for(rim, tmp_path))
    assert rim.called("place_blueprint") == []  # built: no more placing
    indoor = {b["id"] for b in rim.beds[3:]}
    assert set(rim.owners) == indoor and set(rim.owners.values()) == {"HumanA", "HumanB", "HumanC"}
    (deconstruct,) = rim.called("designate")
    assert deconstruct["kind"] == "deconstruct" and set(deconstruct["thing_ids"]) == {b["id"] for b in rim.beds[:3]}
    house.update(ctx_for(rim, tmp_path))
    assert len(rim.called("assign_owner")) == 3  # not assigned again


def test_no_free_ground_is_a_warning(tmp_path):
    from .fakegame import grid
    rim = FakeRim(cells=grid(100, 100, "t"))
    ctx = ctx_for(rim, tmp_path)
    HouseManager().update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("noHouseSite", "warn")]
