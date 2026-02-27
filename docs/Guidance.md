# EMG Processor — Usage Guide ✅

**Purpose:** This document explains how to use the EMG processing utilities in this repo (programmatic API and CLI), with concrete examples, notes about CSV formats, and troubleshooting tips. Use it as a quick reference for loading data, building filter chains, running the processing pipeline, visualizing outputs, and performing frequency analysis.

---

## Table of contents
- Quick start (CLI & code)
- EMGProcessor overview
- Loading data (CSV / dataset)
  - Selecting a channel
  - Concatenating channels
- Synthetic data generation
- Filter chain API
  - Factory helpers
  - Example chains
- Full pipeline example (programmatic)
- CLI examples (`main_pipeline.py`)
- Frequency analyzer notes
- Troubleshooting & tips
- Appendix: file locations and CSV expectations

---

## Quick start

### Run the full pipeline for volunteer 1 via CLI
```bash
# Load volunteer 1 (raw dataset), use channel name, show results
python main_pipeline.py --mode load --volunteer 1 --dataset-source raw --channel "HandOpen" --output results/

# Run synthetic test (10 s, SNR 10 dB)
python main_pipeline.py --mode synthetic --duration 10 --snr 10 --output results/
```

### Minimal programmatic example
```python
from emg_signal_processor import EMGProcessor, make_notch, make_butter_bandpass

proc = EMGProcessor(sampling_rate=1000)
proc.load_from_dataset(dataset_dir='EMGdataset/dataset/raw_signals', volunteer_id=1, channel='HandOpen')

# Add standard filters
proc.clear_filters()
proc.add_filter(make_notch(50, q=30))
proc.add_filter(make_butter_bandpass(20, 400, order=4))

# Run pipeline
proc.apply_filter_chain()
proc.apply_rectification()
proc.extract_envelope(window_ms=200)
proc.detect_peaks_and_control()

# Visualize and save
proc.visualize_all(save_path='results/volunteer1_pipeline.png')
```

---

## EMGProcessor — overview

`EMGProcessor` is the central class to load, preprocess, filter, analyze, and visualize EMG signals. Key attributes and helpers:
- `raw_data` — loaded raw signal (1D numpy array). May be a concatenation of multiple channels.
- `time` — time vector aligned to `raw_data` (seconds).
- `sampling_rate` — sampling frequency (Hz). Ensure this is set correctly for your data (many scripts assume 1000 Hz unless otherwise set).
- `filtered_stages` — dict mapping descriptive stage names to numpy arrays (results of each filter step).
- `envelope` — envelope extracted from rectified signal.
- `peaks` — detected peak indices (integers) in the envelope.
- `channel_order` and `channel_segments` — metadata when multiple channels are concatenated; `channel_segments` is a list of tuples `(name, start_idx, end_idx)` so you can map samples to original channels.

Primary methods:
- `load_from_dataset(dataset_dir=..., source='raw', volunteer_id=None, filename=None, channel=None, voltage_range=3.3)` — robust CSV loader.
- `generate_synthetic_data(...)` — create synthetic EMG traces for testing.
- `add_filter(filter_spec)` / `clear_filters()` / `get_filter_summary()` — manage the filter chain.
- `apply_filter_chain()` — apply configured filters in order.
- `apply_rectification()` / `extract_envelope(window_ms=...)` — rectification + smoothing to get envelope.
- `detect_peaks_and_control()` — auto-detect activation peaks and optional control commands.
- `visualize_all(save_path=None)` — adaptive plotting for the pipeline; shows filters, channel boundaries, envelope+peaks.

---

## Loading data

### Loading from the dataset folder
`load_from_dataset` will select a file based on `volunteer_id` or `filename`. Behavior:
- It ignores likely *index/time* columns automatically (`Unnamed: *`, `timestamp*`, `time`, `index`, or a pure 0..N-1 first column).
- If you pass `channel='HandOpen'`, it will load that named column; if you pass an integer, it will use that numeric column index.
- If `channel=None`, numeric channels are concatenated end-to-end; `self.channel_segments` records sample ranges and names.

