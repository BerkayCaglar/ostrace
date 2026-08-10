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
    QByteArray,
    QElapsedTimer,
    QModelIndex,
    QSettings,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
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
from ostrace.gui.columns import COLUMNS
from ostrace.gui.filters import Filter
from ostrace.gui.live import CaptureThread
from ostrace.gui.loader import CaptureLoader
from ostrace.gui.models import Find, RecordModel
from ostrace.gui.pump import Pump
from ostrace.gui.shortcuts import BINDINGS, key_table, sequences
from ostrace.gui.theme import Scheme, apply_theme, scheme_for
from ostrace.gui.widgets.banner import Banner
from ostrace.gui.widgets.detail_pane import DetailPane
from ostrace.gui.widgets.device_button import DeviceButton
from ostrace.gui.widgets.export_dialog import ExportDialog
from ostrace.gui.widgets.filter_bar import FilterBar
from ostrace.gui.widgets.jump_button import JumpButton
from ostrace.gui.widgets.log_table import LogTable
from ostrace.gui.widgets.minimap import Minimap
from ostrace.gui.widgets.status_bar import StatusBar
from ostrace.model import DeviceInfo
from ostrace.paths import export_stem, sessions_dir
from ostrace.storage.capture import Capture, open_capture

if TYPE_CHECKING:
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

#: How long to wait for the capture thread to release the device. Its teardown
#: is a socket close rather than a network round trip, so this is generous.
_STOP_TIMEOUT_MS = 5_000

#: How near the bottom still counts as "at the bottom" for auto-follow. A few
#: pixels of slack, because a scrollbar rarely lands exactly on its maximum.
_FOLLOW_SLACK = 4

#: How often the tail may actually scroll. Ten times a second still reads as
#: continuous, and it is the difference between a third of the GUI thread going
#: into repaints and a fifth: at device throughput every drain scrolls further
#: than the viewport is tall, so each one is a full repaint of every visible
#: cell. `docs/design/gui.md` §9 asks for this to be a preference; a measured
#: constant is what 0.1.0 ships.
_FOLLOW_MIN_MS = 100

#: How long the filter waits for the typing to stop. Long enough that a word is
#: one rescan rather than five, short enough that the table does not feel
#: detached from the keyboard.
_FILTER_DEBOUNCE_MS = 200

#: What the window opens at when there is nothing saved, or when what was saved
#: turned out to be unusable. Wide enough for the fixed columns and the start of
#: a message, which is the narrowest the table is worth reading at.
_DEFAULT_SIZE = QSize(1280, 800)

#: Below this in either direction a restored window is not something a person
#: can use, whatever the settings say.
_MIN_USABLE = 200


def _submenu(action: QAction) -> QMenu | None:
    """The submenu an action opens, or ``None`` if it is a plain item."""
    menu = action.menu()
    return menu if isinstance(menu, QMenu) else None


