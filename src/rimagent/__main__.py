"""Run the colony runtime.

    uv run python -m rimagent run --hours 24                    # play; stop on incidents
    uv run python -m rimagent run --hours 24 --escalate claude  # play; Claude Code fixes the code on incidents
    uv run python -m rimagent run --dry-run                     # one cycle against the live game, changing nothing
    uv run python -m rimagent inspect --tools                   # read the live game (see inspect --help)
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
    run.add_argument("--max-escalations", type=int, default=5, help="fixing sessions allowed per run")
    run.add_argument("--budget-usd", type=float, default=3.0, help="spending cap per fixing session")
    run.add_argument("--model", help="model for fixing sessions (Claude Code's default if unset)")
    inspect = sub.add_parser("inspect", help="read-only access to the live game", add_help=False)
    inspect.add_argument("rest", nargs=argparse.REMAINDER)
    raw = sys.argv[1:] if argv is None else argv
    if raw[:1] == ["inspect"]:
        from .inspect_cli import main as inspect_main

        return inspect_main(raw[1:], focus_wait=600.0)
    args = parser.parse_args(raw)

    run_dir = RUNS / datetime.now().strftime("%Y%m%d-%H%M%S")
    with RimClient.connect(focus_wait=args.focus_wait) as rim:
        if args.dry_run:
            dry = DryRunClient(rim)
            runtime = Runtime(dry, run_dir)
            ok = runtime.cycle(Snapshot(dry))
            print(f"\nWould make {len(dry.planned)} changes:")
            for name, call_args in dry.planned:
                print(f"  {name} {json.dumps(call_args)}")
            return 0 if ok else 1
        escalator = None
        if args.escalate == "claude":
            from .escalate import ClaudeEscalator

            escalator = ClaudeEscalator(model=args.model, budget_usd=args.budget_usd)
        runtime = Runtime(rim, run_dir, chunk_hours=args.chunk, speed=args.speed, escalator=escalator,
                          max_escalations=args.max_escalations)
        reason = runtime.run(args.hours)
        print(f"\nStopped: {reason}. Journal: {runtime.journal.path}")
        return 0 if reason == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
