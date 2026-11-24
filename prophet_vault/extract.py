"""Extraction of a Prophet model's metadata from the ``.PRW`` database.

The queries here target the tables Prophet writes for a model:

===============  =====================================================
Table            Content
===============  =====================================================
VARIABLES        variable name, description, data type, dimensions
VARIABLEINFO     variable <-> business-database (library) link
VARIABLEDEFN     formula text and indicator expression, as BLOBs
INDICATOR        indicator names and codes
BUSINESSDATABASE library names keyed by ``BUSINESSDBID``
DIMENSIONS       dimension names
VARDIMLINK       variable <-> dimension link with array index
===============  =====================================================

Table and column names are stable across Prophet 2018-2024 in our testing, but
they are not a public API.  If a query fails, run ``prophet-vault schema`` to dump
the live table list and adjust the SQL constants below.

Formulas are BLOBs and are dumped in one batch per ``BUSINESSDBID``: pulling every
formula in a single result set makes ``isql`` produce output large enough to be
truncated by pipes on Windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .config import SHARED_LIBRARY
from .isql import IsqlRunner, Runner, parse_blob_records
from .formulas import extract_references, formula_hash

SQL_VARIABLES = (
    "SELECT NAME, DESCRIPTION, DATATYPE, NUMDIMENSIONS, ISARRAY "
    "FROM VARIABLES ORDER BY NAME"
)
SQL_INDICATORS = "SELECT NAME, DESCRIPTION, CODE FROM INDICATOR ORDER BY NAME"
SQL_LIBRARIES = "SELECT BUSINESSDBID, NAME FROM BUSINESSDATABASE ORDER BY BUSINESSDBID"
SQL_VARIABLE_LIBRARIES = (
    "SELECT V.NAME as VAR_NAME, VI.BUSINESSDBID FROM VARIABLES V "
    "JOIN VARIABLEINFO VI ON V.VARIABLEID = VI.VARIABLEID "
    "ORDER BY V.NAME, VI.BUSINESSDBID"
)
SQL_FORMULA_LIBRARIES = (
    "SELECT DISTINCT VI.BUSINESSDBID FROM VARIABLEDEFN VD "
    "JOIN VARIABLEINFO VI ON VD.VARIABLEINFOID = VI.VARIABLEINFOID "
    "ORDER BY VI.BUSINESSDBID"
)
SQL_FORMULAS_FOR_LIBRARY = (
    "SET BLOBDISPLAY 0;\n"
    "SELECT V.NAME as VAR_NAME, VD.INDICATOREXPR, VD.VARIABLEEXPR "
    "FROM VARIABLEDEFN VD "
    "JOIN VARIABLEINFO VI ON VD.VARIABLEINFOID = VI.VARIABLEINFOID "
    "JOIN VARIABLES V ON VI.VARIABLEID = V.VARIABLEID "
    "WHERE VI.BUSINESSDBID = {dbid};\n"
    "EXIT;\n"
)
SQL_FORMULAS_ALL = (
    "SET BLOBDISPLAY 0;\n"
    "SELECT V.NAME as VAR_NAME, VD.INDICATOREXPR, VD.VARIABLEEXPR "
    "FROM VARIABLEDEFN VD "
    "JOIN VARIABLEINFO VI ON VD.VARIABLEINFOID = VI.VARIABLEINFOID "
    "JOIN VARIABLES V ON VI.VARIABLEID = V.VARIABLEID;\n"
    "EXIT;\n"
)
SQL_DIMENSIONS = (
    "SELECT V.NAME as VAR_NAME, D.NAME as DIM_NAME, VL.ARRAYINDEX "
    "FROM VARDIMLINK VL "
    "JOIN VARIABLES V ON VL.VARIABLEID = V.VARIABLEID "
    "JOIN DIMENSIONS D ON VL.DIMENSIONID = D.DIMENSIONID "
    "ORDER BY V.NAME, VL.ARRAYINDEX"
)

Progress = Callable[[str], None]


@dataclass
class ModelData:
    """Everything extracted from one ``.PRW`` at one point in time."""

    variables: list[dict[str, str]] = field(default_factory=list)
    indicators: list[dict[str, str]] = field(default_factory=list)
    formulas: list[dict[str, str]] = field(default_factory=list)
    dimensions: list[dict[str, str]] = field(default_factory=list)
    library_map: list[dict[str, str]] = field(default_factory=list)
    libraries: dict[str, str] = field(default_factory=dict)


def _get(row: dict[str, str], *names: str) -> str:
    """Read the first present, non-empty column among ``names``."""
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _pair_rows(
    rows: list[dict[str, str]],
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> list[tuple[str, str]]:
    """Extract ``(left, right)`` pairs from rows, tolerating renamed columns."""
    pairs: list[tuple[str, str]] = []
    for row in rows:
        first = _get(row, *left)
        second = _get(row, *right)
        if not second:
            # Fall back to positional: isql always preserves projection order.
            values = [str(v).strip() for v in row.values()]
            if len(values) >= 2:
                first, second = values[0], values[1]
        if first and second:
            pairs.append((first, second))
    return pairs


def extract_variables(runner: Runner) -> list[dict[str, str]]:
    """Variable list with description and shape."""
    rows = runner.query(SQL_VARIABLES)
    variables: list[dict[str, str]] = []
    for row in rows:
        name = _get(row, "NAME", "VAR_NAME")
        if not name:
            continue
        variables.append(
            {
                "NAME": name,
                "DESCRIPTION": _get(row, "DESCRIPTION", "DESC"),
                "DATATYPE": _get(row, "DATATYPE"),
                "NUMDIMENSIONS": _get(row, "NUMDIMENSIONS"),
                "ISARRAY": _get(row, "ISARRAY"),
            }
        )
    variables.sort(key=lambda r: r["NAME"])
    return variables


def extract_indicators(runner: Runner) -> list[dict[str, str]]:
    """Indicator conditions defined in the model."""
    rows = runner.query(SQL_INDICATORS)
    indicators: list[dict[str, str]] = []
    for row in rows:
        name = _get(row, "NAME", "IND_NAME")
        if not name:
            continue
        indicators.append(
            {
                "NAME": name,
                "DESCRIPTION": _get(row, "DESCRIPTION", "DESC"),
                "CODE": _get(row, "CODE"),
            }
        )
    indicators.sort(key=lambda r: r["NAME"])
    return indicators


def extract_libraries(runner: Runner) -> dict[str, str]:
    """Map ``BUSINESSDBID`` to its library name."""
    rows = runner.query(SQL_LIBRARIES)
    libraries: dict[str, str] = {}
    # Projection order is BUSINESSDBID, NAME; fall back to positional order when a
    # Prophet version aliases the columns differently.
    for row in rows:
        dbid = _get(row, "BUSINESSDBID", "DBID")
        name = _get(row, "NAME", "LIBRARY", "DESCRIPTION")
        if not name:
            values = [str(v).strip() for v in row.values()]
            if len(values) >= 2:
                dbid, name = values[0], values[1]
        if dbid and name:
            libraries[dbid] = name
    return libraries


def extract_variable_libraries(runner: Runner) -> dict[str, list[str]]:
    """Map each variable name to the ``BUSINESSDBID`` values that contain it."""
    rows = runner.query(SQL_VARIABLE_LIBRARIES)
    pairs = _pair_rows(rows, ("VAR_NAME", "NAME"), ("BUSINESSDBID", "DBID"))
    mapping: dict[str, list[str]] = {}
    for name, dbid in pairs:
        bucket = mapping.setdefault(name, [])
        if dbid not in bucket:
            bucket.append(dbid)
    return mapping


def build_library_map(
    variable_libraries: dict[str, list[str]],
    libraries: dict[str, str],
) -> list[dict[str, str]]:
    """Build the variable -> library table used for vault folders.

    A variable that lives in exactly one library belongs to it; a variable shared by
    several libraries goes to :data:`prophet_vault.config.SHARED_LIBRARY` so that a
    page never has two homes (Obsidian wikilinks resolve by file name).
    """
    rows: list[dict[str, str]] = []
    for name in sorted(variable_libraries):
        dbids = variable_libraries[name]
        names = [libraries[dbid] for dbid in dbids if dbid in libraries]
        primary = names[0] if len(names) == 1 else SHARED_LIBRARY
        rows.append(
            {
                "VAR_NAME": name,
                "LIBRARY": primary,
                "LIBRARIES": "|".join(names),
            }
        )
    return rows


def extract_formulas(
    runner: Runner,
    progress: Progress | None = None,
    timeout: int = 120,
) -> list[dict[str, str]]:
    """Dump every formula block, batched per library.

    Each record is ``{"VAR_NAME", "FORMULA", "INDICATOREXPR"}``; a variable with
    several indicators yields several records.
    """
    notify = progress or (lambda _msg: None)
    dbids = [
        row_value
        for row_value in (
            _get(row, "BUSINESSDBID", "DBID") for row in runner.query(SQL_FORMULA_LIBRARIES)
        )
        if row_value
    ]

    records: list[dict[str, str]] = []
    if dbids:
        notify(f"formula batches: {len(dbids)} libraries")
        for dbid in dbids:
            script = SQL_FORMULAS_FOR_LIBRARY.format(dbid=dbid)
            batch = parse_blob_records(runner.run_raw(script, timeout=timeout))
            notify(f"  library {dbid}: {len(batch)} formula blocks")
            records.extend(batch)
    else:
        notify("no business databases found; dumping formulas in one batch")
        records.extend(parse_blob_records(runner.run_raw(SQL_FORMULAS_ALL, timeout=timeout)))

    records.sort(key=lambda r: (r["VAR_NAME"], r["INDICATOREXPR"]))
    return records


def extract_dimensions(runner: Runner) -> list[dict[str, str]]:
    """Variable <-> dimension links."""
    rows = runner.query(SQL_DIMENSIONS)
    dimensions: list[dict[str, str]] = []
    for row in rows:
        name = _get(row, "VAR_NAME", "NAME")
        if not name:
            continue
        dimensions.append(
            {
                "VAR_NAME": name,
                "DIM_NAME": _get(row, "DIM_NAME", "NAME"),
                "ARRAYINDEX": _get(row, "ARRAYINDEX"),
            }
        )
    return dimensions


def build_references(
    variables: list[dict[str, str]],
    formulas: list[dict[str, str]],
    extra_reserved: tuple[str, ...] = (),
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Derive forward and reverse dependencies from formula text.

    Candidates are intersected with the real variable list, which removes both
    unknown identifiers and any keyword the tokeniser did not know about.

    Returns:
        ``(references, referenced_by)``, both name -> sorted list of names.
    """
    known = {row["NAME"] for row in variables if row.get("NAME")}
    references: dict[str, set[str]] = {}
    referenced_by: dict[str, set[str]] = {}

    for record in formulas:
        name = record.get("VAR_NAME", "")
        if not name:
            continue
        for candidate in extract_references(record.get("FORMULA"), extra_reserved):
            if candidate == name or candidate not in known:
                continue
            references.setdefault(name, set()).add(candidate)
            referenced_by.setdefault(candidate, set()).add(name)

    return (
        {name: sorted(refs) for name, refs in references.items()},
        {name: sorted(users) for name, users in referenced_by.items()},
    )


