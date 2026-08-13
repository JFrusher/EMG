from emgdemo.sources.synthetic import SyntheticSource


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _source(clock, **kwargs):
    return SyntheticSource(sample_rate_hz=1000, clock=clock, **kwargs)


def test_stopped_source_yields_nothing():
    clock = FakeClock()
    source = _source(clock)
    clock.advance(1.0)
    assert source.read(100) == []


def test_no_elapsed_time_means_no_samples():
    clock = FakeClock()
    source = _source(clock)
    source.start()
    assert source.read(100) == []


def test_sample_count_follows_elapsed_time():
    # A source that hands back whatever is asked for, whenever it is asked, is a
    # firehose: the engine measures its rate as tens of kilohertz and retunes to it.
    clock = FakeClock()
    source = _source(clock)
    source.start()

    clock.advance(0.064)
    assert len(source.read(1000)) == 64


def test_requests_smaller_than_the_budget_are_honoured():
    clock = FakeClock()
    source = _source(clock)
    source.start()
    clock.advance(1.0)
    assert len(source.read(100)) == 100


def test_samples_stay_inside_the_adc_voltage_range():
    clock = FakeClock()
    source = _source(clock)
    source.start()
    clock.advance(2.0)

    for side_a, side_b in source.read(2000):
        assert 0.0 <= side_a <= 3.3
        assert 0.0 <= side_b <= 3.3


def test_same_seed_produces_the_same_stream():
    clock_a, clock_b = FakeClock(), FakeClock()
    first, second = _source(clock_a, seed=7), _source(clock_b, seed=7)
    first.start()
    second.start()
    clock_a.advance(0.2)
    clock_b.advance(0.2)

    assert first.read(200) == second.read(200)


def test_the_two_sides_are_not_identical():
    clock = FakeClock()
    source = _source(clock, seed=1)
    source.start()
    clock.advance(0.5)

    assert any(abs(a - b) > 1e-6 for a, b in source.read(500))


def test_status_reports_streaming_once_started():
    source = _source(FakeClock())
    assert source.status().state == "stopped"
    source.start()
    assert source.status().state == "streaming"
    source.stop()
    assert source.status().state == "stopped"
