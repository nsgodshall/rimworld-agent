"""A client that reads the real game but only records the changes it would make."""

from __future__ import annotations

from typing import Any

from rimsdk import Result, RimClient


class DryRunClient(RimClient):
    """Reads pass through; tools that change the game are logged to `planned` and answered with
    {"dryRun": true, "changed": false, "data": {}} so the caller can carry on."""

    def __init__(self, inner: RimClient):
        super().__init__(inner.transport, manifest=inner.manifest)
        self.planned: list[tuple[str, dict[str, Any]]] = []

    def _call(self, name: str, args: dict[str, Any]) -> Result:
        if self.manifest.tools[name].read_only:
            return super()._call(name, args)
        self.planned.append((name, {k: v for k, v in args.items() if v is not None}))
        return Result({"dryRun": True, "changed": False, "data": {}})
