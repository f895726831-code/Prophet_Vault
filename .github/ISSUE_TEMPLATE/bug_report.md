---
name: Bug report
about: Something parsed, rendered or updated incorrectly
labels: [bug]
---

## What happened

<!-- One or two sentences. -->

## Reproduction

```bash
# the exact commands, with paths redacted
python -m prophet_vault ...
```

## Expected

## Actual

<!-- Error output, or the relevant part of a generated page. Redact model content. -->

## Environment

- `prophet-vault --version`:
- Python version and OS:
- Prophet / Firebird version (if the problem involves the `.PRW`):
- Did `python -m prophet_vault schema` succeed?

## Sanitised sample

<!--
For a parser problem, a synthetic or heavily redacted sample helps enormously:
the first 200 bytes of VAR_LIST.RCI in hex, or the `isql` output shape that breaks.
Never attach a real PRW, RCI or a vault generated from a production model.
-->
