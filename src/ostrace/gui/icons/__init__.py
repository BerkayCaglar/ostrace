# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The toolbar's icons, tinted from the theme rather than baked.

The set in ``icons/`` is original, drawn to the convention every current icon
library shares -- a 24-unit grid, a 2-unit stroke, round caps and joins -- so
that it sits comfortably beside the platform's own chrome. Eight files, 1.8 kB
in total, which is why they are shipped as files rather than pulled from a
dependency: an icon library would be a runtime dependency and a licence
obligation for less than two kilobytes of geometry.

Two things rule out the alternatives:

* ``QStyle.StandardPixmap`` is free and wrong. Fusion synthesises those as
  *pixmaps*, not masks, so they cannot be recoloured -- the dark scheme would
  draw light-scheme glyphs -- and it has about five of the eight shapes needed.
* A ``QIcon`` built straight from an SVG file does not recolour either. The
  stroke is written as ``currentColor``, and the colour is substituted in the
  markup before the renderer ever sees it, which is the only place a
  substitution can happen without a custom icon engine.

Rendered at the device pixel ratio and cached by everything that can change it,
because a pixmap built for one density and asked for another is blurry in
exactly the way that reads as a cheap application.
"""

from __future__ import annotations

import functools
from importlib import resources

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ostrace.gui.theme import Scheme, token

__all__ = ["ICON_SIZE", "icon", "icon_names"]

#: Toolbar icons, in logical pixels. Sixteen against a 26-pixel button leaves
#: the glyph room to be a glyph rather than a filled square.
ICON_SIZE = 16

_PACKAGE = __name__

#: Substituted in the markup. SVG's own ``currentColor`` resolves against a CSS
#: cascade that ``QSvgRenderer`` does not have, so left alone it renders black
#: in both schemes.
_PLACEHOLDER = "currentColor"


@functools.cache
def _source(name: str) -> str:
    """The markup for one icon.

    ``importlib.resources`` rather than a path built from ``__file__``: the
    package is installed from a wheel, and this is the supported way to read a
    file out of one. It is also the reason no build step is involved -- a Qt
    resource file would need ``pyside6-rcc`` run at build time and a generated
    module kept in step with the directory.
    """
    return resources.files(_PACKAGE).joinpath(f"{name}.svg").read_text(encoding="utf-8")


def icon_names() -> list[str]:
    """Every icon that ships, by name."""
    return sorted(
        entry.name.removesuffix(".svg")
        for entry in resources.files(_PACKAGE).iterdir()
        if entry.name.endswith(".svg")
    )


@functools.lru_cache(maxsize=256)
def _pixmap(name: str, colour: str, size: int, ratio: float) -> QPixmap:
    renderer = QSvgRenderer(_source(name).replace(_PLACEHOLDER, colour).encode("utf-8"))
    pixmap = QPixmap(QSize(int(size * ratio), int(size * ratio)))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    # `end()` explicitly: a QPainter still active when its device is destroyed
    # warns on every platform and leaves the pixmap half drawn on some.
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def icon(
    name: str,
    scheme: Scheme,
    *,
    role: str = "text-secondary",
    size: int = ICON_SIZE,
    ratio: float = 1.0,
) -> QIcon:
    """One icon, in this scheme's colour for ``role``.

    ``role`` is a token name, so an icon cannot end up a colour the contrast
    tests have never seen. The disabled state is built here rather than left to
    Qt, which fades a pixmap by compositing it against the *window* colour --
    correct on a toolbar and wrong anywhere else, and unrecognisable in the dark
    scheme.
    """
    built = QIcon()
    built.addPixmap(_pixmap(name, token(role, scheme).name(), size, ratio), QIcon.Mode.Normal)
    built.addPixmap(
        _pixmap(name, token("text-primary", scheme).name(), size, ratio), QIcon.Mode.Active
    )
    built.addPixmap(
        _pixmap(name, token("text-disabled", scheme).name(), size, ratio), QIcon.Mode.Disabled
    )
    return built


def clear_cache() -> None:
    """Drop the rendered pixmaps.

    Only the pixmaps: the markup does not change. Worth having because the cache
    is keyed by colour and density, and a long session that switches theme twice
    would otherwise hold three sets it will never ask for again.
    """
    _pixmap.cache_clear()
