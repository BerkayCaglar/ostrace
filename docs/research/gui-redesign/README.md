# GUI redesign, 2026-08-09

Five working documents produced in one pass, when the viewer that shipped in
0.1.0 was judged to look dated. They are the reasoning behind the visual layer
in `src/ostrace/gui/theme.py` and behind most of what
[design/gui.md](../../design/gui.md) has gained since — kept because a decision
whose evidence has been thrown away is indistinguishable from a preference.

They are **research, not contract.** Where one of these and
[design/gui.md](../../design/gui.md) disagree, the contract is right; where a
document and the code disagree, the document is a snapshot of 2026-08-09 and
the code has moved. Nothing here is maintained against the source.

| Document | What it answers | Evidence quality |
| --- | --- | --- |
| [01-competitors.md](01-competitors.md) | What the competing viewers look like, what their users complain about, and where the opening is | Published issues and documentation, each claim with a URL |
| [02-current-state.md](02-current-state.md) | What was actually wrong with the 0.1.0 window, section by section against its own contract | Measured on Windows 11, PySide6 6.11.1 |
| [03-visual-system.md](03-visual-system.md) | Colour, typography, density, iconography — the tokens `theme.py` now holds | Measured; every colour checked against WCAG |
| [04-qt-feasibility.md](04-qt-feasibility.md) | What Qt Widgets can deliver, what it costs, and what will break | Everything run rather than reasoned about; macOS from documentation only |
| [05-interaction.md](05-interaction.md) | What is on screen, where, and what happens when the user acts | Read against the source and the contract; §10 is the scope split |

**§10 of [05-interaction.md](05-interaction.md) is the one to read first.** It
splits the work into must-have, nice-to-have and later. 0.1.1 took the
must-have items that could be done at once, 0.1.2 finished that tier, and the
nice-to-have and later tiers are still here — this document is the backlog for
them, and the [changelog](../../../CHANGELOG.md) records what shipped.

Two things were changed on the way in: absolute paths off one machine became
repository-relative, and the capture device's name became `My iPhone`. A device
name is the identifier class `tools/audit_capture.py` states plainly that it
cannot recognise — *"an SSID is a word somebody chose; a device name is
another"* — so it is replaced by hand rather than trusted to be dull. The
mockup these documents describe is not in the repository; it was published as
an artifact.
