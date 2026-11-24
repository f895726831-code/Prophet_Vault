"""Render a snapshot as an Obsidian vault, and keep it up to date month by month.

Why Obsidian
------------
An actuary needs to *browse* a model: jump from a variable to the variables it
uses, to the indicators that gate it, to the pages that consume it.  Obsidian gives
that for free from plain Markdown with ``[[wikilinks]]`` - no server, no database,
no licence, and the files stay diffable in git.

Layout
------
::

    <vault>/
    ├── Variables/<Library>/<A-Z or _>/<NAME>.md
    ├── Indicators/<INDICATOR>.md
    ├── _Index/00-Overview.md
    ├── _Index/CHANGELOG.md
    └── .obsidian/app.json

Folders are split by library and then by initial letter: Prophet models routinely
hold 15,000 variables, and one flat folder makes Obsidian, Explorer and git all
unhappy.  Wikilinks resolve by file name, so the folder nesting is free.

Updating
--------
:func:`apply_diff` re-renders only the pages that a diff marks as changed, and
merges the previous ``version_history`` frontmatter into the new page.  Re-rendering
from the new snapshot is deliberately preferred over patching Markdown sections in
place: string surgery around ``##`` headings survives exactly until someone edits a
page by hand, while a full re-render with merged history is idempotent.
"""

from __future__ import annotations

import os
import re
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

from ._io import write_text
from .config import SHARED_LIBRARY
from .diff import Diff
from .snapshot import Snapshot

OVERVIEW_PATH = Path("_Index") / "00-Overview.md"
CHANGELOG_PATH = Path("_Index") / "CHANGELOG.md"
OBSIDIAN_DIR = Path(".obsidian")
MAX_HISTORY_ENTRIES = 50

_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class VaultError(RuntimeError):
    """Raised when a vault directory cannot be created or safely replaced."""


def safe_filename(name: str) -> str:
    """Make ``name`` safe as a file name on Windows, macOS and Linux."""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("_", name).strip().rstrip(".")
    return cleaned or "_"


def yaml_string(value: object) -> str:
    """Quote a value for YAML frontmatter."""
    if value is None:
        return '""'
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    text = " ".join(text.split())
    return f'"{text}"'


def library_to_folder(library: str) -> str:
    """Library name to a filesystem-friendly folder name."""
    return safe_filename(library.replace(" ", "_")) or SHARED_LIBRARY


def variable_page_path(vault: str | Path, name: str, library: str = SHARED_LIBRARY) -> Path:
    """Where a variable page lives inside a vault."""
    first = name[0].upper() if name else "_"
    bucket = first if first.isalpha() and first.isascii() else "_"
    return Path(vault) / "Variables" / library_to_folder(library) / bucket / f"{safe_filename(name)}.md"


def indicator_link_prefix(vault: str | Path, page_path: str | Path) -> str:
    """Relative path from a variable page to the vault's ``Indicators`` folder.

    Computed rather than hard-coded: the default layout puts pages three folders deep
    (``Variables/<library>/<letter>/``), but the link must stay correct if the layout
    ever changes.
    """
    target = Path(vault) / "Indicators"
    relative = os.path.relpath(target, Path(page_path).parent)
    return Path(relative).as_posix()


