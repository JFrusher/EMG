"""Serves the interface and streams the engine to it.

Server-sent events over the standard library rather than a WebSocket framework. The
traffic is one-way at thirty frames a second with a handful of button presses going the
other way, which is exactly what SSE is for — and it keeps the dependency list at numpy,
scipy and pandas, which is what makes "clone it and run it" true on someone else's
laptop.

The engine runs on its own thread. Frames are built under the engine's lock, so a
request can never catch a trace buffer mid-write.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .commands import UnknownCommand, apply_command
from .engine import Engine

ASSETS = Path(__file__).parent / "ui"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}


class _Handler(BaseHTTPRequestHandler):
    server_version = "emgdemo"

    @property
    def demo(self) -> DemoServer:
        return self.server.demo  # type: ignore[attr-defined]

    def log_message(self, *_args) -> None:
        """Quiet by default; the demo's own event log is the interesting one."""

    # -- routing ---------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        if path == "/stream":
            self._stream()
        else:
            self._static("index.html" if path == "/" else path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        if self.path.split("?", 1)[0] != "/command":
            self._error(404, "no such endpoint")
            return

        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            action = payload["action"]
        except (ValueError, KeyError, TypeError):
            self._error(400, "expected a JSON body with an 'action'")
            return

        try:
            apply_command(self.demo.engine, action)
        except UnknownCommand as exc:
            self._error(400, str(exc))
            return

        self._json(200, {"ok": True, "action": action})

    # -- responses -------------------------------------------------------

    def _static(self, name: str) -> None:
        target = (ASSETS / name).resolve()
        if not target.is_relative_to(ASSETS.resolve()) or not target.is_file():
            self._error(404, "not found")
            return

        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "text/plain"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        demo = self.demo
        try:
            while not demo.stopping:
                frame = demo.engine.render_frame(max_points=demo.max_points)
                self.wfile.write(f"data: {json.dumps(frame)}\n\n".encode())
                self.wfile.flush()
                if demo.stopping_event.wait(demo.frame_interval):
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the page was closed; nothing to report

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})


class DemoServer:
    def __init__(
        self,
        engine: Engine,
        host: str = "127.0.0.1",
        port: int = 8420,
        frame_hz: float = 30.0,
        max_points: int = 400,
        tick_hz: float = 200.0,
    ):
        self.engine = engine
        self.frame_interval = 1.0 / frame_hz
        self.max_points = int(max_points)
        self.tick_hz = tick_hz

        self.stopping_event = threading.Event()
        self._engine_thread: threading.Thread | None = None

        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.demo = self  # type: ignore[attr-defined]

    @property
    def stopping(self) -> bool:
        return self.stopping_event.is_set()

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def serve_forever(self) -> None:
        self._engine_thread = threading.Thread(
            target=self.engine.run,
            args=(lambda _state: None, self.stopping_event, self.tick_hz),
            daemon=True,
        )
        self._engine_thread.start()
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        self.stopping_event.set()
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._engine_thread is not None:
            self._engine_thread.join(timeout=3.0)
            self._engine_thread = None
