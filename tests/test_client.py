import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rimsdk import NO_RETRY, RetryPolicy, RimClient, errors
from rimsdk.codegen import SNAPSHOT
from rimsdk.transport import HttpTransport

from .conftest import FakeTransport


def test_result_exposes_envelope(rim, fake):
    fake.handler = lambda m, p, b: {"schemaVersion": "1", "tick": 42, "mapId": "0", "truncated": True, "nextCursor": 10, "data": {"x": 1}}
    result = rim.get_colony_status()
    assert (result.tick, result.map_id, result.truncated, result.next_cursor, result.data) == (42, "0", True, 10, {"x": 1})
    assert result["schemaVersion"] == "1"
    assert fake.requests[0][0] == "GET" and fake.requests[0][2] is None


def test_read_only_client_refuses_changes_but_allows_reads(fake):
    rim = RimClient(fake, read_only=True)
    rim.get_game_context()
    with pytest.raises(errors.ReadOnlyViolation):
        rim.set_game_speed(speed="Normal")
    assert len(fake.requests) == 1


def test_pages_follow_next_cursor(rim, fake):
    cursors = {None: 2, "2": 4, "4": None}

    def handler(method, path, body):
        cursor = path.split("cursor=")[1].split("&")[0] if "cursor=" in path else None
        return {"data": [cursor], "nextCursor": cursors[cursor]}

    fake.handler = handler
    pages = list(rim.pages(rim.list_pawns, limit=2))
    assert [p.data for p in pages] == [[None], ["2"], ["4"]]


def test_advance_polls_until_the_run_ends(rim, fake):
    replies = iter([
        {"changed": True, "data": {"id": 7, "status": "running"}},
        {"data": {"time": {}, "run": {"id": 7, "status": "running"}}},
        {"data": {"time": {}, "run": {"id": 7, "status": "stopped", "endReason": "hostiles"}}},
    ])
    fake.handler = lambda m, p, b: next(replies)
    run = rim.advance(6, stop_on=["hostiles"])
    assert run["endReason"] == "hostiles"
    start, *polls = fake.requests
    assert start[0] == "POST" and start[2]["hours"] == 6 and start[2]["stopOn"] == ["hostiles"] and start[2]["requestId"]
    assert all("runId=7" in p[1] and "waitSeconds=30" in p[1] for p in polls)


def test_wait_operation_stops_at_done_or_question(rim, fake):
    replies = iter([
        {"data": {"operationId": "op1", "state": "running", "done": False}},
        {"data": {"operationId": "op1", "state": "awaitingConfirmation", "done": False}},
    ])
    fake.handler = lambda m, p, b: next(replies)
    op = rim.wait_operation({"data": {"operationId": "op1", "state": "queued", "done": False}})
    assert op["state"] == "awaitingConfirmation"
    assert all(r[1].startswith("/v1/operations/op1") for r in fake.requests)


# --- real HTTP against a stand-in bridge -------------------------------------------------


class Bridge:
    """A local HTTP server answering from a queue of (status, body) and recording requests."""

    def __init__(self):
        self.replies: list[tuple[int, dict]] = []
        self.seen: list[tuple[str, str, str | None, str | None]] = []
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def handle_one(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode() if length else None
                bridge.seen.append((self.command, self.path, self.headers.get("Authorization"), body))
                status, payload = bridge.replies.pop(0) if bridge.replies else (200, {"data": None})
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = handle_one

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def bridge():
    b = Bridge()
    yield b
    b.close()


FAST = RetryPolicy(attempts=3, first_delay=0.01, max_delay=0.01)


def test_http_sends_token_and_json_body(bridge):
    rim = RimClient(HttpTransport(bridge.url, "secret", retry=FAST))
    rim.set_pawn_work_priority("Thing_Human1", "Cooking", priority=1)
    method, path, auth, body = bridge.seen[0]
    assert (method, auth) == ("PUT", "Bearer secret")
    assert path.startswith("/v1/pawns/Thing_Human1/work/Cooking")
    assert json.loads(body)["priority"] == 1


@pytest.mark.parametrize(
    "status, message, exc",
    [
        (400, "Field 'priority' must be 0 to 4.", errors.BadRequest),
        (401, "Missing or invalid bearer token.", errors.AuthError),
        (403, "Tool is off.", errors.AccessDenied),
        (404, "No pawn Thing_Human9.", errors.NotFound),
        (409, "Ideology expansion is not active.", errors.Conflict),
        (500, "NullReferenceException: boom", errors.ServerError),
        (503, "RimWorld is in the background with Run in background off, so...", errors.NotProcessing),
    ],
)
def test_http_errors_map_to_exceptions_without_retry(bridge, status, message, exc):
    bridge.replies = [(status, {"error": message})] * 3
    rim = RimClient(HttpTransport(bridge.url, "t", retry=FAST))
    with pytest.raises(exc) as info:
        rim.get_game_context()
    assert info.value.status == status and info.value.message == message
    assert len(bridge.seen) == 1


def test_busy_bridge_is_retried(bridge):
    bridge.replies = [(429, {"error": "busy"}), (503, {"error": "RimWorld is loading, saving, or changing games"}), (200, {"data": "ok"})]
    rim = RimClient(HttpTransport(bridge.url, "t", retry=FAST))
    assert rim.get_game_context().data == "ok"
    assert len(bridge.seen) == 3


def test_busy_bridge_gives_up_after_policy(bridge):
    bridge.replies = [(429, {"error": "busy"})] * 5
    rim = RimClient(HttpTransport(bridge.url, "t", retry=NO_RETRY))
    with pytest.raises(errors.GameBusy):
        rim.get_game_context()


UNFOCUSED = (503, {"error": "RimWorld is in the background with Run in background off, so it is not processing requests."})


def test_unfocused_game_is_waited_out_when_asked(bridge):
    bridge.replies = [UNFOCUSED, UNFOCUSED, (200, {"data": "ok"})]
    rim = RimClient(HttpTransport(bridge.url, "t", retry=NO_RETRY, focus_wait=10))
    assert rim.get_game_context().data == "ok"
    assert len(bridge.seen) == 3


def test_unfocused_game_raises_once_focus_wait_runs_out(bridge):
    bridge.replies = [UNFOCUSED] * 10
    rim = RimClient(HttpTransport(bridge.url, "t", retry=NO_RETRY, focus_wait=1.5))
    with pytest.raises(errors.NotProcessing):
        rim.get_game_context()
    assert 2 <= len(bridge.seen) <= 3


def test_unreachable_bridge():
    rim = RimClient(HttpTransport("http://127.0.0.1:9", "t", timeout=2))
    with pytest.raises(errors.BridgeUnavailable, match="Is RimWorld running"):
        rim.get_game_context()


def test_check_manifest_reports_drift():
    bundled = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    tools = [t for t in bundled["tools"] if t["name"] != "list_mods"]
    tools[0] = {**tools[0], "pathTemplate": "/v1/moved"}
    tools.append({**tools[1], "name": "brand_new_tool"})
    fake = FakeTransport(lambda m, p, b: {"manifestVersion": "1", "tools": tools})
    drift = RimClient(fake).check_manifest()
    assert drift.added == ["brand_new_tool"]
    assert drift.removed == ["list_mods"]
    assert drift.changed == [tools[0]["name"]]
