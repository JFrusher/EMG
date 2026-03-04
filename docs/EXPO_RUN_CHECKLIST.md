# Expo Run Checklist (EMG Public Demo)

Use this checklist on event day for predictable, safe operation.

## A) T-60 min: Bench Preflight

- [ ] Laptop fully charged + power adapter available
- [ ] Python environment activates and dependencies installed
- [ ] `python -m pip show bleak pyserial` confirms packages
- [ ] ESP32 boots and shows BLE startup lines in serial monitor
- [ ] `python ble_demo_setup.py --ble-device-name MYOWARE --config demo_ble_config.json` succeeds
- [ ] `run_demo_ble_auto.bat` starts and shows live updates
- [ ] Synthetic fallback path confirmed (disconnect ESP32 briefly)
- [ ] Snapshot saving works into `results/`

## B) T-30 min: Station Setup

- [ ] Board physically secured (no cable strain)
- [ ] Cables taped/managed; no trip hazards
- [ ] Spare electrodes ready
- [ ] Cleaning wipes + spare USB cable available
- [ ] Signage explains non-medical demo intent

## C) T-15 min: Signal Quality Check

- [ ] Electrode placement validated on operator
- [ ] Activation events visible in UI event log
- [ ] Gripper response smooth and repeatable
- [ ] No prolonged "waiting for samples" state
- [ ] Source status indicates healthy BLE stream

## D) Live Operation Procedure

1. Start with `run_demo_ble_auto.bat`.
2. Confirm status line updates with sample rate.
3. Briefly explain raw -> filtered -> envelope -> control flow.
4. Guide participant through short contractions (0.5 to 2 s).
5. Recalibrate with in-UI `Calibrate` button when participant changes.

## E) Live Incident Playbook

### BLE dropout (temporary)

- [ ] Wait for auto-recovery (watch status line)
- [ ] If recoveries exceed 2-3, power-cycle ESP32 once
- [ ] Continue in synthetic fallback if audience flow must continue

### Signal too noisy

- [ ] Replace pads
- [ ] Re-clean skin
- [ ] Re-seat reference electrode
- [ ] Re-run calibration

### Application stutter

- [ ] Relaunch with `--lightweight-mode`
- [ ] Close background heavy applications

## F) Session Handover Between Participants

- [ ] Pause demo briefly
- [ ] Replace/adjust electrodes
- [ ] Clean contact surfaces
- [ ] Run quick 10-second calibration
- [ ] Resume and verify event detection

## G) End-of-Day Shutdown

- [ ] Save final snapshots if required
- [ ] Stop demo and disconnect hardware
- [ ] Archive logs/screenshots into dated folder
- [ ] Note failures and mitigations for next event

## H) Recommended Command Profiles

### Standard expo profile

```bash
python public_engagement_demo.py --source ble --runtime-recovery --source-stall-timeout 6 --source-restart-cooldown 4 --source-max-restarts 5 --ui-mode gripper
```

### High interference venue profile

```bash
python public_engagement_demo.py --source ble --runtime-recovery --source-stall-timeout 8 --source-restart-cooldown 5 --source-max-restarts 6 --ui-mode gripper --lightweight-mode
```

### Emergency continuity profile

```bash
python public_engagement_demo.py --source synthetic --ui-mode gripper
```

## I) Team Roles (Optional but Recommended)

- **Operator**: Talks through UI and guides participant actions.
- **Spotter**: Watches status/event lines and handles electrode changes.
- **Tech backup**: Handles ESP32 reset and command relaunch if needed.
