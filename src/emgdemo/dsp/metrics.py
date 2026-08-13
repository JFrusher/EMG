"""The 'how much cleaner is this stage' figure shown beside each trace.

A jitter proxy — mean absolute sample-to-sample change — stands in for noise. It is not a
rigorous SNR, but it is honest about what it measures and it moves in the direction a
viewer expects when a filter engages, which is the whole point of showing it.
"""

from __future__ import annotations

import numpy as np

_EPSILON = 1e-6

#: Bounds on the reported figure. A stage cannot be more than 100% cleaner, and a stage
#: that amplifies noise is pinned so one bad frame cannot blow up the axis.
_MIN_IMPROVEMENT_PCT = -300.0
_MAX_IMPROVEMENT_PCT = 100.0


def noise_proxy(signal: np.ndarray) -> float:
    signal = np.asarray(signal, dtype=np.float64)
    if signal.size < 2:
        return _EPSILON
    return float(np.mean(np.abs(np.diff(signal)))) + _EPSILON


def improvement_pct(raw: np.ndarray, stage: np.ndarray) -> float:
    """Percentage by which ``stage`` is quieter than ``raw``. Positive means cleaner."""
    raw_noise = noise_proxy(raw)
    stage_noise = noise_proxy(stage)
    improvement = (1.0 - (stage_noise / raw_noise)) * 100.0
    return float(np.clip(improvement, _MIN_IMPROVEMENT_PCT, _MAX_IMPROVEMENT_PCT))
