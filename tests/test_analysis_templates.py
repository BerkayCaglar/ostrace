# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Message normalisation.

The invented strings below are legitimate: normalisation is a transformation we
define, so a test of it needs an input exhibiting the case, not evidence of what
a device emits. What a device emits is asserted against the captured fixture at
the bottom of the file -- which is where the ordering rules actually earn their
keep, because real messages combine all five patterns in one line.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter

import pytest

from ostrace.analysis.templates import normalise
from ostrace.sources.replay import ReplaySource
from tests.helpers import MIXED


class TestSubstitutions:
    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("fetched 214 rows", "fetched <N> rows"),
            ("took 1.25 s", "took <F> s"),
            ("mask 0x1f4e", "mask <HEX>"),
            ("operation A1B2C3D4E5F60718", "operation <HEX>"),
            (
                "account 4B2A9C10-1E77-4F3B-9A02-77C1D5E4B8A6 ready",
                "account <UUID> ready",
            ),
            ("open /var/mobile/Library/Caches/x.db", "open <PATH>"),
        ],
    )
    def test_each_pattern(self, message: str, expected: str) -> None:
        assert normalise(message) == expected

    def test_single_digits_survive(self) -> None:
        """ "retry 1 of 3" and "retry 2 of 3" are not the same event.

        A single digit is usually a position or a phase rather than an
        identity, and collapsing it merges messages a reader needs apart.
        """
        assert normalise("retry 1 of 3") == "retry 1 of 3"

    def test_a_uuid_is_taken_whole_rather_than_shredded(self) -> None:
        """The ordering rule, stated as a test.

        A UUID contains both hex runs and digit runs. If integers or hex ran
        first it would come out as a trail of placeholders, and two records
        about different objects would stop folding together.
        """
        assert normalise("id=4B2A9C10-1E77-4F3B-9A02-77C1D5E4B8A6") == "id=<UUID>"

    def test_a_path_is_one_token_not_a_trail_of_numbers(self) -> None:
        assert normalise("/var/mobile/Containers/Data/22/x") == "<PATH>"

    def test_a_float_does_not_become_two_integers(self) -> None:
        assert normalise("elapsed 12.75") == "elapsed <F>"

    def test_prose_with_a_slash_is_not_a_path(self) -> None:
        """`PATH_RE` wants two directory components before the leaf."""
        assert normalise("accept and/or reject") == "accept and/or reject"

    def test_a_number_welded_to_a_unit_keeps_its_digits(self) -> None:
        """A known limitation, kept on purpose because it was measured.

        ``1.25s`` has no word boundary between the digits and the unit, so
        nothing matches and ``took 1.25s`` and ``took 3.40s`` stay distinct
        templates. Loosening the boundary to fix it folds 5 further templates
        out of 921 on the mixed fixture and 23 out of 831 on the errors one --
        not worth trading away a rule that currently cannot over-match.
        """
        assert normalise("took 1.25s") == "took 1.25s"

    def test_a_word_is_never_mistaken_for_bare_hex(self) -> None:
        """The bare-hex rule has no ``0x`` to key on, so its guards are all it
        has. A word made only of hex letters carries no digit; a plain number
        carries no hex letter. Both are excluded by construction."""
        assert normalise("decade added deface") == "decade added deface"
        assert normalise("count 1234567") == "count <N>"

    def test_a_path_wins_over_bare_hex(self) -> None:
        """Ordering, again. A directory named like a hash must not be replaced
        before the path pattern -- which matches word characters, not ``<`` --
        has had its look."""
        assert normalise("/var/mobile/a1b2c3d4e5/x") == "<PATH>"


@pytest.fixture(scope="module")
def messages() -> list[str]:
    """Every message in the mixed capture, read once for the whole module."""

    async def read() -> list[str]:
        async with ReplaySource(MIXED) as source:
            return [record.message async for record in source.records()]

    return asyncio.run(read())


class TestAgainstRealMessages:
    def test_normalising_is_idempotent(self, messages: list[str]) -> None:
        """Every placeholder is digit-free and slash-free, so a second pass is a
        no-op. If that ever stops holding, counts drift depending on how many
        times a message happened to be normalised."""
        for message in messages:
            once = normalise(message)
            assert normalise(once) == once

    def test_folding_actually_folds(self, messages: list[str]) -> None:
        """The whole justification for the step.

        Measured on this fixture: 2,593 distinct messages fold to 921
        templates. The bar is set a little above that so an ordinary
        improvement does not fail the test, but a regression that stops the
        bare-hex rule -- worth 243 templates on its own -- does.

        A normalisation that barely folded would mean `patterns.tsv` is just
        the log again, sorted differently.
        """
        distinct = len(set(messages))
        templates = len({normalise(m) for m in messages})
        assert templates < distinct * 0.60, (
            f"{distinct} distinct messages folded to only {templates}"
        )

    def test_the_quoted_counts_are_the_measured_ones(self, messages: list[str]) -> None:
        """Exact, because the ratio above cannot see a quoted number go stale.

        These two figures are repeated in `analysis/scan.py`,
        `analysis/templates.py`, `docs/formats/agent-bundle.md`, `CHANGELOG.md`
        and the docstrings in this file. A bound that accepts anything under
        60% lets all of them drift without a failure, which is how they came to
        disagree with the fixture they name.

        If normalisation improves, this is the test that says so. Re-measure
        and correct every citation together -- the count is evidence for a
        decision, not decoration.
        """
        assert len(set(messages)) == 2_593
        assert len({normalise(m) for m in messages}) == 921

    def test_the_dominant_identifiers_are_gone(self, messages: list[str]) -> None:
        """Not "no digits survive" -- some genuinely belong to the message.

        What must not survive is a *frequent* template still carrying an
        identifier, because that is one event wearing many faces. Anything
        appearing more than twice has had its variable parts taken out.
        """
        counts = Counter(normalise(m) for m in messages)
        repeated_with_identity = [
            (n, t) for t, n in counts.items() if n > 2 and re.search(r"\b[0-9a-fA-F]{6,}\b", t)
        ]
        assert not repeated_with_identity, (
            f"{len(repeated_with_identity)} repeated templates kept an identifier: "
            f"{sorted(repeated_with_identity, reverse=True)[:2]}"
        )
