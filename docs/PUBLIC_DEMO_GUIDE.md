# Public Engagement Demo Guide

This guide explains how to run the real-time EMG demonstrator for exhibitions, outreach sessions, and participant-facing demos.

## What the Demo Shows

The live dashboard presents:
- Stage-by-stage scrolling EMG signal transformation
  - Raw
  - Notch filtered
  - Bandpass filtered
  - Rectified
  - Low-pass smoothed
  - Envelope
- Event detection timeline (activation events)
- Mock gripper visualization with live force/gesture state (gripper UI mode)
- Live numerical debug console with action buttons (debug UI mode)
- Live "Noise Reduction vs Raw" metrics so audiences can see filter benefit numerically, not just visually

## Launch Commands

From repository root:

```bash
pip install -r requirements.txt
```

Windows one-click launchers:
- `run_demo.bat` (synthetic + gripper UI)
- `run_demo_emulated.bat` (dataset replay loop + gripper UI)
- `run_demo_debug.bat` (dataset replay loop + debug UI)

### Synthetic mode (safe default)

```bash
python public_engagement_demo.py --source synthetic
```

### Serial mode (ESP32 via USB)

```bash
python public_engagement_demo.py --source serial --port COM3 --baud 921600
```

### BLE mode (dry EMG wearable)

```bash
python public_engagement_demo.py --source ble --ble-address XX:XX:XX:XX:XX:XX --ble-char 0000ffe1-0000-1000-8000-00805f9b34fb
```

### Dataset replay mode (live emulation)

Sequential playback across all files:

```bash
python public_engagement_demo.py --source dataset --dataset-source raw --replay-speed 1.0
```

Continuous loop mode:

```bash
python public_engagement_demo.py --source dataset --dataset-source raw --replay-speed 1.0 --replay-loop
```

### Debug UI mode (replaces gripper panel)

```bash
python public_engagement_demo.py --source dataset --dataset-source raw --replay-loop --ui-mode debug
```

Debug controls in-panel:
- `Pause` / `Resume` processing
- `Reset` event log and counters
- `Snapshot` save current screen into `results/`
- `AutoScale` dynamic y-axis scaling for stage plots

### Dual-pad directional control mode

Use two dry-EMG pads (one each side of forearm):
- Left/side A pad controls **close** direction
- Right/side B pad controls **open** direction
- The **sum** of both channels drives the main stage plots (raw → envelope)

Example with dataset channel names:

```bash
python public_engagement_demo.py --source dataset --dataset-source raw --side-a-channel HandClose --side-b-channel HandOpen --replay-loop --ui-mode gripper
```

The gripper panel now includes bilateral pad-amplitude bars and logs **co-contraction events** when both sides are active together.

Notes:
- `--dataset-source raw|filtered` switches folder.
- `--dataset-channel` can target one channel/column in multichannel CSV files.
- Without `--dataset-channel`, multichannel files are averaged per row to create a single demo stream.
- `--ui-mode gripper|debug` selects right-side panel type.

## Fallback Strategy

- Default behavior: if BLE or Serial cannot initialize, the app falls back to synthetic mode.
- Use strict mode to force the selected source:

```bash
python public_engagement_demo.py --source ble --strict-source --ble-address <ADDR> --ble-char <CHAR_UUID>
```

## Tuning for Different Participants

You can adjust event sensitivity:

```bash
python public_engagement_demo.py --source synthetic --event-high 0.25 --event-low 0.18
```

Guideline:
- Lower thresholds = easier event triggering.
- Keep `event-low` below `event-high` to preserve hysteresis stability.

## Operational Tips for Public Sessions

- Start with synthetic mode first (verifies display and pipeline instantly).
- Keep a serial fallback ready if BLE pairing is unstable in crowded RF spaces.
- Explain the panel top-to-bottom: raw bio-signal to control envelope to gripper action.
- Use short participant activations (0.5–2 s) for clear event markers.
- Narrate the "Noise Reduction vs Raw" values as a running scorecard: values moving positive indicate cleaner signal and clearer control intent.

## Troubleshooting

- No BLE connection:
  - Verify address and characteristic UUID.
  - Confirm the device is advertising notifications.
  - Try synthetic mode to ensure UI remains operational.
- No serial data:
  - Check COM port and baud rate.
  - Confirm firmware emits `timestamp_ms,adc_raw_value` lines.
- Plot appears static:
  - Ensure source is delivering samples (status line will show waiting/throughput).

## Architecture Notes

The demo is intentionally modular in `public_engagement_demo.py`:
- Input sources are pluggable classes (`BLEEMGSource`, `SerialEMGSource`, `SyntheticEMGSource`, `DatasetReplaySource`).
- Processing is encapsulated in `StreamingEMGPipeline`.
- UI and event logic are independent from source transport.

This design makes hot-swapping emulators, filters, or output widgets straightforward.
