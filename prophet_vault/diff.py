"""Snapshot comparison: "what changed in the model since last month?".

Four independent dimensions are compared per variable:

===============  ====================================  ==========================
dimension        comparison                             change label
===============  ====================================  ==========================
existence        set of names                          ``NEW`` / ``DELETED``
description      exact string                          ``DESC_CHANGED``
formula set      normalised text, then MD5             ``FORMULA_CHANGED``
indicator        set of ``INDICATOREXPR`` values       ``INDICATOR_CHANGED``
references       set of referenced variable names      ``REFS_CHANGED``
===============  ====================================  ==========================

Formula comparison goes through a hash rather than the raw text so that
re-indentation or re-ordering is not reported as a change; see
:func:`prophet_vault.formulas.formula_hash`.

Two output formats, two audiences, and therefore two policies:

``as_json``
    **Complete.** ``update-vault`` replays this file, so an entry that is missing here is
    a page that never gets updated. Nothing is truncated except the before/after formula
    *preview text* (500 characters), which is display only.
``as_markdown``
    Capped at 20-50 entries per section, because a 3,000-line report is not a report.

Totals in ``summary`` are always complete.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._io import write_text
from .snapshot import Snapshot

#: Marks the truncation of the before/after formula text in the JSON report. The
#: *entries* are never dropped: the updater depends on them.
FORMULA_PREVIEW_CHARS = 500

MARKDOWN_ENTRY_CAP = 50


@dataclass
class Diff:
    """The difference between two snapshots."""

    old_label: str
    new_label: str
    old_total: int = 0
    new_total: int = 0
    added: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    desc_changed: list[dict[str, str]] = field(default_factory=list)
    formula_changed: list[dict[str, str]] = field(default_factory=list)
    indicator_changed: list[dict[str, str]] = field(default_factory=list)
    refs_changed: list[dict[str, Any]] = field(default_factory=list)
    unchanged: int = 0

    def summary(self) -> dict[str, int]:
        return {
            "added": len(self.added),
            "deleted": len(self.deleted),
            "desc_changed": len(self.desc_changed),
            "formula_changed": len(self.formula_changed),
            "indicator_changed": len(self.indicator_changed),
            "refs_changed": len(self.refs_changed),
            "unchanged": self.unchanged,
        }

    @property
    def is_empty(self) -> bool:
        return not any(
            self.summary()[key]
            for key in (
                "added",
                "deleted",
                "desc_changed",
                "formula_changed",
                "indicator_changed",
                "refs_changed",
            )
        )

    def as_json(self) -> dict[str, Any]:
        """Complete machine-readable report; the vault updater replays this file.

        Every changed variable is listed. Only the before/after formula *text* is cut
        to :data:`FORMULA_PREVIEW_CHARS`, because it is a preview for the page's
        ``version_history`` rather than a source of truth.
        """
        return {
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "format_version": 1,
            "old_label": self.old_label,
            "new_label": self.new_label,
            "old_total": self.old_total,
            "new_total": self.new_total,
            "summary": self.summary(),
            "added": self.added,
            "deleted": self.deleted,
            "desc_changed": self.desc_changed,
            "formula_changed": [
                {
                    "name": item["name"],
                    "old_hash": item.get("old_hash", ""),
                    "new_hash": item.get("new_hash", ""),
                    "old_formula": item.get("old_formula", "")[:FORMULA_PREVIEW_CHARS],
                    "new_formula": item.get("new_formula", "")[:FORMULA_PREVIEW_CHARS],
                }
                for item in self.formula_changed
            ],
            "indicator_changed": self.indicator_changed,
            "refs_changed": self.refs_changed,
        }

    def as_markdown(self) -> str:
        """Human-readable report, suitable for a PR or a monthly mail."""
        summary = self.summary()
        lines = [
            "# Model change report",
            "",
            f"**Old snapshot**: `{self.old_label}` ({self.old_total:,} variables)",
            f"**New snapshot**: `{self.new_label}` ({self.new_total:,} variables)",
            "",
            "## Summary",
            "",
            "| Change type | Count |",
            "|-------------|-------|",
            f"| Variables added | {summary['added']} |",
            f"| Variables deleted | {summary['deleted']} |",
            f"| Formulas changed | {summary['formula_changed']} |",
            f"| Descriptions changed | {summary['desc_changed']} |",
            f"| Indicators changed | {summary['indicator_changed']} |",
            f"| References changed | {summary['refs_changed']} |",
            f"| Unchanged | {summary['unchanged']} |",
            "",
        ]

        if self.added:
            lines += [f"## Added variables ({len(self.added)})", ""]
            lines += [f"- `{name}`" for name in self.added[:MARKDOWN_ENTRY_CAP]]
            if len(self.added) > MARKDOWN_ENTRY_CAP:
                lines.append(f"- ... and {len(self.added) - MARKDOWN_ENTRY_CAP} more")
            lines.append("")

        if self.deleted:
            lines += [f"## Deleted variables ({len(self.deleted)})", ""]
            lines += [f"- ~~`{name}`~~" for name in self.deleted[:MARKDOWN_ENTRY_CAP]]
            if len(self.deleted) > MARKDOWN_ENTRY_CAP:
                lines.append(f"- ... and {len(self.deleted) - MARKDOWN_ENTRY_CAP} more")
            lines.append("")

        if self.formula_changed:
            lines += [f"## Formula changes ({len(self.formula_changed)})", ""]
            for item in self.formula_changed[:20]:
                lines += [
                    f"### `{item['name']}`",
                    "",
                    "Before:",
                    "",
                    "```prophet",
                    item.get("old_formula", "")[:300],
                    "```",
                    "",
                    "After:",
                    "",
                    "```prophet",
                    item.get("new_formula", "")[:300],
                    "```",
                    "",
                ]
            if len(self.formula_changed) > 20:
                lines += [f"... and {len(self.formula_changed) - 20} more formula changes", ""]

        if self.refs_changed:
            lines += [f"## Dependency changes ({len(self.refs_changed)})", ""]
            for item in self.refs_changed[:MARKDOWN_ENTRY_CAP]:
                added = ", ".join(f"`{name}`" for name in item.get("added", [])) or "-"
                removed = ", ".join(f"`{name}`" for name in item.get("removed", [])) or "-"
                lines.append(f"- `{item['name']}`: +{added} / -{removed}")
            lines.append("")

        return "\n".join(lines)


def _indicator_sets(snapshot: Snapshot) -> dict[str, str]:
    """Per-variable, order-independent signature of its indicator expressions."""
    buckets: dict[str, set[str]] = {}
    for record in snapshot.formulas:
        name = record.get("VAR_NAME", "")
        expression = (record.get("INDICATOREXPR") or "").strip()
        if name and expression:
            buckets.setdefault(name, set()).add(expression)
    return {name: "|".join(sorted(values)) for name, values in buckets.items()}


def _formula_text(snapshot: Snapshot, name: str) -> str:
    blocks = [
        (record.get("FORMULA") or "").strip()
        for record in snapshot.formulas
        if record.get("VAR_NAME") == name and (record.get("FORMULA") or "").strip()
    ]
    return " | ".join(blocks) if blocks else "(none)"


def compare(old: Snapshot, new: Snapshot) -> Diff:
    """Compare two snapshots and return the structured difference."""
    old_names = set(old.variable_names())
    new_names = set(new.variable_names())
    common = old_names & new_names

    diff = Diff(
        old_label=old.label(),
        new_label=new.label(),
        old_total=len(old_names),
        new_total=len(new_names),
        added=sorted(new_names - old_names),
        deleted=sorted(old_names - new_names),
    )

    old_desc = old.description_by_name()
    new_desc = new.description_by_name()
    old_hash = old.hash_by_name()
    new_hash = new.hash_by_name()
    old_indicators = _indicator_sets(old)
    new_indicators = _indicator_sets(new)
    old_refs = old.references_by_name()
    new_refs = new.references_by_name()

    changed: set[str] = set()

    for name in sorted(common):
        if old_desc.get(name, "") != new_desc.get(name, ""):
            diff.desc_changed.append(
                {"name": name, "old": old_desc.get(name, ""), "new": new_desc.get(name, "")}
            )
            changed.add(name)

        if old_hash.get(name, "") != new_hash.get(name, ""):
            diff.formula_changed.append(
                {
                    "name": name,
                    "old_hash": old_hash.get(name, ""),
                    "new_hash": new_hash.get(name, ""),
                    "old_formula": _formula_text(old, name),
                    "new_formula": _formula_text(new, name),
                }
            )
            changed.add(name)

        if old_indicators.get(name, "") != new_indicators.get(name, ""):
            diff.indicator_changed.append(
                {
                    "name": name,
                    "old": old_indicators.get(name, ""),
                    "new": new_indicators.get(name, ""),
                }
            )
            changed.add(name)

        before = set(old_refs.get(name, []))
        after = set(new_refs.get(name, []))
        if before != after:
            diff.refs_changed.append(
                {
                    "name": name,
                    "added": sorted(after - before),
                    "removed": sorted(before - after),
                }
            )
            changed.add(name)

    diff.unchanged = len(common) - len(changed)
    return diff


def write(diff: Diff, json_path: str | Path) -> tuple[Path, Path]:
    """Write ``<name>.json`` plus ``<name>_report.md``. Returns both paths."""
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    write_text(
        json_path,
        json.dumps(diff.as_json(), indent=2, ensure_ascii=False) + "\n",
    )
    report_path = json_path.with_name(f"{json_path.stem}_report.md")
    write_text(report_path, diff.as_markdown())
    return json_path, report_path


def load(path: str | Path) -> dict[str, Any]:
    """Load a diff JSON produced by :func:`write`."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
