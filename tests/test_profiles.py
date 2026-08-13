"""Profiles replace the flag soup. A typo in one must not pass silently."""

import pytest

from emgdemo.profiles import ProfileError, load_profile, resolve_profile


def _write(tmp_path, text, name="test.toml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_settings_are_overridden(tmp_path):
    profile = load_profile(_write(tmp_path, "[settings]\ntrace_seconds = 4.0\n"))
    assert profile.settings.trace_seconds == 4.0


def test_unspecified_settings_keep_their_defaults(tmp_path):
    profile = load_profile(_write(tmp_path, "[settings]\ntrace_seconds = 4.0\n"))
    assert profile.settings.sample_rate_hz == 1000.0


def test_nested_sections_reach_nested_settings(tmp_path):
    profile = load_profile(
        _write(
            tmp_path,
            "[settings.gripper]\nforce_gain = 20.0\n[settings.events]\nthreshold_high = 0.5\n",
        )
    )
    assert profile.settings.gripper.force_gain == 20.0
    assert profile.settings.events.threshold_high == 0.5
    assert profile.settings.gripper.force_smoothing == 0.20


def test_source_and_server_keys_become_command_line_defaults(tmp_path):
    profile = load_profile(
        _write(
            tmp_path, '[source]\nkind = "dataset"\nreplay_loop = true\n[server]\nhttp_port = 9000\n'
        )
    )
    defaults = profile.cli_defaults()
    assert defaults["source"] == "dataset"
    assert defaults["replay_loop"] is True
    assert defaults["http_port"] == 9000


def test_a_misspelled_setting_is_an_error_not_a_shrug(tmp_path):
    # Silently ignoring `treshold_high` means finding out at the stand.
    with pytest.raises(ProfileError, match="threshold_high"):
        load_profile(_write(tmp_path, "[settings.events]\ntreshold_high = 0.5\n"))


def test_a_misspelled_section_is_an_error(tmp_path):
    with pytest.raises(ProfileError, match="settings"):
        load_profile(_write(tmp_path, "[setings]\ntrace_seconds = 4.0\n"))


def test_a_misspelled_source_key_is_an_error(tmp_path):
    with pytest.raises(ProfileError, match="replay_loop"):
        load_profile(_write(tmp_path, "[source]\nreplay_lop = true\n"))


def test_a_missing_profile_names_the_path_it_looked_for(tmp_path):
    with pytest.raises(ProfileError, match="nope.toml"):
        load_profile(tmp_path / "nope.toml")


def test_malformed_toml_is_reported_clearly(tmp_path):
    with pytest.raises(ProfileError, match="test.toml"):
        load_profile(_write(tmp_path, "[settings\ntrace_seconds = 4.0\n"))


def test_a_bare_name_resolves_to_the_shipped_profiles():
    assert resolve_profile("expo").name == "expo.toml"
    assert resolve_profile("expo").is_file()


def test_an_explicit_path_is_used_as_given(tmp_path):
    path = _write(tmp_path, "[settings]\ntrace_seconds = 2.0\n", name="mine.toml")
    assert resolve_profile(str(path)) == path


def test_the_shipped_profiles_load():
    for name in ("expo", "dev"):
        assert load_profile(resolve_profile(name)).settings.sample_rate_hz > 0
