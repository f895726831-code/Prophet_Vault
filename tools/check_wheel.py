"""Verify the built wheel before it is published.

Run after ``python -m build --wheel``::

    python tools/check_wheel.py [dist]

Checks that the wheel really carries everything a user needs, which is the class of bug a
source-tree test suite cannot catch:

* ``prophet_vault/templates/dependency_graph.html`` - the graph page fails without it;
* ``prophet_vault/py.typed`` - without it downstream type checkers see ``Any``;
* ``LICENSE`` inside ``dist-info/licenses`` - required for MIT redistribution;
* ``METADATA``: ``License-Expression: MIT``, a version matching
  ``prophet_vault.__version__``, and ``Requires-Python``.

Deliberately dependency-free and shell-agnostic: it globs in Python, so it behaves the same
in bash and in PowerShell.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

REQUIRED_MEMBERS = (
    "prophet_vault/__init__.py",
    "prophet_vault/cli.py",
    "prophet_vault/templates/dependency_graph.html",
    "prophet_vault/py.typed",
)


def find_wheel(dist: Path) -> Path:
    wheels = sorted(dist.glob("*.whl"))
    if not wheels:
        raise SystemExit(f"no wheel found in {dist}; run `python -m build --wheel` first")
    if len(wheels) > 1:
        print(f"note: {len(wheels)} wheels in {dist}, checking {wheels[-1].name}")
    return wheels[-1]


def read_metadata(archive: zipfile.ZipFile) -> str:
    names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
    if not names:
        raise SystemExit("wheel has no METADATA file")
    return archive.read(names[0]).decode("utf-8")


def source_version(repo_root: Path) -> str:
    text = (repo_root / "prophet_vault" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "([^"]+)"', text)
    if not match:
        raise SystemExit("cannot read __version__ from prophet_vault/__init__.py")
    return match.group(1)


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    dist = Path(argv[1]) if len(argv) > 1 else repo_root / "dist"
    wheel = find_wheel(dist)

    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
        missing = [name for name in REQUIRED_MEMBERS if name not in members]
        if missing:
            raise SystemExit(f"{wheel.name} is missing: {', '.join(missing)}")

        if not any(
            name.startswith("prophet_vault-") and name.endswith(".dist-info/licenses/LICENSE")
            for name in members
        ):
            raise SystemExit(f"{wheel.name} does not ship LICENSE")

        metadata = read_metadata(archive)

    version = re.search(r"^Version: (.+)$", metadata, re.MULTILINE)
    requires_python = re.search(r"^Requires-Python: (.+)$", metadata, re.MULTILINE)
    if not version:
        raise SystemExit("METADATA has no Version")
    if "License-Expression: MIT" not in metadata:
        raise SystemExit("METADATA does not carry `License-Expression: MIT` (PEP 639)")
    if not requires_python:
        raise SystemExit("METADATA has no Requires-Python")

    declared = source_version(repo_root)
    built = version.group(1).strip()
    if built != declared:
        raise SystemExit(
            f"version mismatch: wheel says {built}, prophet_vault.__version__ says {declared}"
        )

    print(f"wheel ok: {wheel.name}")
    print(f"  version {built} | requires-python {requires_python.group(1).strip()} | MIT")
    print(f"  shipped: template, py.typed, LICENSE, {len(members)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
