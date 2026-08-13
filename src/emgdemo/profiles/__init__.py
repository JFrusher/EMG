"""Named TOML profiles instead of a wall of command-line flags.

Unknown keys are errors, not shrugs. A profile is edited between sessions and read at a
stand, so a mistyped threshold that quietly does nothing is the worst possible outcome —
the demo comes up looking fine and behaving wrong.
"""

from __future__ import annotations

import dataclasses
import difflib
import tomllib
from dataclasses import fields, is_dataclass
from pathlib import Path

from ..config import DemoSettings

#: The .toml files shipped alongside this module.
SHIPPED = Path(__file__).parent

#: Keys each non-settings section may carry, mapped to their command-line names.
SOURCE_KEYS = {
    "kind": "source",
    "dataset_dir": "dataset_dir",
    "side_a_channel": "side_a_channel",
    "side_b_channel": "side_b_channel",
    "replay_speed": "replay_speed",
    "replay_loop": "replay_loop",
    "port": "port",
    "baud": "baud",
    "ble_address": "ble_address",
    "ble_name": "ble_name",
    "ble_service": "ble_service",
    "fallback_synthetic": "fallback_synthetic",
}

SERVER_KEYS = {
    "host": "host",
    "http_port": "http_port",
    "no_browser": "no_browser",
    "fullscreen": "fullscreen",
    "headless": "headless",
}

SECTIONS = ("source", "server", "settings")


class ProfileError(Exception):
    """Raised when a profile cannot be read, or asks for something that isn't there."""


def _did_you_mean(name: str, known) -> str:
    close = difflib.get_close_matches(name, sorted(known), n=1)
    return f" Did you mean {close[0]!r}?" if close else f" Known keys: {sorted(known)}"


def _apply(instance, values: dict, where: str):
    """Return a copy of a frozen settings dataclass with `values` applied, recursively."""
    known = {f.name: f for f in fields(instance)}
    changes = {}

    for key, value in values.items():
        field = known.get(key)
        if field is None:
            raise ProfileError(f"[{where}] has no setting {key!r}.{_did_you_mean(key, known)}")

        current = getattr(instance, key)
        if isinstance(value, dict):
            if not is_dataclass(current):
                raise ProfileError(f"[{where}.{key}] is a value, not a section")
            changes[key] = _apply(current, value, f"{where}.{key}")
        else:
            changes[key] = value

    return dataclasses.replace(instance, **changes)


def _checked(values: dict, allowed: dict, where: str) -> dict:
    out = {}
    for key, value in values.items():
        if key not in allowed:
            raise ProfileError(f"[{where}] has no key {key!r}.{_did_you_mean(key, allowed)}")
        out[allowed[key]] = value
    return out


@dataclasses.dataclass(frozen=True)
class Profile:
    path: Path
    settings: DemoSettings
    source: dict
    server: dict

    def cli_defaults(self) -> dict:
        return {**self.source, **self.server}


def resolve_profile(name: str) -> Path:
    """Accept either a bare profile name or a path to a TOML file."""
    candidate = Path(name)
    if candidate.suffix == ".toml" or candidate.exists():
        return candidate

    for folder in (Path("profiles"), SHIPPED):
        shipped = folder / f"{name}.toml"
        if shipped.is_file():
            return shipped
    return SHIPPED / f"{name}.toml"


def load_profile(path: Path | str) -> Profile:
    path = Path(path)
    if not path.is_file():
        raise ProfileError(f"No profile at {path}")

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{path} is not valid TOML: {exc}") from exc

    for section in raw:
        if section not in SECTIONS:
            raise ProfileError(
                f"{path} has no section [{section}].{_did_you_mean(section, SECTIONS)}"
            )

    return Profile(
        path=path,
        settings=_apply(DemoSettings(), raw.get("settings", {}), "settings"),
        source=_checked(raw.get("source", {}), SOURCE_KEYS, "source"),
        server=_checked(raw.get("server", {}), SERVER_KEYS, "server"),
    )
