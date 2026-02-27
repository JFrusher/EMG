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


class SyntheticEMGSource(BaseSignalSource):
    """Stable synthetic source used as default fallback in public demos."""

    def __init__(self, sample_rate_hz: int):
        super().__init__(sample_rate_hz)
        self._running = False
        self._phase = 0.0
        self._activation_phase = 0.0

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def read_available(self, max_samples: int) -> List[float]:
        if not self._running or max_samples <= 0:
            return []

        out: List[float] = []
        dt = 1.0 / self.sample_rate_hz

        for _ in range(max_samples):
            self._phase += 2.0 * math.pi * dt
            self._activation_phase += 2.0 * math.pi * 0.45 * dt

            burst = 0.5 * (1.0 + math.sin(self._activation_phase))
            burst = burst ** 1.8

            emg = (
                0.20 * math.sin(2 * math.pi * 70 * self._phase)
                + 0.16 * math.sin(2 * math.pi * 95 * self._phase)
                + 0.12 * math.sin(2 * math.pi * 130 * self._phase)
            )
            noise = np.random.normal(0.0, 0.05)
            powerline = 0.05 * math.sin(2 * math.pi * 50 * self._phase)

            v = 1.65 + burst * (emg + noise + powerline)
            out.append(float(np.clip(v, 0.0, 3.3)))

        return out


class SerialEMGSource(BaseSignalSource):
    """Serial source reading ESP32 CSV lines: timestamp_ms,adc_raw_value"""

    def __init__(self, sample_rate_hz: int, port: str, baud: int = 921600):
        super().__init__(sample_rate_hz)
        self.port = port
        self.baud = baud
        self._serial = None
        self._running = False

    def start(self) -> None:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required for serial source") from exc

        self._serial = serial.Serial(self.port, self.baud, timeout=0)
        self._running = True

    def stop(self) -> None:
        self._running = False
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    def _decode_line(self, line: str) -> Optional[float]:
        if not line or line.startswith("===") or line.startswith("---"):
            return None

        parts = line.split(",")
        if len(parts) != 2:
            return None

        try:
            adc_raw = int(parts[1])
        except ValueError:
            return None

        return float(np.clip((adc_raw / 4095.0) * 3.3, 0.0, 3.3))

    def read_available(self, max_samples: int) -> List[float]:
        if not self._running or self._serial is None or max_samples <= 0:
            return []

        samples: List[float] = []
        for _ in range(max_samples):
            try:
                raw = self._serial.readline()
            except Exception:
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

        return samples


class DatasetReplaySource(BaseSignalSource):
    """Replay dataset CSV files sequentially as pseudo-live EMG input."""

    def __init__(
        self,
        sample_rate_hz: int,
        dataset_dir: str,
        dataset_source: str = "raw",
        channel: Optional[str] = None,
        replay_speed: float = 1.0,
        loop: bool = False,
    ):
        super().__init__(sample_rate_hz)
        self.dataset_dir = dataset_dir
        self.dataset_source = dataset_source
        self.channel = channel
        self.replay_speed = max(0.05, float(replay_speed))
        self.loop = loop

        self.files: List[str] = self._discover_files()
        self.file_idx = 0
        self.current_data = np.array([], dtype=np.float32)
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

    def _extract_signal(self, filepath: str) -> np.ndarray:
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

        if self.channel is not None:
            if str(self.channel).isdigit():
                idx = int(self.channel)
                if idx < 0 or idx >= len(numeric_cols):
                    raise IndexError(
                        f"Channel index {idx} out of range for {os.path.basename(filepath)}; "
                        f"available 0..{len(numeric_cols)-1}"
                    )
                sig = df[numeric_cols[idx]].values.astype(np.float32)
            else:
                if self.channel not in numeric_cols:
                    raise ValueError(
                        f"Channel '{self.channel}' not found in {os.path.basename(filepath)}. "
                        f"Available: {numeric_cols}"
                    )
                sig = df[self.channel].values.astype(np.float32)
        else:
            if "adc_raw_value" in df.columns:
                sig = df["adc_raw_value"].values.astype(np.float32)
            elif "voltage" in df.columns:
                sig = df["voltage"].values.astype(np.float32)
            elif len(numeric_cols) == 1:
                sig = df[numeric_cols[0]].values.astype(np.float32)
            else:
                sig = df[numeric_cols].mean(axis=1).values.astype(np.float32)

        if np.nanmax(sig) > 3.3:
            sig = (sig / 4095.0) * 3.3

        sig = np.nan_to_num(sig, nan=1.65, posinf=3.3, neginf=0.0)
        return np.clip(sig, 0.0, 3.3)

    def _load_current_file(self) -> bool:
        if self.file_idx >= len(self.files):
            if self.loop:
                self.file_idx = 0
            else:
                return False

        try:
            current_path = self.files[self.file_idx]
            self.current_data = self._extract_signal(current_path)
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
        if self.current_data.size == 0:
            loaded = self._load_current_file()
            if not loaded:
                raise RuntimeError("Unable to load any dataset files for replay")

    def stop(self) -> None:
        self._running = False

    def read_available(self, max_samples: int) -> List[float]:
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

        out: List[float] = []
        while len(out) < want:
            if self.current_pos >= len(self.current_data):
                if not self._load_current_file():
                    self._running = False
                    break

            remaining = want - len(out)
            end = min(self.current_pos + remaining, len(self.current_data))
            chunk = self.current_data[self.current_pos:end]
            out.extend(float(v) for v in chunk)
            self.current_pos = end

        return out

    def status_summary(self) -> str:
        file_number = min(self.file_idx, len(self.files))
        total = len(self.files)
        return (
            f"dataset file {file_number}/{total}: {self.current_file} | "
            f"sample {self.current_pos}/{len(self.current_data)}"
        )


