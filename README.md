# ostrace

Stream, inspect and export iOS device logs — on Windows, macOS and Linux.

`ostrace` reads Apple's unified log over `com.apple.os_trace_relay`, the same
service Console.app uses. That means structured records: subsystem, category,
thread id and the emitting library, at DEBUG level and above — not just the
NOTICE-tier text that the legacy `syslog_relay` path returns.

> **Status: early development.** The 0.0.x line is a skeleton. See
> [CHANGELOG.md](CHANGELOG.md) for what is actually implemented, and
> [docs/](docs/) for the design.

---

## Why

Measured on an `iPhone18,2` running iOS 26.5.2, a 20-second capture:

| Level | Records | Share |
| --- | ---: | ---: |
| DEBUG | 3,198 | 62.2% |
| INFO | 1,264 | 24.6% |
| NOTICE | 604 | 11.8% |
| ERROR | 74 | 1.4% |

Tools built on `syslog_relay` — including `idevicesyslog` — deliver
essentially only that NOTICE tier. The DEBUG and INFO records, the ones that
matter when you are debugging your own app, never arrive at all. Separately,
96.8% of records carry a `subsystem` and `category` that the text-based
pipeline discards.

`os_trace_relay` is still an ordinary lockdown service on iOS 26: no RemoteXPC
tunnel, no administrator privileges.

## Planned features

- **Live viewer** — a virtualised table with per-level colouring, filters on
  level, process, subsystem and message, and a detail pane showing every field.
- **Long captures** — records spool to a gzip file on disk, so an hour-long
  capture is bounded by disk, not RAM.
- **Exports built for reading, not just archiving** — Markdown, JSONL, plain
  text, a token-budgeted AI report, and an *agent bundle*: a directory of
  tab-separated files plus a generated `CLAUDE.md`, designed for a coding agent
  to investigate with `grep`/`rg` rather than by loading the whole log.

## Install

```bash
pipx install ostrace
```

`pipx` (or `uv tool install ostrace`) is the recommended route. Files installed
by a package manager are never quarantined by macOS, so Gatekeeper never enters
the picture.

For the graphical viewer:

```bash
pipx install "ostrace[gui]"
```

### Requirements

| | |
| --- | --- |
| Python | 3.11 or newer |
| Windows | **Apple Mobile Device Service** must be installed. It ships with iTunes from apple.com — *not* the Microsoft Store build. See [docs/troubleshooting.md](docs/troubleshooting.md). |
| macOS / Linux | Nothing beyond the pip install; `usbmuxd` is already present on macOS. |
| Device | Connected over USB and paired (tap **Trust** on the device). |

A note on install size: `ostrace` depends on `pymobiledevice3`, which pulls in
roughly 40 packages of its own. Adding the GUI extra brings PySide6. The full
install is in the hundreds of megabytes. This is documented rather than hidden;
see [docs/adr/0002](docs/adr/0002-use-pymobiledevice3-over-libimobiledevice-cli.md).

## Usage

```bash
ostrace devices          # list attached devices
ostrace doctor           # diagnose the environment
ostrace capture          # stream to a session file
ostrace export           # turn a session file into a report
```

None of these are implemented yet — see the changelog.

## Documentation

| | |
| --- | --- |
| [docs/adr/](docs/adr/) | Architecture decision records: what was decided and why |
| [docs/research/](docs/research/) | The measurements and comparisons the decisions rest on |
| [docs/formats/](docs/formats/) | On-disk format contracts |
| [docs/troubleshooting.md](docs/troubleshooting.md) | When no device shows up |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup |

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).

`ostrace` imports `pymobiledevice3`, which is GPL-3.0-or-later; under the
standard FSF reading that makes a combined work, so matching the licence is the
clean answer rather than a reluctant one. Reasoning in
[docs/adr/0003](docs/adr/0003-license-gpl-3-0-or-later.md).

## Acknowledgements

`ostrace` is a viewer on top of [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)
by doronz88, which does the genuinely hard part: speaking Apple's lockdown and
usbmux protocols in pure Python.
