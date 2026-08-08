# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning a stream of records into the few numbers worth reporting."""

from __future__ import annotations

from ostrace.analysis.scan import ScanResult
from ostrace.analysis.templates import normalise

#: ``scan`` itself is deliberately not re-exported. The module is
#: ``analysis.scan`` and the function inside it is ``scan()``; lifting the
#: function to the package would shadow the module, so that
#: ``from ostrace.analysis import scan`` and ``import ostrace.analysis.scan``
#: would hand back two different objects. Import it from its module.
__all__ = ["ScanResult", "normalise"]
