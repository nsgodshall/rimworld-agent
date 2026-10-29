"""RimClient: the generated tool methods plus the helpers long-running scripts need."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from . import config, errors
from ._generated import MANIFEST_VERSION, GeneratedTools
from .manifest import Manifest, ToolSpec, build_request
from .result import Result
from .transport import HttpTransport, RetryPolicy

# Long-poll length for advance_time / get_advance / get_operation; the bridge caps it at 30s.
POLL_SECONDS = 30
# Polls in a row that may find a run paused without progress before advance() gives up on it.
# A window that forces a pause (the speed stays set) never ends a run: trial 4 sat 7 hours on one.
STALLED_POLLS = 3


@dataclass
class ManifestDrift:
    """Differences between the live game's tools and the ones this SDK was generated from."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.changed)


class RimClient(GeneratedTools):
    """Typed access to every RimMCP tool, e.g. `rim.get_colony_status()` or `rim.list_pawns(kind=...)`.

    Every method returns a `Result` (the reply's JSON dict, with `.data`, `.tick`, `.next_cursor`...)
    and raises a `rimsdk.errors.RimError` subclass when the game refuses or can't be reached.
    """

    def __init__(self, transport: HttpTransport, *, manifest: Manifest | None = None, read_only: bool = False):
        self.transport = transport
        self.manifest = manifest or Manifest.bundled()
        self.read_only = read_only

    @classmethod
    def connect(
        cls,
        url: str | None = None,
        token: str | None = None,
        *,
        read_only: bool = False,
        retry: RetryPolicy = RetryPolicy(),
        timeout: float = 100.0,
        focus_wait: float = 0.0,
    ) -> RimClient:
        """Connect using explicit values, else RIMCP_URL/RIMCP_TOKEN, else RimMCP's saved settings.

        focus_wait > 0 makes calls wait (up to that many seconds) for an unfocused RimWorld to be
        focused, rather than raising NotProcessing, for scripts run with Run in background off.
        """
        found = config.discover()
        transport = HttpTransport(
            url or found.url, token or found.token, timeout=timeout, retry=retry, focus_wait=focus_wait
        )
        return cls(transport, read_only=read_only)

    def __enter__(self) -> RimClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.transport.close()

    # --- calling tools ---------------------------------------------------------------------

    def _call(self, name: str, args: dict[str, Any]) -> Result:
        spec = self.manifest.tools.get(name)
        if spec is None:
            raise errors.NotFound(f"Unknown RimMCP tool {name!r} (SDK manifest {MANIFEST_VERSION}).")
        if self.read_only and not spec.read_only:
            raise errors.ReadOnlyViolation(f"{name} changes the game, and this client is read-only.")
        method, path, body = build_request(spec, args)
        return Result(self.transport.request(method, path, body))

    def call(self, name: str, **args: Any) -> Result:
        """Call a tool by its MCP name with its wire (camelCase) argument names."""
        return self._call(name, args)

    def spec(self, name: str) -> ToolSpec:
        return self.manifest.tools[name]

    # --- bridge-level routes ---------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self.transport.request("GET", "/health")

    def raw_manifest(self) -> dict[str, Any]:
        return self.transport.request("GET", "/v1/tools")

    def enabled_tools(self) -> set[str]:
        """Tools the player's access settings currently allow."""
        return {t["name"] for t in self.raw_manifest()["tools"] if t.get("name") and t.get("enabled")}

    def check_manifest(self) -> ManifestDrift:
        """Compare the live game's tools with the SDK's; regenerate with `python -m rimsdk.codegen` on drift."""
        live = Manifest.from_json(self.raw_manifest())
        drift = ManifestDrift(
            added=sorted(set(live.tools) - set(self.manifest.tools)),
            removed=sorted(set(self.manifest.tools) - set(live.tools)),
        )
        for name in sorted(set(live.tools) & set(self.manifest.tools)):
            a, b = live.tools[name], self.manifest.tools[name]
            if (a.method, a.path_template, a.query_keys, a.body_keys, a.input_schema) != (
                b.method, b.path_template, b.query_keys, b.body_keys, b.input_schema
            ):
                drift.changed.append(name)
        return drift

    def wait_until_ready(self, timeout: float = 120.0, interval: float = 2.0) -> dict[str, Any]:
        """Block until the bridge answers (e.g. while RimWorld starts up), returning /health."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self.health()
            except (errors.BridgeUnavailable, errors.GameBusy):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(interval)

    # --- paging, time, and operations ------------------------------------------------------

    def pages(self, method: Callable[..., Result], /, **kwargs: Any) -> Iterator[Result]:
        """Yield every page of a list tool, following nextCursor: `for page in rim.pages(rim.list_pawns): ...`"""
        cursor = kwargs.pop("cursor", None)
        while True:
            page = method(cursor=cursor, **kwargs)
            yield page
            cursor = page.next_cursor
            if cursor is None:
                return

    def advance(
        self,
        hours: float,
        *,
        speed: str | None = None,
        stop_on: list[str] | None = None,
        on_poll: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Run the game for `hours` (max 24) and block until the run ends; returns the run.

        The run's `status` is completed, stopped (a stopOn condition fired; see `stoppedBy`), or
        interrupted (paused, speed changed, game unloaded). `events` lists what happened.
        stop_on=None uses RimMCP's defaults (death, downed, injured, mentalBreak, hostiles, lowFood,
        threatLetter); [] runs to the end no matter what.

        A run the game holds paused without its speed changing (a window that forces a pause) would
        never end; after STALLED_POLLS such polls it is ended and returned as interrupted with
        endReason "forcedPause".
        """
        started = self.advance_time(
            hours=hours, speed=speed, stop_on=stop_on, request_id=uuid.uuid4().hex, wait_seconds=POLL_SECONDS
        )
        run = started.data
        stalled = 0
        while run.get("status") == "running":
            if on_poll:
                on_poll(run)
            last_tick = run.get("tick")
            polled = self.get_advance(run_id=run["id"], wait_seconds=POLL_SECONDS).data
            run = polled["run"]
            held = run.get("status") == "running" and (polled.get("time") or {}).get("paused") and run.get("tick") == last_tick
            stalled = stalled + 1 if held else 0
            if stalled >= STALLED_POLLS:
                ended = self.set_game_speed(speed="Paused").data.get("endedAdvance") or run
                return {**ended, "status": "interrupted", "endReason": "forcedPause"}
        return run

    def wait_operation(self, operation: Result | dict[str, Any] | str, timeout: float = 600.0) -> dict[str, Any]:
        """Block until a save/load/setup operation is done or waits on a question (awaitingConfirmation)."""
        op = operation.get("data", operation) if isinstance(operation, dict) else {"operationId": operation}
        deadline = time.monotonic() + timeout
        while not op.get("done") and op.get("state") != "awaitingConfirmation":
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Operation {op.get('operationId')} still {op.get('state')} after {timeout}s.")
            op = self.get_operation(op["operationId"], wait_seconds=POLL_SECONDS).data
        return op
