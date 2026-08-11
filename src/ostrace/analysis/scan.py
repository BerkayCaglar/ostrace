# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Folding a capture into the few numbers worth reporting.

A capture is too large to read and too repetitive to summarise by sampling. What
makes it tractable is that a handful of templates account for most of it: on the
committed fixture, 5,000 records reduce to 921 templates, and the top twenty
cover a third of the log.

Everything here is single-pass and bounded. A scan of two million records must
not cost two million records of memory, so the only unbounded structure --
distinct templates -- is capped, and what the cap dropped is *counted* rather
than quietly discarded. A summary that silently omits things is worse than no
summary, because it reads as complete.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ostrace.analysis.templates import normalise
from ostrace.model import Gap, Level, Record

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

__all__ = ["MAX_TEMPLATES", "MinuteStats", "ScanResult", "TemplateKey", "TemplateStats", "scan"]

#: Distinct templates held before the scan stops learning new ones. Reached only
#: by a capture that is either enormous or pathological -- the fixture produces
#: 921 -- and at roughly 200 bytes a template this bounds the scan at ~10 MB.
MAX_TEMPLATES = 50_000

#: Records kept verbatim on either side of the first error. Templating is what
#: makes a large capture describable, and it is also what hides the one value
#: that mattered; a window of untouched records is the antidote. Both numbers
#: are small and fixed, so the memory this costs does not grow with the capture.
EXCERPT_BEFORE = 60
EXCERPT_AFTER = 140

#: Written wherever a record carries no value. An empty field between two tabs
#: is ambiguous to read and easy to mis-split; a literal dash is not. Part of
#: the bundle contract -- see docs/formats/agent-bundle.md.
ABSENT = "-"


#: ``(level, process, subsystem)`` plus the normalised message.
TemplateKey = tuple[Level, str, str, str]


@dataclass(slots=True)
class TemplateStats:
    """One distinct message template."""

    count: int
    #: Line number in ``session.log`` where this template first appears, so a
    #: reader can go straight to an instance instead of searching for one.
    first_line: int
    #: An unnormalised message, kept so a report can show what the template
    #: actually looks like in the log.
    example: str


@dataclass(slots=True)
class MinuteStats:
    records: int
    errors: int
    first_line: int


