"""Block and per-sample paths must agree exactly.

The engine receives samples in batches, so it filters them in one scipy call per stage
rather than one per sample. That is only safe if the two paths are the same computation.
"""

import numpy as np
import pytest

from emgdemo.config import FilterConfig
from emgdemo.dsp.envelope import RunningMean
from emgdemo.dsp.filters import make_bandpass
from emgdemo.dsp.pipeline import EMGPipeline


def _signal(n=1500, seed=3):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / 1000.0
    return 1.65 + 0.5 * np.sin(2 * np.pi * 120 * t) + rng.normal(0, 0.05, n)


def test_sos_stage_block_matches_sample_by_sample():
    signal = _signal()
    per_sample = np.array([make_bandpass(FilterConfig(), 1000).step(x) for x in signal[:1]])
    assert per_sample.size == 1  # sanity: the per-sample API still exists

    stage_a = make_bandpass(FilterConfig(), 1000)
    stage_b = make_bandpass(FilterConfig(), 1000)

    stepped = np.array([stage_a.step(float(x)) for x in signal])
    blocked = stage_b.step_block(signal)

    assert np.allclose(stepped, blocked, atol=1e-9)


def test_sos_stage_block_state_carries_across_blocks():
    signal = _signal()
    whole = make_bandpass(FilterConfig(), 1000).step_block(signal)

    split = make_bandpass(FilterConfig(), 1000)
    chunked = np.concatenate([split.step_block(signal[:400]), split.step_block(signal[400:])])

    assert np.allclose(whole, chunked, atol=1e-9)


def test_running_mean_block_matches_sample_by_sample():
    signal = _signal(n=800)
    stepped = np.array([RunningMean(200).step(float(x)) for x in signal[:1]])
    assert stepped.size == 1

    mean_a = RunningMean(200)
    mean_b = RunningMean(200)

    stepped = np.array([mean_a.step(float(x)) for x in signal])
    blocked = mean_b.step_block(signal)

    assert np.allclose(stepped, blocked, atol=1e-9)


def test_running_mean_block_is_correct_before_the_window_fills():
    signal = np.arange(10, dtype=np.float64)
    blocked = RunningMean(200).step_block(signal)
    expected = np.cumsum(signal) / np.arange(1, 11)
    assert np.allclose(blocked, expected, atol=1e-9)


def test_running_mean_block_state_carries_across_blocks():
    signal = _signal(n=900)
    whole = RunningMean(200).step_block(signal)

    split = RunningMean(200)
    chunked = np.concatenate([split.step_block(signal[:250]), split.step_block(signal[250:])])

    assert np.allclose(whole, chunked, atol=1e-9)


def test_empty_block_is_handled():
    empty = np.array([], dtype=np.float64)
    assert make_bandpass(FilterConfig(), 1000).step_block(empty).size == 0
    assert RunningMean(200).step_block(empty).size == 0


def test_pipeline_block_matches_sample_by_sample():
    signal = _signal(n=1200)

    per_sample = EMGPipeline(FilterConfig(), 1000)
    stepped = {key: [] for key in ("raw", "notch", "bandpass", "rectified", "lowpass", "envelope")}
    for x in signal:
        for key, value in per_sample.step(float(x)).as_dict().items():
            stepped[key].append(value)

    blocked = EMGPipeline(FilterConfig(), 1000).step_block(signal)

    for key, values in stepped.items():
        assert np.allclose(values, blocked[key], atol=1e-9), key


def test_pipeline_block_processing_is_faster_than_realtime():
    """A second of 1 kHz signal must cost well under a second of CPU."""
    import time

    signal = _signal(n=10_000)
    pipelines = [EMGPipeline(FilterConfig(), 1000) for _ in range(3)]

    start = time.perf_counter()
    for pipeline in pipelines:
        for offset in range(0, signal.size, 250):
            pipeline.step_block(signal[offset : offset + 250])
    elapsed = time.perf_counter() - start

    # Ten seconds of signal through three pipelines, in under one second of CPU.
    assert elapsed < 1.0, f"took {elapsed:.2f}s"


def test_pipeline_block_returns_every_stage():
    blocked = EMGPipeline(FilterConfig(), 1000).step_block(_signal(n=50))
    assert set(blocked) == {"raw", "notch", "bandpass", "rectified", "lowpass", "envelope"}
    assert all(len(values) == 50 for values in blocked.values())


def test_rectified_and_envelope_blocks_are_never_negative():
    blocked = EMGPipeline(FilterConfig(), 1000).step_block(_signal(n=2000))
    assert blocked["rectified"].min() >= 0.0
    assert blocked["envelope"].min() >= 0.0


@pytest.mark.parametrize("block_size", [1, 7, 250, 1000])
def test_any_block_size_gives_the_same_answer(block_size):
    signal = _signal(n=1000)
    whole = EMGPipeline(FilterConfig(), 1000).step_block(signal)

    split = EMGPipeline(FilterConfig(), 1000)
    offsets = range(0, signal.size, block_size)
    parts = [split.step_block(signal[i : i + block_size]) for i in offsets]
    joined = {key: np.concatenate([part[key] for part in parts]) for key in whole}

    for key in whole:
        assert np.allclose(whole[key], joined[key], atol=1e-9), key
