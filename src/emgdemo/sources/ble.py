"""BLE input from a wearable EMG pad.

Two things changed from the original:

* **Device selection is explicit.** The old resolver ended with
  ``if target_device is None and devices: target_device = devices[0]`` — so at a public
  stand, with a name mismatch, it would connect to whichever stranger's phone or watch
  the scan happened to list first and render its bytes as a muscle signal (R2). Here an
  unmatched scan is an error.
* **Payload decoding refuses what it cannot recognise.** Readings outside 12-bit range
  are rejected rather than rescaled into something plausible-looking.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Sequence

import numpy as np

from .base import ADC_MAX_COUNTS, ADC_REFERENCE_V, Sample, SourceStatus, to_voltage

#: Characteristics commonly used by MyoWare/ESP32 sketches, tried before any other
#: notifiable characteristic on the matched device.
DEFAULT_CHAR_CANDIDATES = (
    "beb5483e-36e1-4688-b7f5-ea07361b26a8",
    "0000ffe1-0000-1000-8000-00805f9b34fb",
    "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
)


class NoMatchingDevice(Exception):
    """Raised when the scan found nothing matching the criteria given."""


def _device_uuids(device) -> list[str]:
    uuids = getattr(device, "service_uuids", None)
    if uuids is None:
        metadata = getattr(device, "metadata", None) or {}
        uuids = metadata.get("uuids") or []
    return [str(u).lower() for u in uuids]


def select_device(
    devices: Sequence,
    address: str | None = None,
    name_hint: str | None = None,
    service_uuid: str | None = None,
):
    """Pick the intended device, or refuse. Never substitutes an arbitrary one."""
    if address:
        wanted = address.strip().lower()
        for device in devices:
            if str(getattr(device, "address", "")).strip().lower() == wanted:
                return device
        raise NoMatchingDevice(f"No BLE device with address {address}")

    if name_hint:
        wanted = name_hint.strip().lower()
        for device in devices:
            name = getattr(device, "name", None)
            if name and wanted in str(name).strip().lower():
                return device
        raise NoMatchingDevice(f"No BLE device whose name contains {name_hint!r}")

    if service_uuid:
        wanted = service_uuid.strip().lower()
        for device in devices:
            if wanted in _device_uuids(device):
                return device
        raise NoMatchingDevice(f"No BLE device advertising service {service_uuid}")

    raise NoMatchingDevice(
        "Refusing to pick a BLE device at random - give an address, name or service UUID"
    )


def _counts_to_samples(counts: np.ndarray, dual: bool) -> list[Sample]:
    if counts.size == 0 or int(counts.max()) > ADC_MAX_COUNTS:
        return []

    volts = (counts.astype(np.float64) / ADC_MAX_COUNTS) * ADC_REFERENCE_V
    if not dual:
        return [(float(v), 0.0) for v in volts]

    pairs = volts.reshape(-1, 2)
    return [(float(a), float(b)) for a, b in pairs]


def _parse_text(payload: bytes, dual: bool) -> list[Sample]:
    text = payload.decode("utf-8", errors="ignore").strip()
    if not text:
        return []

    samples: list[Sample] = []
    for line in text.splitlines():
        numbers: list[float] = []
        for part in line.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                numbers.append(float(part))
            except ValueError:
                numbers = []
                break
        if not numbers:
            continue

        if dual and len(numbers) >= 3:
            samples.append((to_voltage(numbers[-2]), to_voltage(numbers[-1])))
        elif dual and len(numbers) == 2:
            samples.append((to_voltage(numbers[0]), to_voltage(numbers[1])))
        else:
            samples.append((to_voltage(numbers[-1]), 0.0))
    return samples


def parse_payload(payload: bytes, dual: bool) -> list[Sample]:
    """Decode a notification. Unrecognised bytes yield nothing rather than noise."""
    if not payload:
        return []

    stride = 4 if dual else 2
    if len(payload) % stride == 0:
        samples = _counts_to_samples(np.frombuffer(payload, dtype="<u2"), dual)
        if samples:
            return samples

    return _parse_text(payload, dual)


class BLESource:
    """Runs bleak on its own thread and hands decoded samples to the engine."""

    def __init__(
        self,
        sample_rate_hz: float = 1000.0,
        address: str | None = None,
        name_hint: str | None = None,
        service_uuid: str | None = None,
        char_uuid: str | None = None,
        dual: bool = True,
        scan_timeout_s: float = 6.0,
        data_timeout_s: float = 3.0,
        reconnect_backoff_s: float = 1.0,
        max_reconnect_backoff_s: float = 8.0,
        queue_limit: int = 20000,
    ):
        if not (address or name_hint or service_uuid):
            raise NoMatchingDevice(
                "BLE needs an address, device name or service UUID - it will not guess"
            )

        self.sample_rate_hz = float(sample_rate_hz)
        self.address = address
        self.name_hint = name_hint
        self.service_uuid = service_uuid
        self.char_uuid = char_uuid
        self.dual = dual
        self.scan_timeout_s = float(scan_timeout_s)
        self.data_timeout_s = float(data_timeout_s)
        self.reconnect_backoff_s = max(0.3, float(reconnect_backoff_s))
        self.max_reconnect_backoff_s = max(self.reconnect_backoff_s, float(max_reconnect_backoff_s))

        self._samples: list[Sample] = []
        self._lock = threading.Lock()
        self._queue_limit = int(queue_limit)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = "stopped"
        self._detail = ""

    def start(self) -> None:
        self._stop.clear()
        self._set_status("connecting")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._set_status("stopped")

    def status(self) -> SourceStatus:
        with self._lock:
            return SourceStatus(state=self._state, detail=self._detail)

    def read(self, max_samples: int) -> list[Sample]:
        if max_samples <= 0:
            return []
        with self._lock:
            taken = self._samples[:max_samples]
            del self._samples[: len(taken)]
        return taken

    def _set_status(self, state: str, detail: str = "") -> None:
        with self._lock:
            self._state = state
            if detail:
                self._detail = detail

    def _push(self, samples: Iterable[Sample]) -> None:
        with self._lock:
            self._samples.extend(samples)
            overflow = len(self._samples) - self._queue_limit
            if overflow > 0:
                del self._samples[:overflow]
                self._detail = f"dropped {overflow} samples - consumer behind"

    def _run(self) -> None:
        import asyncio

        try:
            asyncio.run(self._session())
        except Exception as exc:  # noqa: BLE001 - surfaced through status, not swallowed
            self._set_status("error", str(exc) or exc.__class__.__name__)

    async def _session(self) -> None:
        import asyncio

        import bleak

        backoff = self.reconnect_backoff_s
        while not self._stop.is_set():
            try:
                self._set_status("connecting", "scanning")
                devices = await bleak.BleakScanner.discover(timeout=self.scan_timeout_s)
                device = select_device(
                    devices,
                    address=self.address,
                    name_hint=self.name_hint,
                    service_uuid=self.service_uuid,
                )

                async with bleak.BleakClient(device, timeout=8.0) as client:
                    char = self.char_uuid or _pick_characteristic(client)
                    last_rx = time.monotonic()

                    def on_notify(_handle, data: bytearray) -> None:
                        nonlocal last_rx
                        decoded = parse_payload(bytes(data), self.dual)
                        if decoded:
                            self._push(decoded)
                            last_rx = time.monotonic()

                    await client.start_notify(char, on_notify)
                    self._set_status("streaming", f"{device.address} {char}")

                    while not self._stop.is_set() and client.is_connected:
                        if (time.monotonic() - last_rx) > self.data_timeout_s:
                            raise TimeoutError("no BLE notifications")
                        await asyncio.sleep(0.05)

                backoff = self.reconnect_backoff_s

            except Exception as exc:  # noqa: BLE001 - reported, then retried
                self._set_status("reconnecting", str(exc) or exc.__class__.__name__)
                await asyncio.sleep(backoff)
                backoff = min(self.max_reconnect_backoff_s, backoff * 1.7)


def _pick_characteristic(client) -> str:
    """Prefer a known MyoWare characteristic, otherwise the first notifiable one."""
    notifiable = [
        str(char.uuid).lower()
        for service in client.services
        for char in service.characteristics
        if "notify" in {p.lower() for p in (char.properties or [])}
    ]
    for candidate in DEFAULT_CHAR_CANDIDATES:
        if candidate in notifiable:
            return candidate
    if notifiable:
        return notifiable[0]
    raise NoMatchingDevice("Matched device exposes no notifiable characteristic")


__all__ = [
    "DEFAULT_CHAR_CANDIDATES",
    "BLESource",
    "NoMatchingDevice",
    "parse_payload",
    "select_device",
]
