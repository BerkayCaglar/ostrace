# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The toolbar and the device selector.

`docs/design/gui.md` §1 sketched a toolbar and phase 4 shipped without one, so
every primary action lived two clicks deep in a menu and there was no way at all
to say which attached device a capture should come from.

Nothing here drives a real device: the scanner is a `QThread` and its signals
are emitted by hand, which is what the platform does anyway.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("PySide6", reason="the gui extra is not installed")

from PySide6.QtCore import QRect, QSettings, Qt
from PySide6.QtWidgets import QApplication, QToolBar, QToolButton, QWidgetAction

from ostrace.devices.discovery import DeviceSummary
from ostrace.gui import icons
from ostrace.gui.models import Find
from ostrace.gui.theme import Scheme, token
from ostrace.gui.widgets.device_button import NO_DEVICE, SCANNING, DeviceButton
from ostrace.gui.windows.main import MainWindow
from ostrace.model import DeviceInfo, Level, Platform
from tests.helpers import make_record

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtGui import QAction

pytestmark = pytest.mark.gui

DEVICE = DeviceInfo(
    udid="A-UDID",
    name="Berkay's iPhone",
    product_type="iPhone18,2",
    product_version="26.5.2",
    utc_offset=dt.timedelta(hours=3),
    clock_skew=dt.timedelta(seconds=1),
    platform=Platform.IOS,
)


def _buttons(window: MainWindow) -> list[QAction]:
    """The toolbar's real buttons.

    ``actions()`` also carries the ``QWidgetAction`` wrapping the device
    selector, which is a widget rather than a command: it has no icon of its own
    and belongs to no menu.
    """
    return [
        action
        for action in window.toolbar.actions()
        if not action.isSeparator() and not isinstance(action, QWidgetAction)
    ]


@pytest.fixture
def window(qt_app: object) -> MainWindow:
    del qt_app
    return MainWindow()


def test_the_device_menu_is_never_empty(qt_app: object) -> None:
    """It is an instant-popup button, and Qt pops up nothing for a menu with no
    actions.

    The menu was filled by an asynchronous scan, so the first press showed
    nothing at all -- and then the scan landed, took the first device and
    changed the label, which looked like a control that had skipped its own
    menu. Both readings were of one empty popup.
    """
    del qt_app
    button = DeviceButton()

    assert button.menu() is not None
    assert [action.text() for action in button.menu().actions()] == [SCANNING]
    assert all(not action.isEnabled() for action in button.menu().actions())


def test_the_menu_says_it_is_looking_again_rather_than_showing_a_stale_answer(
    qt_app: object,
) -> None:
    """A menu still reading "No device attached" while the scan that would
    contradict it is running is the one moment this control is guaranteed to be
    out of date -- which is exactly when somebody has just plugged a phone in.
    """
    del qt_app
    button = DeviceButton()
    button._on_found([])
    assert [action.text() for action in button.menu().actions()] != [SCANNING]

    button.rescan()
    try:
        assert [action.text() for action in button.menu().actions()] == [SCANNING]
    finally:
        button.stop()


def test_the_application_has_a_mark_at_every_size_a_desktop_asks_for(qt_app: object) -> None:
    """There was no icon at all, so the title bar, Alt-Tab and the taskbar all
    showed Qt's default -- on Windows, a blank sheet.

    Sizes rather than one bitmap: Qt would rescale a single pixmap into exactly
    the soft edges that read as an unfinished program, at the sizes people see
    most.
    """
    del qt_app
    built = icons.app_icon()

    assert not built.isNull()
    available = {size.width() for size in built.availableSizes()}
    assert available == set(icons.APP_SIZES)


def test_the_application_mark_does_not_follow_the_theme(qt_app: object) -> None:
    """A taskbar entry that changed colour with the scheme reads as a different
    program -- and on macOS and Linux the icon is drawn by a shell that never
    asked this application what scheme it is in."""
    del qt_app
    small = icons.APP_SIZES[0]
    first = icons.app_icon().pixmap(small, small).toImage()
    icons.clear_cache()
    second = icons.app_icon().pixmap(small, small).toImage()

    assert first == second


class TestTheJumpTarget:
    """The chevrons were wired to errors and nothing else."""

    def test_choosing_a_target_moves_the_arrows(self, window: MainWindow) -> None:
        window.jump_button.set_target(Find.MARKER)

        assert window._jump is Find.MARKER
        assert "Gaps" in window.action_next_jump.toolTip()

    def test_every_kind_is_offered_and_exactly_one_is_checked(self, window: MainWindow) -> None:
        """An arrow has one meaning at a time, and the menu is where that is
        visible."""
        window.jump_button.set_target(Find.MARK)
        checked = [
            kind for kind, action in window.jump_button._actions.items() if action.isChecked()
        ]

        assert set(window.jump_button._actions) == set(Find)
        assert checked == [Find.MARK]

    def test_the_explicit_keys_keep_their_own_kinds(self, window: MainWindow) -> None:
        """Choosing a target in the toolbar must not take `Ctrl+Shift+G` away
        from somebody who already knows it."""
        window.jump_button.set_target(Find.MARK)

        assert window.action_next_error is not window.action_next_jump
        assert window.action_next_marker is not window.action_next_jump

    def test_the_choice_is_remembered(self, window: MainWindow) -> None:
        """It is a way of reading rather than a property of a capture, so it
        travels with the geometry and not with the filter."""
        window.jump_button.set_target(Find.FAULT)
        window._save_layout()

        assert MainWindow()._jump is Find.FAULT


