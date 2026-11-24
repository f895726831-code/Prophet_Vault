# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
