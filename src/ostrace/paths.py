# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where things live on disk.

Every path the package writes to comes from here. No module builds one from a
literal, and nothing assumes a layout: the predecessor tool hardcoded
``C:\\msys64\\...`` and that single habit was the largest obstacle to running it
anywhere else.

"Where a session lives" is one decision, so this module owns all of it -- the
directory, the sanitised name, the suffix and the length budget. Splitting it
was actively harmful: the suffix used to be applied elsewhere with
``Path.with_suffix``, which *replaces* the last dotted component, so a device
called ``iPhone 15.1`` produced ``iPhone-15.ostrace`` and lost the timestamp
that makes the name unique. Two captures then landed in the same directory.

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

__all__ = [
    "SESSION_SUFFIX",
    "cache_dir",
    "config_dir",
    "data_dir",
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
