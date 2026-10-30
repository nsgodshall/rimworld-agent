from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers.food import FoodManager
from rimagent.managers.house import HouseManager, WingManager, plan
from rimagent.managers.kitchen import KitchenManager
from rimagent.managers.planner import CoreManager, PlannerManager, layout
from rimagent.managers.research import ResearchManager
from rimagent.snapshot import RESERVED
from rimsdk.mapview import Rect

from .fakegame import FOOTPRINTS, FakeRim, grid


def ctx_for(rim, tmp_path, board):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False), board=board)


def colony():
    rim = FakeRim()
    rim.resources = [{"defName": "WoodLog", "count": 3000}, {"defName": "Steel", "count": 1000}]
    return rim


def cells_of(def_, xz):
    fp, ic = FOOTPRINTS[def_]
    x, z = xz
    cells = {(x + fp["x"] + i, z + fp["z"] + j) for i in range(fp["width"]) for j in range(fp["height"])}
    return cells, (x + ic["x"], z + ic["z"])


def test_each_core_room_is_closed_with_doors_and_nothing_blocks_them():
    p = layout((10, 10))
    solid = set(p["walls"]) | set(p["doors"])
    for name in ("kitchen", "store", "workshop"):
        cells = set(p[name].cells())
        ring = {(x + dx, z + dz) for x, z in cells for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))} - cells
        assert ring <= solid, f"{name} isn't enclosed"
        assert ring & set(p["doors"]), f"{name} has no door"
    stove, cook = cells_of("FueledStove", p["stove"])
    bench, researcher = cells_of("SimpleResearchBench", p["bench"])
    assert stove | {cook} <= set(p["kitchen"].cells()) and bench | {researcher} <= set(p["workshop"].cells())
    fixtures = stove | bench | set(p["lamps"]) | {(p["bench"][0] + 2, p["bench"][1])}  # and research's bench lamp
    # The cell inside each door, on either side, stays free.
    beside = {(x + dx, z + dz) for x, z in p["doors"] for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))} - solid
    assert not beside & fixtures
    assert set(p["pantry"].cells()) | set(p["general"].cells()) == set(p["store"].cells())


def test_house_and_wing_sit_north_of_the_core_across_a_clear_doorstep_row():
    p = layout((10, 10))
    house, wing = plan(p["house"], 3), plan(p["wing"], 2, common_room=False)
    core = p["core"]
    doorstep = {(x, core.z + core.height) for x in range(core.x, core.x + core.width)}
    buildings = [core, house["outer"], wing["outer"]]
    for b in buildings:
        assert set(b.cells()) <= set(p["footprint"].cells())
        assert not set(b.cells()) & doorstep
    assert not set(house["outer"].cells()) & set(wing["outer"].cells())  # no shared wall: no replacements
    assert all(z == core.z + core.height + 1 for _, z in house["doors"] + wing["doors"])  # open onto the row


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
    assert beds == plan(p["house"], 3)["beds"]
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
