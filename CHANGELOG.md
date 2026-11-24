# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `ruff` is pinned in the `dev` extra (`0.15.16`, the version the code base is formatted
  with) so that `ruff format --check` in CI cannot turn red from a formatter change alone.

## [0.1.1] - 2026-11-24

### Fixed

- **`update-vault` silently skipped pages when a diff had more than 200 changes.** The JSON
  report was capped at 200 entries per section, and `update-vault` replays exactly that
  file - so on a large month (250 formula changes, say) 50 pages were never updated and
  nothing reported it. `Diff.as_json()` is now complete; only the Markdown report is capped,
  and only the before/after formula *preview text* is shortened. `update-vault` additionally
  warns when a report lists fewer entries than its own summary claims.
- **A deleted variable was re-created in the `Summary` folder, leaving the original page
  live.** The updater derived the target path from the new snapshot, which no longer knows
  the variable's library. Deleted pages now stay in their own library folder and keep their
  definition and description; only the `deprecated` tag, the warning callout and a
  `version_history` entry are added.
- **A variable that moved between libraries kept a stale page.** Library moves are not a
  diff dimension, so they are reconciled from the snapshot after the update: the file moves,
  the content does not change.
- **`isql` failures were indistinguishable from empty results.** The error check in
  `IsqlRunner._invoke` could never fire, so a rejected query produced an empty snapshot
  instead of an error. `Statement failed` / `SQLSTATE = ...` now raises `IsqlError`, which
  the CLI reports as `error:` with exit code 2.
- **An empty extraction was accepted as a valid snapshot.** A successful query returning no
  rows produced a header-only snapshot that became the new baseline, so the next diff
  reported the whole model as deleted. `extract_all` now raises unless `--allow-empty` is
  given, and warns when variables exist but no formulas were returned.
- **A partly copied snapshot loaded as an empty model.** `Snapshot.load` now requires the
  core files and names the missing ones; `dimensions.csv` stays optional.
- **`graph` without `--snapshot` could render the wrong model.** The newest snapshot was
  chosen by folder name, so `demo_2026-01` beat `2026-11`. It now uses `metadata.json`'s
  `created_at`, falling back to the name.
- **Library names broke the YAML frontmatter.** A library called `Life: UK` invalidated every
  property on every page in it; `name` and `library` are now quoted.
- **The graph page could break on unusual text.** The title was inserted into HTML
  unescaped, and a `</script>` sequence inside a variable description would terminate the
  embedded data block. The title is HTML-escaped and the embedded JSON uses unicode escapes.
- **Indicator expressions were split on the raw substring `AND`**, cutting `GRAND_TOTAL`
  into `GR` and `_TOTAL`, and ignoring `OR`. One shared helper now uses word boundaries.
- A literal `None` description or data type was blanked on load; only real empty values and
  `NaN` are normalised now.
- A variable description containing a newline no longer breaks the page blockquote.
- `extract-rci --force` did nothing: an implausible header still parsed and exited 0. It now
  exits 2 without `--force`, and also exits 2 when nothing parses.

### Changed

- **The generated vault no longer depends on the Dataview plugin.** The overview and
  indicator pages contain tables computed at build time; `indicators` is also written to the
  frontmatter. A query over a field that no page wrote used to render as an empty table.
- `--rci` / `--workspace` now do something: `extract-rci` defaults to
  `<workspace>/VAR_LIST.RCI`, and `snapshot` uses the file to enrich descriptions where it
  has a longer text than the database.
- New `--charset` flag (and `IsqlRunner(charset=...)`) for installations whose `isql`
  connection charset is not UTF-8; undecodable output now warns instead of silently planting
  U+FFFD.
- `PROPHET_OUTPUT_DIR` / `PROPHET_VAULT_DIR` now supply the defaults for `--out` / `--vault`
  (previously stored but never read).
- Packaging: PEP 639 `license = "MIT"` and `license-files`, dynamic version sourced from
  `prophet_vault.__version__`, `py.typed` shipped, `[project.urls]`, and `templates` declared
  as a package so setuptools no longer warns.
- `ruff` added to the `dev` extra, the code base formatted with it, and CI now runs
  `ruff check` / `ruff format --check`, builds a wheel and asserts the template and version
  inside it.
- `SECURITY.md`, `THIRD_PARTY_NOTICES.md`, Dependabot config, and issue/PR templates added.
- Documentation corrected where it disagreed with the code: the RCI data-flow, the
  idempotency claim, Dataview usage, `--force`, Windows scope, determinism of the demo, the
  environment-variable table, the snapshot file list, and the production indicator count.
- The README badge is now the real GitHub Actions badge instead of a hand-written claim.

## [0.1.0] - 2026-11-24

First public release: the reusable core extracted from an internal Prophet
knowledge-base tool that had been running against a ~15,000-variable production model.

### Added

- **Package `prophet_vault`**, standard library only, Python 3.10+.
- **`rci.py`** - tolerant parser for the undocumented `VAR_LIST.RCI` binary variable index,
  including the `[category][control byte]` record prefix, name validation and description
  sanity checks.
- **`isql.py`** - `isql.exe` subprocess runner plus parsers for fixed-width `SELECT` output
  and `SET BLOBDISPLAY 0` formula dumps, with per-library batching to avoid pipe truncation.
- **`extract.py`** - the six PRW queries that matter, library mapping (`Summary` for shared
  variables), and dependency derivation by candidate intersection.
- **`formulas.py`** - Prophet tokeniser, reserved-word sets, whitespace-insensitive formula
  hashing.
- **`snapshot.py`** - the eight-file CSV/JSON snapshot contract, stable across versions.
- **`diff.py`** - five-dimension snapshot comparison (added, deleted, description, formula,
  indicators, references) with JSON and Markdown reports.
- **`vault.py`** - Obsidian rendering: library/initial folder split, wikilinks, Mermaid
  previews, Dataview overview, per-variable `version_history`, and incremental updates that
  re-render changed pages while merging history.
- **`graph.py`** - single-file dependency graph (ECharts) that renders a focus subgraph at
  depth 1-3, colours by library, and can inline ECharts for offline use.
- **`demo.py`** - deterministic synthetic model generator (146 variables, four libraries),
  used by the docs and the test suite. No Prophet installation required.
- **CLI** - `demo`, `extract-rci`, `schema`, `snapshot`, `diff`, `build-vault`,
  `update-vault`, `graph`.
- **120 tests**, fully offline.
- Documentation: architecture, snapshot data model, PRW extraction, RCI format, dependency
  graph, Obsidian vault, monthly update procedure, troubleshooting.

### Changed relative to the internal original

- Replaced `pandas` with the standard library (`csv`), so the package installs with no
  dependencies.
- De-duplicated the `isql` subprocess and parsing code that existed twice (once in the
  snapshot script, once in the extraction script).
- `update-vault` re-renders changed pages from the new snapshot and merges
  `version_history`, replacing the previous approach of patching Markdown sections in place.
- Regenerating a vault now refuses to delete a non-empty folder unless `--force` is given.
- Graph node colours come from the variable's library instead of a hard-coded list of
  model-specific name prefixes.
- Removed the non-functional "tree" layout; added a radial layout for hub-and-leaf
  neighbourhoods.
- Reference extraction treats the reserved-word list as keywords and built-ins; the previous
  heuristic noise words are available as `formulas.LEGACY_NOISE_WORDS`.
