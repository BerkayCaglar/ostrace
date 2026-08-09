# Documentation

| | |
| --- | --- |
| [adr/](adr/) | Architecture decision records — what was decided and why |
| [research/](research/) | The measurements and comparisons the decisions rest on |
| [formats/](formats/) | On-disk format contracts |
| [design/](design/) | Behaviour contracts, written before the code |
| [troubleshooting.md](troubleshooting.md) | When no device shows up |

Read [adr/](adr/) first if you are wondering why something looks the way it
does. Read [formats/](formats/) if you are writing something that consumes an
`ostrace` export.

## Project status

`ostrace` is a rewrite of a working single-file tool, delivered in phases:

| Phase | Deliverable | State |
| --- | --- | --- |
| 0 | Repository skeleton, packaging, CI, documentation, ADRs | **done** |
| 1 | `model.py`, `sources/`, `storage/`, `paths.py`, `compat.py` | **done** |
| 3a | CLI: `devices`, `capture`, `doctor` | **done** |
| 2 | `analysis/` and `exporters/`, six-column agent bundle | **done** |
| 3b | CLI: `export` | **done** |
| 4 | PySide6 GUI | **done**, against [its contract](design/gui.md) |
| 5 | Release: PyPI via Trusted Publishing, tagged 0.1.0 | in progress — everything but the tag |

Phases 1 and 2 carried the real risk, and phase 4 carried the rest of it: it is
the one part of the program whose macOS behaviour cannot be run here. See
[design/gui.md §12](design/gui.md) for what CI can and cannot prove about it —
the short version is that the model, the colour maths and the key bindings are
verified on all three operating systems, and native menu placement is not
verifiable at all, so it is guarded by a property test rather than by looking.

The documentation under `formats/` and `design/` describes contracts, which are
specified before they are implemented so that the shape is a decision rather
than an accident. Where something is not built yet, the document says so —
`design/gui.md` in particular carries several of these, because phase 4 shipped
a subset of it and each divergence is recorded where it happened rather than
quietly dropped.
