from emgdemo.config import EventConfig
from emgdemo.domain.events import CoContractionDetector, EventDetector


def test_crossing_the_high_threshold_starts_an_event():
    detector = EventDetector(EventConfig())
    assert detector.step(0.05, t=0.0).started is False
    assert detector.step(0.40, t=0.1).started is True


def test_staying_above_the_threshold_does_not_retrigger():
    detector = EventDetector(EventConfig())
    detector.step(0.40, t=0.0)
    for i in range(1, 20):
        assert detector.step(0.40, t=i * 0.1).started is False


def test_dropping_below_the_low_threshold_rearms_the_detector():
    detector = EventDetector(EventConfig())
    detector.step(0.40, t=0.0)
    detector.step(0.10, t=1.0)
    assert detector.step(0.40, t=2.0).started is True


def test_refractory_period_suppresses_a_rapid_retrigger():
    config = EventConfig(min_interval_s=0.25)
    detector = EventDetector(config)
    detector.step(0.40, t=0.0)
    detector.step(0.10, t=0.05)
    assert detector.step(0.40, t=0.10).started is False


def test_active_flag_tracks_the_hysteresis_band():
    detector = EventDetector(EventConfig(threshold_high=0.28, threshold_low=0.20))
    assert detector.step(0.40, t=0.0).active is True
    # inside the band: neither retrigger nor release
    assert detector.step(0.24, t=1.0).active is True
    assert detector.step(0.15, t=2.0).active is False


def test_co_contraction_requires_both_sides_above_threshold():
    detector = CoContractionDetector(EventConfig())
    assert detector.step(0.40, 0.05, t=0.0).started is False
    assert detector.step(0.05, 0.40, t=1.0).started is False
    assert detector.step(0.40, 0.40, t=2.0).started is True


def test_co_contraction_does_not_retrigger_while_sustained():
    detector = CoContractionDetector(EventConfig())
    detector.step(0.40, 0.40, t=0.0)
    assert detector.step(0.40, 0.40, t=5.0).started is False
