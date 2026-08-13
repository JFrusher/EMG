"""Does it still behave after hours of running? Deselected by default.

    pytest -m soak                       # the default two minutes
    EMG_SOAK_SECONDS=7200 pytest -m soak  # the full pre-expo two hours

Three things go wrong in long unattended runs, and none of them show up in a short one:
the consumer falls behind and never catches up, buffers grow without bound, and the
demo's own clock drifts away from the wall.
"""

from __future__ import annotations

import gc
import os
import time

import pytest

from emgdemo.config import DemoSettings
from emgdemo.engine import STAGE_KEYS, Engine
from emgdemo.sources.synthetic import SyntheticSource

pytestmark = pytest.mark.soak

SOAK_SECONDS = float(os.environ.get("EMG_SOAK_SECONDS", "120"))


@pytest.fixture(scope="module")
def soaked():
    """Run the engine hard for a while, sampling health as it goes."""
    settings = DemoSettings()
    engine = Engine(
        settings,
        source=SyntheticSource(settings.sample_rate_hz, seed=11),
        source_name="soak",
    )
    engine.start()

    gc.collect()
    started = time.perf_counter()
    samples = []

    while (time.perf_counter() - started) < SOAK_SECONDS:
        engine.tick()
        elapsed = time.perf_counter() - started
        if len(samples) < 2 or elapsed - samples[-1]["wall"] >= 5.0:
            frame = engine.render_frame(max_points=400)
            samples.append(
                {
                    "wall": elapsed,
                    "engine_t": frame["t"],
                    "processed": frame["counts"]["samples"],
                    "objects": len(gc.get_objects()),
                    "trace_len": len(engine.trace("envelope")),
                    "log_len": len(frame["events"]),
                    "rate": frame["rate"]["measured"],
                }
            )
        time.sleep(1.0 / 200.0)

    engine.stop()
    return engine, samples


def test_the_engine_keeps_up_with_the_stream(soaked):
    _, samples = soaked
    last = samples[-1]
    expected = last["wall"] * 1000.0
    shortfall = 1.0 - (last["processed"] / expected)
    assert shortfall < 0.02, f"dropped {shortfall:.1%} of the stream over {last['wall']:.0f}s"


def test_the_demo_clock_does_not_drift_from_the_wall(soaked):
    _, samples = soaked
    for sample in samples[2:]:
        drift = abs(sample["engine_t"] - sample["wall"])
        assert drift < 1.0, f"clock drifted {drift:.2f}s by {sample['wall']:.0f}s"


def test_trace_buffers_stay_bounded(soaked):
    engine, samples = soaked
    cap = int(engine.settings.trace_seconds * engine.design_rate_hz)
    for key in STAGE_KEYS:
        assert len(engine.trace(key)) <= cap, key
    assert samples[-1]["trace_len"] == samples[len(samples) // 2]["trace_len"]


def test_the_event_log_stays_bounded(soaked):
    engine, samples = soaked
    assert all(s["log_len"] <= engine.settings.max_events for s in samples)


def test_live_object_count_is_flat_across_the_run(soaked):
    _, samples = soaked
    settled = samples[len(samples) // 2 :]
    first, last = settled[0]["objects"], settled[-1]["objects"]
    growth = (last - first) / max(first, 1)
    assert growth < 0.05, f"live objects grew {growth:.1%} over the second half"


def test_the_measured_rate_holds_steady(soaked):
    _, samples = soaked
    for sample in samples[2:]:
        assert 900.0 < sample["rate"] < 1100.0, f"rate {sample['rate']:.0f} Hz"
