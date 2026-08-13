"""Filter stages built from the sample rate that was actually measured.

Two departures from the original demo:

* Second-order sections rather than transfer-function coefficients, which is the correct
  default for a cascaded IIR.
* Band edges are clamped to the real Nyquist, and every coefficient is derived from the
  rate passed in. The old pipeline hardcoded 1 kHz, so a source delivering 500 Hz put the
  notch at 100 Hz and pushed the bandpass past Nyquist (R1).
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, iirnotch, sosfilt, sosfilt_zi, tf2sos

from ..config import FilterConfig


class SosStage:
    """One stateful second-order-section stage, stepped a sample at a time.

    State is initialised from the first sample's steady state rather than a fixed
    1.65 V assumption, so stages fed a rectified signal no longer open with a
    transient (R9).
    """

    def __init__(self, sos: np.ndarray):
        self.sos = np.asarray(sos, dtype=np.float64)
        self._zi_template = sosfilt_zi(self.sos)
        self._zi: np.ndarray | None = None

    def step(self, sample: float) -> float:
        sample = float(sample)
        if self._zi is None:
            self._zi = self._zi_template * sample

        out, self._zi = sosfilt(self.sos, [sample], zi=self._zi)
        return float(out[0])

    def step_block(self, block: np.ndarray) -> np.ndarray:
        """Filter a whole batch in one call. Identical result, far less overhead."""
        block = np.asarray(block, dtype=np.float64)
        if block.size == 0:
            return block

        if self._zi is None:
            self._zi = self._zi_template * float(block[0])

        out, self._zi = sosfilt(self.sos, block, zi=self._zi)
        return out

    def reset(self) -> None:
        self._zi = None


def _nyquist_safe(freq_hz: float, sample_rate_hz: float) -> float:
    """Clamp a cutoff to something a digital filter can actually represent."""
    nyquist = sample_rate_hz / 2.0
    return float(np.clip(freq_hz, 1e-3, nyquist * 0.95))


def make_notch(config: FilterConfig, sample_rate_hz: float) -> SosStage:
    freq = _nyquist_safe(config.notch_freq_hz, sample_rate_hz)
    b, a = iirnotch(freq, config.notch_q, fs=sample_rate_hz)
    return SosStage(tf2sos(b, a))


def make_bandpass(config: FilterConfig, sample_rate_hz: float) -> SosStage:
    low = _nyquist_safe(config.bandpass_low_hz, sample_rate_hz)
    high = _nyquist_safe(config.bandpass_high_hz, sample_rate_hz)
    if low >= high:
        low = high / 2.0
    sos = butter(
        config.bandpass_order, [low, high], btype="bandpass", fs=sample_rate_hz, output="sos"
    )
    return SosStage(sos)


def make_lowpass(config: FilterConfig, sample_rate_hz: float) -> SosStage:
    cutoff = _nyquist_safe(config.lowpass_cutoff_hz, sample_rate_hz)
    sos = butter(config.lowpass_order, cutoff, btype="lowpass", fs=sample_rate_hz, output="sos")
    return SosStage(sos)


class StreamingCascade:
    """Notch then bandpass — everything applied before rectification."""

    def __init__(self, config: FilterConfig, sample_rate_hz: float):
        self.config = config
        self.sample_rate_hz = float(sample_rate_hz)
        self.notch = make_notch(config, sample_rate_hz)
        self.bandpass = make_bandpass(config, sample_rate_hz)

    def step(self, sample: float) -> float:
        return self.bandpass.step(self.notch.step(sample))

    def reset(self) -> None:
        self.notch.reset()
        self.bandpass.reset()
