# Troubleshooting

## `isql.exe not found`

```
error: No isql.exe path configured. Pass --isql, or set PROPHET_ISQL_PATH ...
```

Find the copy that ships with your installation - typically
`.../ProphetServer/ProphetSuite/Firebird_3_0/isql.exe` - and either pass `--isql` or set the
environment variable:

```powershell
$env:PROPHET_ISQL_PATH = "C:/Prophet/ProphetServer/ProphetSuite/Firebird_3_0/isql.exe"
```

Mac/Linux users: there is no supported path, because the database format and the tool are
Windows-only.

## `Statement failed, SQLSTATE = 28000` / login rejected

The SYSDBA credential is not the default. Set:

```powershell
$env:PROPHET_ISQL_USER = "SYSDBA"
$env:PROPHET_ISQL_PASS = "<your password>"
```

## `unsupported on-disk structure` or an empty result with no error

This is the failure mode that motivates shelling out to `isql` in the first place, but it
can still appear if the `isql.exe` you pointed at belongs to a *different* Firebird
version than the one that created the `.PRW`. Use the `isql.exe` inside the same
installation as the model.

## Descriptions come out as mojibake

`isql` writes in the console code page on some installations. Construct the runner with the
matching encoding:

```python
from prophet_vault.isql import IsqlRunner
runner = IsqlRunner(isql_path=..., database=..., encoding="cp936")
```

The CLI uses UTF-8 with `errors="replace"`, so you get replacement characters rather than an
exception. That is intentional: a snapshot with three odd characters beats no snapshot.

## The snapshot stops early / formulas are missing at the end

Symptom: `formulas.csv` has far fewer rows than expected, and the missing ones are all from
the last library.

Cause: one giant blob result overflowing the Windows pipe buffer. The current code batches
per library for exactly this reason. If you still hit it on an unusually large library,
lower the batch size by adding a `BUSINESSDBID` filter to `SQL_FORMULAS_FOR_LIBRARY`.

## `VaultError: ... is not empty`

`build-vault` deletes the target folder, so it refuses to run against anything that already
has content. Either pass `--force` (deliberately destructive) or point `--vault` at a new
folder. To update an existing vault without losing history, use `update-vault`.

## Wikilinks in Obsidian point at the wrong page or show as unresolved

Three causes, in order of likelihood:

1. **Two variables with the same name.** Cannot happen from one snapshot (names are
   unique), but can happen if two vaults are merged. Obsidian resolves by file name, so keep
   one vault per model.
2. **A variable page was moved by hand** into another library folder. Wikilinks still
   resolve by name, so this is harmless - but the next `update-vault` will write the page
   back to its canonical folder, leaving a stale copy behind. Delete the moved file.
3. **Obsidian's link settings.** The generated `.obsidian/app.json` sets
   `"newLinkFormat": "shortest"`. If you changed it to "absolute path in vault", existing
   links still resolve; new ones written by the tool remain name-based.

## The HTML graph shows "ECharts could not be loaded"

The page loads ECharts from a CDN. On a machine without internet access, inline the
library:

```bash
curl -L https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js -o echarts.min.js
python -m prophet_vault graph --snapshot output/snapshots/2026-08 -o graph.html --echarts echarts.min.js
```

## The graph is slow, or a hub node fills the canvas

Use depth 1 for hubs; depth 3 on a variable with 900 consumers is inherently dense. Above
300 nodes the renderer keeps the highest-degree neighbours, so raising `--max-nodes` helps
only up to the point where the canvas stops being readable.

## `schema` works but `snapshot` fails on a table name

Your Prophet version renamed a table or column. Run `schema` to list what exists, then adjust
the `SQL_*` constants at the top of `prophet_vault/extract.py`. The parsers tolerate renamed
aliases where possible (`_get(row, "NAME", "VAR_NAME")`), so usually only a table name needs
changing.

## Tests fail after upgrading Python

The package uses `X | Y` type syntax, so it needs 3.10+. Run:

```bash
python -m pytest -q
```

and open an issue with the Python version and the failing assertion.

## Nothing in the vault is marked as changed after a real model update

Check, in order:

1. Are the two snapshot folders actually different? `diff` prints totals for both.
2. Was the snapshot taken from the same `.PRW`? `metadata.json` records the source path.
3. Do the `formula_hashes.csv` files differ? If not, the model genuinely did not change -
   or the formula dump silently returned nothing (see the truncation section above).
