# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The main window.

Two things here are not obvious and both come from `docs/design/gui.md`.

**Every action declares its menu role.** On macOS, Qt applies *text heuristics*
to menu items: anything matching ``settings``/``options``/``preferences``/
``config``/``setup`` is moved into the application menu, ``about.*`` into
About, ``quit``/``exit`` into Quit. The default for every action is
``TextHeuristicRole`` -- verified, not assumed -- so an item is opted *into*
being relocated unless it says otherwise. A "Settings…" entry silently
disappears from its own menu on the one platform that cannot be tested here.
`test_gui_window.py` asserts that no action is left on the default.

**Pause and Disconnect are different verbs and must stay that way.** Pause
freezes the view and never touches the source. This project already learned
that releasing a device releases the lockdown session *and* the
``os_trace_relay`` service together, so a pause that reached the source would
be a disconnect wearing a friendlier label, and everything that arrived during
it would be gone. The destructive control is therefore named after its
consequence.
"""

from __future__ import annotations

from html import escape as escape_html
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QModelIndex,
    QPoint,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ostrace import __version__
from ostrace.errors import OstraceError
from ostrace.exporters.base import escape
from ostrace.gui import icons
from ostrace.gui.actions import build_actions, build_menus, menu_items
from ostrace.gui.capture_controller import CaptureController, Lifecycle
from ostrace.gui.columns import COLUMNS
from ostrace.gui.filters import Filter, SavedFilter, remember, save
from ostrace.gui.follow import FollowController
from ostrace.gui.loader import CaptureLoader
from ostrace.gui.markers import when
from ostrace.gui.models import Find, RecordModel
from ostrace.gui.settings import Layout, WindowSettings
from ostrace.gui.shortcuts import key_table
from ostrace.gui.theme import Scheme
from ostrace.gui.theme_policy import ThemePolicy
from ostrace.gui.timeinput import EXAMPLES, parse_jump
from ostrace.gui.widgets.banner import Banner, Notice
from ostrace.gui.widgets.detail_pane import DetailPane
from ostrace.gui.widgets.device_button import DeviceButton
from ostrace.gui.widgets.export_dialog import ExportDialog
from ostrace.gui.widgets.filter_bar import FilterBar
from ostrace.gui.widgets.jump_button import JumpButton
from ostrace.gui.widgets.log_table import LogTable
from ostrace.gui.widgets.minimap import Minimap
from ostrace.gui.widgets.saved_filters_dialog import SavedFiltersDialog
from ostrace.gui.widgets.status_bar import StatusBar
from ostrace.gui.windows.doctor import open_doctor
from ostrace.model import DeviceInfo, Record
from ostrace.paths import export_stem, sessions_dir
from ostrace.sources.base import CaptureState
from ostrace.storage.capture import Capture, open_capture

if TYPE_CHECKING:
    from datetime import datetime

    # Only ever annotations here now that the action factory owns construction.
    from PySide6.QtGui import QAction, QCloseEvent, QShowEvent
    from PySide6.QtWidgets import QWidget as QWidgetType

    from ostrace.sources.base import LogSource

__all__ = ["MainWindow"]

_TITLE = "ostrace"

#: What the title says while a device is streaming, before and after its name
#: is known. Wireshark's wording, because it is the right one: the title is
#: read in a taskbar, by somebody who wants to know whether the thing is still
#: running and what it is pointed at.
#:
#: It used to be the source's own name, which is ``os_trace_relay`` -- the
#: Apple service the stream comes from. That is an implementation detail of the
#: transport, it is the same string for every device, and it answers no
#: question anybody has while looking at a window.
_CAPTURING = "Capturing"
_CAPTURING_FROM = "Capturing from {device}"

#: Between the subject and the application name. An em dash with spaces, which
#: is what every desktop uses and what Qt itself writes when it composes one.
_SEPARATOR = " — "

#: Proportions of the vertical split at first show, as stretch factors rather
#: than pixels: no fixed pixel sizes anywhere, because High DPI cannot be
#: switched off on macOS and its device pixel ratio is an integer where
#: Windows' is fractional.
_TABLE_STRETCH = 3
_DETAIL_STRETCH = 1

#: How long the filter waits for the typing to stop. Long enough that a word is
#: one rescan rather than five, short enough that the table does not feel
#: detached from the keyboard.
_FILTER_DEBOUNCE_MS = 200

#: How long a filter has to stand before it counts as one the user *used*
#: rather than one they typed through on the way to it. Without this the recent
#: list fills with `d`, `da`, `das`, `dasd` -- four entries, three of which
#: nobody ever asked for, pushing out the ones they did. Two seconds is long
#: enough that no intermediate state survives it and short enough that a filter
#: somebody is reading results under is remembered before they move on.
_FILTER_SETTLED_MS = 2_000

#: What the window opens at when there is nothing saved, or when what was saved
#: turned out to be unusable. Wide enough for the fixed columns and the start of
#: a message, which is the narrowest the table is worth reading at.
_DEFAULT_SIZE = QSize(1280, 800)

#: Below this in either direction a restored window is not something a person
#: can use, whatever the settings say.
_MIN_USABLE = 200


#: What the banner says while the device is gone and the source is retrying.
#: A constant because it is the one sentence a test asserts by name -- the
#: window itself no longer recognises it by wording, only by `Notice`.
RECONNECT_MESSAGE = "The device stopped answering. Reconnecting — records arriving now are lost."


class MainWindow(QMainWindow):
    """Toolbar, filter bar, table, detail pane, status bar."""

    #: The device came or went, reported by the source from the capture
    #: thread. A signal rather than a direct call because that is the thread
    #: boundary: emitting is queued and delivered here, where widgets may be
    #: touched, and `gui.live`'s own rule -- signals for lifecycle only, never
    #: for a record -- is what makes one per outage affordable.
    capture_state = Signal(str)

    # Declared, then filled from `gui.shortcuts.BINDINGS` in `_build_actions`.
    # Assigning them through `setattr` alone would leave a type checker blind
    # to twenty attributes -- and static checking is one of the few things
    # standing in for the macOS testing this project cannot do. The list is
    # asserted against the table in `test_gui_shortcuts.py`, so the two cannot
    # drift.
    action_capture: QAction
    action_pause: QAction
    action_disconnect: QAction
    action_open: QAction
    action_close: QAction
    action_export: QAction
    action_copy: QAction
    action_copy_filter: QAction
    action_deselect: QAction
    action_find: QAction
    action_mark: QAction
    action_clear_marks: QAction
    action_top: QAction
    action_bottom: QAction
    action_go_time: QAction
    action_follow: QAction
    action_detail_pane: QAction
    action_next_jump: QAction
    action_previous_jump: QAction
    action_next_error: QAction
    action_previous_error: QAction
    action_next_marker: QAction
    action_previous_marker: QAction
    action_next_mark: QAction
    action_previous_mark: QAction
    action_step_down: QAction
    action_step_up: QAction
    action_dark_mode: QAction
    action_doctor: QAction
    action_keys: QAction
    action_quit: QAction
    action_about: QAction

    def __init__(self, scheme: Scheme = Scheme.LIGHT, parent: QWidgetType | None = None) -> None:
        super().__init__(parent)
        self.scheme = scheme
        #: What the toolbar's chevrons move between. Read before the toolbar is
        #: built, since the button is constructed with it, and separately from
        #: `_restore_layout`, which is allowed to give up on a geometry that no
        #: longer fits any screen and would take this with it.
        self._jump = self._restore_jump()
        self.setWindowTitle(_TITLE)
        # Before anything asks for a size hint. Left to Qt the window opened at
        # 751x362 -- the sum of what an empty table and a two-line form ask for,
        # and about a third of what this one is worth reading at.
        self.resize(_DEFAULT_SIZE)

        self._build_layout()

        self.capture: Capture | None = None
        #: The device a live capture is coming from, once it has said. Held
        #: because the title wants it and the title is rebuilt from state
        #: rather than pushed to from wherever the name happened to arrive.
        self._device_name: str | None = None
        self._loader: CaptureLoader | None = None
        # `_replace_model` builds the first model, so the controller is made
        # after it and pointed at each replacement as it happens.
        self._replace_model(keep_filter=True)
        self.capture_controller = CaptureController(self.model, parent=self)
        self.follow_controller = FollowController(self.table, self.model, parent=self)
        self.follow_controller.changed.connect(self._show_follow_state)
        self.minimap.row_requested.connect(self.go_to)

        self._filter_debounce = QTimer(self)
        self._filter_debounce.setSingleShot(True)
        self._filter_debounce.setInterval(_FILTER_DEBOUNCE_MS)
        self._filter_debounce.timeout.connect(self._apply_filter)

        #: The last few filters, newest first, and the timer that decides one
        #: has been used rather than typed through. See `_remember_filter`.
        self._recent: list[Filter] = self._restore_recent()
        self.filter_bar.set_recent(self._recent)
        #: The named ones. Not capped and not automatic -- see `settings`.
        self._saved: list[SavedFilter] = WindowSettings().read_saved()
        self.filter_bar.set_saved(self._saved)
        self._filter_settled = QTimer(self)
        self._filter_settled.setSingleShot(True)
        self._filter_settled.setInterval(_FILTER_SETTLED_MS)
        self._filter_settled.timeout.connect(self._remember_filter)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()

        self._connect_actions()
        # A fresh window shows everything, so there is no filter to copy yet.
        # Stated here rather than left to the first filter change, which on a
        # window nobody touches never comes.
        self.action_copy_filter.setEnabled(False)
        # After the actions, because restoring a preference moves the checkbox
        # that reports it -- and before the first paint, so nothing is drawn in
        # a scheme the user overruled a session ago.
        self.theme_policy = ThemePolicy(parent=self)
        self.theme_policy.scheme_changed.connect(self._on_scheme_changed)
        self.theme_policy.follow_system()
        self.theme_policy.restore()
        self._set_capturing(capturing=False)

    def _on_scheme_changed(self, scheme: object) -> None:
        """The scheme moved. Repaint what this window prebuilt for itself.

        Which scheme is in force is `gui.theme_policy`'s decision and the
        application palette is already on it by the time this runs; what is
        left is the colours resolved once and held here, and the checkbox that
        reports the answer.
        """
        if not isinstance(scheme, Scheme):  # pragma: no cover - the signal carries one
            return
        self.set_scheme(scheme)
        self._show_theme_state()

    def _show_theme_state(self) -> None:
        """Put the checkbox where the scheme is, without that counting as a choice.

        `setChecked` emits `toggled`, which is wired to `toggle_dark_mode` --
        so *following* the system would mark the theme as chosen and the next
        system switch would be ignored. Measured: one switch worked and every
        one after it did nothing.
        """
        self.action_dark_mode.blockSignals(True)
        self.action_dark_mode.setChecked(self.scheme is Scheme.DARK)
        self.action_dark_mode.blockSignals(False)

    def toggle_dark_mode(self, *, dark: bool) -> None:
        """The menu item was used. Choosing is the policy's to record."""
        self.theme_policy.choose(dark=dark)

    def set_scheme(self, scheme: Scheme) -> None:
        """Move the colours this window prebuilt for itself to ``scheme``.

        `theme.apply_theme` moves the *palette*, which is everything Qt draws.
        It does not reach the severity foregrounds or the minimap's bands,
        which are resolved once and held, so a theme switch used to repaint the
        window in the new scheme and leave every record's colour in the old
        one. Measured on the shipped palette, `Info` and `Notice` -- most of any
        capture -- landed at **1.14:1** against the new background: near-black
        on near-black, or near-white on white. `docs/design/gui.md` §10 says the
        switch is the same function called again, and this is the fan-out that
        was missing rather than a second way of doing it.
        """
        self.scheme = scheme
        self.model.set_scheme(scheme)
        self.minimap.set_scheme(scheme)
        self.table.set_scheme(scheme)
        self.device_button.set_scheme(scheme)
        self.filter_bar.set_scheme(scheme)
        icons.clear_cache()
        self._apply_icons()

    def _build_layout(self) -> None:
        """Assemble the widgets. No behaviour, no state."""
        self.filter_bar = FilterBar(self, scheme=self.scheme)
        self.banner = Banner(self)
        self.table = LogTable(self, scheme=self.scheme)
        self.detail = DetailPane(self)

        # The table and its overview strip travel together, so the splitter
        # sees one widget rather than two that could drift apart.
        table_area = QWidget(self)
        beside = QHBoxLayout(table_area)
        beside.setContentsMargins(0, 0, 0, 0)
        beside.setSpacing(0)
        beside.addWidget(self.table, stretch=1)
        self.minimap = Minimap(self.scheme, table_area)
        beside.addWidget(self.minimap)

        self._split = QSplitter(Qt.Orientation.Vertical, self)
        self._split.addWidget(table_area)
        self._split.addWidget(self.detail)
        self._split.setStretchFactor(0, _TABLE_STRETCH)
        self._split.setStretchFactor(1, _DETAIL_STRETCH)
        self._sized = False
        # The table may be collapsed to nothing by dragging; the detail pane
        # may not, because a pane that can vanish behind a one-pixel handle is
        # a pane the user cannot get back.
        self._split.setChildrenCollapsible(False)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.filter_bar)
        layout.addWidget(self.banner)
        layout.addWidget(self._split, stretch=1)
        self.setCentralWidget(central)

        self.status = StatusBar(self)
        self.setStatusBar(self.status)

        # Once: the scrollbar belongs to the view, which outlives every
        # model the window will attach to it.
        self.table.verticalScrollBar().actionTriggered.connect(self._on_user_scroll)
        # Where the reader is, told to the strip that draws it. Not routed
        # through the pump: scrolling a file that is not being captured has no
        # ticks, and a marker that only moved during a live capture would be
        # stuck to the top of every capture anybody opened.
        self.table.viewport_changed.connect(self._show_viewport)

    #: The toolbar, in order: which device, what to do with it, then the file
    #: verbs, then the two jumps a reader makes constantly. ``None`` is a
    #: separator. Named by action attribute and icon, so that adding a button
    #: cannot invent a behaviour -- every one of these already exists as a menu
    #: item with a shortcut, and this is a second way to reach it rather than a
    #: second implementation of it.
    _TOOLBAR: tuple[tuple[str, str, bool] | None, ...] = (
        ("action_capture", "play", True),
        ("action_pause", "pause", True),
        ("action_disconnect", "eject", True),
        None,
        ("action_open", "folder-open", False),
        ("action_export", "download", False),
        None,
        ("action_previous_jump", "chevron-up", False),
        ("action_next_jump", "chevron-down", False),
    )

    def _build_toolbar(self) -> None:
        """The five verbs, one press away.

        `docs/design/gui.md` §1 sketched this and phase 4 did not build it, so
        every primary action lived two clicks deep in a menu. A real `QToolBar`
        rather than a styled `QWidget`: it is marginally the faster of the two
        to paint, but the reason is the overflow menu -- narrow the window and a
        custom widget silently clips Capture and Disconnect off the end, where
        the real one moves them into a chevron.

        Capture, Pause and Disconnect carry their labels. The rest do not: an
        unlabelled icon row is the specific thing people name when they call a
        tool dated, and these three are the ones whose consequences differ.
        """
        self.toolbar = QToolBar("Main", self)
        # `saveState` identifies each toolbar and dock by object name, and warns
        # on every close without one -- which `closeEvent` triggers, so the
        # warning was printed every time the window shut. The single unnamed
        # toolbar still came back, by position, but that fallback is the thing
        # that stops working the moment a second toolbar or a dock exists.
        self.toolbar.setObjectName("Main")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setIconSize(QSize(icons.ICON_SIZE, icons.ICON_SIZE))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        self.device_button = DeviceButton(self.scheme, self.toolbar)
        self.toolbar.addWidget(self.device_button)
        self.toolbar.addSeparator()

        for entry in self._TOOLBAR:
            if entry is None:
                self.toolbar.addSeparator()
                continue
            name, _icon, labelled = entry
            action = getattr(self, name)
            self.toolbar.addAction(action)
            button = self.toolbar.widgetForAction(action)
            if isinstance(button, QToolButton) and not labelled:
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                # Stripping the label strips the only thing a screen reader
                # had. The accelerator marker goes with it: `&Export…` is read
                # out as "ampersand Export", and the ellipsis means "this asks
                # something first", which is worth keeping.
                button.setAccessibleName(action.text().replace("&", ""))
                button.setAccessibleDescription(action.toolTip())

        # Immediately after the two chevrons, because it is what they mean. An
        # arrow whose target is stated somewhere else is an arrow you have to
        # remember the setting of.
        self.jump_button = JumpButton(self._jump, self.toolbar)
        self.jump_button.changed.connect(self._on_jump_target_changed)
        self.toolbar.addWidget(self.jump_button)
        self._on_jump_target_changed(self._jump)

        self._apply_icons()

    def _apply_icons(self) -> None:
        """Rebuild every icon for the current scheme.

        The pixmaps are tinted from a token, so they are as scheme-specific as
        the palette and have to be redrawn beside it. A `QIcon` built from an
        SVG file does not recolour itself.
        """
        ratio = self.devicePixelRatioF()
        for entry in self._TOOLBAR:
            if entry is None:
                continue
            name, icon_name, _labelled = entry
            getattr(self, name).setIcon(icons.icon(icon_name, self.scheme, ratio=ratio))

    def _connect_actions(self) -> None:
        """Wire every action to what it does.

        Separate from ``__init__`` because there are twenty of them and a
        constructor that also happens to be the wiring diagram is one nobody
        reads.
        """
        self.filter_bar.changed.connect(self._on_filter_changed)
        self.filter_bar.recent_chosen.connect(self._on_recent_chosen)
        self.filter_bar.save_requested.connect(self.name_current_filter)
        self.filter_bar.manage_requested.connect(self.manage_saved_filters)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.action_open.triggered.connect(self.choose_capture)
        self.action_close.triggered.connect(self.close_capture)
        self.action_capture.triggered.connect(self.capture_from_device)
        self.action_disconnect.triggered.connect(self.stop_capture)
        self.action_pause.toggled.connect(self.set_paused)

        self.action_copy.triggered.connect(self.copy_selection)
        self.action_copy_filter.triggered.connect(self.copy_filter)
        self.action_deselect.triggered.connect(self.deselect)
        # The pane's own way out. `Esc` was the only one, which is a key you
        # have to be told about; a control you can see is not.
        self.detail.closed.connect(self.deselect)
        self.action_dark_mode.toggled.connect(lambda on: self.toggle_dark_mode(dark=on))
        self.action_find.triggered.connect(self.filter_bar.focus_search)
        self.action_mark.triggered.connect(self.toggle_mark)
        self.action_clear_marks.triggered.connect(self.clear_marks)
        self.action_top.triggered.connect(self.go_to_top)
        self.action_bottom.triggered.connect(self.go_to_bottom)
        self.action_go_time.triggered.connect(self.ask_for_time)
        self.action_detail_pane.toggled.connect(lambda on: self.set_detail_visible(visible=on))
        self.action_follow.toggled.connect(lambda on: self.set_following(follow=on))
        self.status.follow.clicked.connect(self._on_follow_clicked)
        self.action_next_jump.triggered.connect(lambda: self.find_next(self._jump))
        self.action_previous_jump.triggered.connect(
            lambda: self.find_next(self._jump, backwards=True)
        )
        self.action_next_error.triggered.connect(lambda: self.find_next(Find.ERROR))
        self.action_previous_error.triggered.connect(
            lambda: self.find_next(Find.ERROR, backwards=True)
        )
        self.action_next_marker.triggered.connect(lambda: self.find_next(Find.MARKER))
        self.action_previous_marker.triggered.connect(
            lambda: self.find_next(Find.MARKER, backwards=True)
        )
        self.action_next_mark.triggered.connect(lambda: self.find_next(Find.MARK))
        self.action_previous_mark.triggered.connect(
            lambda: self.find_next(Find.MARK, backwards=True)
        )
        self.action_step_down.triggered.connect(lambda: self.step_row(1))
        self.action_step_up.triggered.connect(lambda: self.step_row(-1))
        self.action_export.triggered.connect(self.export_capture)
        self.action_doctor.triggered.connect(self.show_doctor)
        self.action_keys.triggered.connect(self.show_keys)
        # The two macOS relocates, wired here with the rest rather than beside
        # their construction. Where a platform puts an item is the factory's
        # business; what the item does is this window's, and that is the whole
        # split.
        self.capture_controller.state_changed.connect(self._on_lifecycle)
        self.capture_controller.identified.connect(self._on_identified)
        self.capture_controller.session_at.connect(self._adopt_session)
        self.capture_controller.failed.connect(self._on_capture_failed)
        self.capture_controller.finished.connect(self._on_capture_finished)
        self.capture_controller.rate_changed.connect(self._on_rate)
        self.capture_controller.overflowed.connect(self._on_pause_overflow)
        self.action_quit.triggered.connect(self.close)
        self.action_about.triggered.connect(self.show_about)
        self.capture_state.connect(self._on_capture_state)

    def clear_marks(self) -> None:
        """Drop every mark.

        A method rather than connecting ``self.model.clear_marks`` directly:
        the model is *replaced* whenever a capture is opened or started, and a
        direct connection would go on clearing the marks of a model nobody can
        see any more.
        """
        self.model.clear_marks()

    def _connect_selection(self) -> None:
        """Re-attach to the selection model, which is replaced with the model."""
        selection = self.table.selectionModel()
        if selection is not None:
            selection.currentRowChanged.connect(self._on_current_row_changed)
        # Called once, at construction: the model is emptied rather than
        # replaced now, so the selection model it belongs to outlives every
        # capture and there is nothing to re-attach.
        self.model.top_shifted.connect(self._keep_place)

    def _on_user_scroll(self) -> None:
        """The user moved the view themselves."""
        self.follow_controller.note_scroll()

    def _keep_place(self, shifted: int) -> None:
        """Hold the same records under the reader when the top is trimmed.

        The view keeps a *pixel* offset from the top of its content, so
        dropping twenty thousand rows above the viewport slides everything
        under it while the offset stays put. On a busy device that is every
        seven seconds, forever, and always while somebody is reading: measured
        at a cap of 2,000, a reader on record 989 was looking at record 1,588
        afterwards, having pressed nothing.

        Exact rather than approximate because the row height is fixed, which is
        a property this table already guarantees for its own reasons. Applied
        whether or not the tail is following -- following will scroll to the
        bottom a moment later either way, and a correct position in between
        costs nothing.
        """
        bar = self.table.verticalScrollBar()
        row_height = self.table.verticalHeader().defaultSectionSize()
        bar.setValue(max(0, bar.value() - shifted * row_height))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Release the device before the window goes.

        Without this the capture thread outlives the window it was reporting
        to, and the device is left streaming into a queue nobody drains -- the
        exact failure this project already paid for once at the source level.

        The device scan is the same hazard in miniature. It is short, but a
        ``QThread`` that is still running when Python drops its last reference
        aborts the process outright -- measured here as exit ``0xC0000409``
        with nothing printed -- and closing the window during a scan is exactly
        how that reference gets dropped.
        """
        self.capture_controller.shutdown()
        self.minimap.stop()
        self.device_button.stop()
        self._save_layout()
        super().closeEvent(event)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """Split the panes on first show, when there is a height to divide.

        Stretch factors only govern how *extra* space is shared on a resize;
        the first layout comes from the children's size hints, and neither an
        empty table nor a two-line form has a hint that reflects what the user
        wants to see. Doing it here rather than in the constructor is the
        difference between a ratio and a guess: the window has no height yet
        when it is built.
        """
        super().showEvent(event)
        if self._sized:
            return
        self._sized = True
        # After the sizes, whichever way they were arrived at: putting the pane
        # away and then dividing the split would hand the hidden pane a share
        # of the window, which it takes back the moment it is shown again.
        restored = self._restore_layout()
        if not restored:
            total = self._split.height()
            share = _TABLE_STRETCH + _DETAIL_STRETCH
            self._split.setSizes(
                [total * _TABLE_STRETCH // share, total * _DETAIL_STRETCH // share]
            )
        self._restore_detail_visible()

    # -- what the window remembers ---------------------------------------

    def _restore_detail_visible(self) -> None:
        """Put the pane back the way the last session left it.

        Through the menu item rather than around it, so the tick and the pane
        cannot start out disagreeing -- a window that opened with the pane
        hidden and the item ticked would need two presses to show it, the first
        of which appears to do nothing.

        Only on the way to *hidden*. Visible is the default and the state the
        window is built in, and setting a checkable action to the value it
        already holds emits nothing.
        """
        if not WindowSettings().read_layout().detail_visible:
            self.action_detail_pane.setChecked(False)

    def _save_recent(self) -> None:
        WindowSettings().write_recent(self._recent)

    def _restore_recent(self) -> list[Filter]:
        return WindowSettings().read_recent()

    def _restore_jump(self) -> Find:
        return WindowSettings().read_layout().jump

    def _on_a_screen(self) -> bool:
        """Is this window somewhere a person could actually see it?

        Both halves matter. A restored size can be degenerate, and a restored
        *position* can be perfectly valid for a display that is not attached
        any more -- neither of which `restoreGeometry` reports as a failure,
        because neither is malformed.
        """
        if self.width() < _MIN_USABLE or self.height() < _MIN_USABLE:
            return False
        return any(
            screen.availableGeometry().intersects(self.frameGeometry())
            for screen in QApplication.screens()
        )

    def _save_layout(self) -> None:
        """Remember where the window was and how it was arranged.

        What is *not* remembered, and why, is `gui.settings`' module docstring:
        the policy travels with the code that enforces it.
        """
        WindowSettings().write_layout(
            Layout(
                geometry=self.saveGeometry(),
                state=self.saveState(),
                split=self._split.saveState(),
                columns=[self.table.columnWidth(index) for index in range(len(COLUMNS))],
                jump=self._jump,
                detail_visible=self.detail.isVisible(),
            )
        )

    def _restore_layout(self) -> bool:
        """Put it back, and say whether there was anything to put.

        Decoding is `gui.settings`' half, and it hands back only what it could
        read. Deciding whether the result is *usable* is this one's, because
        answering that takes the screens and the window's own frame.
        """
        layout = WindowSettings().read_layout()
        if layout.geometry is None:
            return False
        if not self.restoreGeometry(layout.geometry) or not self._on_a_screen():
            # A geometry can be well-formed and still unusable: saved on a
            # second monitor that is no longer attached, saved by a window
            # manager that reported a size of nothing, or -- how this was
            # found -- saved by an offscreen test run and restored on a real
            # display, where the window opened somewhere nothing could show it
            # and the program looked as though it had failed to start.
            self.resize(_DEFAULT_SIZE)
            return False
        if layout.state is not None:
            self.restoreState(layout.state)
        if layout.split is not None:
            self._split.restoreState(layout.split)
        if layout.columns is not None:
            # Through the table rather than column by column, so that it knows
            # these are the user's widths and stops fitting its own.
            self.table.restore_column_widths(layout.columns)
        return True

    # -- actions ---------------------------------------------------------

    def _build_actions(self) -> None:
        """Build every action, and give each one its typed attribute.

        The attributes are declared above and assigned here, which is the mypy
        contract standing in for a Mac: a menu item renamed in the bindings
        table stops resolving, on every platform, rather than silently landing
        in the wrong macOS menu where only a Mac would see it.
        """
        self.actions_by_name = build_actions(self)
        for name, action in self.actions_by_name.items():
            setattr(self, f"action_{name}", action)

    def _build_menus(self) -> None:
        self.menus = build_menus(self.menuBar(), self.actions_by_name, self)

    def menu_items(self) -> list[QAction]:
        """Every clickable item in the menu bar, for the menu-role test."""
        # The module function of the same name; this method is what the tests
        # and the window itself ask.
        return menu_items(self.menuBar())

    # -- opening a capture -----------------------------------------------

    def choose_capture(self) -> None:
        """Ask for a capture and open it."""
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Open capture",
            str(sessions_dir()),
            "Captures (*.jsonl.gz *.jsonl);;All files (*)",
            # The native macOS dialog ignores the filter argument outright, so
            # the filters above would silently do nothing there. Qt's own
            # dialog honours them and looks the same on every platform, which
            # is the same reason this project chose Qt in the first place.
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if chosen:
            self.open_capture(Path(chosen))

    def _replace_model(self, *, keep_filter: bool) -> None:
        """Swap in a fresh model and leave the chrome agreeing with it.

        Every door that empties the table arrives here: opening a capture,
        closing one, starting a live capture, and building the window. They had
        a copy of this each, and one of the copies was missing a step -- opening
        a capture while a filter stood left the bar displaying a filter the new
        model did not apply, so the table showed everything while the chrome
        said it was narrowed. Three sites is where that becomes inevitable
        rather than unlucky.

        ``keep_filter`` is the only thing the doors disagree about, and it is a
        policy rather than an oversight. Closing clears, because there is no
        next capture and this is the one moment the window knows for certain
        that the filter is not for whatever comes after. Every other door keeps
        it: there *is* a capture in hand, and a filter typed in front of the
        last one is usually the question being carried to the next.

        Applied while the model is still empty, and directly rather than
        through the debounce -- a swap is not typing. Filtering nothing costs
        nothing, and the rows then arrive already narrowed instead of arriving
        and being taken away.

        The outgoing model is deleted rather than left to the window, and that
        is only half of the release -- see `open_capture`, which deletes the
        loader for the other half. A model has two owners: this window, which
        is its Qt parent and would hold it until the window itself dies, and
        the `CaptureLoader` that was reading into it, which keeps it in an
        attribute. Freeing either one alone frees nothing at all, because the
        other still points at the rows.

        Measured over twenty successive opens, as process private bytes:
        neither released grows 41.0 MiB, model only 41.2 MiB, loader only
        40.6 MiB, both 2.2 MiB. The pair is the fix; each half on its own looks
        like one and is not.

        ``deleteLater`` rather than a plain drop, because the view and the
        minimap have only just let go of this and Qt may still be holding a
        pointer this far up the stack.
        """
        if getattr(self, "model", None) is None:
            # The window's own construction: the one door with nothing to
            # empty. Everything after this point is wired to *this* model and
            # stays wired, which is the whole of the change.
            self.model = RecordModel(self.scheme, parent=self)
            self.table.setModel(self.model)
            self.minimap.set_model(self.model)
            self._connect_selection()
        else:
            self.model.clear()
        # Every door, not only the first: emptying the model is what a new
        # capture is now, and the tail goes back on with it.
        #
        # Through `getattr` because the first call comes from `__init__`, before
        # there is a controller to tell -- the window builds its model here and
        # its controllers afterwards, since they take it.
        follow = getattr(self, "follow_controller", None)
        if follow is not None:
            follow.set_model(self.model)
        self.detail.clear()

        if not keep_filter:
            self.filter_bar.clear()
            # Stated here rather than assumed inside `clear`, which empties the
            # rows and leaves the filter alone: which filter an emptied model
            # should carry is this method's policy, and it differs by door.
            self.model.set_filter(Filter())
            return
        wanted = self._bar_filter()
        if wanted is not None:
            self.model.set_filter(wanted)

    def open_capture(self, path: Path) -> None:
        """Load a capture into the table.

        Read in batches from the event loop rather than in one pass -- see
        `gui.loader`. Replacing the contents rather than appending to them: two
        captures interleaved by arrival order would be a timeline that never
        happened.
        """
        # Cancelling stops it reading; it does not release it. The loader is
        # parented to this window and holds the model it was filling, so an
        # abandoned one keeps a whole retained row set alive. The other half of
        # the release is in `_replace_model`, and neither half works alone.
        if self._loader is not None:
            self._loader.cancel()
            self._loader.deleteLater()
            self._loader = None

        try:
            capture = open_capture(path)
        except OstraceError as exc:
            # The useful answer to a capture that will not open is the file
            # chooser, not an acknowledgement: whatever went wrong, the next
            # thing wanted is a different file.
            self.banner.show_message(
                f"Could not open {path.name}: {exc}",
                "Open another…",
                on_action=self.choose_capture,
            )
            return

        self.stop_capture()
        self.capture = capture
        self._replace_model(keep_filter=True)
        self.status.set_device(capture.device)

        self._loader = CaptureLoader(capture, self.model, parent=self)
        self._loader.progressed.connect(self._on_progress)
        self._loader.finished.connect(self._on_loaded)
        self._loader.failed.connect(self._on_load_failed)
        self._loader.start()

        self._retitle()

    def close_capture(self) -> None:
        """Put the window back the way it starts.

        There was no way to do this. Every state the window can be in -- a
        capture loaded, a filter narrowed, a row selected, a device named in the
        status bar, a file name in the title -- was reachable and none of it was
        reversible without quitting and starting again. Reported as wanting "a
        clean page" after finishing with a capture, which is exactly right: the
        alternative was reading the next capture through the last one's filter.

        A running capture is not closed out from under itself. Disconnect
        releases the device and finalises the session, and doing that silently
        because somebody asked for an empty window would throw away a recording
        in progress.
        """
        if self.capture_controller.is_running:
            self.banner.show_message(
                "A capture is still running. Disconnect to finish it, and the "
                "window can be emptied after that.",
                "Disconnect",
                on_action=self.stop_capture,
            )
            return

        if self._loader is not None:
            self._loader.cancel()
            self._loader.deleteLater()
            self._loader = None

        self.capture = None
        # The filter goes with it -- the one door that clears rather than
        # carries. See `_replace_model`.
        self._replace_model(keep_filter=False)
        # Nothing follows to redraw it, unlike the doors that start a loader.
        self.minimap.rebuild()
        self.banner.hide()
        self.status.set_device(None)
        self.status.set_rate(None)
        self._retitle()
        self._update_counts()
        self._update_placeholder()

    # -- what the window is called ---------------------------------------

    def title_text(self) -> str:
        """The window title, derived from what the window is holding.

        One place decides. It was set from six, each with its own f-string, and
        they disagreed: a live capture was titled after the *source* -- which
        is ``os_trace_relay``, the Apple service the stream arrives on, the
        same for every device and an answer to no question -- while a file was
        titled with its full name including ``.jsonl.gz``, and two of the six
        cleared it to bare ``ostrace`` in states where something was still
        open.

        The subject comes first and the application name last, which is the
        convention on every desktop and the order that survives a taskbar
        button too narrow to show all of it.
        """
        if self.capture_controller.is_running:
            subject = (
                _CAPTURING_FROM.format(device=self._device_name)
                if self._device_name
                else _CAPTURING
            )
        elif self.capture is not None:
            # `export_stem` rather than `path.name`: it already knows every
            # ending a capture can arrive with, longest first, so `.jsonl.gz`
            # does not come off as `.gz` and leave `…jsonl` behind.
            subject = export_stem(self.capture.path)
        else:
            return _TITLE
        return f"{subject}{_SEPARATOR}{_TITLE}"

    def _retitle(self) -> None:
        self.setWindowTitle(self.title_text())

    def _on_jump_target_changed(self, target: object) -> None:
        """Point the chevrons somewhere else, and say so in their tooltips."""
        if not isinstance(target, Find):  # pragma: no cover - the signal carries a Find
            return
        self._jump = target
        self.action_next_jump.setToolTip(f"Next: {target.label}")
        self.action_previous_jump.setToolTip(f"Previous: {target.label}")

    def _on_progress(self, loaded: int) -> None:
        self.status.set_volume(loaded)
        self.status.set_gap_count(self.model.gaps)
        self.status.set_shown(self.model.rowCount(), self.model.retained)

    def _on_loaded(self) -> None:
        self._on_progress(self._loader.loaded if self._loader else 0)
        self.minimap.rebuild()
        if self.capture is not None and self.capture.truncated:
            # Worth saying out loud: the end of a truncated capture is missing,
            # and its absence says nothing about the device.
            self.banner.show_message(
                "This capture has no gzip trailer, so it was still being written "
                "or the writer was killed. Its last records are missing.",
                "Dismiss",
            )
        self._update_banner()

    def _on_load_failed(self, message: str) -> None:
        self._on_progress(self._loader.loaded if self._loader else 0)
        self.banner.show_message(
            f"Stopped reading: {message}. Everything read before that point is shown.",
            "Dismiss",
        )

    # -- live capture ----------------------------------------------------

    def capture_from_device(self) -> None:
        """Start capturing from whatever device is attached.

        No device is not an error worth a dialog: it is the ordinary state of a
        program whose subject is a phone that spends most of its time in a
        pocket. It gets the same banner every other invisible state gets, with
        the same way out.
        """
        try:
            source = self._build_source()
        except OstraceError as exc:
            hint = f" {exc.hint}" if getattr(exc, "hint", None) else ""
            self.banner.show_message(f"{exc}{hint}", "Retry", on_action=self.capture_from_device)
            return
        self.start_capture(source)

    def _build_source(self) -> LogSource:
        """The live source, imported here rather than at module scope.

        The reason given for that used to be that `ostrace.sources.os_trace`
        refuses to be imported under ``-O`` and pulls in pymobiledevice3, ninety
        distributions. Both are false. Measured: importing it pulls **no**
        pymobiledevice3 modules -- the library is imported inside
        `_open_service` -- and the ``-O`` guard refuses at construction, not at
        import. With this window already imported, deferring saves one module
        and 1.2 ms.

        It stays deferred here because hoisting it changes what `ostrace.gui`
        depends on at import time, which is a decision for the packages moving
        this code rather than for the commit correcting the sentence.
        """
        from ostrace.sources.os_trace import OsTraceSource  # noqa: PLC0415

        # The udid the toolbar is showing, which until the device selector
        # existed was always `None` -- "whichever answers first". With two
        # devices attached that was a coin toss the user could not see and,
        # since nothing named the winner, could not lose either.
        # `on_state` crosses a thread: the source runs on the capture thread
        # and this is a Qt signal belonging to a window on the interface one,
        # so the emission is queued and delivered where it can touch widgets.
        # Calling a method directly from there would repaint from the wrong
        # thread, which Qt does not always refuse and never survives.
        return OsTraceSource(self.device_button.udid, on_state=self.capture_state.emit)

    def start_capture(self, source: LogSource, *, destination: Path | None = None) -> None:
        """Begin a live capture into a fresh model.

        The records go to a session file as well as to the table -- the same
        `ostrace.capture.capture` the CLI runs. A live view that keeps nothing
        would make "pause" a promise it cannot honour and would lose everything
        the moment the window closed. ``destination`` overrides where that file
        goes; by default `paths` decides, as it does for the CLI.
        """
        self._replace_model(keep_filter=True)
        self.capture = None
        # Not known until the device answers, which is a round trip. The title
        # says so rather than guessing, and `_on_identified` fills it in.
        self._device_name = None

        self.capture_controller.set_model(self.model)
        self.capture_controller.start(source, destination=destination)
        self.minimap.start()

    def stop_capture(self) -> None:
        """Release the device.

        Named after its consequence rather than "stop": releasing a device
        releases the lockdown session *and* the ``os_trace_relay`` service, and
        a control that reads as the opposite of "pause" invites the user to
        press it expecting to be able to press it back.
        """
        self.capture_controller.stop()
        self.minimap.stop()

    def _adopt_session(self, path: object) -> None:
        """Make the capture that was just recorded the one Export offers.

        A live capture writes every record through the same
        `ostrace.capture.capture` the CLI runs, and its ``finally`` finalises
        the session on every exit path -- including the cancellation that
        Disconnect performs. So the moment the thread ends there is a complete
        capture on disk, and the only thing missing was anything in this window
        knowing where it went. Without this, Export told the user to disconnect
        and then said exactly the same thing after they had.

        The file rather than the model, deliberately: the view holds a bounded
        number of rows and the file holds all of them.

        Opening it stays here rather than in the controller, because the
        failure is a sentence and sentences are this window's.
        """
        if not isinstance(path, Path):
            return  # cancelled before it opened one: there is genuinely nothing
        try:
            self.capture = open_capture(path)
        except OstraceError as exc:
            self.banner.show_message(
                f"The capture was written to {path.name}, but it cannot be reopened: {exc}",
                "Dismiss",
            )
            return
        # The one place the window says where the capture went. The CLI prints
        # it; until now the GUI never said at all.
        self._retitle()

    def set_paused(self, paused: bool) -> None:
        """Freeze the view. The device is not consulted."""
        self.capture_controller.set_paused(paused)
        if paused:
            self.banner.show_message(
                "The view is paused. The capture is still running and still "
                "writing every record to the session file.",
                "Resume",
                on_action=lambda: self.action_pause.setChecked(False),
                key=Notice.PAUSED,
            )
        elif self.banner.current_key is Notice.PAUSED:
            # Its own notice and no other. Resuming used to clear the strip
            # outright, so a reader who paused during an outage and then
            # resumed was left with a device that was still gone and nothing
            # on screen saying so.
            self.banner.hide()

    def _on_lifecycle(self, state: object) -> None:
        """Everything the window shows about a capture, from one value.

        The controller says where the capture is; this decides what that looks
        like. `PARKED` is the one state with a sentence of its own -- the
        device is still held, and the consequence is the user's: the next
        capture may find the relay busy.
        """
        if not isinstance(state, Lifecycle):  # pragma: no cover - the signal carries one
            return
        if state is Lifecycle.PARKED:
            # With an action, because the consequence is one the user will meet
            # later and elsewhere. Doctor is what tells them whether the device
            # is free again.
            self.banner.show_message(
                "The capture has not released the device yet. It is still shutting "
                "down, and a new capture may fail until it has.",
                "Diagnose…",
                on_action=self.show_doctor,
            )
        self._set_capturing(capturing=self.capture_controller.is_running)

    def _set_capturing(self, *, capturing: bool) -> None:
        self.action_capture.setEnabled(not capturing)
        self.action_disconnect.setEnabled(capturing)
        self.action_pause.setEnabled(capturing)
        # There is no tail to follow in a file. The control stays visible and
        # goes quiet, rather than appearing and disappearing under the cursor.
        self.action_follow.setEnabled(capturing)
        self.status.follow.setEnabled(capturing)
        # Choosing a device mid-capture would either do nothing or silently
        # apply to the next one, and both are worse than saying you have to
        # disconnect first. `busy_udid` covers the scan that was already in
        # flight when the capture started.
        self.device_button.setEnabled(not capturing)
        self.device_button.set_busy(self.device_button.udid if capturing else None)
        # The funnel every capture state change passes through, including the
        # one at construction -- which is what puts a sentence on the cold-start
        # window instead of an empty grid, and the right name on the title bar
        # whichever way the capture started or ended.
        self._update_placeholder()
        self._retitle()
        # Last, and after the control's own enabled state: the unseen count is
        # silent when there is no tail, so a capture that ends while the reader
        # is half way up would otherwise leave its final "1,204 behind" on the
        # bar for as long as the window stayed open.
        self._show_follow_state()
        if not capturing:
            self.action_pause.setChecked(False)
            self.status.set_rate(None)

    def _on_identified(self, device: object) -> None:
        if isinstance(device, DeviceInfo):
            self.status.set_device(device)
            if self.capture_controller.is_running:
                # Which device is actually held, rather than which one was
                # picked. They are the same when the user chose one and they
                # are not when nobody did -- and the one a scan must leave
                # alone is the one the capture thread is blocked on reading,
                # which only the device itself can say.
                self.device_button.set_busy(device.udid)
            # The title has been saying "Capturing" until now, because until
            # now that was the whole of what was known.
            self._device_name = device.name
            self._retitle()

    def _on_rate(self, rate: float) -> None:
        self.status.set_rate(rate)
        self._update_counts()
        self._follow()

    def _on_pause_overflow(self, dropped: int) -> None:
        self.banner.show_message(
            f"The view is paused and {dropped:,} records did not fit. They are "
            f"in the session file, not lost.",
            "Resume",
            on_action=lambda: self.action_pause.setChecked(False),
        )

    def _on_capture_state(self, state: str) -> None:
        """The device came or went, said while it is happening.

        The `Gap` in the stream is the *record* of an outage and stays that --
        it travels in position, which is where its meaning is. This is the
        other half: a gap can only be written once the device is back, and the
        question somebody staring at a stalled window has is being asked
        several seconds before that.

        Disconnect rather than a way out: the source is already retrying, and
        the only decision left to the user is whether to stop waiting.
        """
        self.capture_controller.link_state(CaptureState(state))
        if state == CaptureState.RECONNECTING:
            self.banner.show_message(
                RECONNECT_MESSAGE,
                "Disconnect",
                on_action=self.stop_capture,
                key=Notice.RECONNECTING,
            )
        elif state == CaptureState.STREAMING and self.banner.current_key is Notice.RECONNECTING:
            # Only its own notice. A pause banner raised during the outage is
            # a different state that is still true, and clearing it here would
            # leave the view frozen with nothing on screen saying why.
            self.banner.hide()

    def show_doctor(self) -> None:
        """Open the Doctor window on whichever device is selected.

        Kept on the window, because a dialog whose last reference is a local
        in the function that opened it is collected on the next line.
        """
        self._doctor = open_doctor(self.device_button.udid, self)

    def _on_capture_failed(self, message: str) -> None:
        """The capture died. The controller has already wound the machinery
        down; what is left is telling the user.

        `Diagnose…` rather than `Retry`, which is what this offered until the
        Doctor window existed. A capture that ran and then died is a different
        situation from one that never started: pressing Capture again is one
        click away on the toolbar, and what the user does not have is any way
        to find out *why* -- which is almost never in this program. It is a
        service that stopped, a device that locked, or a cable half out.
        """
        self.minimap.stop()
        self.banner.show_message(
            f"Capture stopped: {message}",
            "Diagnose…",
            on_action=self.show_doctor,
        )

    def _on_capture_finished(self) -> None:
        """The capture ended by itself -- the device was unplugged, or a limit
        was reached.

        The controller has already wound down and reported where the session
        went. What is left for the window is the overview timer, which is still
        running against a stream that has stopped, and the sentence.
        """
        self.minimap.stop()
        # The end of a capture is the moment an export is worth offering, and
        # until now it was a moment nothing marked at all: the records stopped
        # arriving and the window said so in no way a person notices. The
        # banner is the same one every other invisible state uses.
        self.banner.show_message(
            f"Capture finished — {self.model.retained:,} records.",
            "Export…",
            on_action=self.export_capture,
        )

    def deselect(self) -> None:
        """Let go of the selected row, and do nothing else.

        Selecting a row stops the tail, deliberately -- see `_follow`. Until
        this existed there was no way to say you had finished reading it: the
        only route back was `Go to Bottom` pressed twice, which is a thing you
        have to be told. A live capture therefore stopped following the first
        time anybody clicked anything, and stayed stopped.

        `Esc` because it is what the key means everywhere else, and it was the
        only obvious chord this window had not already spent.

        **Nothing else** is the correction. This used to force `_at_bottom`,
        clear `_user_scrolled` and call `_follow`, on the reasoning that asking
        to let go of a row is asking for the tail back. Against a real capture
        that reads as `Esc` throwing the reader to the end of the log from
        wherever they were -- the tail is somewhere else by definition, which is
        why they had scrolled away from it. It is also unnecessary: `_follow`
        derives "at the bottom" from the scrollbar, so a reader who deselects
        while genuinely at the bottom gets the tail back without being teleported
        there, and one who deselects half way up keeps their place. `Ctrl+End`
        remains the way to ask for the end on purpose.
        """
        self.table.clearSelection()
        self.table.setCurrentIndex(QModelIndex())
        self.detail.clear()

    @property
    def following(self) -> bool:
        """Whether the next batch of records will be scrolled to.

        Delegated rather than moved out of sight: `docs/design/gui.md` §4 makes
        a claim about this window's surface, and the claim stays true here
        because the answer is still derived on every read -- now by the object
        that also does the scrolling, so the indicator and the behaviour cannot
        come to different conclusions.
        """
        return self.follow_controller.following

    def set_detail_visible(self, *, visible: bool) -> None:
        """Put the detail pane away, or bring it back where it was.

        One line, and it was two more until the test that claimed to cover them
        stayed green with them removed: `QSplitter` keeps a hidden child's size
        and gives it back on the way in, so saving the sizes by hand was
        restoring numbers Qt had already restored. The assertion is kept
        because the behaviour matters -- a pane that came back bigger than it
        went away is one there is no way to put right that a second press does
        not undo -- and because it pins a Qt behaviour rather than ours.

        The menu item is not synced here. It is the only thing that calls this,
        and `setChecked` from inside its own `toggled` handler is the loop this
        project has already walked into twice.
        """
        self.detail.setVisible(visible)

    def _show_viewport(self) -> None:
        """Tell the minimap which rows are on screen."""
        self.minimap.set_viewport(*self.table.visible_rows())

    @property
    def behind(self) -> int:
        """How many records sit below the bottom of the viewport, unseen."""
        return self.follow_controller.behind

    def set_following(self, *, follow: bool) -> None:
        """Turn the tail on or off, from the status bar or the keyboard."""
        self.follow_controller.set_following(follow=follow)
        # The detail pane is the window's, so clearing it is too: the
        # controller lets go of the row and this stops showing it.
        if follow:
            self.detail.clear()

    def _on_follow_clicked(self) -> None:
        """The status bar's control was pressed: do the other thing.

        Derived from `following` rather than from the button's own checked
        state, which it has already flipped by the time this runs and which is
        a copy of the answer rather than the answer. Taking no argument is also
        what binds this to the parameterless ``clicked()`` overload: connecting
        `setChecked` to it directly bound the same overload and called it with
        nothing, which PySide reports on stderr and otherwise swallows.
        """
        self.set_following(follow=not self.following)

    def _show_follow_state(self) -> None:
        """Put the indicator and the menu item where the view actually is.

        `setChecked` emits `toggled`, which is wired to `set_following`, so
        reporting the state would otherwise be indistinguishable from choosing
        it -- the trap this project has already walked into twice, once with
        the theme checkbox and once here.
        """
        following = self.following
        # The count is about a tail, and a file has none: in a loaded capture
        # every row below the viewport has already been there since it opened,
        # and calling that "behind" would invent an arrival. Asked of the
        # capture rather than of the control that reports it -- a widget's
        # enabled state is a rendering of the answer, not the answer.
        behind = self.behind if self.capture_controller.is_running else 0
        self.status.set_following(following=following, behind=behind)
        self.action_follow.blockSignals(True)
        self.action_follow.setChecked(following)
        self.action_follow.blockSignals(False)

    def _follow(self) -> None:
        """Advance the tail, and say where it is.

        Two halves, and the split is the point: `tick` decides and scrolls,
        this puts the answer on screen. The controller says when to look rather
        than what to show.
        """
        self.follow_controller.tick()

    def export_capture(self) -> None:
        """Open the export dialog, if there is anything to export."""
        dialog = self.export_dialog()
        if dialog is not None:
            dialog.exec()

    def export_dialog(self) -> ExportDialog | None:
        """The dialog Export would open, or ``None`` with a banner saying why.

        Separate from `export_capture` because `exec()` is a nested event loop
        that only a person can leave, so nothing can test what this window
        decides to offer without hanging on it.

        A running capture used to be refused outright, on the reasoning in
        `docs/design/gui.md` §7: a file growing under the exporter produces a
        report whose end is arbitrary. The objection is real and the refusal was
        the wrong answer to it, for two reasons.

        The first is that the end is only arbitrary while it goes *unstated*.
        Every exporter in this package already declares its own omissions, so
        the honest form of "this report stops somewhere" is a sentence saying
        where, which is what `exporters.notes` is for. A snapshot that says it
        is a snapshot is not a report with an arbitrary end; it is a report with
        a declared one.

        The second is that this was already built. `storage.spool` emits a
        ``Z_SYNC_FLUSH`` boundary as it writes precisely so that a reader can
        decompress everything up to the last one, and its module docstring says
        live export during capture depends on it. The capability existed and the
        window declined to use it.
        """
        if self.capture is not None:
            return ExportDialog(self.capture, self)

        # A plain attribute read on the controller, not a signal: this runs
        # while the capture is live and a queued signal would need the event
        # loop to have turned first.
        path = self.capture_controller.path
        if path is None:
            self.banner.show_message(
                "There is nothing to export yet. Open a capture, or record one from a device.",
                "Open capture…",
                on_action=self.choose_capture,
            )
            return None

        try:
            snapshot = open_capture(path)
        except OstraceError as exc:
            # The session file exists but cannot be read yet -- the first flush
            # boundary has not been written, most likely, which on a quiet
            # device is a real wait rather than a moment.
            self.banner.show_message(
                f"Nothing can be read from the capture yet: {exc}",
                "Dismiss",
            )
            return None
        return ExportDialog(snapshot, self, running=True)

    # -- navigation, marks, copy -----------------------------------------

    def go_to(self, row: int | None) -> None:
        """Select and scroll to a row, if there is one."""
        if row is None or not 0 <= row < self.model.rowCount():
            return
        index = self.model.index(row, 0)
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def go_to_top(self) -> None:
        self.go_to(0)

    def go_to_bottom(self) -> None:
        """Jump to the last row, and resume following if already there.

        Two commands on one key, in the order klogg settled on: the first press
        takes you to the bottom, the second says *stay* there. Conflating them
        into one is what leaves Wireshark's users with "Ctrl End is close, but
        doesn't resume auto scroll".

        The second press *clears the selection*, which is what "stay" means
        here rather than a flag saying so: a row that is no longer the last one
        is exactly how `_follow` recognises a reader who has stopped tailing,
        so a caret parked on the bottom would break the tail again on the very
        next record. Asking to follow is asking to watch the end, not to keep
        one record open while it races past.
        """
        last = self.model.rowCount() - 1
        if last < 0:
            return
        if self.table.currentIndex().row() == last:
            # Through `set_following`, which is the same request spelled
            # another way -- and which also puts `_at_bottom` back. Doing the
            # clearing and the scrolling here without it meant the second press
            # did not resume anything for a reader who had *scrolled* away
            # rather than clicked away: the flag stayed false, `_follow`
            # returned, and the promise in this docstring went unkept.
            self.set_following(follow=True)
            return
        self.go_to(last)

    def ask_for_time(self) -> None:
        """Ask where to jump to, then jump there.

        Split from `go_to_time` because this half calls a modal ``exec``, and a
        test that reaches a modal dialog does not fail -- it hangs, holding the
        job until it is killed. That has cost this suite once already, in the
        export dialog, and the fix is the same shape: the asking and the doing
        are separate methods and the tests drive the doing.
        """
        current = self._time_anchor()
        if current is None:
            self.banner.show_message("There is nothing to jump through yet.", "Dismiss")
            return
        text, chosen = QInputDialog.getText(
            self,
            "Go to Time",
            f"Time, or an offset from {current:%H:%M:%S} ({EXAMPLES}):",
        )
        if chosen:
            self.go_to_time(text)

    def _time_anchor(self) -> datetime | None:
        """The instant a typed time is read relative to.

        The selected row if there is one, and otherwise the top of the screen:
        both are "where the reader is", and the second is what that means
        before they have clicked anything. Not the first row of the capture,
        which is where they were an hour of scrolling ago.
        """
        if self.model.rowCount() == 0:
            return None
        current = self.table.currentIndex()
        row = current.row() if current.isValid() else self.table.visible_rows()[0]
        return when(self.model.row_at(row))

    def go_to_time(self, text: str) -> None:
        """Jump to the first row at or after the time ``text`` names."""
        anchor = self._time_anchor()
        if anchor is None:
            return
        try:
            moment = parse_jump(text, anchor=anchor)
        except ValueError as exc:
            self.banner.show_message(str(exc), "Dismiss")
            return
        row = self.model.row_at_time(moment)
        if row is None:
            # Said with the time in it, because the usual cause is a digit
            # typed wrong rather than a capture that really ends there.
            self.banner.show_message(
                f"No record at or after {moment:%H:%M:%S} — the capture ends before it.",
                "Dismiss",
            )
            return
        self.go_to(row)

    def find_next(self, kind: Find, *, backwards: bool = False) -> None:
        current = self.table.currentIndex()
        start = current.row() if current.isValid() else -1 if not backwards else 0
        self.go_to(self.model.find(kind, start, backwards=backwards))

    def toggle_mark(self) -> None:
        current = self.table.currentIndex()
        if current.isValid():
            self.model.toggle_mark(current.row())
            self.minimap.rebuild()

    def step_row(self, delta: int) -> None:
        """Move the selection without needing the table to have focus.

        Wireshark documents exactly this and it is necessary rather than a
        nicety once there is a detail pane: reading a record puts focus in the
        pane, and the next thing anyone wants is the next record.
        """
        current = self.table.currentIndex()
        row = current.row() + delta if current.isValid() else 0
        self.go_to(max(0, min(row, self.model.rowCount() - 1)))

    def copy_selection(self) -> None:
        """Copy the selected rows as tab-separated text.

        Rows rather than cells, and TSV rather than anything cleverer, because
        the destination is a bug report or a spreadsheet. Two things the table
        does for readability are undone on the way out:

        - **a blanked repeat cell is filled back in.** What was elided to make
          a long run scannable would be a hole in a pasted record, in exactly
          the fields that identify it.
        - **the message is folded onto one line**, by the exporters' own
          `escape`. Device messages really do contain newlines and tabs, and a
          record spilling across several lines breaks every consumer of a
          tab-separated paste -- which is the whole audience for this. Reused
          rather than reinvented: the folding rule is part of the bundle
          contract, and two spellings of it would eventually disagree.
        """
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows:
            return
        lines = [
            "\t".join(
                escape(self.model.cell_text(row, column))
                for column in range(self.model.columnCount())
            )
            for row in rows
        ]
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n".join(lines))

    def copy_filter(self) -> None:
        """Copy the standing filter as one line of text.

        The half of a shareable filter that needs no parser. Somebody says
        "I only see this under `level:error -process:backupd`" in an issue and
        the reader sets the same four controls in four seconds, where a
        screenshot of the bar makes them squint and a description of it makes
        them guess.

        The bar's value, not the model's: a half-typed regular expression
        leaves the model on the previous filter, and copying that would hand
        over the filter the user is *leaving* rather than the one in front of
        them. `current()` raises on it, and an unusable filter is not worth
        putting on the clipboard silently.
        """
        try:
            text = self.filter_bar.current().as_text()
        except ValueError:
            self.status.showMessage("The filter is not finished, so there is nothing to copy")
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self.status.showMessage(f"Copied the filter: {text}")

    def show_keys(self) -> None:
        """The key sheet, rendered from the same table the bindings come from.

        A table rather than padded text: the padding lined the columns up only
        in a monospaced font, and a `QMessageBox` label is proportional on
        every platform, so what shipped was ragged everywhere.
        """
        rows = "".join(
            f"<tr><td style='padding-right:1.5em'><b>{escape_html(keys)}</b></td>"
            f"<td style='padding-right:1em'>{escape_html(label)}</td>"
            f"<td>{escape_html(why)}</td></tr>"
            for label, keys, why in key_table()
        )
        box = QMessageBox(self)
        box.setWindowTitle("Keyboard shortcuts")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(f"<table cellspacing='0'>{rows}</table>")
        box.exec()

    def show_about(self) -> None:
        """Which version this is, and what it is built on.

        The application already knows its version -- `app.build_application`
        sets it -- and until this existed there was nowhere in the viewer that
        said it out loud. A bug report against "the GUI" with no version in it
        costs a round trip.
        """
        QMessageBox.about(
            self,
            "About ostrace",
            f"<h3>ostrace {escape_html(__version__)}</h3>"
            "<p>Stream, inspect and export iOS device logs on Windows, macOS and Linux.</p>"
            "<p>GPL-3.0-or-later. Built on "
            "<a href='https://github.com/doronz88/pymobiledevice3'>pymobiledevice3</a>"
            " and Qt for Python.</p>"
            "<p><a href='https://github.com/BerkayCaglar/ostrace'>"
            "github.com/BerkayCaglar/ostrace</a></p>",
        )

    # -- filtering, selection, state -------------------------------------

    def _on_filter_changed(self) -> None:
        """Coalesce keystrokes into one rescan.

        Rescanning per character is what makes Android Studio's Logcat throw
        the user to the bottom of the buffer on every key they press.
        """
        self._filter_debounce.start()
        # Restarted, so only a filter left alone is ever remembered.
        self._filter_settled.start()
        # Not debounced: the menu item is read at the moment somebody opens the
        # menu, and a Copy Filter that stays enabled for a third of a second
        # after the bar was emptied copies an empty line.
        self.action_copy_filter.setEnabled(not self.filter_bar.is_empty)

    def _remember_filter(self) -> None:
        """Add the standing filter to the recent list, if it is worth having.

        Driven by a timer rather than by the apply, because every keystroke
        applies: remembering there would fill the list with the prefixes of the
        one filter somebody typed.
        """
        before = self._recent
        self._recent = remember(before, self.model.filter)
        if self._recent != before:
            self.filter_bar.set_recent(self._recent)
            self._save_recent()

    def _on_recent_chosen(self, entry: object) -> None:
        """Put a remembered filter back in the bar, which applies it."""
        if isinstance(entry, Filter):
            self.filter_bar.set_filter(entry)

    def name_current_filter(self) -> None:
        """Ask for a name and keep the standing filter under it.

        The name is asked for *after* the filter exists, never before: a viewer
        that wants a name up front is one people decline, which is the whole
        reason the recent list is unnamed.

        Saving over an existing name replaces it, and the prompt is
        pre-filled with nothing rather than with a guess -- a suggested name
        derived from the terms would be accepted unread, and a menu of
        `level:error process:dasd` is the summary line the recent half already
        offers.
        """
        try:
            terms = self.filter_bar.current()
        except ValueError:
            self.status.showMessage("The filter is not finished, so there is nothing to save")
            return
        if terms.is_empty:  # pragma: no cover - the menu row is disabled
            return
        name, chosen = QInputDialog.getText(self, "Save filter", "Name")
        if not chosen or not name.strip():
            return
        self._set_saved(save(self._saved, SavedFilter(name=name.strip(), terms=terms)))
        self.status.showMessage(f"Saved the filter as {name.strip()!r}")

    def manage_saved_filters(self) -> None:
        """Open the list of named filters, and keep whatever it returns.

        Split from the dialog itself the way every other modal here is: the
        window builds it, and what the dialog does to the list is testable
        without opening one.
        """
        dialog = SavedFiltersDialog(self._saved, self)
        dialog.exec()
        self._set_saved(dialog.saved)

    def _set_saved(self, saved: list[SavedFilter]) -> None:
        """Hold the named filters, offer them, and write them down."""
        self._saved = saved
        self.filter_bar.set_saved(saved)
        WindowSettings().write_saved(saved)

    def _on_context_menu(self, position: QPoint) -> None:
        """Pop the row menu where it was asked for.

        Split from `row_menu` because this half is a modal ``exec``, and a test
        that reaches one does not fail -- it hangs, holding the job until it is
        killed. The export dialog and `Go to Time` are split for the same
        reason; this one cost the suite two minutes before it was.

        Mapped through the viewport: `position` arrives in viewport coordinates
        and a menu popped at the widget's would sit one header height too high.
        """
        menu = self.row_menu(self.table.indexAt(position))
        menu.exec(self.table.viewport().mapToGlobal(position))

    def row_menu(self, index: QModelIndex) -> QMenu:
        """The menu on a row: narrow by what is in front of you.

        Built here rather than in the table because every entry on it is an
        action this window already owns -- which is the same rule the toolbar
        follows. A context menu that implemented its own copy or its own mark
        would be a second implementation to keep in step with the first.
        """
        menu = QMenu(self)
        row = self.model.row_at(index.row()) if index.isValid() else None
        if isinstance(row, Record):
            # `row.process` rather than the cell, which the table blanks when
            # it repeats the row above: right-clicking half way down a run of
            # one process would otherwise offer to filter by nothing.
            menu.addAction(
                f"Filter by process {row.process}", lambda: self.filter_by_process(row.process)
            )
            if row.subsystem:
                menu.addAction(
                    f"Filter by subsystem {row.subsystem}",
                    lambda: self.filter_by_subsystem(row.subsystem or ""),
                )
            menu.addSeparator()
        menu.addAction(self.action_copy)
        menu.addAction(self.action_mark)
        menu.addSeparator()
        menu.addAction(self.action_go_time)
        return menu

    def filter_by_process(self, process: str) -> None:
        """Narrow to one process, keeping everything else that is set.

        Keeping, because the right-click is almost always the second step:
        somebody already at `Error and above` who spots one noisy process is
        asking for the errors *from it*, not for a fresh start.

        Written into the bar rather than built from `model.filter`, which is
        the *applied* filter and lags the bar by the debounce -- a right-click
        a fifth of a second after a keystroke would silently discard it.
        """
        self.filter_bar.set_process(process)

    def filter_by_subsystem(self, subsystem: str) -> None:
        self.filter_bar.set_subsystem(subsystem)

    def _bar_filter(self) -> Filter | None:
        """What the bar is currently displaying, or `None` if it is half-typed.

        Separate from `_apply_filter` because a model swap needs the filter
        without the readouts and the banner that follow one: the new model is
        empty at that moment, and `_update_banner` would read that as a capture
        with nothing in it and say so, a sentence the loader contradicts a
        fraction of a second later.
        """
        try:
            return self.filter_bar.current()
        except ValueError as exc:
            # Half a pattern is not an empty log. The previous filter stays
            # applied and the user is told why, rather than watching the view
            # empty itself as they type.
            self.banner.show_message(str(exc), "Dismiss")
            return None

    def _apply_filter(self) -> None:
        wanted = self._bar_filter()
        if wanted is None:
            return

        anchor = self._anchor()
        self.model.set_filter(wanted)
        self._restore(anchor)
        self._update_counts()
        self._update_banner()

    def _update_counts(self) -> None:
        """Refresh the readouts that a filter change moves."""
        self.status.set_volume(self.model.retained)
        self.status.set_gap_count(self.model.gaps)
        self.status.set_shown(self.model.rowCount(), self.model.retained)

    def _anchor(self) -> int | None:
        """Which retained item the user is currently reading.

        A position in the retained list, not a view row: view rows are
        renumbered by the rescan that is about to happen.
        """
        current = self.table.currentIndex()
        if not current.isValid() or self.model.rowCount() == 0:
            return None
        return self.model.source_index(current.row())

    def _restore(self, anchor: int | None) -> None:
        """Put the user back where they were reading.

        The record they had selected may not have survived the new filter, in
        which case the nearest survivor after it is where they were. Nobody
        surveyed does this -- see `RecordModel.nearest_view_row`.
        """
        if anchor is None:
            return
        row = self.model.nearest_view_row(anchor)
        if row is None:
            return
        index = self.model.index(row, 0)
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _on_current_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        del previous
        # Selecting a row stops the tail, so the indicator has to move with the
        # selection and not only with the next batch of records -- a capture
        # that has gone quiet would otherwise still claim to be following.
        self._show_follow_state()
        if not current.isValid():
            self.detail.clear()
            return
        # No host clock: these records came out of a file. Comparing one
        # against the present moment measures how long ago it was captured, not
        # how far apart the two clocks are, and labelling that "difference"
        # would invent a problem the device does not have. The live path, which
        # does have two readings of one moment, will pass it.
        self.detail.show_item(self.model.row_at(current.row()))

    def _update_placeholder(self) -> None:
        """What the table says when it has nothing to show.

        Ordered by how much the user already knows: someone who has just opened
        the program is told what the program is for, someone whose device is
        quiet is told the connection is fine. The two states with an action --
        a filter that hides everything, an empty capture -- belong to the
        banner, which can offer it, so the table stays quiet under them rather
        than saying the same thing twice.
        """
        if self.model.retained > 0:
            self.table.set_placeholder("")
        elif self.capture_controller.is_running:
            self.table.set_placeholder(
                "Waiting for the device",
                "Connected and listening. Records appear as the device emits them.",
            )
        elif self.capture is None:
            self.table.set_placeholder(
                "No capture open",
                "Open a saved capture, or record one from an attached device.",
            )
        else:
            self.table.set_placeholder("")

    def _update_banner(self) -> None:
        """The states that look exactly like a quiet device.

        A filter that matches nothing, a capture with nothing in it, and a
        device that is saying nothing all produce the same empty table. Only
        some of them are the user's own doing, and they need different answers,
        so an empty table has to say which one it is.

        The banner carries the ones with a way out; the table itself carries
        the two that have none, because a banner offering no action is a strip
        of text the user cannot dismiss.
        """
        self._update_placeholder()
        if self.model.rowCount() == 0 and self.model.retained > 0:
            self.banner.show_message(
                f"All {self.model.retained:,} records are hidden by the filter.",
                "Clear filter",
                on_action=self.filter_bar.clear,
                key=Notice.FILTER_HIDES_EVERYTHING,
            )
            return
        if self.banner.current_key is Notice.FILTER_HIDES_EVERYTHING:
            self.banner.hide()
        if self.capture is not None and self.model.retained == 0:
            # An empty capture is a fact about the capture, not about the
            # filter and not about the device. Saying nothing here leaves the
            # reader to work out which of the three they are looking at.
            self.banner.show_message(
                "This capture contains no records.",
                "Open another…",
                on_action=self.choose_capture,
            )
