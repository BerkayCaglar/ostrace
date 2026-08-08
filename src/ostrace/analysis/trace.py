# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verbatim windows around the records you care about.

The exact counterpart to templating. :mod:`ostrace.analysis.scan` answers "what
is in this capture and how often", and to do that it throws away ordering,
interleaving and every variable value -- which are the three things you need in
order to follow one object across a sequence of records. This module keeps all
of them, and pays for it by only looking near the anchors.

Windows that overlap are **merged, not duplicated**. Two errors four records
apart are one event being described twice, and emitting two windows that share
most of their content makes a reader compare them to find out they are the same.
An anchor that lands inside an open window extends it instead.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ostrace.model import Record

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from ostrace.model import Gap

__all__ = [
    "DEFAULT_AFTER",
    "DEFAULT_BEFORE",
    "MAX_WINDOWS",
    "MAX_WINDOW_RECORDS",
    "TracePolicy",
    "TraceResult",
    "Window",
    "is_error",
    "trace",
]

#: Records kept either side of an anchor. Asymmetric on purpose: what happened
#: before an error is usually a short run-up, and what happened after is the
#: consequence you are trying to follow.
DEFAULT_BEFORE = 40
DEFAULT_AFTER = 80

#: Windows collected before the scan stops opening new ones. A trace of every
#: error in a capture with nine thousand of them is the capture again.
MAX_WINDOWS = 25

#: Records in any one window. Capping the *number* of windows is not enough:
#: an anchor inside an open window extends it, so on a dense capture the
#: extensions never stop and the single window becomes the whole log. Measured
#: on this project's error-heavy fixture -- 2,250 errors in 3,000 records -- the
#: uncapped form produced exactly one window containing everything, which is not
#: a trace of anything. A window is an excerpt somebody reads; past a few
#: hundred records it has stopped being one.
MAX_WINDOW_RECORDS = 500


@dataclass(frozen=True, slots=True)
class TracePolicy:
    """How much context to keep, and where to stop.

    Grouped rather than passed as four loose arguments because they are only
    meaningful together: a window size means nothing without a window count,
    and either alone fails to bound the output -- which is the whole job.
    """

    before: int = DEFAULT_BEFORE
    after: int = DEFAULT_AFTER
    max_windows: int = MAX_WINDOWS
    max_window_records: int = MAX_WINDOW_RECORDS


@dataclass(slots=True)
class Window:
    """A contiguous run of records, with the anchors inside it marked."""

    records: list[Record] = field(default_factory=list)
    #: Positions within :attr:`records` that matched the anchor predicate.
    anchors: list[int] = field(default_factory=list)
    #: ``session.log`` line number of ``records[0]``, so a window can be tied
    #: back to the full capture.
    first_line: int = 0
    #: Closed because it reached the size limit rather than because the run of
    #: interesting records ended. The reader is mid-sequence at the last line.
    truncated: bool = False

    @property
    def anchor_records(self) -> list[Record]:
        return [self.records[i] for i in self.anchors]


@dataclass(slots=True)
class TraceResult:
    windows: list[Window] = field(default_factory=list)
    records_scanned: int = 0
    #: Anchors found in the whole capture.
    anchors_seen: int = 0
    #: Anchors that ended up inside a window. Lower than ``anchors_seen`` once
    #: the window cap is reached, and the difference is what a report has to
    #: declare rather than let a reader assume they saw everything.
    anchors_covered: int = 0

    @property
    def anchors_missed(self) -> int:
        return self.anchors_seen - self.anchors_covered

    @property
    def truncated(self) -> bool:
        return self.anchors_missed > 0


def is_error(record: Record) -> bool:
    """The default anchor. Errors are what people trace."""
    return record.is_error


def trace(
    items: Iterable[Record | Gap],
    *,
    anchor: Callable[[Record], bool] = is_error,
    policy: TracePolicy | None = None,
) -> TraceResult:
    """Collect verbatim windows around every record matching ``anchor``.

    Single pass, and bounded in both directions: at most ``max_windows``
    windows, each of at most ``max_window_records``. Gaps are skipped rather
    than included -- a gap is not a record, and numbering it would put every
    line pointer after it out of step -- but a window spanning one is still a
    window with a hole in it, which is why the report says so.
    """
    if policy is None:
        policy = TracePolicy()
    before, after = policy.before, policy.after
    max_windows, max_window_records = policy.max_windows, policy.max_window_records

    result = TraceResult()
    preceding: deque[Record] = deque(maxlen=before)
    current: Window | None = None
    remaining = 0
    line = 0

    for item in items:
        if not isinstance(item, Record):
            continue
        line += 1
        result.records_scanned += 1
        hit = anchor(item)
        if hit:
            result.anchors_seen += 1

        if current is not None:
            current.records.append(item)
            remaining -= 1
            if hit:
                # Extend rather than open a second window. The reset happens
                # before the exhaustion check below, so an anchor arriving on
                # the very last record of a window keeps it open.
                current.anchors.append(len(current.records) - 1)
                result.anchors_covered += 1
                remaining = after
            if len(current.records) >= max_window_records:
                # Size wins over the extension. Without this a dense capture
                # extends one window forever and the trace becomes the log.
                current.truncated = True
                result.windows.append(current)
                current = None
            elif remaining == 0:
                result.windows.append(current)
                current = None
            continue

        if hit and len(result.windows) < max_windows:
            result.anchors_covered += 1
            current = Window(
                records=[*preceding, item],
                anchors=[len(preceding)],
                first_line=line - len(preceding),
            )
            remaining = after
            # The run-up has been consumed into this window; keeping it would
            # repeat those records at the head of the next one.
            preceding.clear()
        else:
            preceding.append(item)

    if current is not None:
        # The capture ended mid-window. Shorter than the others, and real.
        result.windows.append(current)

    return result
