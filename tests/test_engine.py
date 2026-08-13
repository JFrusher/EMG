import math

from emgdemo.config import DemoSettings
from emgdemo.engine import Engine
from emgdemo.sources.base import SourceStatus


class ScriptedSource:
    """Emits a fixed number of samples per read, from a caller-supplied generator."""

    def __init__(self, generator, per_read):
        self.generator = generator
        self.per_read = per_read
        self.running = False
        self.starts = 0
        self.t = 0.0

    def start(self):
        self.running = True
        self.starts += 1

    def stop(self):
        self.running = False

    def read(self, max_samples):
        if not self.running:
            return []
        count = min(self.per_read, max_samples)
        out = []
        for _ in range(count):
            out.append(self.generator(self.t))
            self.t += 1.0 / 1000.0
        return out

    def status(self):
        return SourceStatus(state="streaming" if self.running else "stopped")


class SilentSource(ScriptedSource):
    def __init__(self):
        super().__init__(lambda t: (1.65, 1.65), per_read=0)


class DyingSource(ScriptedSource):
    """Streams normally, then goes quiet — a source losing its connection."""

    def __init__(self, alive_reads: int):
        super().__init__(_rest, per_read=20)
        self.alive_reads = alive_reads
        self.reads = 0

    def read(self, max_samples):
        self.reads += 1
        if self.reads > self.alive_reads:
            return []
        return super().read(max_samples)


def _rest(_t):
    return (1.65, 1.65)


def _burst(t):
    """Side A contracts for 600 ms every 2 s; side B rests throughout.

    An unmodulated carrier would be wrong here: a signal that never changes is exactly
    what a raised resting baseline looks like, and reading it as effort is the R8 bug.
    """
    carrier = math.sin(2 * math.pi * 120 * t)
    activation = 1.0 if (t % 2.0) < 0.6 else 0.05
    return (1.65 + 0.7 * carrier * activation, 1.65)


class FakeClock:
    def __init__(self, step):
        self.now = 0.0
        self.step = step

    def __call__(self):
        now = self.now
        self.now += self.step
        return now


def _engine(source, settings=None, clock=None):
    return Engine(
        settings or DemoSettings(),
        source=source,
        source_name="test",
        clock=clock or FakeClock(step=0.02),
    )


def test_tick_returns_a_complete_snapshot():
    engine = _engine(ScriptedSource(_rest, per_read=20))
    engine.start()
    state = engine.tick()

    assert state.source_name == "test"
    assert state.stages is not None
    assert 0.0 <= state.side_a_level <= 1.0
    assert 0.0 <= state.side_b_level <= 1.0
    assert state.gripper.force_n >= 0.0


def test_sample_counter_accumulates_across_ticks():
    engine = _engine(ScriptedSource(_rest, per_read=20))
    engine.start()
    for _ in range(5):
        state = engine.tick()
    assert state.total_samples == 100


def test_resting_input_does_not_close_the_gripper():
    engine = _engine(ScriptedSource(_rest, per_read=20))
    engine.start()
    for _ in range(200):
        state = engine.tick()
    assert state.gripper.label == "OPEN"


def test_a_burst_on_side_a_drives_the_gripper_closed():
    engine = _engine(ScriptedSource(_burst, per_read=20))
    engine.start()

    peak_a = peak_b = peak_force = 0.0
    for _ in range(400):
        state = engine.tick()
        peak_a = max(peak_a, state.side_a_level)
        peak_b = max(peak_b, state.side_b_level)
        peak_force = max(peak_force, state.gripper.force_n)

    assert peak_a > 0.5
    assert peak_a > peak_b
    assert peak_force > 0.0


def test_traces_are_kept_for_every_stage():
    engine = _engine(ScriptedSource(_rest, per_read=20))
    engine.start()
    engine.tick()
    for key in ("raw", "notch", "bandpass", "rectified", "lowpass", "envelope"):
        assert len(engine.trace(key)) > 0


def test_measured_rate_is_reported():
    engine = _engine(ScriptedSource(_rest, per_read=20), clock=FakeClock(step=0.02))
    engine.start()
    for _ in range(200):
        state = engine.tick()
    # 20 samples every 20 ms is 1000 Hz.
    assert 900 < state.measured_rate_hz < 1100


def test_filters_are_rebuilt_when_the_source_runs_at_a_different_rate():
    # R1: 10 samples every 20 ms is 500 Hz, not the 1000 Hz the settings assume.
    engine = _engine(ScriptedSource(_rest, per_read=10), clock=FakeClock(step=0.02))
    engine.start()
    assert engine.design_rate_hz == 1000.0

    for _ in range(400):
        state = engine.tick()

    assert 400 < state.design_rate_hz < 600
    assert any("retuned" in entry for entry in state.events)


def test_an_implausible_measured_rate_is_refused():
    # 250 samples every 5 ms is 50 kHz. That is a broken source, not a sample rate to
    # design a 50 Hz notch against.
    engine = _engine(ScriptedSource(_rest, per_read=250), clock=FakeClock(step=0.005))
    engine.start()

    for _ in range(300):
        state = engine.tick()

    assert state.design_rate_hz == 1000.0
    assert any("implausible" in entry for entry in state.events)


def test_a_silent_source_is_restarted_then_failed_over():
    source = SilentSource()
    engine = _engine(source, clock=FakeClock(step=2.0))
    engine.start()

    for _ in range(20):
        state = engine.tick()

    assert source.starts > 1
    assert state.failover_active is True
    assert state.source_name != "test"


def test_a_dying_source_does_not_drag_the_filters_down_with_it():
    # A stream trailing off toward silence has a falling measured rate. Designing
    # filters against it puts the notch and the passband somewhere meaningless, and the
    # synthetic stand-in then inherits that bogus rate.
    engine = _engine(DyingSource(alive_reads=100), clock=FakeClock(step=0.02))
    engine.start()

    for _ in range(1_100):
        state = engine.tick()

    assert state.failover_active is True
    assert state.design_rate_hz == 1000.0


def test_failover_keeps_the_demo_producing_samples():
    engine = _engine(SilentSource(), clock=FakeClock(step=2.0))
    engine.start()
    for _ in range(20):
        state = engine.tick()

    before = state.total_samples
    for _ in range(5):
        state = engine.tick()
    assert state.total_samples > before


def test_pausing_stops_consuming_samples():
    engine = _engine(ScriptedSource(_rest, per_read=20))
    engine.start()
    engine.tick()
    engine.paused = True

    before = engine.tick().total_samples
    after = engine.tick().total_samples
    assert after == before


def test_calibration_gives_up_when_the_source_goes_quiet():
    # The deadline has to be honoured even when no samples arrive, or a source that
    # dies mid-capture leaves the demo stuck reading CALIBRATING.
    engine = _engine(SilentSource(), clock=FakeClock(step=0.1))
    engine.start()
    engine.tick()
    engine.begin_calibration(duration_s=0.3)

    for _ in range(20):
        state = engine.tick()

    assert state.calibrating is False
    assert state.calibrated is False
    assert any("alibration" in entry for entry in state.events)


def test_calibration_replaces_the_adaptive_reference():
    engine = _engine(ScriptedSource(_burst, per_read=20))
    engine.start()
    for _ in range(50):
        engine.tick()

    engine.begin_calibration(duration_s=0.5)
    for _ in range(200):
        state = engine.tick()

    assert state.calibrated is True
