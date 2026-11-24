# The `VAR_LIST.RCI` binary format

## Why bother

`VAR_LIST.RCI` is a compact index of every variable in a workspace: name, category and a
human description. The `.PRW` database has descriptions too, but they are frequently
shorter than the ones in the RCI file, and the RCI file is readable when the database is
locked, being rebuilt, or on a machine where the Firebird client is unavailable.

The format is undocumented. What follows is a reverse-engineered description, good enough
for a tolerant parser, and explicitly **not** a specification.

## Layout

```
offset  size      content
0       4         magic: ff ff 07 03
4       4         file size in bytes, little endian
8       4         entry count, little endian
12      28        reserved (zero)
40      n * 4     table of contents: section offsets, little endian, 0-terminated
...               sections
```

Each section is a stream of records with no stored length:

```
[ name field: 32 bytes, NUL padded ]
[ optional zero padding ]
[ description: ASCII, NUL terminated ]
```

Some records begin with a two-byte prefix instead of a bare name:

```
[ 'A'..'Z' category byte ][ control byte, 1..31 ][ name ... ]
```

### Category codes

Observed category bytes, with the meanings Prophet uses elsewhere in the UI:

| Byte | Meaning |
|---|---|
| `A` | general information |
| `B` | transactions and benefits |
| `M` | interest rates |
| `O` | commission and expenses |
| `P` | projection parameters |
| `T` | counters |
| `U` | revenue accounts |
| `V` | reserves |
| `Y` | discounting |
| `?` | not present in this record |

Treat them as hints. Nothing downstream depends on them: the vault uses the `.PRW`
library mapping, not the category.

## Parsing strategy

Because record boundaries are not stored, the parser **scans**:

```
pos = 0
while pos <= len(data) - 32:
    field = data[pos : pos + 32]
    nul = field.find(0)
    if nul == -1: pos += 1; continue

    name, category = split_category(field[:nul])
    if not is_valid_name(name): pos += 1; continue

    start = pos + 32
    while data[start] == 0: start += 1          # skip padding
    description = read_until_nul(data, start, limit=200)

    if description and not looks_like_identifier(description):
        record(name, category, description)
        pos = end_of_description + 1
    else:
        pos += 1
```

### Why the extra checks

* **Name validation** (`[A-Z][A-Z0-9_]{1,39}`, length 2..40) rejects whatever padding,
  TOC bytes and section headers the scan lands on. Without it, the scanner produces
  thousands of garbage "names" made of control characters.
* **Description sanity** - a description that starts with an upper-case letter, contains
  an underscore and is at most 40 characters long is almost always the *next record's*
  name, meaning the scan has lost alignment. Rejecting it and advancing one byte recovers
  quickly; accepting it corrupts the record.
* **Longest description wins** - the same name can be found more than once when the scan
  walks into a misaligned position. Keeping the longest description yields the complete
  text.

### Verifying a parse

The header carries an entry count. Compare it with the number of parsed records:

```python
from prophet_vault.rci import read_header, parse_file, to_rows

path = "VAR_LIST.RCI"
header = read_header(open(path, "rb").read(40))
entries = parse_file(path)
print(header.entry_count, len(entries))
```

* Within a few percent: normal. Some records have no description, or a description the
  heuristic rejects, and a handful of entries are workspace bookkeeping.
* Wildly different (say 5x): the file is not the format described here - check the magic
  bytes first.

## Failure modes

| Symptom | Cause | What to do |
|---|---|---|
| `does not look like VAR_LIST.RCI` | Not a `VAR_LIST.RCI`, or a different vendor version | Pass `--force` only if you know the file is right - without it the command exits 2 and writes nothing |
| Empty output | Scan found nothing valid | Check the file is not encrypted; see the `PROPHENC` note below |
| Names with control characters | Scanner lost alignment | Report the file; the validator usually catches these |
| Descriptions in the wrong language | Correct - the file stores what the modeller wrote | - |

## What is *not* readable

Some workspace metadata lives in `workspace_files/*.xml` encrypted with a vendor routine
(`PROPHENC`). It is not parsed here, and no attempt is made to defeat it: everything the
toolkit needs is available in plain form in the `.PRW` and `.RCI` files.

## Using the parser on its own

```bash
python -m prophet_vault extract-rci --rci path/to/VAR_LIST.RCI --out output
```

writes `output/variables_phase1.csv` with columns `name`, `category`, `description`,
`source`. `--rci` can be omitted when `--workspace` (or `PROPHET_WORKSPACE_DIR`) points at
the folder containing the file; the command then exits 2 if no file is found or nothing
parses.

`snapshot --rci PATH` (or the same workspace variable) uses the file to *enrich* variable
descriptions: the longer of the database and RCI description wins, and the command reports
how many variables it replaced.