class BLEEMGSource(BaseSignalSource):
    """BLE source via notification callback queue.

    Supports two common payload forms:
    - int16 little-endian samples
    - UTF-8 CSV text lines, where the last field is interpreted as ADC-like value
    """

    def __init__(self, sample_rate_hz: int, address: str, char_uuid: str):
        super().__init__(sample_rate_hz)
        self.address = address
        self.char_uuid = char_uuid
        self._running = False
        self._queue: "queue.Queue[float]" = queue.Queue(maxsize=20000)
        self._loop_thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

    def start(self) -> None:
        try:
            import bleak  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("bleak is required for BLE source") from exc

        self._running = True
        self._stop_evt.clear()
        self._loop_thread = threading.Thread(target=self._run_ble_loop, daemon=True)
        self._loop_thread.start()

    def stop(self) -> None:
        self._running = False
        self._stop_evt.set()
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=2.0)
        self._loop_thread = None

    def read_available(self, max_samples: int) -> List[float]:
        if not self._running or max_samples <= 0:
            return []

        out: List[float] = []
        for _ in range(max_samples):
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out

    def _push(self, value: float) -> None:
        if not self._running:
            return
        value = float(np.clip(value, 0.0, 3.3))
        try:
            self._queue.put_nowait(value)
        except queue.Full:
            try:
                _ = self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(value)
            except queue.Full:
                pass

    def _parse_payload(self, payload: bytes) -> List[float]:
        if not payload:
            return []

        if len(payload) % 2 == 0:
            try:
                int16_vals = np.frombuffer(payload, dtype="<i2")
                scaled = ((int16_vals.astype(np.float32) + 32768.0) / 65535.0) * 3.3
                return [float(np.clip(v, 0.0, 3.3)) for v in scaled]
            except Exception:
                pass

        try:
            text = payload.decode("utf-8", errors="ignore").strip()
            if not text:
                return []
            values: List[float] = []
            for line in text.splitlines():
                parts = [p.strip() for p in line.split(",") if p.strip()]
                if not parts:
                    continue
                try:
                    last = float(parts[-1])
                except ValueError:
                    continue
                if last > 3.3:
                    v = (last / 4095.0) * 3.3
                else:
                    v = last
                values.append(float(np.clip(v, 0.0, 3.3)))
            return values
        except Exception:
            return []

    def _run_ble_loop(self) -> None:
        import asyncio
        from bleak import BleakClient

        async def _runner() -> None:
            while not self._stop_evt.is_set():
                try:
                    async with BleakClient(self.address, timeout=8.0) as client:
                        async def _on_notify(_: int, data: bytearray) -> None:
                            parsed = self._parse_payload(bytes(data))
                            for value in parsed:
                                self._push(value)

                        await client.start_notify(self.char_uuid, _on_notify)
                        while not self._stop_evt.is_set() and client.is_connected:
                            await asyncio.sleep(0.05)

                except Exception:
                    await asyncio.sleep(1.0)

        try:
            asyncio.run(_runner())
        except Exception:
            self._running = False


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

    def step(self, envelope_norm: float) -> None:
        target_force = float(np.clip(envelope_norm, 0.0, 1.0) * 100.0)
        self.grip_force_n += (target_force - self.grip_force_n) * 0.15

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

    def __init__(self, cfg: DemoConfig, source: BaseSignalSource, source_name: str, ui_mode: str = "gripper"):
        self.cfg = cfg
        self.source = source
        self.source_name = source_name
        self.ui_mode = ui_mode

        self.pipeline = StreamingEMGPipeline(cfg)
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

        self.session_t0 = time.perf_counter()
        self.last_frame_t = self.session_t0
        self.event_log: Deque[str] = deque(maxlen=8)
        self.event_count = 0
        self.total_samples = 0
        self.recent_samples = 0
        self.recent_t0 = self.session_t0
        self.measured_rate_hz = 0.0
        self.paused = False
        self.autoscale_enabled = False

        self.fig = None
        self.axes = {}
        self.lines = {}
        self.fills = {}
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
        self.event_times: Deque[float] = deque(maxlen=12)
        self.event_marker_artists: List = []

    def _norm_envelope(self) -> float:
        env = np.array(self.buffers["envelope"], dtype=np.float32)
        p95 = float(np.percentile(env, 95))
        ref = max(p95, 0.08)
        return float(np.clip(env[-1] / ref, 0.0, 1.0))

    def _append_event(self, msg: str) -> None:
        t = time.perf_counter() - self.session_t0
        self.event_log.appendleft(f"[{t:6.2f}s] {msg}")

    def _source_status_suffix(self) -> str:
        if isinstance(self.source, DatasetReplaySource):
            return self.source.status_summary()
        if isinstance(self.source, BLEEMGSource):
            return f"BLE queue={self.source._queue.qsize()}"
        return ""

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
            line, = ax.plot(self.time_axis, data, linewidth=1.6, color=self.stage_colors[key])
            fill = ax.fill_between(self.time_axis, 0, data, color=self.stage_colors[key], alpha=0.10)
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
            self.fills[key] = fill
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

    def _setup_gripper_panel(self, panel_ax) -> None:
        panel_ax.text(5, 9.65, "Public Engagement Control Panel", ha="center", va="center", fontsize=12, fontweight="bold")

        panel_ax.text(1.0, 9.18, "Noise Reduction vs Raw (live)", fontsize=8.8, fontweight="bold")
        self.clarity_text = panel_ax.text(
            1.0,
            8.95,
            "(waiting for signal)",
            fontsize=7.8,
            va="top",
            family="monospace",
        )

        panel_ax.text(1.0, 7.60, "Signal Clarity", fontsize=8.8, fontweight="bold")
        clarity_bg = patches.Rectangle((1.0, 7.26), 8.0, 0.28, facecolor="#E5E7EB", edgecolor="#9CA3AF")
        panel_ax.add_patch(clarity_bg)
        self.clarity_bar = patches.Rectangle((1.0, 7.26), 0.0, 0.28, facecolor="#22C55E", edgecolor="#22C55E")
        panel_ax.add_patch(self.clarity_bar)
        self.clarity_text_small = panel_ax.text(1.0, 6.97, "Clarity gain: +0.0%", fontsize=8.2)

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

        self.status_text = panel_ax.text(1.0, 0.95, "Source: starting...", fontsize=9)
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

        btn_pause = Button(ax_pause, "Pause")
        btn_reset = Button(ax_reset, "Reset")
        btn_snap = Button(ax_snap, "Snapshot")
        btn_scale = Button(ax_scale, "AutoScale")

        btn_pause.on_clicked(self._on_toggle_pause)
        btn_reset.on_clicked(self._on_reset_events)
        btn_snap.on_clicked(self._on_snapshot)
        btn_scale.on_clicked(self._on_toggle_autoscale)

        self.button_widgets = [btn_pause, btn_reset, btn_snap, btn_scale]

    def _on_toggle_pause(self, _event) -> None:
        self.paused = not self.paused
        self._append_event("Paused" if self.paused else "Resumed")

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
        self.fig.savefig(out, dpi=130)
        self._append_event(f"Snapshot saved: {out.name}")

    def _on_toggle_autoscale(self, _event) -> None:
        self.autoscale_enabled = not self.autoscale_enabled
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
            lower = max(0.0, lo - margin)
            ax.set_ylim(lower, hi + margin)

    def _noise_proxy(self, signal_data: np.ndarray) -> float:
        if signal_data.size < 3:
            return 1e-6
        derivative = np.diff(signal_data)
        return float(np.mean(np.abs(derivative)) + 1e-6)

    def _format_clarity_metrics(self) -> str:
        abs_stage = {k: np.abs(np.array(self.buffers[k], dtype=np.float32)) for k in self.stage_keys}
        raw_noise = self._noise_proxy(abs_stage["raw"])

        labels = {
            "notch": "Notch",
            "bandpass": "Bandpass",
            "rectified": "Rectified",
            "lowpass": "Low-pass",
            "envelope": "Envelope",
        }

        lines = [f"Raw jitter: {raw_noise:0.5f}"]
        for key in ["notch", "bandpass", "rectified", "lowpass", "envelope"]:
            stage_noise = self._noise_proxy(abs_stage[key])
            improvement = (1.0 - (stage_noise / raw_noise)) * 100.0
            improvement = float(np.clip(improvement, -300.0, 100.0))
            lines.append(f"{labels[key]:9s}: {improvement:+6.1f}%")

        lines.append("(+ means cleaner than raw)")
        return "\n".join(lines)

    def _compute_stage_improvements(self) -> Dict[str, float]:
        abs_stage = {k: np.abs(np.array(self.buffers[k], dtype=np.float32)) for k in self.stage_keys}
        raw_noise = self._noise_proxy(abs_stage["raw"])
        out: Dict[str, float] = {}
        for key in ["notch", "bandpass", "rectified", "lowpass", "envelope"]:
            stage_noise = self._noise_proxy(abs_stage[key])
            improvement = (1.0 - (stage_noise / raw_noise)) * 100.0
            out[key] = float(np.clip(improvement, -300.0, 100.0))
        return out

    def _draw_event_markers(self) -> None:
        for artist in self.event_marker_artists:
            try:
                artist.remove()
            except Exception:
                pass
        self.event_marker_artists = []

        now = time.perf_counter() - self.session_t0
        for ev_time in self.event_times:
            rel_t = ev_time - now
            if rel_t < -self.cfg.view_seconds or rel_t > 0:
                continue
            for key in self.stage_keys:
                ax = self.axes[key]
                marker = ax.axvline(rel_t, color="#EC4899", linestyle="--", linewidth=1.0, alpha=0.65)
                self.event_marker_artists.append(marker)

    def _update_gripper_panel(self) -> None:
        if self.ui_mode != "gripper":
            return

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
        samples = self.source.read_available(max_samples=expected * 2)

        if len(samples) == 0:
            suffix = self._source_status_suffix()
            if suffix:
                self.status_text.set_text(f"Source: {self.source_name} | waiting for samples... | {suffix}")
            else:
                self.status_text.set_text(f"Source: {self.source_name} | waiting for samples...")
            return

        self.total_samples += len(samples)
        self.recent_samples += len(samples)

        elapsed_rate_window = now - self.recent_t0
        if elapsed_rate_window >= 0.5:
            self.measured_rate_hz = self.recent_samples / elapsed_rate_window
            self.recent_samples = 0
            self.recent_t0 = now

        for raw in samples[: expected * 2]:
            out = self.pipeline.step(raw)
            for key, value in out.items():
                self.buffers[key].append(value)

            env_n = self._norm_envelope()
            event_started, active = self.events.step(env_n, now - self.session_t0)
            self.gripper.step(env_n)

            if event_started:
                self.event_count += 1
                self.event_times.append(now - self.session_t0)
                self._append_event(f"Activation event | env_norm={env_n:.2f}")
            if active and np.random.rand() < 0.004:
                self._append_event("Sustained contraction")

        suffix = self._source_status_suffix()
        if suffix:
            self.status_text.set_text(
                f"Source: {self.source_name} | +{len(samples)} samples | rate~{self.measured_rate_hz:6.1f} Hz | {suffix}"
            )
        else:
            self.status_text.set_text(
                f"Source: {self.source_name} | +{len(samples)} samples | rate~{self.measured_rate_hz:6.1f} Hz"
            )

    def _update_plot_lines(self) -> None:
        for key, line in self.lines.items():
            mag = np.abs(np.array(self.buffers[key], dtype=np.float32))
            line.set_ydata(mag)

            if self.fills.get(key) is not None:
                try:
                    self.fills[key].remove()
                except Exception:
                    pass
            self.fills[key] = self.axes[key].fill_between(
                self.time_axis,
                0,
                mag,
                color=self.stage_colors[key],
                alpha=0.10 if key != "envelope" else 0.18,
            )

        self._apply_autoscale_if_enabled()
        self._draw_event_markers()

        improvements = self._compute_stage_improvements()
        for key, badge in self.stage_badges.items():
            val = improvements.get(key, 0.0)
            is_pos = val >= 0
            badge.set_text(f"{val:+5.1f}% cleaner")
            if is_pos:
                badge.set_bbox(dict(boxstyle="round,pad=0.25", facecolor="#DCFCE7", edgecolor="#86EFAC", alpha=0.9))
            else:
                badge.set_bbox(dict(boxstyle="round,pad=0.25", facecolor="#FEE2E2", edgecolor="#FCA5A5", alpha=0.9))

        env = np.array(self.buffers["envelope"], dtype=np.float32)
        p95 = float(np.percentile(env, 95))
        high_y = max(0.05, p95 * self.cfg.event_threshold_high)
        low_y = max(0.03, p95 * self.cfg.event_threshold_low)

        self.env_high_line.set_ydata(np.full_like(self.time_axis, high_y))
        self.env_low_line.set_ydata(np.full_like(self.time_axis, low_y))

        event_body = "\n".join(self.event_log) if self.event_log else "(no events yet)"
        self.event_text.set_text("Events:\n" + event_body)

        if self.clarity_text is not None:
            self.clarity_text.set_text(self._format_clarity_metrics())

        if self.ui_mode == "gripper" and self.clarity_bar is not None and self.clarity_text_small is not None:
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
                    f"grip_force_n    : {self.gripper.grip_force_n:0.2f}",
                    f"grip_label      : {self.gripper.grip_label}",
                ])
            )

    def _animate(self, _frame: int):
        self._step_engine()
        self._update_plot_lines()
        self._update_gripper_panel()

        artists = list(self.lines.values())
        artists.extend(list(self.stage_badges.values()))
        artists.extend(self.event_marker_artists)
        if self.ui_mode == "gripper":
            artists.extend(self.finger_patches)
            artists.extend([self.force_bar, self.grip_text])
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
        self.source.start()
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
            self.source.stop()


