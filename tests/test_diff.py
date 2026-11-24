"""Tests for snapshot comparison and report rendering."""

from __future__ import annotations

from pathlib import Path

from prophet_vault.diff import Diff, compare, load, write
from prophet_vault.snapshot import Snapshot


def make_snapshot(
    variables: list[dict[str, str]],
    formulas: list[dict[str, str]] | None = None,
    hashes: dict[str, str] | None = None,
    references: dict[str, list[str]] | None = None,
    label: str = "snap",
) -> Snapshot:
    formulas = formulas or []
    hashes = hashes or {}
    references = references or {}
    return Snapshot(
        variables=variables,
        formulas=formulas,
        indicators=[],
        dimensions=[],
        formula_hashes=[{"VAR_NAME": k, "FORMULA_HASH": v} for k, v in hashes.items()],
        references=[{"VAR_NAME": k, "REFERENCES": "|".join(v)} for k, v in references.items()],
        library_map=[],
        metadata={"label": label, "total_variables": len(variables)},
    )


def vars_of(*names: str, description: str = "d") -> list[dict[str, str]]:
    return [{"NAME": name, "DESCRIPTION": description} for name in names]


def test_added_and_deleted():
    old = make_snapshot(vars_of("A", "B"))
    new = make_snapshot(vars_of("A", "C"))
    diff = compare(old, new)
    assert diff.added == ["C"]
    assert diff.deleted == ["B"]
    assert diff.unchanged == 1


def test_formula_change_reports_both_versions():
    old = make_snapshot(
        vars_of("A"),
        formulas=[{"VAR_NAME": "A", "FORMULA": "X + Y", "INDICATOREXPR": "ALWAYS"}],
        hashes={"A": "aaa"},
    )
    new = make_snapshot(
        vars_of("A"),
        formulas=[{"VAR_NAME": "A", "FORMULA": "X + Y + Z", "INDICATOREXPR": "ALWAYS"}],
        hashes={"A": "bbb"},
    )
    diff = compare(old, new)
    assert len(diff.formula_changed) == 1
    item = diff.formula_changed[0]
    assert item["name"] == "A"
    assert item["old_formula"] == "X + Y"
    assert item["new_formula"] == "X + Y + Z"
    assert item["old_hash"] == "aaa"
    assert item["new_hash"] == "bbb"


def test_description_change():
    old = make_snapshot(vars_of("A", description="old"))
    new = make_snapshot(vars_of("A", description="new"))
    diff = compare(old, new)
    assert diff.desc_changed == [{"name": "A", "old": "old", "new": "new"}]


def test_indicator_change():
    old = make_snapshot(
        vars_of("A"),
        formulas=[{"VAR_NAME": "A", "FORMULA": "1", "INDICATOREXPR": "ALWAYS"}],
    )
    new = make_snapshot(
        vars_of("A"),
        formulas=[{"VAR_NAME": "A", "FORMULA": "1", "INDICATOREXPR": "IFRS17"}],
    )
    diff = compare(old, new)
    assert len(diff.indicator_changed) == 1
    assert diff.indicator_changed[0]["old"] == "ALWAYS"


def test_reference_change():
    old = make_snapshot(vars_of("A", "B", "C"), references={"A": ["B"]})
    new = make_snapshot(vars_of("A", "B", "C"), references={"A": ["B", "C"]})
    diff = compare(old, new)
    assert diff.refs_changed == [{"name": "A", "added": ["C"], "removed": []}]


def test_unchanged_count_excludes_touched_variables():
    old = make_snapshot(vars_of("A", "B", "C"), hashes={"A": "1", "B": "2", "C": "3"})
    new = make_snapshot(vars_of("A", "B", "C"), hashes={"A": "9", "B": "2", "C": "3"})
    diff = compare(old, new)
    assert diff.unchanged == 2


def test_empty_diff_is_detected():
    old = make_snapshot(vars_of("A"))
    new = make_snapshot(vars_of("A"))
    diff = compare(old, new)
    assert diff.is_empty
    assert diff.summary()["unchanged"] == 1


def test_summary_counts():
    old = make_snapshot(vars_of("A", "B"), hashes={"A": "1", "B": "1"})
    new = make_snapshot(vars_of("A", "C"), hashes={"A": "2"})
    summary = compare(old, new).summary()
    assert summary == {
        "added": 1,
        "deleted": 1,
        "desc_changed": 0,
        "formula_changed": 1,
        "indicator_changed": 0,
        "refs_changed": 0,
        "unchanged": 0,
    }


def test_json_report_shape(tmp_path: Path):
    old = make_snapshot(vars_of("A"), label="old")
    new = make_snapshot(vars_of("A", "B"), label="new")
    diff = compare(old, new)
    payload = diff.as_json()

    assert payload["old_label"] == "old"
    assert payload["new_label"] == "new"
    assert payload["added"] == ["B"]
    assert payload["summary"]["added"] == 1
    assert "generated_at" in payload


def test_write_produces_json_and_markdown(tmp_path: Path):
    old = make_snapshot(vars_of("A"), label="old")
    new = make_snapshot(vars_of("A", "B"), label="new")
    json_path, report_path = write(compare(old, new), tmp_path / "diffs" / "latest.json")

    assert json_path.exists() and report_path.exists()
    assert report_path.name == "latest_report.md"
    assert load(json_path)["added"] == ["B"]
    text = report_path.read_text(encoding="utf-8")
    assert "# Model change report" in text
    assert "`B`" in text


def test_markdown_lists_formula_before_and_after():
    old = make_snapshot(vars_of("A"), formulas=[{"VAR_NAME": "A", "FORMULA": "OLD + 1"}], hashes={"A": "1"})
    new = make_snapshot(vars_of("A"), formulas=[{"VAR_NAME": "A", "FORMULA": "NEW + 1"}], hashes={"A": "2"})
    text = compare(old, new).as_markdown()
    assert "OLD + 1" in text
    assert "NEW + 1" in text


def test_empty_diff_object():
    diff = Diff(old_label="a", new_label="b")
    assert diff.is_empty
    assert diff.as_json()["summary"]["added"] == 0
