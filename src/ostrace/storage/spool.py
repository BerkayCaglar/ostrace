# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The gzip JSON-Lines spool.

Records go to disk as they arrive and the viewer keeps only a bounded window in
memory, so capture length is bounded by disk rather than by RAM. An hour at a
thousand records a second is several million records; holding those in a list is
what limited the predecessor tool.

Two properties are load-bearing.

**A spool is readable while it is still being written.** The writer emits a
``Z_SYNC_FLUSH`` boundary periodically, which ends a deflate block on a byte
boundary, so a reader can decompress everything up to that point without the
stream being closed. Live export during capture depends on it, and so does
recovering a capture whose process was killed.

**The reader tolerates a missing trailer.** A file that was never closed has no
gzip CRC at the end. The reader decompresses incrementally and treats truncation
as the end of the data rather than as an error -- and, specifically, still
yields the last complete line before giving up. An earlier implementation
dropped the final record of every unclosed file because the exception was caught
before the final ``yield``; there is a regression test for exactly that.
"""

from __future__ import annotations

import gzip
import json
import zlib
from typing import TYPE_CHECKING

from ostrace.errors import SessionCorruptError
from ostrace.model import Gap, Record
from ostrace.storage.codec import decode, encode_gap, encode_record

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import TracebackType
    from typing import Self

__all__ = ["SpoolReader", "SpoolWriter"]

#: Flush to a readable boundary at least this often.
DEFAULT_FLUSH_EVERY = 500

_CHUNK = 1 << 16


class SpoolWriter:
    """Append records to a gzip JSON-Lines file.

    Not thread-safe and not shared: one capture owns one writer.
    """

    def __init__(
        self,
        path: Path,
        *,
        flush_every: int = DEFAULT_FLUSH_EVERY,
        compresslevel: int = 6,
    ) -> None:
        self.path = path
        self.flush_every = flush_every
        self._records = 0
        self._gaps = 0
        self._since_flush = 0
        self._closed = False
        path.parent.mkdir(parents=True, exist_ok=True)
        # Held open for the life of the writer rather than per call: a capture
        # runs for an hour and reopening per record would defeat the point.
        self._fh = gzip.open(path, "wb", compresslevel=compresslevel)  # noqa: SIM115

    @property
    def record_count(self) -> int:
        return self._records

    @property
    def gap_count(self) -> int:
        return self._gaps

    def write(self, record: Record) -> None:
        self._write_obj(encode_record(record))
        self._records += 1

    def write_gap(self, gap: Gap) -> None:
        self._write_obj(encode_gap(gap))
        self._gaps += 1
        # A gap means the stream just broke. Make it durable now rather than
        # keep it in a buffer that the next failure may take with it.
        self.flush()

    def write_many(self, records: list[Record]) -> None:
        for record in records:
            self.write(record)

    def _write_obj(self, obj: dict[str, object]) -> None:
        if self._closed:
            msg = "spool is closed"
            raise ValueError(msg)
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        self._fh.write(line.encode("utf-8"))
        self._fh.write(b"\n")
        self._since_flush += 1
        if self._since_flush >= self.flush_every:
            self.flush()

    def flush(self) -> None:
        """End a deflate block so that everything written so far is readable.

        ``Z_SYNC_FLUSH`` rather than a full flush: it costs a few bytes of
        padding and keeps the compression window, where ``Z_FULL_FLUSH`` would
        reset it and cost real ratio at this record rate.
        """
        if self._closed:
            return
        self._fh.flush(zlib.Z_SYNC_FLUSH)
        self._since_flush = 0

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._fh.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class SpoolReader:
    """Read a spool, closed or not.

    Iterating yields :class:`~ostrace.model.Record` and
    :class:`~ostrace.model.Gap` in the order they were written.
    """

    def __init__(self, path: Path, *, skip_malformed: bool = True) -> None:
        self.path = path
        self.skip_malformed = skip_malformed
        self.truncated = False
        self.malformed = 0

    def __iter__(self) -> Iterator[Record | Gap]:
        return self.items()

    def records(self) -> Iterator[Record]:
        """Only the records, skipping gap markers."""
        for item in self.items():
            if isinstance(item, Record):
                yield item

    def gaps(self) -> Iterator[Gap]:
        for item in self.items():
            if isinstance(item, Gap):
                yield item

    def items(self) -> Iterator[Record | Gap]:
        for line in self.lines():
            try:
                obj = json.loads(line)
            except ValueError:
                self.malformed += 1
                if self.skip_malformed:
                    continue
                raise
            try:
                yield decode(obj)
            except SessionCorruptError:
                self.malformed += 1
                if not self.skip_malformed:
                    raise

    def lines(self) -> Iterator[str]:
        """Yield decoded lines, stopping cleanly at truncation.

        Written against ``zlib`` rather than ``gzip.open`` on purpose: the file
        may have no trailer, and the high-level reader raises ``EOFError`` at
        the point where the last line still needs emitting.
        """
        decompressor = zlib.decompressobj(wbits=31)  # 31 = gzip container
        buffer = ""
        damaged = False

        with self.path.open("rb") as raw:
            while True:
                chunk = raw.read(_CHUNK)
                if not chunk:
                    break
                try:
                    buffer += decompressor.decompress(chunk).decode("utf-8", "replace")
                except zlib.error:
                    # Damage part-way through. Everything already decoded is
                    # still good, so surface that rather than nothing.
                    damaged = True
                    break

                *complete, buffer = buffer.split("\n")
                yield from complete

        # No gzip trailer means the writer never closed the file -- a capture
        # still running, or one whose process was killed.
        self.truncated = damaged or not decompressor.eof

        # Whatever is left after the last newline. The writer emits the line and
        # its newline in one call and flushes on a line boundary, so this is
        # normally empty; it is non-empty only when the file was cut mid-line.
        # It is still yielded: a partial line is the reader's to reject, and
        # discarding the tail unexamined is how the last record of an unclosed
        # file goes missing.
        if buffer:
            yield buffer