Example:
```python
proc.load_from_dataset(volunteer_id=1, dataset_dir='EMGdataset/dataset/raw_signals', channel='HandOpen')
```

### Concatenated channels: understanding `channel_segments`
When `channel=None` and multiple numeric columns exist, the loader concatenates them. After loading you can inspect:
```python
print(proc.channel_order)
print(proc.channel_segments)
# channel_segments -> list like [('HandOpen', 0, 5467), ('HandClose', 5468, 10935), ...]
```
Use these indices to locate time ranges for each original channel.

---

## Synthetic data
Use `generate_synthetic_data()` to create controlled signals (SNR, duration, sampling rate). Helpful for quick tests when hardware is not connected.

```python
proc.generate_synthetic_data(duration_seconds=5, snr_db=10, amplitude=1.0)
proc.visualize_all()
```

---

## Filter chain API 🔧
You can build a chain of filters in order. Use the factory helper functions (preferred) or pass dict specs.

Factory helpers (examples):
```python
make_notch(freq=50, q=30)
make_butter_bandpass(lowcut=20, highcut=400, order=4)
make_butter_lowpass(cutoff=150, order=3)
make_butter_highpass(cutoff=20, order=3)
make_moving_average(window_ms=200)
```

Add filters:
```python
proc.clear_filters()
proc.add_filter(make_notch(50, q=30))
proc.add_filter(make_butter_bandpass(20, 400, order=4))
proc.apply_filter_chain()
```
The names of the stages are descriptive (e.g., `notch_50Hz_Q30`, `bandpass_20-400_o4`) and appear in `proc.filtered_stages` and in the plot summary.

---

## Full pipeline (recommended pattern)
1. Load or generate data
2. Configure filters (or leave defaults)
3. Apply filters
4. Rectify and extract envelope
5. Detect peaks, optionally map to control commands
6. Visualize and save outputs

Example snippet:
```python
proc = EMGProcessor(sampling_rate=1000)
proc.load_from_dataset(volunteer_id=1, channel=None)  # loads and concatenates all channels
proc.clear_filters()
proc.add_filter(make_notch(50, q=30))
proc.add_filter(make_butter_bandpass(20, 400, order=4))
proc.apply_filter_chain()
proc.apply_rectification()
proc.extract_envelope(window_ms=200)
proc.detect_peaks_and_control()
proc.visualize_all(save_path='results/volunteer1_all_channels.png')
```

Want to process each channel independently? Use `proc.channel_segments` to slice `proc.raw_data` by channel and run the pipeline per channel (example below).

```python
for name, start, end in proc.channel_segments:
    seg_raw = proc.raw_data[start:end]
    # create small EMGProcessor or set attributes and repeat the pipeline
```

---

## CLI examples (`main_pipeline.py`) 🖥️
- Load volunteer 1 and save results:
```bash
python main_pipeline.py --mode load --volunteer 1 --dataset-source raw --channel "HandOpen" --output results/
```

- Run a synthetic run (SNR and duration):
```bash
python main_pipeline.py --mode synthetic --duration 10 --snr 10 --output results/
```

Notes:
- Use `--channel` to pass channel name or numeric index to the loader.
- Use `--dataset-source` to select `raw` or `filtered` dataset directories.
- Use `--preset` to apply a filter preset defined in `emg_filters.PRESETS` (e.g. `default`, `aggressive`, `none`).
- Use `--list-presets` to print available presets and exit.
- Use `--analyze-filtered` to run a dedicated frequency analysis (PSD/FFT) on the *filtered signal just before the envelope* (rectified stage if present, otherwise the last filtered stage). A PNG named `04_filtered_signal_frequency_analysis.png` will be saved to the output folder when this flag is used. An initial frequency analysis on the raw signal is also run automatically and saved as `00_raw_signal_frequency_analysis.png` for comparison.

