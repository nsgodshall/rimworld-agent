import pytest

from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers import planner
from rimagent.managers.food import FoodManager
from rimagent.managers.house import HouseManager, WingManager, plan
from rimagent.managers.kitchen import KitchenManager
from rimagent.managers.planner import (
    CORE_HEIGHT,
    CORE_WIDTH,
    EDGE_REACH,
    CoreManager,
    GardenManager,
    PlannerManager,
    best_frame,
    layout,
)
from rimagent.managers.research import ResearchManager
from rimagent.snapshot import RESERVED
from rimsdk.mapview import FACING, ORIENTATIONS, Frame, MapView, Rect

from .fakegame import FakeRim, grid, offsets


def ctx_for(rim, tmp_path, board):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False), board=board)


def colony():
    rim = FakeRim()
    rim.resources = [{"defName": "WoodLog", "count": 3000}, {"defName": "Steel", "count": 1000}]
    return rim


def cells_of(def_, xz, rotation="north"):
    fp, ic = offsets(def_, rotation)
    x, z = xz
    cells = {(x + fp["x"] + i, z + fp["z"] + j) for i in range(fp["width"]) for j in range(fp["height"])}
    return cells, (x + ic["x"], z + ic["z"]) if ic else None


def houses(p):
    frame = Frame.from_list(p["frame"])
    return plan(p["house"], 3, frame=frame), plan(p["wing"], 2, common_room=False, frame=frame)


def around(cells):
    cells = set(cells)
    return {(x + dx, z + dz) for x, z in cells for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))} - cells


LAID = [o.moved(50, 50) for o in ORIENTATIONS]


@pytest.mark.parametrize("frame", LAID, ids=str)
def test_each_core_room_is_closed_with_doors_and_nothing_blocks_them(frame):
    p = layout(frame)
    solid = set(p["walls"]) | set(p["doors"])
    for name in ("kitchen", "store", "workshop"):
        ring = around(p[name].cells())
        assert ring <= solid, f"{name} isn't enclosed"
        assert ring & set(p["doors"]), f"{name} has no door"
    stove, cook = cells_of("FueledStove", p["stove"], p["stove_rotation"])
    bench, researcher = cells_of("SimpleResearchBench", p["bench"], p["bench_rotation"])
    assert stove | {cook} <= set(p["kitchen"].cells()) and bench | {researcher} <= set(p["workshop"].cells())
    fixtures = stove | bench | set(p["lamps"]) | {p["bench_lamp"]}
    assert {cook, researcher}.isdisjoint(fixtures) and p["bench_lamp"] in set(p["workshop"].cells())
    # The cell inside each door, on either side, stays free.
    assert not (around(p["doors"]) - solid) & fixtures
    assert set(p["pantry"].cells()) | set(p["general"].cells()) == set(p["store"].cells())


@pytest.mark.parametrize("frame", LAID, ids=str)
def test_house_and_wing_face_the_core_across_the_street(frame):
    p = layout(frame)
    house, wing = houses(p)
    street = set(p["street"].cells())
    for b in (p["core"], house["outer"], wing["outer"]):
        assert set(b.cells()) <= set(p["footprint"].cells()) and not set(b.cells()) & street
    assert not set(house["outer"].cells()) & set(wing["outer"].cells())  # no shared wall: no replacements
    # Every door on the street side opens onto it: the house's and wing's, and the core's three.
    for door in house["doors"] + wing["doors"]:
        assert around([door]) & street
    assert sum(bool(around([d]) & street) for d in p["doors"]) == 3
    # Beds in the bedrooms, the table and its chairs in the common room, all where the game puts them turned.
    for room, bed in zip(house["bedrooms"] + wing["bedrooms"], house["beds"] + wing["beds"]):
        cells, _ = cells_of("Bed", bed, (house["facing"] | wing["facing"])[bed])
        assert cells <= set(room.cells())
    table = set(Rect(*house["table"], 2, 2).cells())
    assert table <= set(house["common"].cells())
    for chair in house["chairs"]:
        dx, dz = FACING[house["facing"][chair]]
        assert (chair[0] + dx, chair[1] + dz) in table  # facing the table


