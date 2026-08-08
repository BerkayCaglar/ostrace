# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line entry point.

Phase 0 ships the argument parser and nothing behind it. The ``devices``,
``capture``, ``export`` and ``doctor`` subcommands land in phase 3; each is
declared here already so that ``--help`` documents the intended surface and so
that the console script installed by ``pyproject.toml`` resolves.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from ostrace import __version__

if TYPE_CHECKING:
    from collections.abc import Sequence

_PLANNED = ("devices", "capture", "export", "doctor")

EXIT_OK = 0
EXIT_NOT_IMPLEMENTED = 69  # EX_UNAVAILABLE


def build_parser() -> argparse.ArgumentParser:
    """Build the top level parser."""
    parser = argparse.ArgumentParser(
        prog="ostrace",
        description="Stream, inspect and export device logs.",
        epilog=(
            "This is a phase 0 skeleton: the subcommands are not implemented yet. "
            "See https://github.com/BerkayCaglar/ostrace"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ostrace {__version__}",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=_PLANNED,
        help="subcommand to run (all of them are planned, none implemented)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_OK

    print(f"ostrace {__version__}: '{args.command}' is not implemented yet (phase 3).")
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
