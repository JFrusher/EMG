"""Map an envelope voltage onto the 0..1 activation level the gripper consumes.

Two strategies, one interface:

``Calibrated``        participant has pressed Calibrate; baseline and span are measured.
``AdaptiveReference`` nobody has calibrated yet; baseline and ceiling are tracked live.

The adaptive path replaces the old ``latest / p95(trailing 8 s)`` reference. That version
divided a quiet signal by its own quiet percentile, so a raised resting baseline — dry
electrodes, a movement artifact — read as a sustained full contraction (R8).
"""

from __future__ import annotations

import numpy as np

from ..config import NormalizeConfig


def _unit(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


class Calibrated:
    """Fixed mapping from a measured calibration capture."""

    def __init__(self, baseline: float, span: float):
        self.baseline = float(baseline)
        self.span = max(float(span), 1e-4)

    def step(self, value: float) -> float:
        return _unit((float(value) - self.baseline) / self.span)


class AdaptiveReference:
    """Self-tuning mapping used before calibration.

    The ceiling rises toward peaks and leaks back down slowly; the baseline sinks toward
    troughs and creeps back up slower still. Steady input pulls them together, so rest
    reads as rest no matter what absolute voltage the electrodes happen to sit at.

    Both edges move gradually in both directions. Tracking peaks and troughs instantly
    looks equivalent and is not: it makes the reference hug the signal's own ripple, so
    a steady envelope jittering by a few percent gets stretched across the whole output
    range and reads as sustained effort.
    """

    def __init__(self, config: NormalizeConfig | None = None):
        self.config = config or NormalizeConfig()
        self._ceiling: float | None = None
        self._baseline: float | None = None
        self._warmup: list[float] = []

    @property
    def baseline(self) -> float:
        return self._baseline or 0.0

    @property
    def ceiling(self) -> float:
        return self._ceiling or 0.0

    def step(self, value: float) -> float:
        value = float(value)

        if self._ceiling is None or self._baseline is None:
            self._seed(value)
            return 0.0

        rising = value > self._ceiling
        rate = self.config.ceiling_attack if rising else self.config.ceiling_release
        self._ceiling += (value - self._ceiling) * rate

        falling = value < self._baseline
        rate = self.config.baseline_fall if falling else self.config.baseline_rise
        self._baseline += (value - self._baseline) * rate

        span = max(self._ceiling - self._baseline, self.config.min_span)
        return _unit((value - self._baseline) / span)

    def _seed(self, value: float) -> None:
        """Watch a short warm-up, then anchor to it. Reads as rest until it has.

        Only the back half of the warm-up is used, so the filters' settling transient at
        the front of a session does not become the resting baseline.
        """
        self._warmup.append(value)
        if len(self._warmup) < self.config.warmup_samples:
            return

        settled = np.array(self._warmup[len(self._warmup) // 2 :])
        self._baseline = float(np.percentile(settled, 10))
        self._ceiling = float(np.percentile(settled, 90))
        self._warmup = []

    def reset(self) -> None:
        self._ceiling = None
        self._baseline = None
        self._warmup = []
