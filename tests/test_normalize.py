"""Regression tests for R8 — the normalization reference must not read rest as effort."""

import numpy as np
import pytest

from emgdemo.dsp.normalize import AdaptiveReference, Calibrated


def _drive(norm, value, samples):
    out = 0.0
    for _ in range(samples):
        out = norm.step(value)
    return out


def test_resting_baseline_reads_near_zero_not_full_scale():
    # R8: the old p95 reference divided a quiet envelope by its own quiet p95,
    # so a raised baseline read as a full contraction.
    norm = AdaptiveReference()
    assert _drive(norm, 0.12, 4000) < 0.15


def test_strong_contraction_after_rest_reads_near_full():
    norm = AdaptiveReference()
    _drive(norm, 0.10, 4000)
    assert _drive(norm, 0.90, 400) > 0.8


def test_a_noisy_but_steady_signal_is_not_amplified_into_effort():
    # A reference that hugs the ripple turns a stationary envelope into full-scale
    # activation. Real recorded EMG sits around 0.24 V with roughly this much jitter.
    rng = np.random.default_rng(0)
    norm = AdaptiveReference()
    levels = np.array([norm.step(0.24 + float(rng.normal(0, 0.02))) for _ in range(20_000)])

    settled = levels[2_000:]
    assert settled.mean() < 0.25
    assert np.mean(settled > 0.9) < 0.02


def test_the_pipeline_startup_ramp_does_not_leave_everything_reading_as_effort():
    # The first envelope samples of a session are the filter's own settling, climbing
    # from zero. Seeding the reference on sample one therefore anchors the baseline at
    # zero, and it then takes fifteen seconds to reach the real resting level - during
    # which a motionless participant drives the gripper fully closed.
    rng = np.random.default_rng(1)
    norm = AdaptiveReference()

    startup_ramp = np.linspace(0.0, 0.24, 200)
    steady_rest = 0.24 + rng.normal(0, 0.02, 4_000)
    levels = np.array([norm.step(float(v)) for v in np.concatenate([startup_ramp, steady_rest])])

    assert np.mean(levels[2_000:] > 0.5) < 0.05


def test_a_real_contraction_still_reads_full_scale_after_that_steadiness():
    rng = np.random.default_rng(0)
    norm = AdaptiveReference()
    for _ in range(20_000):
        norm.step(0.24 + float(rng.normal(0, 0.02)))

    peak = max(norm.step(0.95) for _ in range(1_000))
    assert peak > 0.9


def test_the_reference_does_not_chase_a_single_spike():
    norm = AdaptiveReference()
    for _ in range(5_000):
        norm.step(0.20)

    norm.step(3.0)
    after_spike = norm.step(0.20)
    assert after_spike < 0.2


def test_output_is_bounded_to_unit_range():
    norm = AdaptiveReference()
    for value in (-5.0, 0.0, 0.05, 3.3, 1e6):
        assert 0.0 <= norm.step(value) <= 1.0


def test_constant_input_never_divides_by_zero_span():
    norm = AdaptiveReference()
    assert _drive(norm, 0.5, 2000) == pytest.approx(_drive(norm, 0.5, 10), abs=0.5)


def test_calibrated_maps_baseline_to_zero_and_ceiling_to_one():
    calibrated = Calibrated(baseline=0.2, span=0.6)
    assert calibrated.step(0.2) == pytest.approx(0.0)
    assert calibrated.step(0.8) == pytest.approx(1.0)
    assert calibrated.step(0.5) == pytest.approx(0.5)


def test_calibrated_clamps_outside_the_calibrated_range():
    calibrated = Calibrated(baseline=0.2, span=0.6)
    assert calibrated.step(0.0) == 0.0
    assert calibrated.step(9.9) == 1.0
