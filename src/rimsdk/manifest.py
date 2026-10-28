"""RimMCP's tool manifest, and turning a tool call into the HTTP request RimMCP's own proxy would send."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Any
from urllib.parse import quote


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    group: str
    method: str
    path_template: str
    query_keys: tuple[str, ...]
    body_keys: tuple[str, ...]
    input_schema: dict[str, Any] = field(repr=False)
    annotations: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dto(cls, dto: dict[str, Any]) -> ToolSpec:
        return cls(
            name=dto["name"],
            description=dto.get("description", ""),
            group=dto.get("group") or "",
            method=dto["method"].upper(),
            path_template=dto["pathTemplate"],
            query_keys=tuple(dto.get("queryKeys") or ()),
            body_keys=tuple(dto.get("bodyKeys") or ()),
            input_schema=dto.get("inputSchema") or {},
            annotations=dto.get("annotations") or {},
        )

    @property
    def read_only(self) -> bool:
        return bool(self.annotations.get("readOnlyHint"))

    @property
    def path_params(self) -> list[str]:
        return [s[1:-1] for s in self.path_template.split("/") if len(s) > 2 and s[0] == "{" and s[-1] == "}"]


@dataclass(frozen=True)
class Manifest:
    version: str
    tools: dict[str, ToolSpec]

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Manifest:
        # The proxy's embedded manifest has "version"; the live /v1/tools route has "manifestVersion"
        # and also lists route-only entries (tools, access) that carry no MCP name.
        version = str(data.get("version") or data.get("manifestVersion") or "")
        specs = [ToolSpec.from_dto(t) for t in data["tools"] if t.get("name") and t.get("exposeAsMcp", True)]
        return cls(version, {s.name: s for s in specs})

    @classmethod
    def bundled(cls) -> Manifest:
        text = resources.files("rimsdk").joinpath("manifest.json").read_text(encoding="utf-8")
        return cls.from_json(json.loads(text))


def _query_value(value: Any) -> str:
    # Mirrors McpProxy/src/main.rs query_value: the bridge parses C#-style booleans.
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            if item is None:
                continue
            if not isinstance(item, str):
                raise TypeError("Query array values must be strings.")
            if item.strip():
                items.append(item)
        return ",".join(items)
    raise TypeError("Query values must be scalars or arrays of strings.")


def _escape(value: str) -> str:
    return quote(value, safe="")


def build_request(spec: ToolSpec, args: dict[str, Any]) -> tuple[str, str, dict[str, Any] | None]:
    """Return (method, path?query, json body or None) for a call, dropping None arguments as the proxy does."""
    segments = []
    for segment in spec.path_template.split("/"):
        if len(segment) > 2 and segment[0] == "{" and segment[-1] == "}":
            value = args.get(segment[1:-1])
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{spec.name}: missing required argument '{segment[1:-1]}'.")
            segments.append(_escape(value))
        else:
            segments.append(segment)
    path = "/".join(segments)

    query, seen = [], set()
    for key in spec.query_keys:
        if key.lower() in seen:
            continue
        seen.add(key.lower())
        value = args.get(key)
        if value is None:
            continue
        encoded = _query_value(value)
        if encoded:
            query.append(f"{_escape(key)}={_escape(encoded)}")
    if query:
        path += "?" + "&".join(query)

    body = None
    if spec.body_keys:
        body = {key: args[key] for key in spec.body_keys if args.get(key) is not None}
    return spec.method, path, body
