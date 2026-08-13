# EMG Signal to Action

A live demonstrator that turns muscle signals into a moving gripper, built to run in
front of people. It shows the whole chain on screen — raw electrode voltage through
notch, bandpass, rectification and smoothing to a control envelope — so the filtering is
visible rather than asserted.

Runs with no hardware attached.

## Run it

```bash
uv run emg-demo --profile dev
```

That opens a browser on a synthetic signal. No ESP32, no electrodes, no setup.

For a stand:

```bash
uv run emg-demo --profile expo --fullscreen
```

Without `uv`, any Python 3.12+ works:

```bash
python -m venv .venv && .venv/Scripts/pip install -e .   # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m emgdemo.cli --profile dev
```

## Where the signal comes from

| `--source` | What it is |
|---|---|
| `synthetic` | Generated EMG. Always works; the automatic fallback |
| `dataset` | Recorded volunteer sessions, replayed at real speed |
| `serial` | ESP32 over USB — `--port COM3` |
| `ble` | ESP32 over Bluetooth — `--ble-name MYOWARE` |

Any live source that stops delivering is restarted, and if it stays dead the demo
switches to synthetic and says so, rather than freezing.

## Controls

`Space` pause · `C` calibrate · `R` reset · `F` fullscreen — or the buttons.

**Calibrate** is the one that matters with a participant attached: four seconds of rest
then squeeze, which maps that person's range onto the gripper. Without it the demo
adapts on its own, less well.

## Profiles

Settings live in TOML rather than in twenty command-line flags:

```toml
[source]
kind = "ble"
ble_name = "MYOWARE"

[settings.events]
threshold_high = 0.35     # harder to trigger
```

```bash
uv run emg-demo --profile ./my-stand.toml
```

Shipped profiles are in [src/emgdemo/profiles/](src/emgdemo/profiles/). An unknown key
is an error, not a shrug — a typo at a stand should fail loudly.

## Layout

```
src/emgdemo/
  sources/    where samples come from      dsp/       filters, envelope, normalization
  domain/     events, gripper, calibration engine.py  the one clock
  server.py   serves the page              ui/        what you see
```

The engine has no idea anything is being drawn. It publishes state; the interface reads
it. That is what lets the renderer be replaced without touching the signal path.

## Developing

```bash
uv run pytest                          # 169 tests, no hardware needed
uv run pytest -m soak                  # two-minute stability run
EMG_SOAK_SECONDS=7200 uv run pytest -m soak    # the full pre-expo check
uv run ruff check src tests
```

`--headless` prints frames instead of serving them, which is how to debug a stand with
no screen.

## More

- [docs/HARDWARE.md](docs/HARDWARE.md) — wiring, electrodes, flashing the ESP32
- [docs/EXPO.md](docs/EXPO.md) — event-day checklist and what to do when it misbehaves

## Data

`EMGdataset/` holds recordings from eleven volunteers. Check what you are permitted to
publish or display before sharing this repository or running `--source dataset` in
public.

## Licence

MIT — see [LICENSE](LICENSE).
