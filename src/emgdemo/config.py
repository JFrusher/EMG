"""Tunable constants, grouped by what they configure.

Every value that used to be a magic number in the demo loop lives here so it can be
overridden from a TOML profile without touching code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FilterConfig:
    """Pre-rectification cascade plus the post-rectification smoothing."""

    notch_freq_hz: float = 50.0
    notch_q: float = 30.0
    bandpass_low_hz: float = 20.0
    bandpass_high_hz: float = 400.0
    bandpass_order: int = 2
    lowpass_cutoff_hz: float = 150.0
    lowpass_order: int = 3
    envelope_window_ms: float = 200.0


@dataclass(frozen=True)
class NormalizeConfig:
    """Adaptive reference used until a participant has been calibrated.

    The ceiling rises toward peaks and leaks back down slowly; the baseline sinks toward
    troughs and creeps back up more slowly still. A steady input collapses the two
    together and reads as rest, which is what the old trailing-percentile reference got
    wrong (R8).

    Neither edge tracks instantly, and that matters more than it looks: a reference that
    jumps straight onto every peak and trough hugs the signal's own ripple, so a
    perfectly steady envelope with a few percent of jitter gets stretched across the
    whole 0..1 range and reads as a sustained contraction.
    """

    #: Samples observed before the reference commits to a baseline and ceiling. The
    #: opening moments of a session are the filters settling, not the participant, so
    #: seeding on the first sample anchors the baseline to a transient near zero and
    #: then takes tens of seconds to climb off it.
    warmup_samples: int = 1000

    #: Per-sample tracking rates at the design sample rate. Attack is faster than
    #: release so a real contraction registers quickly but does not immediately reset
    #: the scale it is being measured against.
    ceiling_attack: float = 0.003
    ceiling_release: float = 0.0005
    baseline_fall: float = 0.002
    baseline_rise: float = 0.0002

    #: How far above rest a contraction must reach to count as full scale. This is the
    #: knob to turn per electrode set and gain; calibration replaces it outright.
    min_span: float = 0.15


@dataclass(frozen=True)
class EventConfig:
    threshold_high: float = 0.28
    threshold_low: float = 0.20
    min_interval_s: float = 0.25


@dataclass(frozen=True)
class GripperConfig:
    force_gain: float = 12.0
    force_smoothing: float = 0.20
    max_force_n: float = 100.0
    finger_ratios: tuple[float, ...] = (0.72, 1.0, 1.0, 0.9, 0.82)
    finger_smoothing: float = 0.18
    light_force_n: float = 10.0
    power_force_n: float = 40.0


@dataclass(frozen=True)
class CalibrationConfig:
    min_samples: int = 20
    baseline_percentile: float = 20.0
    ceiling_percentile: float = 95.0
    min_span: float = 0.03


@dataclass(frozen=True)
class ResilienceConfig:
    """Watchdog thresholds for a source that has gone quiet."""

    stall_timeout_s: float = 2.0
    restart_cooldown_s: float = 5.0
    max_restarts: int = 3


@dataclass(frozen=True)
class DemoSettings:
    """Everything the engine needs. A TOML profile overrides fields on this."""

    sample_rate_hz: float = 1000.0
    trace_seconds: float = 8.0
    max_events: int = 12

    #: Longest stretch of samples drained in one tick. Bounds catch-up work after a
    #: slow tick without ever coupling intake to a frame rate, which was R7.
    max_tick_seconds: float = 0.25

    #: How far the measured rate may drift from the design rate before the filters are
    #: rebuilt, and how long to wait between rebuilds so a jittery rate cannot thrash.
    retune_tolerance: float = 0.15
    min_retune_interval_s: float = 2.0
    rate_window_s: float = 1.0

    #: How often the per-stage noise-reduction figures are recomputed. They scan the
    #: whole trace buffer, so they are worth throttling well below the tick rate.
    improvement_interval_s: float = 0.3

    #: Rates outside this band are treated as a broken source rather than something to
    #: design filters against. A stream claiming 50 kHz is a bug, and quietly retuning
    #: to it moves the 50 Hz notch somewhere useless.
    min_design_rate_hz: float = 50.0
    max_design_rate_hz: float = 20_000.0

    filters: FilterConfig = field(default_factory=FilterConfig)
    normalize: NormalizeConfig = field(default_factory=NormalizeConfig)
    events: EventConfig = field(default_factory=EventConfig)
    gripper: GripperConfig = field(default_factory=GripperConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    resilience: ResilienceConfig = field(default_factory=ResilienceConfig)
