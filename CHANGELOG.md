# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the version is below 1.0.0, the minor version may carry breaking changes.
Two things are treated as public API from the start and will be versioned as
such: the `Record` model and the on-disk export formats documented in
[docs/formats/](docs/formats/).

## [Unreleased]

### Added

- Repository skeleton: `pyproject.toml` (hatchling + hatch-vcs, src-layout),
  GPL-3.0-or-later licensing, `ruff` + `mypy --strict` + `pytest` configuration.
- CI across Linux, Windows and macOS; the full Python 3.11–3.14 sweep on Linux.
- Release workflow publishing to PyPI via Trusted Publishing (OIDC), so no
  long-lived API token exists.
- Architecture decision records 0001–0006 and the research they rest on, under
  [docs/](docs/).
- A `ostrace` console script and `python -m ostrace`, both of which currently
  only report a version and the fact that nothing is implemented.

- The core: `model.py` (`Record`, `Level`, `DeviceInfo`, `Gap`), `errors.py`,
  `paths.py`, `compat.py`, `devices/discovery.py`, `storage/` (gzip JSON-Lines
  spool plus a metadata sidecar) and `sources/` with the live `os_trace_relay`
  source and an offline replay source.
- Two captures from a physical `iPhone18,2` on iOS 26.5.2, committed as test
  fixtures, so the whole pipeline is exercised in CI on three operating systems
  with no device attached.

### Notes

Three things were measured on hardware during this phase and are worth knowing
because the obvious assumption is wrong in each case.

- **Apple's log levels are not severity-ordered.** `SyslogLogLevel` on iOS 26 is
  `NOTICE=0, INFO=1, DEBUG=2, USER_ACTION=3, ERROR=16, FAULT=17`, so a filter
  written against those numbers matches everything. `Level` is our own ordered
  enum for that reason before any portability one.
- **Turning off the `HISTORICAL` stream flag starves the stream rather than
  trimming it.** The same device delivered roughly 1,600 records a second with
  it and 65 a second without, in bursts separated by up to forty seconds of
  silence. It stays on by default.
- **A quiet device can produce nothing for tens of seconds.** Any timeout has to
  come from a separate task; waiting for the next record in order to notice that
  time has passed is a hang, not a timeout.

### Added (phase 3a)

- `ostrace doctor` — diagnoses why a device cannot be reached, in dependency
  order, and stops reporting downstream failures once an upstream one is found.
  Almost every problem in this domain is environmental rather than logical, and
  that deserves a command rather than a paragraph in a README.
- `ostrace devices` — lists what is attached, `--verbose` to read identity.
- `ostrace capture` — streams a device log to a session file. `--duration`,
  `--max-records` and Ctrl-C all stop it cleanly, and the sidecar is finalised
  on every exit path including an exception.
- `ostrace.capture.capture()`, separate from the CLI because a GUI stop button
  has the same obligations as Ctrl-C.

`export` is declared but not implemented; it needs the exporters from phase 2.

The capture loop takes a `LogSource`, so a recorded session stands in for a
device: the end-to-end tests run a real iPhone capture through the CLI and
assert on the session file that comes out, with no hardware.

`--duration` is enforced with `asyncio.timeout`, which fires from a timer
rather than from record arrival. On a device that can go silent for tens of
seconds, a limit checked only when the next record shows up is not a limit.

### Fixed

A correctness review of phases 0 and 1 found twelve defects, all fixed before
anything depends on them:

- `aclose()` could not close the streaming session. Reading device identity
  opened a second lockdown and, on releasing it, deregistered the first — so
  every start/stop cycle leaked a socket, which is the one thing `aclose()`
  exists to prevent. It also doubled the most expensive operation at capture
  start.
- Every session closed through its context manager recorded `ended_at: null`,
  making a finished capture indistinguishable from a killed one.
- A record with no process path was named after the *first* such pid seen,
  because the pid-dependent fallback was cached against the path. The kernel
  arrives this way.
- Mid-stream outages were matched by exception type while connect-time outages
  asked `recoverable`, so a recoverable outage arriving as a different class
  ended the capture instead of reconnecting.
- Gap start came from the device clock and gap end from the host's, making the
  duration wrong by the clock skew and negative when the device ran ahead.
- `truncated` answered `False` until a full pass completed — including for the
  natural case of asking before reading.
- A non-numeric clock value from lockdown escaped as a bare `ValueError`.
- The device timezone was read once and reused across reconnects.

Plus a dead attribute, a redundant dictionary copy, a counter that
double-counted across passes, and a mixin whose default teardown silently did
nothing.

Test coverage of the live source went from 22% to 80%: the reconnect loop, gap
bookkeeping and session lifecycle are now driven in CI against stubbed device
seams, with no hardware.

### Changed

A review pass over phases 0 and 1 tightened several things before they had
callers to break:

- Naming a capture is one decision and now lives entirely in `paths.py`. It was
  split, and the halves cancelled out: the suffix was applied with
  `Path.with_suffix`, which *replaces* the last dotted component, so a device
  called `iPhone 15.1` produced `iPhone-15.ostrace` and lost the timestamp that
  makes the name unique.
- Errors declare whether they are `recoverable`, and the reconnect loop asks
  them instead of enumerating types. A device that was never trusted used to be
  retried thirty times before its hint appeared, with a fabricated gap written
  into the session file for an outage that never happened.
- Every source is an async context manager, declared on the protocol. Only one
  of the two implemented it, so the teardown pattern the tests establish would
  have failed the first time it met a replay fixture.
- The `-O` guard moved from package import to `OsTraceSource`. It is a
  constraint of one library, and offline replay was being blocked by it.
- `DeviceInfo` carries its platform rather than the label hardcoding "iOS", and
  `Record.platform` is required rather than defaulted.
- Reading device identity uses the value dictionary the lockdown client already
  holds: one round trip became none, where it used to be seven before the first
  record could arrive.
- Deriving a process name from its path is cached, and `Record.image` no longer
  builds a `PurePosixPath` per access — together about 40% of the measured
  per-record ingest cost, and it takes `pathlib` off `model.py`'s import path.
- Scanning a capture for gaps no longer decodes every record on the way past.
- Dropped from `compat.py`: the subprocess helpers, which supported an
  architecture ADR 0002 rejected, and the platform constants, which the module's
  own rules left with no legal caller.

[Unreleased]: https://github.com/BerkayCaglar/ostrace/commits/main
