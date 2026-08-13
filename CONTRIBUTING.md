# Contributing

## Setup

```bash
uv sync                       # or: python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
uv run pytest
```

No hardware needed for anything below.

## Before opening a PR

```bash
uv run pytest                 # 169 tests
uv run ruff check src tests
uv run ruff format --check src tests
```

If you touched the engine, the DSP or a source, also run the stability checks:

```bash
uv run pytest -m soak         # two minutes
```

## How this codebase is meant to stay

**Tests first.** Every module here was written against a failing test. Watch it fail
before you make it pass — a test written afterwards proves only that the code does what
it does.

**The engine knows nothing about drawing.** `src/emgdemo/` must not import matplotlib, a
browser, or a UI framework. State crosses to the interface as a `DemoState`; if a
renderer needs something new, it goes on that object.

**Sources are pulled, never pushed.** A source implements `start`, `stop`,
`read(max_samples)` and `status()`. Nothing else. Hardware imports (`serial`, `bleak`)
stay lazy so the package installs without them.

**Clocks are injected.** Anything time-dependent takes a `clock` callable so it can be
driven deterministically in a test. No `time.sleep` in library code.

**Failures surface.** A bare `except: pass` is a bug here. Errors become a status the
operator can see, or they propagate. The old demo had 23 swallowed exceptions and that
is why nobody could tell why it misbehaved.

**Tunable numbers live in `config.py`.** If you find yourself typing a threshold inline,
it belongs in a frozen config dataclass and probably in a profile.

**Real hardware needs a knob.** A sensor reads off, a clock drifts, an ADC runs a few
percent fast. Leave the calibration parameter even when the model looks exact.

## Layout

```
src/emgdemo/
  sources/   inputs           dsp/      filters, envelope, normalization
  domain/    events, gripper  engine.py the one clock
  server.py  HTTP + SSE       ui/       the page
  profiles/  shipped TOML
```

`legacy/` is the pre-rewrite implementation, kept out of git. Don't add to it, and
don't import from it.