def formulas_by_variable(formulas: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Group formula records by variable name, preserving order."""
    grouped: dict[str, list[dict[str, str]]] = {}
    for record in formulas:
        grouped.setdefault(record["VAR_NAME"], []).append(record)
    return grouped


def compute_hashes(
    variables: list[dict[str, str]],
    formulas: list[dict[str, str]],
) -> dict[str, str]:
    """Fingerprint of each variable's formula set, for change detection."""
    grouped = formulas_by_variable(formulas)
    hashes: dict[str, str] = {}
    for row in variables:
        name = row["NAME"]
        blocks = [record.get("FORMULA", "") for record in grouped.get(name, [])]
        hashes[name] = formula_hash(blocks)
    return hashes


def extract_all(
    runner: Runner,
    progress: Progress | None = None,
) -> ModelData:
    """Run the full extraction pipeline against one database."""
    notify = progress or (lambda _msg: None)

    notify("variables")
    variables = extract_variables(runner)
    notify(f"  {len(variables)} variables")

    notify("indicators")
    indicators = extract_indicators(runner)
    notify(f"  {len(indicators)} indicators")

    notify("libraries")
    libraries = extract_libraries(runner)
    variable_libraries = extract_variable_libraries(runner)
    library_map = build_library_map(variable_libraries, libraries)
    notify(f"  {len(libraries)} libraries, {len(library_map)} variables mapped")

    notify("formulas")
    formulas = extract_formulas(runner, progress=notify)
    notify(f"  {len(formulas)} formula blocks")

    notify("dimensions")
    dimensions = extract_dimensions(runner)
    notify(f"  {len(dimensions)} dimension links")

    return ModelData(
        variables=variables,
        indicators=indicators,
        formulas=formulas,
        dimensions=dimensions,
        library_map=library_map,
        libraries=libraries,
    )


def make_runner(settings, isql_path=None, prw_path=None) -> IsqlRunner:
    """Build a :class:`IsqlRunner` from :class:`~prophet_vault.config.Settings`."""
    return IsqlRunner(
        isql_path=isql_path or settings.require_isql(),
        database=prw_path or settings.require_prw(),
        user=settings.isql_user,
        password=settings.isql_password,
    )
