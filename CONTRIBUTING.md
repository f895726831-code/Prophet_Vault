# Contributing

Thanks for taking a look. This project exists because a model that cannot be searched is a
model that only one person understands.

## Development setup

```bash
git clone https://github.com/f895726831-code/Prophet_Vault.git
cd Prophet_Vault
python -m venv .venv
# Windows: .venv\Scripts\activate     POSIX: source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The test suite is offline and needs no Prophet installation. If you have a real `.PRW`, the
`examples/` generator plus a manual `snapshot` run is the fastest way to sanity-check a
change.

## What is most useful

1. **Parser fixes.** `VAR_LIST.RCI` and `isql` output are both undocumented and both vary
   between Prophet versions. A redacted sample file, or the exact `isql` output shape that
   breaks a parser, is worth more than a patch.
2. **Schema reports.** If a table or column name differs in your version, run
   `python -m prophet_vault schema` and open an issue with the output.
3. **Adapters.** The snapshot contract (`docs/data-model.md`) is the seam. A Moses, AXIS or
   RAFM extractor only needs to produce those eight files.
4. **Translations of the docs.** The project started in a Chinese-speaking actuarial team;
   `README.zh-CN.md` exists for that reason.

## Ground rules

* **Never commit real model data.** No `.PRW`, `.RCI`, `.fac` files, no snapshots or vaults
  generated from a production model, no screenshots containing variable names that are not
  public. `.gitignore` covers the file types; the responsibility for a page or an image is
  yours. The demo generator produces entirely fabricated data - use it for examples.
* **Keep the package dependency-free.** The core uses the standard library only. `pytest` is
  the only development dependency. A parser or renderer that needs a heavyweight library
  belongs in a separate optional module with a documented reason.
* **Tests come with the change.** Every module with behaviour worth defending has a test
  module (`tests/test_<module>.py`); a bug fix should add the case that reproduced it.
  Small helpers are covered through their callers rather than in isolation.
* **Document the *why*.** Docstrings explain the decisions (why `isql` instead of a driver,
  why the hash ignores whitespace, why the graph caps depth). Keep that style.

## Code style

* `ruff` with the config in `pyproject.toml` (`line-length = 100`).
* Type hints on public functions; `from __future__ import annotations` at the top.
* No camelCase in Python, no abbreviations that need a comment.

```bash
ruff check prophet_vault tests
ruff format prophet_vault tests
```

## Commit messages

Short imperative subject, then a body explaining the consequence:

```
Fix identifier filter for names ending in a digit

VAR_LIST.RCI in Prophet 2024 keeps a trailing digit in some records; the
validator rejected them, silently dropping ~1% of the variable list.
```

## Pull requests

* One concern per PR. A parser fix and a doc rewrite are two PRs.
* Say which Prophet version (if any) you tested against.
* Update `CHANGELOG.md` under `## Unreleased`.

## Licence

Contributions are accepted under the MIT licence (see `LICENSE`).
