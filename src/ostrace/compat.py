# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform differences, in one place.

This project is developed on Windows and has to run on macOS and Linux, where
the author cannot test it. The rule that follows: no module outside this one may
branch on the operating system, and none may touch a platform-specific
attribute. ``subprocess.CREATE_NO_WINDOW`` and ``os.startfile`` do not exist off
Windows, and referencing either raises ``AttributeError`` at import time on a
Mac -- a crash before main() runs, found by a user rather than by CI.

The platform tests below are written as literal ``sys.platform == "win32"``
comparisons rather than as the module constants, even where a constant would
read better. Type checkers narrow on the literal form and not on a constant, so
this way ``mypy --platform darwin`` type-checks the macOS branch from a Windows
machine. CI runs all three platforms for exactly that reason.

Assumptions not verified on real hardware are marked ``UNVERIFIED-MACOS`` so
they can be grepped and confirmed the moment a Mac is available.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "IS_LINUX",
    "IS_MACOS",
    "IS_WINDOWS",
    "hidden_process_kwargs",
    "open_in_file_manager",
    "terminate",
]

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def hidden_process_kwargs() -> dict[str, Any]:
    """Keyword arguments that stop a child process flashing a console window.

    Empty off Windows: the flags do not exist there, and there is no window to
    suppress in the first place.
    """
    if sys.platform != "win32":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


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


def terminate(process: subprocess.Popen[Any], timeout: float = 5.0) -> None:
    """Stop a child process portably.

    POSIX ``SIGTERM`` is catchable and a well-behaved child may decline it;
    Windows ``terminate()`` is not catchable at all. Asking politely and then
    insisting is the only sequence that behaves the same on both.
    """
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)
