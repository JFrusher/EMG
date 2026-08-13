import numpy as np

from emgdemo.dsp.metrics import improvement_pct, noise_proxy


def test_jittery_signal_scores_higher_than_smooth_signal():
    rng = np.random.default_rng(1)
    smooth = np.linspace(0.0, 1.0, 500)
    jittery = smooth + rng.normal(0, 0.2, 500)
    assert noise_proxy(jittery) > noise_proxy(smooth)


def test_short_signals_do_not_divide_by_zero():
    assert noise_proxy(np.array([])) > 0
    assert noise_proxy(np.array([0.5])) > 0


def test_identical_signals_show_no_improvement():
    signal = np.linspace(0.0, 1.0, 100)
    assert improvement_pct(signal, signal) == 0.0


def test_smoothing_reports_positive_improvement():
    rng = np.random.default_rng(2)
    raw = rng.normal(0, 1.0, 1000)
    smoothed = np.convolve(raw, np.ones(20) / 20, mode="same")
    assert improvement_pct(raw, smoothed) > 50.0
