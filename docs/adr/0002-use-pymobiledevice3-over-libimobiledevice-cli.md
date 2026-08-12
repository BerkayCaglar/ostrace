---
status: accepted
date: 2026-08-08
decision-makers: Berkay ÇAĞLAR
---

# Read logs through pymobiledevice3's os_trace_relay, not the libimobiledevice CLI

## Context and Problem Statement

The predecessor tool shelled out to `idevicesyslog.exe` from a 2021-era MSYS2
build of libimobiledevice and parsed its text output with a regular expression.
Three problems made that untenable.

**It sees roughly a quarter of the log.** `idevicesyslog` uses
`com.apple.syslog_relay`. Measured against `com.apple.os_trace_relay` on the
same device (`iPhone18,2`, iOS 26.5.2, 20-second capture):

| Level | Records | Share |
| --- | ---: | ---: |
| DEBUG | 3,198 | 62.2% |
| INFO | 1,264 | 24.6% |
| NOTICE | 604 | 11.8% |
| ERROR | 74 | 1.4% |

`syslog_relay` delivers the NOTICE tier and above, and nothing below it. The
DEBUG and INFO records, which are the ones that matter when debugging your own
app, never arrive.

That boundary was an inference when this decision was taken and is now measured:
reading both services from one process over the same minute, `syslog_relay`
returned 11,642 entries against 11,479 records at NOTICE and above on
`os_trace_relay` — 1.4% apart, and exactly equal in one of the shorter runs. The
figure this ADR used to give, "about 900–1,200 lines per second", was a line
count from a separate run and does not reconcile with the table above; see
[log-sources-comparison.md](../research/log-sources-comparison.md) Finding 1b.

**Structured metadata exists and is being thrown away.** 96.8% of records carry
a `subsystem` and `category`. `os_trace_relay` also carries `thread_id`, the
process image path, and the emitting library. `syslog_relay` carries none of
it — the transport is a line of text.

**Text parsing is fragile in a way that fails silently.** The regular expression
in the old tool assumed a syslog hostname field between the timestamp and the
process name. Real device output has no such field. The parser matched 0% of
real records for weeks, and the tests did not catch it because they were written
against invented sample lines that contained the invented hostname. Process
colouring, filtering and grouping were all quietly dead.

## Decision Drivers

- Access to DEBUG and INFO, non-negotiable.
- Structured fields rather than a line of text.
- One code path on Windows, macOS and Linux.
- No external toolchain for a user to install.
- Testable without a physical device.

## Considered Options

1. **`pymobiledevice3` as an imported library** (`OsTraceService`).
2. **`pymobiledevice3` as a subprocess**, parsing its CLI output.
3. **Keep libimobiledevice**, upgrading to a current build with `os_trace` support.
4. **Implement the lockdown and `os_trace_relay` protocols directly.**

## Decision Outcome

Chosen option: **`pymobiledevice3` as an imported library**, with the text
parser deleted outright.

> **Correction, 0.1.0.** This originally added "with `syslog_relay` retained as
> a fallback source for devices where `os_trace_relay` is unavailable". No such
> source was built: `sources/` holds `os_trace.py` and `replay.py` and nothing
> else. `os_trace_relay` turned out to be available on every device tested, and
> the fallback would have been a second parser for a tier of data the whole ADR
> argues is not worth having. `errors.SourceUnavailableError` still names the
> case, so a device that genuinely lacks the service says so rather than
> failing obscurely. The claim is corrected here rather than left standing,
> since it sent two other documents on to give advice about a session file that
> cannot exist.

The concern that iOS 17+ moved this behind a RemoteXPC tunnel was checked
empirically rather than assumed: `com.apple.os_trace_relay` is still an ordinary
lockdown service. Plain usbmux, ordinary user account, no tunnel, no elevation,
verified on iOS 26.5.2.

### Consequences

- Good: DEBUG and INFO records arrive; the log is roughly 4× larger and the part
  that was missing is the useful part.
- Good: `subsystem` and `category` become real columns. An agent can run
  `rg '\tcom\.apple\.network\t'` across a capture and get every networking
  record from every process — not expressible at all in the old format.
- Good: the MSYS2 dependency and every hardcoded `C:\msys64\...` path disappear,
  which removes the single largest obstacle to running on macOS.
- Good: pip-installable, so there is nothing for a user to build.
- **Bad: dependency weight.** `pymobiledevice3` pulls **90 distributions** —
  FastAPI, uvicorn, IPython, xonsh, Pillow and `av` (FFmpeg bindings) among them
  — in order to stream logs. There is no lightweight extras group upstream. This
  is documented in the README rather than hidden.

  Ninety is measured, not estimated, and by two methods that agree: the
  recursive closure of the installed metadata's requirements with markers
  evaluated for this environment, and `pip install --dry-run --ignore-installed`
  resolving the same package from scratch. Both say 90 on Windows and Python
  3.13, against the `>=10.3,<11` pin. Neither counts extras nobody installs.

  The weight is real and it is confined: every import of the library sits inside
  the function that needs it, so nothing loads until a service is actually
  opened. `import ostrace` and every documented offline import stay free of it,
  which is asserted in `tests/test_architecture.py` rather than intended.
- **Bad: API churn.** The 10.x line removed the synchronous API that most
  examples online still show; the project releases frequently. Mitigated by
  pinning `>=10.3,<11` and confining every import to `ostrace/sources/`.
- Neutral: the library is asyncio-only, so the GUI needs a dedicated thread
  owning its own event loop. `ServiceConnection` is not thread-safe and is never
  shared.
- Neutral: there is no auto-reconnect, in the library or its CLI. We own that
  loop — catch `ConnectionTerminatedError`, rebuild via
  `retry_create_using_usbmux`, resume, and write a gap marker into the session
  file so exports can state the gap rather than hide it.

### Confirmation

The load-bearing structural consequence is the `ostrace/sources/` boundary:
everything downstream consumes `Record` objects and never learns where they came
from. `sources/replay.py` reads a committed fixture, so the entire pipeline is
testable with no device attached. If `pymobiledevice3` ever has to be replaced,
that replacement is confined to one directory.

## Pros and Cons of the Options

### Subprocess rather than library import

- Good, because it would arguably avoid the GPL combined-work question.
- Bad, because it reintroduces text parsing — the exact failure mode being
  eliminated.
- Bad, because it gives up structured fields, which was the point.

### Keep libimobiledevice

- Good, because it is C and fast.
- Bad, because Windows users need a prebuilt toolchain; the MSYS2 dependency and
  its hardcoded paths are the main thing blocking macOS support.
- Bad, because the shipped 1.3.0 build has no `os_trace` support at all, so this
  means building from source on every platform.

### Implement the protocols directly

- Good, because it would have no dependencies worth mentioning.
- Bad, because lockdown, usbmux, pairing and TLS are a large, undocumented,
  moving target. This is precisely the work `pymobiledevice3` exists to do.

## More Information

- [docs/research/log-sources-comparison.md](../research/log-sources-comparison.md)
  — the raw measurements.
- [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)
- Licence consequence: [ADR 0003](0003-license-gpl-3-0-or-later.md).
