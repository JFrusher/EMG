"""R2 regression: the scanner must never fall back to an arbitrary nearby device."""

from dataclasses import dataclass

import pytest

from emgdemo.sources.ble import NoMatchingDevice, parse_payload, select_device


@dataclass
class FakeDevice:
    address: str
    name: str | None = None
    service_uuids: tuple[str, ...] = ()


NEARBY = [
    FakeDevice(address="AA:BB:CC:DD:EE:01", name="Someone's Watch"),
    FakeDevice(address="AA:BB:CC:DD:EE:02", name="MYOWARE-01", service_uuids=("4fafc201",)),
    FakeDevice(address="AA:BB:CC:DD:EE:03", name=None),
]


def test_explicit_address_wins():
    chosen = select_device(NEARBY, address="aa:bb:cc:dd:ee:03")
    assert chosen.address == "AA:BB:CC:DD:EE:03"


def test_name_hint_matches_case_insensitively():
    assert select_device(NEARBY, name_hint="myoware").address == "AA:BB:CC:DD:EE:02"


def test_service_uuid_matches_when_the_name_does_not():
    assert select_device(NEARBY, service_uuid="4FAFC201").address == "AA:BB:CC:DD:EE:02"


def test_unmatched_address_is_an_error_not_a_substitute_device():
    with pytest.raises(NoMatchingDevice):
        select_device(NEARBY, address="11:22:33:44:55:66")


def test_unmatched_name_never_falls_back_to_the_first_device():
    # The original demo returned devices[0] here, connecting to a stranger's hardware.
    with pytest.raises(NoMatchingDevice):
        select_device(NEARBY, name_hint="nothing-like-this")


def test_no_criteria_at_all_is_refused():
    with pytest.raises(NoMatchingDevice):
        select_device(NEARBY)


def test_empty_scan_is_refused():
    with pytest.raises(NoMatchingDevice):
        select_device([], name_hint="myoware")


def test_uint16_pairs_decode_to_both_sides():
    payload = (2048).to_bytes(2, "little") + (1024).to_bytes(2, "little")
    ((side_a, side_b),) = parse_payload(payload, dual=True)
    assert side_a == pytest.approx(2048 / 4095 * 3.3, abs=1e-4)
    assert side_b == pytest.approx(1024 / 4095 * 3.3, abs=1e-4)


def test_uint16_singles_decode_to_side_a_only():
    payload = b"".join((v).to_bytes(2, "little") for v in (100, 200, 300))
    samples = parse_payload(payload, dual=False)
    assert len(samples) == 3
    assert all(side_b == 0.0 for _, side_b in samples)


def test_csv_text_payload_is_decoded():
    samples = parse_payload(b"1,2048,1024\n", dual=True)
    assert samples[0][0] == pytest.approx(2048 / 4095 * 3.3, abs=1e-4)


def test_out_of_range_counts_are_rejected_rather_than_wrapped():
    # 60000 is not a 12-bit ADC reading; treating it as one would render noise as signal.
    payload = (60000).to_bytes(2, "little")
    assert parse_payload(payload, dual=False) == []


def test_empty_payload_is_empty():
    assert parse_payload(b"", dual=True) == []
