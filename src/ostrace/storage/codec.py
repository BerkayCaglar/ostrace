# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning records into JSON lines and back.

This is a format contract, documented in ``docs/formats/session-file.md``. Two
rules hold it together:

* **Readers ignore unknown keys.** That is what allows a field to be added
  without a version bump, and it is why ``platform`` is written from the first
  release even though only one platform exists -- adding a key to a format that
  is already on disk is free, adding one that readers reject is not.
* **Levels are written by name, never by number.** The numeric values in
  :class:`~ostrace.model.Level` are spaced so new levels can be inserted, which
  would silently reinterpret every file already written if numbers were stored.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ostrace.errors import SessionCorruptError
from ostrace.model import Gap, Level, Platform, Record

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["decode", "encode_gap", "encode_record"]


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
    out.update(
        {
            key: value
            for key, value in (
                ("subsystem", record.subsystem),
                ("category", record.category),
                ("thread_id", record.thread_id),
                ("image_path", record.image_path),
            )
            if value is not None
        }
    )
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
                start=_timestamp(obj["from"]),
                end=_timestamp(obj["to"]),
                reason=str(obj.get("reason", "unknown")),
            )
        return Record(
            timestamp=_timestamp(obj["ts"]),
            level=Level[obj["level"]],
            pid=int(obj["pid"]),
            process=str(obj["process"]),
            process_path=str(obj["process_path"]),
            subsystem=_optional_str(obj.get("subsystem")),
            category=_optional_str(obj.get("category")),
            thread_id=_optional_int(obj.get("thread_id")),
            image_path=_optional_str(obj.get("image_path")),
            message=str(obj["message"]),
            platform=Platform(obj.get("platform", Platform.IOS)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        msg = f"malformed record: {exc}"
        raise SessionCorruptError(msg) from exc


def _timestamp(raw: object) -> datetime:
    value = datetime.fromisoformat(str(raw))
    if value.tzinfo is None:
        # Every writer of this format attaches the device's offset. A naive
        # timestamp means the file was written by something else, and guessing
        # a zone here would produce a plausible wrong answer instead of a
        # visible one.
        msg = f"timestamp {raw!r} has no timezone"
        raise ValueError(msg)
    return value


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int | str):
        return int(value)
    msg = f"expected an integer, got {type(value).__name__}"
    raise ValueError(msg)
