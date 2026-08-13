import numpy as np
import pytest

from emgdemo.dsp.envelope import RunningMean


def test_mean_of_constant_input_equals_that_constant():
    mean = RunningMean(window_samples=10)
    for _ in range(10):
        out = mean.step(0.4)
    assert out == pytest.approx(0.4)


def test_matches_numpy_trailing_window_mean():
    rng = np.random.default_rng(0)
    signal = rng.random(500)
    window = 50

    mean = RunningMean(window_samples=window)
    for i, sample in enumerate(signal):
        out = mean.step(float(sample))
        expected = float(np.mean(signal[max(0, i - window + 1) : i + 1]))
        assert out == pytest.approx(expected, abs=1e-9)


def test_window_smaller_than_one_is_clamped_to_one():
    mean = RunningMean(window_samples=0)
    assert mean.step(0.7) == pytest.approx(0.7)
    assert mean.step(0.2) == pytest.approx(0.2)
