from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers.food import FoodManager
from rimagent.managers.research import ResearchManager

from .fakegame import FakeRim, grid


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def test_no_bench_no_project_plans_a_bench_and_picks_a_project(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    ResearchManager().update(ctx := ctx_for(rim, tmp_path))

    (pick,) = rim.called("set_research_project")
    assert pick["project_def_name"] == "B"  # A is finished
    (call,) = rim.called("place_blueprint")
    (bench,) = call["placements"]
    assert bench["def"] == "SimpleResearchBench" and bench["stuff"] == "WoodLog"
    stockpile = rim.zones[0]["representativeCell"]
    assert abs(bench["x"] - stockpile["x"]) <= 10 and abs(bench["z"] - stockpile["z"]) <= 10
    assert ctx.incidents == []


def test_a_planned_bench_is_not_placed_twice_and_a_project_is_chosen_once(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    ResearchManager().update(ctx_for(rim, tmp_path))
    ResearchManager().update(ctx_for(rim, tmp_path))
    first, second = rim.called("place_blueprint")
    assert first == second and len(rim.blueprints) == 1
    assert len(rim.called("set_research_project")) == 1


def test_a_built_bench_and_a_project_need_nothing(tmp_path):
    rim = FakeRim()
    FoodManager().update(ctx_for(rim, tmp_path))
    ResearchManager().update(ctx_for(rim, tmp_path))
    rim.build_blueprints()
    ResearchManager().update(ctx_for(rim, tmp_path))
    bench, lamp = rim.called("place_blueprint")  # and, once it's built, a lamp beside it
    assert lamp["placements"][0]["def"] == "TorchLamp" and len(rim.called("set_research_project")) == 1


def test_preferred_project_before_cheaper_ones(tmp_path):
    rim = FakeRim()
    rim.projects = [
        {"defName": "Pemmican", "label": "Pemmican", "baseCost": 500, "finished": False},
        {"defName": "Batteries", "label": "Battery", "baseCost": 400, "finished": True},
        {"defName": "SolarPanels", "label": "Solar panel", "baseCost": 600, "finished": False},
        {"defName": "Hydroponics", "label": "Hydroponics", "baseCost": 700, "finished": False, "available": False},
    ]
    ResearchManager().update(ctx_for(rim, tmp_path))
    (pick,) = rim.called("set_research_project")
    assert pick["project_def_name"] == "SolarPanels"


def test_nothing_to_research_is_a_warning(tmp_path):
    rim = FakeRim()
    rim.projects = [{"defName": "A", "label": "A", "baseCost": 300, "finished": True}]
    ResearchManager().update(ctx := ctx_for(rim, tmp_path))
    assert rim.called("set_research_project") == []
    assert ("noResearch", "warn") in [(i.kind, i.severity) for i in ctx.incidents]


def test_no_room_is_a_warning(tmp_path):
    rim = FakeRim(cells=grid(100, 100, "^"))
    ResearchManager().update(ctx := ctx_for(rim, tmp_path))
    assert ("noSite", "warn") in [(i.kind, i.severity) for i in ctx.incidents]
    assert rim.called("place_blueprint") == []


def test_a_torch_lamp_goes_beside_the_bench(tmp_path):
    rim = FakeRim()
    rim.buildings = [{"ids": {"id": "Bench1"}, "def": {"defName": "SimpleResearchBench"}, "position": {"x": 50, "y": 0, "z": 50}}]
    rim.research_project = "B"
    manager = ResearchManager()
    manager.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    (call,) = rim.called("place_blueprint")
    assert call["placements"] == [{"def": "TorchLamp", "x": 52, "z": 50, "rotation": "north"}]
    manager.update(Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False)))
    assert len(rim.called("place_blueprint")) == 1  # placed once
