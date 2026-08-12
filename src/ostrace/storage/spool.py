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
yields the last complete line before giving up. Catching that truncation before
the final ``yield`` instead drops the last record of every unclosed file, which
is a whole record lost from every capture whose process was killed; there is a
regression test for exactly it.

A damaged line is always skipped and counted in :attr:`SpoolReader.malformed`,
never raised. This is a diagnostic tool: reading as far as possible and saying
how much was lost beats refusing to open a capture that is mostly intact.
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

    def __init__(self, path: Path, *, flush_every: int = DEFAULT_FLUSH_EVERY) -> None:
        self.path = path
        self.flush_every = flush_every
        self._records = 0
        self._gaps = 0
        self._since_flush = 0
        self._closed = False
        path.parent.mkdir(parents=True, exist_ok=True)
        # Held open for the life of the writer rather than per call: a capture
        # runs for an hour and reopening per record would defeat the point.
        self._fh = gzip.open(path, "wb")  # noqa: SIM115

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

    def __init__(self, path: Path) -> None:
        self.path = path
        self.malformed = 0
        self._truncated: bool | None = None

    @property
    def truncated(self) -> bool:
        """True when the spool has no gzip trailer -- still open, or killed.

        Answered on demand rather than only as a side effect of iterating. As
        a plain attribute filled in at the end of a full pass, asking "is this
        capture still being written?" *before* reading it -- the natural order
        -- always answers ``False``, and a consumer that stops iterating early
        gets the same wrong answer.

        The probe decompresses but does not parse, so it is far cheaper than a
        full pass, and any pass that does complete fills the value in for free.
        """
        if self._truncated is None:
            self._truncated = self._probe()
        return self._truncated

    def _probe(self) -> bool:
        decompressor = zlib.decompressobj(wbits=31)
        with self.path.open("rb") as raw:
            while chunk := raw.read(_CHUNK):
                try:
                    decompressor.decompress(chunk)
                except zlib.error:
                    return True
        return not decompressor.eof

    def __iter__(self) -> Iterator[Record | Gap]:
        return self.items()

    def records(self) -> Iterator[Record]:
        """Only the records, skipping gap markers."""
        for item in self.items():
            if isinstance(item, Record):
                yield item

    def gaps(self) -> Iterator[Gap]:
        """Only the gap markers.

        Filters on the raw object before decoding. A capture holds millions of
        records and a handful of gaps, and building a full
        :class:`~ostrace.model.Record` for each one only to discard it more than
        doubled the cost of this scan.
        """
        # Every object is decoded, not only the ones claiming to be gaps: the
        # counter describes the file, and a pass that skipped the records
        # reported less damage than a pass that read them. Two passes over one
        # file disagreeing about how much of it is broken is worse than the
        # decode work saved.
        for obj in self._objects():
            try:
                item = decode(obj)
            except SessionCorruptError:
                self.malformed += 1
                continue
            if isinstance(item, Gap):
                yield item

    def items(self) -> Iterator[Record | Gap]:
        for obj in self._objects():
            try:
                yield decode(obj)
            except SessionCorruptError:
                self.malformed += 1

    def _objects(self) -> Iterator[dict[str, object]]:
        # Reset per pass. The counter describes the file, not the reader, and
        # accumulating across passes made a second scan report twice the damage.
        self.malformed = 0
        for line in self.lines():
            try:
                obj = json.loads(line)
            except ValueError:
                self.malformed += 1
                continue
            if isinstance(obj, dict):
                yield obj
            else:
                self.malformed += 1

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
        # still running, or one whose process was killed. A completed pass
        # already knows the answer, so record it and save the probe.
        self._truncated = damaged or not decompressor.eof

        # Whatever is left after the last newline. The writer emits the line and
        # its newline in one call and flushes on a line boundary, so this is
        # normally empty; it is non-empty only when the file was cut mid-line.
        # It is still yielded: a partial line is the reader's to reject, and
        # discarding the tail unexamined is how the last record of an unclosed
        # file goes missing.
        if buffer:
            yield buffer
