from rimagent import Context, Snapshot
from rimagent.journal import Journal
from rimagent.managers.letters import LettersManager

from .fakegame import FakeRim


def ctx_for(rim, tmp_path, board=None):
    return Context(rim, Snapshot(rim), Journal(tmp_path / "j.jsonl", echo=False), board=board or {})


def joiner(expires=50000):
    """The letter that held trial 18 paused, as get_events detail=full showed it."""
    return {"id": 9, "label": "Wanderer joins: Humps", "type": "AcceptJoiner", "tick": 447000, "expiresInTicks": expires,
            "canDismiss": False, "revision": "f26a3ff8ec09a178",
            "options": [{"id": "1", "text": "Accept"}, {"id": "2", "text": "Reject"},
                        {"id": "3", "text": "Postpone", "disabledReason": "Unavailable."}]}


def test_a_joiner_is_turned_away_when_every_bedroom_is_taken(tmp_path):
    rim = FakeRim()
    rim.letters = [joiner()]
    LettersManager().update(ctx_for(rim, tmp_path, {"house_beds": 3}))
    assert rim.called("answer_letter") == [{"letter_id": 9, "option": "2", "revision": "f26a3ff8ec09a178"}]


def test_a_joiner_is_taken_in_when_there_is_a_free_bedroom(tmp_path):
    rim = FakeRim()
    rim.letters = [joiner()]
    LettersManager().update(ctx_for(rim, tmp_path, {"house_beds": 4}))
    assert rim.called("answer_letter")[0]["option"] == "1"


def test_another_must_answer_letter_about_to_expire_stops_the_run_once(tmp_path):
    rim = FakeRim()
    rim.letters = [{**joiner(expires=100), "type": "ChoiceLetter_Something", "label": "A choice"}]
    manager = LettersManager()
    ctx = ctx_for(rim, tmp_path)
    manager.update(ctx)
    manager.update(second := ctx_for(rim, tmp_path))
    assert [(i.kind, i.severity) for i in ctx.incidents] == [("letterNeedsAnswer", "halt")] and second.incidents == []
    assert rim.called("answer_letter") == []


def test_dismissable_letters_are_left_alone(tmp_path):
    rim = FakeRim()
    rim.letters = [{"id": 1, "label": "Raid", "type": "ThreatBig", "canDismiss": True}]
    LettersManager().update(ctx_for(rim, tmp_path))
    assert rim.called("answer_letter") == []
