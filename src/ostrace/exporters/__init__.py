# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning a capture into something else.

Importing this package registers every exporter, which is what makes
``EXPORTERS`` complete for the CLI's ``--format`` choices. An exporter that is
never imported is never registered, so new ones are added here rather than
discovered.
"""

from __future__ import annotations

from ostrace.exporters import agent_bundle
from ostrace.exporters.base import EXPORTERS, Exporter, ExportResult, escape

__all__ = ["EXPORTERS", "ExportResult", "Exporter", "agent_bundle", "escape"]
