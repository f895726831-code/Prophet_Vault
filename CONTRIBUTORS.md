# Contributors

Prophet Vault was built in two stages. Both are recorded here, because the *roles* matter
more than the commit graph: this repository is documentation tooling for a regulated
subject, and every artefact in it was specified and accepted by an actuary.

## Maintainer

**[@f895726831-code](https://github.com/f895726831-code)** - problem definition, Prophet
model knowledge, review and acceptance of every output. Accountable for the content.

## Original implementation - Claude Code

The internal tool this repository is extracted from was written with **Claude Code** (the
VS Code AI coding agent), iteratively, against a live Prophet workspace:

- `isql`-based extraction from the Firebird `.PRW` (fixed-width and blob output parsing)
- reverse engineering of the undocumented `VAR_LIST.RCI` binary format
- the Obsidian vault generator (library/initial folder split, wikilinks, Mermaid, Dataview)
- the ECharts dependency-graph page and the snapshot/diff pipeline

## Repository packaging - DeepSeek Harness

This public repository was assembled with **DeepSeek Harness**:

- restructuring the one-off scripts into the `prophet_vault` package and CLI
- removing model-specific code and paths, keeping the reverse-engineering knowledge in `docs/`
- the offline test suite (152 tests), the synthetic demo generator, and the bilingual README
- fixing defects found while packaging: indicator link depth, duplicate `isql` parsing,
  in-place Markdown patching, platform-dependent line endings

## Why the AI agents are credited by role

GitHub's contributor graph counts commit authors who have a linked GitHub account. The two
agents above have no accounts, so they are credited here instead - along with the specific
work each produced. If you have contributed and want to be listed, open a pull request that
adds yourself to this file; contributors are also listed automatically on the repository's
[contributors graph](https://github.com/f895726831-code/Prophet_Vault/graphs/contributors).
