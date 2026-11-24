"""Thin wrapper around Firebird's ``isql`` command-line tool.

Why shell out instead of using a driver
---------------------------------------
A Prophet ``.PRW`` file is an *embedded* Firebird database.  Depending on the
Prophet version, the file was created by Firebird 2.5 or 3.0, with matching on-disk
format (ODS) versions; a Python driver links against one client library and fails
on the others.  ``isql.exe`` that ships inside the Prophet installation always
matches, so the toolkit uses it as a subprocess and parses its text output.

Two output formats matter:

``SELECT`` statements
    Printed as fixed-width columns, with the column names on the first line.
    :func:`parse_fixed_width` slices values by the header's column positions.

``SET BLOBDISPLAY 0; SELECT ...``
    Used to dump formula text blocks.  ``isql`` prints the row, then a ``b2:``
    blob marker, then the content between two ``===`` rules.  That structure is
    what :func:`parse_blob_records` walks.

Both parsers are tolerant: unknown lines are ignored instead of raising, because
``isql`` mixes banners, prompts and warnings into stdout.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol, Sequence

#: Column names in ``isql`` output are upper-case words; ``$`` appears in system
#: column names such as ``RDB$RELATION_NAME``.
HEADER_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9_$]+)\b")

#: Marker that introduces a blob value in ``SET BLOBDISPLAY 0`` output.
BLOB_MARKER = "b2:"

#: Prompt prefixes that ``isql`` writes into the same stream as the data.
PROMPT_PREFIXES = ("SQL>", "CON>", "Database:")


class IsqlError(RuntimeError):
    """Raised when ``isql`` cannot be started or reports a statement failure."""


class Runner(Protocol):
    """The subset of :class:`IsqlRunner` that the extractors depend on."""

    def run(self, sql: str, timeout: int | None = None) -> str: ...

    def run_raw(self, script: str, timeout: int | None = None) -> str: ...

    def query(self, sql: str, timeout: int | None = None) -> list[dict[str, str]]: ...


def flatten_sql(sql: str) -> str:
    """Join a multi-line statement into one line and terminate it with ``;``.

    ``isql`` reads stdin statement by statement, so an embedded newline would start
    a new statement.  Blob scripts must therefore use :func:`IsqlRunner.run_raw`.
    """
    flat = " ".join(line.strip() for line in sql.splitlines() if line.strip())
    if not flat.endswith(";"):
        flat += ";"
    return flat


def _is_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("==="):
        return True
    if any(stripped.startswith(prefix) for prefix in PROMPT_PREFIXES):
        return True
    lower = stripped.lower()
    return lower.startswith("rows affected") or lower.startswith("statement failed")


def parse_fixed_width(text: str) -> list[dict[str, str]]:
    """Parse ``isql``'s fixed-width ``SELECT`` output into row dictionaries.

    The first non-noise line is treated as the header; column boundaries come from
    the header's token positions.  The final column extends to end of line, which
    keeps free-text descriptions intact.

    Limitation: a value wider than its header column is wrapped by ``isql`` onto a
    continuation line, which the fixed-width format cannot represent.  Keep
    projected values narrow (see ``docs/prw-extraction.md``).
    """
    header: str | None = None
    data_lines: list[str] = []

    for line in text.splitlines():
        if _is_noise(line):
            continue
        if header is None:
            header = line
            continue
        data_lines.append(line)

    if header is None:
        return []

    matches = list(HEADER_TOKEN_RE.finditer(header))
    if not matches:
        # Non-standard header (aliases quoted or lower-case): fall back to whitespace.
        names = [part for part in header.split() if part]
        rows_fallback: list[dict[str, str]] = []
        for line in data_lines:
            values = line.split()
            if len(values) < len(names):
                values += [""] * (len(names) - len(values))
            rows_fallback.append(dict(zip(names, values[: len(names)])))
        return rows_fallback

    spans: list[tuple[str, int, int]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else None
        spans.append((match.group(1), start, end if end is not None else -1))

    rows: list[dict[str, str]] = []
    for line in data_lines:
        row: dict[str, str] = {}
        for name, start, end in spans:
            value = line[start:] if end < 0 else line[start:end]
            row[name] = value.strip()
        if any(row.values()):
            rows.append(row)
    return rows


def parse_blob_records(
    text: str,
    name_end: int = 42,
    indicator_end: int = 122,
) -> list[dict[str, str]]:
    """Parse ``SET BLOBDISPLAY 0`` output into formula records.

    Each record has ``VAR_NAME``, ``INDICATOREXPR`` and ``FORMULA`` keys.  A data
    line is recognised by the ``b2:`` blob marker; the variable name and indicator
    expression are sliced from fixed offsets, and the formula is everything between
    the two ``===`` rules that follow.

    Args:
        text: Raw ``isql`` stdout.
        name_end: End offset of the name column (Prophet prints it padded to 42).
        indicator_end: End offset of the indicator-expression column.
    """
    records: list[dict[str, str]] = []
    state = "scan"
    var_name = ""
    indicator = ""
    blob_lines: list[str] = []

    def flush() -> None:
        nonlocal var_name, indicator, blob_lines
        if var_name:
            records.append(
                {
                    "VAR_NAME": var_name,
                    "INDICATOREXPR": indicator,
                    "FORMULA": "\n".join(blob_lines).rstrip(),
                }
            )
        var_name, indicator, blob_lines = "", "", []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "SQL>" in stripped or "Database:" in stripped or stripped.startswith("CON>"):
            continue
        if stripped.startswith("NAME") and "INDICATOR" in stripped:
            continue

        if state == "scan":
            if BLOB_MARKER in stripped:
                candidate = line[:name_end].strip()
                if re.fullmatch(r"[A-Z][A-Z0-9_]*", candidate):
                    var_name = candidate
                    # The indicator column ends where the blob marker begins, which
                    # keeps this working for narrow as well as padded layouts.
                    indicator = line[name_end:indicator_end].split(BLOB_MARKER)[0].strip()
                    state = "blob_start"
            continue

        if state == "blob_start":
            if stripped.startswith("==="):
                state = "blob_content"
                blob_lines = []
            continue

        if state == "blob_content":
            if stripped.startswith("==="):
                flush()
                state = "scan"
            elif stripped.startswith("VARIABLEEXPR:"):
                continue
            else:
                blob_lines.append(line.rstrip("\r\n"))

    flush()
    return records


#: ``isql`` prints failures into the data stream as ``Statement failed, SQLSTATE = ...``.
FAILURE_RE = re.compile(r"Statement failed|SQLSTATE\s*=", re.IGNORECASE)


def _raise_on_statement_failure(stdout: str, stderr: str) -> None:
    """Turn ``isql`` error output into an exception instead of empty result rows.

    ``isql`` writes failures to the same stream as data, so a caller that only looks at
    parsed rows would treat a failed query as "no rows". That is the difference between
    an empty snapshot and a silent error, and it is worth failing loudly.

    The check requires the full ``Statement failed`` / ``SQLSTATE =`` shape, so prose that
    merely mentions the word cannot trip it.
    """
    combined = f"{stdout}\n{stderr}"
    if not FAILURE_RE.search(combined):
        return

    detail: list[str] = []
    for line in combined.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if FAILURE_RE.search(stripped) or stripped.startswith("-"):
            if stripped not in detail:
                detail.append(stripped)
    raise IsqlError("isql reported a failure: " + (" | ".join(detail) or "unknown error"))


def _warn_on_undecodable_bytes(output: str, encoding: str) -> None:
    """Tell the caller when text was lossily decoded.

    ``errors="replace"`` keeps a snapshot usable when one description has an odd byte, but
    silently planting U+FFFD in a variable description would corrupt it permanently. One
    warning per query is enough to point at ``--charset``.
    """
    if "\ufffd" in output:
        print(
            f"warning: isql output produced undecodable bytes with encoding {encoding!r}; "
            "some text contains U+FFFD. Pass --charset (e.g. UTF8 or WIN1252) to fix it.",
            file=sys.stderr,
        )


@dataclass
class IsqlRunner:
    """Run SQL against a Prophet ``.PRW`` database through ``isql.exe``.

    Args:
        charset: Optional Firebird connection charset, passed as ``-charset``. Set this
            (``UTF8``, ``WIN1252``, ...) when descriptions come back as mojibake; the
            default lets the installation decide.
    """

    isql_path: Path
    database: Path
    user: str = "sysdba"
    password: str = "masterkey"
    timeout: int = 60
    encoding: str = "utf-8"
    charset: str | None = None

    def __post_init__(self) -> None:
        self.isql_path = Path(self.isql_path)
        self.database = Path(self.database)

    def _invoke(self, stdin_text: str, timeout: int | None) -> str:
        if not self.isql_path.exists():
            raise IsqlError(
                f"isql.exe not found at {self.isql_path}. Point --isql at the copy "
                "inside your Prophet installation."
            )
        if not self.database.exists():
            raise IsqlError(f"Prophet database not found at {self.database}")

        command = [
            str(self.isql_path),
            "-q",
            "-u",
            self.user,
            "-p",
            self.password,
        ]
        if self.charset:
            command += ["-charset", self.charset]
        command.append(str(self.database))
        try:
            result = subprocess.run(
                command,
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                encoding=self.encoding,
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - environment
            raise IsqlError(f"isql timed out after {timeout or self.timeout}s") from exc
        except OSError as exc:  # pragma: no cover - environment
            raise IsqlError(f"could not start isql: {exc}") from exc

        output = result.stdout or ""
        _raise_on_statement_failure(output, result.stderr or "")
        _warn_on_undecodable_bytes(output, self.encoding)
        return output

    def run(self, sql: str, timeout: int | None = None) -> str:
        """Execute one statement and return raw stdout."""
        return self._invoke(flatten_sql(sql) + "\nEXIT;\n", timeout)

    def run_raw(self, script: str, timeout: int | None = None) -> str:
        """Execute an ``isql`` script verbatim (needed for ``SET`` + blob dumps)."""
        if not script.rstrip().endswith("EXIT;"):
            script = script.rstrip() + "\nEXIT;\n"
        return self._invoke(script, timeout)

    def query(self, sql: str, timeout: int | None = None) -> list[dict[str, str]]:
        """Execute a ``SELECT`` and return parsed rows."""
        return parse_fixed_width(self.run(sql, timeout))

    def table_names(self) -> list[str]:
        """List user tables, useful when a Prophet version renames something."""
        sql = (
            "SELECT rdb$relation_name FROM rdb$relations "
            "WHERE rdb$system_flag = 0 AND rdb$view_blr IS NULL ORDER BY 1;"
        )
        rows = self.query(sql)
        if not rows:
            return []
        first_column = next(iter(rows[0]))
        return [row[first_column].strip() for row in rows if row.get(first_column, "").strip()]


def query_columns(rows: Sequence[dict[str, str]], column: str) -> list[str]:
    """Convenience: non-empty values of one column, in order."""
    out: list[str] = []
    for row in rows:
        value = (row.get(column) or "").strip()
        if value:
            out.append(value)
    return out


def unique(values: Iterable[str]) -> list[str]:
    """Order preserving de-duplication."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
