from rimagent import Context, Event, Runtime, Snapshot
from rimagent.journal import Journal
from rimagent.managers.defense import COMBAT_CHUNK_HOURS, DefenseManager
from rimagent.managers.threats import ThreatsManager

from .fakegame import FakeRim


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


def raider(name, x, z, **kw):
    return {"ids": {"id": name}, "name": name, "kind": "pawn", "threatKind": "humanlike",
            "position": {"x": x, "y": 0, "z": z}, "downed": False, **kw}


def colony():
    rim = FakeRim()
    rim.zones = [{"id": "zone:0:0", "kind": "stockpile", "cellCount": 36, "representativeCell": {"x": 50, "y": 0, "z": 50}}]
    for p in rim.colonists:
        p["gear"]["equipment"] = [{"def": {"defName": "Gun_Revolver"}}]
    return rim


def test_near_raid_drafts_everyone_gathers_them_and_shortens_time(tmp_path):
    rim = colony()
    rim.threats = [raider("R1", 70, 60)]
    for p, x in zip(rim.colonists, (30, 50, 51)):
        p["position"] = {"x": x, "y": 0, "z": 50}
    ctx = ctx_for(rim, tmp_path)
    DefenseManager().update(ctx)
    assert {c["pawn_id"] for c in rim.called("set_pawn_drafted")} == {"HumanA", "HumanB", "HumanC"}
    assert all(p["drafted"] for p in rim.colonists)
    # Only the colonist out of place (A, 20 cells off) is moved; the others are already at the rally point.
    assert [c["pawn_id"] for c in rim.called("order_pawn") if c["order"] == "move"] == ["HumanA"]
    assert ctx.chunk_hours == COMBAT_CHUNK_HOURS


def test_far_raid_is_watched_not_fought(tmp_path):
    rim = colony()
    rim.threats = [raider("R1", 99, 99), {"kind": "pawn", "threatKind": "animal", "position": {"x": 51, "z": 51}}]
    ctx = ctx_for(rim, tmp_path)
    manager = DefenseManager()
    manager.update(ctx)
    assert rim.called("set_pawn_drafted") == []
    # Its raid letter counts as handled: the raiders are on the map, and will be fought when near.
    assert manager.on_event(ctx, Event("threatLetter", 1, "run", "Raid")) is True


def test_threat_letter_without_hostiles_is_not_claimed(tmp_path):
    rim = colony()
    assert DefenseManager().on_event(ctx_for(rim, tmp_path), Event("threatLetter", 1, "run", "Siege coming")) is False


def test_downed_raiders_and_predators_dont_count(tmp_path):
    rim = colony()
    rim.threats = [raider("R1", 55, 55, downed=True), {"kind": "pawn", "threatKind": "animal", "position": {"x": 51, "z": 51}}]
    DefenseManager().update(ctx_for(rim, tmp_path))
    assert rim.called("set_pawn_drafted") == []


def test_after_the_fight_undraft_and_rescue_the_downed(tmp_path):
    rim = colony()
    rim.colonists[0]["drafted"] = rim.colonists[1]["drafted"] = True
    rim.colonists[2]["downed"] = True
    manager = DefenseManager()
    manager.combat_since = 0
    manager.update(ctx_for(rim, tmp_path))
    assert [c["drafted"] for c in rim.called("set_pawn_drafted")] == [False, False]
    rescue = [c for c in rim.called("order_pawn") if c["order"] == "rescue"]
    assert rescue == [{"pawn_id": "HumanA", "order": "rescue", "target_id": "HumanC"}]
    assert manager.combat_since is None


def test_unarmed_colonists_pick_up_guns_first(tmp_path):
    rim = colony()
    rim.colonists[0]["gear"]["equipment"] = []
    rim.colonists[1]["gear"]["equipment"] = []
    rim.weapons = [
        {"id": "Knife1", "def": "MeleeWeapon_Knife", "forbidden": False},
        {"id": "Rifle1", "def": "Gun_BoltActionRifle", "forbidden": True},
    ]
    DefenseManager().update(ctx_for(rim, tmp_path))
    assert rim.called("designate") == [{"kind": "unforbid", "thing_ids": ["Rifle1"]}]
    equips = [(c["pawn_id"], c["target_id"]) for c in rim.called("order_pawn") if c["order"] == "equip"]
    assert equips == [("HumanA", "Rifle1"), ("HumanB", "Knife1")]


def test_a_long_fight_raises_an_incident(tmp_path):
    rim = colony()
    rim.threats = [raider("R1", 55, 55)]
    rim.tick = 9 * 2500
    manager = DefenseManager()
    manager.combat_since = 0
    ctx = ctx_for(rim, tmp_path)
    manager.update(ctx)
    assert [i.kind for i in ctx.incidents] == ["longFight"]


def test_raid_in_the_runtime_needs_no_escalation_and_runs_short_chunks(tmp_path):
    rim = colony()
    rim.threats = [raider("R1", 60, 60)]
    rim.run_script = [{"status": "stopped", "events": [
        {"kind": "threatLetter", "tick": 10, "detail": "Raid"}, {"kind": "hostiles", "tick": 10}]}]
    rt = Runtime(rim, tmp_path / "run", managers=[DefenseManager(), ThreatsManager()], tripwires=[], echo=False)
    assert rt.run(1) == "done"
    assert not (tmp_path / "run" / "incidents").exists()
    hours = [c["hours"] for c in rim.called("advance")]
    assert hours[0] == COMBAT_CHUNK_HOURS or hours[1] == COMBAT_CHUNK_HOURS
