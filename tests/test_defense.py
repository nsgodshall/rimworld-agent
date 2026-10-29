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
    rim.resources = [{"defName": "WoodLog", "count": 400}, {"defName": "Steel", "count": 400}]
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
    # No cover on this bare map: a group at the base, two cells apart.
    moves = {c["pawn_id"]: (c["x"], c["z"]) for c in rim.called("order_pawn") if c["order"] == "move"}
    assert moves == {"HumanA": (50, 50), "HumanB": (52, 50), "HumanC": (48, 50)}
    assert ctx.chunk_hours == COMBAT_CHUNK_HOURS


def test_raiders_anywhere_on_the_map_bring_everyone_home(tmp_path):
    """The second live raid: raiders 70 cells away, a colonist working out by them, no defense at all."""
    rim = colony()
    rim.threats = [raider("R1", 99, 99), {"kind": "pawn", "threatKind": "animal", "position": {"x": 51, "z": 51}}]
    rim.colonists[0]["position"] = {"x": 95, "y": 0, "z": 95}
    ctx = ctx_for(rim, tmp_path)
    manager = DefenseManager()
    manager.update(ctx)
    assert all(p["drafted"] for p in rim.colonists)
    assert "HumanA" in [c["pawn_id"] for c in rim.called("order_pawn") if c["order"] == "move"]
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


def test_rescuers_are_chosen_after_undrafting(tmp_path):
    """The live raid: one colonist still drafted, two downed. Undrafting must free them to carry."""
    rim = colony()
    rim.colonists[0]["drafted"] = True
    rim.colonists[1]["downed"] = rim.colonists[2]["downed"] = True
    manager = DefenseManager()
    manager.combat_since = 0
    ctx = ctx_for(rim, tmp_path)
    manager.update(ctx)
    rescues = [(c["pawn_id"], c["target_id"]) for c in rim.called("order_pawn") if c["order"] == "rescue"]
    assert rescues == [("HumanA", "HumanB")]
    assert ctx.incidents == []  # one helper for two downed: the second waits for the next cycle


def test_nobody_to_carry_the_downed_is_an_incident(tmp_path):
    rim = colony()
    for p in rim.colonists:
        p["downed"] = True
    ctx = ctx_for(rim, tmp_path)
    DefenseManager().update(ctx)
    assert [i.kind for i in ctx.incidents] == ["noRescuer"]


def test_shooters_take_cover_facing_the_raiders_and_melee_waits_behind(tmp_path):
    rim = colony()
    rim.colonists[2]["gear"]["equipment"] = [{"def": {"defName": "MeleeWeapon_Knife"}}]
    for z in range(45, 56):
        rim.cells[(53, z)] = "t"  # a line of trees east of the base
    rim.threats = [raider("R1", 80, 50)]  # raiders to the east
    DefenseManager().update(ctx_for(rim, tmp_path))
    moves = {c["pawn_id"]: (c["x"], c["z"]) for c in rim.called("order_pawn") if c["order"] == "move"}
    for shooter in ("HumanA", "HumanB"):
        x, z = moves.get(shooter, (50, 50))
        assert rim.cells[(x + 1, z)] == "t", f"{shooter} at {(x, z)} has no tree between it and the raiders"
    assert moves["HumanC"][0] < 50  # the knife waits west of the base, away from the shooting


def test_fighters_stand_two_cells_apart_against_grenades(tmp_path):
    rim = colony()
    for z in range(40, 61):
        rim.cells[(53, z)] = "t"
    rim.threats = [raider("R1", 80, 50)]
    for p in rim.colonists:
        p["position"] = {"x": 10, "y": 0, "z": 10}  # far off, so every fighter gets a move order
    DefenseManager().update(ctx_for(rim, tmp_path))
    cells = [(c["x"], c["z"]) for c in rim.called("order_pawn") if c["order"] == "move"]
    assert len(cells) == 3
    assert all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) >= 2 for i, a in enumerate(cells) for b in cells[i + 1:])


