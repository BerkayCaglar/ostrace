# Troubleshooting

Almost every problem is one of three things: the device is not visible to the
host, the host cannot talk to it, or nothing is being logged. Work through them
in that order — most of the time spent on this during development went into
diagnosing the wrong layer.

---

## Start here: is the device visible at all?

```bash
ostrace devices
```

If that lists nothing, no amount of investigating `ostrace` itself will help.

**This is the first thing to check when logs stop arriving mid-capture, too.**
During development a capture went silent and was diagnosed as an iOS version
incompatibility. It was not: the cable had come loose. The tool had printed
`[connected]` and then simply went quiet, without ever printing
`[disconnected]`. Reseating the cable produced 35,782 lines in thirty seconds.

An empty device list explains far more failures than a version mismatch does.

## No devices listed

### Windows: Apple Mobile Device Service

This is the most common cause on Windows by a wide margin.

Windows has no built-in usbmux. It is provided by **Apple Mobile Device
Service**, which listens on TCP `127.0.0.1:27015`. Without it, nothing can see
an iPhone at all.

Check whether it is running:

```powershell
Get-Service "Apple Mobile Device Service"
```

If the service does not exist, it is not installed. Two traps:

- **The Microsoft Store build of iTunes does not install it.** You need iTunes
  from apple.com.
- **A silent `winget` install skips it.** `AppleMobileDeviceSupport64.msi` is
  bundled inside `iTunes64Setup.exe` and is not run under a silent install.
  Extract the installer (7-Zip opens it) and run that MSI directly; it needs
  elevation.

You do not need iTunes itself — only the Apple Mobile Device Support package.

If the service exists but is stopped:

```powershell
Start-Service "Apple Mobile Device Service"
```

### Every platform: pairing and trust

Unlock the device, connect it over USB, and answer **Trust This Computer**. The
prompt appears only while the device is unlocked, and it is easy to miss and
then dismiss by picking the phone up again.

If trust was previously refused, the device remembers. Reset it on the device
under **Settings → General → Transfer or Reset iPhone → Reset → Reset Location &
Privacy**, then reconnect and answer the prompt.

### Cable and port

Charge-only cables are common and give exactly this symptom: the device charges,
and no data connection exists. Try a different cable and a port directly on the
machine rather than through a hub.

### macOS

`usbmuxd` is part of the OS and needs nothing installed. If a device does not
appear, check that it is trusted, and that no other tool is holding an exclusive
lockdown session.

### Linux

Install `usbmuxd` from your distribution and make sure the service is running.
You will also need a udev rule granting your user access to the device, which
the `usbmuxd` package normally installs. If `ostrace devices` works under `sudo`
but not as your user, it is the udev rule.

## Device is listed, but no logs arrive

**Check the log level.** If the level filter is set to Error, an idle device can
genuinely produce nothing for minutes at a time. Drop it to Debug and confirm
records appear.

**Check the source.** If a session fell back to `syslog_relay`, expect only
NOTICE-level records and no subsystem or category on any of them. That is the
service's limit, not a bug — see
[the source comparison](research/log-sources-comparison.md).

**Do not capture under `-O` or `PYTHONOPTIMIZE`.** The device stream protocol
depends on `assert` statements that optimisation removes, which desynchronises
the frame protocol and produces garbage rather than an error. `ostrace` refuses
to open a device stream when the flag is set; if you see that error, unset the
environment variable rather than working around it. Offline work — replaying a
session, re-exporting a capture — is unaffected and runs fine under `-O`.

## The connection drops during a long capture

Expected, and handled: the capture reconnects and writes a **gap marker** into
the session file recording the interval that was lost. Records emitted during
the gap are unrecoverable — nothing buffers them on the device.

If it happens repeatedly, in likelihood order: the cable, a hub, or the host
suspending USB power. On Windows, check Device Manager → the USB root hub →
Power Management → "Allow the computer to turn off this device to save power".

## Logs contain `<private>`

This is Apple's own redaction, applied by iOS before the data ever leaves the
device. It is not a defect in `ostrace` and there is nothing here that can
reveal it.

For your own application's logs, use non-private format specifiers in your
`os_log` calls, or attach a debugger.

## Everything looks slow

An idle device produces a few hundred records per second; a busy one over a
thousand. If the viewer is struggling well below that, please open an issue with
the record rate shown in the status bar and your OS and Python versions — the
model is designed around specific measured limits, and a report below them is a
bug worth having.

## Still stuck

Open an issue with:

- `ostrace --version` and `ostrace doctor` output
- OS and Python version
- Device model and iOS version
- What you expected and what happened

**Redact before you paste.** A capture can contain account identifiers, file
paths, network endpoints and anything an app decided to log.