class MainWindow(QMainWindow):
    """Toolbar, filter bar, table, detail pane, status bar."""

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
    action_deselect: QAction
    action_find: QAction
    action_mark: QAction
    action_clear_marks: QAction
    action_top: QAction
    action_bottom: QAction
    action_follow: QAction
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
    action_keys: QAction
    action_quit: QAction
    action_about: QAction

    def __init__(self, scheme: Scheme = Scheme.LIGHT, parent: QWidgetType | None = None) -> None:
        super().__init__(parent)
        self.scheme = scheme
        #: Set once the user picks a theme, after which the system stops
        #: being consulted. Default is to follow it.
        self._theme_chosen = False
        #: Whether the tail should stay at the bottom. Only a person can
        #: turn it off -- see `_on_user_scroll`.
        self._at_bottom = True
        self._user_scrolled = False
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
        self._showing_filter_notice = False
        #: When the tail last scrolled. See `_follow`.
        self._scrolled = QElapsedTimer()
        self._capture_thread: CaptureThread | None = None
        #: Capture threads that outlived their stop wait. See `_park`.
        self._parked: list[CaptureThread] = []
        self._pump: Pump | None = None
        self.model = RecordModel(scheme, parent=self)
        self.table.setModel(self.model)
        self.minimap.set_model(self.model)
        self.minimap.row_requested.connect(self.go_to)
        self._connect_selection()

        self._filter_debounce = QTimer(self)
        self._filter_debounce.setSingleShot(True)
        self._filter_debounce.setInterval(_FILTER_DEBOUNCE_MS)
        self._filter_debounce.timeout.connect(self._apply_filter)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()

        self._connect_actions()
        self._follow_color_scheme()
        self._restore_theme()
        self._set_capturing(capturing=False)

    def _restore_theme(self) -> None:
        """Re-apply a theme the user chose in an earlier session.

        Absent, the window follows the system, which is the right default and
        was the only behaviour. The checkbox is set through `_show_theme_state`
        so that restoring a preference does not look like expressing one.
        """
        stored = self._settings().value("window/theme")
        if stored not in (Scheme.LIGHT.value, Scheme.DARK.value):
            return
        scheme = Scheme(stored)
        self._theme_chosen = True
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, scheme)
        self.set_scheme(scheme)
        self._show_theme_state()

    def _follow_color_scheme(self) -> None:
        """Track the operating system's light/dark setting while this window lives.

        A bound method rather than a lambda closing over ``self``: Qt drops a
        connection whose receiver is a destroyed ``QObject``, and a lambda would
        instead keep this window alive for as long as the application and then
        call into a deleted C++ object.
        """
        app = QApplication.instance()
        if not isinstance(app, QApplication):  # pragma: no cover - no app, no signal
            return
        app.styleHints().colorSchemeChanged.connect(self._on_color_scheme_changed)

    def _on_color_scheme_changed(self, colour_scheme: Qt.ColorScheme) -> None:
        """Follow the operating system, if the user has not overruled it.

        Both halves of the switch happen here, and that is the point.
        `apply_theme` moves the application -- palette, tooltips, chrome
        stylesheet -- and `set_scheme` moves what this window prebuilt for
        itself. `gui.app` used to make the first call from its own connection
        to this same signal, under a rule that could not see `_theme_chosen`,
        so the two listeners disagreed the moment anybody picked a theme: the
        chrome went dark and the table stayed white, which reads as a broken
        dark mode rather than as a preference being honoured.
        """
        if self._theme_chosen:
            # The user said which one they wanted. The operating system is the
            # default, not the authority.
            return
        scheme = scheme_for(colour_scheme)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, scheme)
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
        """Choose a theme, rather than inheriting one.

        The viewer followed the system and offered no way to disagree with it,
        which is fine until you are the person reading a log at night on a
        machine set to light -- or the reverse. Reported as "there is no dark
        mode", and there was one; there was no way to ask for it.

        Choosing stops the following, and it is remembered. `apply_theme` is
        called here as well as `set_scheme`: the palette belongs to the
        application and the prebuilt colours belong to this window, and a
        switch that moved only one of them is the bug this project already
        found once, where every severity colour stayed in the previous scheme.
        """
        self._theme_chosen = True
        scheme = Scheme.DARK if dark else Scheme.LIGHT
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, scheme)
        self.set_scheme(scheme)
        self._settings().setValue("window/theme", scheme.value)

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
        icons.clear_cache()
        self._apply_icons()

    def _build_layout(self) -> None:
        """Assemble the widgets. No behaviour, no state."""
        self.filter_bar = FilterBar(self)
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
        self.action_open.triggered.connect(self.choose_capture)
        self.action_close.triggered.connect(self.close_capture)
        self.action_capture.triggered.connect(self.capture_from_device)
        self.action_disconnect.triggered.connect(self.stop_capture)
        self.action_pause.toggled.connect(self.set_paused)

        self.action_copy.triggered.connect(self.copy_selection)
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
        self.action_keys.triggered.connect(self.show_keys)

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
        # A new capture and a newly opened file both build a new model, and a
        # connection to the old one dies with it.
        self._at_bottom = True
        self.model.top_shifted.connect(self._keep_place)

    def _on_user_scroll(self) -> None:
        """The user moved the view themselves.

        ``actionTriggered`` fires for a drag, a wheel, an arrow and a page --
        and *not* for ``setValue``, which is how everything this window does
        moves the view. That distinction is the whole mechanism: leaving the
        bottom is something a person does, and nothing else here can be
        mistaken for it.

        The position cannot be read yet -- the signal arrives before the value
        changes -- so this only records that a look is owed, and `_follow`
        takes it.
        """
        self._user_scrolled = True

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
        self.stop_capture()
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
        if self._restore_layout():
            return
        total = self._split.height()
        share = _TABLE_STRETCH + _DETAIL_STRETCH
        self._split.setSizes([total * _TABLE_STRETCH // share, total * _DETAIL_STRETCH // share])

    # -- what the window remembers ---------------------------------------

    def _settings(self) -> QSettings:
        """Where the layout is kept between sessions.

        `gui.app` has set the organisation and application names since it was
        written -- which is what stops Qt filing settings under a vendor called
        "Unknown" -- and nothing ever constructed a `QSettings` to use them.
        Qt picks the location per platform, so this is not a decision `paths`
        owns: no file of ours is being placed.
        """
        return QSettings()

    def _restore_jump(self) -> Find:
        """Which jump target the last session left the toolbar on."""
        stored = self._settings().value("table/jump")
        try:
            return Find(stored)
        except ValueError:
            # Absent, or written by a version that offered a kind this one does
            # not. The default is the one every reader wants first.
            return Find.ERROR

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
        """Remember the window, the split and the columns.

        Only geometry. Not the filter, and not the open capture: a viewer that
        reopened yesterday's file would be guessing, and a filter that survived
        a restart is one the user has to remember they set -- which is the
        "where did my logs go" failure with a longer fuse.
        """
        settings = self._settings()
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("window/state", self.saveState())
        settings.setValue("window/split", self._split.saveState())
        settings.setValue(
            "table/columns",
            [self.table.columnWidth(index) for index in range(len(COLUMNS))],
        )
        # A way of reading rather than a property of a capture, so it belongs
        # with the geometry and not with the filter, which is deliberately not
        # remembered.
        settings.setValue("table/jump", self._jump.value)

    def _restore_layout(self) -> bool:
        """Put it back, and say whether there was anything to put.

        Column widths are only restored if the count still matches: a capture
        opened by a version with a different set of columns would otherwise get
        widths applied to the wrong ones, which looks like a rendering fault
        rather than like stale settings.
        """
        settings = self._settings()
        geometry = settings.value("window/geometry")
        if not isinstance(geometry, QByteArray):
            return False
        if not self.restoreGeometry(geometry) or not self._on_a_screen():
            # A geometry can be well-formed and still unusable: saved on a
            # second monitor that is no longer attached, saved by a window
            # manager that reported a size of nothing, or -- how this was
            # found -- saved by an offscreen test run and restored on a real
            # display, where the window opened somewhere nothing could show it
            # and the program looked as though it had failed to start.
            self.resize(_DEFAULT_SIZE)
            return False
        state = settings.value("window/state")
        if isinstance(state, QByteArray):
            self.restoreState(state)
        split = settings.value("window/split")
        if isinstance(split, QByteArray):
            self._split.restoreState(split)
        widths = settings.value("table/columns")
        if isinstance(widths, list) and len(widths) == len(COLUMNS):
            # Through the table rather than column by column, so that it knows
            # these are the user's widths and stops fitting its own.
            self.table.restore_column_widths([int(width) for width in widths])
        return True

    # -- actions ---------------------------------------------------------

    def _build_actions(self) -> None:
        """Build every action from `gui.shortcuts.BINDINGS`.

        The bindings table is also the help sheet, so a key that changes here
        changes the documentation in the same commit or not at all. klogg's
        fourth trap is a key table in a manual that drifted from the code.

        ``_action`` refuses to create one without a menu role, which is the
        point: a rule enforced by the only constructor survives someone adding
        a menu item in a hurry.
        """
        self.actions_by_name: dict[str, QAction] = {}
        for binding in BINDINGS:
            keys = sequences(binding)
            action = self._action(binding.text, keys[0], checkable=binding.checkable)
            if len(keys) > 1:
                # Aliases are real bindings, not documentation. A menu shows
                # one; `setShortcuts` registers all of them.
                action.setShortcuts(keys)
            action.setToolTip(binding.description)
            setattr(self, f"action_{binding.name}", action)
            self.actions_by_name[binding.name] = action

        # Qt relocates these three on macOS by matching their text, and should:
        # that is the native behaviour a Mac user expects. They get the real
        # role rather than NoRole, and they are built here rather than in the
        # table because their roles, not their keys, are the point.
        self.action_quit = self._action(
            "&Quit", QKeySequence.StandardKey.Quit, role=QAction.MenuRole.QuitRole
        )
        self.action_about = self._action("&About ostrace", role=QAction.MenuRole.AboutRole)

        self.action_quit.triggered.connect(self.close)
        self.action_about.triggered.connect(self.show_about)

    def _action(
        self,
        text: str,
        shortcut: QKeySequence | QKeySequence.StandardKey | None = None,
        *,
        role: QAction.MenuRole = QAction.MenuRole.NoRole,
        checkable: bool = False,
    ) -> QAction:
        """Build one action. ``role`` defaults to *not moving*, never to the heuristic."""
        action = QAction(text, self)
        action.setMenuRole(role)
        action.setCheckable(checkable)
        # The toolbar and the menus share these objects, and an icon put on one
        # for the toolbar's sake is drawn by the other in the column a
        # checkmark occupies. The two jump buttons carry chevrons, so `Next
        # Error` and `Previous Error` appeared in the View menu with what reads
        # as a tick and an indicator beside them, next to a `Dark Mode` whose
        # tick is real. Icons belong on the toolbar, where they are the label.
        action.setIconVisibleInMenu(False)
        if shortcut is not None:
            # StandardKey maps Ctrl to Cmd on macOS *and* knows where the two
            # platforms genuinely differ, which a literal string cannot.
            action.setShortcut(QKeySequence(shortcut))
        self.addAction(action)
        return action

    def _build_menus(self) -> None:
        bar = self.menuBar()

        # Each menu is constructed with this window as its parent and added by
        # object, never by `bar.addMenu("title")`. That convenience overload
        # returns a menu Python owns, so the local reference is the only thing
        # keeping it alive and the menu dies at the end of this method. The
        # failure surfaces nowhere near here: the menu bar keeps an action
        # whose `menu()` hands back a fresh wrapper around freed memory, which
        # reports itself valid right up until it is used.
        self.menus = {
            name: QMenu(title, self)
            for name, title in (
                ("capture", "&Capture"),
                ("edit", "&Edit"),
                ("view", "&View"),
                ("help", "&Help"),
            )
        }
        for menu in self.menus.values():
            bar.addMenu(menu)

        # A separator wherever the group changes. Declared in the bindings table
        # rather than inserted here by name, so a reordered or added item lands
        # in the right run without anybody remembering to move a divider: the
        # View menu is eleven items and was one undivided column of them.
        seen: dict[str, str] = {}
        for binding in BINDINGS:
            menu = self.menus[binding.menu]
            if binding.menu in seen and seen[binding.menu] != binding.group:
                menu.addSeparator()
            seen[binding.menu] = binding.group
            menu.addAction(self.actions_by_name[binding.name])

        self.menus["capture"].addSeparator()
        self.menus["capture"].addAction(self.action_quit)
        self.menus["help"].addSeparator()
        self.menus["help"].addAction(self.action_about)

    def menu_items(self) -> list[QAction]:
        """Every clickable item in the menu bar, for the menu-role test.

        Walked from the menu bar rather than filtered out of
        ``findChildren(QAction)``: that returns widget actions too -- each
        ``QLineEdit`` with a clear button contributes one -- and none of those
        can be relocated by a menu heuristic because none of them is in a menu.
        Asking the menu bar what is in it is both narrower and truer.
        """
        items: list[QAction] = []
        # `QAction.menu()` is typed as returning QObject, so every result is
        # narrowed rather than assumed -- and `isinstance` is also the check
        # that separates a submenu from a plain item.
        pending = [menu for action in self.menuBar().actions() if (menu := _submenu(action))]
        while pending:
            for action in pending.pop().actions():
                if action.isSeparator():
                    continue
                submenu = _submenu(action)
                if submenu is not None:
                    pending.append(submenu)
                else:
                    items.append(action)
        return items

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

    def open_capture(self, path: Path) -> None:
        """Load a capture into the table.

        Read in batches from the event loop rather than in one pass -- see
        `gui.loader`. Replacing the contents rather than appending to them: two
        captures interleaved by arrival order would be a timeline that never
        happened.
        """
        if self._loader is not None:
            self._loader.cancel()

        try:
            capture = open_capture(path)
        except OstraceError as exc:
            self.banner.show_message(f"Could not open {path.name}: {exc}", "Dismiss")
            return

        self.stop_capture()
        self.capture = capture
        self.model = RecordModel(self.scheme, parent=self)
        self.table.setModel(self.model)
        self.minimap.set_model(self.model)
        self._connect_selection()
        self.detail.clear()
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
        if self._capture_thread is not None:
            self.banner.show_message(
                "A capture is still running. Disconnect to finish it, and the "
                "window can be emptied after that.",
                "Disconnect",
                on_action=self.stop_capture,
            )
            return

        if self._loader is not None:
            self._loader.cancel()
            self._loader = None

        self.capture = None
        self.model = RecordModel(self.scheme, parent=self)
        self.table.setModel(self.model)
        self.minimap.set_model(self.model)
        self.minimap.rebuild()
        self._connect_selection()
        self.detail.clear()
        # The filter goes with it. A filter that outlived the capture it was
        # written for is the "where did my logs go" failure with a longer fuse,
        # and this is the one moment the window knows for certain that it is
        # not the filter for whatever comes next.
        self.filter_bar.clear()
        self.banner.hide()
        self._showing_filter_notice = False
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
        if self._capture_thread is not None:
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
        """The live source. Imported here, not at module scope.

        `ostrace.sources.os_trace` refuses to be imported under ``-O``, and it
        pulls in pymobiledevice3 -- about forty packages. Neither belongs in the
        path that merely opens a saved capture.
        """
        from ostrace.sources.os_trace import OsTraceSource  # noqa: PLC0415

        # The udid the toolbar is showing, which until the device selector
        # existed was always `None` -- "whichever answers first". With two
        # devices attached that was a coin toss the user could not see and,
        # since nothing named the winner, could not lose either.
        return OsTraceSource(self.device_button.udid)

    def start_capture(self, source: LogSource, *, destination: Path | None = None) -> None:
        """Begin a live capture into a fresh model.

        The records go to a session file as well as to the table -- the same
        `ostrace.capture.capture` the CLI runs. A live view that keeps nothing
        would make "pause" a promise it cannot honour and would lose everything
        the moment the window closed. ``destination`` overrides where that file
        goes; by default `paths` decides, as it does for the CLI.
        """
        self.stop_capture()

        self.model = RecordModel(self.scheme, parent=self)
        self.table.setModel(self.model)
        self.minimap.set_model(self.model)
        self._connect_selection()
        self.detail.clear()
        self.capture = None
        # Not known until the device answers, which is a round trip. The title
        # says so rather than guessing, and `_on_identified` fills it in.
        self._device_name = None

        self._capture_thread = CaptureThread(source, destination=destination)
        self._pump = Pump(self._capture_thread.queue, self.model, parent=self)
        self._pump.rate_changed.connect(self._on_rate)
        self._pump.overflowed.connect(self._on_pause_overflow)
        self._capture_thread.identified.connect(self._on_identified)
        self._capture_thread.failed.connect(self._on_capture_failed)
        self._capture_thread.completed.connect(self._on_capture_finished)

        self._capture_thread.start()
        self._pump.start()
        self.minimap.start()
        self._set_capturing(capturing=True)

    def stop_capture(self) -> None:
        """Release the device.

        Named after its consequence rather than "stop": releasing a device
        releases the lockdown session *and* the ``os_trace_relay`` service, and
        a control that reads as the opposite of "pause" invites the user to
        press it expecting to be able to press it back.
        """
        if self._capture_thread is None:
            return
        thread = self._capture_thread
        thread.stop()
        # Bounded: the capture's own teardown is a socket close, not a network
        # round trip. Waiting at all is what stops a second capture starting
        # while the first still holds the device.
        if thread.wait(_STOP_TIMEOUT_MS):
            # Only once it has really ended: until then the session file is
            # still being written and the sidecar is not finalised.
            self._adopt_session(thread.path)
        else:
            self._park(thread)
        if self._pump is not None:
            self._pump.stop()
        self.minimap.stop()
        self._capture_thread = None
        self._set_capturing(capturing=False)

    def _adopt_session(self, path: Path | None) -> None:
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
        """
        if path is None:
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

    def _park(self, thread: CaptureThread) -> None:
        """Keep a capture thread that outlived the wait above.

        The wait is bounded so that a device which will not let go cannot
        freeze the window -- which means it can time out, and clearing the
        reference would then drop the last one to a *running* ``QThread``. That
        is not a leak. Qt's destructor calls ``qFatal`` on a running thread, so
        the window would not report a stuck capture, it would take the process
        down with it. A parked thread costs one small object instead.

        The user is told, because the consequence is theirs: the device is
        still held, so the next capture finds the relay busy.
        """
        self._parked.append(thread)
        # Queued, because `self` lives on the GUI thread and the signal is
        # emitted on the capture's: the object is destroyed by this thread once
        # the other has genuinely ended, and never from inside its own `run`.
        thread.finished.connect(self._reap)
        self.banner.show_message(
            "The capture has not released the device yet. It is still shutting "
            "down, and a new capture may fail until it has."
        )

    def _reap(self) -> None:
        """Let go of every parked thread that has actually finished."""
        self._parked = [thread for thread in self._parked if thread.isRunning()]

    def set_paused(self, paused: bool) -> None:
        """Freeze the view. The device is not consulted."""
        if self._pump is not None:
            self._pump.set_paused(paused)
        if paused:
            self.banner.show_message(
                "The view is paused. The capture is still running and still "
                "writing every record to the session file.",
                "Resume",
                on_action=lambda: self.action_pause.setChecked(False),
            )
        else:
            self.banner.hide()

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
        self.device_button.busy_udid = self.device_button.udid if capturing else None
        # The funnel every capture state change passes through, including the
        # one at construction -- which is what puts a sentence on the cold-start
        # window instead of an empty grid, and the right name on the title bar
        # whichever way the capture started or ended.
        self._update_placeholder()
        self._retitle()
        if not capturing:
            self.action_pause.setChecked(False)
            self.status.set_rate(None)

    def _on_identified(self, device: object) -> None:
        if isinstance(device, DeviceInfo):
            self.status.set_device(device)
            if self._capture_thread is not None:
                # Which device is actually held, rather than which one was
                # picked. They are the same when the user chose one and they
                # are not when nobody did -- and the one a scan must leave
                # alone is the one the capture thread is blocked on reading,
                # which only the device itself can say.
                self.device_button.busy_udid = device.udid
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

    def _on_capture_failed(self, message: str) -> None:
        """The capture died. Wind the machinery down as if Disconnect had been
        pressed, because from here on nothing is going to press it.

        Retry rather than Dismiss: the message is almost always "no device", and
        the answer to that is to plug one in and go again. Dismissing it just
        clears the sentence off the screen.
        """
        self.stop_capture()
        self.banner.show_message(
            f"Capture stopped: {message}",
            "Retry",
            on_action=self.capture_from_device,
        )

    def _on_capture_finished(self, result: object) -> None:
        """The capture ended by itself -- the device was unplugged, or a limit
        was reached.

        The same wind-down as Disconnect, and for the same reasons: the pump
        and the overview timer are still running against a stream that has
        stopped, and the session on disk is finished and worth picking up. The
        thread has already ended by the time this queued signal arrives, so the
        wait inside `stop_capture` returns at once.
        """
        del result  # `stop_capture` reads the path off the thread, which is the same one
        self.stop_capture()

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

        Derived, and this is the *only* derivation -- `_follow` acts on it and
        the status bar shows it, so the indicator cannot disagree with the
        behaviour. `docs/design/gui.md` §4 is explicit that a stored bit can
        disagree with the view, and Console.app shipped an eleven-month bug of
        exactly that shape; an indicator computed separately from the thing it
        indicates is the same mistake with a second face.
        """
        last = self.model.rowCount() - 1
        current = self.table.currentIndex()
        if last >= 0 and current.isValid() and current.row() < last:
            # A selection that is not the last row is the evidence of a reader
            # who has stopped tailing, read from the view rather than stored.
            return False
        return self._at_bottom

    def set_following(self, *, follow: bool) -> None:
        """Turn the tail on or off, from the status bar or the keyboard.

        Selecting a row stops the tail deliberately, and getting back to it
        meant a key nobody had been told about or a menu item two levels down.
        Turning it back on therefore lets go of the row as well as returning to
        the end -- asking to watch the newest records is not asking to keep one
        old record open while they race past. That is the same thing the second
        press of `Go to Bottom` does, for the same reason.
        """
        self._user_scrolled = False
        self._at_bottom = follow
        if follow:
            self.table.clearSelection()
            self.table.setCurrentIndex(QModelIndex())
            self.detail.clear()
            self.table.scrollToBottom()
        self._show_follow_state()

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
        self.status.set_following(following=following)
        self.action_follow.blockSignals(True)
        self.action_follow.setChecked(following)
        self.action_follow.blockSignals(False)

    def _follow(self) -> None:
        """Stay at the bottom, but only if that is where the user already is.

        Derived on every tick rather than stored as a mode. A stored flag can
        disagree with the view -- Console.app kept one and shipped an
        eleven-month bug where selecting a row silently stopped the tail.

        Two ways to leave the bottom, and both have to count. Scrolling up is
        the obvious one. **Selecting a row is the other, and it is not
        optional here**: this window has a detail pane, so selection is the
        primary interaction, and a tail that survived it would drag the row out
        from under whoever just clicked it -- which is the Console.app bug from
        the other direction.

        Still no stored bit. A selection that is no longer the last row *is*
        the evidence, and it is read from the view like the scrollbar. The
        `following` property is where that reading lives, so the indicator in
        the status bar and this method cannot come to different conclusions.
        """
        if self._user_scrolled:
            # Read once, when a person has just moved the view. Reading it on
            # every tick instead is what broke this: appending raises the
            # maximum and leaves the value alone, so a view that had simply not
            # been scrolled *yet* -- or one whose scroll had just been skipped
            # by the throttle below -- looked exactly like a reader who had
            # gone up, and follow died on the first batch and stayed dead.
            bar = self.table.verticalScrollBar()
            self._at_bottom = bar.value() >= bar.maximum() - _FOLLOW_SLACK
            self._user_scrolled = False
        self._show_follow_state()
        if self.model.rowCount() == 0 or not self.following:
            return
        # Throttled apart from the drain. Each tick appends about a hundred
        # rows and the scroll advances by a hundred, but the viewport holds
        # forty -- so there is nothing to blit and every tick costs a full
        # repaint, measured at 20 ms, 15 times a second, a third of the GUI
        # thread. Draining stays at 50 ms so the queue never builds; only the
        # scrolling is coalesced, and no record is lost by coalescing it.
        if self._scrolled.isValid() and self._scrolled.elapsed() < _FOLLOW_MIN_MS:
            return
        self._scrolled.restart()
        self.table.scrollToBottom()

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

        path = self._capture_thread.path if self._capture_thread is not None else None
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

    def _apply_filter(self) -> None:
        try:
            wanted = Filter(
                minimum_level=self.filter_bar.minimum_level,
                process=self.filter_bar.process,
                subsystem=self.filter_bar.subsystem,
                search=self.filter_bar.search,
                regex=self.filter_bar.regex,
            )
        except ValueError as exc:
            # Half a pattern is not an empty log. The previous filter stays
            # applied and the user is told why, rather than watching the view
            # empty itself as they type.
            self.banner.show_message(str(exc), "Dismiss")
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
        elif self._capture_thread is not None:
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
            )
            self._showing_filter_notice = True
            return
        if self._showing_filter_notice:
            self.banner.hide()
            self._showing_filter_notice = False
        if self.capture is not None and self.model.retained == 0:
            # An empty capture is a fact about the capture, not about the
            # filter and not about the device. Saying nothing here leaves the
            # reader to work out which of the three they are looking at.
            self.banner.show_message(
                "This capture contains no records.",
                "Open another…",
                on_action=self.choose_capture,
            )
