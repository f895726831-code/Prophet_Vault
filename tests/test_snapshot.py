"""Tests for snapshot construction, persistence and derived indexes."""

from __future__ import annotations

import json
from pathlib import Path

from prophet_vault.snapshot import (
    Snapshot,
    latest_snapshot,
    read_rows,
    write_rows,
)


def test_build_from_model_data(new_snapshot: Snapshot):
    assert new_snapshot.label() == "2026-02_demo"
    assert new_snapshot.metadata["total_variables"] == len(new_snapshot.variables)
    assert new_snapshot.metadata["total_formulas"] == len(new_snapshot.formulas)
    assert new_snapshot.metadata["variables_with_formulas"] > 0
    assert new_snapshot.metadata["variables_with_refs"] > 0


def test_inputs_have_no_formula(new_snapshot: Snapshot):
    hashes = new_snapshot.hash_by_name()
    assert hashes["MORT_IN_01"] == ""
    assert hashes["FLOW_001"] != ""


def test_references_only_point_at_real_variables(new_snapshot: Snapshot):
    known = set(new_snapshot.variable_names())
    for record in new_snapshot.references:
        for ref in record["REFERENCES"].split("|"):
            assert ref in known


def test_reverse_dependencies_are_symmetric(new_snapshot: Snapshot):
    forward = new_snapshot.references_by_name()
    reverse = new_snapshot.referenced_by()
    for name, refs in forward.items():
        for ref in refs:
            assert name in reverse[ref]


def test_library_assignment_falls_back_to_shared(new_snapshot: Snapshot):
    libraries = new_snapshot.library_by_name()
    assert libraries["MORT_IN_01"] == "Summary"  # input lives in two libraries
    assert "IFRS17" in set(libraries.values())


def test_save_and_load_roundtrip(tmp_path: Path, new_snapshot: Snapshot):
    directory = new_snapshot.save(tmp_path / "snap")
    for expected in (
        "variables.csv",
        "formulas.csv",
        "indicators.csv",
        "dimensions.csv",
        "formula_hashes.csv",
        "references.csv",
        "library_map.csv",
        "metadata.json",
    ):
        assert (directory / expected).exists(), expected

    loaded = Snapshot.load(directory)
    assert loaded.variables == new_snapshot.variables
    assert loaded.formulas == new_snapshot.formulas
    assert loaded.references == new_snapshot.references
    assert loaded.formula_hashes == new_snapshot.formula_hashes
    assert loaded.label() == new_snapshot.label()
    assert loaded.metadata["total_variables"] == new_snapshot.metadata["total_variables"]


def test_load_missing_directory_raises(tmp_path: Path):
    try:
        Snapshot.load(tmp_path / "nope")
    except FileNotFoundError as exc:
        assert "snapshot directory not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected FileNotFoundError")


def test_csv_helper_treats_nan_as_empty(tmp_path: Path):
    path = tmp_path / "rows.csv"
    path.write_text("A,B\n1,nan\n", encoding="utf-8-sig")
    assert read_rows(path) == [{"A": "1", "B": ""}]


def test_csv_helper_handles_missing_file(tmp_path: Path):
    assert read_rows(tmp_path / "missing.csv") == []


def test_write_rows_returns_count(tmp_path: Path):
    count = write_rows(tmp_path / "out.csv", [{"A": "1"}, {"A": "2"}], ["A"])
    assert count == 2
    assert read_rows(tmp_path / "out.csv") == [{"A": "1"}, {"A": "2"}]


def test_metadata_json_is_readable(snapshot_dir: Path):
    metadata = json.loads((snapshot_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["label"] == "2026-02_demo"
    assert metadata["libraries"]["27"] == "IFRS17"


def test_latest_snapshot_picks_last_by_name(
    tmp_path: Path, old_snapshot: Snapshot, new_snapshot: Snapshot
):
    root = tmp_path / "snapshots"
    old_snapshot.save(root / "2026-01_demo")
    new_snapshot.save(root / "2026-02_demo")
    assert latest_snapshot(root).name == "2026-02_demo"
    assert latest_snapshot(tmp_path / "absent") is None


def test_latest_snapshot_prefers_creation_time_over_the_label(tmp_path: Path):
    """A label like demo_2026-01 must not beat a real month just because of its name."""
    older = Snapshot(
        variables=[{"NAME": "A"}],
        metadata={"label": "2026-11", "created_at": "2026-11-01T10:00:00+08:00"},
    )
    newer = Snapshot(
        variables=[{"NAME": "B"}],
        metadata={"label": "demo_2026-01", "created_at": "2026-11-20T10:00:00+08:00"},
    )
    root = tmp_path / "snapshots"
    older.save(root / "2026-11")
    newer.save(root / "demo_2026-01")
    assert latest_snapshot(root).name == "demo_2026-01"


def test_load_rejects_an_incomplete_snapshot(tmp_path: Path):
    directory = tmp_path / "partial"
    directory.mkdir()
    (directory / "metadata.json").write_text('{"label": "x"}', encoding="utf-8")
    (directory / "variables.csv").write_text("NAME\n", encoding="utf-8-sig")

    try:
        Snapshot.load(directory)
    except FileNotFoundError as exc:
        message = str(exc)
        assert "incomplete" in message
        assert "formulas.csv" in message
    else:  # pragma: no cover
        raise AssertionError("expected FileNotFoundError")


def test_literal_none_description_survives_a_roundtrip(tmp_path: Path):
    snapshot = Snapshot(
        variables=[{"NAME": "A", "DESCRIPTION": "None", "DATATYPE": "NONE"}],
        metadata={"label": "x"},
    )
    loaded = Snapshot.load(snapshot.save(tmp_path / "snap"))
    assert loaded.variables[0]["DESCRIPTION"] == "None"
    assert loaded.variables[0]["DATATYPE"] == "NONE"
