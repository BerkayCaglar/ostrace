# ostrace

Stream, inspect and export iOS device logs — on Windows, macOS and Linux.

`ostrace` reads Apple's unified log over `com.apple.os_trace_relay`, the same
service Console.app uses. That means structured records: subsystem, category,
thread id and the emitting library, at DEBUG level and above — not just the
NOTICE-tier text that the legacy `syslog_relay` path returns.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/BerkayCaglar/ostrace/main/docs/images/viewer-dark.png">
  <img alt="The ostrace viewer showing a capture from an iPhone, with an error selected and every field of it in the detail pane" src="https://raw.githubusercontent.com/BerkayCaglar/ostrace/main/docs/images/viewer-light.png">
</picture>

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
| Windows | **Apple Mobile Device Service** must be installed. It ships with iTunes from apple.com — *not* the Microsoft Store build. See [docs/troubleshooting.md](docs/troubleshooting.md). |
| macOS | Nothing beyond the pip install; `usbmuxd` is already present. The graphical viewer needs **macOS 13 or newer**, which is Qt 6.11's floor; the command line does not. |
| Linux | Nothing beyond the pip install, plus a running `usbmuxd`. |
| Device | Connected over USB and paired (tap **Trust** on the device). |

A note on install size: `ostrace` depends on `pymobiledevice3`, which pulls in
roughly 40 packages of its own, and the GUI extra brings PySide6. The full
install is in the hundreds of megabytes. This is documented rather than hidden;
see [docs/adr/0002](docs/adr/0002-use-pymobiledevice3-over-libimobiledevice-cli.md).

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
[ ok ] ostrace      0.1.0 on Python 3.13.14 (win32)
[ ok ] usbmux       Apple Mobile Device Service on 127.0.0.1:27015
[FAIL] devices      none connected
               Connect the device over USB and unlock it. A charge-only cable
               gives exactly this symptom.
```

## Exporting

`ostrace export` needs no device, and the viewer's export dialog offers the
same formats. It reads a session directory or a bare capture file and writes
beside it, named after it.

| `--format` | What it is for |
| --- | --- |
| `agent-bundle` *(default)* | A directory of eight tab-separated text files to investigate with `grep` and bounded line reads. The only format that loses nothing — see [docs/formats/agent-bundle.md](docs/formats/agent-bundle.md). |
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

## What 0.1.0 is not

- **There are no downloadable binaries.** Install from PyPI; that is also what
  keeps macOS from quarantining anything.
- **Nothing is code-signed.** It does not need to be on the install route
  above.
- **macOS is verified by CI, not by hand.** The test suite and a screenshot job
  run on a macOS runner every change, but no Mac has ever run this
  interactively. Assumptions that could not be checked are marked
  `# UNVERIFIED-MACOS` in the source. Reports from an actual Mac are welcome.
- **Only iOS is supported.** The device layer is written around lockdown and
  `os_trace_relay`.

## Documentation

| | |
| --- | --- |
| [docs/adr/](docs/adr/) | Architecture decision records: what was decided and why |
| [docs/design/gui.md](docs/design/gui.md) | The viewer's behaviour contract, written before the code |
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
