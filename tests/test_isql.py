"""Tests for the isql wrapper: statement flattening and output parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from prophet_vault import isql

SELECT_OUTPUT = """
Database: PROPHET.PRW, User: SYSDBA
SQL> SELECT NAME, DESCRIPTION FROM VARIABLES;

NAME                         DESCRIPTION
============================ ==============================
AGE_AT_ENTRY                 Age at entry of the policy
SUM_ASSURED                  Sum assured for the base cover
NET_CF                       Net cash flow of the period

SQL>
"""

SELECT_OUTPUT_SINGLE_COLUMN = """
SQL> SELECT NAME FROM VARIABLES;

NAME
============================
ALPHA_VAR
BETA_VAR
"""

BLOB_OUTPUT = """
SQL> SET BLOBDISPLAY 0;
SQL> SELECT V.NAME as VAR_NAME, VD.INDICATOREXPR, VD.VARIABLEEXPR FROM ...;

VAR_NAME                                   INDICATOREXPR       VARIABLEEXPR
========================================== =================== =====================
NET_CF                                     ALWAYS              b2:d1
==========================================
IF t = 0 THEN
  0
ELSE
  PREMIUM(t) - CLAIMS(t)
==========================================
SUM_ASSURED                                IFRS17              b2:d2
==========================================
SUM_ASSURED * 2
==========================================
"""


def test_flatten_sql_joins_and_terminates():
    assert isql.flatten_sql("SELECT 1\nFROM T") == "SELECT 1 FROM T;"
    assert isql.flatten_sql("SELECT 1;") == "SELECT 1;"


def test_parse_fixed_width_rows():
    rows = isql.parse_fixed_width(SELECT_OUTPUT)
    assert [row["NAME"] for row in rows] == ["AGE_AT_ENTRY", "SUM_ASSURED", "NET_CF"]
    assert rows[0]["DESCRIPTION"] == "Age at entry of the policy"
    # The last column keeps its interior spaces.
    assert rows[2]["DESCRIPTION"] == "Net cash flow of the period"


def test_parse_fixed_width_single_column():
    rows = isql.parse_fixed_width(SELECT_OUTPUT_SINGLE_COLUMN)
    assert rows == [{"NAME": "ALPHA_VAR"}, {"NAME": "BETA_VAR"}]


def test_parse_fixed_width_without_data():
    assert isql.parse_fixed_width("") == []
    assert isql.parse_fixed_width("SQL> SELECT 1;\n\nSQL>\n") == []


def test_parse_fixed_width_ignores_banners():
    rows = isql.parse_fixed_width("Database: X\nSQL> SELECT A;\n\nA\n===\n1\n")
    assert rows == [{"A": "1"}]


def test_parse_blob_records():
    records = isql.parse_blob_records(BLOB_OUTPUT)
    assert len(records) == 2
    assert records[0]["VAR_NAME"] == "NET_CF"
    assert records[0]["INDICATOREXPR"] == "ALWAYS"
    assert records[0]["FORMULA"] == "IF t = 0 THEN\n  0\nELSE\n  PREMIUM(t) - CLAIMS(t)"
    assert records[1]["VAR_NAME"] == "SUM_ASSURED"
    assert records[1]["FORMULA"] == "SUM_ASSURED * 2"


def test_parse_blob_records_empty():
    assert isql.parse_blob_records("") == []


def test_parse_blob_records_custom_offsets():
    text = "NAME  IE  b2:1\n====\nbody\n====\n"
    records = isql.parse_blob_records(text, name_end=6, indicator_end=9)
    assert records[0]["VAR_NAME"] == "NAME"
    assert records[0]["FORMULA"] == "body"


def test_missing_isql_binary_raises(tmp_path: Path):
    runner = isql.IsqlRunner(isql_path=tmp_path / "nope.exe", database=tmp_path / "PROPHET.PRW")
    with pytest.raises(isql.IsqlError, match="isql.exe not found"):
        runner.run("SELECT 1")


def test_missing_database_raises(tmp_path: Path):
    binary = tmp_path / "isql.exe"
    binary.write_text("stub", encoding="utf-8")
    runner = isql.IsqlRunner(isql_path=binary, database=tmp_path / "missing.PRW")
    with pytest.raises(isql.IsqlError, match="database not found"):
        runner.run("SELECT 1")


class _StubRunner(isql.IsqlRunner):
    """Runner that returns canned text instead of starting a process."""

    def __init__(self, responses: dict[str, str]):
        super().__init__(isql_path=Path("isql.exe"), database=Path("PROPHET.PRW"))
        self.responses = responses
        self.calls: list[str] = []

    def _invoke(self, stdin_text: str, timeout):  # type: ignore[override]
        self.calls.append(stdin_text)
        for needle, text in self.responses.items():
            if needle in stdin_text:
                return text
        return ""


def test_query_uses_the_stub():
    runner = _StubRunner({"SELECT NAME": SELECT_OUTPUT})
    rows = runner.query("SELECT NAME, DESCRIPTION FROM VARIABLES")
    assert len(rows) == 3
    assert "EXIT;" in runner.calls[0]


def test_table_names_reads_first_column():
    runner = _StubRunner({"rdb$relation_name": "RDB$RELATION_NAME\n===\nVARIABLES\nINDICATOR\n"})
    assert runner.table_names() == ["VARIABLES", "INDICATOR"]


def test_query_columns_and_unique_helpers():
    rows = [{"A": "x"}, {"A": ""}, {"A": "y"}, {"A": "x"}]
    assert isql.query_columns(rows, "A") == ["x", "y", "x"]
    assert isql.unique(["a", "b", "a"]) == ["a", "b"]
