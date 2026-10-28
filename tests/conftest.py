from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from rimsdk import RimClient


class FakeTransport:
    """Records requests and answers them from a handler: handler(method, path, body) -> dict."""

    def __init__(self, handler: Callable[[str, str, dict[str, Any] | None], dict[str, Any]] | None = None):
        self.handler = handler or (lambda method, path, body: {"schemaVersion": "1", "data": None})
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append((method, path, body))
        return self.handler(method, path, body)

    def close(self) -> None:
        pass


@pytest.fixture
def fake() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def rim(fake: FakeTransport) -> RimClient:
    return RimClient(fake)
