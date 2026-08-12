# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading back what an earlier session wrote.

Every value here is untrusted. It was written by some version of this program,
possibly not this one, and a settings store is also a file a person can edit --
so the interesting cases are all damage, and none of them needs a window. That
is the whole reason the decoding moved out of one: these ran against a
`MainWindow` before, which meant a `QApplication`, a table, a minimap and a
capture thread in order to assert what a list of six integers turns into.

`gui` because `QSettings` is Qt, and the interpreter sweep installs the package
without it. No `QApplication` is built.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtCore import QByteArray

from ostrace.gui.columns import COLUMNS
from ostrace.gui.filters import RECENT_KEPT, Filter
from ostrace.gui.models import Find
from ostrace.gui.settings import Layout, WindowSettings

pytestmark = pytest.mark.gui


@pytest.fixture
def settings() -> WindowSettings:
    """A store of its own per test. `conftest` redirects Qt's settings path to
    a fresh directory, so this is empty and nothing leaks between tests."""
    return WindowSettings()


class TestAnEmptyStore:
    """The first run, and every run after a settings file is thrown away."""

    def test_nothing_stored_reads_as_nothing_to_restore(self, settings: WindowSettings) -> None:
        layout = settings.read_layout()

        assert layout.geometry is None
        assert layout.state is None
        assert layout.split is None
        assert layout.columns is None

    def test_the_two_that_carry_a_default_carry_it(self, settings: WindowSettings) -> None:
        """`jump` and `detail_visible` have an answer that is right when nothing
        was stored. Handing back `None` would push that decision to the caller,
        and there are two callers."""
        layout = settings.read_layout()

        assert layout.jump is Find.ERROR
        assert layout.detail_visible is True

    def test_no_theme_means_follow_the_system(self, settings: WindowSettings) -> None:
        assert settings.theme is None

    def test_no_recent_filters_is_an_empty_list(self, settings: WindowSettings) -> None:
        assert settings.read_recent() == []


class TestARoundTrip:
    def test_everything_written_comes_back(self, settings: WindowSettings) -> None:
        written = Layout(
            geometry=QByteArray(b"geometry"),
            state=QByteArray(b"state"),
            split=QByteArray(b"split"),
            columns=[10] * len(COLUMNS),
            jump=Find.MARKER,
            detail_visible=False,
        )

        settings.write_layout(written)

        assert settings.read_layout() == written

    def test_the_theme_comes_back(self, settings: WindowSettings) -> None:
        settings.theme = "dark"

        assert settings.theme == "dark"

    def test_the_recent_filters_come_back_in_order(self, settings: WindowSettings) -> None:
        wanted = [Filter(process="dasd"), Filter(process="cloudd")]

        settings.write_recent(wanted)

        assert settings.read_recent() == wanted


class TestDamage:
    """Every one of these produced a window that looked broken rather than a
    window that had lost a preference."""

    def test_a_geometry_of_the_wrong_type_is_absent(self, settings: WindowSettings) -> None:
        """`restoreGeometry` takes bytes. Handed a string it is a type error at
        the point of restoring, which is during the window's construction."""
        settings.store.setValue("window/geometry", "not bytes at all")

        assert settings.read_layout().geometry is None

    def test_widths_for_a_different_set_of_columns_are_absent(
        self, settings: WindowSettings
    ) -> None:
        """A capture opened by a version with a different set of columns would
        get widths applied to the wrong ones, which reads as a rendering fault
        rather than as stale settings."""
        settings.store.setValue("table/columns", [10] * (len(COLUMNS) - 1))

        assert settings.read_layout().columns is None

    def test_widths_that_are_not_numbers_are_absent(self, settings: WindowSettings) -> None:
        settings.store.setValue("table/columns", ["wide"] * len(COLUMNS))

        assert settings.read_layout().columns is None

    def test_a_jump_kind_this_version_does_not_offer_falls_back(
        self, settings: WindowSettings
    ) -> None:
        """Written by a version that had one more. The default is the one every
        reader wants first."""
        settings.store.setValue("table/jump", "sometime-later")

        assert settings.read_layout().jump is Find.ERROR

    def test_one_unreadable_recent_filter_costs_that_entry_only(
        self, settings: WindowSettings
    ) -> None:
        """Entry by entry rather than all or nothing: a line written by a
        version that spelled a field differently should cost that line, not the
        other nine."""
        settings.write_recent([Filter(process="dasd"), Filter(process="cloudd")])
        stored = settings.store.value("filters/recent")
        assert isinstance(stored, list)
        settings.store.setValue("filters/recent", [stored[0], "{ not json", stored[1]])

        assert settings.read_recent() == [Filter(process="dasd"), Filter(process="cloudd")]

    def test_recent_filters_that_are_not_a_list_are_no_filters(
        self, settings: WindowSettings
    ) -> None:
        settings.store.setValue("filters/recent", "process dasd")

        assert settings.read_recent() == []

    def test_more_recent_filters_than_are_kept_are_trimmed_on_the_way_in(
        self, settings: WindowSettings
    ) -> None:
        """The cap is enforced when writing too, but a store written by a
        version with a larger one is exactly the case this reads."""
        many = [Filter(process=f"p{index}") for index in range(RECENT_KEPT + 5)]
        settings.store.setValue("filters/recent", [entry.as_stored() for entry in many])

        assert settings.read_recent() == many[:RECENT_KEPT]

    def test_a_theme_of_the_wrong_type_is_no_theme(self, settings: WindowSettings) -> None:
        settings.store.setValue("window/theme", 3)

        assert settings.theme is None
