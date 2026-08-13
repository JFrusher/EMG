import numpy as np
import pytest

from emgdemo.config import CalibrationConfig
from emgdemo.domain.calibration import CalibrationError, calibrate


def test_baseline_and_span_come_from_the_captured_distribution():
    samples = np.linspace(0.0, 1.0, 1000)
    profile = calibrate(samples, CalibrationConfig())

    assert profile.baseline == pytest.approx(np.percentile(samples, 20), abs=1e-6)
    assert profile.span == pytest.approx(
        np.percentile(samples, 95) - np.percentile(samples, 20), abs=1e-6
    )


def test_too_few_samples_is_an_error_not_a_silent_bad_profile():
    with pytest.raises(CalibrationError):
        calibrate(np.linspace(0.0, 1.0, 5), CalibrationConfig(min_samples=20))


def test_a_flat_capture_still_yields_a_usable_span():
    profile = calibrate(np.full(500, 0.3), CalibrationConfig(min_span=0.03))
    assert profile.span >= 0.03


def test_profile_round_trips_through_a_dict():
    profile = calibrate(np.linspace(0.0, 1.0, 500), CalibrationConfig())
    assert type(profile).from_dict(profile.to_dict()) == profile
