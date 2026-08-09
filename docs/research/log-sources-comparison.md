# Log sources on iOS: `os_trace_relay` versus `syslog_relay`

**Date:** 2026-08-08
**Device:** `iPhone18,2`, iOS 26.5.2, USB, UDID redacted
**Host:** Windows 11, Python 3.13, `pymobiledevice3` 10.3.1
**Feeds:** [ADR 0002](../adr/0002-use-pymobiledevice3-over-libimobiledevice-cli.md)

Everything below was measured on the device named above, not taken from
documentation. Where a number is quoted, it came out of a probe script that ran
against that device.

---

## The two services

iOS exposes two lockdown services that carry log data.

**`com.apple.syslog_relay`** is the legacy path. It streams lines of text. It is
what `idevicesyslog` from libimobiledevice uses, and it is what the predecessor
tool consumed. There is no structure in the stream — a client can only parse the
text back into fields, and there are fields that were never in the text to begin
with.

**`com.apple.os_trace_relay`** is the modern path, and the one Console.app uses.
It carries the unified logging record itself: level, subsystem, category, thread
id, process image path, the emitting library, and a microsecond timestamp.

## Finding 1: the legacy path delivers about a quarter of the log

A 20-second capture over `os_trace_relay` on an otherwise idle device:

| Level | Records | Share |
| --- | ---: | ---: |
| DEBUG | 3,198 | 62.2% |
| INFO | 1,264 | 24.6% |
| NOTICE | 604 | 11.8% |
| ERROR | 74 | 1.4% |
| **Total** | **5,140** | |

The `syslog_relay` path, measured separately, produced roughly 900–1,200 lines
per second of almost entirely NOTICE-level output.

The two numbers describe the same device over the same period. The conclusion is
that the legacy path is not a slower or lossier version of the modern one — it is
a different tier of the log. The 87% of records at DEBUG and INFO never appear on
it at all, and those are exactly the levels an application developer emits when
instrumenting their own code.

This alone justified the rewrite. Everything else is a bonus.

## Finding 2: 96.8% of records carry a subsystem and category

Of the same 5,140 records, 4,976 had a non-null `label`, giving both a
`subsystem` and a `category`.

A single record, printed field by field:

```
timestamp : 2026-08-08 01:10:31.696620      (microsecond precision)
level     : NOTICE
pid       : 70              thread_id : 13570622
subsystem : com.apple.CoreBrightness.ColourSensorFilterPlugin
category  : default
image_name: /System/Library/HIDPlugins/ColourSensorFilterPlugin.plugin/...
filename  : /usr/libexec/backboardd
message   : [ALS] ts=861562.666 lux=3.830<private> ...
```

Note `image_name` and `filename` differ: the record was emitted by a plugin
loaded into `backboardd`. The text path collapses that to `backboardd[70]` and
the plugin's identity is gone.

The practical consequence is a query that becomes possible: every networking
record from every process, in one search, by filtering on
`subsystem` rather than guessing at process names.

## Finding 3: no tunnel and no elevation are required

The concern worth checking was that iOS 17 moved developer services behind
RemoteXPC, which needs a tunnel and, on most hosts, administrator privileges.
That is true of several services. It is **not** true of `os_trace_relay`.

Verified end to end on iOS 26.5.2:

1. `pymobiledevice3.usbmux.list_devices()` — device enumerated over plain
   usbmux, ordinary user account.
2. `create_using_usbmux()` — lockdown session established, `product_version`
   read back correctly.
3. `OsTraceService(lockdown=lockdown).syslog()` — records streamed immediately.

No `remote tunneld`, no elevated process, no developer disk image.

On Windows the one prerequisite is Apple Mobile Device Service, which provides
the usbmux endpoint on TCP `127.0.0.1:27015`. It ships with iTunes **from
apple.com**; the Microsoft Store build does not install it. Under a silent
`winget` install, `AppleMobileDeviceSupport64.msi` is skipped — it has to be
extracted from `iTunes64Setup.exe` and installed directly. This is the single
most common reason no device appears, and it is documented in
[troubleshooting](../troubleshooting.md).

## Finding 4: pure-Python throughput is adequate, with a caveat

`os_trace_relay` costs three awaited reads and roughly fifteen `struct.unpack`
calls per record. On an idle device the measured rate was around 256 records per
second, which is simply the device's own emission rate rather than a ceiling.

The rate has not been benchmarked against a device under sustained load. That
measurement belongs to phase 1. If the parser turns out to be the bottleneck,
there are three levers before anything is rewritten: drop `HISTORICAL` from the
stream flags, filter at the device with `pid=` or `PROCESS_ONLY`, and batch the
reads.

## Two implementation traps

**`pymobiledevice3` 10.x is asyncio-only.** The synchronous API was removed, and
most examples online still show it. Anything written from a tutorial will not
run.

**Never run under `-O` or `PYTHONOPTIMIZE`.** The upstream stream loop is written
as:

```python
assert await self.service.recvall(1) == b"\x02"
```

Optimisation strips `assert` statements *including the `await` inside them*.
The read never happens, the frame protocol desynchronises, and the result is
garbage records rather than an exception. `ostrace/__init__.py` raises at import
time if `sys.flags.optimize` is set, because a silent corruption is worse than a
refusal to start.

**`HISTORICAL` is on by default** in the upstream stream flags, producing a
backlog burst at connect. It stays on.

> **Correction, 0.1.0.** This said the flag was "off by default here and
> exposed as a capture option", on the assumption that a live view wants only
> what arrives next. Measured on the device: with the flag, roughly 1,600
> records a second; without it, 65 a second, in bursts separated by up to forty
> seconds of complete silence. Turning it off starves the stream rather than
> trimming it, and a viewer defaulting to that would look broken. There is no
> capture option, and `DEFAULT_STREAM_FLAGS` keeps it set.

## A methodological note that cost real time

An earlier version of this work concluded that `syslog_relay` returned nothing
at all on iOS 26 and that building a current libimobiledevice was required. That
was wrong. The device had silently dropped off USB — `idevicesyslog` printed
`[connected]` and then went quiet *without* ever printing `[disconnected]`.
Re-running after reseating the cable produced 35,782 lines in 30 seconds.

The rule that came out of it: **when no logs arrive, check `idevice_id -l`
before suspecting the tool.** An empty device list explains far more failures
than a version mismatch does.

A second, more expensive lesson from the same period is recorded in
[ADR 0002](../adr/0002-use-pymobiledevice3-over-libimobiledevice-cli.md): the
old text parser matched 0% of real device output for weeks because its tests
were written against invented sample lines containing a syslog hostname field
that real output does not have. **Parsers are validated against captured device
output, never against hand-written samples.**
