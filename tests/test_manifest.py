"""Requests must match what RimMCP's own proxy (McpProxy/src/main.rs) sends for the same tool call."""

import pytest

from rimsdk.manifest import Manifest, ToolSpec, build_request


def spec(**overrides) -> ToolSpec:
    dto = {
        "name": "t",
        "method": "GET",
        "pathTemplate": "/v1/things",
        "queryKeys": [],
        "bodyKeys": [],
        "inputSchema": {},
        "annotations": {},
    }
    dto.update(overrides)
    return ToolSpec.from_dto(dto)


def test_query_encodes_bools_as_csharp_and_joins_string_arrays():
    s = spec(queryKeys=["idsOnly", "include", "limit", "hours"])
    _, path, body = build_request(s, {"idsOnly": True, "include": ["training", "", "skills"], "limit": 5, "hours": 1.5})
    assert path == "/v1/things?idsOnly=True&include=training%2Cskills&limit=5&hours=1.5"
    assert body is None


def test_none_and_empty_values_are_not_sent():
    s = spec(queryKeys=["a", "b", "c"])
    assert build_request(s, {"a": None, "b": "", "c": []})[1] == "/v1/things"


def test_query_keys_dedupe_case_insensitively():
    s = spec(queryKeys=["mapId", "mapid"])
    assert build_request(s, {"mapId": "1", "mapid": "2"})[1] == "/v1/things?mapId=1"


def test_query_rejects_non_string_arrays():
    with pytest.raises(TypeError):
        build_request(spec(queryKeys=["ids"]), {"ids": [1, 2]})


def test_path_captures_are_escaped_and_required():
    s = spec(pathTemplate="/v1/pawns/{pawnId}/work/{workType}")
    assert build_request(s, {"pawnId": "Thing_Human 12/a", "workType": "Cooking"})[1] == (
        "/v1/pawns/Thing_Human%2012%2Fa/work/Cooking"
    )
    with pytest.raises(ValueError, match="pawnId"):
        build_request(s, {"workType": "Cooking"})


def test_body_holds_only_body_keys_and_is_sent_even_when_empty():
    s = spec(method="PUT", bodyKeys=["priority", "note"], queryKeys=["waitSeconds"])
    method, path, body = build_request(s, {"priority": 1, "note": None, "waitSeconds": 10, "stray": 1})
    assert (method, path, body) == ("PUT", "/v1/things?waitSeconds=10", {"priority": 1})
    assert build_request(s, {})[2] == {}


def test_bundled_manifest_loads_and_routes_every_parameter():
    manifest = Manifest.bundled()
    assert len(manifest.tools) >= 80
    for tool in manifest.tools.values():
        props = set(tool.input_schema.get("properties", {}))
        routed = set(tool.query_keys) | set(tool.body_keys) | set(tool.path_params)
        assert props <= routed, f"{tool.name} has parameters the bridge never receives: {props - routed}"


def test_live_manifest_shape_skips_route_only_entries():
    data = {
        "manifestVersion": "1",
        "tools": [
            {"name": "get_x", "method": "GET", "pathTemplate": "/v1/x", "exposeAsMcp": True, "enabled": True},
            {"name": None, "handlerId": "tools", "method": "GET", "pathTemplate": "/v1/tools", "exposeAsMcp": False},
        ],
        "access": {"preset": "full"},
    }
    manifest = Manifest.from_json(data)
    assert list(manifest.tools) == ["get_x"]
    assert manifest.version == "1"
