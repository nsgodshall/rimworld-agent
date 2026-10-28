"""Evaluation: replay a baseline save with the current code, score the colony, and compare runs.

    uv run python -m rimagent eval --save rimagent-start --days 3 --label baseline
    uv run python -m rimagent evals                      # every evaluation so far, oldest first

A score says how the colony did; autonomy (escalations, their estimated API cost, halts) says how much help the code
needed. RimWorld's storyteller is random, so compare several trials, not single runs.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rimsdk import RimClient, errors

from .incidents import Escalator
from .manager import TICKS_PER_HOUR
from .runtime import Runtime
from .snapshot import Snapshot

TICKS_PER_DAY = 24 * TICKS_PER_HOUR
SAMPLE_EVERY_HOURS = 6

# Score weights (sum 100). Each part is a fraction 0..1. Version 2 added production, progress and
# busy, after version 1 gave 95.7 to a colony living on its starting rations with nothing to do.
SCORE_VERSION = 2
WEIGHTS = {
    "survival": 30,    # colonists alive at the end
    "food": 15,        # samples after day one with FOOD_OK_DAYS of stored food
    "production": 15,  # food the colony made: OWN_FOOD_PER_COLONIST nutrition each, not counting rations
    "mood": 10,        # average mood
    "shelter": 10,     # beds per colonist
    "progress": 10,    # research finished and buildings built during the run
    "busy": 5,         # colonist-samples not idle
    "completion": 5,   # planned days actually played
}
FOOD_OK_DAYS = 2.0
OWN_FOOD_PER_COLONIST = 6.0  # nutrition: about three days' eating
STARTER_FOOD = {"MealSurvivalPack"}  # what scenarios hand out; can't be made early
RESEARCH_TARGET = 2
BUILDINGS_TARGET = 15


@dataclass
class EvalConfig:
    save: str
    days: float
    label: str = ""
    chunk_hours: float = 2.0
    speed: str | None = None
    max_escalations: int = 5
    # The colony that's loaded when an eval starts is saved here first. Timestamped, so a second eval
    # never overwrites the backup of a colony that mattered with a copy of the last baseline.
    backup: str = field(default_factory=lambda: f"rimagent-before-eval-{datetime.now():%Y%m%d-%H%M%S}")


@dataclass
class Sampler:
    """Records colony vitals every SAMPLE_EVERY_HOURS of game time; used as a Runtime observer."""

    samples: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, snap: Snapshot) -> None:
        if self.samples and snap.tick - self.samples[-1]["tick"] < SAMPLE_EVERY_HOURS * TICKS_PER_HOUR:
            return
        colony = snap.colony
        idle = next((a for a in snap.alerts if a.get("type") == "Alert_ColonistsIdle"), None)
        self.samples.append({
            "tick": snap.tick,
            "colonists": len(snap.colonists),
            "downed": (colony.get("medical") or {}).get("downed", 0),
            "mood": (colony.get("mood") or {}).get("average"),
            "foodDays": snap.food_days,
            "hostiles": snap.hostiles,
            "idle": (idle.get("culpritCount") or 1) if idle else 0,
        })


# --- the game side ---------------------------------------------------------------------------


def load_baseline(rim: RimClient, cfg: EvalConfig, say=print) -> None:
    """Load cfg.save, saving whatever colony is loaded to cfg.backup first."""
    loaded = rim.get_game_context().data.get("programState") == "Playing"
    kwargs = {"save_first": cfg.backup, "overwrite": True} if loaded else {}
    op = rim.wait_operation(rim.load_game(name=cfg.save, wait_seconds=30, **kwargs), timeout=900)
    while op.get("state") == "awaitingConfirmation":
        say(f"RimWorld is asking about loading {cfg.save}: {op.get('confirmation', {}).get('message')!r}. Answer it in game.")
        time.sleep(5)
        op = rim.get_operation(op["operationId"], wait_seconds=30).data
    if op.get("state") != "succeeded":
        raise RuntimeError(f"Loading {cfg.save} ended {op.get('state')}: {op.get('message')}")
    rim.wait_until_ready()


def final_metrics(rim: RimClient, snap: Snapshot) -> dict[str, Any]:
    beds = rim.list_buildings(category="bed", limit=200).data.get("buildings") or []
    buildings = sum(len(p.data.get("buildings") or []) for p in rim.pages(rim.list_buildings, limit=200))
    research = sum(sum(1 for r in p.data.get("projects") or [] if r.get("finished")) for p in rim.pages(rim.get_research, limit=200))
    fields = snap.zones_of("growing")
    # Anything with nutrition: meals (FoodMeals), but also raw crops (PlantFoodRaw) and meat (MeatRaw).
    food = [r for r in rim.list_resources().data.get("resources") or [] if (r.get("estimatedNutrition") or 0) > 0]
    return {
        "tick": snap.tick,
        "colonists": len(snap.colonists),
        "ownFood": round(sum(r.get("estimatedNutrition") or 0 for r in food if r.get("defName") not in STARTER_FOOD), 1),
        "beds": len(beds),
        "buildings": buildings,
        "researchFinished": research,
        "fieldCells": sum(z.get("cellCount", 0) for z in fields),
        "sownCells": sum((z.get("growing") or {}).get("sown", 0) for z in fields),
        "foodDays": snap.food_days,
        "mood": (snap.colony.get("mood") or {}).get("average"),
    }


# --- scoring (pure: unit-tested) ---------------------------------------------------------------


def score(start: dict[str, Any], end: dict[str, Any], samples: list[dict[str, Any]], days: float) -> dict[str, Any]:
    first_day = start["tick"] + TICKS_PER_DAY
    food = [s["foodDays"] for s in samples if s["tick"] >= first_day and s["foodDays"] is not None]
    moods = [s["mood"] for s in samples if s["mood"] is not None]
    played = (end["tick"] - start["tick"]) / TICKS_PER_DAY
    colonist_samples = sum(s["colonists"] for s in samples)
    research = end.get("researchFinished", 0) - start.get("researchFinished", 0)
    built = end.get("buildings", 0) - start.get("buildings", 0)
    parts = {
        "survival": min(1.0, end["colonists"] / start["colonists"]) if start["colonists"] else 0.0,
        # Day one is setup: the game counts only stored food, and storage doesn't exist yet.
        "food": sum(d >= FOOD_OK_DAYS for d in food) / len(food) if food else 1.0,
        "production": min(1.0, end.get("ownFood", 0) / (OWN_FOOD_PER_COLONIST * end["colonists"])) if end["colonists"] else 0.0,
        "mood": sum(moods) / len(moods) if moods else 0.0,
        "shelter": min(1.0, end["beds"] / end["colonists"]) if end["colonists"] else 0.0,
        "progress": 0.5 * min(1.0, max(0, research) / RESEARCH_TARGET) + 0.5 * min(1.0, max(0, built) / BUILDINGS_TARGET),
        "busy": 1 - min(1.0, sum(s.get("idle", 0) for s in samples) / colonist_samples) if colonist_samples else 0.0,
        "completion": min(1.0, played / days) if days else 0.0,
    }
    total = sum(WEIGHTS[k] * v for k, v in parts.items())
    return {"version": SCORE_VERSION, "total": round(total, 1), "parts": {k: round(v, 3) for k, v in parts.items()},
            "daysPlayed": round(played, 2)}


def autonomy(journal: Path) -> dict[str, Any]:
    """What the run needed from outside: incidents by kind, fixing sessions, their estimated API cost
    (Claude Code's total_cost_usd: billing with an API key, plan usage with a subscription)."""
    incidents: dict[str, int] = {}
    escalations = resumed = 0
    cost = 0.0
    for line in journal.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry["kind"] == "incident":
            kind = entry["summary"].split(":")[0]
            incidents[kind] = incidents.get(kind, 0) + 1
        elif entry["kind"] == "escalation":
            # One "Escalating ..." entry per session started; the outcome entry follows it.
            escalations += entry["summary"].startswith("Escalating")
            resumed += entry.get("resume") is True
            cost += entry.get("cost_usd") or 0.0
    return {"incidents": incidents, "escalations": escalations, "resumed": resumed, "costUsd": round(cost, 3)}


# --- running and comparing ---------------------------------------------------------------------


def code_version(repo: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True).stdout.strip()

    return {"commit": git("rev-parse", "--short", "HEAD"), "dirty": bool(git("status", "--porcelain", "src"))}


def run_eval(rim: RimClient, cfg: EvalConfig, run_dir: Path, escalator: Escalator | None, repo: Path) -> dict[str, Any]:
    load_baseline(rim, cfg)
    sampler = Sampler()
    runtime = Runtime(rim, run_dir, chunk_hours=cfg.chunk_hours, speed=cfg.speed, escalator=escalator,
                      max_escalations=cfg.max_escalations, observers=[sampler])
    start = final_metrics(rim, Snapshot(rim))  # the same measures, before any code acts
    started = time.time()
    reason = runtime.run(cfg.days * 24)
    if not start["colonists"]:
        # A save from a game's first moments has the colonists still in their drop pods.
        start["colonists"] = next((s["colonists"] for s in sampler.samples if s["colonists"]), 0)
    end = final_metrics(rim, Snapshot(rim))
    result = {
        "label": cfg.label,
        "save": cfg.save,
        "days": cfg.days,
        "started": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
        "wallSeconds": round(time.time() - started),
        "code": code_version(repo),
        "managers": [m.name for m in runtime.managers],
        "endReason": reason,
        "score": score(start, end, sampler.samples, cfg.days),
        "autonomy": autonomy(runtime.journal.path),
        "start": start,
        "end": end,
        "samples": sampler.samples,
    }
    (run_dir / "eval.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def compare(runs: Path) -> str:
    rows = []
    for path in sorted(runs.glob("*/eval.json")):
        r = json.loads(path.read_text(encoding="utf-8"))
        p, a = r["score"]["parts"], r["autonomy"]
        part = lambda k: f"{p[k]:.2f}" if k in p else "-"
        rows.append([
            path.parent.name, r["label"] or "-", f"{r['code']['commit']}{'+' if r['code']['dirty'] else ''}",
            f"{r['score']['daysPlayed']}/{r['days']}", r["endReason"],
            f"{r['score']['total']} (v{r['score'].get('version', 1)})", *(part(k) for k in WEIGHTS),
            str(a["escalations"]), f"${a['costUsd']:.2f}", ",".join(r["managers"]),
        ])
    head = ["run", "label", "code", "days", "end", "score", "surv", "food", "prod", "mood", "shelter", "progress",
            "busy", "compl", "esc", "est. API $", "managers"]
    if not rows:
        return "No evaluations yet: uv run python -m rimagent eval --save <name> --days N"
    widths = [max(len(str(x)) for x in col) for col in zip(head, *rows)]
    return "\n".join("  ".join(str(c).ljust(w) for c, w in zip(row, widths)) for row in [head, *rows])
