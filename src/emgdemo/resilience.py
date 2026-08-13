"""Watchdog for a source that stops delivering.

Ported from the original demo's recovery logic, which was sound. The one change is that
every decision is recorded rather than swallowed, so an operator can see why the demo
switched to synthetic instead of guessing (R10).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .config import ResilienceConfig


class Action(Enum):
    NONE = "none"
    RESTART = "restart"
    FAILOVER = "failover"


@dataclass(frozen=True)
class SupervisorEvent:
    t: float
    action: Action
    reason: str


class SourceSupervisor:
    """Decides when to restart a silent source and when to give up on it."""

    def __init__(self, config: ResilienceConfig | None = None):
        self.config = config or ResilienceConfig()
        self.history: list[SupervisorEvent] = []
        self.restarts = 0
        self.failed_over = False
        self._last_sample_t: float | None = None
        self._last_restart_t = float("-inf")

    def observe(self, samples_seen: int, now: float) -> Action:
        if samples_seen > 0:
            self._last_sample_t = now
            return Action.NONE

        if self._last_sample_t is None:
            self._last_sample_t = now
            return Action.NONE

        if self.failed_over:
            return Action.NONE

        silent_for = now - self._last_sample_t
        if silent_for < self.config.stall_timeout_s:
            return Action.NONE

        if (now - self._last_restart_t) < self.config.restart_cooldown_s:
            return Action.NONE

        if self.restarts >= self.config.max_restarts:
            self.failed_over = True
            return self._record(
                now, Action.FAILOVER, f"failover after {self.restarts} failed restarts"
            )

        self.restarts += 1
        self._last_restart_t = now
        return self._record(now, Action.RESTART, f"source stall: no samples for {silent_for:.1f}s")

    def note_samples(self, now: float) -> None:
        """Called after a successful restart so the stall clock starts fresh."""
        self._last_sample_t = now

    def _record(self, now: float, action: Action, reason: str) -> Action:
        self.history.append(SupervisorEvent(t=now, action=action, reason=reason))
        return action
