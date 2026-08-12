# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where things live on disk.

Every path the package writes to comes from here. No module builds one from a
literal, and nothing assumes a layout: the predecessor tool hardcoded
``C:\\msys64\\...`` and that single habit was the largest obstacle to running it
anywhere else.

"Where a session lives" is one decision, so this module owns all of it -- the
directory, the sanitised name, the suffix and the length budget. Splitting it
is actively harmful: applying the suffix elsewhere with ``Path.with_suffix``
*replaces* the last dotted component, so a device called ``iPhone 15.1`` yields
``iPhone-15.ostrace`` and loses the timestamp that makes the name unique --
after which two captures land in the same directory.

One macOS trap is worth stating because it is invisible from Windows: there the
config directory and the data directory are the same path, both
``~/Library/Application Support/ostrace``. Code that writes a config file and a
data file with the same name into "different" directories overwrites itself
there and nowhere else.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from platformdirs import PlatformDirs

from ostrace.errors import DestinationInUseError

__all__ = [
    "SESSION_SUFFIX",
    "cache_dir",
    "check_export_destination",
    "config_dir",
    "data_dir",
    "export_path",
    "export_stem",
    "log_dir",
    "session_name",
    "session_path",
    "sessions_dir",
    "with_session_suffix",
]

_APP = "ostrace"

#: Set to redirect every path below, for tests and for portable installs.
_ENV_OVERRIDE = "OSTRACE_HOME"

#: Directory extension for a capture.
SESSION_SUFFIX = ".ostrace"

_dirs = PlatformDirs(appname=_APP, appauthor=False, roaming=False)


def _resolve(subdirectory: str | None, default: str) -> Path:
    """One override rule for every directory, so they cannot drift apart."""
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        base = Path(override).expanduser()
        return base / subdirectory if subdirectory else base
    return Path(default)


def data_dir() -> Path:
    """Captured sessions and anything else worth keeping."""
    return _resolve(None, _dirs.user_data_dir)


def config_dir() -> Path:
    """User settings.

    On macOS this is the same directory as :func:`data_dir`. That is correct
    for the platform, not an oversight -- see the module docstring.
    """
    return _resolve("config", _dirs.user_config_dir)


def cache_dir() -> Path:
    """Regenerable data. Safe to delete at any time."""
    return _resolve("cache", _dirs.user_cache_dir)


def log_dir() -> Path:
    """ostrace's own diagnostics -- not device logs."""
    return _resolve("logs", _dirs.user_log_dir)


def sessions_dir(*, create: bool = False) -> Path:
    """Where captures are written."""
    path = data_dir() / "sessions"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


# Windows forbids these outright; the others are merely a bad idea in a shell.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TRAILING = " ."
_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)
_MAX_STEM = 96


def session_name(device_name: str, stamp: str) -> str:
    """Build a filesystem-safe session directory name, without the suffix.

    The device name is chosen by the user and routinely contains an apostrophe
    (``Berkay's iPhone``), a colon, or an emoji. The timestamp is always
    appended and is always safe, so a name that sanitises down to nothing still
    produces a usable, unique result.
    """
    cleaned = _UNSAFE.sub("-", device_name).strip(_TRAILING)
    cleaned = re.sub(r"[-\s]+", "-", cleaned).strip("-")

    if cleaned.split(".")[0].upper() in _RESERVED:
        cleaned = f"_{cleaned}"
    if len(cleaned) > _MAX_STEM:
        cleaned = cleaned[:_MAX_STEM].rstrip("-")
    if not cleaned:
        cleaned = "device"

    return f"{cleaned}-{stamp}"


def session_path(device_name: str, stamp: str, *, root: Path | None = None) -> Path:
    """Full path of a new capture directory.

    The suffix is *appended*, never applied with ``Path.with_suffix`` -- see
    the module docstring for what that cost.
    """
    base = root if root is not None else sessions_dir()
    return base / f"{session_name(device_name, stamp)}{SESSION_SUFFIX}"


def with_session_suffix(path: Path) -> Path:
    """Ensure a caller-supplied path carries the session suffix."""
    return path if path.suffix == SESSION_SUFFIX else path.with_name(path.name + SESSION_SUFFIX)


#: Endings a capture can arrive with, longest first so that ``.jsonl.gz`` is not
#: mistaken for ``.gz`` and left as ``…jsonl``.
_CAPTURE_ENDINGS = (SESSION_SUFFIX, ".jsonl.gz", ".jsonl", ".gz")


def export_stem(session: Path) -> str:
    """The capture's name with whatever marks it as a capture removed.

    ``Berkay-iPhone-20260808-135325.ostrace`` and a bare
    ``ios26-mixed.jsonl.gz`` both reduce to something an export can be named
    after. Done by suffix list rather than ``Path.stem``, which would take
    ``ios26-mixed.jsonl.gz`` down to ``ios26-mixed.jsonl``.
    """
    name = session.name
    for ending in _CAPTURE_ENDINGS:
        if name.endswith(ending):
            return name[: -len(ending)]
    return name


def export_path(session: Path, suffix: str, *, root: Path | None = None) -> Path:
    """Where an export of ``session`` goes when the caller did not say.

    Beside the capture, named after it. An export that lands in a directory
    the user has to go looking for gets regenerated rather than found.

    ``suffix`` belongs to the format -- ``-bundle`` for a directory, ``.md``
    for a document -- because what an export is called is a property of the
    format. Where it goes is this module's decision, which is why the two are
    combined here and nowhere else.
    """
    base = root if root is not None else session.parent
    return base / f"{export_stem(session)}{suffix}"


def check_export_destination(destination: Path, session: Path) -> None:
    """Refuse an export that would be written over the capture it is reading.

    Not a hypothetical. ``.jsonl`` is both a capture ending this module strips
    and the jsonl exporter's suffix, so ``ostrace export capture.jsonl -f
    jsonl`` computed its default destination as the input path. The exporter
    opened it for writing while the reader was still a lazy iterator over it:
    a 2.2 MB capture became zero bytes, the command reported ``0 records`` and
    exited successfully. An explicit ``--output`` at the same path did the same.

    Compared after ``resolve()`` so that a relative path, a symlink and a
    different spelling of the same file are one file, and case-folded because
    two spellings of one name on Windows are also one file.
    """
    try:
        same = os.path.normcase(destination.resolve()) == os.path.normcase(session.resolve())
    except OSError:  # pragma: no cover - an unresolvable path is not this check's problem
        return
    if not same:
        return
    msg = f"the export would be written over the capture it reads, {session.name}"
    raise DestinationInUseError(msg)
