# EMG Signal Processing & Digital Twin Gripper

End-to-end EMG (Electromyography) acquisition and processing pipeline for prosthetic control research, with:
- ESP32 + MyoWare data capture firmware
- Multi-stage EMG filtering and feature extraction
- Frequency-domain analysis tools
- Digital twin gripper visualization
- Synthetic-data mode for testing without hardware

This repository is ready for local experimentation, demos, and dissertation/research workflows.

---

## Repository Contents

### Core Python Modules
- `main_pipeline.py` — Main CLI entrypoint (acquire/load/process/test).
- `emg_signal_processor.py` — EMGProcessor class with filters, envelope, SNR, features, and control detection.
- `frequency_analyzer.py` — FFT/PSD analysis and frequency-response plotting.
- `digital_twin_gripper.py` — Gripper simulation and visualization dashboard.
- `emg_filters.py` — Reusable filter presets (`default`, `aggressive`, `balanced`, etc.).

### Firmware
- `myoware_acquisition.ino` — ESP32 firmware for 1 kHz EMG acquisition and serial CSV streaming.

### Data / Outputs
- `EMGdataset/dataset/raw_signals/` — Raw volunteer CSV data.
- `EMGdataset/dataset/filtered_signals/` — Pre-filtered volunteer CSV data.
- `results/` — Generated plots and summaries from pipeline runs.

### Documentation
- `docs/EMG_Setup_Guide.md` — Hardware setup and troubleshooting.
- `docs/TESTING_GUIDE.md` — Validation/testing procedures.
- `docs/Guidance.md` and `docs/COMPLETE SYSTEM SUMMARY.md` — Extended reference notes.
- `CONTRIBUTING.md` — Contribution workflow and pre-PR validation.

---

## System Pipeline

Typical processing chain:
1. Notch filtering (power-line rejection)
2. Bandpass filtering (EMG band isolation)
3. Rectification
4. Low-pass smoothing
5. Envelope extraction
6. Feature extraction + control interpretation
7. Visualization + export

---

## Requirements

- Python 3.9+
- Windows/macOS/Linux
- Optional (live mode):
  - ESP32 board
  - MyoWare sensor + electrodes
  - Serial connection to host machine

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Quick Start

### 1) Run without hardware (synthetic data)

```bash
python main_pipeline.py --mode synthetic
```

Optional parameters:

```bash
python main_pipeline.py --mode synthetic --duration 10 --snr 8 --preset balanced --output ./results
```

### 2) Process a specific CSV file

```bash
python main_pipeline.py --mode load --file path/to/file.csv --preset default --output ./results
```

### 3) Load bundled volunteer dataset

```bash
python main_pipeline.py --mode load --volunteer 1 --dataset-source raw --preset balanced
```

- `--dataset-source` options: `raw`, `filtered`
- `--channel` can select a channel in multichannel CSVs (name or index)

### 4) Live acquisition from ESP32

```bash
python main_pipeline.py --mode live --port COM3 --duration 10 --preset balanced
```

---

## Useful CLI Options

```text
--mode {synthetic,live,load}
--test {all,synthetic,stability,serial,real}
--preset <name>
--list-presets
--analyze-filtered
--output <dir>
```

Show available presets:

```bash
python main_pipeline.py --list-presets
```

Run built-in checks:

```bash
python main_pipeline.py --test all
```

---

## Output Files

A standard run writes artifacts into `results/` (or your chosen `--output`):
- `01_emg_processing_pipeline.png`
- `02_filter_frequency_response.png`
- `03_gripper_control.png`
- `04_filtered_signal_frequency_analysis.png` (when `--analyze-filtered` is enabled)
- `results_summary.csv`

---

## ESP32 Firmware Notes

`myoware_acquisition.ino` is configured for:
- 1 kHz sampling
- 12-bit ADC reads
- CSV serial output (`timestamp_ms,adc_raw_value`)
- High baud rate (921600)

Default signal pin is GPIO 34 (ADC1). Ensure firmware settings match Python serial settings.

---

## Suggested Workflow

1. Validate software path first (`--mode synthetic`).
2. Run serial test (`--test serial`) before recording live sessions.
3. Record short sessions (5–10 s) and inspect generated plots.
4. Tune/compare presets in `emg_filters.py` for your experiment goals.
5. Track results folders per run for reproducibility.

---

## Project Structure

```text
.
├─ main_pipeline.py
├─ emg_signal_processor.py
├─ frequency_analyzer.py
├─ digital_twin_gripper.py
├─ emg_filters.py
├─ myoware_acquisition.ino
├─ EMGdataset/
│  └─ dataset/
│     ├─ raw_signals/
│     └─ filtered_signals/
├─ results/
└─ docs/
```

---

## Reproducibility Tips

- Keep filter preset and CLI args logged per run.
- Save outputs to a timestamped folder via `--output`.
- Avoid editing raw datasets in place.
- Pin Python package versions if sharing across machines.

---

## License

This project is licensed under the MIT License. See `LICENSE`.

## Contributing

See `CONTRIBUTING.md` for setup, validation steps, and pull request guidance.