# -- the toolbar -------------------------------------------------------------


def test_the_toolbar_exists_and_is_not_draggable(window: MainWindow) -> None:
    """A movable toolbar is a toolbar the user can put somewhere surprising and
    cannot obviously put back."""
    assert isinstance(window.toolbar, QToolBar)
    assert not window.toolbar.isMovable()
    assert not window.toolbar.isFloatable()


def test_every_toolbar_button_is_an_existing_action(window: MainWindow) -> None:
    """The toolbar is a second way to reach a verb, never a second one.

    Each entry names an action that already exists with a menu item and a
    shortcut, so a button cannot acquire behaviour of its own -- and the menu
    audit, which counts items against `BINDINGS`, still covers all of it.
    """
    assert _buttons(window), "an empty toolbar would pass every assertion here"
    assert set(_buttons(window)) <= set(window.menu_items())


def test_the_three_verbs_that_differ_carry_their_labels(window: MainWindow) -> None:
    """An unlabelled icon row is the specific thing people name when they call
    a tool dated, and these are the three whose consequences are not guessable
    from a glyph: one starts a device stream, one freezes a view, one releases
    the hardware."""
    for name in ("action_capture", "action_pause", "action_disconnect"):
        button = window.toolbar.widgetForAction(getattr(window, name))
        assert isinstance(button, QToolButton)
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        assert button.text()


def test_every_toolbar_action_has_an_icon(window: MainWindow) -> None:
    for action in _buttons(window):
        assert not action.icon().isNull(), action.text()


def test_the_icons_are_the_scheme_they_are_drawn_for(window: MainWindow) -> None:
    """A `QIcon` built from an SVG file does not recolour itself, so the tint is
    substituted in the markup and the pixmaps are as scheme-specific as the
    palette. Left un-rebuilt, a theme switch draws light-scheme glyphs on a dark
    toolbar."""

    def opaque(scheme: Scheme) -> set[str]:
        image = icons.icon("play", scheme).pixmap(icons.ICON_SIZE, icons.ICON_SIZE).toImage()
        return {
            image.pixelColor(x, y).name()
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).alpha() > 200
        }

    assert token("text-secondary", Scheme.LIGHT).name() in opaque(Scheme.LIGHT)
    assert token("text-secondary", Scheme.DARK).name() in opaque(Scheme.DARK)
    assert opaque(Scheme.LIGHT) != opaque(Scheme.DARK)

    window.set_scheme(Scheme.DARK)
    assert not window.action_capture.icon().isNull()


# -- the device selector -----------------------------------------------------


def test_with_nothing_attached_the_button_says_so(qt_app: object) -> None:
    """A control with no text reads as a rendering fault rather than an answer."""
    del qt_app
    button = DeviceButton()
    button._on_found([])
    assert button.text() == NO_DEVICE
    assert button.udid is None


def test_the_first_device_is_chosen_so_that_one_device_is_no_clicks(
    qt_app: object,
) -> None:
    """Which is what the capture did before this existed. The difference is that
    the name is now on screen rather than implied."""
    del qt_app
    button = DeviceButton()
    button._on_found([DeviceSummary("A-UDID", "usb"), DeviceSummary("B-UDID", "usb")])
    assert button.udid == "A-UDID"


def test_a_name_replaces_the_udid_when_the_device_answers(qt_app: object) -> None:
    """Identifying a device is a lockdown session and a round trip, so the menu
    is built from udids first and upgraded as each answer arrives. A menu that
    waited for all of them would hang the toolbar on a sleeping phone."""
    del qt_app
    button = DeviceButton()
    button._on_found([DeviceSummary("A-UDID", "usb")])
    assert "A-UDID" in button.text()

    button._on_identified("A-UDID", DEVICE)
    assert button.text() == DEVICE.name


def test_choosing_a_device_is_what_the_capture_uses(window: MainWindow) -> None:
    """`OsTraceSource` has always taken a udid; nothing ever passed one."""
    from ostrace.sources.os_trace import OsTraceSource

    window.device_button._on_found([DeviceSummary("A-UDID", "usb"), DeviceSummary("B-UDID", "usb")])
    window.device_button.choose("B-UDID")

    source = window._build_source()
    # `isinstance` rather than reading the attribute off the protocol: `udid`
    # belongs to this source, and the window's contract is a `LogSource`.
    assert isinstance(source, OsTraceSource)
    assert source.udid == "B-UDID"


