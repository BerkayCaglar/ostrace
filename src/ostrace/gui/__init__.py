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
        print(_MISSING, file=sys.stderr)
        return 1
    return run(argv)
