## What this changes

<!-- And why. Link the issue if there is one. -->

## Checklist

- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `mypy` passes
- [ ] `pytest -m "not device"` passes
- [ ] `CHANGELOG.md` updated under `## [Unreleased]`, if user-visible
- [ ] New behaviour has a test; a bug fix has the test that fails without it

## If this touches a parser or an export format

- [ ] Tested against a fixture captured from a real device, **not** against
      hand-written sample lines
- [ ] If a column changed in a documented format, `docs/formats/` is updated and
      the version bumped

## If this reverses a decision in `docs/adr/`

- [ ] A new ADR supersedes the old one, rather than editing it
