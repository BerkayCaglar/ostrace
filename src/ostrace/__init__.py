# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""ostrace -- stream, inspect and export device logs.

The package is organised around one boundary: everything downstream of
``ostrace.sources`` consumes :class:`~ostrace.model.Record` objects and never
learns where they came from. That is what lets the test suite run the whole
pipeline against a committed fixture with no device attached.

This is the phase 0 skeleton. The subpackages described in ``docs/`` land in
later phases; see ``CHANGELOG.md`` for what is actually implemented.
"""

from __future__ import annotations

from ostrace.errors import guard_optimized_interpreter

__all__ = ["__version__"]

# Fail at import time rather than let a user debug corrupted logs. See the
# function's docstring for why an interpreter flag can corrupt a wire protocol.
guard_optimized_interpreter()

try:
    from ostrace._version import __version__
except ImportError:  # pragma: no cover - source checkout that was never built
    __version__ = "0.0.0+unknown"
