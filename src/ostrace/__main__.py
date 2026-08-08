# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Support ``python -m ostrace`` alongside the installed console script."""

from __future__ import annotations

from ostrace.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
