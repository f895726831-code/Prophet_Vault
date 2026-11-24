# Data model: the snapshot contract

A snapshot is a folder of plain files. It is the only interface between extraction and
presentation, so it is documented here as a contract rather than as an implementation
detail.

```
snapshots/<label>/
├── variables.csv
├── formulas.csv
├── indicators.csv
├── dimensions.csv
├── formula_hashes.csv
├── references.csv
├── library_map.csv
└── metadata.json
```

All CSV files are UTF-8 **with BOM** (`utf-8-sig`) so Excel opens Chinese descriptions
correctly. Readers strip the BOM. Missing values are written as empty cells; the loader
also normalises the literal strings `nan` and `None` to empty.

## `variables.csv`

| Column | Type | Meaning |
|---|---|---|
| `NAME` | string | Variable name, upper case, unique |
| `DESCRIPTION` | string | Free text, may be empty |
| `DATATYPE` | string | Prophet data type code |
| `NUMDIMENSIONS` | string | Number of dimensions |
| `ISARRAY` | `0`/`1` | Whether the variable is an array |
| `LIBRARY` | string | Owning library, or `Summary` when shared |

## `formulas.csv`

One row per formula block. A variable gated by three indicators has three rows.

| Column | Type | Meaning |
|---|---|---|
| `VAR_NAME` | string | Variable the block defines |
| `FORMULA` | string | Prophet formula text, newlines preserved |
| `INDICATOREXPR` | string | Indicator condition for this block, e.g. `IFRS17 AND NOT SOLVENCY` |

## `indicators.csv`

| Column | Type | Meaning |
|---|---|---|
| `NAME` | string | Indicator name |
| `DESCRIPTION` | string | Free text |
| `CODE` | string | Prophet indicator code |

## `dimensions.csv`

| Column | Type | Meaning |
|---|---|---|
| `VAR_NAME` | string | Variable |
| `DIM_NAME` | string | Dimension name |
| `ARRAYINDEX` | string | Position along the dimension |

## `formula_hashes.csv`

| Column | Type | Meaning |
|---|---|---|
| `VAR_NAME` | string | Variable |
| `FORMULA_HASH` | string | First 12 hex chars of `md5` over the sorted, whitespace-normalised formula set; empty when the variable has no formula |

The hash is order- and indentation-insensitive. Two snapshots with the same hash for a
variable are treated as "formula unchanged".

## `references.csv`

| Column | Type | Meaning |
|---|---|---|
| `VAR_NAME` | string | Variable |
| `REFERENCES` | string | `\|`-separated names that its formulas read |

Only names that exist in `variables.csv` appear here; unresolved identifiers are dropped
at extraction time.

## `library_map.csv`

| Column | Type | Meaning |
|---|---|---|
| `VAR_NAME` | string | Variable |
| `LIBRARY` | string | Folder-owning library (`Summary` if shared) |
| `LIBRARIES` | string | `\|`-separated list of every library containing it |

## `metadata.json`

```json
{
  "label": "2026-08",
  "source": "D:/models/PROPHET.PRW",
  "created_at": "2026-08-28T16:05:11+08:00",
  "total_variables": 14539,
  "total_formulas": 25721,
  "total_indicators": 553,
  "total_dimensions": 2529,
  "variables_with_formulas": 12721,
  "variables_with_refs": 12724,
  "libraries": { "2": "Summary", "3": "Conventional", "27": "IFRS" }
}
```

`libraries` maps `BUSINESSDBID` to its name; it is kept for provenance, not for
rendering.

## Compatibility

The layout above matches the snapshots produced by the original internal tool, so
existing snapshot folders can be used directly. Additive changes (new columns) are
backwards compatible because the loader reads by column name and ignores unknown ones.
