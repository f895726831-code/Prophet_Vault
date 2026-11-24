"""Tests for the VAR_LIST.RCI binary parser."""

from __future__ import annotations

import struct

from helpers import build_rci_bytes

from prophet_vault import rci


def test_read_header_from_synthetic_file(rci_file):
    header = rci.read_header(rci_file.read_bytes()[:40])
    assert header.magic_ok is True
    assert header.file_size == rci_file.stat().st_size
    assert header.entry_count == 3
    assert header.plausible is True


def test_read_header_reports_bad_magic():
    header = rci.read_header(b"\x00\x00\x00\x00" + struct.pack("<I", 100) + struct.pack("<I", 5) + b"\x00" * 28)
    assert header.magic_ok is False
    assert header.entry_count == 5
    assert header.plausible is False


def test_parse_file_returns_all_records(rci_file):
    entries = rci.parse_file(rci_file)
    names = [entry.name for entry in entries]

    assert names == ["AGE_AT_ENTRY", "SUM_ASSURED", "PREMIUM_ANNUAL"]
    assert entries[0].description == "Age at entry of the policy"
    assert all(entry.category == "?" for entry in entries)


def test_parse_file_from_path_string(rci_file):
    entries = rci.parse_file(str(rci_file))
    assert len(entries) == 3


def test_category_prefix_is_split_off():
    blob = build_rci_bytes([("THIS_NAME_IS_LONG", "description")])
    # Rewrite the first record as "[B][control byte][name]".
    marker = blob.index(b"THIS_NAME_IS_LONG")
    patched = blob[:marker] + b"B\x01" + blob[marker:]
    entries = rci.parse_bytes(patched)

    assert entries
    assert entries[0].name == "THIS_NAME_IS_LONG"
    assert entries[0].category == "B"


def test_junk_names_are_rejected():
    blob = build_rci_bytes([("SQL", "select prompt"), ("FROM", "clause"), ("REAL_VAR", "a variable")])
    names = [entry.name for entry in rci.parse_bytes(blob)]
    assert "REAL_VAR" in names
    assert "SQL" not in names
    assert "FROM" not in names


def test_lowercase_names_are_not_variables():
    blob = build_rci_bytes([("lower_case", "not a Prophet variable")])
    assert rci.parse_bytes(blob) == []


def test_description_that_looks_like_identifier_is_ignored():
    blob = build_rci_bytes([("VAR_ONE", "ANOTHER_VARIABLE_NAME")])
    # The heuristic refuses a description shaped like an identifier, and then keeps
    # scanning; nothing valid is left, so no entry is produced.
    assert rci.parse_bytes(blob) == []


def test_empty_input():
    assert rci.parse_bytes(b"") == []


def test_to_rows_shape(rci_file):
    rows = rci.to_rows(rci.parse_file(rci_file))
    assert set(rows[0]) == {"name", "category", "description", "source"}
    assert rows[0]["source"] == "VAR_LIST.RCI"


def test_read_toc_stops_at_terminator():
    data = bytearray(b"\x00" * 40 + struct.pack("<II", 52, 0) + b"\x00" * 20)
    assert rci.read_toc(bytes(data)) == [52]


def test_read_toc_ignores_offsets_past_end_of_file():
    data = bytearray(b"\x00" * 40 + struct.pack("<II", 9999, 0))
    assert rci.read_toc(bytes(data)) == []


def test_is_valid_name_rules():
    assert rci.is_valid_name("GOOD_NAME")
    assert rci.is_valid_name("A1")
    assert not rci.is_valid_name("A")
    assert not rci.is_valid_name("lower")
    assert not rci.is_valid_name("HAS SPACE")
    assert not rci.is_valid_name("X" * 41)
