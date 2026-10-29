from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers.beds import BedsManager
from rimagent.managers.food import FoodManager
from rimagent.managers.house import HouseManager, plan
from rimagent.managers.materials import pick

from .fakegame import FakeRim, grid


def ctx_for(rim, tmp_path, board=None):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False), board=board if board is not None else {})


def colony():
    rim = FakeRim()
    rim.resources = [{"defName": "WoodLog", "count": 2000}, {"defName": "Steel", "count": 500}]
    return rim


def test_every_bedroom_is_closed_with_its_own_door_and_bed():
    p = plan((10, 10), 3)
    solid = set(p["walls"]) | set(p["doors"])
    assert len(p["doors"]) == 4 and all(z == 10 for _, z in p["doors"])  # all in the south wall
    for room in [p["common"], *p["bedrooms"]]:
        cells = set(room.cells())
        ring = {(x + dx, z + dz) for x, z in cells for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))} - cells
        assert ring <= solid, f"{room} isn't enclosed"
        assert len(ring & set(p["doors"])) == 1, f"{room} needs exactly one door"
    for room, (bx, bz) in zip(p["bedrooms"], p["beds"]):
        assert {(bx, bz), (bx, bz - 1)} <= set(room.cells())  # both cells of a south-facing bed
    furniture = [p["table"], (p["table"][0] + 1, p["table"][1]), *p["chairs"], p["horseshoes"], p["chess"], *p["lamps"]]
    assert len(set(furniture)) == len(furniture) and not set(furniture) & solid
    door_inside = [(x, z + 1) for x, z in p["doors"]]
    assert not set(door_inside) & set(furniture + p["beds"])  # nothing blocks a doorway


def test_planned_once_placed_until_built_then_left_alone(tmp_path):
    rim = colony()
    FoodManager().update(ctx_for(rim, tmp_path))
    house, board = HouseManager(), {}
    house.update(ctx_for(rim, tmp_path, board))
    first = [p for c in rim.called("place_blueprint") for p in c["placements"]]
    house.update(ctx_for(rim, tmp_path, board))
    second = [p for c in rim.called("place_blueprint") for p in c["placements"]][len(first):]
    assert first == second and board["house_beds"] == 3
    assert {p["def"] for p in first} == {"Bed", "Table2x2c", "DiningChair"}  # beds come first
    for _ in range(3):  # each stage built, then the next placed
        rim.build_blueprints()
        house.update(ctx_for(rim, tmp_path, board))
    assert house.memory["built"]
    calls = len(rim.called("place_blueprint"))
    house.update(ctx_for(rim, tmp_path, board))
    assert len(rim.called("place_blueprint")) == calls


def test_the_doorstep_row_is_free_ground(tmp_path):
    rim = colony()
    FoodManager().update(ctx_for(rim, tmp_path))
    house = HouseManager()
    house.update(ctx_for(rim, tmp_path))
    x0, z0 = house.memory["house"]["origin"]
    p = plan((x0, z0), 3)
    assert all(rim.cells[(x, z0 - 1)] == "." for x in range(x0, x0 + p["outer"].width))


def test_each_colonist_gets_their_own_bedroom_and_outdoor_beds_come_down(tmp_path):
    rim = colony()
    FoodManager().update(ctx_for(rim, tmp_path))
    BedsManager().update(ctx_for(rim, tmp_path))  # day-one beds outdoors (no house yet)
    rim.build_blueprints()
    outdoor = {b["id"] for b in rim.beds}
    house, board = HouseManager(), {}
    house.update(ctx_for(rim, tmp_path, board))
    rim.build_blueprints()
    house.update(ctx_for(rim, tmp_path, board))
    indoor = {b["id"] for b in rim.beds} - outdoor
    assert set(rim.owners) == indoor and sorted(rim.owners.values()) == ["HumanA", "HumanB", "HumanC"]
    (deconstruct,) = [c for c in rim.called("designate") if c["kind"] == "deconstruct"]
    assert set(deconstruct["thing_ids"]) == outdoor
    house.update(ctx_for(rim, tmp_path, board))
    assert len(rim.called("assign_owner")) == 3 and len(rim.called("designate")) == 1  # nothing repeated


def test_the_beds_manager_leaves_beds_to_the_house(tmp_path):
    rim = colony()
    FoodManager().update(ctx_for(rim, tmp_path))
    board = {}
    HouseManager().update(ctx_for(rim, tmp_path, board))
    rim.calls = []
    BedsManager().update(ctx_for(rim, tmp_path, board))
    assert rim.called("place_blueprint") == []


def test_walls_are_steel_when_wood_is_short(tmp_path):
    """Trial 6: 37 wood, 1,065 steel, and the house's last wall waited days for wood."""
    rim = colony()
    rim.resources = [{"defName": "WoodLog", "count": 37}, {"defName": "Steel", "count": 1065}]
    FoodManager().update(ctx_for(rim, tmp_path))
    house = HouseManager()
    house.update(ctx_for(rim, tmp_path))
    rim.build_blueprints()  # the first stage: beds, table, chairs
    house.update(ctx_for(rim, tmp_path))
    walls = [p for c in rim.called("place_blueprint") for p in c["placements"] if p["def"] in ("Wall", "Door")]
    assert walls
    assert {p["stuff"] for p in walls} == {"Steel"}
    assert pick(ctx_for(rim, tmp_path), 10_000) == "Steel"  # nothing has enough: the larger stock


def test_a_house_over_50_placements_goes_in_batches(tmp_path):
    """The live game refuses more than 50 placements per call; a 3-bedroom house is more."""
    rim = colony()
    FoodManager().update(ctx_for(rim, tmp_path))
    house = HouseManager()
    house.update(ctx_for(rim, tmp_path))
    rim.build_blueprints()  # beds, table, chairs
    rim.calls = []
    ctx = ctx_for(rim, tmp_path)
    house.update(ctx)
    calls = rim.called("place_blueprint")
    assert len(calls) > 2 and all(len(c["placements"]) <= 50 for c in calls)
    assert not ctx.incidents and len(rim.blueprints) == len(plan((0, 0), 3)["walls"]) + 4  # the walls and doors


def test_no_free_ground_is_a_warning(tmp_path):
    rim = FakeRim(cells=grid(100, 100, "~"))
    ctx = ctx_for(rim, tmp_path)
    HouseManager().update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("noHouseSite", "warn")]
