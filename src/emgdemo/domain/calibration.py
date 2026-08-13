"""Per-participant calibration: capture a rest-to-effort sweep, derive baseline and span.

The profile is serializable so a good calibration survives a restart, which matters when
the thing falls over mid-session at a stand.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from ..config import CalibrationConfig


class CalibrationError(Exception):
    """Raised when a capture is too short to produce a trustworthy profile."""


@dataclass(frozen=True)
class CalibrationProfile:
    baseline: float
    span: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, float]) -> CalibrationProfile:
        return cls(baseline=float(payload["baseline"]), span=float(payload["span"]))


def calibrate(samples, config: CalibrationConfig | None = None) -> CalibrationProfile:
    config = config or CalibrationConfig()
    values = np.asarray(samples, dtype=np.float64)

    if values.size < config.min_samples:
        raise CalibrationError(
            f"Calibration needs at least {config.min_samples} samples, got {values.size}"
        )

    baseline = float(np.percentile(values, config.baseline_percentile))
    ceiling = float(np.percentile(values, config.ceiling_percentile))

    return CalibrationProfile(baseline=baseline, span=max(ceiling - baseline, config.min_span))
