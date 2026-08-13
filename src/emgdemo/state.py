"""The single boundary between the engine and anything that displays it.

Everything a renderer, a log or a test needs is in here, and nothing else crosses. That
is what lets the UI be swapped, the session be recorded, and the engine be exercised
with no screen attached.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain.gripper import GripperState
from .dsp.pipeline import StageOutputs


@dataclass(frozen=True)
class DemoState:
    t: float

    source_name: str
    source_state: str
    source_detail: str
    failover_active: bool

    measured_rate_hz: float
    design_rate_hz: float

    stages: StageOutputs
    side_a_level: float
    side_b_level: float
    envelope_level: float
    gripper: GripperState

    total_samples: int
    event_count: int
    cocontraction_count: int
    events: tuple[str, ...]

    paused: bool
    calibrating: bool
    calibrated: bool