@dataclass(slots=True)
class ScanResult:
    """What a single pass over a capture learned.

    Also the accumulator: the exporter writes ``session.log`` and folds
    statistics in the same pass, because the line numbers this records are line
    numbers *in that file*. Feeding records straight to :meth:`add` is what the
    tests do, and keeps the analysis independent of any exporter.
    """

    records: int = 0
    errors: int = 0
    #: Total message characters, for the average record length a report quotes.
    message_chars: int = 0

    levels: Counter[Level] = field(default_factory=Counter)
    processes: Counter[str] = field(default_factory=Counter)
    process_errors: Counter[str] = field(default_factory=Counter)
    subsystems: Counter[str] = field(default_factory=Counter)
    subsystem_errors: Counter[str] = field(default_factory=Counter)

    minutes: dict[datetime, MinuteStats] = field(default_factory=dict)
    templates: dict[TemplateKey, TemplateStats] = field(default_factory=dict)
    #: Records whose template was not learned because the cap was reached. They
    #: are still counted everywhere else; only the template is missing.
    templates_dropped: int = 0

    #: Earliest and latest timestamps, not first and last seen. Under load a
    #: device emits slightly out of order -- measured at about 0.065% of records
    #: -- so "the capture covers X to Y" has to be a minimum and a maximum.
    first: datetime | None = None
    last: datetime | None = None

    #: Outages recorded during capture. A reader who does not know the log has
    #: a hole in it will explain the hole as the absence of an event.
    gaps: list[Gap] = field(default_factory=list)

    #: A real record, and where it is, so generated documentation can show one
    #: rather than describe one. An error is preferred: the example then also
    #: shows what a problem looks like in this capture.
    sample: Record | None = None
    sample_line: int = 0

    #: Untouched records around the first error, in order, and the
    #: ``session.log`` line the window starts at. Empty when the capture has no
    #: errors -- there is nothing to centre a window on, and an arbitrary window
    #: would imply one.
    excerpt: list[Record] = field(default_factory=list)
    excerpt_line: int = 0
    _preceding: deque[Record] = field(
        default_factory=lambda: deque(maxlen=EXCERPT_BEFORE), repr=False
    )
    _excerpt_remaining: int = field(default=0, repr=False)

    def add(self, record: Record, line: int) -> None:
        """Fold one record in, at its 1-based line number in ``session.log``."""
        self.records += 1
        self.message_chars += len(record.message)
        self.levels[record.level] += 1

        is_error = record.is_error
        if is_error:
            self.errors += 1

        self.processes[record.process] += 1
        subsystem = record.subsystem or ABSENT
        self.subsystems[subsystem] += 1
        if is_error:
            self.process_errors[record.process] += 1
            self.subsystem_errors[subsystem] += 1

        stamp = record.timestamp
        if self.first is None or stamp < self.first:
            self.first = stamp
        if self.last is None or stamp > self.last:
            self.last = stamp

        minute = stamp.replace(second=0, microsecond=0)
        bucket = self.minutes.get(minute)
        if bucket is None:
            self.minutes[minute] = MinuteStats(1, int(is_error), line)
        else:
            bucket.records += 1
            bucket.errors += int(is_error)

        key: TemplateKey = (record.level, record.process, subsystem, normalise(record.message))
        template = self.templates.get(key)
        if template is not None:
            template.count += 1
        elif len(self.templates) < MAX_TEMPLATES:
            self.templates[key] = TemplateStats(1, line, record.message)
        else:
            self.templates_dropped += 1

        if self.sample is None or (is_error and not self.sample.is_error):
            self.sample = record
            self.sample_line = line

        self._collect_excerpt(record, line, is_error=is_error)

    def _collect_excerpt(self, record: Record, line: int, *, is_error: bool) -> None:
        """Keep a verbatim window around the *first* error.

        The first, not the worst or the most frequent: an investigation starts
        at the earliest point something went wrong, and everything after it may
        be consequence rather than cause.
        """
        if self._excerpt_remaining:
            self.excerpt.append(record)
            self._excerpt_remaining -= 1
        elif not self.excerpt and is_error:
            self.excerpt = [*self._preceding, record]
            self.excerpt_line = line - len(self._preceding)
            self._excerpt_remaining = EXCERPT_AFTER
            self._preceding.clear()
        elif not self.excerpt:
            # Only worth paying for until a window has been taken.
            self._preceding.append(record)

    def add_gap(self, gap: Gap) -> None:
        self.gaps.append(gap)

    @property
    def average_message_length(self) -> int:
        """Used to warn a reader how many matches will fit in a tool's output."""
        return self.message_chars // self.records if self.records else 0

    def top_error_templates(self, limit: int = 10) -> list[tuple[TemplateKey, TemplateStats]]:
        """The error templates worth reading first, most frequent first.

        Frequency is the point rather than severity: iOS logs a great deal of
        routine chatter at ``Error``, so the question that decides whether a
        finding is real is how often the thing normally happens.
        """
        errors = [(k, v) for k, v in self.templates.items() if k[0] >= Level.ERROR]
        errors.sort(key=lambda kv: -kv[1].count)
        return errors[:limit]


def scan(items: Iterable[Record | Gap]) -> ScanResult:
    """Fold a session into a :class:`ScanResult`.

    Line numbers are assigned as records are seen, which matches ``session.log``
    exactly because that file holds every record in arrival order and nothing
    else. Gaps take no line: they are not records, and numbering them would put
    every pointer after the first outage one out of step.
    """
    result = ScanResult()
    line = 0
    for item in items:
        if isinstance(item, Record):
            line += 1
            result.add(item, line)
        else:
            result.add_gap(item)
    return result
