# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which scheme is in force: chosen, followed, or remembered from last time.

Three ways a scheme arrives and one rule that orders them. The operating
system is the **default**, not the authority: once somebody picks a theme the
system stops being consulted, in this session and in every session after it.

Distinct from `gui.theme`, which is the function from a scheme to a palette,
and from `MainWindow.set_scheme`, which moves the colours a window prebuilt for
itself. This decides *which* scheme; those two carry it out. The split is the
one this project has already been bitten by: `gui.app` once listened to the
same system signal under a rule that could not see whether the user had chosen,
so the chrome went dark and the table stayed white — which reads as a broken
dark mode rather than as a preference being honoured. There is one listener
now, and one place that knows about choosing.

Applying the palette to the *application* happens here rather than in the
window: it is application-wide, and doing it in three window methods is how the
two halves came to disagree in the first place.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from ostrace.gui.settings import WindowSettings
from ostrace.gui.theme import Scheme, apply_theme, scheme_for

__all__ = ["ThemePolicy"]


class ThemePolicy(QObject):
    """Decides which colour scheme is in force, and says when it moves."""

    #: The scheme changed. Carries a :class:`~ostrace.gui.theme.Scheme`; the
    #: application palette has already been moved to it, and what is left is
    #: whatever the listener prebuilt for itself.
    scheme_changed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        #: Set once the user picks a theme, after which the system stops being
        #: consulted.
        self._chosen = False

    @property
    def chosen(self) -> bool:
        """Whether the user has overruled the system."""
        return self._chosen

    def restore(self) -> None:
        """Re-apply a theme chosen in an earlier session, if there was one.

        Absent, the window follows the system, which is the right default and
        was the only behaviour. Restoring is not choosing *again* -- it is the
        same choice, still standing -- so it takes the same path and marks the
        same flag.
        """
        stored = WindowSettings().theme
        if stored not in (Scheme.LIGHT.value, Scheme.DARK.value):
            return
        self._chosen = True
        self._apply(Scheme(stored))

    def follow_system(self) -> None:
        """Track the operating system's light/dark setting from now on.

        A bound method rather than a lambda closing over the listener: Qt drops
        a connection whose receiver is a destroyed ``QObject``, and a lambda
        would instead keep it alive for as long as the application and then
        call into a deleted C++ object.
        """
        app = QApplication.instance()
        if not isinstance(app, QApplication):  # pragma: no cover - no app, no signal
            return
        app.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)

    def choose(self, *, dark: bool) -> None:
        """Pick a theme, rather than inheriting one.

        The viewer followed the system and offered no way to disagree with it,
        which is fine until you are the person reading a log at night on a
        machine set to light -- or the reverse. Reported as "there is no dark
        mode", and there was one; there was no way to ask for it.

        Choosing stops the following, and it is remembered.
        """
        self._chosen = True
        scheme = Scheme.DARK if dark else Scheme.LIGHT
        self._apply(scheme)
        WindowSettings().theme = scheme.value

    def _on_system_scheme_changed(self, colour_scheme: Qt.ColorScheme) -> None:
        if self._chosen:
            # The user said which one they wanted. The operating system is the
            # default, not the authority.
            return
        self._apply(scheme_for(colour_scheme))

    def _apply(self, scheme: Scheme) -> None:
        """Move the application, then tell whoever prebuilt colours of its own.

        In that order, and both every time. `apply_theme` moves the palette,
        the tooltips and the chrome stylesheet; it does not reach a severity
        foreground or a minimap band, which are resolved once and held. A
        switch that moved only one of the two is the bug this project already
        found, where the window repainted in the new scheme and every record's
        colour stayed in the old.
        """
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, scheme)
        self.scheme_changed.emit(scheme)
