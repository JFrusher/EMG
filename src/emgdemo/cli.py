"""Entry point. Serves the interface by default; ``--headless`` prints instead.

Both modes drive the same engine and read the same frames, so the headless one stays
useful for soak tests and for debugging a stand with no screen attached.

Setup failures are reported and exit non-zero rather than quietly becoming synthetic.
That is a deliberate reversal: a source that never starts is an operator mistake worth
seeing, while a source that dies mid-session is still handled by the runtime failover.
Pass --fallback-synthetic to get the old forgiving behaviour at a stand.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from .config import DemoSettings
from .engine import Engine
from .profiles import ProfileError, load_profile, resolve_profile
from .state import DemoState

DEFAULT_DATASET_DIR = Path("EMGdataset/dataset/raw_signals")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="emg-demo",
        description="Live EMG signal-to-action demonstrator",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="named profile (expo, dev) or a path to a .toml",
    )
    parser.add_argument(
        "--source",
        choices=["synthetic", "dataset", "serial", "ble"],
        default="synthetic",
        help="where samples come from",
    )
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--side-a-channel", default=None, help="column driving grip close")
    parser.add_argument("--side-b-channel", default=None, help="column driving grip open")
    parser.add_argument("--replay-speed", type=float, default=1.0)
    parser.add_argument("--replay-loop", action="store_true")
    parser.add_argument("--port", default=None, help="serial port, e.g. COM3")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--ble-address", default=None)
    parser.add_argument("--ble-name", default=None, help="substring of the device name")
    parser.add_argument("--ble-service", default=None)
    parser.add_argument(
        "--fallback-synthetic",
        action="store_true",
        help="fall back to synthetic if the chosen source cannot be set up",
    )
    parser.add_argument("--duration", type=float, default=0.0, help="seconds; 0 runs until Ctrl+C")
    parser.add_argument("--headless", action="store_true", help="print frames instead of serving")
    parser.add_argument("--host", default="127.0.0.1")
    # Not --port: that already means the serial port the ESP32 is on.
    parser.add_argument("--http-port", type=int, default=8420)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="ask the browser to go fullscreen on the first click or keypress",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse once to find the profile, then again so explicit flags still win."""
    parser = build_parser()
    args = parser.parse_args(argv)
    args.settings = DemoSettings()

    if args.profile:
        profile = load_profile(resolve_profile(args.profile))
        parser.set_defaults(**profile.cli_defaults())
        args = parser.parse_args(argv)
        args.settings = profile.settings
        args.profile_path = str(profile.path)

    return args


def _build(args: argparse.Namespace, sample_rate_hz: float):
    if args.source == "dataset":
        from .sources.replay import DatasetReplaySource

        folder = Path(args.dataset_dir)
        source = DatasetReplaySource(
            folder=folder,
            sample_rate_hz=sample_rate_hz,
            side_a_channel=args.side_a_channel,
            side_b_channel=args.side_b_channel,
            replay_speed=args.replay_speed,
            loop=args.replay_loop,
        )
        return source, f"Dataset replay ({folder.name})"

    if args.source == "serial":
        from .sources.serial import SerialSource

        if not args.port:
            raise ValueError("--port is required for the serial source")
        return SerialSource.on_port(args.port, args.baud, sample_rate_hz=sample_rate_hz), (
            f"Serial {args.port}"
        )

    if args.source == "ble":
        from .sources.ble import BLESource

        source = BLESource(
            sample_rate_hz=sample_rate_hz,
            address=args.ble_address,
            name_hint=args.ble_name,
            service_uuid=args.ble_service,
        )
        return source, f"BLE {args.ble_address or args.ble_name or args.ble_service}"

    from .sources.synthetic import SyntheticSource

    return SyntheticSource(sample_rate_hz), "Synthetic"


def build_source(args: argparse.Namespace, sample_rate_hz: float):
    try:
        return _build(args, sample_rate_hz)
    except Exception as exc:
        if not args.fallback_synthetic:
            raise
        from .sources.synthetic import SyntheticSource

        print(f"Source setup failed ({exc}); using synthetic fallback", file=sys.stderr)
        return SyntheticSource(sample_rate_hz), "Synthetic (setup fallback)"


def format_state(state: DemoState) -> str:
    return (
        f"t={state.t:7.2f}s "
        f"{state.source_name:<28.28s} {state.source_state:<12.12s} "
        f"rate={state.measured_rate_hz:6.1f}/{state.design_rate_hz:6.1f}Hz "
        f"L={state.side_a_level:4.2f} R={state.side_b_level:4.2f} "
        f"grip={state.gripper.label:<5.5s} {state.gripper.force_n:5.1f}N "
        f"events={state.event_count:<4d} co={state.cocontraction_count:<4d} "
        f"n={state.total_samples}"
    )


def serve(engine: Engine, args: argparse.Namespace) -> int:
    from .server import DemoServer

    server = DemoServer(engine, host=args.host, port=args.http_port)
    url = f"{server.url}/?fullscreen=1" if args.fullscreen else server.url
    print(f"EMG demo running at {url}   (Ctrl+C to stop)")

    if not args.no_browser:
        import webbrowser

        threading.Timer(0.4, webbrowser.open, args=(url,)).start()

    if args.duration:
        threading.Timer(args.duration, server.shutdown).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        server.shutdown()
    return 0


def run_headless(engine: Engine, args: argparse.Namespace) -> int:
    engine.start()

    print_interval = 1.0 / 30.0
    tick_interval = 1.0 / 200.0
    started = time.perf_counter()
    next_print = started
    last_shown: tuple[str, ...] = ()

    try:
        while True:
            state = engine.tick()
            now = time.perf_counter()

            if now >= next_print:
                next_print = now + print_interval
                print(format_state(state))
                for line in state.events:
                    if line not in last_shown:
                        print(f"    {line}")
                last_shown = state.events

            if args.duration and (now - started) >= args.duration:
                break
            time.sleep(tick_interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        engine.stop()

    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except ProfileError as exc:
        print(f"Profile problem: {exc}", file=sys.stderr)
        return 2

    settings = args.settings

    try:
        source, name = build_source(args, settings.sample_rate_hz)
    except Exception as exc:
        print(f"Could not set up the {args.source} source: {exc}", file=sys.stderr)
        return 2

    engine = Engine(settings, source=source, source_name=name)
    return run_headless(engine, args) if args.headless else serve(engine, args)


if __name__ == "__main__":
    raise SystemExit(main())
