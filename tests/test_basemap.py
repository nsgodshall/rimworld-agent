import asyncio
import json

from rimagent import Runtime
from rimagent.basemap import BLUEPRINT, HEAT, css, plan_text, search_text
from rimagent.managers.food import FoodManager
from rimagent.managers.house import HouseManager, WingManager
from rimagent.managers.planner import INNER, CoreManager, GardenManager, PlannerManager
from rimagent.watch import Watch
from rimsdk.mapview import Frame

from .fakegame import FakeRim
from .test_planner import colony, ctx_for, houses


def styles(text):
    return {str(span.style) for span in text.spans}


def test_the_planner_publishes_its_plan_cell_by_cell_and_how_far_it_is_built(tmp_path):
    rim, board = colony(), {}
    planner = PlannerManager()
    planner.update(ctx_for(rim, tmp_path, board))
    p, view = board["plan"], board["base_view"]
    house, wing = houses(p)
    letters = "".join(view["roles"])
    assert letters.count("W") == len(p["walls"]) + len(house["walls"]) + len(wing["walls"])
    assert letters.count("f") == len(p["garden"]) == 18 and letters.count("S") == 3 and letters.count("R") == 6
    assert letters.count("B") == 2 * (len(house["beds"]) + len(wing["beds"]))
    assert len(view["roles"]) == len(view["state"]) == view["rect"]["height"]
    assert view["progress"]["core"][0] == 0 and view["terms"]["score"] == planner.memory["terms"]["score"]
    # The core's walls go up: the picture shows them built.
    board["house_stage"] = 2
    core = CoreManager()
    core.update(ctx_for(rim, tmp_path, board))
    planner.update(ctx_for(rim, tmp_path, board))
    built, blueprints, total = board["base_view"]["progress"]["core"]
    assert built == 0 and blueprints == len(p["walls"]) + len(p["doors"]) and total > blueprints
    rim.build_blueprints()
    planner.update(ctx_for(rim, tmp_path, board))
    assert board["base_view"]["progress"]["core"][0] == len(p["walls"]) + len(p["doors"])


def test_the_planner_publishes_its_site_search(tmp_path):
    rim, board = colony(), {}
    PlannerManager().update(ctx_for(rim, tmp_path, board))
    search, p = board["base_search"], board["plan"]
    assert search["chosen"] == Frame.from_list(p["frame"]).rect(INNER).to_api()
    assert search["tried"] >= search["fits"] > 0
    rows = search["rows"]
    assert len(rows) == search["rect"]["height"] and {len(r) for r in rows} == {search["rect"]["width"]}
    digits = {ch for row in rows for ch in row if ch.isdigit()}
    assert {"0", "9"} <= digits  # ranked: the worst tenth and the best


def test_the_plan_is_drawn_with_blueprints_pulsing(tmp_path):
    rim, board, planner = colony(), {}, PlannerManager()
    planner.update(ctx_for(rim, tmp_path, board))
    board["house_stage"] = 2
    CoreManager().update(ctx_for(rim, tmp_path, board))
    planner.update(ctx_for(rim, tmp_path, board))
    base = board["base_view"]
    a, b = plan_text(base, 0), plan_text(base, 1)
    assert any(BLUEPRINT[0] in s for s in styles(a)) and any(BLUEPRINT[1] in s for s in styles(b))
    assert "kitchen·store·shop" in a.plain and "back door" in a.plain and "score" in a.plain


def test_the_search_sweeps_in_row_by_row(tmp_path):
    rim, board = colony(), {}
    PlannerManager().update(ctx_for(rim, tmp_path, board))
    search = board["base_search"]
    whole, half, none = (search_text(search, 40, r) for r in (1.0, 0.5, 0.0))
    lines = lambda t: [line for line in t.plain.split("\n") if line.startswith("▀")]
    assert len(lines(whole)) == len(lines(half)) == len(lines(none))  # the same size all through
    def heat(t):  # pixels in heat colours, in the map's rows (not the legend under it)
        end = sum(len(line) + 1 for line in lines(t))
        return sum(any(css(c) in str(span.style) for c in HEAT) for span in t.spans if span.end <= end)
    assert heat(none) == 0 < heat(half) <= heat(whole)
    assert "placements tried" in whole.plain


def test_watch_sweeps_a_search_chosen_while_watching_then_shows_the_plan(tmp_path):
    rim = FakeRim()
    rim.resources = [{"defName": "WoodLog", "count": 3000}, {"defName": "Steel", "count": 1000}]
    run_dir = tmp_path / "run"
    managers = [PlannerManager(), HouseManager(), WingManager(), FoodManager(), CoreManager(), GardenManager()]
    rt = Runtime(rim, run_dir, managers=managers, tripwires=[], echo=False)
    (run_dir / "journal.jsonl").write_text("")
    (run_dir / "state.json").write_text(json.dumps({"status": "cycle", "tick": 0}))  # before the plan

    async def check():
        app = Watch(run_dir, runs=tmp_path)
        async with app.run_test(size=(200, 55)) as pilot:
            await pilot.pause()
            assert "No base plan yet" in str(app.query_one("#base").render())
            rt.run(1)  # the planner chooses a site
            app.state_mtime = 0
            app.refresh_all()
            await pilot.pause()
            assert app.base_mode == "search" and app.reveal_from is not None
            assert "sweeping" in str(app.query_one("#base").border_title)
            app.reveal_from -= 100  # long done
            app.animate()
            assert app.base_mode == "plan" and "plan" in str(app.query_one("#base").border_title)
            await pilot.press("b")
            assert app.base_mode == "search" and app.reveal_from is None  # the whole search, no sweep
            await pilot.press("b")
            assert app.base_mode == "plan"

    asyncio.run(check())