- The `04_filtered…` analysis will include a short visible annotation listing the filters used so you can compare the effect of the filter chain on the frequency content.
Note: Moving-average smoothing filters are *time-domain* operations used for envelope extraction and are **omitted** from the filter FRF plot. If your chain only contains moving-average smoothing, the filter FRF figure will be skipped.

---

## Presets — How to use `emg_filters` (over-explained) 🔧

This project includes a simple, central place to configure and **stack** filter operations called `emg_filters.py`.

Why use presets?
- Keeps your filter choices version-controlled and easy to edit in one place.
- Lets you run the CLI with a single `--preset` flag (no need to re-edit the pipeline code).
- Makes experiments reproducible: name the preset and the same filter stack will be applied each run.

Step-by-step: Create or edit a preset
1. Open `d:\EMG\emg_filters.py` in your editor.
2. Each preset is a Python function that accepts one argument `processor` (an `EMGProcessor` instance).
3. Inside the function, call `processor.clear_filters()` then `processor.add_filter(...)` for each filter you want, using the factory helpers such as `processor.make_notch(...)` and `processor.make_butter_bandpass(...)`.
4. Return the `processor` (convention; the pipeline uses the mutated processor in-place).

Minimal example (to add in `emg_filters.py`):
```python
def my_favourite(processor):
    processor.clear_filters()
    processor.add_filter(processor.make_notch(50, q=30))
    processor.add_filter(processor.make_butter_bandpass(20, 400, order=4))
    return processor
```

How to run a preset from the CLI
- List available presets:
```bash
python main_pipeline.py --list-presets
```

- Run processing with a named preset:
```bash
python main_pipeline.py --mode load --volunteer 1 --preset my_favourite
```

Tips and best practices
- Keep preset names meaningful (e.g., `default`, `aggressive`, `envelope_only`).
- If you want to test different chains quickly, add several presets and use `--list-presets` to discover them.
- The `process_emg_data(...)` function will print the preset being applied — check the stdout to confirm.

If you'd like, I can add a short test `--test presets` option that runs each preset on a short synthetic trace and writes a small summary image per preset.


---

## Frequency analyzer notes
The `frequency_analyzer` utilities attempt to ignore index/time columns and select the best numeric column to analyze (prioritizing `adc_raw_value` or `voltage`, then highest variance). Example usage:
```python
from frequency_analyzer import load_csv, compute_fft
signal = load_csv('EMGdataset/dataset/raw_signals/volunteer_1.csv')  # picks a signal column and prints choice
# then use compute_fft(signal...) to inspect PSD
```

---

## Troubleshooting & tips ⚠️
- Index/time columns: If a dataset contains an index/time column (e.g., `Unnamed: 0`), the loader will attempt to drop it. If you see odd behavior, inspect the CSV header and pass `channel` explicitly.
- Channel selection: If `channel=None`, channels are concatenated; use `channel='Name'` or an integer index to select a single channel.
- Sampling rate: Confirm `proc.sampling_rate` matches your actual recording hardware. Plotting and FFT use this value.
- Empty peaks: `detect_peaks_and_control()` produces integer `proc.peaks`. If empty, check envelope values and threshold configuration.
- Filter chain: If filters appear not to apply, call `proc.get_filter_summary()` to confirm the order and parameters.

---

## Appendix: file locations & CSV expectations
- Raw dataset folder: `EMGdataset/dataset/raw_signals/`
- Filtered dataset folder: `EMGdataset/dataset/filtered_signals/`
- Typical CSV layout (multi-channel):
  - Optional index column (e.g. `Unnamed: 0`)
  - Named channels: `HandOpen`, `HandClose`, `Wrist Flexion`, `Wrist Extension`, `Supination`, `Pronation`, `Rest`
