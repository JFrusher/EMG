import numpy as np

from emgdemo.config import FilterConfig
from emgdemo.dsp.pipeline import EMGPipeline


def _burst(fs, seconds=2.0):
    t = np.arange(int(seconds * fs)) / fs
    carrier = np.sin(2 * np.pi * 120 * t)
    activation = np.where((t > 0.8) & (t < 1.4), 1.0, 0.05)
    return 1.65 + 0.6 * carrier * activation


def test_step_reports_every_stage():
    pipeline = EMGPipeline(FilterConfig(), sample_rate_hz=1000)
    stages = pipeline.step(1.65)
    assert set(stages.as_dict()) == {"raw", "notch", "bandpass", "rectified", "lowpass", "envelope"}


def test_rectified_and_envelope_are_never_negative():
    fs = 1000
    pipeline = EMGPipeline(FilterConfig(), sample_rate_hz=fs)
    for sample in _burst(fs):
        stages = pipeline.step(float(sample))
        assert stages.rectified >= 0.0
        assert stages.envelope >= 0.0


def test_envelope_rises_during_a_burst_and_falls_after():
    fs = 1000
    pipeline = EMGPipeline(FilterConfig(), sample_rate_hz=fs)
    envelope = np.array([pipeline.step(float(x)).envelope for x in _burst(fs)])

    at_rest = float(np.mean(envelope[int(0.4 * fs) : int(0.7 * fs)]))
    during = float(np.mean(envelope[int(1.0 * fs) : int(1.3 * fs)]))
    after = float(np.mean(envelope[int(1.7 * fs) : int(2.0 * fs)]))

    assert during > at_rest * 3
    assert after < during
