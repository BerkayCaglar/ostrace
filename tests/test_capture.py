# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The capture loop, driven by a recorded session standing in for a device.

This is the substitutability the `sources/` boundary was built for, cashed in:
a real capture from an iPhone goes in through `ReplaySource`, a real session
file comes out, and none of it needs hardware. If `capture()` ever grows a
dependency on something only a live source provides, this file stops compiling.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING, Any

import pytest

from ostrace.capture import capture
from ostrace.sources.base import SourceCloseMixin
from ostrace.sources.replay import ReplaySource
from ostrace.storage.session import SessionReader
from tests.helpers import ScriptedSource, make_gap, make_record

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from ostrace.model import DeviceInfo, Gap, Record


def run(*args: Any, **kwargs: Any) -> Any:
    return asyncio.run(capture(*args, **kwargs))


class TestAgainstARealCapture:
    def test_a_recorded_session_captures_like_a_device(
        self,
        mixed_fixture: Path,
        tmp_path: Path,
    ) -> None:
        result = run(ReplaySource(mixed_fixture), destination=tmp_path / "out")

        assert result.records == 5000
        assert result.gaps == 0
        assert result.path.name == "out.ostrace"

        reader = SessionReader(result.path)
        assert len(list(reader.records())) == 5000
        assert reader.truncated is False, "a finished capture is closed properly"

    def test_the_records_survive_the_round_trip_unchanged(
        self,
        mixed_fixture: Path,
        tmp_path: Path,
    ) -> None:
        async def original() -> list[Record]:
            return [r async for r in ReplaySource(mixed_fixture).records()]

        before = asyncio.run(original())[:200]
        result = run(ReplaySource(mixed_fixture), destination=tmp_path / "out", max_records=200)
        after = list(SessionReader(result.path).records())
        assert after == before


class TestStopping:
    def test_max_records_stops_early_and_says_so(self, tmp_path: Path) -> None:
        source = ScriptedSource([make_record(i) for i in range(100)])
        result = run(source, destination=tmp_path / "out", max_records=10)

        assert result.records == 10
        assert result.stopped_early is True

    def test_a_duration_limit_fires_on_a_timer_not_on_arrival(self, tmp_path: Path) -> None:
        """The distinction that matters on a quiet device.

        A limit checked only when the next record shows up is not a limit --
        this device produces one record every 50 ms and would take five seconds
        to hit a record-count limit.
        """
        source = ScriptedSource([make_record(i) for i in range(100)], delay=0.05)
        result = run(source, destination=tmp_path / "out", duration=0.2)

        assert result.stopped_early is True
        assert result.records < 100
        assert result.duration_seconds < 3.0

    def test_a_duration_limit_survives_a_source_that_never_yields(self, tmp_path: Path) -> None:
        """`stream()` is documented as able to block indefinitely. A capture
        with a time limit must still end."""

        class Silent(SourceCloseMixin):
            name = "silent"

            async def device_info(self) -> DeviceInfo:
                return await ScriptedSource([]).device_info()

            async def stream(self) -> AsyncGenerator[Record | Gap, None]:
                await asyncio.sleep(3600)
                yield make_record(0)  # pragma: no cover - never reached

            async def aclose(self) -> None:
                return

        result = run(Silent(), destination=tmp_path / "out", duration=0.1)
        assert result.records == 0
        assert result.stopped_early is True

    def test_the_source_is_closed_on_every_path(self, tmp_path: Path) -> None:
        source = ScriptedSource([make_record(i) for i in range(10)])
        run(source, destination=tmp_path / "out", max_records=2)
        assert source.closed is True

    def test_the_session_is_finalised_even_when_the_source_raises(
        self,
        tmp_path: Path,
    ) -> None:
        class Exploding(ScriptedSource):
            async def stream(self) -> AsyncGenerator[Record | Gap, None]:
                yield make_record(0)
                msg = "boom"
                raise RuntimeError(msg)

        source = Exploding([])
        with pytest.raises(RuntimeError, match="boom"):
            run(source, destination=tmp_path / "out")

        reader = SessionReader(tmp_path / "out.ostrace")
        assert reader.meta is not None
        assert reader.meta.ended_at is not None, "an aborted capture is still closed"
        assert reader.truncated is False


class TestMetadata:
    def test_the_sidecar_records_what_produced_it(self, tmp_path: Path) -> None:
        source = ScriptedSource([make_record(0)])
        result = run(source, destination=tmp_path / "out")

        meta = SessionReader(result.path).meta
        assert meta is not None
        assert meta.source == "scripted"
        assert meta.device.product_type == "iPhone18,2"
        assert meta.record_count == 1
        assert meta.started_at.utcoffset() == dt.timedelta(hours=3)
        assert meta.ended_at is not None

    def test_gaps_are_recorded_and_counted_separately(self, tmp_path: Path) -> None:
        source = ScriptedSource([make_record(0), make_gap(), make_record(1)])
        result = run(source, destination=tmp_path / "out")

        assert (result.records, result.gaps) == (2, 1)
        assert SessionReader(result.path).meta.gap_count == 1  # type: ignore[union-attr]
        assert len(list(SessionReader(result.path).gaps())) == 1

    def test_the_default_destination_is_named_after_the_device(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OSTRACE_HOME", str(tmp_path))
        result = run(ScriptedSource([make_record(0)]))

        assert result.path.parent == tmp_path / "sessions"
        assert result.path.name.startswith("Test-iPhone-")
        assert result.path.suffix == ".ostrace"

    def test_progress_is_reported_at_the_end_even_below_the_interval(
        self,
        tmp_path: Path,
    ) -> None:
        seen: list[tuple[int, int]] = []
        run(
            ScriptedSource([make_record(0)]),
            destination=tmp_path / "out",
            on_progress=lambda records, gaps: seen.append((records, gaps)),
        )
        assert seen[-1] == (1, 0)
