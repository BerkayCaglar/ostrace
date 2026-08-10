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
| 5 | Release: PyPI via Trusted Publishing | **done** — `v0.1.1`, [on PyPI](https://pypi.org/project/ostrace/) |

0.1.0 is missing from that row on purpose. It was published and withdrawn the
next day, over the fixtures its `sdist` carried, and the number will not be
reused — PyPI does not allow a deleted version to be re-uploaded, and a tag
pointing at a release that cannot exist would be worse than no tag. The
[changelog](../CHANGELOG.md) keeps its entry in full, because the work in it is
real; only the artifact is gone.

Phases 1 and 2 carried the real risk, and phase 4 carried the rest of it: it was
the one part of the program whose macOS behaviour could not be run here. See
[design/gui.md §12](design/gui.md) for what CI can and cannot prove about it —
the short version is that the model, the colour maths and the key bindings are
verified on all three operating systems, and native menu placement is not
verifiable at all, so it is guarded by a property test rather than by looking.
That section now ends with a first hands-on pass on macOS 26.3.1: which of its
claims were watched happening, which one was wrong, and the 2× device pixel
ratio the pass still did not exercise.

Since 0.1.1 the work has been the GUI backlog: phase 4 shipped a subset of
[design/gui.md](design/gui.md), and the redesign that followed
([research/gui-redesign/](research/gui-redesign/)) split what was left into
three tiers. **The must-have tier is now finished** — the unseen count, the
minimap's viewport marker, `Go to Time`, the row context menu, recent filters,
a hideable detail pane, accessible names, `Ctrl+Q`, the Doctor window and the
reconnect and capture-finished banners. The nice-to-have and later tiers stay
in [research/gui-redesign/05-interaction.md](research/gui-redesign/05-interaction.md)
§10; the [changelog](../CHANGELOG.md) is where what shipped is written down.

**None of it is released.** The last tag is `v0.1.1` and all of the above is
under `## [Unreleased]`, so what PyPI serves is a good deal older than this
tree. The next version is 0.1.2.

The documentation under `formats/` and `design/` describes contracts, which are
specified before they are implemented so that the shape is a decision rather
than an accident. Where something is not built yet, the document says so —
`design/gui.md` in particular carries several of these, because phase 4 shipped
a subset of it and each divergence is recorded where it happened rather than
quietly dropped.
