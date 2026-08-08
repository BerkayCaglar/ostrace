# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""ostrace -- stream, inspect and export device logs.

The package is organised around one boundary: everything downstream of
``ostrace.sources`` consumes :class:`~ostrace.model.Record` objects and never
learns where they came from. That is what lets the test suite run the whole
pipeline against a committed fixture with no device attached.

Importing this package deliberately does no work and pulls in no device
libraries, so offline use -- replaying a session, re-exporting a capture --
costs nothing and depends on nothing.
"""

from __future__ import annotations

__all__ = ["__version__"]

try:
    from ostrace._version import __version__
except ImportError:  # pragma: no cover - source checkout that was never built
    __version__ = "0.0.0+unknown"
