import numpy as np
import pytest

from emgdemo.sources.replay import DatasetReplaySource, NoDatasetFiles


class FakeClock:
    """Hand-advanced clock, so replay pacing is deterministic instead of wall-timed."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _write_csv(folder, name, rows, columns=("HandOpen", "HandClose")):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    header = "," + ",".join(columns)
    lines = [header]
    for i, row in enumerate(rows):
        lines.append(str(i) + "," + ",".join(str(v) for v in row))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _source(folder, clock, **kwargs):
    kwargs.setdefault("side_a_channel", "HandClose")
    kwargs.setdefault("side_b_channel", "HandOpen")
    return DatasetReplaySource(folder=folder, sample_rate_hz=1000, clock=clock, **kwargs)


def test_empty_folder_is_an_error_not_an_empty_stream(tmp_path):
    (tmp_path / "signals").mkdir()
    with pytest.raises(NoDatasetFiles):
        _source(tmp_path / "signals", FakeClock())


def test_named_channels_map_to_the_two_sides(tmp_path):
    folder = tmp_path / "signals"
    _write_csv(folder, "v1.csv", [(1000, 2000)] * 100)

    clock = FakeClock()
    source = _source(folder, clock)
    source.start()
    clock.advance(0.05)

    side_a, side_b = source.read(50)[0]
    # HandClose is column 2 and drives side A; HandOpen is column 1 and drives side B.
    assert side_a == pytest.approx(2000 / 4095 * 3.3, abs=1e-6)
    assert side_b == pytest.approx(1000 / 4095 * 3.3, abs=1e-6)


def test_values_already_in_volts_are_left_alone(tmp_path):
    folder = tmp_path / "signals"
    _write_csv(folder, "v1.csv", [(1.2, 0.8)] * 100)

    clock = FakeClock()
    source = _source(folder, clock)
    source.start()
    clock.advance(0.05)

    side_a, side_b = source.read(50)[0]
    assert side_a == pytest.approx(0.8, abs=1e-6)
    assert side_b == pytest.approx(1.2, abs=1e-6)


def test_missing_values_do_not_reach_the_pipeline(tmp_path):
    folder = tmp_path / "signals"
    path = _write_csv(folder, "v1.csv", [(1000, 2000)] * 10)
    path.write_text(path.read_text(encoding="utf-8").replace("1000", "", 1), encoding="utf-8")

    clock = FakeClock()
    source = _source(folder, clock)
    source.start()
    clock.advance(0.05)

    for side_a, side_b in source.read(10):
        assert np.isfinite(side_a)
        assert np.isfinite(side_b)


def test_no_time_elapsed_means_no_samples(tmp_path):
    folder = tmp_path / "signals"
    _write_csv(folder, "v1.csv", [(1000, 2000)] * 100)

    clock = FakeClock()
    source = _source(folder, clock)
    source.start()
    assert source.read(100) == []


def test_sample_budget_follows_elapsed_time(tmp_path):
    folder = tmp_path / "signals"
    _write_csv(folder, "v1.csv", [(1000, 2000)] * 5000)

    clock = FakeClock()
    source = _source(folder, clock)
    source.start()
    clock.advance(0.1)
    assert len(source.read(1000)) == 100


def test_replay_speed_scales_the_budget(tmp_path):
    folder = tmp_path / "signals"
    _write_csv(folder, "v1.csv", [(1000, 2000)] * 5000)

    clock = FakeClock()
    source = _source(folder, clock, replay_speed=2.0)
    source.start()
    clock.advance(0.1)
    assert len(source.read(1000)) == 200


def test_files_play_in_sequence(tmp_path):
    folder = tmp_path / "signals"
    _write_csv(folder, "a.csv", [(100, 100)] * 50)
    _write_csv(folder, "b.csv", [(3000, 3000)] * 50)

    clock = FakeClock()
    source = _source(folder, clock)
    source.start()
    clock.advance(0.1)

    samples = source.read(100)
    assert len(samples) == 100
    assert samples[0][0] < samples[-1][0]


def test_exhausted_playlist_stops_when_not_looping(tmp_path):
    folder = tmp_path / "signals"
    _write_csv(folder, "a.csv", [(1000, 1000)] * 20)

    clock = FakeClock()
    source = _source(folder, clock, loop=False)
    source.start()
    clock.advance(1.0)
    source.read(1000)

    clock.advance(1.0)
    assert source.read(1000) == []
    assert source.status().state == "stopped"


def test_looping_playlist_keeps_going(tmp_path):
    folder = tmp_path / "signals"
    _write_csv(folder, "a.csv", [(1000, 1000)] * 20)

    clock = FakeClock()
    source = _source(folder, clock, loop=True)
    source.start()
    clock.advance(1.0)
    source.read(1000)

    clock.advance(1.0)
    assert len(source.read(1000)) > 0


def test_status_names_the_file_being_played(tmp_path):
    folder = tmp_path / "signals"
    _write_csv(folder, "volunteer_3.csv", [(1000, 2000)] * 100)

    clock = FakeClock()
    source = _source(folder, clock)
    source.start()
    assert "volunteer_3.csv" in source.status().detail
