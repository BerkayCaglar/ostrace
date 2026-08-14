# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the window says to something that cannot see it.

Two rules, and both were broken in the way that leaves a suite green: a control
whose only label is an icon has *no* name, and a widget that announces state by
appearing announces it to nobody who is not looking at that part of the screen.

Nothing here needs a screen reader. Qt's accessibility interface is queryable
from the same process, which is what makes these assertions rather than a
manual pass somebody has to remember to repeat.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtGui import QAccessible, QAccessibleEvent
from PySide6.QtWidgets import QToolButton

from ostrace.gui.widgets import banner
from ostrace.gui.widgets.detail_pane import DetailPane
from ostrace.gui.windows.main import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qt_app: object) -> MainWindow:
    del qt_app
    return MainWindow()


class TestEveryControlHasAName:
    """A tooltip is not a name: it needs a pointer to be hovering over it."""

    def test_the_icon_only_toolbar_buttons_do(self, window: MainWindow) -> None:
        """Stripping the label is what makes the row look modern and what takes
        away the only thing a screen reader had."""
        stripped = [
            button
            for entry in window._TOOLBAR
            if entry is not None and not entry[2]
            if isinstance(
                button := window.toolbar.widgetForAction(getattr(window, entry[0])), QToolButton
            )
        ]
        assert stripped, "no icon-only buttons, so this proves nothing"

        for button in stripped:
            assert button.accessibleName(), f"{button.text()!r} has no name"
            assert "&" not in button.accessibleName(), "the accelerator marker is read aloud"

    def test_the_controls_whose_text_is_their_value_do(self, window: MainWindow) -> None:
        """The device button and the jump button both carry an *answer* --
        a device name, `Errors` -- so read out alone they name a thing rather
        than a control, and give no clue that the thing is settable."""
        assert window.device_button.accessibleName() == "Device"
        assert window.jump_button.accessibleName() == "Jump target"

    def test_the_overview_strip_does(self, window: MainWindow) -> None:
        """It is a control -- clicking it jumps -- drawn entirely by us, with
        no text and no icon to infer a purpose from."""
        assert window.minimap.accessibleName()
        assert window.minimap.accessibleDescription()

    def test_the_close_glyph_says_what_it_does(self, qt_app: object) -> None:
        """`✕` is announced as "multiplication sign".

        And it must not read as "close the pane": putting the pane away is
        `Ctrl+I`, and two controls a keystroke apart that both read as "close"
        are two nobody can choose between.
        """
        del qt_app
        pane = DetailPane()

        name = pane._close.accessibleName()

        assert name
        assert "✕" not in name
        assert "row" in name.lower()

    def test_the_filter_fields_are_tied_to_their_labels(self, window: MainWindow) -> None:
        """A `QLabel` beside a field is a label to somebody looking at it and
        nothing at all to anything reading the window."""
        bar = window.filter_bar

        assert bar._process.accessibleName() == "Process"
        assert bar._subsystem.accessibleName() == "Subsystem"
        assert bar._search.accessibleName() == "Search"
        assert bar._level.accessibleName() == "Level"

    def test_the_in_field_toggles_say_which_field_they_belong_to(self, window: MainWindow) -> None:
        """They have no visible label at all -- an icon inside a text field --
        so the action's own text is the whole of what is read aloud. And it
        has to name the *field*: three toggles announced as "Exclude" are
        three a listener cannot tell apart."""
        bar = window.filter_bar

        assert bar._process_exclude.text() == "Exclude this process"
        assert bar._subsystem_exclude.text() == "Exclude this subsystem"
        assert bar._regex.text() == "Regular expression"


class TestTheBannerAnnouncesItself:
    """Every state this project calls "must be visible" arrives here.

    A paused stream, a filter hiding everything, a capture that died. Visible
    is not the same as perceivable: a screen reader follows focus, and the
    banner never takes it.
    """

    def test_showing_one_raises_an_alert(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`Alert` is the one accessibility event announced without focus,
        which is exactly what this widget is for.

        Observed by standing in for `QAccessible` in the banner's own module.
        PySide6 exposes no update handler to listen with, and
        `updateAccessibility` is a no-op anyway while nothing is actually
        reading the screen -- so a test that only called it would pass whatever
        event it raised, including none.
        """
        raised: list[tuple[object, object]] = []

        class Spy:
            Event = QAccessible.Event

            @staticmethod
            def updateAccessibility(event: QAccessibleEvent) -> None:  # noqa: N802 - Qt's name
                raised.append((event.object(), event.type()))

        monkeypatch.setattr(banner, "QAccessible", Spy)

        window.banner.show_message("the device stopped talking", "Retry")

        assert raised == [(window.banner, QAccessible.Event.Alert)]
        assert window.banner.accessibleName() == "the device stopped talking"

    def test_the_name_follows_the_message(self, window: MainWindow) -> None:
        """The alert carries no text of its own: what is announced is whatever
        the widget's name says at the moment it fires. A name left over from
        the previous banner would announce the wrong state."""
        window.banner.show_message("the view is paused", "Resume")
        window.banner.show_message("all 40 records are hidden by the filter", "Clear filter")

        assert window.banner.accessibleName() == "all 40 records are hidden by the filter"
