"""Prophet formula text utilities: tokenising, reference extraction and hashing.

A Prophet variable's *definition* is a block of the Prophet script language, e.g.::

    IF t = 0 THEN
      0
    ELSE
      CLAIMS_PAID(t) + EXPENSES_PAID(t) - PREMIUM_RECEIVED(t)

References are extracted with a token pattern rather than a real parser: every
upper-case identifier is a candidate, then candidates are filtered against the
keyword/builtin list below.  Two facts make this robust enough in practice:

* Prophet identifiers are upper-case words of at least two characters, so single
  letters (``t``, ``i``) and lower-case local names can never collide.
* The extractor is only ever used as a *candidate generator*.  When building a
  dependency graph the candidates are intersected with the real variable list, so
  a missed keyword costs nothing and a spurious candidate is dropped downstream.

See :func:`prophet_vault.graph.build_references`.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, Sequence

#: Upper-case Prophet identifier, 2..40 characters (the column width Prophet uses).
TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9_]{1,39})\b")

#: Control-flow and declaration keywords of the Prophet script language.
KEYWORDS: frozenset[str] = frozenset(
    """
    IF THEN ELSE ELSEIF ENDIF AND OR NOT
    TRUE FALSE FOR EACH LOOP NEXT WHILE DO TO STEP
    SWITCH ENDSWITCH CASE QUIT QUITLOOP RETURN
    INTEGER REAL TEXT NUMBER BOOLEAN CHAR STRING
    PARAMETER PRIVATE PUBLIC PERSISTENT DYNAMIC_PERSISTENT
    VARIABLE_CONSTRAINT STAT_LIST NESTED_PERIOD OPTION
    AS CONSTRAINT IS IN NULL LIKE BETWEEN EXISTS
    FROM SELECT WHERE GROUP ORDER BY HAVING UNION ALL ANY SOME DISTINCT
    """.split()
)

#: Built-in functions and operators.
BUILTINS: frozenset[str] = frozenset(
    """
    SUM COUNT AVG MAX MIN ABS ROUND SQRT EXP LN LOG POWER MOD SIGN
    TRUNC FLOOR CEIL INTEGER REAL TEXT
    MINIMUM MAXIMUM GREATER LESS EQUAL
    READ_TABLE TABLE ERROR
    """.split()
)

#: Time and period placeholders (``t``/``t-1`` style tokens are lower-case, these
#: are the upper-case spellings that can appear inside expressions).
PERIOD_TOKENS: frozenset[str] = frozenset(
    """
    T_PER T_PREV T_NEXT T_FIRST T_LAST
    PER PERIOD PC PN PP AV
    """.split()
)

#: Words kept for backwards compatibility with older extraction runs.  They are
#: *not* language keywords; they were noise-filtered heuristically in the original
#: implementation.  Pass ``extra_reserved=LEGACY_NOISE_WORDS`` to restore it.
LEGACY_NOISE_WORDS: frozenset[str] = frozenset(
    """
    NO TOT DISC INC MATH RES VAL BEN PREM COMM EXP TAX INV INT RATE
    CASH FLOW CAPITAL ASSET LIAB PROFIT LOSS GAIN
    """.split()
)

RESERVED_WORDS: frozenset[str] = KEYWORDS | BUILTINS | PERIOD_TOKENS


def extract_references(formula: object, extra_reserved: Iterable[str] = ()) -> list[str]:
    """Return candidate variable references found in ``formula``.

    The result is de-duplicated and sorted; it contains *candidates*, not verified
    variables.  ``None``, ``NaN`` and empty input yield an empty list.
    """
    if formula is None:
        return []
    text = str(formula)
    if not text.strip() or text.strip().lower() == "nan":
        return []

    reserved = RESERVED_WORDS
    if extra_reserved:
        reserved = reserved | frozenset(w.upper() for w in extra_reserved)

    found: set[str] = set()
    for match in TOKEN_RE.finditer(text):
        token = match.group(1)
        if token in reserved:
            continue
        found.add(token)
    return sorted(found)


def normalize_formula(formula: object) -> str:
    """Collapse all whitespace so that cosmetic edits do not register as changes."""
    if formula is None:
        return ""
    text = str(formula)
    if text.strip().lower() == "nan":
        return ""
    return " ".join(text.split())


def formula_hash(formulas: Sequence[object] | object) -> str:
    """Short, order-independent fingerprint of a variable's formula set.

    A variable may carry several formula blocks (one per indicator).  They are
    normalised, sorted and hashed so that reordering or re-indenting a formula is
    not reported as a change, while any semantic edit is.
    """
    if isinstance(formulas, (str, bytes)) or formulas is None:
        items: list[object] = [formulas]
    else:
        items = list(formulas)  # type: ignore[arg-type]

    normalized = sorted(n for n in (normalize_formula(f) for f in items) if n)
    if not normalized:
        return ""
    return hashlib.md5("|".join(normalized).encode("utf-8")).hexdigest()[:12]


def split_indicator_expression(expression: object) -> list[str]:
    """Split a Prophet ``INDICATOREXPR`` such as ``A AND B AND NOT C`` into names.

    Splits on the *word* ``AND``/``OR`` only: a plain ``str.split("AND")`` would cut
    ``GRAND_TOTAL`` into ``GR`` and ``_TOTAL``.
    """
    if expression is None:
        return []
    text = str(expression).strip()
    if not text or text.lower() == "nan":
        return []
    names: list[str] = []
    for part in re.split(r"\b(?:AND|OR)\b", text):
        cleaned = part.strip().replace("NOT ", "").replace("(", "").replace(")", "").strip()
        if cleaned and cleaned not in names:
            names.append(cleaned)
    return names
