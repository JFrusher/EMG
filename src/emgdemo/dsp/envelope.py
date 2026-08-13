"""Moving-average envelope in constant time per sample."""

from __future__ import annotations

from collections import deque

import numpy as np


class RunningMean:
    """Trailing mean over a fixed window, maintained by a running sum.

    The demo previously called ``np.mean`` over the whole window on every sample, three
    times over, which dominated its CPU cost.
    """

    def __init__(self, window_samples: int):
        self.window_samples = max(1, int(window_samples))
        self._buffer: deque[float] = deque()
        self._total = 0.0

    def step(self, sample: float) -> float:
        sample = float(sample)
        self._buffer.append(sample)
        self._total += sample

        if len(self._buffer) > self.window_samples:
            self._total -= self._buffer.popleft()

        return self._total / len(self._buffer)

    def step_block(self, block: np.ndarray) -> np.ndarray:
        """Trailing means for a whole batch, via one prefix sum.

        Before the window has filled, each output averages only the samples seen so far,
        exactly as the per-sample path does.
        """
        block = np.asarray(block, dtype=np.float64)
        if block.size == 0:
            return block

        window = self.window_samples
        held = np.fromiter(self._buffer, dtype=np.float64, count=len(self._buffer))
        combined = np.concatenate([held, block])

        prefix = np.concatenate([[0.0], np.cumsum(combined)])
        end = held.size + np.arange(block.size)
        available = np.minimum(window, held.size + np.arange(1, block.size + 1))
        start = end + 1 - available

        means = (prefix[end + 1] - prefix[start]) / available

        keep = combined[-window:]
        self._buffer = deque(keep, maxlen=window)
        self._total = float(keep.sum())

        return means

    def reset(self) -> None:
        self._buffer.clear()
        self._total = 0.0
