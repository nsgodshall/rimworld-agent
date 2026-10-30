from rimagent import Context, Snapshot
from rimagent.events import Event
from rimagent.journal import Journal
from rimagent.managers.graves import GravesManager, is_corpse_of

from .fakegame import FakeRim


def ctx_for(rim, tmp_path):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False))


# As advance_time reported it in run 20261030-002116, and find_things def=Corpse_Human showed the body.
DEATH = {"kind": "death", "tick": 349493, "pawn": {"id": "Human436", "name": "Parker 'Sparky' Strobeck"}, "detail": "died"}
SPARKY = {"id": "Corpse_Human57447", "def": "Corpse_Human", "label": "Sparky, Builder (dead)",
          "x": 50, "z": 52, "count": 1, "forbidden": False, "inStorage": False}
RAIDER = {"id": "Corpse_Human1", "def": "Corpse_Human", "label": "Jones, Waster (dead)",
          "x": 60, "z": 60, "count": 1, "forbidden": False, "inStorage": False}


def test_corpse_labels_match_the_colonists_nickname():
    assert is_corpse_of("Sparky, Builder (dead)", "Parker 'Sparky' Strobeck")
    assert is_corpse_of("Mia (dead)", "Mia")
    assert not is_corpse_of("Sparkle, Waster (dead)", "Parker 'Sparky' Strobeck")


def test_a_dead_colonist_gets_one_grave_south_of_the_base(tmp_path):
    rim = FakeRim()
    rim.corpses = [SPARKY, RAIDER]
    manager = GravesManager()
    assert manager.on_event(ctx_for(rim, tmp_path), Event.from_run(DEATH)) is True
    (placed,) = rim.called("place_blueprint")
    (grave,) = placed["placements"]
    assert grave["def"] == "Grave" and grave["z"] < 50
    manager.update(ctx_for(rim, tmp_path))  # again: the same spot, already satisfied
    assert rim.called("place_blueprint")[1]["placements"] == [grave]
    assert len(rim.blueprints) == 1


def test_once_buried_the_colonist_is_forgotten(tmp_path):
    rim = FakeRim()
    rim.corpses = [SPARKY]
    manager = GravesManager()
    manager.on_event(ctx_for(rim, tmp_path), Event.from_run(DEATH))
    rim.corpses = []  # in the grave: off the map
    manager.update(ctx_for(rim, tmp_path))
    manager.update(ctx_for(rim, tmp_path))
    assert len(rim.called("place_blueprint")) == 1
    assert manager.memory["dead"] == {}


def test_raiders_corpses_get_no_grave(tmp_path):
    rim = FakeRim()
    rim.corpses = [RAIDER]
    GravesManager().update(ctx_for(rim, tmp_path))
    assert rim.called("place_blueprint") == []


def test_a_forbidden_body_is_unforbidden_so_it_can_be_carried(tmp_path):
    rim = FakeRim()
    rim.corpses = [{**SPARKY, "forbidden": True}]
    GravesManager().on_event(ctx_for(rim, tmp_path), Event.from_run(DEATH))
    assert rim.called("designate") == [{"kind": "unforbid", "thing_ids": ["Corpse_Human57447"]}]
