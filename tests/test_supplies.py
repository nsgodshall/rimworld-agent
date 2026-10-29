from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.manager import TICKS_PER_HOUR
from rimagent.managers.supplies import CHOP_BATCH, IDLE_HOLD_HOURS, KEEP_CLEAR, WOOD_TARGET, SuppliesManager

from .fakegame import FakeRim

IDLE = {"type": "Alert_ColonistsIdle", "label": "3 colonists idle", "priority": "Medium", "culprits": [], "culpritCount": 3}


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def test_starting_goods_near_the_base_are_unforbidden(tmp_path):
    rim = FakeRim()
    rim.alerts = [IDLE]
    rim.goods = [
        {"id": "WoodLog1", "def": "WoodLog", "x": 52, "z": 40, "count": 50, "forbidden": True, "inStorage": False},
        {"id": "Steel1", "def": "Steel", "x": 55, "z": 55, "count": 60, "forbidden": True, "inStorage": False},
    ]
    ctx = ctx_for(rim, tmp_path)
    SuppliesManager().update(ctx)

    (call,) = rim.called("designate")
    assert call == {"kind": "unforbid", "thing_ids": ["WoodLog1", "Steel1"]}
    assert ctx.incidents == []
    # Nothing forbidden is left: a second pass changes nothing.
    SuppliesManager().update(ctx_for(rim, tmp_path))
    assert len(rim.called("designate")) == 1


def test_idle_with_nothing_to_unforbid_asks_for_code_after_the_hold(tmp_path):
    rim = FakeRim()
    rim.alerts = [IDLE]
    manager = SuppliesManager()
    manager.update(ctx := ctx_for(rim, tmp_path))
    assert ctx.incidents == [] and rim.called("designate") == []

    rim.tick += IDLE_HOLD_HOURS * TICKS_PER_HOUR
    manager.update(ctx := ctx_for(rim, tmp_path))
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("colonistsIdle", "halt")]


def test_no_idle_alert_no_incident(tmp_path):
    rim = FakeRim()
    manager = SuppliesManager()
    for _ in range(3):
        manager.update(ctx := ctx_for(rim, tmp_path))
        rim.tick += IDLE_HOLD_HOURS * TICKS_PER_HOUR
        assert ctx.incidents == []


def forest(rim, cells):
    for xz in cells:
        rim.cells[xz] = "t"


def test_short_of_wood_the_nearest_trees_past_the_base_are_chopped(tmp_path):
    rim = FakeRim()  # colonists at (50, 50): the base
    rim.resources = [{"defName": "WoodLog", "label": "Wood", "count": 40, "stacks": 1, "forbiddenStacks": 0}]
    near_base = [(52, 50), (50, 55)]  # cover for the defenders: kept
    out = [(50 + KEEP_CLEAR + 1 + i, 50) for i in range(25)] + [(50, 50 - KEEP_CLEAR - 1)]
    far = [(5, 5)]  # outside the first search square
    forest(rim, near_base + out + far)
    manager = SuppliesManager()
    manager.update(ctx := ctx_for(rim, tmp_path))

    (call,) = rim.called("designate")
    marked = {(r["x"], r["z"]) for r in call["rects"]}
    assert call["kind"] == "chopWood" and len(marked) == CHOP_BATCH
    assert (50, 50 - KEEP_CLEAR - 1) in marked and not marked & set(near_base + far)
    assert ctx.incidents == []
    # The same trees are marked again until felled, but only logged once.
    manager.update(ctx_for(rim, tmp_path))
    assert len(rim.called("designate")) == 2
    assert sum("trees nearest" in line for line in (tmp_path / "j.jsonl").read_text().splitlines()) == 1


def test_few_trees_nearby_looks_further_out(tmp_path):
    rim = FakeRim()
    forest(rim, [(15, 15), (85, 85), (2, 2)])  # (2, 2) is past even the wider square
    SuppliesManager().update(ctx_for(rim, tmp_path))
    (call,) = rim.called("designate")
    assert call["kind"] == "chopWood" and {(r["x"], r["z"]) for r in call["rects"]} == {(15, 15), (85, 85)}


def test_enough_wood_no_chopping(tmp_path):
    rim = FakeRim()
    rim.resources = [{"defName": "WoodLog", "label": "Wood", "count": WOOD_TARGET, "stacks": 4, "forbiddenStacks": 0}]
    forest(rim, [(70, 70)])
    SuppliesManager().update(ctx_for(rim, tmp_path))
    assert rim.called("designate") == []


def test_some_colonists_idle_is_a_warning_not_a_halt(tmp_path):
    """Trial 3 stopped on '1 colonist idle': Hikari can't research, and the building was done."""
    rim = FakeRim()
    rim.alerts = [{**IDLE, "label": "1 colonist idle", "culpritCount": 1}]
    manager = SuppliesManager()
    manager.update(ctx_for(rim, tmp_path))
    rim.tick += IDLE_HOLD_HOURS * TICKS_PER_HOUR
    manager.update(ctx := ctx_for(rim, tmp_path))
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("colonistsIdle", "warn")]
