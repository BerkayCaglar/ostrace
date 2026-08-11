# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Message normalisation: reducing a message to its template.

Two records that say the same thing about different objects should be counted
together. ``Fetched 214 items for account <UUID>`` and ``Fetched 3 items for
account <UUID>`` are one event that happened twice, not two events, and a
report that cannot tell those apart from two genuinely distinct messages is a
report of the log's cardinality rather than of its content.

This is the step that decides whether a finding is real. iOS logs a great deal
of routine chatter at ``Error`` level; the question is never "is there an error"
but "does this one fire fourteen times a minute normally".
"""

from __future__ import annotations

import re

__all__ = ["normalise"]

#: Substitutions, applied in this order. **The order is load-bearing** -- each
#: pattern would be shredded by a later one if it ran second.
#:
#: - A UUID contains both hex runs and digit runs, so it has to be taken whole
#:   before anything else looks at it.
#: - ``0x1f4`` is matched by the integer pattern once its ``0x`` prefix has been
#:   consumed, so hex precedes integers.
#: - Paths are full of numbers (``/var/mobile/Containers/Data/22``); replacing
#:   them first keeps a path one token instead of a trail of ``<N>``.
#: - ``1.5`` would become ``<N>.<N>`` if integers went first.
_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b"), "<UUID>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<HEX>"),
    # Two or more directory components before the leaf, so that a bare
    # ``and/or`` in prose is not mistaken for a path.
    (re.compile(r"/(?:[\w.\-@+]+/){2,}[\w.\-@+]*"), "<PATH>"),
    # Hex with no ``0x`` to announce it: operation identifiers, content
    # references, protection tags. iOS logs these constantly and they are pure
    # identity, so leaving them gives every object its own template -- measured
    # on the mixed fixture, this one rule folds 1,164 templates down to 921.
    #
    # Both lookaheads are the guard: requiring at least one digit *and* at least
    # one hex letter excludes plain decimals, which ``<N>`` already handles, and
    # excludes English words, which contain no digits. Six characters is the
    # floor, so short words like ``added`` are never in range.
    #
    # Deliberately after ``<PATH>``: a directory named like a hash would
    # otherwise be replaced first, and the path pattern -- which matches word
    # characters -- would no longer recognise what was left.
    (
        re.compile(r"\b(?=[0-9a-fA-F]*\d)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{6,}\b"),
        "<HEX>",
    ),
    (re.compile(r"-?\b\d+\.\d+\b"), "<F>"),
    # Two digits or more. Single digits usually carry meaning rather than
    # identity -- "retry 1 of 3", "phase 2" -- and collapsing them merges
    # messages that a reader needs to see separately.
    (re.compile(r"-?\b\d{2,}\b"), "<N>"),
)


def normalise(message: str) -> str:
    """Reduce a message to its template.

    Numbers become ``<N>``, floats ``<F>``, hex ``<HEX>``, UUIDs ``<UUID>`` and
    paths ``<PATH>``. Messages that normalise identically are the same event.
    """
    for pattern, placeholder in _SUBSTITUTIONS:
        message = pattern.sub(placeholder, message)
    return message
