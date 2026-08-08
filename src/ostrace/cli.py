# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line entry point.

``export`` is declared but not implemented: it needs the exporters, which land
in phase 2. The other three are real.

Every command funnels its failures through one handler so that an
:class:`~ostrace.errors.OstraceError` prints its message *and its hint* and
exits non-zero, instead of showing a traceback for what is almost always an
unplugged cable or an untrusted device.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING

from ostrace import __version__
from ostrace.errors import OstraceError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["build_parser", "main"]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130  # what a shell reports for SIGINT
EXIT_NOT_IMPLEMENTED = 69  # EX_UNAVAILABLE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ostrace",
        description="Stream, inspect and export device logs.",
    )
    parser.add_argument("--version", action="version", version=f"ostrace {__version__}")
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")

    devices = subcommands.add_parser("devices", help="list attached devices")
    devices.add_argument("--verbose", "-v", action="store_true", help="also read device identity")

    capture = subcommands.add_parser("capture", help="stream a device log to a session file")
    capture.add_argument("--udid", help="device to capture from (default: the first USB device)")
    capture.add_argument(
        "--output",
        "-o",
        help="session directory to write (default: a timestamped one under the data directory)",
    )
    capture.add_argument(
        "--duration",
        "-d",
        type=float,
        metavar="SECONDS",
        help="stop after this long",
    )
    capture.add_argument("--max-records", "-n", type=int, help="stop after this many records")
    capture.add_argument(
        "--no-reconnect",
        action="store_true",
        help="fail on the first outage instead of reconnecting and recording a gap",
    )
    capture.add_argument("--quiet", "-q", action="store_true", help="no progress output")

    doctor = subcommands.add_parser("doctor", help="diagnose why a device cannot be reached")
    doctor.add_argument("--udid", help="check this device specifically")

    subcommands.add_parser("export", help="turn a session file into a report (phase 2)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_OK
    if args.command == "export":
        print("'export' is not implemented yet; it arrives with the exporters in phase 2.")
        return EXIT_NOT_IMPLEMENTED

    handler = {"devices": _devices, "capture": _capture, "doctor": _doctor}[args.command]
    try:
        return asyncio.run(handler(args))
    except OstraceError as exc:
        # The hint is the actionable half, and __str__ carries it.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover - needs a real signal
        return EXIT_INTERRUPTED


async def _devices(args: argparse.Namespace) -> int:
    from ostrace.devices.discovery import (  # noqa: PLC0415
        list_devices,
        open_lockdown,
        read_device_info,
    )

    found = await list_devices()
    if not found:
        print("No devices connected. Run 'ostrace doctor' to find out why.")
        return EXIT_ERROR

    for device in found:
        if not args.verbose:
            print(f"{device.udid}  {device.connection}")
            continue
        lockdown = await open_lockdown(device.udid)
        try:
            info = await read_device_info(lockdown, connection=device.connection)
        finally:
            await _quietly_close(lockdown)
        print(f"{device.udid}  {device.connection}  {info.label}")
    return EXIT_OK


async def _capture(args: argparse.Namespace) -> int:
    from pathlib import Path  # noqa: PLC0415

    from ostrace.capture import capture  # noqa: PLC0415
    from ostrace.sources.os_trace import OsTraceSource, ReconnectPolicy  # noqa: PLC0415

    source = OsTraceSource(
        args.udid,
        reconnect=ReconnectPolicy.disabled() if args.no_reconnect else ReconnectPolicy(),
    )

    progress = None if args.quiet else _progress
    result = await capture(
        source,
        destination=Path(args.output) if args.output else None,
        duration=args.duration,
        max_records=args.max_records,
        on_progress=progress,
    )

    if not args.quiet:
        print(file=sys.stderr)
    rate = result.records / result.duration_seconds if result.duration_seconds > 0 else 0.0
    print(f"{result.records:,} records in {result.duration_seconds:.1f}s ({rate:,.0f}/s)")
    if result.gaps:
        print(f"{result.gaps} gap(s): the device was unreachable for part of the capture")
    print(result.path)
    return EXIT_OK


async def _doctor(args: argparse.Namespace) -> int:
    from ostrace.devices import doctor  # noqa: PLC0415

    report = await doctor.run(args.udid)
    for check in report.checks:
        print(f"{_MARKS[check.status.value]} {check.name:<12} {check.detail}")
        if check.hint:
            for line in _wrapped(check.hint):
                print(f"               {line}")
    return EXIT_OK if report.ok else EXIT_ERROR


_MARKS = {
    # Words rather than symbols: this output gets pasted into issues, and a
    # tick that renders as a box on someone's console helps nobody.
    "ok": "[ ok ]",
    "warn": "[warn]",
    "fail": "[FAIL]",
    "skip": "[skip]",
}


def _progress(records: int, gaps: int) -> None:
    suffix = f", {gaps} gap(s)" if gaps else ""
    # Carriage return, stderr: stdout stays clean for the paths a script wants.
    print(f"\r{records:,} records{suffix}...", end="", file=sys.stderr, flush=True)


def _wrapped(text: str, width: int = 64) -> list[str]:
    import textwrap  # noqa: PLC0415

    return textwrap.wrap(text, width=width)


async def _quietly_close(lockdown: object) -> None:
    import contextlib  # noqa: PLC0415

    with contextlib.suppress(Exception):
        await lockdown.close()  # type: ignore[attr-defined]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
