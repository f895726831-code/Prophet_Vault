# The monthly update procedure

A model change happens every month: new assumptions, redefined formulas, variables added or
retired. The point of this pipeline is that the change becomes **reviewable** - a JSON diff
and a Markdown report that a second actuary can read without opening Prophet.

## The cycle

```
month N                                        month N+1
snapshot/<N>  ──┐                              snapshot/<N+1>
                ├──► diff ──► diff.json  ──►   report.md   ◄── reviewed / filed
vault          ─┘                │
                                 └──► update-vault ──► vault (changed pages only)
                                                       CHANGELOG.md (newest first)
```

## Step by step

### 1. Take the new snapshot

```bash
python -m prophet_vault snapshot \
  --isql "C:/Prophet/ProphetServer/ProphetSuite/Firebird_3_0/isql.exe" \
  --prw  "D:/models/PROPHET.PRW" \
  --label 2026-09
```

Writes `output/snapshots/2026-09/`. Use a sortable label: `YYYY-MM` or
`YYYY-MM_<workspace>` when several models exist side by side. `graph` without `--snapshot`
picks the newest label alphabetically, so the naming convention is functional, not
cosmetic.

Expect minutes, not seconds, on a large model: the formula dump is one `isql` call per
library.

### 2. Compare

```bash
python -m prophet_vault diff \
  --old output/snapshots/2026-08 \
  --new output/snapshots/2026-09 \
  --output output/diffs/2026-09_diff.json
```

Produces `2026-09_diff.json` (machine readable) and `2026-09_diff_report.md` (reviewable).

The two files have deliberately different policies: the JSON is **complete** - it is what
`update-vault` replays, so every changed variable appears - while the Markdown report is
capped at 20-50 entries per section to stay readable. The `summary` counts in both are
always complete. If you hand-edit the JSON, `update-vault` warns when a section lists fewer
entries than its summary claims.

### 3. Review before touching the vault

Read the report. The shape to look for:

| Signal | Meaning |
|---|---|
| Many `added` at once | A new product or a library imported wholesale |
| `deleted` clustered around one prefix | A feature retired |
| `formula_changed` with only whitespace differences | Should not happen - the hash normalises whitespace, so investigate |
| `refs_changed` on a widely used variable | The real impact assessment: follow `added`/`removed` names |
| `indicator_changed` on many variables | Reporting-basis switch, usually intentional once a year |

Nothing has been modified at this point; the vault is still on the old model.

### 4. Apply the delta

```bash
python -m prophet_vault update-vault \
  --diff output/diffs/2026-09_diff.json \
  --vault my_vault \
  --snapshot output/snapshots/2026-09
```

Only changed pages are re-rendered, and pages whose variable moved to another library are
relocated. The vault is copied to `my_vault.bak.<timestamp>` first; `CHANGELOG.md` gains a
section, and each touched variable page gains a `version_history` entry.

### 5. Commit

Keep the vault in git (or another VCS):

```bash
git add my_vault output/snapshots/2026-09 output/diffs/2026-09_diff.json
git commit -m "model update 2026-09: +7 variables, 37 formula changes"
```

Because pages are Markdown, the commit diff *is* the review artefact. Keep snapshots out of
git if they are large - they are reproducible from the `.PRW`, which should be archived
separately.

## Alternative: full rebuild

If the vault is disposable, skip the diff:

```bash
python -m prophet_vault build-vault --snapshot output/snapshots/2026-09 --vault my_vault --force
```

You lose `version_history` and the changelog, which is the main reason to prefer
`update-vault` after the first build.

## Rollback

Three independent options, in increasing cost:

1. **Vault** - restore the automatic backup: `mv my_vault.bak.<stamp> my_vault`.
2. **Snapshot** - snapshots are never modified, so `build-vault` from the previous one
   restores the old knowledge base exactly.
3. **Diff** - re-apply an older diff against an older snapshot if a change was applied out
   of order.

## Handling several workspaces

Keep one snapshot tree per model and one vault per model:

```
output/snapshots/BP_A/2026-09/
output/snapshots/BP_B/2026-09/
vaults/BP_A/
vaults/BP_B/
```

Comparing across models is meaningful for shared libraries but noisy elsewhere; if you need
it, diff two snapshots from different trees directly - the tool does not care where they
live.

## Automation

The four commands are non-interactive and return non-zero on failure, so a scheduler can run
them:

```powershell
$ErrorActionPreference = "Stop"
python -m prophet_vault snapshot --prw $env:PROPHET_PRW_PATH --label (Get-Date -Format yyyy-MM)
python -m prophet_vault diff --old $previous --new $latest
python -m prophet_vault update-vault --diff $diff --vault $vault --snapshot $latest
```

Add a mail step on the generated report. Do **not** auto-commit the vault without review
if the model is subject to change control.
