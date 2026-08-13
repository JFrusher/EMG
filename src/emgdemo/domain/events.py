"""Activation and co-contraction detection. Pure functions of level and time."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import EventConfig

_NEVER = float("-inf")


@dataclass(frozen=True)
class EventStep:
    started: bool
    active: bool


class EventDetector:
    """Threshold crossing with hysteresis and a refractory guard.

    Rises above ``threshold_high`` to fire, must fall below ``threshold_low`` to re-arm,
    and cannot fire twice inside ``min_interval_s``.
    """

    def __init__(self, config: EventConfig | None = None):
        self.config = config or EventConfig()
        self.active = False
        self.last_event_time = _NEVER

    def step(self, level: float, t: float) -> EventStep:
        started = False

        rearmed = not self.active and level >= self.config.threshold_high
        if rearmed and (t - self.last_event_time) >= self.config.min_interval_s:
            self.active = True
            self.last_event_time = t
            started = True

        if self.active and level <= self.config.threshold_low:
            self.active = False

        return EventStep(started=started, active=self.active)

    def reset(self) -> None:
        self.active = False
        self.last_event_time = _NEVER


class CoContractionDetector:
    """Both pads driven at once — the participant is bracing rather than gripping."""

    def __init__(self, config: EventConfig | None = None):
        self.config = config or EventConfig()
        self.active = False
        self.last_event_time = _NEVER

    def step(self, side_a: float, side_b: float, t: float) -> EventStep:
        both_high = side_a >= self.config.threshold_high and side_b >= self.config.threshold_high
        started = False

        rearmed = both_high and not self.active
        if rearmed and (t - self.last_event_time) >= self.config.min_interval_s:
            self.last_event_time = t
            started = True

        self.active = both_high
        return EventStep(started=started, active=self.active)

    def reset(self) -> None:
        self.active = False
        self.last_event_time = _NEVER
