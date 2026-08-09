# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
"""The exception hierarchy.

Every error a user can hit carries a ``hint``: one sentence saying what to do
about it. Most of the pain in this problem domain is environmental rather than
logical -- a service that is not installed, a device that was never trusted, a
cable that only carries power -- and an exception that names the remedy is worth
considerably more than one that names the layer that failed.

Errors also declare whether they are ``recoverable``, so that a retry loop can
ask the error rather than enumerate the types it knows about. Retrying a device
that was never trusted just delays the message that would have fixed it.

``pymobiledevice3`` exceptions are translated at the ``sources`` boundary by
:func:`translate`, so nothing downstream imports the library or has to know its
exception names.
"""

from __future__ import annotations

__all__ = [
    "DeviceError",
    "DeviceLockedError",
    "DeviceNotPairedError",
    "NoDeviceFoundError",
    "OstraceError",
    "SessionCorruptError",
    "SourceError",
    "SourceUnavailableError",
    "StorageError",
    "StreamInterruptedError",
    "UnsupportedFormatVersionError",
    "UsbmuxUnavailableError",
    "translate",
]


class OstraceError(Exception):
    """Base class for everything this package raises deliberately."""

    #: Default remediation, overridden per subclass or per instance.
    hint: str = ""

    #: Whether waiting and trying again could plausibly succeed. Default False:
    #: most of these describe a state only the user can change.
    recoverable: bool = False

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if hint is not None:
            self.hint = hint

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message}\n  {self.hint}"
        return self.message


# --------------------------------------------------------------------------
# Devices
# --------------------------------------------------------------------------


class DeviceError(OstraceError):
    """Something is wrong between this host and the device."""


class NoDeviceFoundError(DeviceError):
    # Recoverable during a capture: a device that vanishes mid-stream is
    # usually a cable being knocked, and waiting for it to come back is what a
    # user wants. It is still fatal on the *first* connect, where there is
    # nothing to resume and the hint is the whole answer.
    recoverable = True

    hint = (
        "Connect the device over USB and unlock it. If it is already connected, "
        "try a different cable -- charge-only cables give exactly this symptom."
    )


class UsbmuxUnavailableError(DeviceError):
    """No usbmux endpoint to talk to at all."""

    # Overwhelmingly the Windows case, so the hint leads with it.
    hint = (
        "On Windows this means Apple Mobile Device Service is not running. It "
        "ships with iTunes from apple.com -- not the Microsoft Store build. "
        "On Linux, install and start usbmuxd. See docs/troubleshooting.md."
    )


class DeviceNotPairedError(DeviceError):
    hint = (
        "Unlock the device and answer 'Trust This Computer'. If the prompt does "
        "not appear, reset it under Settings > General > Transfer or Reset "
        "iPhone > Reset > Reset Location & Privacy."
    )


class DeviceLockedError(DeviceError):
    hint = "Unlock the device and try again."


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------


class SourceError(OstraceError):
    """Something is wrong with the log stream itself."""


class SourceUnavailableError(SourceError):
    # Names the capability rather than a command-line flag: which flag spells it
    # belongs to whoever owns the CLI surface, and this layer is below that.
    hint = (
        "The device did not offer this log service. Very old iOS versions have "
        "only the legacy syslog relay; select that source instead."
    )


class StreamInterruptedError(SourceError):
    """The stream ended mid-capture.

    Recoverable by design: the capture loop reconnects and writes a gap marker.
    It becomes fatal only when reconnection keeps failing.
    """

    recoverable = True

    hint = (
        "The device disconnected. Check the cable and the port, and on Windows "
        "check that USB selective suspend is not powering the port down."
    )


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


class StorageError(OstraceError):
    """Something is wrong with a session file on disk."""


class SessionCorruptError(StorageError):
    hint = (
        "The capture was probably interrupted. Records before the damaged point "
        "are still readable; ostrace reads as far as it can."
    )


class UnsupportedFormatVersionError(StorageError):
    hint = "This session was written by a newer ostrace. Upgrade and try again."


class DestinationInUseError(StorageError):
    """Writing here would destroy something that is already there.

    Its own class rather than a message, because there are two ways to reach
    it -- an export whose default name lands on its own input, and a capture
    reusing a destination -- and both are silent data loss if the write is
    allowed to proceed.
    """

    # Not "pass --output": the export check has two callers now, and the one
    # in the viewer has a field to type in rather than a flag to pass. Raise
    # sites that are only ever reached from the command line say so themselves.
    hint = "Choose a different destination."


# --------------------------------------------------------------------------
# Translation from pymobiledevice3
# --------------------------------------------------------------------------

# Matched most specific first, since the upstream hierarchy overlaps: a
# ConnectionFailedToUsbmuxdError is also a ConnectionFailedError is also a
# MuxException, and only the first of those tells the user anything useful.
_TRANSLATIONS: tuple[tuple[str, type[DeviceError | SourceError]], ...] = (
    ("ConnectionFailedToUsbmuxdError", UsbmuxUnavailableError),
    ("NotPairedError", DeviceNotPairedError),
    ("InvalidHostIDError", DeviceNotPairedError),
    ("FatalPairingError", DeviceNotPairedError),
    ("PairingError", DeviceNotPairedError),
    ("PasswordRequiredError", DeviceLockedError),
    ("NoDeviceConnectedError", NoDeviceFoundError),
    ("DeviceNotFoundError", NoDeviceFoundError),
    ("ConnectionTerminatedError", StreamInterruptedError),
    ("InvalidServiceError", SourceUnavailableError),
    ("MissingValueError", SourceUnavailableError),
    ("ConnectionFailedError", UsbmuxUnavailableError),
    ("MuxException", UsbmuxUnavailableError),
)


def translate(exc: BaseException) -> OstraceError:
    """Map a ``pymobiledevice3`` exception onto ours.

    Matching is by class *name* rather than by importing the upstream classes.
    That keeps this module free of the dependency, and it means a renamed or
    removed upstream exception degrades to a generic error instead of an
    ImportError at start-up -- the library's 10.x line has already removed a
    public API once.
    """
    if isinstance(exc, OstraceError):
        return exc

    names = {klass.__name__ for klass in type(exc).__mro__}
    for upstream, ours in _TRANSLATIONS:
        if upstream in names:
            return ours(str(exc) or upstream)

    detail = str(exc) or type(exc).__name__
    return DeviceError(
        f"{type(exc).__name__}: {detail}",
        hint="This one is not specifically handled; please report it with the traceback.",
    )
