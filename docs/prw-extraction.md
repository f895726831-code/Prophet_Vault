# Reading a Prophet model out of a Firebird `.PRW`

## What a `.PRW` is

A Prophet workspace stores its model in `PROPHET.PRW`, which is a **Firebird embedded
database** - the same engine as Firebird Server, with no server process. Whoever opens
the file needs a matching client library and the SYSDBA credentials the installer used
(`sysdba` / `masterkey` by default).

## Why not a Python Firebird driver

The obvious approach is `fdb.connect(...)` and `pandas.read_sql(...)`. In practice:

* A `.PRW` was created by whichever Firebird build the Prophet version shipped: 2.5 for
  older releases, 3.0 for newer ones. Their on-disk format (ODS) differs.
* A Python driver links, at import time, against one `fbclient.dll`. Point it at the
  other ODS and you get "unsupported on-disk structure" or a silent partial read.
* Installing a second Firebird client just to read one file is not something an actuary
  should have to do on a corporate laptop.

`isql.exe` that sits inside the Prophet installation (`.../ProphetSuite/Firebird_3_0/`)
is guaranteed to match the file, because it is the one that wrote it. So the toolkit
shells out to it and parses text.

Trade-off: parsing text is uglier than reading rows. It is also the only approach that
kept working across every Prophet version we touched, including on machines where
`pip install fdb` failed.

## Invocation

```python
command = [isql, "-q", "-u", user, "-p", password, prw_path]
result = subprocess.run(
    command,
    input=sql_script,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
```

* `-q` suppresses the banner, which would otherwise appear in stdout.
* `-u` / `-p` take the SYSDBA credentials.
* The SQL goes in through **stdin**, terminated by `EXIT;`.

Two quirks matter:

1. **One statement per line or the prompt breaks.** `isql` reads stdin statement by
   statement, so a newline inside a statement starts a new statement. Ordinary queries are
   therefore flattened onto one line by `flatten_sql()`, and only blob dumps are sent as a
   raw multi-line script.
2. **Encoding.** Output is decoded as UTF-8 with `errors="replace"`. Some installations
   use a different connection charset; pass `--charset WIN1252` (or `--charset UTF8`) on the
   CLI, or `IsqlRunner(charset=...)` from Python. When decoding still hits undecodable
   bytes, the runner warns instead of silently planting U+FFFD in a description.

## Parsing `SELECT` output

`isql` prints fixed-width columns:

```
NAME                         DESCRIPTION
============================ ==============================
AGE_AT_ENTRY                 Age at entry of the policy
NET_CF                       Net cash flow of the period
```

`parse_fixed_width()`:

1. drops blank lines, `SQL>` / `CON>` prompts, `Database:` banners and `===` rules;
2. treats the first surviving line as the header and reads column start offsets from it;
3. slices each data line by those offsets, letting the last column run to end of line so
   free text keeps its spaces;
4. drops rows whose values are all empty.

**Known limitation:** a value wider than its header column is wrapped onto a continuation
line, which fixed-width text cannot represent. Keep projections narrow, and if you need a
long description, prefer the `VAR_LIST.RCI` descriptions or project it as the last column.

## Parsing formula BLOBs

`VARIABLEEXPR` is a BLOB. Selecting it normally prints `b2:12345` instead of content. The
trick is the `SET BLOBDISPLAY 0;` directive, which makes `isql` print the blob inline
between two rules:

```
VAR_NAME        INDICATOREXPR       VARIABLEEXPR
=============== =================== ============
NET_CF          ALWAYS              b2:d1
============================================
IF t = 0 THEN
  0
ELSE
  PREMIUM(t) - CLAIMS(t)
============================================
```

`parse_blob_records()` walks that structure as a small state machine:

| State | Trigger | Action |
|---|---|---|
| `scan` | line contains `b2:` | slice name (0..42) and indicator (42..122), enter `blob_start` |
| `blob_start` | line starts with `===` | enter `blob_content` |
| `blob_content` | line starts with `===` | flush record, back to `scan` |
| `blob_content` | anything else | append to the formula |

The column widths (42 / 122) are configurable arguments. The indicator slice is cut at the
`b2:` marker rather than at a fixed offset, which keeps it correct on narrower layouts.

## Batching, and why it is not optional

A production model has ~26,000 formula blocks, some of them a few hundred lines. Dumping
them in one result set overflows the Windows pipe buffer: `subprocess` returns a truncated
string, and the last thousand formulas silently disappear.

`extract_formulas()` therefore:

1. asks for the distinct `BUSINESSDBID` values (one per library);
2. dumps formulas one library at a time, with a 120 s timeout per batch.

Batches are also where the `b2:` counter resets, which keeps each parse independent.

## Schema discovery

Table and column names are stable in our testing but are not a public API. When a query
fails on an unfamiliar version:

```bash
python -m prophet_vault schema --isql <isql> --prw <PRW>
```

prints the user tables, from:

```sql
SELECT rdb$relation_name FROM rdb$relations
WHERE rdb$system_flag = 0 AND rdb$view_blr IS NULL ORDER BY 1;
```

The six queries that matter live at the top of `prophet_vault/extract.py`:

| Constant | Tables |
|---|---|
| `SQL_VARIABLES` | `VARIABLES` |
| `SQL_INDICATORS` | `INDICATOR` |
| `SQL_LIBRARIES` | `BUSINESSDATABASE` |
| `SQL_VARIABLE_LIBRARIES` | `VARIABLES` + `VARIABLEINFO` |
| `SQL_FORMULAS_FOR_LIBRARY` | `VARIABLEDEFN` + `VARIABLEINFO` + `VARIABLES` |
| `SQL_DIMENSIONS` | `VARDIMLINK` + `VARIABLES` + `DIMENSIONS` |

## Library mapping

`BUSINESSDBID` identifies a Prophet library. A variable may appear in several libraries;
`build_library_map()` assigns it to the single library that owns it, or to `Summary` when
it appears in more than one. That decision matters because the vault puts each page in
exactly one folder (Obsidian wikilinks resolve by file name, so a duplicate page would make
links ambiguous).

## Credentials

`sysdba` / `masterkey` is the Firebird default and almost never changed for an embedded
`.PRW`. Override with `PROPHET_ISQL_USER` / `PROPHET_ISQL_PASS` if your installation sets a
different one. Nothing is stored on disk.
