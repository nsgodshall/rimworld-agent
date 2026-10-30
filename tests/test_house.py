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
    cx, cz = p["chess"]
    furniture = [p["table"], (p["table"][0] + 1, p["table"][1]), *p["chairs"], p["horseshoes"], p["chess"], *p["lamps"],
                 *p["end_tables"], *p["pots"], *p["coolers"], (cx, cz - 1), (cx, cz + 1)]
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


def test_hot_rooms_get_a_passive_cooler_each(tmp_path):
    rim = colony()
    FoodManager().update(ctx_for(rim, tmp_path))
    house = HouseManager()
    rim.rooms = [{"role": "Bedroom", "temperatureC": 25.0, "usesOutdoorTemperature": False},
                 {"role": "None", "temperatureC": 35.0, "usesOutdoorTemperature": True}]  # outdoors doesn't count
    house.update(ctx_for(rim, tmp_path))
    placed = lambda: [p for c in rim.called("place_blueprint") for p in c["placements"] if p["def"] == "PassiveCooler"]
    assert placed() == []
    rim.rooms[0]["temperatureC"] = 30.4  # day-7 heat wave
    house.update(ctx_for(rim, tmp_path))
    p = plan(tuple(house.memory["house"]["origin"]), 3)
    assert {(c["x"], c["z"]) for c in placed()} == set(p["coolers"]) and len(placed()) == 4
    rooms = [set(r.cells()) for r in [p["common"], *p["bedrooms"]]]
    assert all(any(xz in cells for xz in p["coolers"]) for cells in rooms)  # one in every room


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
    assert pick(ctx_for(rim, tmp_path), 10_000) == "WoodLog"  # nothing has enough: wood, which can be felled


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


def test_forbidden_steel_doesnt_count(tmp_path):
    """Trial 7: list_resources showed 720 steel, all forbidden in far-off ruins; the steel beds never came."""
    rim = colony()
    rim.resources = [{"defName": "WoodLog", "count": 900}, {"defName": "Steel", "count": 1170, "forbidden": 720}]
    FoodManager().update(ctx_for(rim, tmp_path))
    house = HouseManager()
    house.update(ctx_for(rim, tmp_path))
    assert house.memory["house"]["furniture"] == "WoodLog"  # 450 steel is used up by the walls


def test_no_free_ground_is_a_warning(tmp_path):
    rim = FakeRim(cells=grid(100, 100, "~"))
    ctx = ctx_for(rim, tmp_path)
    HouseManager().update(ctx)
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("noHouseSite", "warn")]


def test_a_stage_stalled_on_a_spent_material_switches_to_the_other(tmp_path):
    """Trial 15: steel beds chosen, the steel spent elsewhere, and two beds waited eleven days."""
    rim = colony()
    rim.resources = [{"defName": "WoodLog", "count": 50}, {"defName": "Steel", "count": 400}]
    FoodManager().update(ctx_for(rim, tmp_path))
    house, board = HouseManager(), {}
    house.update(ctx_for(rim, tmp_path, board))
    assert house.memory["house"]["beds"] == "Steel"
    rim.resources = [{"defName": "WoodLog", "count": 600}, {"defName": "Steel", "count": 0}]  # the steel went elsewhere
    rim.tick += 25 * 2500
    house.update(ctx_for(rim, tmp_path, board))  # first sight of the stall starts its clock...
    rim.tick += 25 * 2500
    house.update(ctx_for(rim, tmp_path, board))  # ...a day later the beds switch
    cancelled = [c for c in rim.called("designate") if c["kind"] == "cancel"]
    assert cancelled and all(i.startswith("Blueprint_Bed") for i in cancelled[0]["thing_ids"])
    overrides = house.memory["house"]["overrides"]
    assert {k for k in overrides if k.startswith("Bed@")} and {v for k, v in overrides.items() if k.startswith("Bed@")} == {"WoodLog"}
    house.update(ctx_for(rim, tmp_path, board))
    beds = [p for p in rim.called("place_blueprint")[-1]["placements"] if p["def"] == "Bed"]
    assert {b["stuff"] for b in beds} == {"WoodLog"} and sum(b["def"] == "Bed" for b in rim.blueprints) == 3


