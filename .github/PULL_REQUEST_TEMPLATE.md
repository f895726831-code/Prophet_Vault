## What this changes

<!-- One concern per PR. What behaviour changes, and why. -->

## How it was checked

- [ ] `python -m pytest` passes
- [ ] `python -m ruff check .` and `python -m ruff format --check .` pass
- [ ] Tested against a real Prophet workspace (say which Prophet/Firebird version), or
      not applicable

## Anything a reviewer should know

<!-- Trade-offs, follow-up work, a decision you are unsure about. -->

## Checklist

- [ ] No real model data is included (no `.PRW`, `.RCI`, snapshot or vault from a
      production model)
- [ ] `CHANGELOG.md` updated under `## Unreleased` if user-visible
- [ ] Docs updated where behaviour or flags changed
