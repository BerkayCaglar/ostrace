# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 0 smoke tests.

These exist to prove the packaging works, not the program. Because the project
uses a src-layout, importing ``ostrace`` at all means the wheel metadata, the
package discovery and the installed console script are correct -- a packaging
mistake fails here in CI rather than in a user's install.
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

import ostrace
from ostrace.cli import EXIT_NOT_IMPLEMENTED, EXIT_OK, build_parser, main

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """Strip ANSI styling.

    Python 3.14's argparse colourises help output, and CI sets FORCE_COLOR, so
    ``usage: ostrace`` arrives with escape sequences between the two words.
    Assertions are about the text, not how a terminal was asked to paint it.
    """
    return _ANSI.sub("", text)


def test_package_exposes_a_version() -> None:
    assert isinstance(ostrace.__version__, str)
    assert ostrace.__version__


def test_package_is_installed_not_merely_on_the_path() -> None:
    """A src-layout package that resolves from the source tree is a red flag."""
    assert ostrace.__file__ is not None
    assert "site-packages" in ostrace.__file__ or "src" in ostrace.__file__


@pytest.mark.parametrize("command", ["devices", "capture", "doctor", "export"])
def test_parser_accepts_every_subcommand(command: str) -> None:
    assert build_parser().parse_args([command]).command == command


def test_bare_invocation_prints_help_and_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == EXIT_OK
    assert "usage: ostrace" in plain(capsys.readouterr().out)


def test_export_reports_a_distinct_exit_code_until_phase_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["export"]) == EXIT_NOT_IMPLEMENTED
    assert "not implemented" in plain(capsys.readouterr().out)


def test_unknown_subcommand_is_rejected() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["definitely-not-a-subcommand"])
    assert excinfo.value.code == 2


def test_module_entry_point_runs() -> None:
    """`python -m ostrace --version` must work on every supported platform."""
    result = subprocess.run(
        [sys.executable, "-m", "ostrace", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert plain(result.stdout).startswith("ostrace ")
