# Event day

## T-60 — bench check

- [ ] Laptop charged, adapter packed
- [ ] `uv run emg-demo --profile dev` comes up and animates
- [ ] `uv run pytest` passes
- [ ] ESP32 boots; startup lines visible in the Serial Monitor
- [ ] `emg-demo --source ble --ble-name MYOWARE` connects and streams
- [ ] Pull the ESP32's power mid-run: the banner goes amber, then falls over to
      synthetic within about twenty seconds. It should never go blank
- [ ] Spare electrodes, spare USB cable, alcohol wipes packed

## T-30 — station

- [ ] Board secured, no cable strain, nothing to trip over
- [ ] Screen angled away from direct light
- [ ] `uv run emg-demo --profile expo --fullscreen`
- [ ] Click once on the page to take it fullscreen (browsers only allow this from a
      click or keypress). Controls hide and the cursor disappears

## Per participant

1. Clean skin, place electrodes (see [HARDWARE.md](HARDWARE.md))
2. Wait 20–30 s for contact to settle
3. Press **Calibrate** — ask them to rest, then squeeze, for the four seconds
4. Let them drive the hand

Calibration is per person. Press it again for the next one.

## Keys

| Key | Does |
|---|---|
| `F` | Fullscreen on/off |
| `Space` | Pause / resume |
| `C` | Calibrate |
| `R` | Reset counters and log |

## When something goes wrong

**Banner amber, "reconnecting"** — the source dropped. It retries three times, then
switches to synthetic and keeps running. Check the cable; restart the demo when there's
a gap in the queue.

**Banner amber, "Synthetic (failover)"** — it already gave up on the hardware. The demo
is still correct, it just isn't reading anyone's muscle. Fix at the next lull.

**Hand stays clamped shut** — the grip integrator holds position when neither pad is
active, which is how a real prosthesis behaves. It releases when the open pad fires.
Press **Reset** if you want it back to neutral now.

**Everything reads as full effort** — an electrode has lifted or dried out. Re-prep the
skin and press **Calibrate** again.

**Traces frozen, banner says `paused`** — somebody hit space. Hit it again.

**Nothing works and there is a queue** — run
`uv run emg-demo --profile expo --source synthetic`. It needs no hardware at all and
demonstrates the same pipeline.

## Notes

- The bundled recordings are volunteer data. Check what you are allowed to show before
  running `--source dataset` in public.
- The "notch: +0.0% cleaner" reading on the replay data is honest: those recordings are
  already-rectified amplitudes with no mains hum left to remove. On live hardware the
  notch does real work.
