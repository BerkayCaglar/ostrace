# ostrace

Cross-platform iOS log viewer, released: 0.2.0 is on PyPI. That covers the
model, sources and storage (phases 0-1), `analysis/` plus all six exporters
(phase 2), the command line — `devices`, `capture`, `doctor`, `export`
(phase 3), the PySide6 viewer in `gui/` (phase 4), and the release machinery
itself (phase 5).

**`main` and `v0.2.0` are the same tree.** When that stops being true, say by
how much and add the sentence back: a bug reproduced against the published
package is not necessarily a bug here, and `CHANGELOG.md`'s `## [Unreleased]`
section is where the gap is written down.

0.2.0 was planned as a structural release and shipped as a feature one. Its
plan lives outside this repository, beside the design notes, and **all eight of
its packages landed** — P (public presence and application identity), A
(contract safety nets), B (the source seam), C (GUI mechanics), D (the capture,
follow and theme controllers), E (the view layer), F (the storage facade) and G
(the public surface and the paper trail). Nothing structural is outstanding.

**The GUI redesign's tiers are both closed.** The must-have tier shipped in
0.1.1 and 0.1.2; the nice-to-have tier went into 0.2.0 in four packages — the
filter bar, the capture options, the export dialog and the View menu. One item
of it was not built and the reason is a measurement, recorded in
`docs/research/gui-redesign/05-interaction.md` §10. What is left is the Later
tier, which is where a feature for 0.3.0 would come from.

**All of it has now been on hardware**, on 2026-08-12: the eleven device tests,
a capture and an export end to end, and the viewer driven by hand through a live
capture and a gap. What that session did not cover is a multi-hour capture, the
three wire-level questions in the plan's §6 — a cancel landing inside the
lockdown handshake, double-close tolerance, a genuinely hanging identify — and
anything needing a Mac or a Linux desktop.

The window went from 2,155 lines to 1,817 across C, D and E, and five
controllers came out of it — `gui/settings.py`, `gui/actions.py`,
`gui/capture_controller.py`, `gui/follow.py`, `gui/theme_policy.py`. ADRs 0007
to 0009 record why they are shaped that way and what deliberately stayed on the
window.

0.1.0 does not exist. It was published and withdrawn the next day over the
fixtures inside its `sdist`, and the number will not be reused — so there is
deliberately no `v0.1.0` tag, and a commit or document referring to one is
wrong rather than missing.

Read when relevant, rather than up front: `docs/adr/` for why decisions were
taken, `docs/formats/` for the on-disk contracts, `CONTRIBUTING.md` for setup,
`docs/README.md` for the phase table.

<!-- Deliberately not @-imports: those load at launch and would put the whole
     docs tree in context every session for no benefit. Also note that any bare
     @-prefixed token in this file IS parsed as an import, which is why the
     pytest marker below is backticked. -->

## Commands

```bash
pip install -e ".[gui]" --group dev   # PEP 735, needs pip >= 25.1 -- not .[dev]
ruff check . && ruff format --check .
zizmor --persona=regular .github/workflows
mypy --platform linux && mypy --platform win32 && mypy --platform darwin
pytest -m "not device and not gui"
QT_QPA_PLATFORM=offscreen pytest -m gui
python tools/audit_capture.py tests/fixtures/ios26-mixed.jsonl.gz
```

**Install the `gui` extra even when not touching the GUI.** Without PySide6,
mypy cannot see `src/ostrace/gui` at all and reports success on a package it
never opened, and every GUI test turns into a skip. CI's lint job installs it
for exactly that reason.

All of these run in CI, which additionally runs CodeQL from GitHub's default
setup — there is no file for it under `.github/workflows/`, so it is invisible
to anyone reading the repository alone. The GUI tests are a job of their own on
all three operating systems, which is why they are a separate command here.

mypy runs three times on purpose: it narrows `sys.platform`
to whatever it runs on, so a single pass leaves the other platforms' branches
unchecked — which is where the bugs would be, since one machine can only ever
run one of the three.

Clone with full history. The version comes from git tags via hatch-vcs and a
shallow clone builds as `0.0.0`.

## Hard rules

Each of these has cost real time at least once.

- **Validate parsers against `tests/fixtures/` captures, never against
  hand-written log lines.** A previous iteration matched 0% of real device
  output for weeks because its samples contained a syslog hostname field that
  real output does not have. The tests passed the whole time.
- **Never run device code under `-O` / `PYTHONOPTIMIZE`.** pymobiledevice3's
  stream loop is `assert await self.service.recvall(1) == b"\x02"`;
  optimisation strips the `assert` *including the `await` inside it*, which
  desynchronises the wire protocol and yields garbage instead of an error.
  `OsTraceSource` refuses to construct when the flag is set.
- **A device stream is two sockets, not one.** The lockdown session starts
  `os_trace_relay` and hands back a *separate* service connection; closing
  lockdown does not close it. `aclose()` closed only the lockdown for a while —
  it returned in a millisecond, reported success, and left the device
  delivering thousands more records into a stream nobody was reading. Anything
  that releases a device releases the service too, and first, because that is
  the read the generator is blocked on.
- **Only `compat.py` may branch on the operating system** or touch a
  platform-specific attribute. Write the literal `sys.platform == "win32"`
  form, not a named constant — type checkers narrow on the literal and not on a
  constant, and the three-platform mypy run depends on that.
- **Mark unverified macOS assumptions `# UNVERIFIED-MACOS`** so they can be
  grepped and confirmed. A Mac is available now and the four markers that
  existed have been checked, so this is a rule about what gets written next
  rather than a backlog. One of the four was wrong, which is the argument for
  keeping the convention rather than against it.
