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

    def test_an_exception_with_no_message_still_names_the_class(self) -> None:
        assert "NotPairedError" in translate(fake("NotPairedError")()).message

    def test_our_own_errors_pass_through_unchanged(self) -> None:
        original = DeviceLockedError("locked")
        assert translate(original) is original


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
            name for name, _ in TRANSLATIONS if not isinstance(getattr(upstream, name, None), type)
        ]
        assert missing == [], (
            f"pymobiledevice3 no longer defines {missing}; update _TRANSLATIONS in errors.py"
        )

    def test_translating_a_real_upstream_exception(self) -> None:
        from pymobiledevice3.exceptions import ConnectionTerminatedError

        assert isinstance(translate(ConnectionTerminatedError()), StreamInterruptedError)
