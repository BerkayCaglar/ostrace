# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""A session: the spool plus a metadata sidecar.

Layout on disk::

    <name>.ostrace/
        session.jsonl.gz    the records
        session.json        metadata

The sidecar is metadata and never an index. If it is missing or truncated --
a capture killed mid-write -- the spool alone is still fully readable, and
:class:`SessionReader` says so instead of refusing to open.

Contract documented in ``docs/formats/session-file.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ostrace import __version__
from ostrace.errors import StorageError, UnsupportedFormatVersionError
from ostrace.model import DeviceInfo, Platform
from ostrace.paths import with_session_suffix
from ostrace.storage.codec import parse_timestamp
from ostrace.storage.spool import SpoolReader, SpoolWriter

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from types import TracebackType
    from typing import Self

    from ostrace.model import Gap, Record

__all__ = ["FORMAT_VERSION", "SessionMeta", "SessionReader", "SessionWriter"]

FORMAT_VERSION = 1

SPOOL_NAME = "session.jsonl.gz"
META_NAME = "session.json"


@dataclass(slots=True)
class SessionMeta:
    """What a session knows about itself."""

    device: DeviceInfo
    source: str
    started_at: datetime
    format_version: int = FORMAT_VERSION
    ostrace_version: str = __version__
    ended_at: datetime | None = None
    record_count: int = 0
    gap_count: int = 0
    flags: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "ostrace_version": self.ostrace_version,
            "device": {
                "udid": self.device.udid,
                "name": self.device.name,
                "platform": str(self.device.platform),
                "product_type": self.device.product_type,
                "product_version": self.device.product_version,
                "build_version": self.device.build_version,
                "connection": self.device.connection,
                "timezone_name": self.device.timezone_name,
                "utc_offset_seconds": (
                    None
                    if self.device.utc_offset is None
                    else int(self.device.utc_offset.total_seconds())
                ),
            },
            "source": self.source,
            "started_at": self.started_at.isoformat(),
            "ended_at": None if self.ended_at is None else self.ended_at.isoformat(),
            "record_count": self.record_count,
            "gap_count": self.gap_count,
            "flags": self.flags,
        }

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> SessionMeta:
        version = int(obj.get("format_version", 0))
        if version > FORMAT_VERSION:
            msg = f"session format version {version} is newer than {FORMAT_VERSION}"
            raise UnsupportedFormatVersionError(msg)

        raw = obj.get("device") or {}
        offset = raw.get("utc_offset_seconds")
        device = DeviceInfo(
            udid=str(raw.get("udid", "")),
            name=str(raw.get("name", "")),
            product_type=str(raw.get("product_type", "")),
            product_version=str(raw.get("product_version", "")),
            build_version=raw.get("build_version"),
            connection=str(raw.get("connection", "usb")),
            timezone_name=raw.get("timezone_name"),
            utc_offset=None if offset is None else timedelta(seconds=int(offset)),
            platform=Platform(raw.get("platform", Platform.IOS)),
        )
        ended = obj.get("ended_at")
        return cls(
            device=device,
            source=str(obj.get("source", "unknown")),
            # Same rule as the records themselves: a timestamp without an offset
            # is rejected rather than guessed at. One function owns that so the
            # two halves of one format cannot drift apart.
            started_at=parse_timestamp(obj["started_at"]),
            format_version=version,
            ostrace_version=str(obj.get("ostrace_version", "unknown")),
            ended_at=None if ended is None else parse_timestamp(ended),
            record_count=int(obj.get("record_count", 0)),
            gap_count=int(obj.get("gap_count", 0)),
            flags=dict(obj.get("flags") or {}),
        )


class SessionWriter:
    """Create a session directory and fill it.

    The sidecar is written twice: once at open, so an interrupted capture is
    still identifiable, and again at close with the final counts.

    ``path`` is expected to come from :func:`ostrace.paths.session_path`, which
    owns the naming rules. The suffix is applied here only as a courtesy for
    callers that built a path some other way.
    """

    def __init__(
        self,
        path: Path,
        *,
        device: DeviceInfo,
        source: str,
        started_at: datetime,
        flags: dict[str, Any] | None = None,
    ) -> None:
        self.path = with_session_suffix(Path(path))
        self.path.mkdir(parents=True, exist_ok=True)
        self.meta = SessionMeta(
            device=device,
            source=source,
            started_at=started_at,
            flags=flags or {},
        )
        self._spool = SpoolWriter(self.path / SPOOL_NAME)
        self._closed = False
        self._write_meta()

    def write(self, record: Record) -> None:
        self._spool.write(record)

    def write_many(self, records: list[Record]) -> None:
        self._spool.write_many(records)

    def write_gap(self, gap: Gap) -> None:
        self._spool.write_gap(gap)

    def flush(self) -> None:
        self._spool.flush()

    def close(self, *, ended_at: datetime | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        self._spool.close()
        self.meta.ended_at = ended_at
        self.meta.record_count = self._spool.record_count
        self.meta.gap_count = self._spool.gap_count
        self._write_meta()

    def _write_meta(self) -> None:
        text = json.dumps(self.meta.to_json(), indent=2, ensure_ascii=False)
        (self.path / META_NAME).write_text(text + "\n", encoding="utf-8")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class SessionReader:
    """Open a session directory for reading.

    Works on a session that is still being written.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.is_dir():
            msg = f"not a session directory: {self.path}"
            raise StorageError(msg)
        if not (self.path / SPOOL_NAME).is_file():
            msg = f"session has no {SPOOL_NAME}: {self.path}"
            raise StorageError(msg)

        self.meta: SessionMeta | None = self._read_meta()
        #: Public so that a consumer can hold one reader rather than a session
        #: and a spool that alias each other.
        self.spool = SpoolReader(self.path / SPOOL_NAME)
        self.spool.meta = self.meta

    @property
    def truncated(self) -> bool:
        """True when the spool has no gzip trailer -- still open, or killed."""
        return self.spool.truncated

    @property
    def malformed(self) -> int:
        return self.spool.malformed

    def _read_meta(self) -> SessionMeta | None:
        meta_path = self.path / META_NAME
        if not meta_path.is_file():
            return None
        try:
            return SessionMeta.from_json(json.loads(meta_path.read_text(encoding="utf-8")))
        except (ValueError, KeyError, TypeError):
            # Deliberately narrow: an UnsupportedFormatVersionError is a
            # StorageError and is not caught here, because a file we do not
            # understand may need fields we would silently ignore. A damaged
            # sidecar loses metadata, not data -- refusing to open the records
            # because their description is corrupt would be the wrong trade for
            # a diagnostic tool.
            return None

    def items(self) -> Iterator[Record | Gap]:
        return self.spool.items()

    def records(self) -> Iterator[Record]:
        return self.spool.records()

    def gaps(self) -> Iterator[Gap]:
        return self.spool.gaps()

    def __iter__(self) -> Iterator[Record | Gap]:
        return self.items()
