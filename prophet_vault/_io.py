"""Small I/O helpers used by the writers.

Generated artefacts (snapshots, reports, vault pages, graph HTML) are committed to
git and compared across machines, so newlines must not depend on the operating
system.  ``Path.write_text`` translates ``\\n`` to ``\\r\\n`` on Windows; these
helpers write explicit UTF-8 bytes instead, so a file generated on Windows is
byte-identical to the same file generated on Linux.
"""

from __future__ import annotations

from pathlib import Path


def write_text(path: str | Path, text: str, create_parents: bool = True) -> Path:
    """Write UTF-8 text with LF newlines on every platform."""
    path = Path(path)
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def read_text(path: str | Path) -> str:
    """Read UTF-8 text written by this package (BOM tolerated)."""
    return Path(path).read_text(encoding="utf-8-sig")
