"""
Public Engagement EMG Demo
==========================

A professional, modular, real-time demo application for showing the full
EMG-to-gripper pipeline to participants.

Capabilities:
- Live sample acquisition from BLE EMG (preferred), Serial, or Synthetic fallback
- Streaming filter pipeline with stage-by-stage scrolling plots:
  Raw -> Notch -> Bandpass -> Rectified -> Low-pass -> Envelope
- Event detection with hysteresis and refractory guard
- Real-time digital gripper mockup driven by envelope level
- Redundancy/fallback handling if BLE or Serial is unavailable

Designed to be easy to maintain and hot-swap:
- Signal sources are isolated classes implementing a common interface
- Filter stack is encapsulated in a dedicated streaming pipeline
- UI update loop is separate from acquisition and processing

Usage examples:
  python public_engagement_demo.py --source synthetic
  python public_engagement_demo.py --source serial --port COM3
  python public_engagement_demo.py --source ble --ble-address XX:XX:XX:XX:XX:XX --ble-char 0000ffe1-0000-1000-8000-00805f9b34fb

Notes:
- BLE path requires `bleak`
- Serial path requires `pyserial`
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import butter, iirnotch, lfilter, lfilter_zi
import pandas as pd

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button

plt.style.use("seaborn-v0_8-whitegrid")

DualSample = Tuple[float, float]


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class DemoConfig:
    sample_rate_hz: int = 1000
    view_seconds: float = 8.0
    frame_interval_ms: int = 40

    notch_freq_hz: float = 50.0
    notch_q: float = 30.0
    bandpass_low_hz: float = 20.0
    bandpass_high_hz: float = 400.0
    bandpass_order: int = 2
    lowpass_cutoff_hz: float = 150.0
    lowpass_order: int = 3
    envelope_window_ms: float = 200.0

    event_threshold_high: float = 0.28
    event_threshold_low: float = 0.20
    min_event_interval_s: float = 0.25


# =============================================================================
# Source Abstractions
# =============================================================================


class BaseSignalSource(ABC):
    """Abstract source for normalized voltage samples in range [0, 3.3]."""

    def __init__(self, sample_rate_hz: int):
        self.sample_rate_hz = sample_rate_hz

    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def read_available(self, max_samples: int) -> List[float]:
        pass

    def read_available_dual(self, max_samples: int) -> List[DualSample]:
        singles = self.read_available(max_samples)
        return [(float(v), 0.0) for v in singles]


class SyntheticEMGSource(BaseSignalSource):
    """Stable synthetic source used as default fallback in public demos."""

    def __init__(self, sample_rate_hz: int):
        super().__init__(sample_rate_hz)
        self._running = False
        self._phase = 0.0
        self._activation_a = 0.0
        self._activation_b = 0.0

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def read_available_dual(self, max_samples: int) -> List[DualSample]:
        if not self._running or max_samples <= 0:
            return []

        out: List[DualSample] = []
        dt = 1.0 / self.sample_rate_hz

        for _ in range(max_samples):
            self._phase += 2.0 * math.pi * dt
            self._activation_a += 2.0 * math.pi * 0.42 * dt
            self._activation_b += 2.0 * math.pi * 0.38 * dt

            burst_a = (0.5 * (1.0 + math.sin(self._activation_a))) ** 1.9
            burst_b = (0.5 * (1.0 + math.sin(self._activation_b + 1.8))) ** 2.0

            emg_a = (
                0.20 * math.sin(2 * math.pi * 70 * self._phase)
                + 0.16 * math.sin(2 * math.pi * 95 * self._phase)
                + 0.12 * math.sin(2 * math.pi * 130 * self._phase)
            )
            emg_b = (
                0.18 * math.sin(2 * math.pi * 65 * self._phase + 0.8)
                + 0.13 * math.sin(2 * math.pi * 110 * self._phase + 1.1)
                + 0.10 * math.sin(2 * math.pi * 145 * self._phase + 0.2)
            )

            noise_a = np.random.normal(0.0, 0.05)
            noise_b = np.random.normal(0.0, 0.05)
            powerline = 0.05 * math.sin(2 * math.pi * 50 * self._phase)

            va = 1.65 + burst_a * (emg_a + noise_a + powerline)
            vb = 1.65 + burst_b * (emg_b + noise_b + powerline)
            out.append((float(np.clip(va, 0.0, 3.3)), float(np.clip(vb, 0.0, 3.3))))

        return out

    def read_available(self, max_samples: int) -> List[float]:
        dual = self.read_available_dual(max_samples)
        return [float(np.clip(a + b, 0.0, 3.3)) for a, b in dual]


class SerialEMGSource(BaseSignalSource):
    """Serial source reading ESP32 CSV lines: timestamp_ms,adc_raw_value"""

    def __init__(
        self,
        sample_rate_hz: int,
        port: str,
        baud: int = 921600,
        reconnect_backoff_s: float = 1.0,
        max_reconnect_backoff_s: float = 8.0,
        data_timeout_s: float = 4.0,
    ):
        super().__init__(sample_rate_hz)
        self.port = port
        self.baud = baud
        self._serial = None
        self._running = False
        self.reconnect_backoff_s = max(0.3, float(reconnect_backoff_s))
        self.max_reconnect_backoff_s = max(self.reconnect_backoff_s, float(max_reconnect_backoff_s))
        self.data_timeout_s = max(0.5, float(data_timeout_s))
        self._next_reconnect_monotonic = 0.0
        self._reconnect_delay_s = self.reconnect_backoff_s
        self._last_data_monotonic = 0.0
        self._reconnect_attempts = 0
        self._last_error = ""

    def _open_serial(self) -> None:
        import serial
        self._serial = serial.Serial(self.port, self.baud, timeout=0)
        self._reconnect_delay_s = self.reconnect_backoff_s
        self._next_reconnect_monotonic = 0.0
        self._last_data_monotonic = time.monotonic()

    def _close_serial(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    def _schedule_reconnect(self, err: Optional[str] = None) -> None:
        self._close_serial()
        self._reconnect_attempts += 1
        if err:
            self._last_error = err
        self._next_reconnect_monotonic = time.monotonic() + self._reconnect_delay_s
        self._reconnect_delay_s = min(self.max_reconnect_backoff_s, self._reconnect_delay_s * 1.7)

    def status_summary(self) -> str:
        state = "connected" if self._serial is not None else "reconnecting"
        msg = (
            f"state={state} | port={self.port} | attempts={self._reconnect_attempts}"
        )
        if self._last_error:
            msg += f" | last={self._last_error[:48]}"
        return msg

    def start(self) -> None:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required for serial source") from exc

        self._open_serial()
        self._running = True

    def stop(self) -> None:
        self._running = False
        self._close_serial()

    @staticmethod
    def _to_voltage(value: float) -> float:
        if value > 3.3:
            return float(np.clip((value / 4095.0) * 3.3, 0.0, 3.3))
        return float(np.clip(value, 0.0, 3.3))

    def _decode_line(self, line: str) -> Optional[DualSample]:
        if not line or line.startswith("===") or line.startswith("---"):
            return None

        parts = [p.strip() for p in line.split(",") if p.strip()]
        if len(parts) < 2:
            return None

        nums: List[float] = []
        for p in parts:
            try:
                nums.append(float(p))
            except ValueError:
                pass

        if len(nums) < 2:
            return None

        # Legacy ESP32 format: timestamp_ms,adc_raw_value
        if len(nums) == 2:
            return self._to_voltage(nums[1]), 0.0

        # Dual-pad serial format: timestamp,pad_a,pad_b  OR  pad_a,pad_b
        return self._to_voltage(nums[-2]), self._to_voltage(nums[-1])

    def read_available_dual(self, max_samples: int) -> List[DualSample]:
        if not self._running or max_samples <= 0:
            return []

        now = time.monotonic()

        if self._serial is None:
            if now < self._next_reconnect_monotonic:
                return []
            try:
                self._open_serial()
            except Exception as exc:
                self._schedule_reconnect(str(exc) or exc.__class__.__name__)
                return []

        serial_handle = self._serial
        if serial_handle is None:
            return []

        samples: List[DualSample] = []
        for _ in range(max_samples):
            try:
                raw = serial_handle.readline()
            except Exception as exc:
                self._schedule_reconnect(str(exc) or exc.__class__.__name__)
                break
            if not raw:
                break

            try:
                line = raw.decode(errors="ignore").strip()
            except Exception:
                continue

            value = self._decode_line(line)
            if value is not None:
                samples.append(value)
                self._last_data_monotonic = now

        if self._serial is not None and (now - self._last_data_monotonic) > self.data_timeout_s:
            self._schedule_reconnect("serial data timeout")

        return samples

    def read_available(self, max_samples: int) -> List[float]:
        dual = self.read_available_dual(max_samples)
        return [float(np.clip(a + b, 0.0, 3.3)) for a, b in dual]


class DatasetReplaySource(BaseSignalSource):
    """Replay dataset CSV files sequentially as pseudo-live EMG input."""

    def __init__(
        self,
        sample_rate_hz: int,
        dataset_dir: str,
        dataset_source: str = "raw",
        channel: Optional[str] = None,
        side_a_channel: Optional[str] = None,
        side_b_channel: Optional[str] = None,
        replay_speed: float = 1.0,
        loop: bool = False,
    ):
        super().__init__(sample_rate_hz)
        self.dataset_dir = dataset_dir
        self.dataset_source = dataset_source
        self.channel = channel
        self.side_a_channel = side_a_channel
        self.side_b_channel = side_b_channel
        self.replay_speed = max(0.05, float(replay_speed))
        self.loop = loop

        self.files: List[str] = self._discover_files()
        self.file_idx = 0
        self.current_data_a = np.array([], dtype=np.float32)
        self.current_data_b = np.array([], dtype=np.float32)
        self.current_pos = 0
        self.current_file = "(none)"

        self._running = False
        self._last_t = 0.0
        self._sample_budget = 0.0

    def _discover_files(self) -> List[str]:
        base = Path(self.dataset_dir)
        folder = base / ("raw_signals" if self.dataset_source == "raw" else "filtered_signals")
        if not folder.is_dir():
            raise FileNotFoundError(f"Dataset folder not found: {folder}")

        files = sorted(str(p) for p in folder.glob("*.csv"))
        if not files:
            raise FileNotFoundError(f"No CSV files found in: {folder}")
        return files

    def _select_channel(self, df: pd.DataFrame, numeric_cols: List[str], selector: Optional[str]) -> np.ndarray:
        if selector is None:
            raise ValueError("selector cannot be None")
        if str(selector).isdigit():
            idx = int(selector)
            if idx < 0 or idx >= len(numeric_cols):
                raise IndexError(
                    f"Channel index {idx} out of range for available 0..{len(numeric_cols)-1}"
                )
            return df[numeric_cols[idx]].values.astype(np.float32)
        if selector not in numeric_cols:
            raise ValueError(f"Channel '{selector}' not found. Available: {numeric_cols}")
        return df[selector].values.astype(np.float32)

    def _extract_dual_signal(self, filepath: str) -> Tuple[np.ndarray, np.ndarray]:
        df = pd.read_csv(filepath)

        drop_cols = []
        for c in df.columns:
            lc = str(c).lower()
            if lc.startswith("unnamed") or "timestamp" in lc or lc in ["time", "index"]:
                drop_cols.append(c)
        if drop_cols:
            df = df.drop(columns=drop_cols)

        numeric_cols = [c for c in df.columns if np.issubdtype(df[c].dtype, np.number)]
        if not numeric_cols:
            raise ValueError(f"No numeric columns in {os.path.basename(filepath)}")

        if self.side_a_channel is not None or self.side_b_channel is not None:
            sig_a = (
                self._select_channel(df, numeric_cols, self.side_a_channel)
                if self.side_a_channel is not None
                else np.zeros(len(df), dtype=np.float32)
            )
            sig_b = (
                self._select_channel(df, numeric_cols, self.side_b_channel)
                if self.side_b_channel is not None
                else np.zeros(len(df), dtype=np.float32)
            )
        elif self.channel is not None:
            sig_a = self._select_channel(df, numeric_cols, self.channel)
            sig_b = np.zeros_like(sig_a)
        else:
            if "adc_raw_value" in df.columns:
                sig_a = df["adc_raw_value"].values.astype(np.float32)
                sig_b = np.zeros_like(sig_a)
            elif "voltage" in df.columns:
                sig_a = df["voltage"].values.astype(np.float32)
                sig_b = np.zeros_like(sig_a)
            elif len(numeric_cols) >= 2:
                sig_a = df[numeric_cols[0]].values.astype(np.float32)
                sig_b = df[numeric_cols[1]].values.astype(np.float32)
            else:
                sig_a = df[numeric_cols[0]].values.astype(np.float32)
                sig_b = np.zeros_like(sig_a)

        for arr in [sig_a, sig_b]:
            if np.nanmax(arr) > 3.3:
                arr[:] = (arr / 4095.0) * 3.3

        sig_a = np.nan_to_num(sig_a, nan=1.65, posinf=3.3, neginf=0.0)
        sig_b = np.nan_to_num(sig_b, nan=1.65, posinf=3.3, neginf=0.0)
        return np.clip(sig_a, 0.0, 3.3), np.clip(sig_b, 0.0, 3.3)

    def _load_current_file(self) -> bool:
        if self.file_idx >= len(self.files):
            if self.loop:
                self.file_idx = 0
            else:
                return False

        try:
            current_path = self.files[self.file_idx]
            self.current_data_a, self.current_data_b = self._extract_dual_signal(current_path)
            self.current_pos = 0
            self.current_file = os.path.basename(current_path)
            self.file_idx += 1
            return True
        except Exception:
            self.file_idx += 1
            if self.file_idx >= len(self.files) and not self.loop:
                return False
            return self._load_current_file()

    def start(self) -> None:
        self._running = True
        self._sample_budget = 0.0
        self._last_t = time.perf_counter()
        if self.current_data_a.size == 0:
            loaded = self._load_current_file()
            if not loaded:
                raise RuntimeError("Unable to load any dataset files for replay")

    def stop(self) -> None:
        self._running = False

    def read_available_dual(self, max_samples: int) -> List[DualSample]:
        if not self._running or max_samples <= 0:
            return []

        now = time.perf_counter()
        elapsed = max(0.0, now - self._last_t)
        self._last_t = now

        self._sample_budget += elapsed * self.sample_rate_hz * self.replay_speed
        want = min(max_samples, int(self._sample_budget))
        if want <= 0:
            return []

        self._sample_budget -= want

        out: List[DualSample] = []
        while len(out) < want:
            if self.current_pos >= len(self.current_data_a):
                if not self._load_current_file():
                    self._running = False
                    break

            remaining = want - len(out)
            end = min(self.current_pos + remaining, len(self.current_data_a))
            chunk_a = self.current_data_a[self.current_pos:end]
            chunk_b = self.current_data_b[self.current_pos:end]
            out.extend((float(a), float(b)) for a, b in zip(chunk_a, chunk_b))
            self.current_pos = end

        return out

    def read_available(self, max_samples: int) -> List[float]:
        dual = self.read_available_dual(max_samples)
        return [float(np.clip(a + b, 0.0, 3.3)) for a, b in dual]

    def status_summary(self) -> str:
        file_number = min(self.file_idx, len(self.files))
        total = len(self.files)
        return (
            f"dataset file {file_number}/{total}: {self.current_file} | "
            f"sample {self.current_pos}/{len(self.current_data_a)}"
        )


class BLEEMGSource(BaseSignalSource):
    """BLE source via notification callback queue.

    Supports two common payload forms:
    - int16 little-endian samples
    - UTF-8 CSV text lines, where the last field is interpreted as ADC-like value
    """

    DEFAULT_CHAR_CANDIDATES = [
        "beb5483e-36e1-4688-b7f5-ea07361b26a8",
        "0000ffe1-0000-1000-8000-00805f9b34fb",
        "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
    ]

    def __init__(
        self,
        sample_rate_hz: int,
        address: Optional[str],
        char_uuid: Optional[str],
        device_name: Optional[str] = None,
        service_uuid: Optional[str] = None,
        scan_timeout_s: float = 6.0,
        reconnect_backoff_s: float = 1.0,
        max_reconnect_backoff_s: float = 8.0,
        data_timeout_s: float = 3.0,
    ):
        super().__init__(sample_rate_hz)
        self.address = address
        self.char_uuid = char_uuid
        self.device_name = device_name
        self.service_uuid = service_uuid
        self.scan_timeout_s = max(1.0, float(scan_timeout_s))
        self.reconnect_backoff_s = max(0.3, float(reconnect_backoff_s))
        self.max_reconnect_backoff_s = max(self.reconnect_backoff_s, float(max_reconnect_backoff_s))
        self.data_timeout_s = max(0.5, float(data_timeout_s))

        self._running = False
        self._queue: "queue.Queue[DualSample]" = queue.Queue(maxsize=20000)
        self._loop_thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._status_lock = threading.Lock()
        self._status = "idle"
        self._last_error = ""
        self._connect_attempts = 0
        self._reconnects = 0
        self._resolved_address = self.address
        self._resolved_char_uuid = self.char_uuid
        self._resolved_name = self.device_name
        self._last_rx_monotonic = 0.0

    @property
    def resolved_address(self) -> Optional[str]:
        return self._resolved_address

    @property
    def resolved_char_uuid(self) -> Optional[str]:
        return self._resolved_char_uuid

    def status_summary(self) -> str:
        with self._status_lock:
            msg = (
                f"state={self._status} | q={self._queue.qsize()} | "
                f"attempts={self._connect_attempts} | reconnects={self._reconnects}"
            )
            if self._resolved_name:
                msg += f" | dev={self._resolved_name}"
            if self._resolved_address:
                msg += f" | addr={self._resolved_address}"
            if self._last_error:
                msg += f" | last={self._last_error[:48]}"
            return msg

    def _set_status(self, status: str, error: Optional[str] = None) -> None:
        with self._status_lock:
            self._status = status
            if error is not None:
                self._last_error = error

    def start(self) -> None:
        try:
            import bleak  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("bleak is required for BLE source") from exc

        self._running = True
        self._stop_evt.clear()
        self._set_status("starting")
        self._last_rx_monotonic = time.monotonic()
        self._loop_thread = threading.Thread(target=self._run_ble_loop, daemon=True)
        self._loop_thread.start()

    def stop(self) -> None:
        self._running = False
        self._stop_evt.set()
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=2.0)
        self._loop_thread = None
        self._set_status("stopped")

    def read_available_dual(self, max_samples: int) -> List[DualSample]:
        if not self._running or max_samples <= 0:
            return []

        out: List[DualSample] = []
        for _ in range(max_samples):
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out

    def read_available(self, max_samples: int) -> List[float]:
        dual = self.read_available_dual(max_samples)
        return [float(np.clip(a + b, 0.0, 3.3)) for a, b in dual]

    def _push(self, value: DualSample) -> None:
        if not self._running:
            return
        va = float(np.clip(value[0], 0.0, 3.3))
        vb = float(np.clip(value[1], 0.0, 3.3))
        try:
            self._queue.put_nowait((va, vb))
        except queue.Full:
            try:
                _ = self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait((va, vb))
            except queue.Full:
                pass

    def _parse_payload(self, payload: bytes) -> List[DualSample]:
        if not payload:
            return []

        if len(payload) % 4 == 0:
            try:
                u16_vals = np.frombuffer(payload, dtype="<u2")
                if u16_vals.size > 0 and int(np.max(u16_vals)) <= 4095:
                    pairs = u16_vals.reshape(-1, 2).astype(np.float32)
                    scaled = (pairs / 4095.0) * 3.3
                    return [
                        (float(np.clip(a, 0.0, 3.3)), float(np.clip(b, 0.0, 3.3)))
                        for a, b in scaled
                    ]
            except Exception:
                pass

        if len(payload) % 2 == 0:
            try:
                u16_vals = np.frombuffer(payload, dtype="<u2")
                if u16_vals.size > 0 and int(np.max(u16_vals)) <= 4095:
                    scaled = (u16_vals.astype(np.float32) / 4095.0) * 3.3
                    return [(float(np.clip(v, 0.0, 3.3)), 0.0) for v in scaled]
            except Exception:
                pass

        if len(payload) % 4 == 0:
            try:
                int16_vals = np.frombuffer(payload, dtype="<i2")
                pairs = int16_vals.reshape(-1, 2).astype(np.float32)
                scaled = ((pairs + 32768.0) / 65535.0) * 3.3
                return [(float(np.clip(a, 0.0, 3.3)), float(np.clip(b, 0.0, 3.3))) for a, b in scaled]
            except Exception:
                pass

        if len(payload) % 2 == 0:
            try:
                int16_vals = np.frombuffer(payload, dtype="<i2")
                scaled = ((int16_vals.astype(np.float32) + 32768.0) / 65535.0) * 3.3
                return [(float(np.clip(v, 0.0, 3.3)), 0.0) for v in scaled]
            except Exception:
                pass

        try:
            text = payload.decode("utf-8", errors="ignore").strip()
            if not text:
                return []
            values: List[DualSample] = []
            for line in text.splitlines():
                parts = [p.strip() for p in line.split(",") if p.strip()]
                if not parts:
                    continue
                nums: List[float] = []
                for p in parts:
                    try:
                        nums.append(float(p))
                    except ValueError:
                        pass
                if not nums:
                    continue

                if len(nums) >= 3:
                    a_raw, b_raw = nums[-2], nums[-1]
                elif len(nums) == 2:
                    a_raw, b_raw = nums[0], nums[1]
                else:
                    a_raw, b_raw = nums[0], 0.0

                a = (a_raw / 4095.0) * 3.3 if a_raw > 3.3 else a_raw
                b = (b_raw / 4095.0) * 3.3 if b_raw > 3.3 else b_raw
                values.append((float(np.clip(a, 0.0, 3.3)), float(np.clip(b, 0.0, 3.3))))
            return values
        except Exception:
            return []

    def _run_ble_loop(self) -> None:
        import asyncio
        import bleak

        async def _resolve_device_and_char() -> Tuple[str, str, Optional[str]]:
            target_device = None
            devices = await bleak.BleakScanner.discover(timeout=self.scan_timeout_s)

            if self.address:
                target_address = self.address.strip().lower()
                for device in devices:
                    if (getattr(device, "address", "") or "").strip().lower() == target_address:
                        target_device = device
                        break
                if target_device is None:
                    raise RuntimeError(f"BLE device {self.address} not found during scan")
            else:
                name_hint = (self.device_name or "MYOWARE").strip().lower()
                for device in devices:
                    device_name = (getattr(device, "name", None) or "").strip().lower()
                    if name_hint in device_name:
                        target_device = device
                        break

                if target_device is None and self.service_uuid:
                    svc = self.service_uuid.strip().lower()
                    for device in devices:
                        uuids = [u.lower() for u in (getattr(device, "metadata", {}).get("uuids") or [])]
                        if svc in uuids:
                            target_device = device
                            break

                if target_device is None and devices:
                    target_device = devices[0]

                if target_device is None:
                    raise RuntimeError("No BLE devices discovered")

            resolved_address = str(getattr(target_device, "address", "")).strip()
            resolved_name = getattr(target_device, "name", None)
            if not resolved_address:
                raise RuntimeError("Discovered BLE device has no address")

            chosen_char = self.char_uuid.strip().lower() if self.char_uuid else ""
            async with bleak.BleakClient(resolved_address, timeout=8.0) as probe_client:
                services = await probe_client.get_services()
                chars = []
                for service in services:
                    if self.service_uuid and str(service.uuid).lower() != self.service_uuid.strip().lower():
                        continue
                    for ch in service.characteristics:
                        chars.append(ch)

                if not chosen_char:
                    candidates = [c.lower() for c in self.DEFAULT_CHAR_CANDIDATES]
                    for ch in chars:
                        props = {p.lower() for p in (ch.properties or [])}
                        if "notify" in props and str(ch.uuid).lower() in candidates:
                            chosen_char = str(ch.uuid).lower()
                            break
                    if not chosen_char:
                        for ch in chars:
                            props = {p.lower() for p in (ch.properties or [])}
                            if "notify" in props:
                                chosen_char = str(ch.uuid).lower()
                                break

                if not chosen_char:
                    raise RuntimeError("No notifiable BLE characteristic found")

            return resolved_address, chosen_char, resolved_name

        async def _runner() -> None:
            backoff = self.reconnect_backoff_s
            while not self._stop_evt.is_set():
                try:
                    self._connect_attempts += 1
                    self._set_status("scanning")
                    resolved_address, chosen_char, resolved_name = await _resolve_device_and_char()
                    self._resolved_address = resolved_address
                    self._resolved_char_uuid = chosen_char
                    self._resolved_name = resolved_name

                    self._set_status("connecting")
                    async with bleak.BleakClient(resolved_address, timeout=8.0) as client:
                        if not client.is_connected:
                            raise RuntimeError("BLE client failed to connect")

                        self._set_status("connected")
                        self._last_rx_monotonic = time.monotonic()

                        def _on_notify(_: int, data: bytearray) -> None:
                            parsed = self._parse_payload(bytes(data))
                            for value in parsed:
                                self._push(value)
                            if parsed:
                                self._last_rx_monotonic = time.monotonic()

                        await client.start_notify(chosen_char, _on_notify)
                        while not self._stop_evt.is_set() and client.is_connected:
                            if (time.monotonic() - self._last_rx_monotonic) > self.data_timeout_s:
                                raise RuntimeError("BLE stream timeout (no notifications)")
                            await asyncio.sleep(0.05)

                        try:
                            await client.stop_notify(chosen_char)
                        except Exception:
                            pass

                    backoff = self.reconnect_backoff_s

                except Exception as exc:
                    self._reconnects += 1
                    err = str(exc) or exc.__class__.__name__
                    self._set_status("reconnecting", error=err)
                    await asyncio.sleep(backoff)
                    backoff = min(self.max_reconnect_backoff_s, backoff * 1.7)

            self._set_status("stopping")

        try:
            asyncio.run(_runner())
        except Exception:
            self._running = False
            self._set_status("error", error="BLE event loop crashed")


# =============================================================================
# Streaming Pipeline
# =============================================================================


class IIRStage:
    """Stateful IIR filter stage for sample-by-sample streaming processing."""

    def __init__(self, b: np.ndarray, a: np.ndarray):
        self.b = b
        self.a = a
        self.zi = lfilter_zi(b, a) * 1.65

    def step(self, sample: float) -> float:
        y, self.zi = lfilter(self.b, self.a, [sample], zi=self.zi)
        return float(y[0])


class MovingAverageStage:
    """Simple moving average stage for envelope smoothing."""

    def __init__(self, window_samples: int):
        self.window_samples = max(1, int(window_samples))
        self.buffer: Deque[float] = deque(maxlen=self.window_samples)

    def step(self, sample: float) -> float:
        self.buffer.append(sample)
        return float(np.mean(self.buffer))


class StreamingEMGPipeline:
    """Realtime EMG processing pipeline with reusable stage outputs."""

    def __init__(self, cfg: DemoConfig):
        nyquist = cfg.sample_rate_hz / 2.0
        b_notch, a_notch = iirnotch(cfg.notch_freq_hz, cfg.notch_q, fs=cfg.sample_rate_hz)
        b_bp, a_bp = butter(
            cfg.bandpass_order,
            [cfg.bandpass_low_hz / nyquist, cfg.bandpass_high_hz / nyquist],
            btype="bandpass",
        )
        b_lp, a_lp = butter(
            cfg.lowpass_order,
            cfg.lowpass_cutoff_hz / nyquist,
            btype="lowpass",
        )

        self.notch = IIRStage(b_notch, a_notch)
        self.bandpass = IIRStage(b_bp, a_bp)
        self.lowpass = IIRStage(b_lp, a_lp)

        window_samples = int((cfg.envelope_window_ms / 1000.0) * cfg.sample_rate_hz)
        self.envelope_ma = MovingAverageStage(window_samples=window_samples)

    def step(self, raw: float) -> Dict[str, float]:
        notch = self.notch.step(raw)
        band = self.bandpass.step(notch)
        rect = abs(band)
        lp = self.lowpass.step(rect)
        env = self.envelope_ma.step(lp)

        return {
            "raw": raw,
            "notch": notch,
            "bandpass": band,
            "rectified": rect,
            "lowpass": lp,
            "envelope": env,
        }


# =============================================================================
# Event Detector + Gripper
# =============================================================================


class EventDetector:
    """Threshold event detector with hysteresis and refractory period."""

    def __init__(self, cfg: DemoConfig):
        self.cfg = cfg
        self.last_event_time = -1e9
        self.active = False

    def step(self, envelope_norm: float, t: float) -> Tuple[bool, bool]:
        event_started = False

        if not self.active and envelope_norm >= self.cfg.event_threshold_high:
            if (t - self.last_event_time) >= self.cfg.min_event_interval_s:
                self.active = True
                self.last_event_time = t
                event_started = True

        if self.active and envelope_norm <= self.cfg.event_threshold_low:
            self.active = False

        return event_started, self.active


class DemoGripper:
    """Lightweight visual gripper state model for public demos."""

    def __init__(self):
        self.finger_positions = np.zeros(5, dtype=np.float32)
        self.grip_force_n = 0.0
        self.grip_label = "OPEN"

    def step(self, close_norm: float, open_norm: float) -> None:
        net_command = float(np.clip(close_norm - open_norm, -1.0, 1.0))
        target_force = float(np.clip(self.grip_force_n + net_command * 12.0, 0.0, 100.0))
        self.grip_force_n += (target_force - self.grip_force_n) * 0.20

        if self.grip_force_n < 10:
            self.grip_label = "OPEN"
        elif self.grip_force_n < 40:
            self.grip_label = "LIGHT"
        else:
            self.grip_label = "POWER"

        ratios = np.array([0.72, 1.0, 1.0, 0.9, 0.82], dtype=np.float32)
        target_pos = np.clip((self.grip_force_n / 100.0) * ratios, 0.0, 1.0)
        self.finger_positions += (target_pos - self.finger_positions) * 0.18


# =============================================================================
# Dashboard
# =============================================================================


class PublicEngagementDashboard:
    """Live UI: scrolling stage plots + event monitor + gripper mockup."""

    def __init__(
        self,
        cfg: DemoConfig,
        source: BaseSignalSource,
        source_name: str,
        ui_mode: str = "gripper",
        emulate_dual_delay: bool = False,
        dual_delay_sec: float = 1.0,
    ):
        self.cfg = cfg
        self.source = source
        self.source_name = source_name
        self.ui_mode = ui_mode
        self.emulate_dual_delay = emulate_dual_delay
        self.dual_delay_sec = max(0.0, float(dual_delay_sec))

        self.pipeline = StreamingEMGPipeline(cfg)
        self.pipeline_side_a = StreamingEMGPipeline(cfg)
        self.pipeline_side_b = StreamingEMGPipeline(cfg)
        self.events = EventDetector(cfg)
        self.gripper = DemoGripper()

        self.max_samples = int(cfg.view_seconds * cfg.sample_rate_hz)
        self.time_axis = np.linspace(-cfg.view_seconds, 0, self.max_samples)

        self.buffers: Dict[str, Deque[float]] = {
            "raw": deque([1.65] * self.max_samples, maxlen=self.max_samples),
            "notch": deque([1.65] * self.max_samples, maxlen=self.max_samples),
            "bandpass": deque([0.0] * self.max_samples, maxlen=self.max_samples),
            "rectified": deque([0.0] * self.max_samples, maxlen=self.max_samples),
            "lowpass": deque([0.0] * self.max_samples, maxlen=self.max_samples),
            "envelope": deque([0.0] * self.max_samples, maxlen=self.max_samples),
        }
        self.side_a_envelope_hist: Deque[float] = deque([0.0] * self.max_samples, maxlen=self.max_samples)
        self.side_b_envelope_hist: Deque[float] = deque([0.0] * self.max_samples, maxlen=self.max_samples)
        self.side_a_level = 0.0
        self.side_b_level = 0.0
        self.cocontract_active = False
        self.last_cocontract_time = -1e9
        self.delay_samples = int(self.dual_delay_sec * self.cfg.sample_rate_hz) if self.emulate_dual_delay else 0
        self.side_b_delay_buf: Deque[float] = deque([0.0] * self.delay_samples)

        self.session_t0 = time.perf_counter()
        self.last_frame_t = self.session_t0
        self.event_log: Deque[str] = deque(maxlen=5 if ui_mode == "gripper" else 8)
        self.event_count = 0
        self.total_samples = 0
        self.recent_samples = 0
        self.recent_t0 = self.session_t0
        self.measured_rate_hz = 0.0
        self.paused = False
        self.autoscale_enabled = ui_mode == "gripper"
        self.autoscale_alpha = 0.22
        self.autoscale_state: Dict[str, Tuple[float, float]] = {}
        self.calibration_active = False
        self.calibration_duration_sec = 4.0
        self.calibration_end_time = 0.0
        self.calibration_a_samples: List[float] = []
        self.calibration_b_samples: List[float] = []
        self.calib_baseline_a = 0.0
        self.calib_span_a = 0.10
        self.calib_baseline_b = 0.0
        self.calib_span_b = 0.10
        self.has_calibration = False

        self.fig = None
        self.axes = {}
        self.lines = {}
        self.stage_badges = {}
        self.event_text = None
        self.status_text = None
        self.finger_patches = []
        self.force_bar = None
        self.grip_text = None
        self.env_high_line = None
        self.env_low_line = None
        self.clarity_text = None
        self.debug_text = None
        self.debug_text_secondary = None
        self.button_widgets: List[Button] = []
        self.ani = None
        self.stage_keys = ["raw", "notch", "bandpass", "rectified", "lowpass", "envelope"]
        self.stage_colors = {
            "raw": "#6B7280",
            "notch": "#3B82F6",
            "bandpass": "#2563EB",
            "rectified": "#F59E0B",
            "lowpass": "#10B981",
            "envelope": "#8B5CF6",
        }
        self.clarity_bar = None
        self.clarity_text_small = None
        self.pause_button = None
        self.calibrate_button = None
        self.event_times: Deque[float] = deque(maxlen=12)
        self.event_marker_line = None
        self.pad_bar_left = None
        self.pad_bar_right = None
        self.pad_value_text = None
        self.improvement_history = {
            "notch": deque(maxlen=20),
            "bandpass": deque(maxlen=20),
            "rectified": deque(maxlen=20),
            "lowpass": deque(maxlen=20),
            "envelope": deque(maxlen=20),
        }
        self.render_stride = max(1, self.max_samples // 1800)
        self.time_axis_view = self.time_axis[::self.render_stride]
        self.metric_frame_counter = 0
        self.metric_every_n_frames = 3
        self.cached_improvements = {
            "notch": 0.0,
            "bandpass": 0.0,
            "rectified": 0.0,
            "lowpass": 0.0,
            "envelope": 0.0,
        }

        self.runtime_recovery_enabled = True
        self.source_stall_timeout_s = 6.0
        self.source_restart_cooldown_s = 4.0
        self.source_max_restarts = 5
        self._last_sample_monotonic = self.session_t0
        self._last_restart_monotonic = 0.0
        self._source_restart_count = 0
        self._failover_active = False
        self._engine_error_count = 0

    def _norm_envelope(self) -> float:
        env = np.array(self.buffers["envelope"], dtype=np.float32)
        p95 = float(np.percentile(env, 95))
        ref = max(p95, 0.08)
        return float(np.clip(env[-1] / ref, 0.0, 1.0))

    @staticmethod
    def _norm_from_hist(history: Deque[float], latest: float) -> float:
        arr = np.array(history, dtype=np.float32)
        p95 = float(np.percentile(arr, 95))
        ref = max(p95, 0.05)
        return float(np.clip(latest / ref, 0.0, 1.0))

    def _normalize_side(self, history: Deque[float], latest: float, side: str) -> float:
        if self.has_calibration:
            if side == "a":
                baseline, span = self.calib_baseline_a, self.calib_span_a
            else:
                baseline, span = self.calib_baseline_b, self.calib_span_b
            return float(np.clip((latest - baseline) / max(span, 1e-4), 0.0, 1.0))
        return self._norm_from_hist(history, latest)

    def _finish_calibration(self) -> None:
        if len(self.calibration_a_samples) < 20 or len(self.calibration_b_samples) < 20:
            self.calibration_active = False
            if self.calibrate_button is not None:
                self.calibrate_button.label.set_text("Calibrate")
            self._append_event("Calibration failed: not enough samples")
            return

        a = np.array(self.calibration_a_samples, dtype=np.float32)
        b = np.array(self.calibration_b_samples, dtype=np.float32)

        self.calib_baseline_a = float(np.percentile(a, 20))
        self.calib_baseline_b = float(np.percentile(b, 20))
        a_high = float(np.percentile(a, 95))
        b_high = float(np.percentile(b, 95))
        self.calib_span_a = max(a_high - self.calib_baseline_a, 0.03)
        self.calib_span_b = max(b_high - self.calib_baseline_b, 0.03)
        self.has_calibration = True
        self.calibration_active = False
        if self.calibrate_button is not None:
            self.calibrate_button.label.set_text("Calibrate")
        self._append_event(
            f"Calibrated | A base={self.calib_baseline_a:.3f} span={self.calib_span_a:.3f} | "
            f"B base={self.calib_baseline_b:.3f} span={self.calib_span_b:.3f}"
        )

    def _append_event(self, msg: str) -> None:
        t = time.perf_counter() - self.session_t0
        self.event_log.appendleft(f"[{t:6.2f}s] {msg}")

    def _source_status_suffix(self) -> str:
        if isinstance(self.source, DatasetReplaySource):
            return self.source.status_summary()
        if isinstance(self.source, BLEEMGSource):
            return self.source.status_summary()
        if isinstance(self.source, SerialEMGSource):
            return self.source.status_summary()
        return ""

    def _safe_start_source(self) -> bool:
        try:
            self.source.start()
            return True
        except Exception as exc:
            self._append_event(f"Source start failed: {exc}")
            return False

    def _safe_stop_source(self) -> None:
        try:
            self.source.stop()
        except Exception as exc:
            self._append_event(f"Source stop warning: {exc}")

    def _activate_synthetic_failover(self, reason: str) -> None:
        if isinstance(self.source, SyntheticEMGSource):
            return
        self._safe_stop_source()
        self.source = SyntheticEMGSource(self.cfg.sample_rate_hz)
        self.source_name = "Synthetic Emergency Fallback"
        self._failover_active = True
        if self._safe_start_source():
            self._append_event(f"Emergency failover active: {reason}")
        else:
            self._append_event(f"Emergency failover failed: {reason}")

    def _restart_live_source(self, reason: str) -> None:
        if not self.runtime_recovery_enabled:
            return
        if isinstance(self.source, SyntheticEMGSource):
            return

        now = time.perf_counter()
        if (now - self._last_restart_monotonic) < self.source_restart_cooldown_s:
            return

        self._last_restart_monotonic = now
        self._source_restart_count += 1
        self._append_event(f"Source recovery {self._source_restart_count}: {reason}")

        self._safe_stop_source()
        if self._safe_start_source():
            self._append_event("Source recovered")
            self._last_sample_monotonic = time.perf_counter()
            return

        if self._source_restart_count >= self.source_max_restarts:
            self._activate_synthetic_failover("max source recovery attempts reached")

    def _setup_figure(self) -> None:
        self.fig = plt.figure(figsize=(16, 10))
        gs = self.fig.add_gridspec(6, 2, width_ratios=[3.7, 1.8], hspace=0.25, wspace=0.2)

        stage_keys = ["raw", "notch", "bandpass", "rectified", "lowpass", "envelope"]
        stage_titles = [
            "Raw Input",
            "Notch (Powerline Removed)",
            "Bandpass (EMG Isolated)",
            "Rectified",
            "Low-pass",
            "Envelope",
        ]

        for idx, (key, title) in enumerate(zip(stage_keys, stage_titles)):
            ax = self.fig.add_subplot(gs[idx, 0])
            data = np.abs(np.array(self.buffers[key]))
            line, = ax.plot(self.time_axis_view, data[::self.render_stride], linewidth=1.6, color=self.stage_colors[key])
            ax.set_xlim(-self.cfg.view_seconds, 0)
            ax.grid(alpha=0.25)
            ax.set_ylabel("V")
            ax.set_title(title, fontsize=10, fontweight="bold")
            if idx < len(stage_keys) - 1:
                ax.set_xticklabels([])
            else:
                ax.set_xlabel("Time (s)")

            if key in ["raw", "notch"]:
                ax.set_ylim(0, 3.3)
            elif key == "rectified":
                ax.set_ylim(0, 2.0)
            elif key in ["lowpass", "envelope"]:
                ax.set_ylim(0, 1.6)
            else:
                ax.set_ylim(0, 1.5)

            self.axes[key] = ax
            self.lines[key] = line
            if key != "raw":
                self.stage_badges[key] = ax.text(
                    0.985,
                    0.86,
                    "+0.0%",
                    transform=ax.transAxes,
                    ha="right",
                    va="center",
                    fontsize=8,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#DCFCE7", edgecolor="#86EFAC", alpha=0.9),
                )

        panel_ax = self.fig.add_subplot(gs[:, 1])
        panel_ax.set_xlim(0, 10)
        panel_ax.set_ylim(0, 10)
        panel_ax.axis("off")

        if self.ui_mode == "debug":
            self._setup_debug_panel(panel_ax)
        else:
            self._setup_gripper_panel(panel_ax)

        self.fig.suptitle("Live EMG Signal-to-Action Demonstrator", fontsize=15, fontweight="bold")

        ax_env = self.axes["envelope"]
        self.env_high_line, = ax_env.plot(
            self.time_axis,
            np.full_like(self.time_axis, 0.15),
            color="#EF4444",
            linestyle="--",
            linewidth=0.9,
            alpha=0.8,
        )
        self.env_low_line, = ax_env.plot(
            self.time_axis,
            np.full_like(self.time_axis, 0.10),
            color="#F59E0B",
            linestyle=":",
            linewidth=0.9,
            alpha=0.8,
        )
        self.event_marker_line, = ax_env.plot(
            [],
            [],
            linestyle="None",
            marker="|",
            markersize=12,
            markeredgewidth=1.5,
            color="#EC4899",
            alpha=0.85,
        )

    def _setup_gripper_panel(self, panel_ax) -> None:
        panel_ax.text(5, 9.65, "Public Engagement Control Panel", ha="center", va="center", fontsize=12, fontweight="bold")

        panel_ax.text(1.0, 9.20, "Noise Reduction vs Raw (running avg)", fontsize=8.6, fontweight="bold")
        self.clarity_text = panel_ax.text(
            1.0,
            8.95,
            "(waiting for signal)",
            fontsize=7.7,
            va="top",
            family="monospace",
        )

        panel_ax.text(1.0, 7.85, "Signal Clarity", fontsize=8.6, fontweight="bold")
        clarity_bg = patches.Rectangle((1.0, 7.50), 8.0, 0.28, facecolor="#E5E7EB", edgecolor="#9CA3AF")
        panel_ax.add_patch(clarity_bg)
        self.clarity_bar = patches.Rectangle((1.0, 7.50), 0.0, 0.28, facecolor="#22C55E", edgecolor="#22C55E")
        panel_ax.add_patch(self.clarity_bar)
        self.clarity_text_small = panel_ax.text(1.0, 7.18, "Clarity gain (envelope): +0.0%", fontsize=8.0)

        panel_ax.text(1.0, 6.92, "Pad Activity (Left closes | Right opens)", fontsize=8.4, fontweight="bold")
        panel_ax.plot([5.0, 5.0], [6.38, 6.80], color="#6B7280", linewidth=1.3)
        pad_bg_left = patches.Rectangle((1.0, 6.45), 4.0, 0.28, facecolor="#E5E7EB", edgecolor="#9CA3AF")
        pad_bg_right = patches.Rectangle((5.0, 6.45), 4.0, 0.28, facecolor="#E5E7EB", edgecolor="#9CA3AF")
        panel_ax.add_patch(pad_bg_left)
        panel_ax.add_patch(pad_bg_right)
        self.pad_bar_left = patches.Rectangle((5.0, 6.45), 0.0, 0.28, facecolor="#2563EB", edgecolor="#2563EB")
        self.pad_bar_right = patches.Rectangle((5.0, 6.45), 0.0, 0.28, facecolor="#EF4444", edgecolor="#EF4444")
        panel_ax.add_patch(self.pad_bar_left)
        panel_ax.add_patch(self.pad_bar_right)
        self.pad_value_text = panel_ax.text(1.0, 6.12, "Left: 0.00  Right: 0.00", fontsize=8.0)

        ax_cal = self.fig.add_axes([0.755, 0.145, 0.095, 0.04])
        ax_pause = self.fig.add_axes([0.865, 0.145, 0.095, 0.04])
        btn_cal = Button(ax_cal, "Calibrate")
        btn_pause = Button(ax_pause, "Pause")
        btn_cal.on_clicked(self._on_start_calibration)
        btn_pause.on_clicked(self._on_toggle_pause)
        self.calibrate_button = btn_cal
        self.pause_button = btn_pause
        self.button_widgets = [btn_cal, btn_pause]

        palm = patches.Rectangle((2.2, 4.2), 5.6, 1.8, linewidth=1.5, edgecolor="#222", facecolor="#DDDDDD")
        panel_ax.add_patch(palm)

        x_positions = [1.8, 3.0, 4.2, 5.4, 6.6]
        for x in x_positions:
            rect = patches.Rectangle((x, 3.2), 0.9, 0.8, linewidth=1.2, edgecolor="#333", facecolor="#FFB3B3")
            panel_ax.add_patch(rect)
            self.finger_patches.append(rect)

        panel_ax.text(5, 6.6, "Mock Gripper", ha="center", fontsize=10, fontweight="bold")

        panel_ax.text(1.0, 2.35, "Grip Force", fontsize=9, fontweight="bold")
        bar_bg = patches.Rectangle((1.0, 1.9), 8.0, 0.28, facecolor="#EAEAEA", edgecolor="#999")
        panel_ax.add_patch(bar_bg)
        self.force_bar = patches.Rectangle((1.0, 1.9), 0.0, 0.28, facecolor="#3B82F6", edgecolor="#3B82F6")
        panel_ax.add_patch(self.force_bar)

        self.grip_text = panel_ax.text(1.0, 1.45, "Grip: OPEN", fontsize=10, fontweight="bold")

        self.status_text = panel_ax.text(1.0, 1.05, "Source: starting...", fontsize=8.8)
        self.event_text = panel_ax.text(1.0, 0.2, "Events:\n(boot)", fontsize=8, va="bottom", family="monospace")

    def _setup_debug_panel(self, panel_ax) -> None:
        panel_ax.text(5, 9.65, "Live Debug Console", ha="center", va="center", fontsize=12, fontweight="bold")
        panel_ax.text(0.8, 9.15, "Realtime telemetry + controls", fontsize=9, alpha=0.85)

        panel_ax.text(0.8, 3.20, "Noise Reduction vs Raw (live)", fontsize=8.3, fontweight="bold")
        self.clarity_text = panel_ax.text(
            0.8,
            3.00,
            "(waiting for signal)",
            fontsize=7.4,
            va="top",
            family="monospace",
        )

        self.debug_text = panel_ax.text(
            0.8,
            8.5,
            "(initializing)",
            fontsize=8.8,
            va="top",
            family="monospace",
        )
        self.debug_text_secondary = panel_ax.text(
            0.8,
            4.35,
            "(awaiting signal)",
            fontsize=8.8,
            va="top",
            family="monospace",
        )

        self.status_text = panel_ax.text(0.8, 1.30, "Source: starting...", fontsize=9)
        self.event_text = panel_ax.text(0.8, 0.18, "Events:\n(boot)", fontsize=8, va="bottom", family="monospace")

        ax_pause = self.fig.add_axes([0.77, 0.20, 0.09, 0.04])
        ax_reset = self.fig.add_axes([0.87, 0.20, 0.09, 0.04])
        ax_snap = self.fig.add_axes([0.77, 0.145, 0.09, 0.04])
        ax_scale = self.fig.add_axes([0.87, 0.145, 0.09, 0.04])
        ax_cal = self.fig.add_axes([0.77, 0.09, 0.19, 0.04])

        btn_pause = Button(ax_pause, "Pause")
        btn_reset = Button(ax_reset, "Reset")
        btn_snap = Button(ax_snap, "Snapshot")
        btn_scale = Button(ax_scale, "AutoScale")
        btn_cal = Button(ax_cal, "Calibrate")

        btn_pause.on_clicked(self._on_toggle_pause)
        btn_reset.on_clicked(self._on_reset_events)
        btn_snap.on_clicked(self._on_snapshot)
        btn_scale.on_clicked(self._on_toggle_autoscale)
        btn_cal.on_clicked(self._on_start_calibration)

        self.calibrate_button = btn_cal
        self.pause_button = btn_pause
        self.button_widgets = [btn_pause, btn_reset, btn_snap, btn_scale, btn_cal]

    def _on_toggle_pause(self, _event) -> None:
        self.paused = not self.paused
        if self.pause_button is not None:
            self.pause_button.label.set_text("Play" if self.paused else "Pause")
        self._append_event("Paused" if self.paused else "Resumed")

    def _on_start_calibration(self, _event) -> None:
        self.calibration_active = True
        self.calibration_end_time = time.perf_counter() + self.calibration_duration_sec
        self.calibration_a_samples = []
        self.calibration_b_samples = []
        if self.calibrate_button is not None:
            self.calibrate_button.label.set_text("Calibrating...")
        self._append_event("Calibration started (hold representative contractions for ~4s)")

    def _on_reset_events(self, _event) -> None:
        self.event_log.clear()
        self.event_count = 0
        self.events.active = False
        self.events.last_event_time = -1e9
        self._append_event("Event log reset")

    def _on_snapshot(self, _event) -> None:
        Path("results").mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out = Path("results") / f"public_demo_snapshot_{ts}.png"
        try:
            self.fig.savefig(out, dpi=130)
            self._append_event(f"Snapshot saved: {out.name}")
        except Exception as exc:
            self._append_event(f"Snapshot failed: {exc}")

    def _on_toggle_autoscale(self, _event) -> None:
        self.autoscale_enabled = not self.autoscale_enabled
        if self.autoscale_enabled:
            self.autoscale_state.clear()
        self._append_event("Autoscale ON" if self.autoscale_enabled else "Autoscale OFF")

    def _apply_autoscale_if_enabled(self) -> None:
        if not self.autoscale_enabled:
            return

        for key, ax in self.axes.items():
            data = np.abs(np.array(self.buffers[key], dtype=np.float32))
            lo = float(np.percentile(data, 1))
            hi = float(np.percentile(data, 99))
            if not np.isfinite(lo) or not np.isfinite(hi):
                continue
            if hi - lo < 1e-4:
                hi = lo + 0.05
            margin = 0.08 * (hi - lo)
            target_lower = max(0.0, lo - margin)
            target_upper = hi + margin

            prev = self.autoscale_state.get(key)
            if prev is None:
                lower, upper = target_lower, target_upper
            else:
                lower = (1.0 - self.autoscale_alpha) * prev[0] + self.autoscale_alpha * target_lower
                upper = (1.0 - self.autoscale_alpha) * prev[1] + self.autoscale_alpha * target_upper

            if upper - lower < 1e-4:
                upper = lower + 0.05

            self.autoscale_state[key] = (lower, upper)
            ax.set_ylim(lower, upper)

    def _noise_proxy(self, signal_data: np.ndarray) -> float:
        if signal_data.size < 3:
            return 1e-6
        derivative = np.diff(signal_data)
        return float(np.mean(np.abs(derivative)) + 1e-6)

    def _format_clarity_metrics(self, improvements: Dict[str, float], compact: bool = False) -> str:
        abs_stage = {k: np.abs(np.array(self.buffers[k], dtype=np.float32)) for k in self.stage_keys}
        raw_noise = self._noise_proxy(abs_stage["raw"])

        if compact:
            return "\n".join([
                f"Raw jitter        : {raw_noise:0.5f}",
                f"Notch cleaner     : {improvements.get('notch', 0.0):+6.1f}%",
                f"Bandpass cleaner  : {improvements.get('bandpass', 0.0):+6.1f}%",
                f"Envelope cleaner  : {improvements.get('envelope', 0.0):+6.1f}%",
            ])

        labels = {
            "notch": "Notch",
            "bandpass": "Bandpass",
            "rectified": "Rectified",
            "lowpass": "Low-pass",
            "envelope": "Envelope",
        }

        lines = [f"Raw jitter: {raw_noise:0.5f}"]
        for key in ["notch", "bandpass", "rectified", "lowpass", "envelope"]:
            lines.append(f"{labels[key]:9s}: {improvements.get(key, 0.0):+6.1f}%")

        lines.append("(+ means cleaner than raw)")
        return "\n".join(lines)

    def _compute_stage_improvements(self) -> Dict[str, float]:
        abs_stage = {k: np.abs(np.array(self.buffers[k], dtype=np.float32)) for k in self.stage_keys}
        raw_noise = self._noise_proxy(abs_stage["raw"])
        out: Dict[str, float] = {}
        for key in ["notch", "bandpass", "rectified", "lowpass", "envelope"]:
            stage_noise = self._noise_proxy(abs_stage[key])
            improvement = (1.0 - (stage_noise / raw_noise)) * 100.0
            clipped = float(np.clip(improvement, -300.0, 100.0))
            self.improvement_history[key].append(clipped)
            out[key] = float(np.mean(self.improvement_history[key]))
        return out

    def _draw_event_markers(self) -> None:
        if self.event_marker_line is None:
            return
        now = time.perf_counter() - self.session_t0
        xs = []
        for ev_time in self.event_times:
            rel_t = ev_time - now
            if rel_t < -self.cfg.view_seconds or rel_t > 0:
                continue
            xs.append(rel_t)

        if len(xs) == 0:
            self.event_marker_line.set_data([], [])
            return

        y_top = self.axes["envelope"].get_ylim()[1] * 0.92
        ys = [y_top] * len(xs)
        self.event_marker_line.set_data(xs, ys)

    def _update_gripper_panel(self) -> None:
        if self.ui_mode != "gripper":
            return

        if self.pad_bar_left is not None and self.pad_bar_right is not None and self.pad_value_text is not None:
            left_w = 4.0 * float(np.clip(self.side_a_level, 0.0, 1.0))
            right_w = 4.0 * float(np.clip(self.side_b_level, 0.0, 1.0))
            self.pad_bar_left.set_x(5.0 - left_w)
            self.pad_bar_left.set_width(left_w)
            self.pad_bar_right.set_x(5.0)
            self.pad_bar_right.set_width(right_w)
            self.pad_value_text.set_text(f"Left: {self.side_a_level:0.2f}  Right: {self.side_b_level:0.2f}")

        for idx, rect in enumerate(self.finger_patches):
            flex = float(self.gripper.finger_positions[idx])
            rect.set_y(3.2 + 1.7 * flex)
            rect.set_height(max(0.2, 0.8 - 0.25 * flex))
            rect.set_facecolor((1.0, 1.0 - 0.45 * flex, 1.0 - 0.45 * flex))

        width = 8.0 * (self.gripper.grip_force_n / 100.0)
        self.force_bar.set_width(width)
        self.grip_text.set_text(f"Grip: {self.gripper.grip_label} ({self.gripper.grip_force_n:5.1f} N)")

    def _step_engine(self) -> None:
        now = time.perf_counter()
        dt = now - self.last_frame_t
        self.last_frame_t = now

        if self.paused:
            suffix = self._source_status_suffix()
            if suffix:
                self.status_text.set_text(f"Source: {self.source_name} | paused | {suffix}")
            else:
                self.status_text.set_text(f"Source: {self.source_name} | paused")
            return

        expected = max(1, int(self.cfg.sample_rate_hz * dt))
        expected = min(expected, int(self.cfg.sample_rate_hz * 0.12))
        try:
            samples_dual = self.source.read_available_dual(max_samples=expected * 2)
        except Exception as exc:
            self._append_event(f"Read error: {exc}")
            self._restart_live_source("read exception")
            return

        if len(samples_dual) == 0:
            if (now - self._last_sample_monotonic) > self.source_stall_timeout_s:
                self._append_event("Source stall detected")
                self._restart_live_source("sample timeout")
            suffix = self._source_status_suffix()
            if suffix:
                self.status_text.set_text(f"Source: {self.source_name} | waiting for samples... | {suffix}")
            else:
                self.status_text.set_text(f"Source: {self.source_name} | waiting for samples...")
            return

        self._last_sample_monotonic = now

        self.total_samples += len(samples_dual)
        self.recent_samples += len(samples_dual)

        elapsed_rate_window = now - self.recent_t0
        if elapsed_rate_window >= 0.5:
            self.measured_rate_hz = self.recent_samples / elapsed_rate_window
            self.recent_samples = 0
            self.recent_t0 = now

        for side_a_raw, side_b_raw in samples_dual[: expected * 2]:
            if self.delay_samples > 0:
                self.side_b_delay_buf.append(float(side_b_raw))
                side_b_raw = float(self.side_b_delay_buf.popleft())

            side_sum = float(np.clip(side_a_raw + side_b_raw, 0.0, 3.3))

            out = self.pipeline.step(side_sum)
            out_a = self.pipeline_side_a.step(side_a_raw)
            out_b = self.pipeline_side_b.step(side_b_raw)

            for key, value in out.items():
                self.buffers[key].append(value)

            self.side_a_envelope_hist.append(float(out_a["envelope"]))
            self.side_b_envelope_hist.append(float(out_b["envelope"]))

            if self.calibration_active:
                self.calibration_a_samples.append(float(out_a["envelope"]))
                self.calibration_b_samples.append(float(out_b["envelope"]))
                if time.perf_counter() >= self.calibration_end_time:
                    self._finish_calibration()

            self.side_a_level = self._normalize_side(self.side_a_envelope_hist, float(out_a["envelope"]), "a")
            self.side_b_level = self._normalize_side(self.side_b_envelope_hist, float(out_b["envelope"]), "b")

            env_n = self._norm_envelope()
            event_started, active = self.events.step(env_n, now - self.session_t0)
            self.gripper.step(self.side_a_level, self.side_b_level)

            cocontract_now = (
                self.side_a_level >= self.cfg.event_threshold_high
                and self.side_b_level >= self.cfg.event_threshold_high
            )
            if cocontract_now and not self.cocontract_active:
                if (now - self.session_t0) - self.last_cocontract_time >= self.cfg.min_event_interval_s:
                    self.last_cocontract_time = now - self.session_t0
                    self._append_event(
                        f"Co-contraction event | L={self.side_a_level:.2f} R={self.side_b_level:.2f}"
                    )
            self.cocontract_active = cocontract_now

            if event_started:
                self.event_count += 1
                self.event_times.append(now - self.session_t0)
                self._append_event(f"Activation event | env_norm={env_n:.2f}")
            if active and np.random.rand() < 0.004:
                self._append_event("Sustained contraction")

        suffix = self._source_status_suffix()
        if suffix:
            self.status_text.set_text(
                f"Source: {self.source_name} | +{len(samples_dual)} samples | rate~{self.measured_rate_hz:6.1f} Hz | {suffix}"
            )
        else:
            self.status_text.set_text(
                f"Source: {self.source_name} | +{len(samples_dual)} samples | rate~{self.measured_rate_hz:6.1f} Hz"
            )

    def _update_plot_lines(self) -> None:
        for key, line in self.lines.items():
            mag = np.abs(np.array(self.buffers[key], dtype=np.float32))
            line.set_ydata(mag[::self.render_stride])

        self._apply_autoscale_if_enabled()
        self._draw_event_markers()

        self.metric_frame_counter += 1
        should_recompute_metrics = (self.metric_frame_counter % self.metric_every_n_frames) == 0
        if should_recompute_metrics:
            self.cached_improvements = self._compute_stage_improvements()
            for key, badge in self.stage_badges.items():
                val = self.cached_improvements.get(key, 0.0)
                is_pos = val >= 0
                badge.set_text(f"{val:+5.1f}% cleaner")
                if is_pos:
                    badge.set_bbox(dict(boxstyle="round,pad=0.25", facecolor="#DCFCE7", edgecolor="#86EFAC", alpha=0.9))
                else:
                    badge.set_bbox(dict(boxstyle="round,pad=0.25", facecolor="#FEE2E2", edgecolor="#FCA5A5", alpha=0.9))

        improvements = self.cached_improvements

        env = np.array(self.buffers["envelope"], dtype=np.float32)
        p95 = float(np.percentile(env, 95))
        high_y = max(0.05, p95 * self.cfg.event_threshold_high)
        low_y = max(0.03, p95 * self.cfg.event_threshold_low)

        self.env_high_line.set_ydata(np.full_like(self.time_axis, high_y))
        self.env_low_line.set_ydata(np.full_like(self.time_axis, low_y))

        event_body = "\n".join(self.event_log) if self.event_log else "(no events yet)"
        self.event_text.set_text("Events:\n" + event_body)

        if self.clarity_text is not None and should_recompute_metrics:
            self.clarity_text.set_text(self._format_clarity_metrics(improvements, compact=self.ui_mode == "gripper"))

        if self.ui_mode == "gripper" and self.clarity_bar is not None and self.clarity_text_small is not None and should_recompute_metrics:
            env_gain = float(np.clip(improvements.get("envelope", 0.0), -100.0, 100.0))
            gain_pos = max(0.0, env_gain)
            width = 8.0 * (gain_pos / 100.0)
            self.clarity_bar.set_width(width)
            self.clarity_text_small.set_text(f"Clarity gain (envelope): {env_gain:+5.1f}%")
            if env_gain >= 0:
                self.clarity_bar.set_facecolor("#22C55E")
                self.clarity_bar.set_edgecolor("#22C55E")
            else:
                self.clarity_bar.set_facecolor("#EF4444")
                self.clarity_bar.set_edgecolor("#EF4444")

        if self.ui_mode == "debug" and self.debug_text is not None:
            last_vals = {k: float(self.buffers[k][-1]) for k in self.buffers.keys()}
            env_norm = self._norm_envelope()
            self.debug_text.set_text(
                "\n".join([
                    f"ui_mode         : {self.ui_mode}",
                    f"paused          : {self.paused}",
                    f"autoscale       : {self.autoscale_enabled}",
                    f"fs_target_hz    : {self.cfg.sample_rate_hz}",
                    f"fs_measured_hz  : {self.measured_rate_hz:7.2f}",
                    f"samples_total   : {self.total_samples}",
                    f"events_total    : {self.event_count}",
                    f"event_active    : {self.events.active}",
                    f"co_contract     : {self.cocontract_active}",
                    f"calibrated      : {self.has_calibration}",
                    f"calibrating_now : {self.calibration_active}",
                    f"dual_delay_sec  : {self.dual_delay_sec if self.emulate_dual_delay else 0.0:0.2f}",
                    f"thr_high_norm   : {self.cfg.event_threshold_high:0.3f}",
                    f"thr_low_norm    : {self.cfg.event_threshold_low:0.3f}",
                ])
            )

            self.debug_text_secondary.set_text(
                "\n".join([
                    f"raw_v           : {last_vals['raw']:0.4f}",
                    f"notch_v         : {last_vals['notch']:0.4f}",
                    f"bandpass_v      : {last_vals['bandpass']:0.4f}",
                    f"rectified_v     : {last_vals['rectified']:0.4f}",
                    f"lowpass_v       : {last_vals['lowpass']:0.4f}",
                    f"envelope_v      : {last_vals['envelope']:0.4f}",
                    f"envelope_norm   : {env_norm:0.4f}",
                    f"left_norm       : {self.side_a_level:0.4f}",
                    f"right_norm      : {self.side_b_level:0.4f}",
                    f"grip_force_n    : {self.gripper.grip_force_n:0.2f}",
                    f"grip_label      : {self.gripper.grip_label}",
                ])
            )

    def _animate(self, _frame: int):
        try:
            self._step_engine()
            self._update_plot_lines()
            self._update_gripper_panel()
            self._engine_error_count = 0
        except Exception as exc:
            self._engine_error_count += 1
            self._append_event(f"Engine error #{self._engine_error_count}: {exc}")
            self._restart_live_source("engine exception")
            if self._engine_error_count >= 3:
                self._activate_synthetic_failover("repeated engine errors")

        artists = list(self.lines.values())
        artists.extend(list(self.stage_badges.values()))
        if self.event_marker_line is not None:
            artists.append(self.event_marker_line)
        if self.ui_mode == "gripper":
            artists.extend(self.finger_patches)
            artists.extend([self.force_bar, self.grip_text])
            if self.pad_bar_left is not None:
                artists.append(self.pad_bar_left)
            if self.pad_bar_right is not None:
                artists.append(self.pad_bar_right)
            if self.pad_value_text is not None:
                artists.append(self.pad_value_text)
            if self.clarity_bar is not None:
                artists.append(self.clarity_bar)
            if self.clarity_text_small is not None:
                artists.append(self.clarity_text_small)
        else:
            if self.debug_text is not None:
                artists.append(self.debug_text)
            if self.debug_text_secondary is not None:
                artists.append(self.debug_text_secondary)

        if self.clarity_text is not None:
            artists.append(self.clarity_text)

        artists.extend([self.status_text, self.event_text, self.env_high_line, self.env_low_line])
        return artists

    def run(self) -> None:
        self._setup_figure()
        started = self._safe_start_source()
        if not started:
            self._activate_synthetic_failover("startup failure")
        self._append_event("System online")
        self._append_event(f"Input source selected: {self.source_name}")
        self._append_event(f"UI mode: {self.ui_mode}")

        try:
            self.ani = FuncAnimation(
                self.fig,
                self._animate,
                interval=self.cfg.frame_interval_ms,
                blit=False,
                cache_frame_data=False,
            )
            plt.show()
        finally:
            self._safe_stop_source()


# =============================================================================
# Source Selection + Entrypoint
# =============================================================================


def build_source(args: argparse.Namespace, cfg: DemoConfig) -> Tuple[BaseSignalSource, str]:
    preferred = args.source.lower()

    def _load_ble_config(path: Path) -> Dict[str, str]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return {str(k): str(v) for k, v in payload.items() if isinstance(v, (str, int, float))}
            return {}
        except Exception:
            return {}

    def _save_ble_config(path: Path, payload: Dict[str, str]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    if preferred == "ble":
        cfg_path = Path(args.ble_config).expanduser() if args.ble_config else (Path(__file__).resolve().parent / "demo_ble_config.json")
        saved = _load_ble_config(cfg_path)

        address = args.ble_address or saved.get("address")
        char_uuid = args.ble_char or saved.get("char_uuid")
        device_name = args.ble_device_name or saved.get("device_name") or "MYOWARE"
        service_uuid = args.ble_service or saved.get("service_uuid")

        try:
            source = BLEEMGSource(
                cfg.sample_rate_hz,
                address=address,
                char_uuid=char_uuid,
                device_name=device_name,
                service_uuid=service_uuid,
                scan_timeout_s=args.ble_scan_timeout,
                reconnect_backoff_s=args.ble_backoff,
                max_reconnect_backoff_s=args.ble_max_backoff,
                data_timeout_s=args.ble_data_timeout,
            )
            source.start()
            time.sleep(0.8)
            source.stop()

            resolved_address = source.resolved_address or address
            resolved_char = source.resolved_char_uuid or char_uuid

            if not resolved_address or not resolved_char:
                raise RuntimeError("BLE auto-configuration failed to resolve address/characteristic")

            if not args.ble_no_save:
                _save_ble_config(
                    cfg_path,
                    {
                        "address": resolved_address,
                        "char_uuid": resolved_char,
                        "device_name": device_name,
                        "service_uuid": service_uuid or "",
                    },
                )

            return (
                BLEEMGSource(
                    cfg.sample_rate_hz,
                    address=resolved_address,
                    char_uuid=resolved_char,
                    device_name=device_name,
                    service_uuid=service_uuid,
                    scan_timeout_s=args.ble_scan_timeout,
                    reconnect_backoff_s=args.ble_backoff,
                    max_reconnect_backoff_s=args.ble_max_backoff,
                    data_timeout_s=args.ble_data_timeout,
                ),
                f"BLE {resolved_address}",
            )
        except Exception:
            if args.strict_source:
                raise
            return SyntheticEMGSource(cfg.sample_rate_hz), "Synthetic Fallback (BLE failed)"

    if preferred == "serial":
        if not args.port:
            raise ValueError("Serial source requires --port")

        try:
            source = SerialEMGSource(cfg.sample_rate_hz, args.port, args.baud)
            source.start()
            source.stop()
            return SerialEMGSource(cfg.sample_rate_hz, args.port, args.baud), f"Serial {args.port}"
        except Exception:
            if args.strict_source:
                raise
            return SyntheticEMGSource(cfg.sample_rate_hz), "Synthetic Fallback (Serial failed)"

    if preferred == "dataset":
        dataset_dir = args.dataset_dir
        if dataset_dir is None:
            dataset_dir = str(Path(__file__).resolve().parent / "EMGdataset" / "dataset")

        try:
            source = DatasetReplaySource(
                sample_rate_hz=cfg.sample_rate_hz,
                dataset_dir=dataset_dir,
                dataset_source=args.dataset_source,
                channel=args.dataset_channel,
                side_a_channel=args.side_a_channel,
                side_b_channel=args.side_b_channel,
                replay_speed=args.replay_speed,
                loop=args.replay_loop,
            )
            source.start()
            source.stop()
            return (
                DatasetReplaySource(
                    sample_rate_hz=cfg.sample_rate_hz,
                    dataset_dir=dataset_dir,
                    dataset_source=args.dataset_source,
                    channel=args.dataset_channel,
                    side_a_channel=args.side_a_channel,
                    side_b_channel=args.side_b_channel,
                    replay_speed=args.replay_speed,
                    loop=args.replay_loop,
                ),
                f"Dataset Replay ({args.dataset_source})",
            )
        except Exception:
            if args.strict_source:
                raise
            return SyntheticEMGSource(cfg.sample_rate_hz), "Synthetic Fallback (Dataset replay failed)"

    return SyntheticEMGSource(cfg.sample_rate_hz), "Synthetic"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Public engagement EMG live demonstrator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--source", choices=["ble", "serial", "synthetic", "dataset"], default="synthetic")
    parser.add_argument("--ui-mode", choices=["gripper", "debug"], default="gripper", help="Right panel mode")
    parser.add_argument("--strict-source", action="store_true", help="Fail instead of auto-fallback to synthetic")

    parser.add_argument("--port", default="COM3", help="Serial COM port for ESP32 mode")
    parser.add_argument("--baud", type=int, default=921600, help="Serial baud rate")

    parser.add_argument("--ble-address", default=None, help="BLE device MAC/address")
    parser.add_argument("--ble-char", default=None, help="BLE GATT characteristic UUID for notifications")
    parser.add_argument("--ble-device-name", default="MYOWARE", help="BLE device name hint used for auto-discovery")
    parser.add_argument("--ble-service", default=None, help="Optional BLE service UUID filter")
    parser.add_argument("--ble-config", default="demo_ble_config.json", help="Path to persisted BLE auto-config JSON")
    parser.add_argument("--ble-no-save", action="store_true", help="Do not persist discovered BLE settings")
    parser.add_argument("--ble-scan-timeout", type=float, default=6.0, help="BLE scan timeout in seconds")
    parser.add_argument("--ble-data-timeout", type=float, default=3.0, help="Reconnect if BLE notifications stall")
    parser.add_argument("--ble-backoff", type=float, default=1.0, help="BLE reconnect initial backoff")
    parser.add_argument("--ble-max-backoff", type=float, default=8.0, help="BLE reconnect max backoff")

    parser.add_argument("--dataset-dir", default=None, help="Base dataset directory (contains raw_signals/filtered_signals)")
    parser.add_argument("--dataset-source", choices=["raw", "filtered"], default="raw", help="Dataset subfolder for replay")
    parser.add_argument("--dataset-channel", default=None, help="Optional channel name or index for multichannel CSV replay")
    parser.add_argument("--side-a-channel", default=None, help="Optional left/close channel name or index")
    parser.add_argument("--side-b-channel", default=None, help="Optional right/open channel name or index")
    parser.add_argument("--replay-speed", type=float, default=1.0, help="Dataset replay speed multiplier")
    parser.add_argument("--replay-loop", action="store_true", help="Loop dataset files when replay reaches end")
    parser.add_argument("--emulate-dual-delay", action="store_true", help="Emulate dual-pad timing by delaying side B")
    parser.add_argument("--dual-delay-sec", type=float, default=1.0, help="Delay to apply to side B in emulation mode")

    parser.add_argument("--sample-rate", type=int, default=1000, help="Pipeline sample rate")
    parser.add_argument("--view-seconds", type=float, default=8.0, help="Visible scrolling window")
    parser.add_argument("--frame-ms", type=int, default=40, help="UI frame interval")
    parser.add_argument("--lightweight-mode", action="store_true", help="Reduce rendering load for low-spec machines")

    parser.add_argument("--event-high", type=float, default=0.28, help="Event trigger normalized threshold")
    parser.add_argument("--event-low", type=float, default=0.20, help="Event reset normalized threshold")
    parser.add_argument("--runtime-recovery", action="store_true", default=True, help="Enable runtime source auto-recovery")
    parser.add_argument("--no-runtime-recovery", action="store_false", dest="runtime_recovery", help="Disable runtime source auto-recovery")
    parser.add_argument("--source-stall-timeout", type=float, default=6.0, help="Seconds of no samples before recovery")
    parser.add_argument("--source-restart-cooldown", type=float, default=4.0, help="Minimum seconds between recoveries")
    parser.add_argument("--source-max-restarts", type=int, default=5, help="Max recoveries before synthetic failover")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    cfg = DemoConfig(
        sample_rate_hz=args.sample_rate,
        view_seconds=args.view_seconds,
        frame_interval_ms=args.frame_ms,
        event_threshold_high=args.event_high,
        event_threshold_low=args.event_low,
    )

    source, source_name = build_source(args, cfg)
    dashboard = PublicEngagementDashboard(
        cfg,
        source,
        source_name,
        ui_mode=args.ui_mode,
        emulate_dual_delay=args.emulate_dual_delay,
        dual_delay_sec=args.dual_delay_sec,
    )

    if args.lightweight_mode:
        dashboard.metric_every_n_frames = 5
        dashboard.autoscale_alpha = 0.30
        dashboard.render_stride = max(dashboard.render_stride, 3)
        dashboard.time_axis_view = dashboard.time_axis[::dashboard.render_stride]

    dashboard.runtime_recovery_enabled = bool(args.runtime_recovery)
    dashboard.source_stall_timeout_s = max(1.0, float(args.source_stall_timeout))
    dashboard.source_restart_cooldown_s = max(0.5, float(args.source_restart_cooldown))
    dashboard.source_max_restarts = max(1, int(args.source_max_restarts))

    dashboard.run()


if __name__ == "__main__":
    main()
