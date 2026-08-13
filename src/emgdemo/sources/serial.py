"""Serial input from the ESP32.

The original read with ``timeout=0`` and called ``readline()``, which on a non-blocking
port returns whatever bytes happen to be sitting in the buffer. A chunk cut mid-number —
``"1234,20"`` — parsed as a perfectly valid sample (R4). Bytes are now accumulated and
only complete lines are handed to the parser.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable

from .base import Sample, SourceStatus, to_voltage

#: Lines the firmware prints around a session that are not samples.
_BANNER_PREFIXES = ("===", "---")


class LineBuffer:
    """Accumulates bytes and emits only newline-terminated lines."""

    def __init__(self, max_pending_bytes: int = 4096):
        self.max_pending_bytes = int(max_pending_bytes)
        self._pending = b""

    @property
    def pending_bytes(self) -> int:
        return len(self._pending)

    def feed(self, chunk: bytes) -> list[str]:
        if not chunk:
            return []

        self._pending += chunk
        *complete, self._pending = self._pending.split(b"\n")

        # A stream with no newlines at all must not grow without bound; keep only the
        # most recent bytes, which is where a real line would eventually start.
        if len(self._pending) > self.max_pending_bytes:
            self._pending = self._pending[-self.max_pending_bytes :]

        return [line.decode("utf-8", errors="ignore").strip() for line in complete]

    def reset(self) -> None:
        self._pending = b""


def decode_line(line: str) -> Sample | None:
    """Parse one firmware line. Two fields mean ``timestamp,adc``; more mean dual pads."""
    line = line.strip()
    if not line or line.startswith(_BANNER_PREFIXES):
        return None

    numbers: list[float] = []
    for part in line.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            numbers.append(float(part))
        except ValueError:
            return None

    if len(numbers) < 2:
        return None
    if len(numbers) == 2:
        return to_voltage(numbers[1]), 0.0
    return to_voltage(numbers[-2]), to_voltage(numbers[-1])


class SerialSource:
    def __init__(
        self,
        port_factory: Callable[[], object],
        sample_rate_hz: float = 1000.0,
        read_size: int = 4096,
        reconnect_backoff_s: float = 1.0,
        max_reconnect_backoff_s: float = 8.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.port_factory = port_factory
        self.sample_rate_hz = float(sample_rate_hz)
        self.read_size = int(read_size)
        self.reconnect_backoff_s = max(0.3, float(reconnect_backoff_s))
        self.max_reconnect_backoff_s = max(self.reconnect_backoff_s, float(max_reconnect_backoff_s))
        self.clock = clock

        self._port: object | None = None
        self._running = False
        self._buffer = LineBuffer()
        self._backoff = self.reconnect_backoff_s
        self._retry_at = 0.0
        self._attempts = 0
        self._last_error = ""

    @classmethod
    def on_port(cls, port: str, baud: int = 921600, **kwargs) -> SerialSource:
        """Build a source that opens a real pyserial handle when started."""

        def factory():
            import serial

            return serial.Serial(port, baud, timeout=0)

        source = cls(port_factory=factory, **kwargs)
        source.port_name = port
        return source

    def start(self) -> None:
        self._running = True
        self._buffer.reset()
        self._open()

    def stop(self) -> None:
        self._running = False
        self._close()

    def status(self) -> SourceStatus:
        if not self._running:
            return SourceStatus(state="stopped")
        if self._port is None:
            return SourceStatus(
                state="reconnecting", detail=f"attempts={self._attempts} {self._last_error}"
            )
        return SourceStatus(state="streaming", detail=f"attempts={self._attempts}")

    def read(self, max_samples: int) -> list[Sample]:
        if not self._running or max_samples <= 0:
            return []

        if self._port is None:
            if self.clock() < self._retry_at:
                return []
            if not self._open():
                return []

        try:
            chunk = self._port.read(self.read_size)  # type: ignore[union-attr]
        except Exception as exc:
            self._schedule_retry(exc)
            return []

        samples: list[Sample] = []
        for line in self._buffer.feed(chunk):
            decoded = decode_line(line)
            if decoded is not None:
                samples.append(decoded)
            if len(samples) >= max_samples:
                break
        return samples

    def _open(self) -> bool:
        try:
            self._port = self.port_factory()
        except Exception as exc:
            self._schedule_retry(exc)
            return False

        self._backoff = self.reconnect_backoff_s
        return True

    def _close(self) -> None:
        if self._port is not None:
            # Closing a port that has already gone away is not worth reporting.
            with contextlib.suppress(Exception):
                self._port.close()  # type: ignore[union-attr]
        self._port = None

    def _schedule_retry(self, error: BaseException) -> None:
        self._close()
        self._attempts += 1
        self._last_error = str(error) or error.__class__.__name__
        self._retry_at = self.clock() + self._backoff
        self._backoff = min(self.max_reconnect_backoff_s, self._backoff * 1.7)
