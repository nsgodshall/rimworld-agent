"""Append-only JSONL record of a run: cycles, time runs, events, manager actions, incidents."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class Journal:
    def __init__(self, path: Path, echo: bool = True):
        self.path = path
        self.echo = echo
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, kind: str, **data: Any) -> None:
        entry = {"t": round(time.time(), 3), "kind": kind, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        if self.echo:
            tick = data.get("tick")
            head = f"[{tick:>7}]" if isinstance(tick, int) else "[       ]"
            body = data.get("message") or data.get("summary") or {k: v for k, v in data.items() if k != "tick"}
            who = f" {data['manager']}:" if "manager" in data else ""
            print(f"{head} {kind}{who} {body}", flush=True)
