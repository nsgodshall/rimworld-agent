"""Exceptions raised by the SDK, one per way a bridge call can fail."""

from __future__ import annotations

from typing import Any


class RimError(Exception):
    """A bridge call failed. `status` is the HTTP status, or None when no response arrived."""

    def __init__(self, message: str, *, status: int | None = None, method: str = "", path: str = "", body: Any = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.method = method
        self.path = path
        self.body = body

    def __str__(self) -> str:
        where = f" [{self.method} {self.path}]" if self.method else ""
        code = f"{self.status}: " if self.status is not None else ""
        return f"{code}{self.message}{where}"


class BridgeUnavailable(RimError):
    """Nothing answered: RimWorld isn't running, RimMCP isn't enabled, or the port is wrong."""


class AuthError(RimError):
    """401: the bearer token is missing or stale (RimMCP can regenerate it in its settings)."""


class AccessDenied(RimError):
    """403: the player's access preset in RimMCP's settings turns this tool off."""


class NotFound(RimError):
    """404: the pawn, building, zone, def, or route doesn't exist."""


class BadRequest(RimError):
    """400: the game rejected the arguments; the message says which and why."""


class Conflict(RimError):
    """409: the game's state forbids this now (another save loaded, expansion inactive, Multiplayer...)."""


class GameBusy(RimError):
    """429/503/504: RimWorld is loading, saving, or its main thread is backed up. Retrying usually works."""


class NotProcessing(RimError):
    """503: RimWorld is in the background with Run in background off, so it won't answer until focused."""


class ServerError(RimError):
    """500: RimMCP threw while handling the request; check get_game_log."""


class ReadOnlyViolation(RimError):
    """The client was created with read_only=True and the tool changes the game."""


def from_response(status: int, message: str, *, method: str, path: str, body: Any) -> RimError:
    kwargs = dict(status=status, method=method, path=path, body=body)
    if status == 401:
        return AuthError(message, **kwargs)
    if status == 403:
        return AccessDenied(message, **kwargs)
    if status == 404:
        return NotFound(message, **kwargs)
    if status == 409:
        return Conflict(message, **kwargs)
    if status == 503 and "background" in message.lower():
        return NotProcessing(message, **kwargs)
    if status in (429, 503, 504):
        return GameBusy(message, **kwargs)
    if 400 <= status < 500:
        return BadRequest(message, **kwargs)
    return ServerError(message, **kwargs)
