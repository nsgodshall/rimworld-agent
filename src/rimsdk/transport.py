"""HTTP transport to the RimMCP bridge, with retries for the moments RimWorld is briefly busy."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

from . import errors


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 6
    first_delay: float = 0.5
    max_delay: float = 8.0

    def delays(self):
        delay = self.first_delay
        for _ in range(self.attempts - 1):
            yield delay
            delay = min(delay * 2, self.max_delay)


NO_RETRY = RetryPolicy(attempts=1)


class HttpTransport:
    # The bridge holds long-poll requests (waitSeconds) for up to 30s, and the proxy allows 100s.
    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        timeout: float = 100.0,
        retry: RetryPolicy = RetryPolicy(),
        focus_wait: float = 0.0,
    ):
        """focus_wait: with Run in background off, an unfocused RimWorld refuses every request;
        wait up to this many seconds for the player to focus it instead of raising NotProcessing."""
        self.base_url = base_url.rstrip("/")
        self.retry = retry
        self.focus_wait = focus_wait
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        delays = self.retry.delays()
        focus_deadline = None
        while True:
            try:
                return self._once(method, path, body)
            except errors.GameBusy:
                delay = next(delays, None)
                if delay is None:
                    raise
                time.sleep(delay)
            except errors.NotProcessing:
                if focus_deadline is None:
                    if self.focus_wait <= 0:
                        raise
                    focus_deadline = time.monotonic() + self.focus_wait
                    print("rimsdk: RimWorld is unfocused (Run in background is off); waiting for focus...", file=sys.stderr)
                if time.monotonic() >= focus_deadline:
                    raise
                time.sleep(1.0)

    def _once(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        content = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"} if content is not None else None
        try:
            response = self._http.request(method, path, content=content, headers=headers)
        except httpx.TransportError as exc:
            raise errors.BridgeUnavailable(
                f"Unable to reach RimMCP at {self.base_url}: {exc}. Is RimWorld running with RimMCP enabled?",
                method=method,
                path=path,
            ) from exc

        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {"error": response.text}
        if response.is_success:
            return payload
        message = payload.get("error") if isinstance(payload, dict) else None
        raise errors.from_response(
            response.status_code,
            message or f"RimMCP request failed with HTTP {response.status_code}.",
            method=method,
            path=path,
            body=payload,
        )
