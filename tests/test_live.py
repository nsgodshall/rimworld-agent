"""Contract tests against a running RimWorld with RimMCP: `uv run pytest -m live`.

They only read, through a read-only client, so they are safe on a real colony.
"""

import pytest

from rimsdk import RimClient, errors

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live():
    # Run in background may be off: give the player time to focus RimWorld.
    rim = RimClient.connect(read_only=True, focus_wait=120)
    try:
        rim.health()
    except errors.BridgeUnavailable as exc:
        pytest.skip(str(exc))
    yield rim
    rim.close()


def test_health(live):
    assert live.health()["status"] == "ok"


def test_sdk_matches_live_manifest(live):
    drift = live.check_manifest()
    assert not drift, f"Regenerate with `uv run python -m rimsdk.codegen`: {drift}"


def test_game_context_envelope(live):
    result = live.get_game_context()
    assert result["schemaVersion"] == "1"
    assert result.data is not None


def test_colony_reads(live):
    if live.get_game_context().map_id is None:
        pytest.skip("No colony loaded.")
    for read in (live.get_colony_status, live.list_pawns, live.list_resources, live.get_events, live.get_research):
        result = read()
        assert result["schemaVersion"] == "1", read.__name__


def test_map_view(live):
    if live.get_game_context().map_id is None:
        pytest.skip("No colony loaded.")
    assert live.get_map_view().data
