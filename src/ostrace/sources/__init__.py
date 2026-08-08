# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where records come from.

This package is the load-bearing boundary of the project. Everything downstream
consumes :class:`~ostrace.model.Record` objects and never learns which device,
transport or library produced them -- which is what lets the whole pipeline be
tested against a committed fixture with no hardware attached, and what confines
a replacement for ``pymobiledevice3`` to one directory if it is ever needed.

Note what is *not* re-exported here: :class:`~ostrace.sources.os_trace.OsTraceSource`
has to be imported from its own module. Importing it pulls in
``pymobiledevice3``, which pulls in roughly forty packages of its own including
FastAPI, uvicorn and IPython. Making that a side effect of ``import
ostrace.sources`` would put a second or more onto the start-up of commands that
never touch a device, and would make an offline test suite depend on the one
library it exists to be independent of.
"""

from __future__ import annotations

from ostrace.sources.base import LogSource
from ostrace.sources.replay import ReplaySource

__all__ = ["LogSource", "ReplaySource"]
