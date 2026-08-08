# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning a stream of records into the few numbers worth reporting."""

from __future__ import annotations

from ostrace.analysis.scan import ScanResult
from ostrace.analysis.templates import normalise
from ostrace.analysis.trace import TraceResult, Window

#: ``scan`` and ``trace`` themselves are deliberately not re-exported. Each is a
#: module containing a function of the same name; lifting the function to the
#: package would shadow the module, so that ``from ostrace.analysis import scan``
#: and ``import ostrace.analysis.scan`` would hand back two different objects.
#: Import them from their modules.
__all__ = ["ScanResult", "TraceResult", "Window", "normalise"]
