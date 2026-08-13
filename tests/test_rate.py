import pytest

from emgdemo.rate import RateMeter


def test_reports_nothing_before_a_full_window():
    meter = RateMeter(window_s=1.0)
    meter.observe(10, now=0.0)
    assert meter.rate_hz is None


def test_measures_a_steady_stream():
    meter = RateMeter(window_s=1.0)
    now = 0.0
    meter.observe(0, now=now)
    for _ in range(20):
        now += 0.05
        meter.observe(25, now=now)
    assert meter.rate_hz == pytest.approx(500.0, rel=0.05)


def test_tracks_a_rate_change():
    meter = RateMeter(window_s=1.0)
    now = 0.0
    meter.observe(0, now=now)
    for _ in range(20):
        now += 0.05
        meter.observe(50, now=now)
    assert meter.rate_hz == pytest.approx(1000.0, rel=0.05)

    for _ in range(40):
        now += 0.05
        meter.observe(10, now=now)
    assert meter.rate_hz == pytest.approx(200.0, rel=0.05)


def test_a_stalled_stream_reads_as_zero_not_stale():
    meter = RateMeter(window_s=1.0)
    now = 0.0
    meter.observe(0, now=now)
    for _ in range(20):
        now += 0.05
        meter.observe(50, now=now)

    for _ in range(40):
        now += 0.05
        meter.observe(0, now=now)
    assert meter.rate_hz == pytest.approx(0.0, abs=1.0)