def test_between_fights_a_barricade_line_goes_up_on_each_side(tmp_path):
    rim = colony()
    DefenseManager().update(ctx_for(rim, tmp_path))
    (call,) = rim.called("place_blueprint")
    placed = {(p["x"], p["z"]) for p in call["placements"]}
    assert {(p["def"], p.get("stuff")) for p in call["placements"]} == {("Barricade", "WoodLog")}
    # Five cells across each side, four cells out from the stockpile at (50, 50).
    assert placed == ({(x, 54) for x in range(48, 53)} | {(x, 46) for x in range(48, 53)}
                      | {(54, z) for z in range(48, 53)} | {(46, z) for z in range(48, 53)})


def test_barricades_are_planned_once_and_skip_fields(tmp_path):
    rim = colony()
    for x in range(40, 61):
        rim.cells[(x, 54)] = ":"  # rich soil north of the base: a field's place, not a barricade's
    DefenseManager().update(ctx_for(rim, tmp_path))
    DefenseManager().update(ctx_for(rim, tmp_path))  # re-created, as on reload
    first, second = rim.called("place_blueprint")
    assert first["placements"] == second["placements"] and len(rim.blueprints) == 20
    north = {(p["x"], p["z"]) for p in first["placements"] if p["z"] > 53}
    assert north == {(x, 55) for x in range(48, 53)}


def test_built_barricades_are_left_alone_and_give_shooters_cover(tmp_path):
    rim = colony()
    DefenseManager().update(ctx_for(rim, tmp_path))
    for n, p in enumerate(rim.blueprints):
        rim.cells[(p["x"], p["z"])] = "b"
        rim.buildings.append({"ids": {"id": f"Barricade{n}"}, "def": {"defName": "Barricade"},
                              "position": {"x": p["x"], "y": 0, "z": p["z"]}})
    rim.blueprints = []
    rim.calls = []
    DefenseManager().update(ctx_for(rim, tmp_path))
    assert rim.called("place_blueprint") == []

    rim.threats = [raider("R1", 80, 50)]  # raiders to the east
    DefenseManager().update(ctx_for(rim, tmp_path))
    moves = [(c["x"], c["z"]) for c in rim.called("order_pawn") if c["order"] == "move"]
    assert moves and all(rim.cells[(x + 1, z)] == "b" for x, z in moves)


def test_need_defenses_alert_no_longer_halts(tmp_path):
    rim = colony()
    rim.alerts = [{"type": "Alert_NeedDefenses", "label": "Need defenses", "priority": "High"}]
    rt = Runtime(rim, tmp_path / "run", managers=[DefenseManager()], tripwires=[], echo=False)
    assert rt.run(24) == "done"
    assert rim.called("place_blueprint")


def test_a_predator_hunting_a_colonist_is_fought(tmp_path):
    """Trial 7: "Timber wolf hunting Miyazaki" was an unhandled threat letter; roaming predators aren't fought."""
    rim = colony()
    wolf = {"ids": {"id": "Wolf1"}, "kind": "pawn", "threatKind": "animal", "position": {"x": 60, "y": 0, "z": 55},
            "downed": False, "combat": {"equipment": [], "currentJob": {"defName": "PredatorHunt", "report": "hunting."}}}
    rim.threats = [wolf]
    manager = DefenseManager()
    assert manager.on_event(ctx_for(rim, tmp_path), Event("threatLetter", 1, "run", "Timber wolf hunting Miyazaki")) is True
    assert all(p["drafted"] for p in rim.colonists)
    wolf["combat"]["currentJob"] = {"defName": "Wander"}
    rim.calls = []
    DefenseManager().update(ctx_for(rim, tmp_path))
    assert not [c for c in rim.called("set_pawn_drafted") if c["drafted"]]  # a wandering wolf is left alone
