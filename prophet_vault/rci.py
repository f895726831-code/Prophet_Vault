"""Parser for Prophet's ``VAR_LIST.RCI`` binary variable index.

Why this exists
---------------
A Prophet workspace keeps a compact binary index of every variable in the model.
It is the only source of *descriptions* that survives when the ``.PRW`` database is
unavailable, so it is worth reading directly instead of asking a human to export it.

File layout (reverse-engineered, see ``docs/rci-format.md``)
-----------------------------------------------------------
::

    offset  size      content
    0       4         magic  ff ff 07 03
    4       4         file size in bytes, little endian
    8       4         entry count, little endian
    12      28        reserved
    40      n * 4     table of contents: section offsets, little endian, 0-terminated
    ...     ...       sections

Each section is a stream of records::

    [ name\0 ][ category byte ][ description\0 ]

The record boundaries are not stored, so the parser scans: a valid upper-case
identifier followed by a NUL, then optional padding, then a NUL-terminated
description.  The scanning approach is what makes the parser tolerant of vendor
version differences, at the cost of being a *heuristic*: callers should treat the
result as a best-effort list, not as a byte-exact decode.

The parser is deliberately conservative: it only accepts names that match
Prophet's identifier rules and rejects descriptions that themselves look like
identifiers, which is how stray padding bytes are skipped.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

MAGIC = b"\xff\xff\x07\x03"

#: Fixed width of the name field inside a record.
NAME_FIELD = 32

#: Descriptions longer than this are not trusted (they usually mean the scan has
#: lost alignment and is reading into the next record).
MAX_DESCRIPTION = 200

#: Names that look like identifiers but are known non-variables.
JUNK_NAMES = frozenset(
    """
    PROPHENC SYSDBA SHOW SELECT FROM WHERE TABLE COUNT ORDER GROUP DATABASE
    COMPUTED TOTAL LINES SQL CON
    """.split()
)

_CATEGORY_RANGE = range(1, 32)


@dataclass(frozen=True)
class RciHeader:
    """Decoded file header."""

    magic_ok: bool
    file_size: int
    entry_count: int

    @property
    def plausible(self) -> bool:
        return self.magic_ok and self.entry_count > 0


@dataclass(frozen=True)
class RciEntry:
    """One variable record."""

    name: str
    category: str
    description: str

    def as_row(self) -> dict[str, str]:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "source": "VAR_LIST.RCI",
        }


def read_header(data: bytes) -> RciHeader:
    """Decode the 40-byte header without validating the body."""
    magic_ok = data[:4] == MAGIC
    file_size = struct.unpack_from("<I", data, 4)[0] if len(data) >= 8 else 0
    entry_count = struct.unpack_from("<I", data, 8)[0] if len(data) >= 12 else 0
    return RciHeader(magic_ok=magic_ok, file_size=file_size, entry_count=entry_count)


def read_toc(data: bytes) -> list[int]:
    """Return the non-zero section offsets from the table of contents."""
    offsets: list[int] = []
    pos = 40
    while pos + 4 <= len(data):
        (offset,) = struct.unpack_from("<I", data, pos)
        pos += 4
        if offset == 0:
            break
        if offset >= len(data):
            break
        offsets.append(offset)
    return offsets


def is_valid_name(name: str) -> bool:
    """True when ``name`` follows Prophet's identifier rules."""
    if not 2 <= len(name) <= 40:
        return False
    if name in JUNK_NAMES:
        return False
    if not name[0].isupper():
        return False
    return all(c.isupper() or c.isdigit() or c == "_" for c in name)


def _looks_like_identifier(text: str) -> bool:
    """Used to reject descriptions that are really the next record's name."""
    return bool(text) and text[0].isupper() and "_" in text and len(text) <= 40


def _split_name_field(raw: str) -> tuple[str, str]:
    """Separate the category byte from the name inside a name field.

    Some records are prefixed by ``[CATEGORY][control byte]``; others store the
    category inside the name field or not at all, in which case ``"?"`` is used.
    """
    if len(raw) >= 3 and raw[0].isupper() and ord(raw[1]) in _CATEGORY_RANGE:
        return raw[2:].strip(), raw[0]
    return raw.strip(), "?"


def _read_cstring(data: bytes, start: int, limit: int) -> tuple[str, int]:
    """Read a NUL-terminated ASCII string. Returns ``(text, next_offset)``."""
    end = data.find(b"\x00", start, start + limit)
    if end == -1:
        return "", start
    return data[start:end].decode("ascii", errors="ignore"), end + 1


def iter_entries(data: bytes) -> Iterator[RciEntry]:
    """Yield every record the scanner can identify, in file order."""
    pos = 0
    limit = len(data) - NAME_FIELD
    seen: dict[str, RciEntry] = {}

    while pos <= limit:
        field = data[pos : pos + NAME_FIELD]
        nul = field.find(b"\x00")
        if nul == -1:
            pos += 1
            continue

        raw = field[:nul].decode("ascii", errors="ignore")
        name, category = _split_name_field(raw)
        if not is_valid_name(name):
            pos += 1
            continue

        desc_start = pos + NAME_FIELD
        while desc_start < len(data) and data[desc_start] == 0:
            desc_start += 1
        description, next_pos = _read_cstring(data, desc_start, MAX_DESCRIPTION)

        if description and not _looks_like_identifier(description):
            entry = RciEntry(name=name, category=category, description=description)
            # Keep the longest description seen for a name: short ones are usually
            # fragments produced by a misaligned scan.
            previous = seen.get(name)
            if previous is None or len(entry.description) > len(previous.description):
                seen[name] = entry
            pos = next_pos
            continue

        pos += 1

    yield from seen.values()


def parse_bytes(data: bytes) -> list[RciEntry]:
    """Parse ``VAR_LIST.RCI`` content held in memory."""
    if not data:
        return []
    return list(iter_entries(data))


def parse_file(path: str | Path) -> list[RciEntry]:
    """Parse a ``VAR_LIST.RCI`` file."""
    return parse_bytes(Path(path).read_bytes())


def to_rows(entries: Sequence[RciEntry]) -> list[dict[str, str]]:
    """Convert entries to CSV-ready dictionaries."""
    return [entry.as_row() for entry in entries]
