"""The one boundary every input crosses.

A structural protocol rather than a base class: a source is anything with these four
methods, so a fake in a test is a handful of lines and nothing has to inherit.

Both pads are always present. The original had a dual-channel path and a single-channel
path, and the single-channel one ended up with four implementations and no callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: (side A, side B) in volts. Side A closes the gripper, side B opens it.
Sample = tuple[float, float]

ADC_MAX_COUNTS = 4095.0
ADC_REFERENCE_V = 3.3


def to_voltage(value: float) -> float:
    """Interpret a reading as volts, or as 12-bit ADC counts if it is out of range."""
    value = float(value)
    if value > ADC_REFERENCE_V:
        value = (value / ADC_MAX_COUNTS) * ADC_REFERENCE_V
    return min(max(value, 0.0), ADC_REFERENCE_V)


@dataclass(frozen=True)
class SourceStatus:
    """What the operator needs to know about this input, in words they can act on."""

    state: str  # stopped | connecting | streaming | reconnecting | error
    detail: str = ""


@runtime_checkable
class SignalSource(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def read(self, max_samples: int) -> list[Sample]: ...

    def status(self) -> SourceStatus: ...
