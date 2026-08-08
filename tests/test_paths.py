# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Path resolution and session naming."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ostrace import paths

if TYPE_CHECKING:
    from pathlib import Path


class TestSessionName:
    @pytest.mark.parametrize(
        ("device_name", "expected"),
        [
            ("iPhone", "iPhone-20260808-130000"),
            # The common real case: apostrophes are legal but awkward, spaces
            # collapse. This device is literally called "Berkay's iPhone".
            ("Berkay's iPhone", "Berkay's-iPhone-20260808-130000"),
            # Windows forbids these outright. A run of them collapses to one
            # separator rather than to a row of dashes.
            ('bad<>:"/\\|?*name', "bad-name-20260808-130000"),
            ("trailing dot.", "trailing-dot-20260808-130000"),
            ("trailing space ", "trailing-space-20260808-130000"),
            ("multiple   spaces", "multiple-spaces-20260808-130000"),
            # Sanitising to nothing must still give a usable name.
            ("///", "device-20260808-130000"),
            ("", "device-20260808-130000"),
            # Reserved DOS device names, still special in 2026.
            ("CON", "_CON-20260808-130000"),
            ("nul.txt", "_nul.txt-20260808-130000"),
            ("COM1", "_COM1-20260808-130000"),
        ],
    )
    def test_sanitising(self, device_name: str, expected: str) -> None:
        assert paths.session_name(device_name, "20260808-130000") == expected

    def test_an_emoji_name_survives_as_a_usable_path(self) -> None:
        """Device names are user-chosen and frequently contain emoji. They are
        legal on every target filesystem, so they are kept rather than stripped."""
        result = paths.session_name("📱 phone", "20260808-130000")
        assert result.endswith("-20260808-130000")
        assert "📱" in result

    def test_a_very_long_name_is_truncated_but_stays_unique(self) -> None:
        result = paths.session_name("x" * 500, "20260808-130000")
        assert len(result) < 130
        assert result.endswith("-20260808-130000")

    def test_control_characters_are_removed(self) -> None:
        assert "\x00" not in paths.session_name("a\x00b\x1fc", "s")
        assert "\x1f" not in paths.session_name("a\x00b\x1fc", "s")


class TestDirectories:
    def test_every_directory_is_absolute(self) -> None:
        for resolver in (paths.data_dir, paths.config_dir, paths.cache_dir, paths.log_dir):
            assert resolver().is_absolute()

    def test_the_home_override_redirects_everything(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OSTRACE_HOME", str(tmp_path))
        assert paths.data_dir() == tmp_path
        assert paths.config_dir() == tmp_path / "config"
        assert paths.cache_dir() == tmp_path / "cache"
        assert paths.log_dir() == tmp_path / "logs"
        assert paths.sessions_dir() == tmp_path / "sessions"

    def test_the_override_expands_a_tilde(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OSTRACE_HOME", "~/ostrace-test")
        assert "~" not in str(paths.data_dir())
        assert paths.data_dir().is_absolute()

    def test_sessions_dir_creates_on_request_only(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OSTRACE_HOME", str(tmp_path / "home"))
        assert not paths.sessions_dir().exists()
        created = paths.sessions_dir(create=True)
        assert created.is_dir()

    def test_no_module_hardcodes_a_windows_path(self) -> None:
        """The predecessor tool hardcoded C:\\msys64 and that single habit was
        the largest obstacle to running it anywhere else."""
        from pathlib import Path as RealPath

        package = RealPath(paths.__file__).parent
        offenders = [
            source.name
            for source in package.rglob("*.py")
            if "C:\\" in source.read_text(encoding="utf-8").replace("C:\\\\msys64", "")
        ]
        assert offenders == []