def parse_version_history(text: str) -> list[dict[str, str]]:
    """Read the ``version_history`` list from an existing page's frontmatter.

    Only the shape this module writes is understood; anything else is ignored, so a
    hand-edited page degrades to "history starts here" instead of crashing.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), -1)
    if end < 0:
        return []

    frontmatter = lines[1:end]
    try:
        start = next(i for i, line in enumerate(frontmatter) if line.strip() == "version_history:")
    except StopIteration:
        return []

    entries: list[dict[str, str]] = []
    for line in frontmatter[start + 1 :]:
        if not line.startswith("  "):
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            entries.append({})
            stripped = stripped[2:]
        if not entries:
            continue
        match = re.match(r'([a-z_]+):\s*"(.*)"$', stripped)
        if match:
            entries[-1][match.group(1)] = match.group(2).replace('\\"', '"')
    return [entry for entry in entries if entry.get("date")]


def render_variable_page(
    name: str,
    description: str = "",
    formulas: Sequence[str] = (),
    indicators: Sequence[str] = (),
    references: Sequence[str] = (),
    referenced_by: Sequence[str] = (),
    library: str = SHARED_LIBRARY,
    version_history: Sequence[dict[str, str]] = (),
    metadata: dict[str, str] | None = None,
    deprecated: bool = False,
    mermaid_limit: int = 10,
    indicator_prefix: str = "../../../Indicators",
) -> str:
    """Render one variable page.

    Args:
        formulas: Definition blocks, in the order Prophet returned them.
        indicators: ``INDICATOREXPR`` values that gate this variable.
        references: Variables this definition reads.
        referenced_by: Variables whose definitions read this one.
        version_history: ``{date, change, old, new}`` entries, newest first.
        metadata: Extra frontmatter keys (``datatype``, ``is_array`` ...).
        deprecated: Mark the page as removed from the model but keep it readable.
        mermaid_limit: Cap graph edges per direction so a hub variable stays legible.
        indicator_prefix: Relative path from the page to the ``Indicators`` folder.
            Variable pages sit three levels deep, which is where the default comes
            from; callers that use another layout pass the value from
            :func:`indicator_link_prefix`.
    """
    metadata = metadata or {}
    tags = ["variable"]
    if deprecated:
        tags.append("deprecated")

    lines: list[str] = ["---", f"name: {name}", f"description: {yaml_string(description)}"]
    for key, value in metadata.items():
        lines.append(f"{key}: {value}")
    lines.append(f"library: {library}")
    lines.append(f"tags: [{', '.join(tags)}]")
    if version_history:
        lines.append("version_history:")
        for entry in version_history:
            lines.append(f'  - date: "{entry.get("date", "")}"')
            lines.append(f'    change: "{entry.get("change", "")}"')
            if entry.get("old"):
                lines.append(f'    old: {yaml_string(entry["old"][:200])}')
            if entry.get("new"):
                lines.append(f'    new: {yaml_string(entry["new"][:200])}')
    lines += ["---", "", f"# {name}", ""]

    if description:
        lines += [f"> {description}", ""]

    if deprecated:
        lines += ["> [!warning] Deprecated", "> This variable is no longer defined in the model.", ""]

    if formulas:
        lines += ["## Definition", ""]
        for formula in formulas:
            lines += ["```prophet", formula.rstrip(), "```", ""]

    if indicators:
        lines += ["## Indicators", ""]
        for indicator in list(dict.fromkeys(indicators)):
            lines.append(f"- [{indicator}]({indicator_prefix}/{safe_filename(indicator)}.md)")
        lines.append("")

    if references:
        lines += ["## References", "", "Variables this definition reads:", ""]
        lines += [f"- [[{ref}]]" for ref in sorted(references)]
        lines.append("")

    if referenced_by:
        lines += ["## Referenced by", "", "Variables whose definitions read this one:", ""]
        lines += [f"- [[{user}]]" for user in sorted(referenced_by)]
        lines.append("")

    if references or referenced_by:
        lines += ["## Dependency graph", "", "```mermaid", "graph LR"]
        for ref in sorted(references)[:mermaid_limit]:
            lines.append(f"    {ref} --> {name}")
        for user in sorted(referenced_by)[:mermaid_limit]:
            lines.append(f"    {name} --> {user}")
        lines += ["```", ""]

    return "\n".join(lines)


def render_indicator_page(name: str, description: str = "", code: str = "", used_by: Sequence[str] = ()) -> str:
    """Render an indicator page with a Dataview query for its consumers."""
    lines = ["---", f"name: {name}", f"description: {yaml_string(description)}", "tags: [indicator]", "---", "", f"# {name}", ""]
    if description:
        lines += [f"> {description}", ""]
    if code:
        lines += ["Code:", "", "```prophet", code, "```", ""]

    lines += ["## Variables gated by this indicator", ""]
    if used_by:
        lines += [f"- [[{var}]]" for var in sorted(used_by)]
    else:
        lines += ["```dataview", "LIST", 'FROM "Variables"', f'WHERE contains(indicators, "{name}")', "```"]
    lines.append("")
    return "\n".join(lines)


def render_overview(snapshot: Snapshot) -> str:
    """Render the vault's map-of-content page."""
    variables = snapshot.variable_names()
    with_formulas = {row["VAR_NAME"] for row in snapshot.formula_hashes if row.get("FORMULA_HASH")}
    with_refs = {row["VAR_NAME"] for row in snapshot.references if row.get("REFERENCES")}
    library_counts = Counter(snapshot.library_by_name().values())

    lines = [
        "---",
        "tags: [MOC, index]",
        "---",
        "",
        "# Model overview",
        "",
        f"> Snapshot: `{snapshot.label()}`",
        f"> Variables: {len(variables):,}",
        f"> With formulas: {len(with_formulas):,}",
        f"> With dependencies: {len(with_refs):,}",
        f"> Libraries: {len(library_counts)}",
        "",
        "## Variables per library",
        "",
        "| Library | Variables |",
        "|---------|-----------|",
    ]
    for library, count in sorted(library_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {library} | {count:,} |")

    lines += [
        "",
        "## Most referenced variables",
        "",
        "```dataview",
        'TABLE description, length(referenced_by) AS "Referenced by"',
        'FROM "Variables"',
        "SORT length(referenced_by) DESC",
        "LIMIT 50",
        "```",
        "",
        "## All variables",
        "",
        "```dataview",
        'TABLE description, library, length(references) AS "References"',
        'FROM "Variables"',
        "SORT name ASC",
        "```",
        "",
        "## Browse",
        "",
        "- `Variables/` - one page per variable, grouped by library and initial",
        "- `Indicators/` - one page per indicator condition",
        "- `_Index/CHANGELOG.md` - change history",
        "",
    ]
    return "\n".join(lines)


def render_changelog(diff: Diff, today: date | None = None) -> str:
    """Render a changelog section for one update."""
    today = today or date.today()
    summary = diff.summary()
    lines = [
        f"## {today.isoformat()} ({diff.old_label} -> {diff.new_label})",
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
    if diff.added:
        lines += [f"### Added ({len(diff.added)})", ""]
        lines += [f"- [[{name}]]" for name in diff.added[:50]]
        if len(diff.added) > 50:
            lines.append(f"- ... and {len(diff.added) - 50} more")
        lines.append("")
    if diff.formula_changed:
        lines += [f"### Formula changes ({len(diff.formula_changed)})", ""]
        lines += [f"- [[{item['name']}]]" for item in diff.formula_changed[:40]]
        if len(diff.formula_changed) > 40:
            lines.append(f"- ... and {len(diff.formula_changed) - 40} more")
        lines.append("")
    return "\n".join(lines)


def _ensure_obsidian_config(vault: Path) -> None:
    obsidian = vault / OBSIDIAN_DIR
    obsidian.mkdir(parents=True, exist_ok=True)
    write_text(
        obsidian / "app.json",
        '{\n  "useMarkdownLinks": false,\n  "newLinkFormat": "shortest"\n}\n',
    )
    write_text(
        obsidian / "core-plugins.json",
        '[\n  "file-explorer",\n  "global-search",\n  "graph",\n  "backlink",\n'
        '  "outgoing-link",\n  "page-preview",\n  "command-palette"\n]\n',
    )


def prepare_vault_dir(vault: str | Path, force: bool = False) -> Path:
    """Create the vault folder, or replace an existing one only when ``force``."""
    vault = Path(vault)
    if vault.exists():
        if not vault.is_dir():
            raise VaultError(f"{vault} exists and is not a directory")
        has_content = any(vault.iterdir())
        if has_content and not force:
            raise VaultError(
                f"{vault} is not empty. Pass --force to regenerate it, or choose a new "
                "folder: this command deletes the old vault."
            )
        if has_content:
            shutil.rmtree(vault)
    vault.mkdir(parents=True, exist_ok=True)
    return vault


def write_vault(
    snapshot: Snapshot,
    vault: str | Path,
    force: bool = False,
    progress=None,
) -> dict[str, int]:
    """Generate a complete vault from a snapshot.

    Returns counts of the pages written.
    """
    notify = progress or (lambda _message: None)
    vault = prepare_vault_dir(vault, force=force)

    (vault / "Variables").mkdir(exist_ok=True)
    (vault / "Indicators").mkdir(exist_ok=True)
    (vault / "_Index").mkdir(exist_ok=True)
    _ensure_obsidian_config(vault)

    library_by_name = snapshot.library_by_name()
    description_by_name = snapshot.description_by_name()
    formulas_by_name = snapshot.formulas_by_name()
    references_by_name = snapshot.references_by_name()
    referenced_by = snapshot.referenced_by()

    notify(f"variables: {len(snapshot.variables)}")
    for row in snapshot.variables:
        name = row["NAME"]
        library = library_by_name.get(name, SHARED_LIBRARY)
        records = formulas_by_name.get(name, [])
        path = variable_page_path(vault, name, library)
        page = render_variable_page(
            name=name,
            description=description_by_name.get(name, ""),
            formulas=[record.get("FORMULA", "") for record in records if record.get("FORMULA")],
            indicators=[record.get("INDICATOREXPR", "") for record in records if record.get("INDICATOREXPR")],
            references=references_by_name.get(name, []),
            referenced_by=referenced_by.get(name, []),
            library=library,
            metadata={
                "datatype": row.get("DATATYPE") or '""',
                "num_dimensions": row.get("NUMDIMENSIONS") or '""',
                "is_array": row.get("ISARRAY") or '""',
            },
            indicator_prefix=indicator_link_prefix(vault, path),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, page)

    # Indicator pages: declared indicators plus any name mentioned in an expression.
    indicator_names: set[str] = {row["NAME"] for row in snapshot.indicators if row.get("NAME")}
    consumers: dict[str, set[str]] = {}
    for record in snapshot.formulas:
        expression = record.get("INDICATOREXPR", "")
        if not expression:
            continue
        for part in re.split(r"\bAND\b", expression):
            cleaned = part.replace("NOT ", "").replace("(", "").replace(")", "").strip()
            if cleaned:
                indicator_names.add(cleaned)
                consumers.setdefault(cleaned, set()).add(record["VAR_NAME"])

    declared = {row["NAME"]: row for row in snapshot.indicators if row.get("NAME")}
    for name in sorted(indicator_names):
        info = declared.get(name, {})
        page = render_indicator_page(
            name=name,
            description=info.get("DESCRIPTION", ""),
            code=info.get("CODE", ""),
            used_by=sorted(consumers.get(name, set())),
        )
        write_text(vault / "Indicators" / f"{safe_filename(name)}.md", page)

    write_text(vault / OVERVIEW_PATH, render_overview(snapshot))
    write_text(
        vault / CHANGELOG_PATH,
        "# Changelog\n\n"
        + f"## {date.today().isoformat()} (initial build from `{snapshot.label()}`)\n\n"
        f"- Variables: {len(snapshot.variables):,}\n"
        f"- Formula blocks: {len(snapshot.formulas):,}\n"
        f"- Indicators: {len(indicator_names):,}\n",
    )

    counts = {
        "variables": len(snapshot.variables),
        "indicators": len(indicator_names),
        "libraries": len(set(library_by_name.values())) or 1,
    }
    notify(f"done: {counts}")
    return counts


def _history_entry(
    change: str,
    today: str,
    old: str = "",
    new: str = "",
) -> dict[str, str]:
    entry = {"date": today, "change": change}
    if old:
        entry["old"] = old
    if new:
        entry["new"] = new
    return entry


def apply_diff(
    diff: Diff,
    vault: str | Path,
    snapshot: Snapshot,
    today: date | None = None,
    backup: bool = True,
    progress=None,
) -> dict[str, int]:
    """Update an existing vault from a diff, re-rendering only changed pages."""
    notify = progress or (lambda _message: None)
    vault = Path(vault)
    if not vault.is_dir():
        raise VaultError(f"vault not found: {vault}")

    stamp = (today or date.today()).isoformat()
    if backup:
        backup_dir = vault.parent / f"{vault.name}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        notify(f"backup: {backup_dir.name}")
        shutil.copytree(vault, backup_dir)

    library_by_name = snapshot.library_by_name()
    description_by_name = snapshot.description_by_name()
    formulas_by_name = snapshot.formulas_by_name()
    references_by_name = snapshot.references_by_name()
    referenced_by = snapshot.referenced_by()

    changed_names: dict[str, str] = {}
    for item in diff.formula_changed:
        changed_names[item["name"]] = "FORMULA_CHANGED"
    for item in diff.desc_changed:
        changed_names.setdefault(item["name"], "DESCRIPTION_CHANGED")
    for item in diff.indicator_changed:
        changed_names.setdefault(item["name"], "INDICATOR_CHANGED")
    for item in diff.refs_changed:
        changed_names.setdefault(item["name"], "REFERENCES_CHANGED")
    for name in diff.added:
        changed_names[name] = "NEW"
    for name in diff.deleted:
        changed_names[name] = "DEPRECATED"

    counts = {"added": 0, "updated": 0, "deprecated": 0, "unchanged_skipped": max(diff.unchanged, 0)}

    def write_page(name: str, change: str, deprecated: bool) -> None:
        library = library_by_name.get(name, SHARED_LIBRARY)
        path = variable_page_path(vault, name, library)
        history: list[dict[str, str]] = []
        if path.exists():
            history = parse_version_history(path.read_text(encoding="utf-8"))
        if change == "FORMULA_CHANGED":
            entry = _history_entry(
                change,
                stamp,
                old=_formula_text_for(diff, name, "old_formula"),
                new=_formula_text_for(diff, name, "new_formula"),
            )
        elif change in {"NEW", "DEPRECATED"}:
            entry = _history_entry(change, stamp)
        else:
            entry = _history_entry(change, stamp)
        history = [entry, *history][:MAX_HISTORY_ENTRIES]

        records = formulas_by_name.get(name, [])
        page = render_variable_page(
            name=name,
            description=description_by_name.get(name, ""),
            formulas=[record.get("FORMULA", "") for record in records if record.get("FORMULA")],
            indicators=[record.get("INDICATOREXPR", "") for record in records if record.get("INDICATOREXPR")],
            references=references_by_name.get(name, []),
            referenced_by=referenced_by.get(name, []),
            library=library,
            version_history=history,
            deprecated=deprecated,
            indicator_prefix=indicator_link_prefix(vault, path),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, page)

    for name in diff.added:
        write_page(name, "NEW", deprecated=False)
        counts["added"] += 1

    for name in diff.deleted:
        write_page(name, "DEPRECATED", deprecated=True)
        counts["deprecated"] += 1

    for name, change in changed_names.items():
        if name in diff.added or name in diff.deleted:
            continue
        write_page(name, change, deprecated=False)
        counts["updated"] += 1

    # Changelog: insert the newest entry directly after the title.
    changelog_path = vault / CHANGELOG_PATH
    section = render_changelog(diff, today=today)
    if changelog_path.exists():
        existing = changelog_path.read_text(encoding="utf-8")
        marker = existing.find("\n## ")
        updated = existing[:marker] + "\n" + section + existing[marker:] if marker >= 0 else existing + "\n" + section
    else:
        updated = "# Changelog\n\n" + section
    changelog_path.parent.mkdir(parents=True, exist_ok=True)
    write_text(changelog_path, updated)

    write_text(vault / OVERVIEW_PATH, render_overview(snapshot))

    notify(f"done: {counts}")
    return counts


def _formula_text_for(diff: Diff, name: str, key: str) -> str:
    for item in diff.formula_changed:
        if item["name"] == name:
            return item.get(key, "")
    return ""


def iter_pages(vault: str | Path) -> Iterable[Path]:
    """Yield every variable page in a vault (used by tests and audits)."""
    variables = Path(vault) / "Variables"
    if not variables.is_dir():
        return []
    return (path for path in variables.rglob("*.md") if path.is_file())
