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


@pytest.fixture
def mixed_fixture() -> Path:
    return MIXED


@pytest.fixture
def errors_fixture() -> Path:
    return ERRORS


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
