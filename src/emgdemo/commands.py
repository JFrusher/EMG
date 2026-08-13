"""Controls the operator can press, wherever the interface happens to live.

Kept apart from the transport so the same set works from a browser, a keyboard or a
test, and so an unrecognised action is refused rather than silently doing nothing.
"""

from __future__ import annotations

from collections.abc import Callable

from .engine import Engine


class UnknownCommand(Exception):
    """Raised when an action arrives that this build does not implement."""


def _pause(engine: Engine) -> None:
    engine.paused = True
    engine.log("Paused")


def _resume(engine: Engine) -> None:
    engine.paused = False
    engine.log("Resumed")


def _toggle_pause(engine: Engine) -> None:
    _resume(engine) if engine.paused else _pause(engine)


def _calibrate(engine: Engine) -> None:
    # A paused engine processes nothing, so a capture started while paused would collect
    # no samples and never reach its deadline. Pressing Calibrate means "measure me now".
    if engine.paused:
        _resume(engine)
    engine.begin_calibration()


def _reset(engine: Engine) -> None:
    engine.event_count = 0
    engine.cocontraction_count = 0
    engine.event_detector.reset()
    engine.cocontraction_detector.reset()
    engine.events_log.clear()
    engine.log("Counters reset")


COMMANDS: dict[str, Callable[[Engine], None]] = {
    "pause": _pause,
    "resume": _resume,
    "toggle-pause": _toggle_pause,
    "calibrate": _calibrate,
    "clear-calibration": lambda engine: engine.clear_calibration(),
    "reset": _reset,
}


def apply_command(engine: Engine, action: str) -> None:
    handler = COMMANDS.get(action)
    if handler is None:
        raise UnknownCommand(f"Unknown action {action!r}. Known: {sorted(COMMANDS)}")
    handler(engine)
