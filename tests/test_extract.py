"""Tests for PRW extraction: query mapping, guards and description enrichment."""

from __future__ import annotations

import pytest

from prophet_vault import extract
from prophet_vault.formulas import formula_hash
from prophet_vault.rci import RciEntry


class FakeRunner:
    """Runner returning canned rows, keyed by a marker in the SQL."""

    def __init__(self, responses: dict[str, list[dict[str, str]]], database: str = "PROPHET.PRW"):
        self.responses = responses
        self.database = database
        self.calls: list[str] = []

    def _match(self, sql: str) -> list[dict[str, str]]:
        for marker, rows in self.responses.items():
            if marker in sql:
                return rows
        return []

    def query(self, sql: str, timeout: int | None = None) -> list[dict[str, str]]:
        self.calls.append(sql)
        return self._match(sql)

    def run(self, sql: str, timeout: int | None = None) -> str:
        self.calls.append(sql)
        return ""

    def run_raw(self, script: str, timeout: int | None = None) -> str:
        self.calls.append(script)
        return ""


def test_build_library_map_prefers_the_single_owner():
    libraries = {"2": "Summary", "3": "Conventional", "27": "IFRS17"}
    mapping = extract.build_library_map(
        {"ONLY_CONV": ["3"], "IN_TWO": ["2", "27"], "UNKNOWN": ["99"]},
        libraries,
    )
    by_name = {row["VAR_NAME"]: row for row in mapping}
    assert by_name["ONLY_CONV"]["LIBRARY"] == "Conventional"
    assert by_name["ONLY_CONV"]["LIBRARIES"] == "Conventional"
    assert by_name["IN_TWO"]["LIBRARY"] == "Summary"
    assert by_name["IN_TWO"]["LIBRARIES"] == "Summary|IFRS17"
    assert by_name["UNKNOWN"]["LIBRARY"] == "Summary"
    assert by_name["UNKNOWN"]["LIBRARIES"] == ""


def test_extract_all_raises_on_an_empty_model():
    runner = FakeRunner({"FROM VARIABLES": []})
    with pytest.raises(extract.ExtractionError) as excinfo:
        extract.extract_all(runner)
    assert "no variables" in str(excinfo.value).lower()
    assert "allow-empty" in str(excinfo.value)


def test_extract_all_can_accept_an_empty_model_explicitly():
    runner = FakeRunner({"FROM VARIABLES": []})
    model = extract.extract_all(runner, allow_empty=True)
    assert model.variables == []


def test_extract_all_maps_every_table():
    responses = {
        "FROM VARIABLES ORDER BY NAME": [
            {
                "NAME": "NET_CF",
                "DESCRIPTION": "net cash flow",
                "DATATYPE": "0",
                "NUMDIMENSIONS": "0",
                "ISARRAY": "0",
            },
            {
                "NAME": "PREMIUM",
                "DESCRIPTION": "premium",
                "DATATYPE": "0",
                "NUMDIMENSIONS": "0",
                "ISARRAY": "0",
            },
        ],
        "FROM INDICATOR ORDER BY NAME": [{"NAME": "ALWAYS", "DESCRIPTION": "always", "CODE": "I1"}],
        "FROM BUSINESSDATABASE": [{"BUSINESSDBID": "3", "NAME": "Conventional"}],
        "VI.BUSINESSDBID FROM VARIABLES V": [
            {"VAR_NAME": "NET_CF", "BUSINESSDBID": "3"},
            {"VAR_NAME": "PREMIUM", "BUSINESSDBID": "3"},
        ],
        "DISTINCT VI.BUSINESSDBID": [{"BUSINESSDBID": "3"}],
        "FROM VARDIMLINK": [],
    }

    class BlobRunner(FakeRunner):
        def run_raw(self, script: str, timeout: int | None = None) -> str:
            return (
                "VAR_NAME                                   INDICATOREXPR       \n"
                "========================================== =================== \n"
                "NET_CF                                     ALWAYS              b2:d1\n"
                "==========================================\n"
                "PREMIUM(t) - CLAIMS(t)\n"
                "==========================================\n"
            )

    runner = BlobRunner(responses)
    model = extract.extract_all(runner, progress=lambda _m: None)

    assert [row["NAME"] for row in model.variables] == ["NET_CF", "PREMIUM"]
    assert model.libraries == {"3": "Conventional"}
    assert model.library_map[0]["LIBRARY"] == "Conventional"
    assert len(model.formulas) == 1

    references, referenced_by = extract.build_references(model.variables, model.formulas)
    # CLAIMS is not a known variable, so it is dropped; PREMIUM is kept.
    assert references == {"NET_CF": ["PREMIUM"]}
    assert referenced_by == {"PREMIUM": ["NET_CF"]}
    assert extract.compute_hashes(model.variables, model.formulas)["NET_CF"] == formula_hash(
        "PREMIUM(t) - CLAIMS(t)"
    )


def test_merge_rci_descriptions_keeps_the_longer_text():
    model = extract.ModelData(
        variables=[
            {"NAME": "A", "DESCRIPTION": "short"},
            {"NAME": "B", "DESCRIPTION": "already the longest of the two"},
            {"NAME": "C", "DESCRIPTION": ""},
        ]
    )
    entries = [
        RciEntry(name="A", category="?", description="a much longer description from the rci file"),
        RciEntry(name="B", category="?", description="tiny"),
        RciEntry(name="C", category="?", description="description that only the rci file has"),
        RciEntry(name="D", category="?", description="not in the model"),
    ]

    changed = extract.merge_rci_descriptions(model, entries)
    by_name = {row["NAME"]: row["DESCRIPTION"] for row in model.variables}

    assert changed == 2
    assert by_name["A"].startswith("a much longer")
    assert by_name["B"] == "already the longest of the two"
    assert by_name["C"].startswith("description that only")
