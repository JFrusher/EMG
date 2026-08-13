import pytest

from emgdemo.cli import build_source, parse_args
from emgdemo.sources.ble import NoMatchingDevice
from emgdemo.sources.replay import DatasetReplaySource, NoDatasetFiles
from emgdemo.sources.synthetic import SyntheticSource


def test_default_source_needs_no_hardware():
    assert parse_args([]).source == "synthetic"


def test_synthetic_source_is_built():
    source, name = build_source(parse_args([]), sample_rate_hz=1000.0)
    assert isinstance(source, SyntheticSource)
    assert "ynthetic" in name


def test_dataset_source_is_built_from_a_folder(tmp_path):
    (tmp_path / "v1.csv").write_text(",HandOpen,HandClose\n0,10,20\n", encoding="utf-8")
    args = parse_args(["--source", "dataset", "--dataset-dir", str(tmp_path)])

    source, name = build_source(args, sample_rate_hz=1000.0)
    assert isinstance(source, DatasetReplaySource)
    assert tmp_path.name in name or "dataset" in name.lower()


def test_a_missing_dataset_folder_is_reported_not_silently_replaced(tmp_path):
    args = parse_args(["--source", "dataset", "--dataset-dir", str(tmp_path / "nope")])
    with pytest.raises(NoDatasetFiles):
        build_source(args, sample_rate_hz=1000.0)


def test_ble_without_an_identifier_is_refused(tmp_path):
    args = parse_args(["--source", "ble"])
    with pytest.raises(NoMatchingDevice):
        build_source(args, sample_rate_hz=1000.0)


def test_fallback_flag_turns_a_setup_failure_into_synthetic(tmp_path):
    args = parse_args(
        ["--source", "dataset", "--dataset-dir", str(tmp_path / "nope"), "--fallback-synthetic"]
    )
    source, name = build_source(args, sample_rate_hz=1000.0)
    assert isinstance(source, SyntheticSource)
    assert "fallback" in name.lower()
