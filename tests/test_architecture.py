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

import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

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


#: The import paths the README's "Using it as a library" table promises. Below
#: 1.0.0 these names may move; what they may not do is move without the README
#: and the changelog moving with them, which is what the tests below are for.
PUBLIC_SURFACE: dict[str, tuple[str, ...]] = {
    "ostrace.model": ("Record", "Gap", "Level", "DeviceInfo", "Platform"),
    "ostrace.storage": ("open_capture", "Capture"),
    "ostrace.sources": ("ReplaySource", "LogSource"),
    "ostrace.capture": ("capture", "CaptureResult"),
    "ostrace.exporters": ("EXPORTERS",),
    "ostrace.exporters.base": ("register",),
    "ostrace.errors": ("OstraceError",),
    "ostrace.sources.os_trace": ("OsTraceSource",),
}

_DOCUMENTED = re.compile(r"from (ostrace[\w.]*) import ([\w, ]+)")


def _promised_by_the_readme() -> set[tuple[str, str]]:
    """Every ``from ostrace... import ...`` the README states, as pairs."""
    text = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    return {
        (module, name.strip())
        for module, names in _DOCUMENTED.findall(text)
        for name in names.split(",")
    }


def _modules_after(imports: list[str]) -> set[str]:
    """What is in ``sys.modules`` after importing ``imports``, in a fresh process.

    A subprocess rather than this one. By the time any test runs, something in
    the suite has imported the device layer, so asking this interpreter what an
    import costs gets the answer "nothing, it was already here".
    """
    program = "\n".join(
        [*(f"import {name}" for name in imports), "import sys", "print(' '.join(sys.modules))"]
    )
    finished = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True
    )
    return set(finished.stdout.split())


@pytest.mark.parametrize(
    ("module", "name"),
    [(module, name) for module, names in PUBLIC_SURFACE.items() for name in names],
)
def test_every_documented_name_is_an_exported_one(module: str, name: str) -> None:
    """A documented name has to be reachable *and* declared.

    ``__all__`` is the difference between a supported name and one that happens
    to be in a module's namespace because something else imported it. The
    second kind disappears when that other import is tidied, and the tidying
    reads as harmless right up until somebody's script stops importing.
    """
    imported = importlib.import_module(module)

    assert hasattr(imported, name), f"{module} no longer defines {name}"
    assert name in imported.__all__, f"{module}.{name} is documented but not in its __all__"


def test_the_readme_documents_exactly_this_surface() -> None:
    """The list above and the table in the README are the same list.

    Two directions, both worth failing on: a name renamed here without the
    README following says the documentation is stale, and a name added to the
    README without arriving here says it is promising something untested.
    """
    assert _promised_by_the_readme() == {
        (module, name) for module, names in PUBLIC_SURFACE.items() for name in names
    }


def test_the_documented_surface_costs_no_device_library_and_no_qt() -> None:
    """Not one documented import loads ``pymobiledevice3``, the device source
    included, and none of them loads Qt.

    ``pymobiledevice3`` is 90 distributions -- measured as the recursive closure
    of its requirements on Windows and Python 3.13 -- and it is reached through
    function-level imports so that it arrives when a service is opened rather
    than when a module is read. That is what the ``noqa: PLC0415`` comments in
    ``sources`` and ``devices`` are buying, and it is invisible enough that a
    tidy-up moving those imports to the top of their files would look like an
    improvement. The same argument is why there is no flat re-export in
    ``__init__.py``: one line there would put the whole device stack behind
    every offline use.
    """
    loaded = _modules_after(sorted(PUBLIC_SURFACE))

    assert "pymobiledevice3" not in loaded
    assert "PySide6" not in loaded


def test_the_import_probe_can_see_a_dependency_that_is_there() -> None:
    """The control for the test above, which would otherwise pass on a typo.

    A subprocess that failed to import anything, or a ``sys.modules`` read that
    returned the wrong shape, produces the same green as a package that is
    genuinely cheap to import.
    """
    loaded = _modules_after(["pymobiledevice3"])

    assert "pymobiledevice3" in loaded