@pytest.mark.parametrize("frame", LAID, ids=str)
def test_the_street_has_pots_by_the_doors_and_a_clear_way_through(frame):
    p = layout(frame)
    house, wing = houses(p)
    street, garden = p["street"], set(p["garden"])
    assert garden <= set(street.cells())
    fronts = around(p["doors"] + house["doors"] + wing["doors"]) & set(street.cells())
    assert not garden & fronts
    across = (street.width < street.height)
    middle = {c for c in street.cells() if (c[0] if across else c[1]) == (street.x + 1 if across else street.z + 1)}
    assert len(middle) == 29 and not garden & middle
    # Each doorstep has a pot either side, unless that's another doorstep.
    assert all(len(around([f]) & garden) + len(around([f]) & fronts) >= 2 for f in fronts)


def test_the_base_is_one_rectangle_and_mirror_symmetric():
    p = layout(Frame())
    house, wing = houses(p)
    row = house["outer"].width + wing["outer"].width
    assert p["core"].width == row == CORE_WIDTH and house["outer"].x == p["core"].x
    east = CORE_WIDTH - 1
    assert p["stove"][0] + p["bench"][0] == east and p["lamps"][0][0] + p["bench_lamp"][0] == east
    xs = sorted(x for x, _ in p["doors"])
    assert xs == sorted(east - x for x in xs)  # the core's doors mirror each other
    assert {x for x, z in p["doors"] if z in (0, CORE_HEIGHT - 1)} >= {CORE_WIDTH // 2}  # front and back on the line


def run_base(rim, tmp_path, board, managers, passes=12):
    incidents = []
    for _ in range(passes):
        for manager in managers:
            ctx = ctx_for(rim, tmp_path, board)
            manager.update(ctx)
            incidents += ctx.incidents
        rim.build_blueprints()
    return incidents


@pytest.mark.parametrize("frame", LAID, ids=str)
def test_every_way_round_the_whole_base_builds_without_a_refusal(tmp_path, frame):
    rim = colony()
    rim.map_size = (130, 130)
    rim.cells = grid(130, 130, ".")
    planner = PlannerManager()
    planner.memory["frame"] = frame.to_list()
    garden = GardenManager()
    managers = [planner, HouseManager(), WingManager(), FoodManager(), KitchenManager(), ResearchManager(),
                CoreManager(), garden]
    board = {}
    incidents = run_base(rim, tmp_path, board, managers)
    assert not incidents, [(i.kind, i.summary) for i in incidents]
    assert not rim.replaced and not rim.blueprints
    assert board["house_stage"] == 3 and board["wing_stage"] == 3 and board["core_stage"] == 2 and garden.memory["done"]
    p = board["plan"]
    built = {(b["def"], b["x"], b["z"]): b for b in rim.built}
    assert ("FueledStove", *p["stove"]) in built and ("SimpleResearchBench", *p["bench"]) in built
    assert {("PlantPot", *xz) for xz in p["garden"]} <= set(built)
    # The cook's and the researcher's cells are free.
    taken = {c for b in rim.built for c in cells_of(b["def"], (b["x"], b["z"]), b.get("rotation"))[0]}
    for def_, key in (("FueledStove", "stove"), ("SimpleResearchBench", "bench")):
        _, stand = cells_of(def_, p[key], p[f"{key}_rotation"])
        assert stand not in taken


def test_a_new_colony_places_everything_in_its_planned_room(tmp_path):
    rim, board = colony(), {}
    for manager in (PlannerManager(), HouseManager(), FoodManager(), KitchenManager(), ResearchManager()):
        manager.update(ctx_for(rim, tmp_path, board))
    p = board["plan"]
    general, pantry = [Rect(**z["add"][0]) for z in rim.called("set_zone") if "add" in z][:2]
    assert (general, pantry) == (p["general"], p["pantry"])
    placed = {(q["def"], q["x"], q["z"]) for c in rim.called("place_blueprint") for q in c["placements"]}
    assert ("FueledStove", *p["stove"]) in placed and ("SimpleResearchBench", *p["bench"]) in placed
    beds = [(q["x"], q["z"]) for c in rim.called("place_blueprint") for q in c["placements"] if q["def"] == "Bed"]
    assert beds == houses(p)[0]["beds"]
    assert board["house_dining"]  # the common room is the dining room: no table outdoors
    (chop,) = [c for c in rim.called("designate") if c["kind"] == "chopWood"]
    assert chop["rects"] == [p["footprint"].to_api()]


def test_fields_and_other_sites_keep_out_of_the_footprint(tmp_path):
    rim, board = colony(), {}
    PlannerManager().update(ctx_for(rim, tmp_path, board))
    FoodManager().update(ctx_for(rim, tmp_path, board))
    (field,) = [Rect(**c["add"][0]) for c in rim.called("set_zone") if c.get("kind") == "growing"]
    assert not field.overlaps(board["plan"]["footprint"])


def test_reserved_open_ground_is_masked_but_walls_stay_cover(tmp_path):
    rim = FakeRim(cells={**grid(100, 100, "."), (5, 5): "#", (6, 5): "t"})
    ctx = ctx_for(rim, tmp_path, {"reserved": {(5, 5), (6, 5), (7, 5)}})
    view = ctx.snapshot.view(Rect(0, 0, 10, 10))
    assert (view[5, 5], view[6, 5], view[7, 5], view[8, 5]) == ("#", RESERVED, RESERVED, ".")


def test_the_core_is_walled_in_after_the_house_shell(tmp_path):
    rim, board = colony(), {}
    PlannerManager().update(ctx_for(rim, tmp_path, board))
    core = CoreManager()
    board["house_stage"] = 1
    core.update(ctx_for(rim, tmp_path, board))
    assert not rim.called("place_blueprint")  # the house's walls first
    board["house_stage"] = 2
    core.update(ctx_for(rim, tmp_path, board))
    p = board["plan"]
    first = [q for c in rim.called("place_blueprint") for q in c["placements"]]
    assert {(q["x"], q["z"]) for q in first} == set(p["walls"]) | set(p["doors"])
    assert {q["stuff"] for q in first} == {"Steel"}
    rim.build_blueprints()
    core.update(ctx_for(rim, tmp_path, board))
    assert ("TorchLamp", *p["lamps"][0]) in {(q["def"], q["x"], q["z"]) for q in rim.called("place_blueprint")[-1]["placements"]}
    rim.build_blueprints()
    core.update(ctx_for(rim, tmp_path, board))
    assert core.memory["built"] and board["core_stage"] == 2


def test_the_plan_is_found_again_after_a_restart(tmp_path):
    rim, board = colony(), {}
    PlannerManager().update(ctx_for(rim, tmp_path, board))
    FoodManager().update(ctx_for(rim, tmp_path, board))
    before = board["plan"]
    fresh = {}  # a restart: no board, no memory
    PlannerManager().update(ctx_for(rim, tmp_path, fresh))
    assert rim.zones[0]["label"] == before["label"]
    assert fresh["plan"]["origin"] == before["origin"] and fresh["reserved"] == set(before["footprint"].cells())
    # The house and wing go where they'd have gone.
    house, wing = HouseManager(), WingManager()
    house.update(ctx_for(rim, tmp_path, fresh))
    assert house.memory["house"]["origin"] == list(before["house"])


def test_a_colony_without_a_planned_stockpile_has_no_plan(tmp_path):
    rim, board = colony(), {}
    FoodManager().update(ctx_for(rim, tmp_path, board))  # placed as before any plan
    planner = PlannerManager()
    planner.update(ctx_for(rim, tmp_path, board))
    planner.update(ctx_for(rim, tmp_path, board))
    assert "plan" not in board and len(rim.called("set_zone")) == 3


def test_no_room_for_the_base_is_a_warning_and_no_plan(tmp_path):
    rim = colony()
    rim.cells = grid(100, 100, "^")
    board = {}
    ctx = ctx_for(rim, tmp_path, board)
    PlannerManager().update(ctx)
    assert "plan" not in board and [(i.kind, i.severity) for i in ctx.incidents] == [("noBaseSite", "warn")]


def test_items_and_animals_on_the_site_dont_stop_the_plan(tmp_path):
    """The replay of s1: drop-pod items lay all over the landing site, and no block was free of them."""
    cells = grid(100, 100, ".")
    for x in range(0, 100, 7):
        for z in range(0, 100, 5):
            cells[(x, z)] = "*"
    rim = colony()
    rim.cells = cells
    board = {}
    PlannerManager().update(ctx_for(rim, tmp_path, board))
    assert "plan" in board


def test_rock_and_water_still_stop_it(tmp_path):
    cells = grid(100, 100, ".")
    for x in range(0, 100, 7):
        for z in range(0, 100, 5):
            cells[(x, z)] = "^"
    rim = colony()
    rim.cells = cells
    board = {}
    PlannerManager().update(ctx_for(rim, tmp_path, board))
    assert "plan" not in board


LEGEND = {".": "soil", ":": "rich soil", "_": "ground too poor to farm, or floor", "t": "tree", "^": "natural rock",
          "*": "item"}


def view_of(cells):
    return MapView(cells, LEGEND)


def inner_of(frame):
    from rimagent.managers.planner import INNER
    return frame.rect(INNER)


def test_a_site_across_rock_loses_to_one_the_colonists_can_walk_to():
    """The nearest clear ground is just past a ridge, which a straight line ignores; the site chosen is the
    farther one on the colonists' side."""
    cells = grid(100, 100, ".")
    for z in range(100):
        cells[(55, z)] = "^"  # a ridge from edge to edge: nothing east of it can be walked to
    for x in range(30, 55):
        for z in range(0, 100, 4):
            cells[(x, z)] = "^"  # rock strewn west of the colonists: no site fits here
    frame, terms = best_frame(view_of(cells), (52, 50), (100, 100))
    inner = inner_of(frame)
    assert inner.x + inner.width <= 30 and terms["walk"] > 0


def test_a_narrow_valley_turns_the_base_to_fit():
    cells = grid(100, 100, "^")
    for x in range(40, 62):  # 22 wide: the base is 31 one way and 19 the other
        for z in range(10, 90):
            cells[(x, z)] = "."
    frame, _ = best_frame(view_of(cells), (50, 50), (100, 100))
    assert frame.turns % 2 == 1
    inner = inner_of(frame)
    assert 40 <= inner.x and inner.x + inner.width <= 62


def test_the_base_keeps_back_from_the_map_edge(monkeypatch):
    monkeypatch.setattr(planner, "ROOM", 0)  # room around pushes it inward too; this is the edge alone
    _, terms = best_frame(view_of(grid(100, 100, ".")), (3, 50), (100, 100))
    assert terms["edge"] >= EDGE_REACH


def test_the_back_door_faces_the_farmland():
    cells = grid(100, 100, "_")  # poor ground all round, but soil to the east
    for x in range(70, 100):
        for z in range(100):
            cells[(x, z)] = "."
    frame, terms = best_frame(view_of(cells), (50, 50), (100, 100))
    p = layout(frame)
    assert p["away"] == (1, 0) and terms["farmland"] > 0


def test_trees_and_rich_soil_count_against_a_site():
    cells = grid(100, 100, ".")
    for x in range(50):  # the west half wooded and rich
        for z in range(100):
            cells[(x, z)] = "t" if (x + z) % 3 else ":"
    frame, terms = best_frame(view_of(cells), (50, 50), (100, 100))
    assert inner_of(frame).x >= 50 and terms["trees"] == terms["rich"] == 0


def test_a_turned_plan_is_found_again_from_its_store(tmp_path):
    rim, board = colony(), {}
    planner = PlannerManager()
    planner.memory["frame"] = Frame(40, 40, 3, True).to_list()
    planner.update(ctx_for(rim, tmp_path, board))
    FoodManager().update(ctx_for(rim, tmp_path, board))
    assert rim.zones[0]["label"] == "Store 40,40 r3m"
    fresh = {}
    PlannerManager().update(ctx_for(rim, tmp_path, fresh))
    assert fresh["plan"]["frame"] == [40, 40, 3, True] and fresh["plan"]["general"] == board["plan"]["general"]


def test_the_first_planners_store_is_not_taken_for_this_plan(tmp_path):
    """Its layout was another: laying this one over it would wall through its rooms."""
    rim = colony()
    rim.zones = [{"id": "zone:0:1", "kind": "stockpile", "label": "Store 34,46", "cellCount": 36}]
    board = {}
    PlannerManager().update(ctx_for(rim, tmp_path, board))
    assert "plan" not in board


def test_ugly_work_goes_out_of_the_back_door(tmp_path):
    rim, board = colony(), {}
    rim.map_size = (150, 150)
    rim.cells = grid(150, 150, ".")
    planner = PlannerManager()
    planner.memory["frame"] = Frame(70, 80, 1).to_list()  # turned: the back door faces west
    planner.update(ctx_for(rim, tmp_path, board))
    FoodManager().update(ctx_for(rim, tmp_path, board))
    kitchen = KitchenManager()
    kitchen.ensure_dump(ctx_for(rim, tmp_path, board))
    kitchen.ensure_built(ctx_for(rim, tmp_path, board), ("ButcherSpot",), "butcher spot")
    p = board["plan"]
    assert p["away"] == (-1, 0)
    dump = Rect(**rim.called("set_zone")[-1]["add"][0])
    (field,) = [Rect(**c["add"][0]) for c in rim.called("set_zone") if c.get("kind") == "growing"]
    (spot,) = [(q["x"], q["z"]) for c in rim.called("place_blueprint") for q in c["placements"] if q["def"] == "ButcherSpot"]
    store_west = p["store"].x
    assert dump.x + dump.width < store_west - 15 and field.x + field.width <= p["footprint"].x
    assert spot[0] < p["footprint"].x and abs(spot[1] - p["butcher"][1]) <= 3


def test_core_and_wing_are_walled_in_what_the_house_is(tmp_path):
    rim, board = colony(), {"base_walls": "WoodLog"}  # the house went up in wood
    PlannerManager().update(ctx_for(rim, tmp_path, board))
    board["house_stage"] = 3
    core, wing = CoreManager(), WingManager()
    core.update(ctx_for(rim, tmp_path, board))
    wing.update(ctx_for(rim, tmp_path, board))
    assert core.memory["core"]["walls"] == "WoodLog" and wing.memory["house"]["walls"] == "WoodLog"


def test_the_garden_waits_for_the_buildings_and_spare_wood(tmp_path):
    rim, board = colony(), {}
    rim.resources = [{"defName": "WoodLog", "count": 300}, {"defName": "Steel", "count": 1000}]
    PlannerManager().update(ctx_for(rim, tmp_path, board))
    garden = GardenManager()
    garden.update(ctx_for(rim, tmp_path, board))
    board.update(house_stage=3, core_stage=2)
    garden.update(ctx_for(rim, tmp_path, board))
    assert not rim.called("place_blueprint")  # 300 wood: kept for what matters
    rim.resources[0]["count"] = 1000
    garden.update(ctx_for(rim, tmp_path, board))
    pots = [(q["x"], q["z"]) for c in rim.called("place_blueprint") for q in c["placements"]]
    assert pots == board["plan"]["garden"] and len(pots) == 18
    rim.build_blueprints()
    garden.update(ctx_for(rim, tmp_path, board))
    assert garden.memory["done"]
