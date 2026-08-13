"""Controls arriving from the browser."""

import pytest

from emgdemo.commands import UnknownCommand, apply_command
from emgdemo.config import DemoSettings
from emgdemo.engine import Engine
from emgdemo.sources.base import SourceStatus


class Quiet:
    def __init__(self):
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def read(self, max_samples):
        return [(1.65, 1.65)] * min(20, max_samples) if self.running else []

    def status(self):
        return SourceStatus(state="streaming" if self.running else "stopped")


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        now = self.now
        self.now += 0.02
        return now


def _engine():
    engine = Engine(DemoSettings(), source=Quiet(), source_name="quiet", clock=FakeClock())
    engine.start()
    engine.tick()
    return engine


def test_pause_and_resume_toggle_the_engine():
    engine = _engine()
    apply_command(engine, "pause")
    assert engine.paused is True
    apply_command(engine, "resume")
    assert engine.paused is False


def test_calibrate_starts_a_capture():
    engine = _engine()
    apply_command(engine, "calibrate")
    assert engine.calibrating is True


def test_calibrating_while_paused_resumes_first():
    # A paused engine processes no samples, so a capture started while paused never
    # collects anything and never reaches its deadline - the panel just reads
    # CALIBRATING until somebody notices.
    engine = _engine()
    apply_command(engine, "pause")
    apply_command(engine, "calibrate")

    assert engine.paused is False
    assert engine.calibrating is True


def test_reset_clears_the_counters_and_the_log():
    engine = _engine()
    engine.event_count = 7
    engine.cocontraction_count = 3

    apply_command(engine, "reset")

    assert engine.event_count == 0
    assert engine.cocontraction_count == 0
    assert engine.events


def test_reset_does_not_stop_the_source():
    engine = _engine()
    apply_command(engine, "reset")
    before = engine.total_samples
    engine.tick()
    assert engine.total_samples > before


def test_clear_calibration_returns_to_the_adaptive_reference():
    engine = _engine()
    engine.calibrated = True
    apply_command(engine, "clear-calibration")
    assert engine.calibrated is False


def test_an_unknown_command_is_refused_not_ignored():
    engine = _engine()
    with pytest.raises(UnknownCommand):
        apply_command(engine, "self-destruct")


def test_every_command_is_recorded_in_the_event_log():
    engine = _engine()
    apply_command(engine, "pause")
    assert any("Pause" in line or "pause" in line for line in engine.events)
