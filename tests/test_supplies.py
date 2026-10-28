from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.manager import TICKS_PER_HOUR
from rimagent.managers.supplies import IDLE_HOLD_HOURS, SuppliesManager

from .fakegame import FakeRim

IDLE = {"type": "Alert_ColonistsIdle", "label": "3 colonists idle", "priority": "Medium", "culprits": []}


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
    assert [i.kind for i in ctx.incidents] == ["colonistsIdle"]


def test_no_idle_alert_no_incident(tmp_path):
    rim = FakeRim()
    manager = SuppliesManager()
    for _ in range(3):
        manager.update(ctx := ctx_for(rim, tmp_path))
        rim.tick += IDLE_HOLD_HOURS * TICKS_PER_HOUR
        assert ctx.incidents == []
