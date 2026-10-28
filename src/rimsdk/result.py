"""The envelope every RimMCP reply shares."""

from __future__ import annotations

from typing import Any


class Result(dict):
    """A bridge reply. It is the raw JSON dict, with the envelope fields as attributes.

    Reads carry `truncated` and `nextCursor`; commands carry `changed`. `data` is the payload.
    """

    @property
    def data(self) -> Any:
        return self.get("data")

    @property
    def tick(self) -> int | None:
        return self.get("tick")

    @property
    def map_id(self) -> str | None:
        return self.get("mapId")

    @property
    def load_id(self) -> str | None:
        return self.get("loadId")

    @property
    def truncated(self) -> bool:
        return bool(self.get("truncated"))

    @property
    def next_cursor(self) -> int | None:
        return self.get("nextCursor")

    @property
    def changed(self) -> bool | None:
        return self.get("changed")
