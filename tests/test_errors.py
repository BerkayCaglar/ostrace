# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""Error translation.

The point of translating by class *name* rather than by importing the upstream
classes is that a rename upstream degrades to a generic error instead of an
ImportError at start-up. The trade-off is that a rename goes unnoticed, so
:class:`TestUpstreamNamesStillExist` closes that loop.
"""

from __future__ import annotations

import pytest

from ostrace.errors import _TRANSLATIONS as TRANSLATIONS
from ostrace.errors import (
    DeviceError,
    DeviceLockedError,
    DeviceNotPairedError,
    NoDeviceFoundError,
    OstraceError,
    SourceUnavailableError,
    StreamInterruptedError,
    UsbmuxUnavailableError,
    translate,
)
from ostrace.errors import _Translation as Translation


def fake(name: str, base: type[Exception] = Exception) -> type[Exception]:
    """An exception class with a given name, standing in for an upstream one."""
    return type(name, (base,), {})


class TestTranslate:
    @pytest.mark.parametrize(
        ("upstream", "expected"),
        [
            ("ConnectionFailedToUsbmuxdError", UsbmuxUnavailableError),
            ("NotPairedError", DeviceNotPairedError),
            ("InvalidHostIDError", DeviceNotPairedError),
            ("PasswordRequiredError", DeviceLockedError),
            ("NoDeviceConnectedError", NoDeviceFoundError),
            ("ConnectionTerminatedError", StreamInterruptedError),
            ("InvalidServiceError", SourceUnavailableError),
            ("MuxException", UsbmuxUnavailableError),
        ],
    )
    def test_known_exceptions_map(self, upstream: str, expected: type[OstraceError]) -> None:
        assert isinstance(translate(fake(upstream)("boom")), expected)

    def test_the_most_specific_match_wins(self) -> None:
        """The upstream hierarchy overlaps: ConnectionFailedToUsbmuxdError is
        also a ConnectionFailedError is also a MuxException. Only the first of
        those tells a user that Apple Mobile Device Service is not running."""
        mux = fake("MuxException")
        failed = fake("ConnectionFailedError", mux)
        specific = fake("ConnectionFailedToUsbmuxdError", failed)

        result = translate(specific("nope"))
        assert type(result) is UsbmuxUnavailableError

    def test_a_subclass_we_do_not_know_still_maps_via_its_base(self) -> None:
        terminated = fake("ConnectionTerminatedError")
        exotic = fake("SomeNewTerminationError", terminated)
        assert isinstance(translate(exotic("x")), StreamInterruptedError)

    def test_an_unknown_exception_becomes_a_generic_error_naming_itself(self) -> None:
        result = translate(fake("CompletelyNovelError")("details here"))
        assert type(result) is DeviceError
        assert "CompletelyNovelError" in result.message
        assert "details here" in result.message
        assert "report it" in result.hint

    def test_an_upstream_message_is_passed_through_when_there_is_one(self) -> None:
        assert translate(fake("NotPairedError")("device said no")).message == "device said no"

    def test_our_own_errors_pass_through_unchanged(self) -> None:
        original = DeviceLockedError("locked")
        assert translate(original) is original


class TestMessagelessUpstreamExceptions:
    """Several upstream exceptions are raised with no message at all.

    The fallback used to be the upstream *class name*, which was fine in a
    traceback and wrong everywhere else it went. A cable pulled mid-capture
    wrote `(ConnectionTerminatedError)` into the gap row -- the one row in a
    log whose entire job is to explain itself to whoever reads it -- and from
    there into all six export formats and both viewer panes.
    """

    def test_the_reported_case_reads_as_a_sentence(self) -> None:
        message = translate(fake("ConnectionTerminatedError")()).message
        assert message == "the connection to the device was lost"

    @pytest.mark.parametrize("entry", TRANSLATIONS, ids=lambda entry: entry.upstream)
    def test_every_entry_falls_back_to_its_own_sentence(self, entry: Translation) -> None:
        assert translate(fake(entry.upstream)()).message == entry.fallback

    @pytest.mark.parametrize("entry", TRANSLATIONS, ids=lambda entry: entry.upstream)
    def test_no_sentence_is_jargon(self, entry: Translation) -> None:
        """What separates a sentence from a class name, mechanically.

        Naming the class is still right in one place -- the unrecognised case
        at the end of `translate`, where it is the only specific thing left to
        say -- and this is deliberately not that.
        """
        assert "Error" not in entry.fallback
        assert "Exception" not in entry.fallback
        assert entry.fallback[0].islower(), "reads mid-sentence"
        assert not entry.fallback.endswith("."), "gap rows put it in parentheses"

    def test_the_sentences_are_not_all_the_same_one(self) -> None:
        """A shared sentence per error class would be easier and worth less.

        Four entries land on DeviceNotPairedError alone, and how you got there
        -- never trusted, or trusted by a host record the device has since
        forgotten -- is the difference between two different remedies.
        """
        sentences = [entry.fallback for entry in TRANSLATIONS]
        assert len(set(sentences)) == len(sentences)


class TestHints:
    def test_the_hint_is_part_of_the_string(self) -> None:
        """`print(exc)` is what a user sees, so the remedy has to be in it."""
        text = str(NoDeviceFoundError("no device found"))
        assert "no device found" in text
        assert "charge-only cables" in text

    def test_a_hint_can_be_overridden_per_instance(self) -> None:
        error = NoDeviceFoundError("gone", hint="specific advice")
        assert str(error) == "gone\n  specific advice"

    def test_an_error_without_a_hint_is_just_its_message(self) -> None:
        assert str(OstraceError("plain")) == "plain"

    def test_the_usbmux_hint_leads_with_the_windows_case(self) -> None:
        """Overwhelmingly the most common cause, so it goes first."""
        assert "Apple Mobile Device Service" in UsbmuxUnavailableError("x").hint


class TestRecoverability:
    """Whether waiting helps is the error's own business.

    Before this existed, the reconnect loop retried *every* error at connect
    time -- including a device that was never trusted, which no amount of
    waiting fixes. The user sat through thirty silent retries before seeing the
    one sentence that would have solved it, and a false gap was written into
    the session file for an outage that never happened.
    """

    def test_a_dropped_stream_is_recoverable(self) -> None:
        assert StreamInterruptedError("x").recoverable is True

    def test_a_vanished_device_is_recoverable(self) -> None:
        """Usually a cable being knocked mid-capture."""
        assert NoDeviceFoundError("x").recoverable is True

    @pytest.mark.parametrize(
        "error",
        [DeviceNotPairedError, UsbmuxUnavailableError, DeviceLockedError, SourceUnavailableError],
    )
    def test_errors_needing_a_human_are_not_recoverable(
        self,
        error: type[OstraceError],
    ) -> None:
        assert error("x").recoverable is False

    def test_the_default_is_not_recoverable(self) -> None:
        """Retrying should be opted into, not inherited by accident."""
        assert OstraceError("x").recoverable is False

    def test_translation_preserves_recoverability(self) -> None:
        assert translate(fake("ConnectionTerminatedError")("x")).recoverable is True
        assert translate(fake("NotPairedError")("x")).recoverable is False

    def test_an_unrecognised_error_is_not_retried(self) -> None:
        """An error we cannot classify is surfaced, not silently looped on."""
        assert translate(fake("CompletelyNovelError")("x")).recoverable is False


class TestUpstreamNamesStillExist:
    """Every name we dispatch on must still be a real pymobiledevice3 exception.

    This is the test that notices an upstream rename. Without it, name-based
    dispatch would quietly stop matching and every device problem would report
    as "not specifically handled".
    """

    def test_all_translated_names_are_real(self) -> None:
        import pymobiledevice3.exceptions as upstream

        missing = [
            entry.upstream
            for entry in TRANSLATIONS
            if not isinstance(getattr(upstream, entry.upstream, None), type)
        ]
        assert missing == [], (
            f"pymobiledevice3 no longer defines {missing}; update _TRANSLATIONS in errors.py"
        )

    def test_translating_a_real_upstream_exception(self) -> None:
        from pymobiledevice3.exceptions import ConnectionTerminatedError

        assert isinstance(translate(ConnectionTerminatedError()), StreamInterruptedError)

    def test_the_entry_type_still_has_the_fields_we_read(self) -> None:
        """Fails on an upstream rename instead of at 3am during a capture.

        It lived in `test_device_live.py` and was therefore marked `device` by
        that module's `pytestmark`, so CI never ran it -- and it is the only
        guard on a field rename inside the `>=10.3,<11` pin, which is precisely
        what a Dependabot bump would introduce. It reads a dataclass
        definition; no device has ever been involved.
        """
        import dataclasses

        from pymobiledevice3.services.os_trace import SyslogEntry

        fields = {field.name for field in dataclasses.fields(SyslogEntry)}
        required = {
            "pid",
            "timestamp",
            "level",
            "image_name",
            "filename",
            "message",
            "label",
            "thread_id",
        }
        assert required <= fields, f"pymobiledevice3 SyslogEntry lost {required - fields}"

    def test_every_level_the_device_can_emit_is_one_we_map(self) -> None:
        """An unmapped level name silently becomes NOTICE, which would hide
        errors. Same story: marked `device`, never run, and it is an enum."""
        from pymobiledevice3.services.os_trace import SyslogLogLevel

        from ostrace.sources.os_trace import _LEVELS

        assert {member.name for member in SyslogLogLevel} <= set(_LEVELS)
