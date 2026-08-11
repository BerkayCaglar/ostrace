# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rules about the shape of the package, checked mechanically.

``CLAUDE.md`` states these and review has enforced them so far, which works
until the change that breaks one is the change nobody reads closely. They are
cheap to check and the cost of finding out late is not: a ``pymobiledevice3``
import in the wrong module is invisible until it is a hard dependency of
something that was supposed to run without a device.
"""

from __future__ import annotations

import re
from pathlib import Path

import ostrace

PACKAGE = Path(ostrace.__file__).parent

#: The two subpackages allowed to speak to the device library at all.
DEVICE_LAYER = {"sources", "devices"}

#: An import statement, not a mention. ``errors.py`` names the library three
#: times in prose, and that is the point of it: it translates the library's
#: exceptions by class name precisely so it never has to import them.
_IMPORTS_IT = re.compile(r"^\s*(?:from|import)\s+pymobiledevice3")


def _modules_importing_it() -> dict[str, list[str]]:
    """Every module under ``src/ostrace`` that imports the device library."""
    found: dict[str, list[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE)
        hits = [
            f"{relative.as_posix()}:{number}"
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
            if _IMPORTS_IT.match(line)
        ]
        if hits:
            found[relative.parts[0]] = found.get(relative.parts[0], []) + hits
    return found


def test_nothing_outside_the_device_layer_imports_pymobiledevice3() -> None:
    """``errors.py`` translates the library's exceptions by class *name* so that
    the dependency stays inside two directories. Everything downstream of
    ``sources`` speaks in this project's own vocabulary, which is what lets the
    whole pipeline be tested against a recorded session on three operating
    systems with no hardware attached.
    """
    offenders = {
        where: hits for where, hits in _modules_importing_it().items() if where not in DEVICE_LAYER
    }
    assert not offenders, f"pymobiledevice3 imported outside {sorted(DEVICE_LAYER)}: {offenders}"


def test_the_search_can_find_an_import_where_one_is_expected() -> None:
    """The control case, and not decoration: a guard that matches nothing passes
    for the same reason a guard that matches nothing wrong does.

    A mistyped pattern, a moved package directory or a rename would leave the
    test above green forever while enforcing nothing at all.
    """
    assert set(_modules_importing_it()) == DEVICE_LAYER
