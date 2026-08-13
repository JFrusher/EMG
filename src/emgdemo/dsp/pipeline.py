"""Raw sample in, six named stage outputs out. No I/O, no clock, no drawing."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from ..config import FilterConfig
from .envelope import RunningMean
from .filters import StreamingCascade, make_lowpass


@dataclass(frozen=True)
class StageOutputs:
    raw: float
    notch: float
    bandpass: float
    rectified: float
    lowpass: float
    envelope: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


class EMGPipeline:
    """Notch, bandpass, rectify, low-pass, envelope — one sample at a time."""

    def __init__(self, config: FilterConfig, sample_rate_hz: float):
        self.config = config
        self.sample_rate_hz = float(sample_rate_hz)

        self.cascade = StreamingCascade(config, sample_rate_hz)
        self.lowpass = make_lowpass(config, sample_rate_hz)

        window_samples = int((config.envelope_window_ms / 1000.0) * sample_rate_hz)
        self.envelope = RunningMean(window_samples)

    def step(self, raw: float) -> StageOutputs:
        raw = float(raw)
        notch = self.cascade.notch.step(raw)
        bandpass = self.cascade.bandpass.step(notch)
        rectified = abs(bandpass)
        lowpass = max(0.0, self.lowpass.step(rectified))
        envelope = max(0.0, self.envelope.step(lowpass))

        return StageOutputs(
            raw=raw,
            notch=notch,
            bandpass=bandpass,
            rectified=rectified,
            lowpass=lowpass,
            envelope=envelope,
        )

    def step_block(self, raw: np.ndarray) -> dict[str, np.ndarray]:
        """Process a whole batch. One scipy call per stage instead of one per sample."""
        raw = np.asarray(raw, dtype=np.float64)
        notch = self.cascade.notch.step_block(raw)
        bandpass = self.cascade.bandpass.step_block(notch)
        rectified = np.abs(bandpass)
        lowpass = np.maximum(self.lowpass.step_block(rectified), 0.0)
        envelope = np.maximum(self.envelope.step_block(lowpass), 0.0)

        return {
            "raw": raw,
            "notch": notch,
            "bandpass": bandpass,
            "rectified": rectified,
            "lowpass": lowpass,
            "envelope": envelope,
        }

    def reset(self) -> None:
        self.cascade.reset()
        self.lowpass.reset()
        self.envelope.reset()
