"""Generate a synthetic Prophet-shaped model so the toolkit can be tried without one.

Everything here is fabricated: names, descriptions and formulas are generated from
templates, and no number is meaningful.  It exists so that a reader of the repository
can run the full pipeline - snapshot -> diff -> vault -> graph - in seconds, and so
the test suite has a realistic fixture without needing a licensed Prophet install.

Shape of the generated model (default size):

* inputs: mortality, lapse, expense, interest and commission parameters and table
  reads - variables with no formula
* intermediate values: flowing totals that reference the inputs
* aggregates: a second layer that references the intermediate values
* results: top-level outputs referenced by nothing

The graph is a layered DAG, which is what makes the dependency view readable: every
edge points from a lower layer to a higher one, and there are no cycles.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .extract import ModelData

#: Library id -> display name, mimicking ``BUSINESSDATABASE``.
DEMO_LIBRARIES: dict[str, str] = {
    "2": "Summary",
    "3": "Conventional",
    "4": "Unit Linked",
    "27": "IFRS17",
}

#: Indicator name -> description.
DEMO_INDICATORS: list[tuple[str, str]] = [
    ("ALWAYS", "Runs in every projection"),
    ("IFRS17", "IFRS 17 measurement only"),
    ("SOLVENCY", "Solvency II reporting only"),
    ("WITH_PROFIT", "Participating business only"),
    ("UNIT_LINKED", "Unit-linked business only"),
]

_INPUT_GROUPS: list[tuple[str, str]] = [
    ("MORT", "Mortality rate"),
    ("LAPSE", "Lapse rate"),
    ("EXPNS", "Expense assumption"),
    ("INT", "Interest rate"),
    ("COMM", "Commission rate"),
]

_GROUP_LABELS = dict(_INPUT_GROUPS)

_DERIVED_TEMPLATES: list[str] = [
    "{a} * {b} / 1000",
    "MAX({a} - {b}, 0) + {c}",
    "{a}(t) * (1 + {b}) - {c}(t)",
    "IF t = 0 THEN\n  {a} * {b}\nELSE\n  {c}(t-1) + {a} * {b}",
    "SUM({a}(t)) + {b} * {c}",
    "ROUND({a} * {b}, 2) + {c}",
]

_AGGREGATE_TEMPLATES: list[str] = [
    "IF {ind} THEN {a} + {b} - {c} ELSE 0",
    "{a}(t) + {b}(t) - {c}(t) + {d}",
    "MAX({a} + {b} - {c}, 0)",
    "IF t = 0 THEN\n  {a} + {b}\nELSE\n  {c}(t-1) * (1 + {d}) + {a}",
]


@dataclass
class DemoOptions:
    """Knobs for the synthetic model."""

    seed: int = 7
    inputs_per_group: int = 6
    derived: int = 48
    aggregates: int = 26
    results: int = 12


def _describe(group: str, index: int) -> str:
    return f"{_GROUP_LABELS.get(group, group)} variant {index + 1}"


def _pick(rng: random.Random, pool: list[str], count: int) -> list[str]:
    return rng.sample(pool, min(count, len(pool)))


def generate_model(options: DemoOptions | None = None) -> ModelData:
    """Build a deterministic synthetic :class:`~prophet_vault.extract.ModelData`."""
    options = options or DemoOptions()
    rng = random.Random(options.seed)

    variables: list[dict[str, str]] = []
    formulas: list[dict[str, str]] = []
    library_assignments: dict[str, list[str]] = {}

    def add_variable(
        name: str,
        description: str,
        library_ids: list[str],
        formula_blocks: list[tuple[str, str]] | None = None,
        is_array: bool = False,
    ) -> None:
        variables.append(
            {
                "NAME": name,
                "DESCRIPTION": description,
                "DATATYPE": "2" if is_array else "0",
                "NUMDIMENSIONS": "1" if is_array else "0",
                "ISARRAY": "1" if is_array else "0",
            }
        )
        library_assignments[name] = library_ids
        for formula, indicator in formula_blocks or []:
            formulas.append({"VAR_NAME": name, "FORMULA": formula, "INDICATOREXPR": indicator})

    inputs: list[str] = []
    for group, _label in _INPUT_GROUPS:
        for index in range(options.inputs_per_group):
            name = f"{group}_IN_{index + 1:02d}"
            add_variable(name, _describe(group, index), ["2", "3"], is_array=index == 0)
            inputs.append(name)

            table_name = f"{group}_TBL_{index + 1:02d}"
            add_variable(
                table_name,
                f"{_describe(group, index)} read from the assumption table",
                ["2", "3"],
                formula_blocks=[
                    (
                        f'READ_TABLE("{group}_ASSUMPTION", POLICY_YEAR, SEX)',
                        "ALWAYS",
                    )
                ],
                is_array=True,
            )
            inputs.append(table_name)

    derived: list[str] = []
    for index in range(options.derived):
        name = f"FLOW_{index + 1:03d}"
        a, b, c = _pick(rng, inputs + derived, 3)
        template = _DERIVED_TEMPLATES[index % len(_DERIVED_TEMPLATES)]
        formula = template.format(a=a, b=b, c=c, ind="ALWAYS")
        indicator = "ALWAYS"
        blocks = [(formula, indicator)]
        if index % 11 == 0:
            # A variable with two formula blocks, one per indicator, is common in
            # real models and exercises the multi-indicator UI.
            blocks.append(
                (
                    f"IF {rng.choice(inputs)} > 0 THEN {rng.choice(derived or inputs)} * 2 ELSE 0",
                    "IFRS17",
                )
            )
        add_variable(
            name,
            f"Intermediate cash-flow item {index + 1}",
            [rng.choice(["2", "3", "4"])],
            formula_blocks=blocks,
        )
        derived.append(name)

    aggregates: list[str] = []
    for index in range(options.aggregates):
        name = f"AGG_{index + 1:03d}"
        a, b, c, d = _pick(rng, derived + aggregates, 4)
        template = _AGGREGATE_TEMPLATES[index % len(_AGGREGATE_TEMPLATES)]
        indicator = DEMO_INDICATORS[index % len(DEMO_INDICATORS)][0]
        formula = template.format(a=a, b=b, c=c, d=d, ind=indicator)
        add_variable(
            name,
            f"Aggregated result {index + 1}",
            [rng.choice(["3", "4", "27"])],
            formula_blocks=[(formula, indicator)],
        )
        aggregates.append(name)

    result_names = [
        "BEL",
        "CSM",
        "RA",
        "PVFP",
        "VIF",
        "STAT_RSV",
        "TOT_PREM",
        "TOT_CLAIM",
        "NET_CF",
        "PROFIT_SIGN",
        "MCR",
        "SCR",
    ]
    for index in range(options.results):
        name = result_names[index % len(result_names)] + (
            "" if index < len(result_names) else f"_{index}"
        )
        a, b, c = _pick(rng, aggregates, 3)
        add_variable(
            name,
            f"Top-level reported figure: {name.replace('_', ' ').title()}",
            ["2"],
            formula_blocks=[(f"{a}(t) + {b}(t) - {c}(t)", "ALWAYS")],
        )

    indicators = [
        {"NAME": name, "DESCRIPTION": description, "CODE": f"IND_{index + 1:03d}"}
        for index, (name, description) in enumerate(DEMO_INDICATORS)
    ]

    library_map: list[dict[str, str]] = []
    for name in sorted(library_assignments):
        ids = library_assignments[name]
        names = [DEMO_LIBRARIES[lib] for lib in ids]
        library_map.append(
            {
                "VAR_NAME": name,
                "LIBRARY": names[0] if len(names) == 1 else "Summary",
                "LIBRARIES": "|".join(names),
            }
        )

    return ModelData(
        variables=sorted(variables, key=lambda row: row["NAME"]),
        indicators=indicators,
        formulas=sorted(formulas, key=lambda row: (row["VAR_NAME"], row["INDICATOREXPR"])),
        dimensions=[],
        library_map=library_map,
        libraries=dict(DEMO_LIBRARIES),
    )


def generate_twin_model(options: DemoOptions | None = None) -> tuple[ModelData, ModelData]:
    """Return ``(old, new)`` demo models two months apart.

    The "new" model differs by a handful of added, removed, renamed and re-formulated
    variables, which is what the diff and the incremental vault update need to show
    something meaningful.
    """
    options = options or DemoOptions()
    old = generate_model(options)
    new = generate_model(options)

    # 1. Add three variables.
    for suffix in ("A", "B", "C"):
        name = f"NEW_FEATURE_{suffix}"
        new.variables.append(
            {
                "NAME": name,
                "DESCRIPTION": f"New assumption introduced in the later model version ({suffix})",
                "DATATYPE": "0",
                "NUMDIMENSIONS": "0",
                "ISARRAY": "0",
            }
        )
        new.formulas.append(
            {"VAR_NAME": name, "FORMULA": "AGG_001(t) * 0.01", "INDICATOREXPR": "IFRS17"}
        )
        new.library_map.append({"VAR_NAME": name, "LIBRARY": "IFRS17", "LIBRARIES": "IFRS17"})

    # 2. Remove one variable.
    removed = "FLOW_007"
    new.variables = [row for row in new.variables if row["NAME"] != removed]
    new.formulas = [row for row in new.formulas if row["VAR_NAME"] != removed]
    new.library_map = [row for row in new.library_map if row["VAR_NAME"] != removed]

    # 3. Change a formula and a description.
    for row in new.formulas:
        if row["VAR_NAME"] == "FLOW_010":
            row["FORMULA"] = row["FORMULA"].replace("*", " / 2 *", 1)
    for row in new.variables:
        if row["NAME"] == "AGG_004":
            row["DESCRIPTION"] = "Aggregated result 4 (redefined for the new reporting basis)"

    new.variables.sort(key=lambda row: row["NAME"])
    new.formulas.sort(key=lambda row: (row["VAR_NAME"], row["INDICATOREXPR"]))
    new.library_map.sort(key=lambda row: row["VAR_NAME"])
    return old, new
