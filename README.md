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
ostrace doctor                    # why can't I see my device?
ostrace devices --verbose         # list what is attached
ostrace capture --duration 60     # stream to a session file
ostrace export CAPTURE            # turn it into something readable
```

`ostrace capture` writes a session directory under your data directory and
prints the path. `--max-records` and `--duration` both stop it; so does Ctrl-C,
cleanly. If the device disconnects mid-capture it reconnects and records a gap
rather than pretending the log is continuous.

### Exporting

`ostrace export` needs no device. It reads a session directory or a bare
capture file and writes beside it, named after it.

| `--format` | What it is for |
| --- | --- |
| `agent-bundle` *(default)* | A directory of tab-separated text to investigate with `grep` and bounded line reads. The only format that loses nothing — see [docs/formats/agent-bundle.md](docs/formats/agent-bundle.md). |
| `text` | Aligned columns, one record per line, for reading in a terminal. |
| `markdown` | A document with a summary and the records verbatim, to paste into an issue. |
| `jsonl` | One JSON object per record — the session format without the gzip. |
| `ai-report` | A summary that shrinks to a token budget, for handing to a model. |
| `trace` | Verbatim windows around each error, for following what led to one. |

```bash
ostrace export capture.ostrace                         # a bundle beside it
ostrace export capture.ostrace -f trace                # what led to each error
ostrace export capture.ostrace -f ai-report --budget-tokens 20000
```

Everything except the bundle is a summary, and **each one states what it left
out** — the gaps in the capture, the patterns that did not fit, the anchors it
could not reach. An export that quietly stops reads as complete, and a reader
then draws conclusions from an absence that is an artefact of the export rather
than a fact about the device.

Start with `doctor` if anything is not working. Almost every problem here is
environmental rather than a bug, and it checks the causes in the order they
actually occur:

```
[ ok ] ostrace      0.1.0 on Python 3.13.14 (win32)
[ ok ] usbmux       Apple Mobile Device Service on 127.0.0.1:27015
[FAIL] devices      none connected
               Connect the device over USB and unlock it. A charge-only cable
               gives exactly this symptom.
```

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
