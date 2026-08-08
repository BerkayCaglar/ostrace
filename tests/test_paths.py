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


class TestSessionPath:
    """The whole path is one decision, so one function makes it.

    It used to be two: this module produced a stem and the storage layer
    applied the suffix with ``Path.with_suffix``, which *replaces* the last
    dotted component. Any device name containing a dot therefore lost its
    timestamp, and the uniqueness guarantee with it.
    """

    def test_the_suffix_is_appended(self, tmp_path: Path) -> None:
        result = paths.session_path("iPhone", "20260808-130000", root=tmp_path)
        assert result.name == "iPhone-20260808-130000.ostrace"
        assert result.parent == tmp_path

    @pytest.mark.parametrize(
        "device_name",
        ["iPhone 15.1", "Test 2.0 phone", "a.b.c.d", "iPhone."],
    )
    def test_a_dot_in_the_device_name_does_not_eat_the_timestamp(
        self,
        device_name: str,
        tmp_path: Path,
    ) -> None:
        result = paths.session_path(device_name, "20260808-130000", root=tmp_path)
        assert result.name.endswith("-20260808-130000.ostrace")

    def test_two_captures_from_one_device_do_not_collide(self, tmp_path: Path) -> None:
        first = paths.session_path("iPhone 15.1", "20260808-130000", root=tmp_path)
        second = paths.session_path("iPhone 15.1", "20260808-130500", root=tmp_path)
        assert first != second

    def test_it_defaults_to_the_sessions_directory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OSTRACE_HOME", str(tmp_path))
        assert paths.session_path("iPhone", "s").parent == paths.sessions_dir()

    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("capture", "capture.ostrace"),
            ("capture.ostrace", "capture.ostrace"),
            ("iPhone 15.1-20260808", "iPhone 15.1-20260808.ostrace"),
        ],
    )
    def test_with_session_suffix_appends_and_never_replaces(
        self,
        given: str,
        expected: str,
        tmp_path: Path,
    ) -> None:
        assert paths.with_session_suffix(tmp_path / given).name == expected


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
