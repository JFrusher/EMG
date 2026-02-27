"""
EMG filter presets module

Edit or add functions here to configure an EMGProcessor instance with a stack
of filters. Preset functions accept a `processor` instance and should call its
factory helpers (e.g., `processor.make_notch`, `processor.make_butter_bandpass`)
through `processor.add_filter(...)` or call the convenience helpers.

Add new presets to the PRESETS dict below so they are discoverable via CLI
`--list-presets` and usable via `--preset NAME`.
"""

from typing import Callable


def default(processor):
    """A sensible default for EMG: Notch 50 Hz, Bandpass 20-400 Hz."""
    processor.clear_filters()
    processor.add_filter(processor.make_notch(50, q=30))
    processor.add_filter(processor.make_butter_bandpass(20, 400, order=4))
    return processor


def aggressive(processor):
    """Stronger filtering: higher high-pass and a tighter notch."""
    processor.clear_filters()
    processor.add_filter(processor.make_butter_highpass(30, order=6))
    processor.add_filter(processor.make_butter_lowpass(400, order=4))
    processor.add_filter(processor.make_notch(50, q=40))
    processor.add_filter(processor.make_moving_average(100.0))
    return processor


def none(processor):
    """No filters applied."""
    processor.clear_filters()
    return processor


def envelope_only(processor):
    """Minimal chain: only rectify and moving average envelope (no high/low filtering)."""
    processor.clear_filters()
    processor.add_filter(processor.make_moving_average(200.0))
    return processor

def balanced(processor):
    """
    RECOMMENDED - Best for your dissertation data
    """
    processor.clear_filters()
    processor.add_filter(processor.make_butter_highpass(2, order=2))      # Remove DC (44% of power)
    processor.add_filter(processor.make_butter_bandpass(20, 150, order=2)) # Keep primary EMG
    processor.add_filter(processor.make_notch(50, q=25))                  # Remove powerline
    processor.add_filter(processor.make_moving_average(200.0))            # Smooth envelope
    return processor


PRESETS = {
    'default': default,
    'aggressive': aggressive,
    'none': none,
    'envelope_only': envelope_only,
    'balanced': balanced
}


# ---------------------------------------------------------------------------
# Convenience helpers for programmatic use
# ---------------------------------------------------------------------------

def get_preset_names():
    """Return a list of available preset names (helpful for UIs/automation)."""
    return list(PRESETS.keys())


def apply_preset(processor, name: str):
    """Apply a preset by name to the given `processor` instance.

    Raises KeyError if preset not found. Returns the processor instance for chaining.
    Example:
        p = EMGProcessor(sampling_rate=1000)
        apply_preset(p, 'default')
    """
    fn = PRESETS.get(name)
    if fn is None:
        raise KeyError(f"Preset not found: {name}. Available: {list(PRESETS.keys())}")
    return fn(processor)


# End of file

