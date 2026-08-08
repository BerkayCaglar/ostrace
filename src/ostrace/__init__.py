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

import sys

__all__ = ["__version__"]

# pymobiledevice3's os_trace stream loop is written as
#     assert await self.service.recvall(1) == b"\x02"
# Running under -O / PYTHONOPTIMIZE strips assert statements *including the
# await inside them*, which desynchronises the frame protocol and yields
# garbage records instead of a clean error. Fail loudly at import time rather
# than let a user debug corrupted logs.
if sys.flags.optimize:  # pragma: no cover - depends on interpreter flags
    _MSG = (
        "ostrace cannot run under -O / PYTHONOPTIMIZE: the device stream "
        "protocol depends on assert statements that optimisation removes. "
        "Unset PYTHONOPTIMIZE and run again."
    )
    raise RuntimeError(_MSG)

try:
    from ostrace._version import __version__
except ImportError:  # pragma: no cover - source checkout that was never built
    __version__ = "0.0.0+unknown"