def test_the_selector_is_disabled_while_a_capture_holds_the_device(
    window: MainWindow,
) -> None:
    """Changing device mid-capture would either do nothing or apply to the next
    one, and both are worse than saying you have to disconnect first.

    `busy_udid` is the other half: a scan already in flight must not open a
    second lockdown against the device the capture thread is blocked on.
    """
    window.device_button._on_found([DeviceSummary("A-UDID", "usb")])

    window._set_capturing(capturing=True)
    assert not window.device_button.isEnabled()
    assert window.device_button.busy_udid == "A-UDID"

    window._set_capturing(capturing=False)
    assert window.device_button.isEnabled()
    assert window.device_button.busy_udid is None


def test_stopping_a_selector_that_never_scanned_is_not_an_error(qt_app: object) -> None:
    """Closing the window calls this whether a scan ever ran or not."""
    del qt_app
    DeviceButton().stop()


# -- what an empty table says, and what the window remembers ------------------


def test_a_cold_start_says_what_the_program_is_for(window: MainWindow) -> None:
    """Every reason the table is empty produces the same blank grid.

    A grid that says nothing is the state in which a working program and a
    broken one look identical, and it is where "dated" is most visible: the
    window has room for a sentence and spends it on ruled lines.
    """
    assert window.table._heading == "No capture open"
    assert "attached device" in window.table._detail


def test_a_running_capture_says_the_connection_is_fine(window: MainWindow) -> None:
    """A quiet device and a failed connection look identical from here."""
    window._capture_thread = object()  # type: ignore[assignment]
    window._update_placeholder()

    assert window.table._heading == "Waiting for the device"


def test_the_table_stops_explaining_itself_once_it_has_rows(window: MainWindow) -> None:
    window.model.append([make_record(0)])
    window._update_placeholder()

    assert window.table._heading == ""


def test_the_two_states_with_a_way_out_are_left_to_the_banner(window: MainWindow) -> None:
    """Saying it twice is worse than saying it once.

    A filter that hides everything and a capture with no records both have an
    action the banner can offer; the table's placeholder cannot offer one, so
    it stays quiet under them.
    """
    window.model.append([make_record(0)])
    window.filter_bar._process.setText("no-such-process")
    window._apply_filter()

    assert window.model.rowCount() == 0
    assert "hidden by the filter" in window.banner.text
    assert window.table._heading == ""


def test_the_status_bar_says_how_much_the_filter_hides(window: MainWindow) -> None:
    """The one readout every competing tool is missing, and the one whose
    absence produces the recurring "where did my logs go".

    `hidden_by_filter` has been on the model since it was written and nothing in
    the application ever read it.
    """
    window.model.append([make_record(index, level=level) for index, level in enumerate(Level)])
    window._update_counts()
    assert window.status.shown_text == "", "nothing hidden, nothing to say"

    window.filter_bar._level.setCurrentIndex(4)
    window._apply_filter()

    assert window.status.shown_text.endswith(f"of {window.model.retained:,} shown")
    assert window.model.rowCount() < window.model.retained


def test_the_layout_survives_a_restart(window: MainWindow, tmp_path: Path) -> None:
    """`gui.app` has set the organisation and application names since it was
    written -- which is what stops Qt filing settings under a vendor called
    "Unknown" -- and nothing ever constructed a `QSettings` to use them.

    Written to a temporary file rather than the real location: a test that
    reached into the user's own settings would be a test that changed them.
    """
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))

    window.table.setColumnWidth(0, 321)
    window._save_layout()

    reopened = MainWindow()
    assert reopened._restore_layout()
    assert reopened.table.columnWidth(0) == 321


def test_nothing_is_restored_on_a_first_run(window: MainWindow, tmp_path: Path) -> None:
    """With no saved geometry the window must fall through to its own ratio
    rather than opening at whatever size Qt last happened to compute."""
    del window
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "empty")
    )
    assert not MainWindow()._restore_layout()


def test_an_unusable_saved_geometry_is_refused(window: MainWindow) -> None:
    """A geometry can be well-formed and still impossible to look at.

    Found the hard way: the suite closed a window, `closeEvent` saved the
    layout of an *offscreen* one into the real settings, and the next launch on
    a real display restored it somewhere no screen could show. The program
    looked as though it had failed to start.

    `restoreGeometry` reports none of that as a failure, because none of it is
    malformed -- a window on a monitor that has since been unplugged is a
    perfectly valid rectangle.
    """
    window.setGeometry(QRect(-30_000, -30_000, 10, 10))
    assert not window._on_a_screen()

    window.setGeometry(QApplication.primaryScreen().availableGeometry().adjusted(0, 0, -200, -200))
    assert window._on_a_screen()


def test_a_refused_geometry_falls_back_to_a_readable_size(tmp_path: Path) -> None:
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))

    saved = MainWindow()
    saved.setGeometry(QRect(-30_000, -30_000, 10, 10))
    saved._save_layout()

    reopened = MainWindow()
    assert not reopened._restore_layout(), "an unusable geometry must not be adopted"
    assert reopened.width() >= 200
    assert reopened.height() >= 200
