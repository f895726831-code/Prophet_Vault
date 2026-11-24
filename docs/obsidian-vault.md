# The Obsidian vault

## Why Obsidian

The requirement is "browse a 15,000-variable model and follow its links". That is a
knowledge base, and Obsidian is the cheapest good one:

* plain Markdown on disk - reviewable in git, readable in any editor, no lock-in;
* `[[wikilinks]]` resolve by file name, so reorganising folders never breaks links;
* backlinks, search and graph view come free;
* Dataview turns frontmatter into live tables;
* no server, no licence, no internet.

## Layout

```
<vault>/
├── Variables/
│   ├── Summary/A/ ... Z/_/
│   ├── Conventional/A/ ... Z/_/
│   ├── Unit_Linked/A/ ... Z/_/
│   └── IFRS17/A/ ... Z/_/
├── Indicators/
│   └── WITH_PROFIT.md
├── _Index/
│   ├── 00-Overview.md
│   └── CHANGELOG.md
└── .obsidian/
    ├── app.json
    └── core-plugins.json
```

Two levels of nesting: **library**, then **initial letter**. One flat folder holding
15,000 files is slow in Obsidian, unusable in Explorer, and produces a filesystem-hostile
git diff. Library first because that is how actuaries think about the model; initial letter
second because it keeps folders to a few hundred entries.

Variables that exist in more than one library are filed under `Summary`, so every variable
has exactly one page and therefore one wikilink target.

## Page schema

### Frontmatter

```yaml
---
name: AGG_004
description: "Aggregated result 4"
datatype: 0
num_dimensions: 0
is_array: 0
library: Conventional
tags: [variable]
version_history:
  - date: "2026-03-01"
    change: "FORMULA_CHANGED"
    old: "FLOW_024 + FLOW_010"
    new: "FLOW_024 + FLOW_010 + FLOW_033"
---
```

| Key | Used by |
|---|---|
| `description` | Dataview tables, search |
| `library` | Dataview grouping, folder placement |
| `tags` | `variable`, plus `deprecated` once removed from the model |
| `version_history` | Change trace on the page itself; newest first, capped at 50 entries |

Values are quoted and escaped by `yaml_string()`, so a description containing `"` or `\`
cannot break the frontmatter.

### Body sections

| Section | Content |
|---|---|
| `## Definition` | One `prophet` fenced block per formula block |
| `## Indicators` | Links to indicator pages |
| `## References` | `[[wikilinks]]` to upstream variables |
| `## Referenced by` | `[[wikilinks]]` to downstream variables |
| `## Dependency graph` | Mermaid `graph LR`, capped at 10 edges per direction |

The Mermaid block is capped because a hub with 900 consumers would otherwise generate a
diagram Markdown renderers refuse to draw. It is a preview; the HTML graph is for
exploration.

## Indicator pages

One page per indicator name, containing its code and either the list of variables gated by
it or, when the list is empty, a Dataview query that finds them:

````markdown
```dataview
LIST
FROM "Variables"
WHERE contains(indicators, "IFRS17")
```
````

Note the caveat: `indicators` is not a frontmatter list in the generated pages - the
indicator names live in the body. Keep the explicit list (as generated) unless you also
promote indicators into frontmatter; the explicit list is accurate, the query is a
convenience.

## Overview page

`_Index/00-Overview.md` carries counts per library plus two Dataview tables: the 50 most
referenced variables, and the full variable table sorted by name. It is regenerated on
every build and every update, so its numbers never drift.

## Change history

`_Index/CHANGELOG.md` receives one section per update, inserted newest-first directly
after the title. Each section shows the diff summary table, the added variables and the
changed formulas.

At page level, `version_history` records the same events per variable. That duplication is
deliberate: the changelog answers "what happened this month", the page answers "what
happened to this variable".

## Update semantics

`update-vault` re-renders pages from the new snapshot rather than patching Markdown in
place, and merges the existing `version_history` into the new page:

| Diff says | Result |
|---|---|
| added | page created, `change: "NEW"` |
| formula changed | page re-rendered, `change: "FORMULA_CHANGED"` with before/after text |
| description / indicator / references changed | page re-rendered with the corresponding entry |
| deleted | page kept, `deprecated` tag added, warning callout, `change: "DEPRECATED"` |
| unchanged | untouched |

Why full re-render: the previous version replaced sections by searching for `##` headings.
That works until somebody edits a page by hand, at which point the heading is renamed and
the updater either fails silently or duplicates content. Re-rendering from the snapshot is
idempotent, and the only state that must survive - the history - is parsed back out of the
frontmatter.

Deleted variables keep their page on purpose. A variable removed from the model is exactly
the thing an auditor asks about six months later; deleting the page destroys that answer.

## Safety

* `build-vault` refuses to write into a non-empty folder without `--force`, because it
  deletes the folder first.
* `update-vault` copies the vault to `<vault>.bak.<timestamp>` before writing (disable with
  `--no-backup`).
* Nothing outside the vault folder is touched.
