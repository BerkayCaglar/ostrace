# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The launcher, which has to work when the GUI does not.

Deliberately **not** marked ``gui`` and deliberately importing no Qt. What is
under test is the path taken when PySide6 is missing, so a test that needed
PySide6 to reach it would be testing the opposite case. It runs in the
interpreter sweep, which is where the package is installed without the extra.

``show_startup_error`` is stubbed for every test here, autouse, and that is not
tidiness. It opens a modal Windows dialog, and a modal dialog in a test run
waits for a person -- reached by accident it blocked for 102 seconds before
something dismissed it, and on a CI runner nobody would. A test that hangs is
worse than a test that fails, so no test in this file can reach the real one.
"""

from __future__ import annotations

import sys

import pytest

from ostrace import compat, gui


@pytest.fixture(autouse=True)
def shown(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every message the console-less fallback was asked to display."""
    messages: list[str] = []
    monkeypatch.setattr(compat, "show_startup_error", messages.append)
    return messages


@pytest.fixture
def _qt_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``from ostrace.gui.app import run`` raise.

    A ``None`` in ``sys.modules`` is the documented way to do this: the import
    system treats it as a module that failed and raises ``ImportError``. Faking
    it beats uninstalling PySide6, and it is the same exception a missing extra
    produces.
    """
    monkeypatch.setitem(sys.modules, "ostrace.gui.app", None)


@pytest.mark.usefixtures("_qt_missing")
def test_the_missing_qt_message_goes_to_stderr_when_there_is_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert gui.main([]) == 1
    assert "ostrace[gui]" in capsys.readouterr().err


@pytest.mark.usefixtures("_qt_missing")
def test_the_message_survives_having_no_console_at_all(
    monkeypatch: pytest.MonkeyPatch, shown: list[str]
) -> None:
    """Under `pythonw` -- which is every `ostrace-gui` launch on Windows, since
    `gui-scripts` means a console script with no console window -- `sys.stderr`
    is `None`, and `print` to it raises nothing and writes nowhere.

    Measured in a detached process: `stderr=None`, `stdout=None`, and
    `print(..., file=sys.stderr)` returns normally having done nothing. So the
    user double-clicked, the process exited 1, and the sentence explaining what
    to install was never delivered.
    """
    monkeypatch.setattr(sys, "stderr", None)

    assert gui.main([]) == 1
    assert len(shown) == 1
    assert "ostrace[gui]" in shown[0]


@pytest.mark.usefixtures("_qt_missing")
def test_the_fallback_is_not_used_when_stderr_works(shown: list[str]) -> None:
    """A message box in front of somebody who is looking at a terminal is worse
    than the line they were about to read."""
    assert gui.main([]) == 1
    assert shown == []