def test_building_the_house_never_replaces_what_stands(tmp_path):
    """Trial 17: after a material switch every built wall got a steel blueprint; they came down and the roof fell."""
    rim = colony()
    FoodManager().update(ctx_for(rim, tmp_path))
    house, board = HouseManager(), {}
    for _ in range(4):
        house.update(ctx_for(rim, tmp_path, board))
        rim.build_blueprints()
    assert house.memory.get("built") and rim.replaced == []


def test_a_material_switch_leaves_built_walls_alone(tmp_path):
    rim = colony()
    rim.resources = [{"defName": "WoodLog", "count": 1000}, {"defName": "Steel", "count": 1000}]
    FoodManager().update(ctx_for(rim, tmp_path))
    house, board = HouseManager(), {}
    house.update(ctx_for(rim, tmp_path, board))
    rim.build_blueprints()                      # beds, table, chairs
    house.update(ctx_for(rim, tmp_path, board))  # walls placed
    walls_stuff = house.memory["house"]["walls"]
    rim.build_blueprints(40)                    # most walls built, the rest wait
    other = "WoodLog" if walls_stuff == "Steel" else "Steel"
    rim.resources = [{"defName": walls_stuff, "count": 0}, {"defName": other, "count": 1000}]
    for _ in range(3):
        rim.tick += 25 * 2500
        house.update(ctx_for(rim, tmp_path, board))
    assert rim.replaced == []
    waiting = [b for b in rim.blueprints if b["def"] in ("Wall", "Door")]
    assert waiting and {b["stuff"] for b in waiting} == {other}


def test_what_stands_keeps_its_material_whatever_the_plan_says(tmp_path):
    rim = colony()
    FoodManager().update(ctx_for(rim, tmp_path))
    house, board = HouseManager(), {}
    house.update(ctx_for(rim, tmp_path, board))
    rim.build_blueprints()
    house.update(ctx_for(rim, tmp_path, board))
    rim.build_blueprints()
    house.memory["house"]["walls"] = "Steel" if house.memory["house"]["walls"] == "WoodLog" else "WoodLog"  # say, a bug
    house.update(ctx_for(rim, tmp_path, board))
    assert rim.replaced == []


def test_newcomers_get_bedrooms_in_the_wing_and_nobody_moves(tmp_path):
    from rimagent.managers.house import WingManager

    rim = colony()
    FoodManager().update(ctx_for(rim, tmp_path))
    house, wing, board = HouseManager(), WingManager(), {}
    for _ in range(7):  # the house, then the wing's shell once the house stands
        house.update(ctx_for(rim, tmp_path, board))
        wing.update(ctx_for(rim, tmp_path, board))
        rim.build_blueprints()
    assert house.memory["built"] and len(rim.beds) == 3
    assert wing.memory["house"]["bedrooms"] == 2 and board["house_beds"] == 5  # room for two more
    assert wing.memory["house"].get("beds_for", 0) == 0  # no wing beds until someone needs one
    before = dict(rim.owners)
    for n in ("Human0", "Human1"):
        rim.colonists.append({"ids": {"id": n}, "name": n, "position": {"x": 50, "y": 0, "z": 50},
                              "drafted": False, "downed": False, "gear": {"equipment": [], "apparel": []}})
        rim.work[n] = rim.work["HumanA"]
    for _ in range(3):
        house.update(ctx_for(rim, tmp_path, board))
        wing.update(ctx_for(rim, tmp_path, board))
        rim.build_blueprints()
    assert len(rim.beds) == 5 and rim.replaced == []
    assert {b: p for b, p in rim.owners.items() if p in ("HumanA", "HumanB", "HumanC")} == before
    assert {"Human0", "Human1"} <= set(rim.owners.values())
    assert not [c for c in rim.called("designate") if c["kind"] == "deconstruct"]  # the wing's beds stay

def test_a_house_far_from_the_stockpile_leaves_dining_to_the_mood_manager(tmp_path):
    """Trial 22: the house stood ~40 cells from the stockpile; meals were eaten standing ("Ate without table")."""
    rim = colony()
    FoodManager().update(ctx_for(rim, tmp_path))
    house, board = HouseManager(), {}
    house.update(ctx_for(rim, tmp_path, board))
    assert board["house_dining"] is True
    house.memory["house"]["origin"] = [5, 5]  # say the only site was far off
    house.update(ctx_for(rim, tmp_path, board))
    assert board["house_dining"] is False
