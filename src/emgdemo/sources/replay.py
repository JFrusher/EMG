"""Replay recorded CSVs as though they were arriving live.

Paced by a wall clock rather than by how fast the caller asks, so it behaves like a real
stream — including falling behind if the consumer stalls. The clock is injectable, which
is what makes it the fixture the rest of the system is built against.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from .base import ADC_MAX_COUNTS, ADC_REFERENCE_V, Sample, SourceStatus

BASELINE_V = 1.65

#: Columns that are indices or timestamps, never signal.
_NON_SIGNAL_HINTS = ("unnamed", "timestamp", "time", "index")


class NoDatasetFiles(Exception):
    """Raised when a replay folder holds nothing playable."""


def _is_signal_column(name: str) -> bool:
    lowered = str(name).lower()
    return not any(hint in lowered for hint in _NON_SIGNAL_HINTS)


def _to_volts(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    peak = np.nanmax(values) if values.size else 0.0
    if np.isfinite(peak) and peak > ADC_REFERENCE_V:
        values = (values / ADC_MAX_COUNTS) * ADC_REFERENCE_V
    values = np.nan_to_num(values, nan=BASELINE_V, posinf=ADC_REFERENCE_V, neginf=0.0)
    return np.clip(values, 0.0, ADC_REFERENCE_V)


class DatasetReplaySource:
    def __init__(
        self,
        folder: Path | str,
        sample_rate_hz: float = 1000.0,
        side_a_channel: str | None = None,
        side_b_channel: str | None = None,
        channel: str | None = None,
        replay_speed: float = 1.0,
        loop: bool = False,
        clock: Callable[[], float] = time.perf_counter,
    ):
        self.folder = Path(folder)
        self.sample_rate_hz = float(sample_rate_hz)
        self.side_a_channel = side_a_channel
        self.side_b_channel = side_b_channel
        self.channel = channel
        self.replay_speed = max(0.05, float(replay_speed))
        self.loop = loop
        self.clock = clock

        self.files = self._discover_files()
        self._file_index = 0
        self._current_name = "(none)"
        self._side_a = np.empty(0)
        self._side_b = np.empty(0)
        self._position = 0

        self._running = False
        self._budget = 0.0
        self._last_t = 0.0

    def _discover_files(self) -> list[Path]:
        if not self.folder.is_dir():
            raise NoDatasetFiles(f"Replay folder does not exist: {self.folder}")
        files = sorted(self.folder.glob("*.csv"))
        if not files:
            raise NoDatasetFiles(f"No CSV files in {self.folder}")
        return files

    def _pick(self, frame: pd.DataFrame, columns: Sequence[str], selector: str) -> np.ndarray:
        if str(selector).isdigit():
            index = int(selector)
            if not 0 <= index < len(columns):
                raise ValueError(f"Channel {index} out of range 0..{len(columns) - 1}")
            return frame[columns[index]].to_numpy()
        if selector not in columns:
            raise ValueError(f"Channel {selector!r} not found. Available: {list(columns)}")
        return frame[selector].to_numpy()

    def _load(self, path: Path) -> tuple[np.ndarray, np.ndarray]:
        frame = pd.read_csv(path)
        frame = frame[[c for c in frame.columns if _is_signal_column(c)]]
        numeric = [c for c in frame.columns if np.issubdtype(frame[c].dtype, np.number)]
        if not numeric:
            raise ValueError(f"No numeric columns in {path.name}")

        if self.side_a_channel is not None or self.side_b_channel is not None:
            zeros = np.zeros(len(frame))
            wanted_a, wanted_b = self.side_a_channel, self.side_b_channel
            side_a = self._pick(frame, numeric, wanted_a) if wanted_a else zeros
            side_b = self._pick(frame, numeric, wanted_b) if wanted_b else zeros
        elif self.channel is not None:
            side_a = self._pick(frame, numeric, self.channel)
            side_b = np.zeros(len(frame))
        elif "adc_raw_value" in numeric:
            side_a = frame["adc_raw_value"].to_numpy()
            side_b = np.zeros(len(frame))
        elif len(numeric) >= 2:
            side_a = frame[numeric[0]].to_numpy()
            side_b = frame[numeric[1]].to_numpy()
        else:
            side_a = frame[numeric[0]].to_numpy()
            side_b = np.zeros(len(frame))

        return _to_volts(side_a), _to_volts(side_b)

    def _advance_file(self) -> bool:
        """Load the next playable file, skipping any that fail to parse."""
        while self._file_index < len(self.files):
            path = self.files[self._file_index]
            self._file_index += 1
            try:
                self._side_a, self._side_b = self._load(path)
            except (ValueError, pd.errors.ParserError):
                continue
            self._position = 0
            self._current_name = path.name
            return True

        if self.loop and self.files:
            self._file_index = 0
            return self._advance_file()
        return False

    def start(self) -> None:
        self._budget = 0.0
        self._last_t = self.clock()
        if self._side_a.size == 0 and not self._advance_file():
            raise NoDatasetFiles(f"No playable CSV files in {self.folder}")
        self._running = True

    def stop(self) -> None:
        self._running = False

    def status(self) -> SourceStatus:
        state = "streaming" if self._running else "stopped"
        detail = (
            f"file {min(self._file_index, len(self.files))}/{len(self.files)} "
            f"{self._current_name} sample {self._position}/{self._side_a.size}"
        )
        return SourceStatus(state=state, detail=detail)

    def read(self, max_samples: int) -> list[Sample]:
        if not self._running or max_samples <= 0:
            return []

        now = self.clock()
        elapsed = max(0.0, now - self._last_t)
        self._last_t = now

        self._budget += elapsed * self.sample_rate_hz * self.replay_speed
        wanted = min(int(max_samples), int(self._budget))
        if wanted <= 0:
            return []
        self._budget -= wanted

        out: list[Sample] = []
        while len(out) < wanted:
            if self._position >= self._side_a.size and not self._advance_file():
                self._running = False
                break

            end = min(self._position + (wanted - len(out)), self._side_a.size)
            chunk_a = self._side_a[self._position : end]
            chunk_b = self._side_b[self._position : end]
            out.extend((float(a), float(b)) for a, b in zip(chunk_a, chunk_b, strict=True))
            self._position = end

        return out
