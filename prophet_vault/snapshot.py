"""Snapshots: an immutable, diffable CSV copy of a Prophet model.

A snapshot answers "what did the model look like on date X" without needing Prophet
to be installed, and it is the unit that :mod:`prophet_vault.diff` compares.

On-disk layout of ``output/snapshots/<label>/``:

===========================  ==================================================
file                         content
===========================  ==================================================
``variables.csv``            NAME, DESCRIPTION, DATATYPE, NUMDIMENSIONS, ISARRAY, LIBRARY
``formulas.csv``             VAR_NAME, FORMULA, INDICATOREXPR
``indicators.csv``           NAME, DESCRIPTION, CODE
``dimensions.csv``           VAR_NAME, DIM_NAME, ARRAYINDEX
``formula_hashes.csv``       VAR_NAME, FORMULA_HASH
``references.csv``           VAR_NAME, REFERENCES (``a|b|c``)
``library_map.csv``          VAR_NAME, LIBRARY, LIBRARIES (``a|b``)
``metadata.json``            label, source, counts, library table
===========================  ==================================================

Files are written as UTF-8 with a BOM so that Excel opens Chinese descriptions
correctly; readers strip the BOM.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from ._io import write_text
from .config import SHARED_LIBRARY
from .extract import ModelData, build_references, compute_hashes

VARIABLE_COLUMNS = ["NAME", "DESCRIPTION", "DATATYPE", "NUMDIMENSIONS", "ISARRAY", "LIBRARY"]
FORMULA_COLUMNS = ["VAR_NAME", "FORMULA", "INDICATOREXPR"]
INDICATOR_COLUMNS = ["NAME", "DESCRIPTION", "CODE"]
DIMENSION_COLUMNS = ["VAR_NAME", "DIM_NAME", "ARRAYINDEX"]
HASH_COLUMNS = ["VAR_NAME", "FORMULA_HASH"]
REFERENCE_COLUMNS = ["VAR_NAME", "REFERENCES"]
LIBRARY_COLUMNS = ["VAR_NAME", "LIBRARY", "LIBRARIES"]

ENCODING = "utf-8-sig"


def _clean(value: object) -> str:
    """Normalise a cell value: ``None``/``NaN``/``"nan"`` all become an empty string."""
    if value is None:
        return ""
    text = str(value)
    if text.strip().lower() in {"", "nan", "none"}:
        return ""
    return text


def read_rows(path: str | Path) -> list[dict[str, str]]:
    """Read a CSV written by this package (or by Excel) into ``list[dict]``."""
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding=ENCODING, newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: _clean(value) for key, value in row.items() if key is not None} for row in reader]


def write_rows(
    path: str | Path,
    rows: Iterable[Mapping[str, object]],
    columns: list[str] | None = None,
) -> int:
    """Write rows to CSV, creating parent folders. Returns the row count."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    fieldnames = columns or (list(rows[0].keys()) if rows else [])
    with path.open("w", encoding=ENCODING, newline="") as handle:
        # LF on every platform keeps committed snapshots byte-stable and diffable.
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return len(rows)


