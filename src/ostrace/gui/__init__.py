# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The desktop viewer.

Qt is an optional dependency, so nothing here imports it at package import
time. ``main()`` is the only entry point and it resolves PySide6 lazily, which
is what turns a missing extra into one sentence telling the user what to
install instead of a traceback ending in ``ModuleNotFoundError: PySide6``.
"""

from __future__ import annotations

import sys

__all__ = ["main"]

_MISSING = """\
ostrace: the graphical viewer needs Qt, which is not installed.

    pip install 'ostrace[gui]'

The command-line tool works without it -- try `ostrace --help`.\
"""


def main(argv: list[str] | None = None) -> int:
    """Launch the viewer, or explain why it cannot start."""
    try:
        # Local by design: importing this at module scope is exactly what
        # turns a missing optional dependency into a traceback.
        from ostrace.gui.app import run  # noqa: PLC0415
    except ImportError:
        _explain(_MISSING)
        return 1
    return run(argv)


def _explain(message: str) -> None:
    """Say it somewhere it can be read.

    ``sys.stderr`` is ``None`` in a process with no console, which on Windows is
    every launch of ``ostrace-gui``: ``gui-scripts`` is defined as a console
    script without a console window. ``print`` to a ``None`` stream raises
    nothing -- it is a silent no-op -- so the one sentence this function exists
    to deliver was reaching nobody at all, and the program appeared to exit
    without a word.

    The import is local so that the ordinary path, where there is a stderr, does
    not pay for a module it will not use.
    """
    if sys.stderr is not None:
        print(message, file=sys.stderr)
        return

    from ostrace.compat import show_startup_error  # noqa: PLC0415

    show_startup_error(message)
