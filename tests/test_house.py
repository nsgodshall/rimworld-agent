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


def test_a_door_opening_onto_a_wall_is_moved(tmp_path):
    """Run 20261029-074313: the house's south door opened onto an ancient wall; Sparky starved inside."""
    rim = FakeRim()
    for x in range(39, 49):
        rim.cells[(x, 39)] = "#"  # the ancient wall along the south side
    ring = [(x, z) for x in range(40, 47) for z in range(40, 46) if x in (40, 46) or z in (40, 45)]
    for x, z in ring:
        rim.cells[(x, z)] = "#"
        if (x, z) != (43, 40):
            rim.buildings.append({"ids": {"id": f"Wall_{x}_{z}"}, "def": {"defName": "Wall"},
                                  "position": {"x": x, "y": 0, "z": z}})
    house = HouseManager()
    house.memory.update({"house": {"outer": [40, 40, 7, 6], "beds": 3}, "built": True})

    house.update(ctx_for(rim, tmp_path))
    assert house.memory["house"]["door"] == [46, 43]  # mid-east, open ground outside
    assert rim.called("designate") == [{"kind": "deconstruct", "thing_ids": ["Wall_46_43"]}]
    assert rim.called("place_blueprint") == []

    # The wall comes down: the door goes in its place, once.
    rim.buildings = [b for b in rim.buildings if b["ids"]["id"] != "Wall_46_43"]
    rim.cells[(46, 43)] = "."
    rim.calls = []
    house.update(ctx_for(rim, tmp_path))
    house.update(ctx_for(rim, tmp_path))
    first, _ = rim.called("place_blueprint")
    assert first["placements"] == [{"def": "Door", "stuff": "WoodLog", "x": 46, "z": 43, "rotation": "north"}]
    assert len(rim.blueprints) == 1 and house.memory["house"]["door"] == [46, 43]


def test_a_house_shut_in_on_every_side_halts(tmp_path):
    from .fakegame import grid
    rim = FakeRim(cells=grid(100, 100, "^"))
    house = HouseManager()
    house.memory.update({"house": {"outer": [40, 40, 7, 6], "beds": 3}, "built": True})
    ctx = ctx_for(rim, tmp_path)
    house.update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("houseSealed", "halt")]