@dataclass
class Snapshot:
    """A complete model state plus the derived tables used for rendering."""

    variables: list[dict[str, str]] = field(default_factory=list)
    formulas: list[dict[str, str]] = field(default_factory=list)
    indicators: list[dict[str, str]] = field(default_factory=list)
    dimensions: list[dict[str, str]] = field(default_factory=list)
    formula_hashes: list[dict[str, str]] = field(default_factory=list)
    references: list[dict[str, str]] = field(default_factory=list)
    library_map: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    # -- derived indexes -------------------------------------------------
    def variable_names(self) -> list[str]:
        return [row["NAME"] for row in self.variables if row.get("NAME")]

    def description_by_name(self) -> dict[str, str]:
        return {row["NAME"]: row.get("DESCRIPTION", "") for row in self.variables if row.get("NAME")}

    def library_by_name(self) -> dict[str, str]:
        return {row["VAR_NAME"]: row.get("LIBRARY", SHARED_LIBRARY) for row in self.library_map}

    def hash_by_name(self) -> dict[str, str]:
        return {row["VAR_NAME"]: row.get("FORMULA_HASH", "") for row in self.formula_hashes}

    def references_by_name(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for row in self.references:
            raw = row.get("REFERENCES", "")
            out[row["VAR_NAME"]] = [part for part in raw.split("|") if part]
        return out

    def referenced_by(self) -> dict[str, list[str]]:
        reverse: dict[str, set[str]] = {}
        for name, refs in self.references_by_name().items():
            for ref in refs:
                reverse.setdefault(ref, set()).add(name)
        return {name: sorted(users) for name, users in reverse.items()}

    def formulas_by_name(self) -> dict[str, list[dict[str, str]]]:
        grouped: dict[str, list[dict[str, str]]] = {}
        for record in self.formulas:
            grouped.setdefault(record.get("VAR_NAME", ""), []).append(record)
        return grouped

    def libraries(self) -> dict[str, str]:
        value = self.metadata.get("libraries")
        return dict(value) if isinstance(value, dict) else {}

    def label(self) -> str:
        return str(self.metadata.get("label", "unknown"))

    # -- construction ----------------------------------------------------
    @classmethod
    def build(
        cls,
        model: ModelData,
        label: str,
        source: str = "",
        extra_reserved: tuple[str, ...] = (),
    ) -> "Snapshot":
        """Assemble a snapshot from freshly extracted model data."""
        library_by_name = {row["VAR_NAME"]: row["LIBRARY"] for row in model.library_map}

        variables = [
            {
                "NAME": row["NAME"],
                "DESCRIPTION": row.get("DESCRIPTION", ""),
                "DATATYPE": row.get("DATATYPE", ""),
                "NUMDIMENSIONS": row.get("NUMDIMENSIONS", ""),
                "ISARRAY": row.get("ISARRAY", ""),
                "LIBRARY": library_by_name.get(row["NAME"], SHARED_LIBRARY),
            }
            for row in model.variables
        ]

        references, _reverse = build_references(model.variables, model.formulas, extra_reserved)
        hashes = compute_hashes(model.variables, model.formulas)

        metadata: dict[str, object] = {
            "label": label,
            "source": source,
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "total_variables": len(variables),
            "total_formulas": len(model.formulas),
            "total_indicators": len(model.indicators),
            "total_dimensions": len(model.dimensions),
            "variables_with_formulas": sum(1 for value in hashes.values() if value),
            "variables_with_refs": len(references),
            "libraries": model.libraries,
        }

        return cls(
            variables=variables,
            formulas=list(model.formulas),
            indicators=list(model.indicators),
            dimensions=list(model.dimensions),
            formula_hashes=[{"VAR_NAME": name, "FORMULA_HASH": value} for name, value in sorted(hashes.items())],
            references=[{"VAR_NAME": name, "REFERENCES": "|".join(refs)} for name, refs in sorted(references.items())],
            library_map=list(model.library_map),
            metadata=metadata,
        )

    @classmethod
    def load(cls, directory: str | Path) -> "Snapshot":
        """Load a snapshot directory."""
        directory = Path(directory)
        if not directory.is_dir():
            raise FileNotFoundError(f"snapshot directory not found: {directory}")

        metadata: dict[str, object] = {}
        meta_path = directory / "metadata.json"
        if meta_path.exists():
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))

        return cls(
            variables=read_rows(directory / "variables.csv"),
            formulas=read_rows(directory / "formulas.csv"),
            indicators=read_rows(directory / "indicators.csv"),
            dimensions=read_rows(directory / "dimensions.csv"),
            formula_hashes=read_rows(directory / "formula_hashes.csv"),
            references=read_rows(directory / "references.csv"),
            library_map=read_rows(directory / "library_map.csv"),
            metadata=metadata,
        )

    def save(self, directory: str | Path) -> Path:
        """Write every table plus ``metadata.json``. Returns the directory."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        write_rows(directory / "variables.csv", self.variables, VARIABLE_COLUMNS)
        write_rows(directory / "formulas.csv", self.formulas, FORMULA_COLUMNS)
        write_rows(directory / "indicators.csv", self.indicators, INDICATOR_COLUMNS)
        write_rows(directory / "dimensions.csv", self.dimensions, DIMENSION_COLUMNS)
        write_rows(directory / "formula_hashes.csv", self.formula_hashes, HASH_COLUMNS)
        write_rows(directory / "references.csv", self.references, REFERENCE_COLUMNS)
        write_rows(directory / "library_map.csv", self.library_map, LIBRARY_COLUMNS)

        metadata = dict(self.metadata)
        metadata.setdefault("label", directory.name)
        write_text(
            directory / "metadata.json",
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        )
        return directory


def latest_snapshot(snapshots_root: str | Path) -> Path | None:
    """Return the most recently created snapshot directory, by name."""
    root = Path(snapshots_root)
    if not root.is_dir():
        return None
    candidates = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda p: p.name)
    return candidates[-1] if candidates else None
