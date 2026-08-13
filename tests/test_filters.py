"""Filter cascade tests, including the R1 regression: coefficients follow the measured rate."""

import numpy as np

from emgdemo.config import FilterConfig
from emgdemo.dsp.filters import StreamingCascade


def _tone(freq_hz, fs, seconds=2.0, amplitude=1.0):
    t = np.arange(int(seconds * fs)) / fs
    return amplitude * np.sin(2 * np.pi * freq_hz * t)


def _run(cascade, signal):
    return np.array([cascade.step(float(x)) for x in signal])


def _settled_rms(signal, fs):
    """RMS of the second half, so filter start-up transients are excluded."""
    return float(np.sqrt(np.mean(signal[int(0.5 * len(signal)) :] ** 2)))


def test_powerline_tone_is_attenuated():
    fs = 1000
    cascade = StreamingCascade(FilterConfig(), sample_rate_hz=fs)
    out = _run(cascade, _tone(50, fs))
    assert _settled_rms(out, fs) < 0.2


def test_in_band_tone_survives():
    fs = 1000
    cascade = StreamingCascade(FilterConfig(), sample_rate_hz=fs)
    out = _run(cascade, _tone(120, fs))
    assert _settled_rms(out, fs) > 0.5


def test_dc_offset_is_rejected():
    fs = 1000
    cascade = StreamingCascade(FilterConfig(), sample_rate_hz=fs)
    out = _run(cascade, np.full(2 * fs, 1.65))
    assert _settled_rms(out, fs) < 0.05


def test_notch_tracks_the_measured_rate_not_a_hardcoded_1000():
    # R1: built at 500 Hz, the cascade must still reject 50 Hz — not 100 Hz.
    fs = 500
    cascade = StreamingCascade(FilterConfig(), sample_rate_hz=fs)
    rejected = _settled_rms(_run(cascade, _tone(50, fs)), fs)

    cascade = StreamingCascade(FilterConfig(), sample_rate_hz=fs)
    passed = _settled_rms(_run(cascade, _tone(100, fs)), fs)

    assert rejected < passed / 3


def test_cascade_state_is_not_shared_between_instances():
    fs = 1000
    signal = _tone(120, fs, seconds=0.5)

    first = _run(StreamingCascade(FilterConfig(), sample_rate_hz=fs), signal)
    second = _run(StreamingCascade(FilterConfig(), sample_rate_hz=fs), signal)

    assert np.allclose(first, second)
