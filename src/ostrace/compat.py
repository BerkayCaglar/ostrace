# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform differences, in one place.

This project is developed on Windows and has to run on macOS and Linux, where
the author cannot test it. The rule that follows: no module outside this one may
branch on the operating system, and none may touch a platform-specific
attribute. ``os.startfile`` does not exist off Windows, and referencing it
raises ``AttributeError`` at import time on a Mac -- a crash before main() runs,
found by a user rather than by CI.

The platform tests below are written as literal ``sys.platform == "win32"``
comparisons rather than as named constants. Type checkers narrow on the literal
form and not on a constant, so this way ``mypy --platform darwin`` type-checks
the macOS branch from a Windows machine, and CI runs all three platforms for
exactly that reason. Because a named constant would defeat that, none is
exported: there would be no correct way to use it.

Assumptions not verified on real hardware are marked ``UNVERIFIED-MACOS`` so
they can be grepped and confirmed the moment a Mac is available.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["local_usbmux_endpoint", "open_in_file_manager"]


def local_usbmux_endpoint() -> tuple[str, int] | None:
    """Where usbmux listens, when it listens on TCP.

    Windows has no usbmux of its own: Apple Mobile Device Service provides it,
    over TCP, and its absence is the single most common reason nothing works
    there. macOS and Linux reach usbmuxd over a unix socket owned by the OS or
    by a package, which this does not probe.

    ``None`` therefore means "not a TCP endpoint here", not "unavailable" --
    which is what lets a caller diagnose the Windows case without branching on
    the operating system itself.
    """
    if sys.platform == "win32":
        return ("127.0.0.1", 27015)
    return None


def open_in_file_manager(path: Path) -> None:
    """Reveal a file or directory in the platform's file manager."""
    target = path if path.is_dir() else path.parent

    if sys.platform == "win32":
        os.startfile(target)
        return

    # UNVERIFIED-MACOS: `open` is the documented way to do this and accepts a
    # directory; the -R flag that reveals a specific file has not been tried.
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, os.fspath(target)])
