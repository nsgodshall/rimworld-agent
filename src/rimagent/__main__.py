"""Run the colony runtime.

    uv run python -m rimagent run --hours 24                    # play; stop on incidents
    uv run python -m rimagent run --hours 24 --escalate claude  # play; Claude Code fixes the code on incidents
    uv run python -m rimagent run --dry-run                     # one cycle against the live game, changing nothing
    uv run python -m rimagent inspect --tools                   # read the live game (see inspect --help)
    uv run python -m rimagent watch                             # a live view of the newest run (TUI)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rimsdk import RimClient

from .dryrun import DryRunClient
from .runtime import Runtime
from .snapshot import Snapshot

RUNS = Path("runs")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rimagent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="play the loaded colony")
    run.add_argument("--hours", type=float, default=24.0, help="in-game hours to play")
    run.add_argument("--chunk", type=float, default=2.0, help="in-game hours per time run (max 24)")
    run.add_argument("--speed", choices=["Normal", "Fast", "Superfast"], help="speed while time runs (RimMCP default: Superfast)")
    run.add_argument("--dry-run", action="store_true", help="one cycle, reads only: print what managers would change")
    run.add_argument("--focus-wait", type=float, default=600.0, help="seconds to wait for an unfocused RimWorld")
    run.add_argument("--escalate", choices=["halt", "claude"], default="halt", help="who handles incidents")
    run.add_argument("--no-alerts", action="store_true", help="don't halt on unclaimed game alerts (for focused tests)")
    run.add_argument("--max-escalations", type=int, default=5, help="fixing sessions allowed per run")
    run.add_argument("--budget-usd", type=float, default=3.0, help="cap per fixing session, in estimated API dollars (plan usage on a subscription)")
    run.add_argument("--model", help="model for fixing sessions (Claude Code's default if unset)")
    ev = sub.add_parser("eval", help="load a baseline save, play it with the current code, and score it")
    start = ev.add_mutually_exclusive_group(required=True)
    start.add_argument("--save", help="save to start from, e.g. rimagent-landed-named")
    start.add_argument("--new", help="a new colony from the main menu: SEED:BIOME[:STORYTELLER[:DIFFICULTY]]")
    ev.add_argument("--days", type=float, default=3.0, help="in-game days to play")
    ev.add_argument("--label", default="", help="a name for this run in `evals`")
    ev.add_argument("--chunk", type=float, default=2.0)
    ev.add_argument("--speed", choices=["Normal", "Fast", "Superfast"])
    ev.add_argument("--escalate", choices=["halt", "claude"], default="halt")
    ev.add_argument("--max-escalations", type=int, default=5)
    ev.add_argument("--budget-usd", type=float, default=3.0, help="as for run --budget-usd")
    ev.add_argument("--model")
    ev.add_argument("--focus-wait", type=float, default=600.0)
    sub.add_parser("evals", help="compare every evaluation so far")
    es = sub.add_parser("evalset", help="evaluate several new colonies in a row and summarise")
    es.add_argument("starts", nargs="+", help="SEED:BIOME[:STORYTELLER[:DIFFICULTY]] each")
    es.add_argument("--days", type=float, default=14.0)
    es.add_argument("--label", default="set")
    es.add_argument("--escalate", choices=["halt", "claude"], default="halt")
    es.add_argument("--max-escalations", type=int, default=6)
    es.add_argument("--budget-usd", type=float, default=3.0)
    es.add_argument("--model")
    es.add_argument("--focus-wait", type=float, default=600.0)
    watch = sub.add_parser("watch", help="live view of a run: the runtime's picture of the game, and its commands")
    watch.add_argument("run_dir", nargs="?", help="a runs/<dir> (default: follow the newest)")
    inspect = sub.add_parser("inspect", help="read-only access to the live game", add_help=False)
    inspect.add_argument("rest", nargs=argparse.REMAINDER)
    raw = sys.argv[1:] if argv is None else argv
    if raw[:1] == ["inspect"]:
        from .inspect_cli import main as inspect_main

        return inspect_main(raw[1:], focus_wait=600.0)
    args = parser.parse_args(raw)
    if args.command == "watch":
        from .watch import main as watch_main

        return watch_main([args.run_dir] if args.run_dir else [])
    if args.command == "evals":
        from .evaluate import compare

        print(compare(RUNS))
        return 0

    run_dir = RUNS / datetime.now().strftime("%Y%m%d-%H%M%S")
    escalator = None
    if args.escalate == "claude":
        from .escalate import ClaudeEscalator

        escalator = ClaudeEscalator(model=args.model, budget_usd=args.budget_usd)

    if args.command == "evalset":
        from .escalate import REPO
        from .evaluate import EvalConfig, run_eval, summarise_set

        results = []
        for spec in args.starts:
            seed = spec.split(":")[0]
            one_dir = RUNS / f"{datetime.now():%Y%m%d-%H%M%S}-{seed}"
            cfg = EvalConfig(None, args.days, f"{args.label}-{seed}", max_escalations=args.max_escalations, new=spec)
            print(f"\n=== {spec}: {one_dir}", flush=True)
            try:
                with RimClient.connect(focus_wait=args.focus_wait) as rim:
                    result = run_eval(rim, cfg, one_dir, escalator, REPO)
            except Exception as exc:  # one start failing to set up shouldn't stop the set
                print(f"{spec} failed: {type(exc).__name__}: {exc}", flush=True)
                results.append({"label": cfg.label, "new": spec, "error": str(exc)})
                continue
            results.append(result)
            print(f"{spec}: {result['score']['total']} over {result['score']['daysPlayed']} days ({result['endReason']})", flush=True)
        print("\n" + summarise_set(results))
        return 0
    if args.command == "eval":
        from .escalate import REPO
        from .evaluate import EvalConfig, run_eval

        cfg = EvalConfig(args.save, args.days, args.label, args.chunk, args.speed, args.max_escalations, new=args.new)
        with RimClient.connect(focus_wait=args.focus_wait) as rim:
            result = run_eval(rim, cfg, run_dir, escalator, REPO)
        s, a = result["score"], result["autonomy"]
        print(f"\nScore {s['total']}/100 over {s['daysPlayed']} of {cfg.days} days ({result['endReason']}): {s['parts']}")
        print(f"Autonomy: {a['escalations']} escalations ({a['resumed']} resumed, est. API cost ${a['costUsd']:.2f}), incidents {a['incidents']}")
        print(f"Saved {run_dir / 'eval.json'}")
        return 0 if result["endReason"] == "done" else 1

    with RimClient.connect(focus_wait=args.focus_wait) as rim:
        if args.dry_run:
            dry = DryRunClient(rim)
            runtime = Runtime(dry, run_dir)
            ok = runtime.cycle(Snapshot(dry))
            print(f"\nWould make {len(dry.planned)} changes:")
            for name, call_args in dry.planned:
                print(f"  {name} {json.dumps(call_args)}")
            return 0 if ok else 1
        runtime = Runtime(rim, run_dir, chunk_hours=args.chunk, speed=args.speed, escalator=escalator,
                          max_escalations=args.max_escalations, watch_alerts=not args.no_alerts)
        reason = runtime.run(args.hours)
        print(f"\nStopped: {reason}. Journal: {runtime.journal.path}")
        return 0 if reason == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
