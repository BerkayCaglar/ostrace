# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures.

The two ``.jsonl.gz`` files under ``fixtures/`` are real captures from an
``iPhone18,2`` running iOS 26.5.2, filtered to system processes only. They are
not hand-written, and nothing in this suite should introduce a hand-written
substitute for them: a previous iteration of this tool matched 0% of real device
output for weeks because its tests used invented log lines that happened to
contain a syslog hostname field real output does not have. The tests passed the
entire time.

Synthetic records built by ``tests.helpers.make_record`` are fine for asserting
that *our own* file format round-trips. They are not fine for asserting anything
about how device output is interpreted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ostrace.model import DeviceInfo
from tests.helpers import DEVICE_TZ, ERRORS, MIXED

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtWidgets import QApplication


@pytest.fixture
def mixed_fixture() -> Path:
    return MIXED


@pytest.fixture
def errors_fixture() -> Path:
    return ERRORS


@pytest.fixture(scope="session")
def qt_app() -> QApplication:
    """One themed ``QApplication`` for the whole session.

    Qt permits exactly one per process and constructing a second is a hard
    failure, so this is session-scoped rather than per-test. It is the same
    application a user gets -- ``build_application`` does the style and palette
    work -- because a test against a differently configured application proves
    something about a program nobody runs.

    ``importorskip`` rather than a hard import: Qt is an optional extra, and
    the interpreter sweep in CI installs the package without it.
    """
    pytest.importorskip("PySide6", reason="the gui extra is not installed")
    from ostrace.gui.app import build_application

    return build_application([])


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Keep the suite out of the user's own settings.

    `MainWindow.closeEvent` saves the layout, and a test that closes a window
    wrote geometry into ``HKEY_CURRENT_USER`` -- geometry belonging to an
    *offscreen* window, which the next real launch then restored, putting the
    window somewhere no display could show it. Running the tests broke the
    program for the person who ran them, which is as bad as a test failure and
    considerably harder to notice.

    Both calls are needed and both are global rather than per-instance: the
    format decides *where* Qt looks, and the path only redirects the format it
    is given. Autouse because the damage is done by any test that closes a
    window, not only by the ones that mean to write settings.

    A fresh directory *per test*, not per session. Shared, the settings leak
    between tests exactly as they leaked onto the user: one test toggling the
    theme left `window/theme` set for every window built afterwards, and the
    test asserting that the window follows the system failed because by then it
    correctly no longer did.
    """
    pytest.importorskip("PySide6", reason="the gui extra is not installed")
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path_factory.mktemp("settings")),
    )


@pytest.fixture(autouse=True)
def _isolate_data_dir(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep everything the package writes out of the real data directory.

    `paths` resolves to the person's own directory by default, so a test that
    starts a capture writes a session file into the directory their real
    captures live in -- one they did not ask for and will not know to delete.
    A single environment variable redirects every path the package decides.

    Suite-wide and autouse rather than sitting in the one module that starts
    captures today. The next test to write something is not required to
    remember this, and when it forgets there is no failure to notice: the file
    lands somewhere plausible and the suite passes.

    Tests about `paths` itself take control back for themselves -- a
    `monkeypatch.setenv` in the test body replaces this value, and
    `delenv` restores the real resolution for the one test that needs to see
    it.
    """
    monkeypatch.setenv("OSTRACE_HOME", str(tmp_path_factory.mktemp("home")))


@pytest.fixture
def device() -> DeviceInfo:
    return DeviceInfo(
        udid="00000000-000000000000000A",
        name="Test iPhone",
        product_type="iPhone18,2",
        product_version="26.5.2",
        build_version="23F84",
        timezone_name="Europe/Istanbul",
        utc_offset=DEVICE_TZ,
    )
