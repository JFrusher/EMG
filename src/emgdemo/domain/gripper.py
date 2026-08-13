"""Differential gripper model — the demo's personality, constants preserved.

Left pad closes, right pad opens, and the difference drives a force integrator rather
than a position. That integrator is why the grip holds when a participant relaxes
slightly, which is what makes the thing feel like a prosthesis instead of a slider.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import GripperConfig


@dataclass(frozen=True)
class GripperState:
    force_n: float
    label: str
    finger_positions: tuple[float, ...]


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


class Gripper:
    def __init__(self, config: GripperConfig | None = None):
        self.config = config or GripperConfig()
        self.force_n = 0.0
        self.finger_positions = tuple(0.0 for _ in self.config.finger_ratios)

    def step(self, close_level: float, open_level: float) -> GripperState:
        command = _clamp(float(close_level) - float(open_level), -1.0, 1.0)

        target_force = _clamp(
            self.force_n + command * self.config.force_gain, 0.0, self.config.max_force_n
        )
        self.force_n += (target_force - self.force_n) * self.config.force_smoothing

        closure = self.force_n / self.config.max_force_n
        self.finger_positions = tuple(
            position + (_clamp(closure * ratio, 0.0, 1.0) - position) * self.config.finger_smoothing
            for position, ratio in zip(
                self.finger_positions, self.config.finger_ratios, strict=True
            )
        )

        return self.state()

    def state(self) -> GripperState:
        return GripperState(
            force_n=self.force_n,
            label=self._label(),
            finger_positions=self.finger_positions,
        )

    def _label(self) -> str:
        if self.force_n < self.config.light_force_n:
            return "OPEN"
        if self.force_n < self.config.power_force_n:
            return "LIGHT"
        return "POWER"

    def reset(self) -> None:
        self.force_n = 0.0
        self.finger_positions = tuple(0.0 for _ in self.config.finger_ratios)
