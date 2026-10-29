import json

from rimagent.evaluate import TICKS_PER_DAY, EvalConfig, Sampler, autonomy, compare, run_eval, score

from .fakegame import FakeRim


def sample(tick, food=5.0, mood=0.6, colonists=3):
    return {"tick": tick, "colonists": colonists, "downed": 0, "mood": mood, "foodDays": food, "hostiles": 0}


def test_score_productive_run():
    start = {"tick": 0, "colonists": 3, "researchFinished": 10, "buildings": 5}
    end = {"tick": 3 * TICKS_PER_DAY, "colonists": 3, "beds": 3, "ownFood": 30, "researchFinished": 12, "buildings": 20}
    samples = [sample(t * TICKS_PER_DAY // 4) for t in range(13)]
    s = score(start, end, samples, days=3)
    assert s["parts"] == {"survival": 1.0, "food": 1.0, "production": 1.0, "mood": 0.6, "shelter": 1.0,
                          "progress": 1.0, "busy": 1.0, "completion": 1.0}
    assert s["total"] == 100 - 25 * 0.4 and s["version"] == 3


def test_rations_and_idleness_no_longer_score_well():
    """The run score v1 gave 95.7: alive, fed from starting rations, beds, and everyone idle."""
    start = {"tick": 0, "colonists": 3, "researchFinished": 10, "buildings": 0}
    end = {"tick": 2 * TICKS_PER_DAY, "colonists": 3, "beds": 3, "ownFood": 0.5, "researchFinished": 10, "buildings": 3,
           "sleptOutside": 3}  # its beds were in the open
    samples = [{**sample(t * TICKS_PER_DAY // 4, mood=0.72), "idle": 3 if t > 4 else 0} for t in range(9)]
    s = score(start, end, samples, days=2)
    assert s["parts"]["production"] < 0.05 and s["parts"]["progress"] == 0.1 and s["parts"]["busy"] == 0.556
    assert s["total"] < 75


def test_score_penalises_deaths_hunger_and_stopping_early():
    start = {"tick": 0, "colonists": 3}
    end = {"tick": TICKS_PER_DAY * 3 // 2, "colonists": 2, "beds": 1}
    # Day one's empty storage doesn't count; after it, food is short half the time.
    samples = [sample(0, food=0), sample(TICKS_PER_DAY, food=1), sample(TICKS_PER_DAY + 1, food=5)]
    s = score(start, end, samples, days=3)
    assert s["parts"]["survival"] == round(2 / 3, 3)
    assert s["parts"]["food"] == 0.5
    assert s["parts"]["shelter"] == 0.75  # a bed for half of them; nobody known to sleep outside
    assert s["parts"]["completion"] == 0.5


def test_mood_weighs_heavily_and_sleeping_outside_costs_shelter():
    start = {"tick": 0, "colonists": 3}
    end = {"tick": 3 * TICKS_PER_DAY, "colonists": 3, "beds": 3, "sleptOutside": 3}
    happy = score(start, end, [sample(0, mood=0.9)], days=3)
    glum = score(start, end, [sample(0, mood=0.3)], days=3)
    assert happy["total"] - glum["total"] == 15.0  # 0.6 of mood's 25
    assert happy["parts"]["shelter"] == 0.5  # beds, but everyone slept outside


def test_sampler_keeps_one_sample_per_six_hours():
    rim, sampler = FakeRim(), Sampler()
    from rimagent import Snapshot

    for tick in (0, 5000, 15000, 16000, 30000):
        rim.tick = tick
        sampler(Snapshot(rim))
    assert [s["tick"] for s in sampler.samples] == [0, 15000, 30000]


def test_autonomy_counts_sessions_resumes_and_cost(tmp_path):
    journal = tmp_path / "journal.jsonl"
    entries = [
        {"kind": "incident", "summary": "unhandledEvent: No manager handles hostiles"},
        {"kind": "escalation", "summary": "Escalating unhandledEvent:hostiles (1/5)..."},
        {"kind": "escalation", "summary": "Added defense.", "resume": True, "cost_usd": 0.5},
        {"kind": "incident", "summary": "unhandledAlert: beds"},
        {"kind": "escalation", "summary": "Escalation budget (1) used up.", "resume": False},
    ]
    journal.write_text("\n".join(json.dumps(e) for e in entries))
    assert autonomy(journal) == {"incidents": {"unhandledEvent": 1, "unhandledAlert": 1},
                                 "escalations": 1, "resumed": 1, "costUsd": 0.5}


def test_colonists_still_in_drop_pods_are_not_a_lost_colony(tmp_path):
    rim = FakeRim()
    landed = rim.colonists
    rim.colonists = []
    real_advance = rim.advance

    def land(hours, **kw):
        rim.colonists = landed
        return real_advance(hours, **kw)

    rim.advance = land
    result = run_eval(rim, EvalConfig(save="base", days=1, chunk_hours=1), tmp_path / "runs" / "r", None, tmp_path)
    assert result["endReason"] == "done"
    assert result["start"]["colonists"] == 3 and result["score"]["parts"]["survival"] == 1.0


def test_run_eval_loads_the_save_backs_up_and_scores(tmp_path, monkeypatch):
    rim = FakeRim()
    rim.tick = 99999  # mid-game when the eval starts
    cfg = EvalConfig(save="base", days=1, label="t", chunk_hours=6)
    result = run_eval(rim, cfg, tmp_path / "runs" / "r1", None, tmp_path)
    (load,) = rim.called("load_game")
    assert load["name"] == "base" and load["save_first"].startswith("rimagent-before-eval-")
    assert result["start"]["tick"] == 0 and result["endReason"] == "done"
    assert result["score"]["daysPlayed"] == 1.0
    assert result["end"]["researchFinished"] == 1
    assert {"food", "beds", "threats"} <= set(result["managers"])
    assert (tmp_path / "runs" / "r1" / "eval.json").exists()
    table = compare(tmp_path / "runs")
    assert "r1" in table and "score" in table.splitlines()[0]
