# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The capture as JSON Lines, for handing to another tool.

Deliberately the *same* per-line shape as the session file, produced by the same
encoder. A second JSON shape for the same record -- ``time`` here and ``ts``
there, or a pid that is a string in one and a number in the other -- is the kind
of difference that is discovered by whoever writes the consumer, at the worst
moment. There is one record encoding, documented in
``docs/formats/session-file.md``, and this is it without the gzip.

No metadata line. A JSON Lines file whose first line has a different shape from
every other breaks `jq`, `pandas.read_json(lines=True)` and every three-line
script anyone writes -- which is exactly the audience for this format. What is
known about the capture belongs in the session it came from.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ostrace.analysis.scan import ScanResult, counted
from ostrace.exporters.base import ExportResult, register
from ostrace.model import Record
from ostrace.storage.codec import encode_gap, encode_record

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from ostrace.model import DeviceInfo, Gap

__all__ = ["JsonLinesExporter"]


class JsonLinesExporter:
    """One JSON object per line, records and gaps in stream order."""

    name = "jsonl"
    description = "JSON Lines, one object per record -- the session format, uncompressed"
    suffix = ".jsonl"

    def export(
        self,
        items: Iterable[Record | Gap],
        destination: Path,
        *,
        device: DeviceInfo | None = None,  # noqa: ARG002 - the format carries no header
    ) -> ExportResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        scan = ScanResult()

        with destination.open("w", encoding="utf-8", newline="\n") as handle:
            for item in counted(items, scan):
                payload = encode_record(item) if isinstance(item, Record) else encode_gap(item)
                # ensure_ascii=False keeps the file readable: device messages
                # are full of non-ASCII, and escaping it costs bytes and eyes.
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

        return ExportResult(destination=destination, files=[destination], scan=scan)


register(JsonLinesExporter())
