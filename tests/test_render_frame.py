"""What crosses to the browser, and that it survives the trip."""

import json
import math

from emgdemo.config import DemoSettings
from emgdemo.engine import Engine
from emgdemo.sources.base import SourceStatus

STAGES = ("raw", "notch", "bandpass", "rectified", "lowpass", "envelope")


class Ramp:
    """Emits a rising ramp so downsampling errors show up as wrong values."""

    # 20 samples per 20 ms tick is 1 kHz, matching the default design rate so these
    # tests are not silently exercising the retune path.
    def __init__(self, per_read=20):
        self.per_read = per_read
        self.running = False
        self.n = 0

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def read(self, max_samples):
        if not self.running:
            return []
        count = min(self.per_read, max_samples)
        out = []
        for _ in range(count):
            self.n += 1
            value = 1.65 + 0.6 * math.sin(2 * math.pi * 120 * self.n / 1000.0)
            out.append((value, 1.65))
        return out

    def status(self):
        return SourceStatus(state="streaming" if self.running else "stopped", detail="ramping")


class FakeClock:
    def __init__(self, step=0.02):
        self.now = 0.0
        self.step = step

    def __call__(self):
        now = self.now
        self.now += self.step
        return now


def _engine(ticks=120):
    engine = Engine(DemoSettings(), source=Ramp(), source_name="ramp", clock=FakeClock())
    engine.start()
    for _ in range(ticks):
        engine.tick()
    return engine


def test_frame_carries_every_stage_trace():
    frame = _engine().render_frame(max_points=200)
    assert set(frame["traces"]) == set(STAGES)


def test_traces_are_downsampled_to_the_requested_budget():
    frame = _engine().render_frame(max_points=150)
    for stage, values in frame["traces"].items():
        assert len(values) <= 150, stage


def test_downsampling_keeps_the_most_recent_sample():
    engine = _engine()
    frame = engine.render_frame(max_points=100)
    assert frame["traces"]["envelope"][-1] == list(engine.trace("envelope"))[-1]


def test_a_short_session_is_not_padded():
    engine = Engine(DemoSettings(), source=Ramp(per_read=20), source_name="r", clock=FakeClock())
    engine.start()
    engine.tick()
    frame = engine.render_frame(max_points=500)
    assert len(frame["traces"]["raw"]) == 20


def test_frame_reports_what_the_operator_must_see():
    frame = _engine().render_frame(max_points=100)

    assert frame["source"]["name"] == "ramp"
    assert frame["source"]["state"] == "streaming"
    assert frame["source"]["failover"] is False
    assert frame["rate"]["design"] == 1000.0
    assert 0.0 <= frame["levels"]["a"] <= 1.0
    assert frame["gripper"]["label"] in {"OPEN", "LIGHT", "POWER"}
    assert len(frame["gripper"]["fingers"]) == 5
    assert isinstance(frame["events"], list)
    assert frame["flags"]["paused"] is False


def test_noise_reduction_is_reported_per_stage():
    frame = _engine().render_frame(max_points=100)
    assert set(frame["improvements"]) == {"notch", "bandpass", "rectified", "lowpass", "envelope"}
    assert all(-300.0 <= v <= 100.0 for v in frame["improvements"].values())


def test_the_frame_is_json():
    payload = json.dumps(_engine().render_frame(max_points=100))
    assert json.loads(payload)["traces"]["raw"]


def test_frame_values_are_plain_floats_not_numpy_scalars():
    frame = _engine().render_frame(max_points=50)
    assert all(type(v) is float for v in frame["traces"]["envelope"])
    assert type(frame["gripper"]["force"]) is float
