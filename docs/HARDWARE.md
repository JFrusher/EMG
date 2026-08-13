# Hardware

Everything the code cannot tell you: what to wire where, where to stick the electrodes,
and how to get firmware onto the board.

## Bill of materials

- ESP32 DevKit (ESP32-WROOM Dev Module)
- MyoWare 2.0 muscle sensor
- EMG electrode pads and cables
- USB **data** cable — power-only cables are the most common cause of a board that
  will not flash
- Optional: USB power bank, for an untethered BLE stand

## Wiring

| MyoWare | ESP32 |
|---|---|
| `VCC` (red) | `3V3` |
| `GND` (black) | `GND` |
| `SIG` (white) | `GPIO34` |

**Use an ADC1 pin.** GPIO 32–39 are ADC1; ADC2 (GPIO 0, 2, 4, 12–15, 25–27) stops
working the moment Wi-Fi or BLE is active, which is exactly when you need it.

Keep the sensor cable short, route it away from power leads and laptop chargers, and add
strain relief so a tug on the cable does not pull an electrode off mid-demo.

## Electrodes

1. Clean the skin with an alcohol wipe and let it dry.
2. Reference pad on a bony, low-activity area away from the muscle.
3. Active pads along the muscle fibre direction — one at the muscle belly, one further
   along the fibre.
4. Wait 20–30 seconds for the contact to settle before judging the signal.

A drifting baseline usually means a drying or lifting electrode, not a software problem.

## Firmware

Two sketches, both in `firmware/esp32/`:

- `myoware_ble_acquisition/` — wireless, what a stand normally runs
- `myoware_serial_acquisition/` — USB fallback, easier to debug

### Flashing

Arduino IDE 2.x, ESP32 board package by Espressif:

- Board: `ESP32 Dev Module`
- CPU frequency: 240 MHz
- Upload speed: 921600 (drop to 460800 if uploads fail)
- Partition scheme: default

No third-party libraries — the BLE sketch uses the ESP32 built-in stack
(`BLEDevice.h`, `BLEServer.h`, `BLEUtils.h`, `BLE2902.h`).

Open the sketch, confirm board and COM port, Verify, Upload. Open the Serial Monitor at
115200 and confirm the startup lines naming the device and its UUIDs.

If upload fails: hold **BOOT** during upload, lower the upload speed, then change the
USB cable.

## What the sketches emit

**Acquisition** — 1 kHz sampling, 12-bit ADC (0–4095), 0–3.3 V input range.

**BLE**
- Device name `MYOWARE_EMG`
- Service UUID `4fafc201-1fb5-459e-8fcc-c5c9c331914b`
- Notify characteristic `beb5483e-36e1-4688-b7f5-ea07361b26a8`
- Payload: packed little-endian `uint16` ADC counts

**Serial** — CSV at 921600 baud, `timestamp_ms,adc_raw_value`.

The demo also accepts a dual-pad stream: `timestamp,pad_a,pad_b`, where pad A closes the
gripper and pad B opens it. A two-field line is always read as the legacy
`timestamp,adc` form.

## Connecting the demo to it

```bash
emg-demo --source ble --ble-name MYOWARE          # wireless
emg-demo --source serial --port COM3              # USB
```

BLE requires a name, address or service UUID. It will not pick a device for you — at a
public event the nearest unnamed device is somebody's headphones.

If the sample rate the board delivers is not 1 kHz, say so in a profile
(`[settings] sample_rate_hz = ...`); the filters are designed from the measured rate, and
the demo will tell you in its event log when it retunes.