- **Only `paths.py` decides where files go.** Building a path from a literal is
  how the predecessor ended up unable to run anywhere but Windows. File *names
  inside* an export are the format contract, not a location decision, and
  belong to the exporter.
- **`docs/formats/` wins over the code.** A column's position, a header row, a
  placeholder spelling — if the implementation and the document disagree, the
  document is right and the code is the bug. Bundles already written to disk
  stay valid forever.
- **Timestamps are timezone-aware, carrying the *device's* offset.** The host is
  a different clock in a frequently different zone. A naive timestamp is
  rejected on read rather than guessed at.
- **Do not bump the exact `ruff` / `mypy` pins to make an error go away.**
- **Actions are referenced by full commit SHA, never by tag**, with the release
  in a trailing comment. A tag can be repointed by whoever owns the action; the
  repository enforces this, so a tag ref fails the run rather than the review.
  Let Dependabot do the bumping — it rewrites the SHA and the comment together.
- **A comment explains the code; git explains the history.** Delete the diary —
  dates, pull request numbers, "was broken until". Rationale that merely reads
  as history gets rewritten forward rather than deleted: `it used to name the
  first device found` becomes `not the first device found`, and the reason
  after it survives word for word. But **a measurement and its method are never
  removed, rounded, or summarised away**. The minimap summarises into fixed
  buckets rather than pixel bands because bands measured 282 ms over 200,000
  rows; trimming happens in one operation because three took 118 ms and one
  takes 50. Take the numbers out and those become opinions, and the next
  tidy-up reintroduces the problem they were paid for.
- Two SPDX lines at the top of every new source file, matching the existing ones.

## Architecture

The load-bearing constraint is the `LogSource` protocol in `sources/base.py`.
Its surface is small on purpose: a recorded session must be substitutable for a
live device in every test, which is what lets CI cover the pipeline on three
operating systems with no hardware.

- Consumers take a `LogSource`. Never a concrete source, and never a method one
  implementation has and the other does not.
- New sources inherit `SourceCloseMixin` rather than re-implementing the async
  context manager pair. Its `aclose()` raises rather than defaulting to a no-op,
  so forgetting to release something is loud instead of a slow socket leak.
- `Gap` travels *in* the stream, in position. A gap that happened between these
  two records and not those two loses its meaning through a side channel.
- `stream()` can block indefinitely without yielding — a quiet device goes
  silent for tens of seconds. Drive any timeout from a separate task; waiting
  for the next record in order to notice time has passed is a hang.
- Nothing outside `sources/` and `devices/` imports pymobiledevice3. `errors.py`
  translates its exceptions by class *name* so the dependency stays confined.
  Inside those two, the import sits in the function that needs it, so nothing
  loads until a service is actually opened — `import ostrace` and every
  documented offline import stay free of 90 distributions, asserted rather than
  intended.
- **The pump outlives the capture thread, never the reverse.** A stop wait is
  bounded so a stuck device cannot freeze the window, and on a timeout the
  thread is parked with its pump *running and paused*, until the thread really
  ends and the pump takes a final drain. Stopping the pump there instead grows
  the deque without bound at up to 1,600 records a second, silently, because a
  stopped pump reports nothing; letting go of the thread is worse, since Qt's
  destructor calls `qFatal` and the viewer vanishes with exit `0xC0000409` and
  no message. `gui/capture_controller.py` owns all of it and says nothing a user
  reads. [ADR 0007](docs/adr/0007-capture-lifecycle-the-pump-outlives-the-thread.md).
- **`RecordModel`'s rows, filter, marks and Qt bracketing stay inside the Qt
  model; only pure arithmetic comes out** — `plan_trim` and `fit_budgets`, which
  are then testable with no Qt at all. A Qt-free buffer underneath would have to
  tell the model what it had just done, which is the same coupling with an extra
  hop, a chance to disagree, and an indirection on the ingest path.
  [ADR 0009](docs/adr/0009-keep-the-model-core-inside-the-qt-model.md).

## Tests

- `` `@pytest.mark.device` `` means a physical iPhone is required. It is
  excluded in CI. Never add it to a test that could run against a fixture, and
  never add it to make CI green.
- Fixtures are real captures from an `iPhone18,2` on iOS 26.5.2, filtered to
  system processes. `tests.helpers.make_record` synthetics are fine for
  round-tripping our own file format and wrong for anything asserting how
  device output is interpreted.
- New behaviour ships with a test. A bug fix ships with the test that fails
  without it.
- `test_sources_os_trace.py` scripts the *service*, through the `_open_service`
  seam. It replaced `_stream_once` wholesale until 0.2.0, and that is the method
  which acquires, records and releases the second socket — so socket ownership
  was structurally invisible there, and measurably: deleting the
  `_stream_service` binding and swapping the `async with` operands each left all
  520 tests green. Both fail now. Anything that replaces `_stream_once` again
  gives that up, and the six named mutations are the check.
- What stays device-only is the wire: whether closing the real socket interrupts
  a blocked `recvall`, the `-O` hazard, and whether the relay is busy on the next
  capture. Those cannot be faked, and a green run without hardware says nothing
  about them.

## Etiquette

Update `CHANGELOG.md` under `## [Unreleased]` for anything user-visible.
Conventional-ish commit subjects. One logical change per pull request.

<!-- The agent-bundle exporter (phase 2) generates a CLAUDE.md *inside each
     exported capture* to orient an agent investigating that log. That is a
     build artifact and has nothing to do with this file. -->

`docs/design/gui.md` is a behaviour contract written before the code, and parts
of it describe things phase 4 deliberately did not build — its own §13 lists
some, and a few more are recorded there where the implementation went a
different way with a reason. A mismatch between that document and the code is
worth reading before assuming either side is wrong.
