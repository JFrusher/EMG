"""
BLE Setup + Validation helper for public EMG demos.

This script discovers a BLE EMG device, resolves a notifiable characteristic,
verifies live notifications, and stores settings in demo_ble_config.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from bleak import BleakClient, BleakScanner


DEFAULT_CHAR_CANDIDATES = [
    "beb5483e-36e1-4688-b7f5-ea07361b26a8",
    "0000ffe1-0000-1000-8000-00805f9b34fb",
    "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-discover and validate BLE EMG stream for public demo",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--ble-address", default=None, help="Exact BLE address/MAC to use")
    parser.add_argument("--ble-device-name", default="MYOWARE", help="Name hint for BLE scan")
    parser.add_argument("--ble-service", default=None, help="Optional BLE service UUID filter")
    parser.add_argument("--ble-char", default=None, help="Characteristic UUID (skip auto selection if provided)")
    parser.add_argument("--scan-timeout", type=float, default=6.0, help="Scan timeout in seconds")
    parser.add_argument("--verify-seconds", type=float, default=3.0, help="Time to verify notifications")
    parser.add_argument("--config", default="demo_ble_config.json", help="Output JSON config path")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if stream verification fails")
    return parser.parse_args()


async def select_device(
    address: Optional[str],
    name_hint: str,
    service_uuid: Optional[str],
    scan_timeout: float,
):
    devices = await BleakScanner.discover(timeout=max(1.0, float(scan_timeout)))
    if not devices:
        raise RuntimeError("No BLE devices discovered")

    if address:
        target = address.strip().lower()
        for dev in devices:
            if (getattr(dev, "address", "") or "").strip().lower() == target:
                return dev
        raise RuntimeError(f"Requested BLE address not found: {address}")

    name_key = (name_hint or "").strip().lower()
    if name_key:
        for dev in devices:
            dev_name = (getattr(dev, "name", None) or "").strip().lower()
            if name_key in dev_name:
                return dev

    if service_uuid:
        svc = service_uuid.strip().lower()
        for dev in devices:
            uuids = [u.lower() for u in (getattr(dev, "metadata", {}).get("uuids") or [])]
            if svc in uuids:
                return dev

    return devices[0]


async def resolve_notify_char(client: BleakClient, char_uuid: Optional[str], service_uuid: Optional[str]) -> str:
    if char_uuid:
        return char_uuid.strip().lower()

    services = await client.get_services()
    candidates = [c.lower() for c in DEFAULT_CHAR_CANDIDATES]

    notify_chars = []
    for service in services:
        if service_uuid and str(service.uuid).lower() != service_uuid.strip().lower():
            continue
        for ch in service.characteristics:
            props = {p.lower() for p in (ch.properties or [])}
            if "notify" in props:
                notify_chars.append(str(ch.uuid).lower())

    if not notify_chars:
        raise RuntimeError("No notify-capable characteristics found")

    for cand in candidates:
        if cand in notify_chars:
            return cand

    return notify_chars[0]


def parse_payload_sample_count(payload: bytes) -> int:
    if not payload:
        return 0
    if len(payload) % 2 != 0:
        return 0

    try:
        values = np.frombuffer(payload, dtype="<u2")
        if values.size > 0 and int(np.max(values)) <= 4095:
            return int(values.size)
    except Exception:
        pass

    return 0


async def configure_and_verify(args: argparse.Namespace) -> Tuple[dict, int, int]:
    device = await select_device(
        address=args.ble_address,
        name_hint=args.ble_device_name,
        service_uuid=args.ble_service,
        scan_timeout=args.scan_timeout,
    )

    resolved_address = str(getattr(device, "address", "")).strip()
    resolved_name = getattr(device, "name", None) or args.ble_device_name
    if not resolved_address:
        raise RuntimeError("Discovered device has no address")

    packet_count = 0
    sample_count = 0

    async with BleakClient(resolved_address, timeout=8.0) as client:
        if not client.is_connected:
            raise RuntimeError("Failed to connect to selected BLE device")

        resolved_char = await resolve_notify_char(client, args.ble_char, args.ble_service)
        done_at = time.monotonic() + max(1.0, float(args.verify_seconds))

        def on_notify(_: int, data: bytearray) -> None:
            nonlocal packet_count, sample_count
            packet_count += 1
            sample_count += parse_payload_sample_count(bytes(data))

        await client.start_notify(resolved_char, on_notify)
        try:
            while time.monotonic() < done_at:
                await asyncio.sleep(0.05)
        finally:
            await client.stop_notify(resolved_char)

    payload = {
        "address": resolved_address,
        "char_uuid": resolved_char,
        "device_name": resolved_name,
        "service_uuid": args.ble_service or "",
        "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return payload, packet_count, sample_count


def main() -> int:
    args = parse_args()
    cfg_path = Path(args.config).expanduser()

    try:
        payload, packets, samples = asyncio.run(configure_and_verify(args))

        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        rate = samples / max(args.verify_seconds, 1e-6)
        print("BLE setup successful")
        print(f"  Device: {payload['device_name']} ({payload['address']})")
        print(f"  Notify char: {payload['char_uuid']}")
        print(f"  Notifications: {packets} | Samples: {samples} | Approx rate: {rate:.1f} Hz")
        print(f"  Saved config: {cfg_path}")
        return 0

    except Exception as exc:
        print(f"BLE setup failed: {exc}")
        if args.strict:
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
