# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning records into JSON lines and back.

This is a format contract, documented in ``docs/formats/session-file.md``. Three
rules hold it together:

* **Readers ignore unknown keys.** That is what allows a field to be added
  without a version bump, and it is why ``platform`` is written from the first
  release even though only one platform exists -- adding a key to a format that
  is already on disk is free, adding one that readers reject is not.
* **Levels are written by name, never by number.** The numeric values in
  :class:`~ostrace.model.Level` are spaced so new levels can be inserted, which
  would silently reinterpret every file already written if numbers were stored.
* **Timestamps must carry an offset.** :func:`parse_timestamp` is the single
  place that rule lives, so that the records and the metadata sidecar cannot
  end up enforcing it differently.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ostrace.errors import SessionCorruptError
from ostrace.model import Gap, Level, Platform, Record, optional_str

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["decode", "encode_gap", "encode_record", "parse_timestamp"]


def encode_record(record: Record) -> dict[str, Any]:
    """Serialise one record. Keys with no value are omitted, not written null."""
    out: dict[str, Any] = {
        "ts": record.timestamp.isoformat(),
        "level": record.level.name,
        "pid": record.pid,
        "process": record.process,
        "process_path": record.process_path,
        "message": record.message,
        "platform": str(record.platform),
    }
    # Four plain conditionals rather than a comprehension over a tuple of pairs:
    # this runs once per record, and the tidier form measured 23% slower for
    # the allocations it makes on the way.
    if record.subsystem is not None:
        out["subsystem"] = record.subsystem
    if record.category is not None:
        out["category"] = record.category
    if record.thread_id is not None:
        out["thread_id"] = record.thread_id
    if record.image_path is not None:
        out["image_path"] = record.image_path
    return out


def encode_gap(gap: Gap) -> dict[str, Any]:
    """Serialise a gap marker."""
    return {
        "gap": True,
        "from": gap.start.isoformat(),
        "to": gap.end.isoformat(),
        "reason": gap.reason,
    }


def decode(obj: Mapping[str, Any]) -> Record | Gap:
    """Deserialise one line's object.

    Raises :class:`~ostrace.errors.SessionCorruptError` rather than letting a
    ``KeyError`` or ``ValueError`` escape: a malformed line is a property of the
    file, and the caller decides whether to skip it or stop.
    """
    try:
        if obj.get("gap"):
            return Gap(
                start=parse_timestamp(obj["from"]),
                end=parse_timestamp(obj["to"]),
                reason=str(obj.get("reason", "unknown")),
            )
        return Record(
            timestamp=parse_timestamp(obj["ts"]),
            level=Level[obj["level"]],
            pid=int(obj["pid"]),
            process=str(obj["process"]),
            process_path=str(obj["process_path"]),
            subsystem=optional_str(obj.get("subsystem")),
            category=optional_str(obj.get("category")),
            thread_id=_optional_int(obj.get("thread_id")),
            image_path=optional_str(obj.get("image_path")),
            message=str(obj["message"]),
            # The one place a platform default is legitimate: a file written
            # before the key existed. Sources must always state it.
            platform=Platform(obj.get("platform", Platform.IOS)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        msg = f"malformed record: {exc}"
        raise SessionCorruptError(msg) from exc


def parse_timestamp(raw: object) -> datetime:
    """Parse a timestamp from the session format, rejecting naive ones.

    Every writer of this format attaches the device's offset. A naive timestamp
    means the file was written by something else, and guessing a zone here would
    produce a plausible wrong answer instead of a visible one.
    """
    value = datetime.fromisoformat(str(raw))
    if value.tzinfo is None:
        msg = f"timestamp {raw!r} has no timezone"
        raise ValueError(msg)
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int | str):
        return int(value)
    msg = f"expected an integer, got {type(value).__name__}"
    raise ValueError(msg)
