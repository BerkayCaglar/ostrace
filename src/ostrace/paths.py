# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where things live on disk.

Every path the package writes to comes from here. No module builds one from a
literal, and nothing assumes a layout: the predecessor tool hardcoded
``C:\\msys64\\...`` and that single habit was the largest obstacle to running it
anywhere else.

One macOS-specific trap is worth stating because it is invisible from Windows:
on macOS the config directory and the data directory are the same path, both
``~/Library/Application Support/ostrace``. Any code that writes a config file
and a data file with the same name into "different" directories overwrites
itself there and nowhere else.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from platformdirs import PlatformDirs

__all__ = [
    "cache_dir",
    "config_dir",
    "data_dir",
    "log_dir",
    "session_name",
    "sessions_dir",
]

_APP = "ostrace"

#: Set to redirect every path below, for tests and for portable installs.
_ENV_OVERRIDE = "OSTRACE_HOME"

_dirs = PlatformDirs(appname=_APP, appauthor=False, roaming=False)


def _home_override() -> Path | None:
    raw = os.environ.get(_ENV_OVERRIDE)
    return Path(raw).expanduser() if raw else None


def data_dir() -> Path:
    """Captured sessions and anything else worth keeping."""
    override = _home_override()
    return override if override is not None else Path(_dirs.user_data_dir)


def config_dir() -> Path:
    """User settings.

    On macOS this is the same directory as :func:`data_dir`. That is correct
    for the platform, not an oversight -- see the module docstring.
    """
    override = _home_override()
    return override / "config" if override is not None else Path(_dirs.user_config_dir)


def cache_dir() -> Path:
    """Regenerable data. Safe to delete at any time."""
    override = _home_override()
    return override / "cache" if override is not None else Path(_dirs.user_cache_dir)


def log_dir() -> Path:
    """ostrace's own diagnostics -- not device logs."""
    override = _home_override()
    return override / "logs" if override is not None else Path(_dirs.user_log_dir)


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
    """Build a filesystem-safe session directory name.

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
