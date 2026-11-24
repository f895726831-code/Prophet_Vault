# Architecture

## One diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Prophet workspace (read-only, on the actuary's machine)                  │
│                                                                          │
│  PROPHET.PRW            VAR_LIST.RCI  (optional)                          │
│  Firebird embedded DB   binary variable index                            │
└──────────┬──────────────────────┬────────────────────────────────────────┘
           │                      │
           │ isql.exe             │ binary scanner (extract-rci,
           ▼                      │ and snapshot --rci / --workspace)
   ┌───────────────┐      ┌───────▼───────┐
   │ isql.py       │      │ rci.py        │
   │ fixed-width   │      │ name/category │
   │ + BLOB parser │      │ /description  │
   └───────┬───────┘      └───────┬───────┘
           │                      │ longer description wins
           ▼                      ▼
   ┌────────────────────────────────────┐
   │ extract.py                         │  tables -> ModelData
   │ queries, library mapping,          │  formulas.py: tokenise + hash
   │ reference derivation               │  merge_rci_descriptions()
   └───────────────┬────────────────────┘
                   ▼
   ┌────────────────────────────────────┐
   │ snapshot.py                        │  ModelData -> 8 CSV/JSON files
   │ Snapshot.build / save / load       │
   └───────┬────────────────────┬───────┘
           │                    │
           ▼                    ▼
   ┌──────────────┐     ┌──────────────────────┐
   │ diff.py      │     │ vault.py   graph.py  │
   │ compare      │     │ Obsidian   HTML      │
   │ report       │     │ pages      single file│
   └───────┬──────┘     └──────────────────────┘
           ▼
   ┌──────────────────────┐
   │ vault.py apply_diff  │  incremental update
   └──────────────────────┘
```

`VAR_LIST.RCI` is optional: the snapshot is complete without it, and the RCI parser is
also usable on its own via `extract-rci`.

## Layers and why they are separate

| Layer | Module | Responsibility | Depends on |
|---|---|---|---|
| I/O primitives | `isql.py`, `rci.py` | Turn vendor file formats into Python values | stdlib |
| Domain extraction | `extract.py`, `formulas.py` | Know which tables, columns and keywords matter | I/O primitives |
| Versioned state | `snapshot.py` | The stable, documented data contract | domain extraction |
| Comparison | `diff.py` | What changed between two states | snapshot |
| Presentation | `vault.py`, `graph.py` | Render state for humans | snapshot, diff |
| Orchestration | `cli.py`, `demo.py` | Wire it together, generate fixtures | everything |

The important boundary is **snapshot ↔ everything else**. Everything upstream of a
snapshot is Prophet-specific; everything downstream of it is generic. That is what makes
it possible to add a Moses, AXIS or RAFM adapter by writing one extractor that produces
the same eight files, without touching diff, vault or graph code.

## Execution model

* **No daemon, no server, no database.** Every command is a one-shot process.
* **Streaming where it matters.** Formulas are dumped one library at a time because a
  single 26,000-row blob result overflows Windows pipe buffers and gets truncated (see
  [prw-extraction.md](prw-extraction.md)).
* **Idempotent page bodies.** `build-vault` refuses to overwrite a non-empty folder unless
  `--force`; `update-vault` re-renders a changed page from the snapshot, so applying the
  same diff twice leaves the *body* identical. What does accumulate is the audit trail:
  one `version_history` entry and one `CHANGELOG.md` section per run.
* **No hidden state.** Everything the tool knows is in the snapshot folder it was given.
  A page body is a pure function of (snapshot, diff), and the only state carried forward is
  the history written into the frontmatter.

## Extension points

1. **New Prophet version with different table names** - edit the `SQL_*` constants in
   `extract.py`. `python -m prophet_vault schema` prints the live table list.
2. **New modelling platform** - implement a function returning
   `extract.ModelData` (variables, formulas, indicators, dimensions, library map,
   libraries) and call `Snapshot.build(...)`. Everything downstream works unchanged.
3. **Different knowledge-base target** - `vault.render_variable_page` is a plain
   function from data to Markdown; a Confluence or Docusaurus renderer can sit next to
   it.
4. **Different graph front end** - `graph.build_graph` returns a documented JSON payload
   (`docs/dependency-graph.md`); only the template needs replacing.
5. **Extra change dimensions** - add a list to `diff.Diff`, fill it in `compare`, render
   it in `as_markdown`. The updater consumes the same object.

## Error handling policy

* Corruption in an input file degrades to *fewer parsed rows*, never to a crash: a
  misaligned `VAR_LIST.RCI` scan stops adding entries, a malformed `isql` line is
  skipped.
* Configuration errors are explicit and early: `Settings.require_prw()` raises with the
  environment variable name to set.
* Destructive operations ask first: regenerating a vault requires `--force`, and
  `update-vault` copies the vault to `<vault>.bak.<timestamp>` before writing.
