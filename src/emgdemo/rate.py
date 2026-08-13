"""Measure the rate a source is actually delivering.

The old demo displayed this number and then ignored it, designing every filter for a
hardcoded 1 kHz (R1). Here it is an input to filter design.
"""

from __future__ import annotations


class RateMeter:
    """Exponentially smoothed sample rate, reported only once it has settled."""

    def __init__(self, window_s: float = 1.0):
        self.window_s = float(window_s)
        self._smoothing = 4.0 / self.window_s
        self._rate: float | None = None
        self._last_t: float | None = None
        self._elapsed = 0.0

    def observe(self, count: int, now: float) -> None:
        if self._last_t is None:
            self._last_t = now
            return

        dt = now - self._last_t
        self._last_t = now
        if dt <= 0.0:
            return

        self._elapsed += dt
        instant = count / dt

        if self._rate is None:
            self._rate = instant
            return

        alpha = min(1.0, dt * self._smoothing)
        self._rate += (instant - self._rate) * alpha

    @property
    def rate_hz(self) -> float | None:
        if self._rate is None or self._elapsed < self.window_s * 0.9:
            return None
        return self._rate

    def reset(self) -> None:
        self._rate = None
        self._last_t = None
        self._elapsed = 0.0
