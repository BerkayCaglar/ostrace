# ostrace

[![pypi](https://img.shields.io/pypi/v/ostrace)](https://pypi.org/project/ostrace/)
[![python](https://img.shields.io/pypi/pyversions/ostrace)](https://pypi.org/project/ostrace/)
[![ci](https://img.shields.io/github/actions/workflow/status/BerkayCaglar/ostrace/ci.yml?branch=main)](https://github.com/BerkayCaglar/ostrace/actions/workflows/ci.yml)
[![licence](https://img.shields.io/pypi/l/ostrace?label=licence)](https://github.com/BerkayCaglar/ostrace/blob/main/LICENSE)

Stream, inspect and export iOS device logs — on Windows, macOS and Linux.

`ostrace` reads Apple's unified log over `com.apple.os_trace_relay`, the same
service Console.app uses. That means structured records: subsystem, category,
thread id and the emitting library, at DEBUG level and above — not just the
NOTICE-tier text that the legacy `syslog_relay` path returns. Reading both
services from one `iPhone18,2` over the same minute, `os_trace_relay` delivered
233,956 records and `syslog_relay` 11,642: **222,477 of them — 95% — reach one
service and not the other.**

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/BerkayCaglar/ostrace/main/docs/images/viewer-dark.png">
  <img alt="The ostrace viewer on Windows, showing a capture from an iPhone with an error selected and every field of it in the detail pane" src="https://raw.githubusercontent.com/BerkayCaglar/ostrace/main/docs/images/viewer-light.png">
</picture>

---

## Why

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/BerkayCaglar/ostrace/main/docs/images/log-sources-dark.png">
  <img alt="Two bars on the same scale. os_trace_relay: 233,956 records in one minute, 88% of them DEBUG, 7% INFO, 4.8% NOTICE, 0.1% ERROR. syslog_relay: 11,642 entries over the same minute, the NOTICE tier and above and nothing below it, 5% of the log." src="https://raw.githubusercontent.com/BerkayCaglar/ostrace/main/docs/images/log-sources-light.png">
</picture>

Both relays were read **at the same time, from one process, over the same
minute** — the same device delivers 5,140 records in one 20-second window and
36,763 in another, so measuring them one after the other compares the device's
mood rather than the two services.

What `syslog_relay` returns is the NOTICE tier and above, and nothing below it.
Across three runs it matched that boundary to within 1.5%, and once exactly.
Tools built on it — `idevicesyslog` among them — therefore never receive the
DEBUG and INFO records, which are the ones that matter when you are debugging
your own app. Roughly 90% of the log is on the other side of that line.

The ratio itself is not the claim: it moved between 9.1× and 20.1× across those
runs, with how much DEBUG the device happened to be emitting. What did not move
is which tiers arrive.

Separately, 96.8% of records in the reference capture carry a `subsystem` and
`category` that the text-based pipeline discards — measured between 80% and 97%
across the captures in `tests/fixtures/` and since.

`os_trace_relay` is still an ordinary lockdown service on iOS 26: no RemoteXPC
tunnel, no administrator privileges.

## Install

```bash
pipx install "ostrace[gui]"
```

`pipx` (or `uv tool install`) is the recommended route. Files installed by a
package manager are never quarantined by macOS, so Gatekeeper never enters the
picture. Leave off `[gui]` for the command line alone, which is a much smaller
install.

| | |
| --- | --- |
| Python | 3.11 or newer |
| Windows | **Apple Mobile Device Service** must be installed. It ships with iTunes from apple.com — *not* the Microsoft Store build. See [docs/troubleshooting.md](https://github.com/BerkayCaglar/ostrace/blob/main/docs/troubleshooting.md). |
| macOS | Nothing beyond the pip install; `usbmuxd` is already present. The graphical viewer needs **macOS 13 or newer**, which is Qt 6.11's floor; the command line does not. |
| Linux | Nothing beyond the pip install, plus a running `usbmuxd`. |
| Device | Connected over USB and paired (tap **Trust** on the device). |

A note on install size: `ostrace` depends on `pymobiledevice3`, which pulls in
90 distributions of its own — measured, not estimated — and the GUI extra brings
PySide6. The full install is in the hundreds of megabytes. This is documented
rather than hidden; see
[docs/adr/0002](https://github.com/BerkayCaglar/ostrace/blob/main/docs/adr/0002-use-pymobiledevice3-over-libimobiledevice-cli.md).

## The viewer

```bash
ostrace-gui
```

**Capture** streams from an attached device; **Open** reads a capture from
disk. Either way the records go into a virtualised table coloured by severity,
with every field of the selected row in the pane below — including the two that
routinely get confused, the process executable and the library that emitted the
line.

A few things it does deliberately:

- **Pause freezes the view and nothing else.** The capture keeps running and
  keeps writing every record to the session file, so nothing is lost by looking
  away. Disconnect is the control that releases the device, and it is named
  after its consequence rather than called "stop".
- **A gap is a row.** When the device disconnects mid-capture, the hole in the
  log appears in the table where it happened, in position, and it survives
  every filter. A filter says which records you want; a gap says whether the
  answer is complete, and hiding one to satisfy the other would make the view
  lie about the capture.
- **The strip beside the table** marks every error, gap and mark across the
  whole capture, not just the visible part. Clicking jumps there. It is the
  only thing that will tell you about a discontinuity forty thousand rows above
  where you are reading.
- **Filters keep your place.** Changing a filter anchors the selection and the
  viewport to the record you were reading, not to a row number, and falls back
  to the nearest survivor when that record is filtered away.

| | |
| --- | --- |
| <kbd>Ctrl</kbd>+<kbd>R</kbd> | Capture from the device |
| <kbd>Ctrl</kbd>+<kbd>P</kbd> | Pause the view |
| <kbd>Ctrl</kbd>+<kbd>D</kbd> | Disconnect, releasing the device |
| <kbd>Ctrl</kbd>+<kbd>O</kbd> | Open a capture |
| <kbd>Ctrl</kbd>+<kbd>E</kbd> | Export |
| <kbd>Ctrl</kbd>+<kbd>F</kbd> or <kbd>/</kbd> | Find |
| <kbd>E</kbd> / <kbd>Shift</kbd>+<kbd>E</kbd> | Next / previous error |
| <kbd>]</kbd> / <kbd>[</kbd> | Next / previous gap |
| <kbd>M</kbd> | Mark the row |
| <kbd>F1</kbd> | Every binding, generated from the same table the menus use |

## The command line

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

Start with `doctor` if anything is not working. Almost every problem here is
environmental rather than a bug, and it checks the causes in the order they
actually occur:

```
[ ok ] ostrace      0.1.2 on Python 3.13.14 (win32)
[ ok ] usbmux       Apple Mobile Device Service on 127.0.0.1:27015
[FAIL] devices      none connected
               Connect the device over USB and unlock it. A charge-only cable
               gives exactly this symptom.
```

### What a script can rely on

| Exit code | |
| --- | --- |
| `0` | It worked. |
| `1` | It did not — no device, an unreadable capture, a path the filesystem refused. The message names the cause and the hint names the remedy. |
| `2` | The command line itself was wrong, and nothing ran. |
| `130` | Ctrl-C, which is what a shell reports for it. A capture still finalises its session file and releases the device on the way out. |

`devices` and `doctor` exit **`1` when they find nothing**. "No devices
connected" is both the answer and a failure, and a script waiting for a phone to
appear should not have to read English to notice that it has not.

`--quiet` means a different thing on each command that has one, because they are
answering different questions:

- `ostrace capture --quiet` drops the progress counter, which was on stderr. The
  record count and the path still go to stdout — those are the result, not
  progress.
- `ostrace export --quiet` prints only the destination. The notes saying what
  the export left out stay on stderr regardless: they are the bad news, and a
  flag about stdout is not permission to hide it.

Both commands leave the path they wrote as the last line of stdout.

## Exporting

`ostrace export` needs no device, and the viewer's export dialog offers the
same formats. It reads a session directory or a bare capture file and writes
beside it, named after it.

| `--format` | What it is for |
| --- | --- |
| `agent-bundle` *(default)* | A directory of eight tab-separated text files to investigate with `grep` and bounded line reads. The only format that loses nothing — see [docs/formats/agent-bundle.md](https://github.com/BerkayCaglar/ostrace/blob/main/docs/formats/agent-bundle.md). |
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

## Using it as a library

Everything the command line does is importable, and reading a capture costs
nothing that talking to a device would cost. No import listed below loads Qt or
`pymobiledevice3` — 90 distributions, measured — including the one that speaks
to a phone: the device library is reached from inside the call that opens the
relay, so it arrives when you connect rather than when you import. That is also
why there is deliberately no flat re-export at the top of the package. One line
there would put the whole device stack behind every offline use.

```python
from ostrace.storage import open_capture

capture = open_capture("2026-08-12T13-04-19")
for item in capture:  # records and gaps, in the order they arrived
    ...
```

| Import | What it is for |
| --- | --- |
| `from ostrace.model import Record, Gap, Level, DeviceInfo, Platform` | The vocabulary. Everything downstream of a source speaks it and nothing else. |
| `from ostrace.storage import open_capture, Capture` | Read a session directory or a bare capture file without having to know which one you were handed. |
| `from ostrace.sources import ReplaySource, LogSource` | A recorded session as a stream. `LogSource` is the protocol a live device satisfies too, which is what makes the two substitutable. |
| `from ostrace.capture import capture, CaptureResult` | Run a capture: `async`, takes any `LogSource`, writes a session file. |
| `from ostrace.exporters import EXPORTERS` / `from ostrace.exporters.base import register` | The six formats by name, and how to add a seventh. |
| `from ostrace.errors import OstraceError` | The base of everything raised deliberately. Every subclass carries a `hint`, and says whether retrying could work. |
| `from ostrace.sources.os_trace import OsTraceSource` | A live device, over USB. The one that eventually needs `pymobiledevice3`, and the only one that needs a phone. |

Below 1.0.0 these names are not frozen, but they are the supported surface: if
one moves, the [CHANGELOG](https://github.com/BerkayCaglar/ostrace/blob/main/CHANGELOG.md)
says so. Anything not listed here is internal, `ostrace.gui` included.

## What this is not

- **There are no downloadable binaries.** Install from PyPI; that is also what
  keeps macOS from quarantining anything.
- **Nothing is code-signed.** It does not need to be on the install route
  above.
- **macOS has now been run by hand, once.** Every test including the eleven
  that need a real iPhone passes on macOS 26.3.1, and the assumptions that were
  marked unverified in the source have been checked. That is one pass on one
  machine, not a support commitment: that machine drove a single non-Retina
  display, so nothing here has yet been seen at the 2× device pixel ratio most
  Macs run at. Reports are still welcome.

  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/BerkayCaglar/ostrace/main/docs/images/viewer-macos-dark.png">
    <img alt="The same window on macOS, drawn in the system font, with no menu bar inside it because macOS puts one in the screen menu instead" src="https://raw.githubusercontent.com/BerkayCaglar/ostrace/main/docs/images/viewer-macos-light.png">
  </picture>

  *The same capture and the same code on macOS. The window carries no menu bar
  of its own: there it belongs to the screen.*
- **Only iOS is supported.** The device layer is written around lockdown and
  `os_trace_relay`.

## Documentation

| | |
| --- | --- |
| [docs/adr/](https://github.com/BerkayCaglar/ostrace/tree/main/docs/adr/) | Architecture decision records: what was decided and why |
| [docs/design/gui.md](https://github.com/BerkayCaglar/ostrace/blob/main/docs/design/gui.md) | The viewer's behaviour contract, written before the code |
| [docs/research/](https://github.com/BerkayCaglar/ostrace/tree/main/docs/research/) | The measurements and comparisons the decisions rest on |
| [docs/formats/](https://github.com/BerkayCaglar/ostrace/tree/main/docs/formats/) | On-disk format contracts |
| [docs/troubleshooting.md](https://github.com/BerkayCaglar/ostrace/blob/main/docs/troubleshooting.md) | When no device shows up |
| [CONTRIBUTING.md](https://github.com/BerkayCaglar/ostrace/blob/main/CONTRIBUTING.md) | Development setup |

## Licence

GPL-3.0-or-later. See [LICENSE](https://github.com/BerkayCaglar/ostrace/blob/main/LICENSE).

`ostrace` imports `pymobiledevice3`, which is GPL-3.0-or-later; under the
standard FSF reading that makes a combined work, so matching the licence is the
clean answer rather than a reluctant one. Reasoning in
[docs/adr/0003](https://github.com/BerkayCaglar/ostrace/blob/main/docs/adr/0003-license-gpl-3-0-or-later.md).

The application mark — `src/ostrace/gui/icons/app.svg` and the card built from
it — is under the same licence as everything else here, so nothing stops you
redistributing it. The request is only that a fork which changes behaviour draws
its own, because an icon in a taskbar is how somebody tells one program from
another and there is no way to check which one they got.

## Acknowledgements

`ostrace` is a viewer on top of [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)
by doronz88, which does the genuinely hard part: speaking Apple's lockdown and
usbmux protocols in pure Python.
