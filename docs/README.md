# Documentation

| | |
| --- | --- |
| [adr/](adr/) | Architecture decision records — what was decided and why |
| [research/](research/) | The measurements and comparisons the decisions rest on |
| [formats/](formats/) | On-disk format contracts |
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
| 2 | `analysis/` and `exporters/`, six-column agent bundle | not started |
| 3b | CLI: `export` | blocked on phase 2 |
| 4 | PySide6 GUI | not started |
| 5 | Release: PyPI via Trusted Publishing, tagged 0.1.0 | not started |

Phases 1 and 2 carry the real risk; 3 to 5 are mechanical.

The documentation under `formats/` describes the target contracts, which are
specified before they are implemented so that the shape is a decision rather
than an accident. Where something is not built yet, the document says so.
