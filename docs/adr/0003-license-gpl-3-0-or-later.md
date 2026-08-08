---
status: accepted
date: 2026-08-08
decision-makers: Berkay ÇAĞLAR
---

# License the project GPL-3.0-or-later

## Context and Problem Statement

[ADR 0002](0002-use-pymobiledevice3-over-libimobiledevice-cli.md) makes
`pymobiledevice3` an imported dependency. `pymobiledevice3` is licensed
GPL-3.0-or-later. Under the Free Software Foundation's standard reading, a
Python program that imports a GPL library forms a combined work, and
distributing that combined work means distributing under the GPL.

This project is intended to be published publicly on GitHub and PyPI, so
"distribution" is exactly what will happen.

One misconception is worth stating plainly because it is common: the GPL is
triggered by **distribution**, not by commercial intent. Giving software away
for free does not exempt a project from it. In this case the conclusion is the
same either way, but for the right reason.

## Decision Drivers

- Legal correctness given a GPL dependency that is not going to be removed.
- Keep the option of relicensing later, if the dependency is ever replaced.
- Do not make the licence a decision users have to think about.

## Considered Options

1. **GPL-3.0-or-later** — match the dependency.
2. **GPL-3.0-only.**
3. **MIT or Apache-2.0** and treat the dependency question as someone else's.
4. **Avoid the GPL dependency** — subprocess isolation, or implement the
   protocols directly.

## Decision Outcome

Chosen option: **GPL-3.0-or-later**, declared as an SPDX expression in
`pyproject.toml` ([PEP 639](https://peps.python.org/pep-0639/)) with per-file
[REUSE](https://reuse.software/spec/) headers:

```python
# SPDX-FileCopyrightText: 2026 Berkay ÇAĞLAR
# SPDX-License-Identifier: GPL-3.0-or-later
```

`-or-later` rather than `-only`, so a future FSF licence version can be adopted
without tracking down contributors for permission.

### Consequences

- Good: unambiguously compatible with the dependency; nothing to argue about.
- Good: `-or-later` keeps forward-compatibility open.
- Good: two-line per-file headers keep the source readable while remaining
  machine-checkable.
- **Bad: this forecloses adoption inside proprietary products.** Anyone shipping
  a closed-source tool cannot link this. That is a real cost, accepted knowingly
  — this is a standalone log viewer, not a library other people build on.
- Consequence for the GUI: **PySide6, not PyQt6**. PyQt6 is GPLv3-*only*, which
  would pin the project to exactly version 3 and permanently foreclose the
  "or-later" option. PySide6's LGPLv3 arm costs nothing here. See
  [ADR 0004](0004-pyside6-with-custom-filtered-model.md).
- Consequence for future dependencies: any new dependency must be GPL-3
  compatible. In practice this rules out a specific class of commercially
  licensed components — AG Grid Enterprise, for one, whose EULA cannot be
  combined with GPL-3 and which is therefore off the table if a web UI is ever
  built.

### Confirmation

- `pyproject.toml` declares `license = "GPL-3.0-or-later"` and
  `license-files = ["LICENSE"]`.
- `LICENSE` holds the full, unmodified GPL-3.0 text.
- Every source file carries the two SPDX lines.
- `twine check --strict` runs in CI and fails on malformed licence metadata.

## Pros and Cons of the Options

### MIT or Apache-2.0

- Good, because it is the least friction for adopters.
- Bad, because with a GPL dependency it would be, at best, misleading about
  what a user actually receives, and at worst simply not permitted.

### Avoid the GPL dependency

- Good, because it would leave the licence genuinely free to choose.
- Bad, because subprocess isolation means going back to parsing text and losing
  the structured fields that motivated the rewrite at all.
- Bad, because implementing lockdown and `os_trace_relay` directly is months of
  work against an undocumented, moving protocol.
- The licence tail would be wagging the architecture dog.

## More Information

- [GNU: Can I release a program under the GPL that I developed using non-free tools?](https://www.gnu.org/licenses/gpl-faq.html)
- [PEP 639 – Improving License Clarity with SPDX](https://peps.python.org/pep-0639/)
- [REUSE Specification](https://reuse.software/spec/)
