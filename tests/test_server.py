"""The HTTP surface: static files, an event stream, and a command endpoint."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from emgdemo.config import DemoSettings
from emgdemo.engine import Engine
from emgdemo.server import DemoServer
from emgdemo.sources.synthetic import SyntheticSource


@pytest.fixture
def server():
    engine = Engine(
        DemoSettings(),
        source=SyntheticSource(1000.0, seed=3),
        source_name="synthetic",
    )
    server = DemoServer(engine, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _get(server, path):
    with urllib.request.urlopen(f"{server.url}{path}", timeout=5) as response:
        return response.status, response.read(), response.headers


def _post(server, path, payload):
    request = urllib.request.Request(
        f"{server.url}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def test_the_page_is_served(server):
    status, body, headers = _get(server, "/")
    assert status == 200
    assert b"<canvas" in body
    assert "text/html" in headers["Content-Type"]


def test_the_client_assets_are_served(server):
    for path, content_type in (("/app.js", "javascript"), ("/style.css", "css")):
        status, body, headers = _get(server, path)
        assert status == 200, path
        assert body
        assert content_type in headers["Content-Type"], path


def test_unknown_paths_are_not_found(server):
    with pytest.raises(urllib.error.HTTPError) as caught:
        _get(server, "/nope")
    assert caught.value.code == 404


def test_paths_cannot_escape_the_asset_directory(server):
    with pytest.raises(urllib.error.HTTPError) as caught:
        _get(server, "/../../pyproject.toml")
    assert caught.value.code in (400, 404)


def test_the_stream_delivers_frames(server):
    with urllib.request.urlopen(f"{server.url}/stream", timeout=5) as response:
        assert "text/event-stream" in response.headers["Content-Type"]

        payloads = []
        while len(payloads) < 2:
            line = response.readline().decode()
            if line.startswith("data: "):
                payloads.append(json.loads(line[6:]))

    assert payloads[0]["source"]["name"] == "synthetic"
    assert set(payloads[0]["traces"]) >= {"raw", "envelope"}
    assert payloads[1]["t"] >= payloads[0]["t"]


def test_a_command_reaches_the_engine(server):
    status, body = _post(server, "/command", {"action": "pause"})
    assert status == 200
    assert body["ok"] is True
    assert server.engine.paused is True


def test_an_unknown_command_is_rejected(server):
    with pytest.raises(urllib.error.HTTPError) as caught:
        _post(server, "/command", {"action": "drop-tables"})
    assert caught.value.code == 400


def test_malformed_command_bodies_are_rejected(server):
    request = urllib.request.Request(
        f"{server.url}/command",
        data=b"not json",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=5)
    assert caught.value.code == 400


def test_the_engine_runs_while_the_server_is_up(server):
    _, first = _post(server, "/command", {"action": "resume"})
    import time

    time.sleep(0.4)
    assert server.engine.total_samples > 0
    assert first["ok"] is True
