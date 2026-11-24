"""Helpers shared by the test modules (kept out of conftest to stay importable)."""

from __future__ import annotations

import struct


def build_rci_bytes(records, broken_magic: bool = False) -> bytes:
    """Build a ``VAR_LIST.RCI``-shaped blob for parser tests.

    Layout mirrors the documented format: a 40-byte header, one TOC terminator, then
    records of ``[name padded to 32][description]\\0``.
    """
    payload = b"".join(
        name.encode("ascii")[:32].ljust(32, b"\x00") + description.encode("ascii") + b"\x00"
        for name, description in records
    )
    header = b"\xff\xff\x07\x03" if not broken_magic else b"\x00\x00\x00\x00"
    body = header + struct.pack("<I", 0) + struct.pack("<I", len(records)) + b"\x00" * 28
    body += b"\x00\x00\x00\x00"  # empty table of contents
    blob = body + payload
    # Patch the file-size field now that the total length is known.
    return blob[:4] + struct.pack("<I", len(blob)) + blob[8:]
