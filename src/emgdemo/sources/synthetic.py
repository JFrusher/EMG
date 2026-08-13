"""Synthetic EMG — the fallback that always works, and the default for a cold start.

Two corrections from the original:

* It accumulated phase as ``2*pi*dt`` and then multiplied by ``2*pi*f`` again inside
  every sine, so its '70 Hz' component actually sat near 440 Hz — above the bandpass it
  was meant to demonstrate. State here is plain elapsed time.
* It generated however many samples the caller asked for, whenever asked. Standing in
  for a 1 kHz stream, that made it a firehose: the engine measured tens of kilohertz and
  retuned every filter to match. It is now paced by a clock like any other live source.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np

from .base import ADC_REFERENCE_V, Sample, SourceStatus

BASELINE_V = 1.65

#: Slow contraction cycles for each pad, deliberately at different rates so the two
#: sides drift in and out of phase instead of looking mirrored.
_BURST_HZ_A = 0.42
_BURST_HZ_B = 0.38

_EMG_COMPONENTS_A = ((70.0, 0.20, 0.0), (95.0, 0.16, 0.0), (130.0, 0.12, 0.0))
_EMG_COMPONENTS_B = ((65.0, 0.18, 0.8), (110.0, 0.13, 1.1), (145.0, 0.10, 0.2))

_NOISE_V = 0.05
_POWERLINE_HZ = 50.0
_POWERLINE_V = 0.05


def _components(t: np.ndarray, spec) -> np.ndarray:
    total = np.zeros_like(t)
    for freq, amplitude, phase in spec:
        total += amplitude * np.sin(2 * np.pi * freq * t + phase)
    return total


class SyntheticSource:
    """Emits a believable EMG stream, paced in real time like the hardware it stands in for."""

    def __init__(
        self,
        sample_rate_hz: float = 1000.0,
        seed: int | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ):
        self.sample_rate_hz = float(sample_rate_hz)
        self.clock = clock
        self._rng = np.random.default_rng(seed)
        self._running = False
        self._t = 0.0
        self._budget = 0.0
        self._last_t = 0.0

    def start(self) -> None:
        self._running = True
        self._budget = 0.0
        self._last_t = self.clock()

    def stop(self) -> None:
        self._running = False

    def status(self) -> SourceStatus:
        return SourceStatus(state="streaming" if self._running else "stopped")

    def read(self, max_samples: int) -> list[Sample]:
        if not self._running or max_samples <= 0:
            return []

        now = self.clock()
        elapsed = max(0.0, now - self._last_t)
        self._last_t = now

        self._budget += elapsed * self.sample_rate_hz
        count = min(int(max_samples), int(self._budget))
        if count <= 0:
            return []
        self._budget -= count

        dt = 1.0 / self.sample_rate_hz
        t = self._t + np.arange(1, count + 1) * dt
        self._t = float(t[-1])

        burst_a = (0.5 * (1.0 + np.sin(2 * np.pi * _BURST_HZ_A * t))) ** 1.9
        burst_b = (0.5 * (1.0 + np.sin(2 * np.pi * _BURST_HZ_B * t + 1.8))) ** 2.0

        powerline = _POWERLINE_V * np.sin(2 * np.pi * _POWERLINE_HZ * t)
        noise_a = self._rng.normal(0.0, _NOISE_V, count)
        noise_b = self._rng.normal(0.0, _NOISE_V, count)

        side_a = BASELINE_V + burst_a * (_components(t, _EMG_COMPONENTS_A) + noise_a + powerline)
        side_b = BASELINE_V + burst_b * (_components(t, _EMG_COMPONENTS_B) + noise_b + powerline)

        side_a = np.clip(side_a, 0.0, ADC_REFERENCE_V)
        side_b = np.clip(side_b, 0.0, ADC_REFERENCE_V)

        return [(float(a), float(b)) for a, b in zip(side_a, side_b, strict=True)]
