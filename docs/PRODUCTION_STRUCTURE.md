# Production Repository Structure

This repository is organized for maintainability, operational safety, and exhibition reliability.

## Top-Level Layout

- `public_engagement_demo.py` - live public demo application
- `main_pipeline.py` - batch/offline processing entry point
- `firmware/` - ESP32 firmware grouped by transport mode
- `scripts/` - operator launch scripts by platform
- `configs/` - runtime configuration artifacts
- `operations/` - operational outputs and run-time assets
- `docs/` - setup guides, runbooks, and checklists

## Firmware Layout

- `firmware/esp32/myoware_serial_acquisition/myoware_serial_acquisition.ino`
- `firmware/esp32/myoware_ble_acquisition/myoware_ble_acquisition.ino`

Design rule: each sketch lives in its own folder with matching `.ino` name.

## Script Layout

- `scripts/windows/run_demo.bat`
- `scripts/windows/run_demo_emulated.bat`
- `scripts/windows/run_demo_debug.bat`
- `scripts/windows/run_demo_ble_auto.bat`

Root-level batch files are compatibility wrappers only.

## Config + Operations

- `configs/demo/` - durable config files (`demo_ble_config.json` etc.)
- `operations/logs/` - event logs and incident traces
- `operations/snapshots/` - curated snapshots for reporting

## Documentation Set

- `docs/ESP32_BLE_SETUP_GUIDE.md` - board wiring, flashing, and BLE validation
- `docs/EXPO_RUN_CHECKLIST.md` - event-day process and incident playbook
- `docs/PUBLIC_DEMO_GUIDE.md` - demo behavior and operator commands

## Production Conventions

1. Keep firmware transport-specific (serial vs BLE) in separate folders.
2. Keep launcher scripts platform-scoped under `scripts/<platform>/`.
3. Keep config separate from source code.
4. Keep operations outputs outside code paths.
5. Preserve backward-compatible wrappers for operator convenience.
