from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers.defense import DefenseManager
from rimagent.managers.heat import MAX_HOLD_HOURS, HeatManager, heatstroke

from .fakegame import FakeRim

# As list_pawns detail=normal and get_events show them (heat wave, day 9 of trial 9).
ALERT = {"type": "Alert_Heatstroke", "label": "Heatstroke", "priority": "High",
         "culprits": [{"id": "HumanA", "label": "A"}], "culpritCount": 1}
ROOMS = [
    {"role": "None", "cellCount": 0, "openRoofCells": 0, "temperatureC": 43.4, "usesOutdoorTemperature": True},
    {"id": "room:0:139,143:Bedroom", "role": "Bedroom", "cellCount": 12, "openRoofCells": 0,
     "temperatureC": 17.4, "usesOutdoorTemperature": False},
    {"id": "room:0:128,143:RecRoom", "role": "RecRoom", "cellCount": 24, "openRoofCells": 0,
     "temperatureC": 22.2, "usesOutdoorTemperature": False},
]


def struck(pawn, severity, stage):
    pawn["health"] = {"dead": False, "downed": False, "pain": 0, "summaryHealthPercent": 1, "hediffs": [
        {"defName": "Stab", "label": "Stab scar", "severity": 2, "part": "Torso"},
        {"defName": "Heatstroke", "label": f"Heatstroke ({stage})", "severity": severity}]}


def ctx_for(rim, tmp_path, board):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False), board=board)


def test_mild_heatstroke_is_left_to_fade(tmp_path):
    rim = FakeRim()
    rim.alerts, rim.rooms = [ALERT], ROOMS
    struck(rim.colonists[0], 0.09, "initial")
    ctx = ctx_for(rim, tmp_path, {})
    HeatManager().update(ctx)
    assert rim.called("set_pawn_drafted") == [] and rim.called("order_pawn") == []
    assert ctx.incidents == []


def test_moderate_heatstroke_rests_in_the_coolest_room_until_recovered(tmp_path):
    rim = FakeRim()
    rim.alerts, rim.rooms = [ALERT], ROOMS
    struck(rim.colonists[0], 0.24, "moderate")
    board: dict = {}
    heat, defense = HeatManager(), DefenseManager()
    heat.update(ctx_for(rim, tmp_path, board))
    assert rim.called("set_pawn_drafted") == [{"pawn_id": "HumanA", "drafted": True}]
    assert rim.called("order_pawn") == [{"pawn_id": "HumanA", "order": "move", "x": 139, "z": 143}]
    assert board["cooling"] == ["HumanA"]

    # No hostiles: defense undrafts the drafted, but not a colonist cooling down.
    defense.stand_down(ctx_for(rim, tmp_path, board))
    assert rim.pawn("HumanA")["drafted"] is True

    rim.tick += 2500
    heat.update(ctx_for(rim, tmp_path, board))  # still heatstruck: held, not ordered again
    assert len(rim.called("order_pawn")) == 1 and rim.pawn("HumanA")["drafted"] is True

    rim.alerts = []
    struck(rim.colonists[0], 0.02, "initial")
    heat.update(ctx_for(rim, tmp_path, board))
    assert rim.called("set_pawn_drafted")[-1] == {"pawn_id": "HumanA", "drafted": False}
    assert board["cooling"] == []


def test_a_long_hold_is_let_go_with_an_incident(tmp_path):
    rim = FakeRim()
    rim.alerts, rim.rooms = [ALERT], ROOMS
    struck(rim.colonists[0], 0.4, "serious")
    heat = HeatManager()
    heat.update(ctx_for(rim, tmp_path, {}))
    rim.tick += MAX_HOLD_HOURS * 2500
    struck(rim.colonists[0], 0.1, "minor")
    ctx = ctx_for(rim, tmp_path, {})
    heat.update(ctx)
    assert rim.pawn("HumanA")["drafted"] is False
    assert [i.kind for i in ctx.incidents] == ["heatstrokeLingers"]


def test_no_cool_room_is_an_incident(tmp_path):
    rim = FakeRim()
    rim.alerts, rim.rooms = [ALERT], [dict(ROOMS[1], temperatureC=31.0)]
    struck(rim.colonists[0], 0.3, "moderate")
    ctx = ctx_for(rim, tmp_path, {})
    HeatManager().update(ctx)
    assert rim.called("set_pawn_drafted") == []
    assert [i.kind for i in ctx.incidents] == ["noCoolRoom"]


def test_severity_reads_the_stage_label_too():
    pawn = {}
    struck(pawn, 0.1, "serious")
    assert heatstroke(pawn) >= 0.2
    assert heatstroke({"health": {"hediffs": []}}) == 0.0
