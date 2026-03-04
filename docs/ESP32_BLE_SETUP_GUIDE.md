# ESP32 + MyoWare BLE Setup Guide (Production)

This guide is the definitive setup workflow for building and deploying the BLE EMG sensor node for live public demos.

## 1) Hardware Bill of Materials

- ESP32 DevKit (recommended: ESP32-WROOM Dev Module)
- MyoWare 2.0 Muscle Sensor
- EMG electrode pads + cables
- USB data cable for ESP32
- Laptop running this repository
- Optional: USB power bank (for untethered demos)

## 2) Wiring (Safe + Stable)

Use only ADC1 pins with BLE/Wi-Fi active.

- MyoWare `VCC` -> ESP32 `3V3`
- MyoWare `GND` -> ESP32 `GND`
- MyoWare `SIG` -> ESP32 `GPIO34` (ADC1)

Recommended physical practices:

- Keep sensor-to-board cable short.
- Route signal wire away from power wires and laptop chargers.
- Add strain relief so cable pull does not tug electrodes.
- Tape exposed conductor joints.

## 3) Electrode Placement

- Clean skin with alcohol wipe; let dry.
- Place reference pad over a bony/low-activity area.
- Place active electrodes along muscle fiber direction.
- Wait 20-30 seconds for contact to settle before testing.

## 4) Arduino IDE / PlatformIO Setup

### Arduino IDE

1. Install Arduino IDE 2.x.
2. Install ESP32 board package by Espressif.
3. Board: `ESP32 Dev Module`.
4. CPU Frequency: 240 MHz.
5. Upload Speed: 921600 (or 460800 if unstable).
6. Partition Scheme: default.

### Required Libraries

The BLE firmware uses ESP32 built-in BLE stack headers:

- `BLEDevice.h`
- `BLEServer.h`
- `BLEUtils.h`
- `BLE2902.h`

No third-party sensor library is required.

## 5) Firmware Location and Intent

Primary BLE firmware:

- `firmware/esp32/myoware_ble_acquisition/myoware_ble_acquisition.ino`

Serial fallback firmware:

- `firmware/esp32/myoware_serial_acquisition/myoware_serial_acquisition.ino`

## 6) Compile + Flash Procedure

1. Open `firmware/esp32/myoware_ble_acquisition/myoware_ble_acquisition.ino`.
2. Confirm board and COM port.
3. Click Verify.
4. Click Upload.
5. Open Serial Monitor at `115200` and confirm startup lines:
   - device name
   - service UUID
   - characteristic UUID

If upload fails:

- Hold BOOT on ESP32 while uploading.
- Try lower upload speed.
- Change USB cable (power-only cables are common failure source).

## 7) BLE Pairing + Laptop Validation

From repo root:

```bash
python ble_demo_setup.py --ble-device-name MYOWARE --config demo_ble_config.json
```

Expected output:

- BLE setup successful
- Device address resolved
- Characteristic resolved
- Notifications and sample rate detected

## 8) Runtime Commands

### One-click (recommended)

```bat
run_demo_ble_auto.bat
```

### Manual

```bash
python public_engagement_demo.py --source ble --ble-config demo_ble_config.json --ui-mode gripper
```

## 9) Reliability Settings (for long sessions)

Use recovery controls during long events:

```bash
python public_engagement_demo.py --source ble --runtime-recovery --source-stall-timeout 6 --source-restart-cooldown 4 --source-max-restarts 5
```

Interpretation:

- If BLE stalls, app attempts source restart.
- After max restart attempts, app fails over to synthetic mode to keep display alive.

## 10) Safety + Operational Notes

- EMG demo is non-diagnostic and non-medical.
- Do not use on broken or irritated skin.
- Do not reuse single-use pads across participants.
- Disinfect reusable surfaces between participants.
- Keep liquids away from laptop and ESP32.

## 11) Troubleshooting Matrix

### No BLE device found

- Check ESP32 power and serial startup output.
- Confirm firmware flashed successfully.
- Move away from heavy RF congestion.

### Notifications found but unstable stream

- Reduce distance between ESP32 and laptop.
- Disable aggressive USB power saving on laptop.
- Ensure electrodes have firm contact.

### High noise / poor response

- Re-clean skin and replace pads.
- Reposition reference electrode.
- Minimize participant cable movement.

### Demo keeps recovering to synthetic

- Inspect live status text in UI.
- Increase `--source-stall-timeout` to 8-10 in noisy conditions.
- Keep serial firmware ready as fallback path.
