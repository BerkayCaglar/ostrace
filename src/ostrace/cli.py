# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line entry point.

Every command funnels its failures through one handler so that an
:class:`~ostrace.errors.OstraceError` prints its message *and its hint* and
exits non-zero, instead of showing a traceback for what is almost always an
unplugged cable or an untrusted device.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
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

#: What `export` writes when asked for nothing in particular. The bundle,
#: because it is the only format that loses nothing: everything else is a
#: summary, and a default that quietly discards data is the wrong default.
DEFAULT_FORMAT = "agent-bundle"


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
        type=_positive_float,
        metavar="SECONDS",
        help="stop after this long",
    )
    capture.add_argument(
        "--max-records",
        "-n",
        type=_positive_int,
        help="stop after this many records",
    )
    capture.add_argument(
        "--no-reconnect",
        action="store_true",
        help="fail on the first outage instead of reconnecting and recording a gap",
    )
    capture.add_argument("--quiet", "-q", action="store_true", help="no progress output")

    doctor = subcommands.add_parser("doctor", help="diagnose why a device cannot be reached")
    doctor.add_argument("--udid", help="check this device specifically")

    # Imported here rather than at module scope so that `ostrace devices` does
    # not pay for the analysis and export machinery it never touches.
    from ostrace.exporters import EXPORTERS  # noqa: PLC0415

    export = subcommands.add_parser(
        "export",
        help="turn a capture into a report",
        description="Turn a capture into a report, a bundle or another file format.",
        epilog="formats:\n"
        + "\n".join(f"  {name:<14} {e.description}" for name, e in sorted(EXPORTERS.items())),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    export.add_argument("session", help="a session directory or a capture file")
    export.add_argument(
        "--format",
        "-f",
        # The registry is the source of truth: registering an exporter is all
        # it takes for it to appear here.
        choices=sorted(EXPORTERS),
        default=DEFAULT_FORMAT,
        help=f"output format (default: {DEFAULT_FORMAT})",
    )
    export.add_argument(
        "--output",
        "-o",
        help="where to write (default: beside the capture, named after it)",
    )
    export.add_argument(
        "--budget-tokens",
        type=_non_negative_int,
        metavar="N",
        help="token budget for 'ai-report'; 0 means no limit",
    )
    export.add_argument("--quiet", "-q", action="store_true", help="print only the destination")
    return parser


def _positive_int(raw: str) -> int:
    """A count that has to mean something.

    ``--max-records 0`` used to capture exactly one record: the limit is tested
    after a record has been written, so the first comparison was ``1 >= 0``.
    Negative values behaved the same. Rejected at the boundary rather than
    reinterpreted, because there is no sensible reading of "capture at most
    minus three records".
    """
    value = int(raw)
    if value < 1:
        msg = f"must be 1 or more, not {value}"
        raise argparse.ArgumentTypeError(msg)
    return value


def _positive_float(raw: str) -> float:
    value = float(raw)
    if value <= 0:
        msg = f"must be greater than zero, not {value:g}"
        raise argparse.ArgumentTypeError(msg)
    return value


def _non_negative_int(raw: str) -> int:
    """Zero is legal here: it spells "no limit" for ``--budget-tokens``."""
    value = int(raw)
    if value < 0:
        msg = f"must be zero or more, not {value}"
        raise argparse.ArgumentTypeError(msg)
    return value


def _tolerate_unencodable_output() -> None:
    """Escape characters the output encoding cannot carry, rather than dying.

    A device is named by the person holding it, and the name comes back
    verbatim: an emoji, a Japanese given name, the curly apostrophe Apple puts
    in "Berkay's iPhone" by default. A redirected stream does not get UTF-8 --
    it gets the locale's encoding, which on Windows is a code page and under
    `LANG=C` anywhere is ASCII. Printing a name that encoding cannot represent
    raised `UnicodeEncodeError` from inside the print itself, so `ostrace
    doctor > report.txt` stopped halfway through its checks and exited with a
    traceback where the diagnostics should have been -- in exactly the
    situation the redirect exists for.

    An escaped character still identifies the device. A traceback identifies
    nothing, and this is what Python already does for stderr.
    """
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is None:  # pragma: no cover - a stdout that is not a text stream
        return
    # A detached or already closed stream. Nothing here is worth failing over:
    # the command has not started yet, and its own output will report the same
    # broken stream in a way that names what the user was trying to do.
    with contextlib.suppress(OSError, ValueError):
        reconfigure(errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    _tolerate_unencodable_output()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_OK

    try:
        # `export` reads a file and writes files. Wrapping it in an event loop
        # to match the shape of the device commands would buy nothing and
        # obscure that it is the one command needing no device at all.
        if args.command == "export":
            return _export(args)
        handler = {"devices": _devices, "capture": _capture, "doctor": _doctor}[args.command]
        return asyncio.run(handler(args))
    except OstraceError as exc:
        # The hint is the actionable half, and __str__ carries it.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        # Every command here writes files, so the filesystem's refusals are
        # ordinary: a destination inside a file, a read-only volume, a full
        # disk, a name the platform will not take. They arrived as a twelve
        # frame traceback, which reads as a crash rather than as "that path
        # will not work".
        print(f"error: {exc.strerror or exc} ({exc.filename or 'no path'})", file=sys.stderr)
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


def _export(args: argparse.Namespace) -> int:
    from pathlib import Path  # noqa: PLC0415

    from ostrace.exporters import EXPORTERS  # noqa: PLC0415
    from ostrace.exporters.ai_report import AiReportExporter  # noqa: PLC0415
    from ostrace.exporters.notes import export_notes  # noqa: PLC0415
    from ostrace.paths import check_export_destination, export_path  # noqa: PLC0415
    from ostrace.storage.capture import open_capture  # noqa: PLC0415

    # A session directory carries device metadata and a bare spool does not.
    # Exports render sensibly without it rather than requiring it: the offline
    # path exists precisely for files that arrived without a sidecar.
    session = Path(args.session)
    capture = open_capture(session)
    items = capture.items()
    device = capture.device
    truncated = capture.truncated

    exporter = EXPORTERS[args.format]
    if args.budget_tokens is not None:
        if args.format != "ai-report":
            if not args.quiet:
                print(
                    f"note: --budget-tokens does not apply to '{args.format}'; ignoring it.",
                    file=sys.stderr,
                )
        else:
            # 0 spells "no limit" because argparse has no natural way to say it
            # and `--budget-tokens 0` reads better than a magic word.
            exporter = AiReportExporter(budget_tokens=args.budget_tokens or None)

    destination = Path(args.output) if args.output else export_path(session, exporter.suffix)
    check_export_destination(destination, session)
    result = exporter.export(items, destination, device=device)

    if not args.quiet:
        print(f"{result.records:,} records -> {exporter.name}")
    # Not gated on --quiet. These say the export is missing data -- a truncated
    # capture, a hole in it, a damaged line -- and "print only the destination"
    # is a statement about stdout, which these were never on. Suppressing them
    # would make the quiet form the one that hides the bad news.
    meta = capture.meta
    for warning in export_notes(
        result,
        truncated=truncated,
        malformed=capture.malformed,
        source=meta.source if meta is not None else None,
    ):
        print(f"note: {warning}", file=sys.stderr)
    print(result.destination)
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
