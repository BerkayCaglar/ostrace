# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the desktop believes this process is.

The complaint these answer is that the application "says Python". Measured, the
window icon, the title bar and the Alt-Tab entry were already right; what was
wrong is one level below them. The window is owned three processes down by
`pythonw.exe`, whose file description is the word `Python`, and the process
carried no identity of its own for the shell to prefer instead.

This is the one module in `tests/` that branches on the operating system. The
rule that keeps `sys.platform` inside `compat.py` is about production code,
where a branch anywhere else is a portability bug waiting to be found by a user;
here the assertion is *about* a platform, and hiding that behind a helper would
only move it. Written as the literal comparison anyway, so the three-platform
mypy run narrows it the same way it narrows `compat.py`.
"""

from __future__ import annotations

import ctypes
import sys

import pytest

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtGui import QGuiApplication

from ostrace.compat import set_app_identity
from ostrace.gui.app import APP_ID, DESKTOP_FILE

pytestmark = pytest.mark.gui


def test_the_process_carries_its_own_identity(qt_app: object) -> None:
    """Without this the taskbar groups ostrace with every other Python program
    on the machine, and a pinned button launches the interpreter.

    The negative case is real: `GetCurrentProcessExplicitAppUserModelID` returns
    `E_FAIL` (0x80004005) before anything sets one, so this fails if the call is
    removed or if the string changes.

    What it does *not* pin is the ordering. The identity reads back the same
    whether it was set before the QApplication or after the first window, and
    the difference only shows in a shell nothing here can ask. That constraint
    lives in a comment beside the call, which is the honest place for it.
    """
    del qt_app

    if sys.platform == "win32":
        buffer = ctypes.c_wchar_p()
        result = ctypes.WinDLL("shell32").GetCurrentProcessExplicitAppUserModelID(
            ctypes.byref(buffer)
        )

        assert result == 0
        assert buffer.value == APP_ID
    else:
        # There is nothing to read back, so what is asserted is the only thing
        # that could go wrong off Windows: that a platform-specific call has not
        # leaked out of its branch.
        set_app_identity(APP_ID)


def test_the_identity_carries_no_version(qt_app: object) -> None:
    """Microsoft's guidance is that the version component is omitted, so that an
    upgrade keeps the identity of the release it replaces.

    A version in the string would give each release its own taskbar group and
    silently break every shortcut anybody had pinned.
    """
    del qt_app

    assert APP_ID.count(".") == 1
    assert not any(part[:1].isdigit() for part in APP_ID.split("."))


def test_the_application_names_its_desktop_entry(qt_app: object) -> None:
    """On Wayland this becomes the surface's `app_id`, and it is the only thing
    a compositor can match a window to its entry, its name and its icon by.

    Ignored on Windows and macOS, so it is asserted on all three: what would
    break it is the call being dropped, not a platform disagreeing.
    """
    del qt_app

    assert QGuiApplication.desktopFileName() == DESKTOP_FILE
