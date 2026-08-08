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