# =============================================================================
# Source Selection + Entrypoint
# =============================================================================


def build_source(args: argparse.Namespace, cfg: DemoConfig) -> Tuple[BaseSignalSource, str]:
    preferred = args.source.lower()

    if preferred == "ble":
        if not args.ble_address or not args.ble_char:
            raise ValueError("BLE source requires --ble-address and --ble-char")

        try:
            source = BLEEMGSource(cfg.sample_rate_hz, args.ble_address, args.ble_char)
            source.start()
            source.stop()
            return BLEEMGSource(cfg.sample_rate_hz, args.ble_address, args.ble_char), "BLE"
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

    parser.add_argument("--dataset-dir", default=None, help="Base dataset directory (contains raw_signals/filtered_signals)")
    parser.add_argument("--dataset-source", choices=["raw", "filtered"], default="raw", help="Dataset subfolder for replay")
    parser.add_argument("--dataset-channel", default=None, help="Optional channel name or index for multichannel CSV replay")
    parser.add_argument("--replay-speed", type=float, default=1.0, help="Dataset replay speed multiplier")
    parser.add_argument("--replay-loop", action="store_true", help="Loop dataset files when replay reaches end")

    parser.add_argument("--sample-rate", type=int, default=1000, help="Pipeline sample rate")
    parser.add_argument("--view-seconds", type=float, default=8.0, help="Visible scrolling window")
    parser.add_argument("--frame-ms", type=int, default=40, help="UI frame interval")

    parser.add_argument("--event-high", type=float, default=0.28, help="Event trigger normalized threshold")
    parser.add_argument("--event-low", type=float, default=0.20, help="Event reset normalized threshold")

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
    dashboard = PublicEngagementDashboard(cfg, source, source_name, ui_mode=args.ui_mode)
    dashboard.run()


if __name__ == "__main__":
    main()
