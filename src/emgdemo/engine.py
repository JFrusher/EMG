"""The demo's one clock.

Pulls whatever the source has, runs it through three pipelines, and publishes a
``DemoState``. It knows nothing about drawing, and nothing that draws can slow it down —
which is the whole point, since the original ran all of this inside a matplotlib
animation callback and dropped samples whenever a frame was slow (R7).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

import numpy as np

from .config import DemoSettings
from .domain.calibration import CalibrationError, calibrate
from .domain.events import CoContractionDetector, EventDetector
from .domain.gripper import Gripper
from .dsp.metrics import improvement_pct
from .dsp.normalize import AdaptiveReference, Calibrated
from .dsp.pipeline import EMGPipeline, StageOutputs
from .rate import RateMeter
from .resilience import Action, SourceSupervisor
from .sources.base import ADC_REFERENCE_V, SignalSource
from .sources.synthetic import SyntheticSource
from .state import DemoState

STAGE_KEYS = ("raw", "notch", "bandpass", "rectified", "lowpass", "envelope")

#: Stages compared against the raw input for the "how much cleaner" readout.
FILTERED_STAGE_KEYS = STAGE_KEYS[1:]

_REST_STAGES = StageOutputs(
    raw=0.0, notch=0.0, bandpass=0.0, rectified=0.0, lowpass=0.0, envelope=0.0
)


class Engine:
    def __init__(
        self,
        settings: DemoSettings,
        source: SignalSource,
        source_name: str = "source",
        clock: Callable[[], float] = time.perf_counter,
        synthetic_factory: Callable[[float], SignalSource] | None = None,
    ):
        self.settings = settings
        self.source = source
        self.source_name = source_name
        self.clock = clock
        # The stand-in stream is paced by the engine's own clock, so a failover under a
        # test clock behaves the same way it does under a wall clock.
        self.synthetic_factory = synthetic_factory or (
            lambda rate: SyntheticSource(rate, clock=self.clock)
        )

        self.design_rate_hz = float(settings.sample_rate_hz)
        self.paused = False
        self.failover_active = False

        self.total_samples = 0
        self.event_count = 0
        self.cocontraction_count = 0

        self.rate_meter = RateMeter(window_s=settings.rate_window_s)
        self.supervisor = SourceSupervisor(settings.resilience)
        self.events_log: deque[str] = deque(maxlen=settings.max_events)

        self.event_detector = EventDetector(settings.events)
        self.cocontraction_detector = CoContractionDetector(settings.events)
        self.gripper = Gripper(settings.gripper)

        self.calibrating = False
        self.calibrated = False
        self._calibration_end = 0.0
        self._calibration_a: list[float] = []
        self._calibration_b: list[float] = []

        self._now = 0.0
        self._session_t0: float | None = None
        self._last_retune_t = float("-inf")
        self._warned_implausible_rate = False

        # The engine runs on its own thread while the server reads frames from another,
        # so trace mutation and frame building must not overlap.
        self._lock = threading.RLock()
        self._improvements: dict[str, float] = dict.fromkeys(FILTERED_STAGE_KEYS, 0.0)
        self._last_improvement_t = float("-inf")

        self.side_a_level = 0.0
        self.side_b_level = 0.0
        self.envelope_level = 0.0
        self.latest_stages = _REST_STAGES

        self._build_signal_chain()

    # -- setup ---------------------------------------------------------------

    def _build_signal_chain(self) -> None:
        rate = self.design_rate_hz
        self.pipeline = EMGPipeline(self.settings.filters, rate)
        self.pipeline_a = EMGPipeline(self.settings.filters, rate)
        self.pipeline_b = EMGPipeline(self.settings.filters, rate)

        trace_len = max(1, int(self.settings.trace_seconds * rate))
        existing = getattr(self, "traces", None)
        self.traces = {
            key: deque(existing[key] if existing else [], maxlen=trace_len) for key in STAGE_KEYS
        }

        if not self.calibrated:
            self.norm_a = AdaptiveReference(self.settings.normalize)
            self.norm_b = AdaptiveReference(self.settings.normalize)
        self.norm_envelope = AdaptiveReference(self.settings.normalize)

        self.max_samples_per_tick = max(1, int(rate * self.settings.max_tick_seconds))

    def trace(self, key: str) -> deque[float]:
        return self.traces[key]

    @property
    def events(self) -> tuple[str, ...]:
        return tuple(self.events_log)

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self._session_t0 = None
        try:
            self.source.start()
            self.log(f"Input source: {self.source_name}")
        except Exception as exc:  # noqa: BLE001 - reported, then failed over
            self.log(f"Source failed to start: {exc}")
            self._failover(f"{self.source_name} would not start")

    def stop(self) -> None:
        try:
            self.source.stop()
        except Exception as exc:  # noqa: BLE001 - reported, never hides a shutdown
            self.log(f"Source stop warning: {exc}")

    def log(self, message: str) -> None:
        self.events_log.appendleft(f"[{self._elapsed():6.2f}s] {message}")

    def _elapsed(self) -> float:
        return 0.0 if self._session_t0 is None else self._now - self._session_t0

    # -- the loop ------------------------------------------------------------

    def tick(self) -> DemoState:
        with self._lock:
            self._now = self.clock()
            if self._session_t0 is None:
                self._session_t0 = self._now

            if self.paused:
                return self.snapshot()

            samples = self._read_samples()
            self.rate_meter.observe(len(samples), self._now)
            self._supervise(len(samples))
            self._maybe_retune()

            if samples:
                self._process_block(samples)
                self.total_samples += len(samples)
                self._maybe_recompute_improvements()

            # Checked here rather than only where samples are handled, so a capture
            # still ends on time when the source has gone quiet underneath it.
            if self.calibrating and self._now >= self._calibration_end:
                self._finish_calibration()

            return self.snapshot()

    def _read_samples(self):
        try:
            return self.source.read(self.max_samples_per_tick)
        except Exception as exc:  # noqa: BLE001 - a broken source is a status, not a crash
            self.log(f"Read error: {exc}")
            self._restart_source("read error")
            return []

    def _process_block(self, samples) -> None:
        """Filter the whole batch at once, then walk it for the stateful domain logic.

        Filtering is vectorised because it dominates the cost; normalization, event
        detection and the gripper stay per-sample because each depends on the last.
        """
        block = np.asarray(samples, dtype=np.float64)
        side_a_raw = block[:, 0]
        side_b_raw = block[:, 1]
        combined = np.clip(side_a_raw + side_b_raw, 0.0, ADC_REFERENCE_V)

        stages = self.pipeline.step_block(combined)
        envelope_a = self.pipeline_a.step_block(side_a_raw)["envelope"]
        envelope_b = self.pipeline_b.step_block(side_b_raw)["envelope"]

        for key in STAGE_KEYS:
            self.traces[key].extend(stages[key].tolist())
        self.latest_stages = StageOutputs(**{key: float(stages[key][-1]) for key in STAGE_KEYS})

        if self.calibrating:
            self._calibration_a.extend(envelope_a.tolist())
            self._calibration_b.extend(envelope_b.tolist())

        envelope = stages["envelope"]
        step_s = 1.0 / self.design_rate_hz
        base_t = self._elapsed()

        for index in range(block.shape[0]):
            self.side_a_level = self.norm_a.step(envelope_a[index])
            self.side_b_level = self.norm_b.step(envelope_b[index])
            self.envelope_level = self.norm_envelope.step(envelope[index])
            t = base_t + index * step_s

            if self.event_detector.step(self.envelope_level, t).started:
                self.event_count += 1
                self.log(f"Activation | level={self.envelope_level:.2f}")

            if self.cocontraction_detector.step(self.side_a_level, self.side_b_level, t).started:
                self.cocontraction_count += 1
                self.log(f"Co-contraction | L={self.side_a_level:.2f} R={self.side_b_level:.2f}")

            self.gripper.step(self.side_a_level, self.side_b_level)

    # -- rate tracking -------------------------------------------------------

    def _maybe_retune(self) -> None:
        measured = self.rate_meter.rate_hz
        if measured is None or measured <= 0.0:
            return
        if (self._now - self._last_retune_t) < self.settings.min_retune_interval_s:
            return

        drift = abs(measured - self.design_rate_hz) / self.design_rate_hz
        if drift <= self.settings.retune_tolerance:
            return

        if not (self.settings.min_design_rate_hz <= measured <= self.settings.max_design_rate_hz):
            self._last_retune_t = self._now
            if not self._warned_implausible_rate:
                self._warned_implausible_rate = True
                self.log(f"Ignoring implausible source rate of {measured:.0f} Hz")
            return

        self._warned_implausible_rate = False
        self._last_retune_t = self._now
        self.design_rate_hz = measured
        self._build_signal_chain()
        self.log(f"Filters retuned for {measured:.0f} Hz")

    # -- failure handling ----------------------------------------------------

    def _supervise(self, samples_seen: int) -> None:
        action = self.supervisor.observe(samples_seen, self._now)
        if action is Action.RESTART:
            self._restart_source(self.supervisor.history[-1].reason)
        elif action is Action.FAILOVER:
            self._failover(self.supervisor.history[-1].reason)

    def _restart_source(self, reason: str) -> None:
        if self.failover_active:
            return
        self.log(f"Restarting source: {reason}")
        # Whatever rate was measured across a dying stream describes its failure, not
        # the hardware. Measuring again from scratch after the break.
        self.rate_meter.reset()
        try:
            self.source.stop()
            self.source.start()
            self.supervisor.note_samples(self._now)
        except Exception as exc:  # noqa: BLE001 - reported, failover handles the rest
            self.log(f"Restart failed: {exc}")

    def _failover(self, reason: str) -> None:
        if self.failover_active:
            return
        try:
            self.source.stop()
        except Exception as exc:  # noqa: BLE001 - the dead source is being replaced
            self.log(f"Stop warning during failover: {exc}")

        # The stand-in runs at the configured rate, not at whatever the failing source
        # was last measured to be limping along at.
        self.rate_meter.reset()
        if self.design_rate_hz != self.settings.sample_rate_hz:
            self.design_rate_hz = float(self.settings.sample_rate_hz)
            self._build_signal_chain()

        self.source = self.synthetic_factory(self.design_rate_hz)
        self.source_name = "Synthetic (failover)"
        self.failover_active = True
        self.source.start()
        self.supervisor.note_samples(self._now)
        self.log(f"Switched to synthetic: {reason}")

    # -- calibration ---------------------------------------------------------

    def begin_calibration(self, duration_s: float = 4.0) -> None:
        self.calibrating = True
        self._calibration_end = self._now + duration_s
        self._calibration_a = []
        self._calibration_b = []
        self.log(f"Calibrating for {duration_s:.0f}s - rest, then squeeze both pads")

    def _finish_calibration(self) -> None:
        self.calibrating = False
        try:
            profile_a = calibrate(self._calibration_a, self.settings.calibration)
            profile_b = calibrate(self._calibration_b, self.settings.calibration)
        except CalibrationError as exc:
            self.log(f"Calibration failed: {exc}")
            return

        self.norm_a = Calibrated(profile_a.baseline, profile_a.span)
        self.norm_b = Calibrated(profile_b.baseline, profile_b.span)
        self.calibrated = True
        self.log(
            f"Calibrated | A base={profile_a.baseline:.3f} span={profile_a.span:.3f}"
            f" | B base={profile_b.baseline:.3f} span={profile_b.span:.3f}"
        )

    def clear_calibration(self) -> None:
        self.calibrated = False
        self.norm_a = AdaptiveReference(self.settings.normalize)
        self.norm_b = AdaptiveReference(self.settings.normalize)
        self.log("Calibration cleared")

    # -- output --------------------------------------------------------------

    def _maybe_recompute_improvements(self) -> None:
        if (self._now - self._last_improvement_t) < self.settings.improvement_interval_s:
            return
        self._last_improvement_t = self._now

        raw = np.fromiter(self.traces["raw"], dtype=np.float64)
        self._improvements = {
            key: improvement_pct(raw, np.fromiter(self.traces[key], dtype=np.float64))
            for key in FILTERED_STAGE_KEYS
        }

    @staticmethod
    def _downsample(values: list[float], max_points: int) -> list[float]:
        """Thin a trace for display, always keeping the newest sample.

        Striding from the end rather than the start matters: the right-hand edge of the
        plot is the live one, and a stride that drops it makes the trace look stalled.
        """
        if max_points <= 0 or len(values) <= max_points:
            return values
        stride = (len(values) + max_points - 1) // max_points
        return values[::-1][::stride][::-1]

    def render_frame(self, max_points: int = 400) -> dict:
        """One complete picture of the demo, ready to be JSON-encoded."""
        with self._lock:
            state = self.snapshot()
            traces = {
                key: self._downsample([float(v) for v in self.traces[key]], max_points)
                for key in STAGE_KEYS
            }
            improvements = dict(self._improvements)

        return {
            "t": float(state.t),
            "source": {
                "name": state.source_name,
                "state": state.source_state,
                "detail": state.source_detail,
                "failover": bool(state.failover_active),
            },
            "rate": {
                "measured": float(state.measured_rate_hz),
                "design": float(state.design_rate_hz),
            },
            "levels": {
                "a": float(state.side_a_level),
                "b": float(state.side_b_level),
                "envelope": float(state.envelope_level),
            },
            "thresholds": {
                "high": float(self.settings.events.threshold_high),
                "low": float(self.settings.events.threshold_low),
            },
            "gripper": {
                "force": float(state.gripper.force_n),
                "max_force": float(self.settings.gripper.max_force_n),
                "label": state.gripper.label,
                "fingers": [float(p) for p in state.gripper.finger_positions],
            },
            "counts": {
                "samples": int(state.total_samples),
                "events": int(state.event_count),
                "cocontractions": int(state.cocontraction_count),
            },
            "events": list(state.events),
            "flags": {
                "paused": bool(state.paused),
                "calibrating": bool(state.calibrating),
                "calibrated": bool(state.calibrated),
            },
            "improvements": {k: float(v) for k, v in improvements.items()},
            "traces": traces,
            "view_seconds": float(self.settings.trace_seconds),
        }

    def snapshot(self) -> DemoState:
        status = self.source.status()
        return DemoState(
            t=self._elapsed(),
            source_name=self.source_name,
            source_state=status.state,
            source_detail=status.detail,
            failover_active=self.failover_active,
            measured_rate_hz=self.rate_meter.rate_hz or 0.0,
            design_rate_hz=self.design_rate_hz,
            stages=self.latest_stages,
            side_a_level=self.side_a_level,
            side_b_level=self.side_b_level,
            envelope_level=self.envelope_level,
            gripper=self.gripper.state(),
            total_samples=self.total_samples,
            event_count=self.event_count,
            cocontraction_count=self.cocontraction_count,
            events=tuple(self.events_log),
            paused=self.paused,
            calibrating=self.calibrating,
            calibrated=self.calibrated,
        )

    # -- threaded operation --------------------------------------------------

    def run(
        self, on_state: Callable[[DemoState], None], stop: threading.Event, tick_hz: float = 200.0
    ) -> None:
        """Drive the engine until ``stop`` is set, publishing every snapshot."""
        interval = 1.0 / tick_hz
        self.start()
        try:
            while not stop.is_set():
                on_state(self.tick())
                stop.wait(interval)
        finally:
            self.stop()
