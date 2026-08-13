"""R4 regression: a non-blocking read must never hand a truncated line to the parser."""

import pytest

from emgdemo.sources.serial import LineBuffer, SerialSource, decode_line


class FakePort:
    """Duck-typed stand-in for a pyserial handle that yields scripted byte chunks."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def read(self, _size):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True


def test_complete_line_is_emitted():
    assert LineBuffer().feed(b"12,34\n") == ["12,34"]


def test_partial_line_is_held_until_its_newline_arrives():
    buffer = LineBuffer()
    assert buffer.feed(b"1234,20") == []
    assert buffer.feed(b"48\n") == ["1234,2048"]


def test_several_lines_in_one_chunk_all_emerge():
    assert LineBuffer().feed(b"1,2\n3,4\n5,6\n") == ["1,2", "3,4", "5,6"]


def test_carriage_returns_are_stripped():
    assert LineBuffer().feed(b"1,2\r\n") == ["1,2"]


def test_buffer_does_not_grow_without_bound_on_a_garbage_stream():
    buffer = LineBuffer(max_pending_bytes=64)
    buffer.feed(b"x" * 5000)
    assert buffer.pending_bytes <= 64


def test_legacy_two_field_line_is_timestamp_then_value():
    assert decode_line("1234,2048") == pytest.approx((2048 / 4095 * 3.3, 0.0))


def test_dual_pad_line_uses_the_last_two_fields():
    side_a, side_b = decode_line("1234,2048,1024")
    assert side_a == pytest.approx(2048 / 4095 * 3.3)
    assert side_b == pytest.approx(1024 / 4095 * 3.3)


def test_values_already_in_volts_pass_through():
    # Two fields are always read as the firmware's legacy timestamp,adc pair, so a
    # volts-valued line has to carry a timestamp to be read as dual-pad.
    assert decode_line("1,1.2,0.8") == pytest.approx((1.2, 0.8))


def test_banner_and_junk_lines_are_ignored():
    assert decode_line("=== EMG READY ===") is None
    assert decode_line("") is None
    assert decode_line("hello") is None


def test_truncated_line_never_reaches_the_sample_stream():
    port = FakePort([b"1,2048,1024\n1,40", b"95,0\n"])
    source = SerialSource(port_factory=lambda: port, sample_rate_hz=1000)
    source.start()

    first = source.read(10)
    assert len(first) == 1

    second = source.read(10)
    assert second[0][0] == pytest.approx(3.3)


def test_stopped_source_yields_nothing():
    source = SerialSource(port_factory=lambda: FakePort([b"1,2\n"]), sample_rate_hz=1000)
    assert source.read(10) == []


def test_failure_to_open_is_reported_not_raised():
    def explode():
        raise OSError("COM3 not found")

    source = SerialSource(port_factory=explode, sample_rate_hz=1000)
    source.start()
    assert source.read(10) == []
    assert source.status().state == "reconnecting"
    assert "COM3" in source.status().detail
