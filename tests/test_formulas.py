"""Tests for formula tokenising, reference extraction and hashing."""

from __future__ import annotations

from prophet_vault import formulas


def test_simple_references():
    refs = formulas.extract_references("NO_DEATHS * SUM_ASSURED")
    assert refs == ["NO_DEATHS", "SUM_ASSURED"]


def test_keywords_are_filtered():
    refs = formulas.extract_references("IF DTH_BENEFIT THEN NO_DEATHS * SUM_ASSURED ELSE 0")
    assert refs == ["DTH_BENEFIT", "NO_DEATHS", "SUM_ASSURED"]


def test_period_placeholders_and_functions_are_filtered():
    refs = formulas.extract_references("SUM(PREMIUM) + MAX(CLAIM, 0) + READ_TABLE(TABLE_X, T_PER)")
    assert refs == ["CLAIM", "PREMIUM", "TABLE_X"]


def test_lowercase_time_variable_is_not_a_reference():
    refs = formulas.extract_references("CF(t) * (1 + INT_RATE_PC)")
    assert refs == ["CF", "INT_RATE_PC"]


def test_single_letter_names_are_not_references():
    assert formulas.extract_references("A + B * C") == []


def test_empty_inputs():
    assert formulas.extract_references("") == []
    assert formulas.extract_references(None) == []
    assert formulas.extract_references("nan") == []


def test_duplicates_are_collapsed_and_sorted():
    refs = formulas.extract_references("B_VAR + A_VAR + B_VAR")
    assert refs == ["A_VAR", "B_VAR"]


def test_extra_reserved_can_be_supplied():
    refs = formulas.extract_references("PREM + OTHER_VAR", extra_reserved=["PREM"])
    assert refs == ["OTHER_VAR"]


def test_legacy_noise_words_are_opt_in():
    assert formulas.extract_references("PREM") == ["PREM"]
    assert formulas.extract_references("PREM", extra_reserved=formulas.LEGACY_NOISE_WORDS) == []
    # The legacy list never removes a word that is not on it.
    assert formulas.extract_references("NOT_NOISE", extra_reserved=formulas.LEGACY_NOISE_WORDS) == [
        "NOT_NOISE"
    ]


def test_multiline_formula():
    formula = "IF t = 0 THEN\n  0\nELSE\n  CLAIMS_PAID(t) + EXPENSES_PAID(t) - PREMIUM_RECEIVED(t)"
    assert formulas.extract_references(formula) == [
        "CLAIMS_PAID",
        "EXPENSES_PAID",
        "PREMIUM_RECEIVED",
    ]


def test_normalize_formula_collapses_whitespace():
    assert formulas.normalize_formula("  a  +\n b  ") == "a + b"
    assert formulas.normalize_formula(None) == ""
    assert formulas.normalize_formula("nan") == ""


def test_hash_is_indentation_and_order_insensitive():
    left = formulas.formula_hash(["X + Y", "IF t > 0 THEN 1 ELSE 0"])
    right = formulas.formula_hash(["  IF t > 0 THEN 1 ELSE 0 ", "\nX   +   Y"])
    assert left == right
    assert len(left) == 12


def test_hash_detects_semantic_change():
    assert formulas.formula_hash("X + Y") != formulas.formula_hash("X - Y")


def test_hash_of_nothing_is_empty():
    assert formulas.formula_hash([]) == ""
    assert formulas.formula_hash(None) == ""
    assert formulas.formula_hash("") == ""


def test_split_indicator_expression():
    assert formulas.split_indicator_expression("A AND B AND NOT C") == ["A", "B", "C"]
    assert formulas.split_indicator_expression("ALWAYS") == ["ALWAYS"]
    assert formulas.split_indicator_expression("") == []
    assert formulas.split_indicator_expression(None) == []


def test_split_indicator_expression_respects_word_boundaries():
    # A plain str.split("AND") would cut GRAND_TOTAL into GR + _TOTAL.
    assert formulas.split_indicator_expression("GRAND_TOTAL AND NOT X") == ["GRAND_TOTAL", "X"]
    assert formulas.split_indicator_expression("A OR B") == ["A", "B"]
