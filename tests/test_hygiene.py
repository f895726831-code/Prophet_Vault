"""Repository hygiene checks that do not fit a single module's behaviour.

The one that matters: a test that imports an undeclared third-party package passes on a
developer machine (where everything is installed) and fails in CI (which installs only
`.[dev]`). That exact bug cost a CI cycle, so it is now a test.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent

#: Import roots a test file may use besides the standard library.
ALLOWED_ROOTS = {
    "pytest",
    "prophet_vault",
    "helpers",  # tests/helpers.py
    "conftest",  # tests/conftest.py, imported by pytest itself
}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_tests_only_import_declared_dependencies():
    """A test may import the standard library, pytest, or the package under test - nothing else."""
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("*.py")):
        for root in sorted(imported_roots(path)):
            if root in ALLOWED_ROOTS or root in sys.stdlib_module_names:
                continue
            offenders.append(f"{path.name}: {root}")
    assert not offenders, "undeclared third-party imports in tests: " + ", ".join(offenders)


def test_package_imports_only_the_standard_library():
    """The shipped package must stay dependency-free, which is a documented promise."""
    package_dir = TESTS_DIR.parent / "prophet_vault"
    offenders: list[str] = []
    for path in sorted(package_dir.rglob("*.py")):
        for root in sorted(imported_roots(path)):
            if root in {"prophet_vault"} or root in sys.stdlib_module_names:
                continue
            offenders.append(f"{path.name}: {root}")
    assert not offenders, "the package imported something outside the stdlib: " + ", ".join(
        offenders
    )
