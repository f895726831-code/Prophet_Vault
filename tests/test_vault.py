"""Tests for Obsidian vault rendering and incremental updates."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from prophet_vault.diff import compare
from prophet_vault.snapshot import Snapshot
from prophet_vault.vault import (
    OVERVIEW_PATH,
    CHANGELOG_PATH,
    VaultError,
    apply_diff,
    library_to_folder,
    parse_version_history,
    prepare_vault_dir,
    render_indicator_page,
    render_overview,
    render_variable_page,
    safe_filename,
    variable_page_path,
    write_vault,
    yaml_string,
)


# ------------------------------------------------------------------ rendering
def test_render_variable_page_contains_all_sections():
    page = render_variable_page(
        name="TEST_VAR",
        description="A test variable",
        formulas=["X + Y"],
        indicators=["ALWAYS"],
        references=["X", "Y"],
        referenced_by=["Z"],
        library="IFRS17",
    )
    assert page.startswith("---\n")
    assert "name: TEST_VAR" in page
    assert 'description: "A test variable"' in page
    assert "library: IFRS17" in page
    assert "tags: [variable]" in page
    assert "```prophet\nX + Y\n```" in page
    assert "[[X]]" in page and "[[Y]]" in page and "[[Z]]" in page
    assert "graph LR" in page
    assert "../../../Indicators/ALWAYS.md" in page


def test_indicator_prefix_matches_page_depth():
    from prophet_vault.vault import indicator_link_prefix

    vault = Path("vault")
    deep = vault / "Variables" / "IFRS17" / "N" / "VAR.md"
    assert indicator_link_prefix(vault, deep) == "../../../Indicators"


def test_render_variable_page_omits_empty_sections():
    page = render_variable_page(name="EMPTY_VAR")
    assert "# EMPTY_VAR" in page
    assert "## Definition" not in page
    assert "## References" not in page
    assert "## Dependency graph" not in page


def test_render_variable_page_marks_deprecated():
    page = render_variable_page(name="OLD_VAR", deprecated=True)
    assert "tags: [variable, deprecated]" in page
    assert "Deprecated" in page


def test_render_variable_page_version_history():
    page = render_variable_page(
        name="A",
        version_history=[
            {"date": "2026-08-03", "change": "FORMULA_CHANGED", "old": "X", "new": "X + Y"},
            {"date": "2026-07-01", "change": "NEW"},
        ],
    )
    assert "version_history:" in page
    assert '  - date: "2026-08-03"' in page
    assert '    change: "FORMULA_CHANGED"' in page
    assert '    old: "X"' in page


def test_mermaid_edges_are_capped():
    refs = [f"UP_{index}" for index in range(30)]
    page = render_variable_page(name="HUB", references=refs, mermaid_limit=5)
    assert page.count("UP_") >= 5
    assert "UP_9 --> HUB" not in page


def test_yaml_string_escapes_quotes_and_backslashes():
    assert yaml_string('say "hi"') == '"say \\"hi\\""'
    assert yaml_string("a\\b") == '"a\\\\b"'
    assert yaml_string(None) == '""'
    assert yaml_string("multi\nline") == '"multi line"'


def test_safe_filename_strips_illegal_characters():
    assert safe_filename("A/B:C*D?E") == "A_B_C_D_E"
    assert safe_filename('quote"name') == "quote_name"
    assert safe_filename("   ") == "_"


def test_library_folder_replaces_spaces():
    assert library_to_folder("Unit Linked") == "Unit_Linked"
    assert library_to_folder("IFRS17") == "IFRS17"


def test_variable_page_path_layout(tmp_path: Path):
    path = variable_page_path(tmp_path, "NET_CF", "Unit Linked")
    assert path == tmp_path / "Variables" / "Unit_Linked" / "N" / "NET_CF.md"


def test_variable_page_path_non_alphabetic(tmp_path: Path):
    path = variable_page_path(tmp_path, "_HIDDEN", "Summary")
    assert path.name == "_HIDDEN.md"
    assert path.parent.name == "_"


def test_render_indicator_page_with_consumers():
    page = render_indicator_page("IFRS17", description="IFRS only", code="IND_001", used_by=["A", "B"])
    assert "[[A]]" in page and "[[B]]" in page
    assert "IND_001" in page
    assert "dataview" not in page


def test_render_indicator_page_without_consumers_uses_dataview():
    page = render_indicator_page("ORPHAN")
    assert "dataview" in page


# ------------------------------------------------------------------ build
def test_write_vault_structure(tmp_path: Path, new_snapshot: Snapshot):
    vault = tmp_path / "vault"
    counts = write_vault(new_snapshot, vault)

    assert counts["variables"] == len(new_snapshot.variables)
    assert (vault / "_Index" / "00-Overview.md").exists()
    assert (vault / CHANGELOG_PATH).exists()
    assert (vault / ".obsidian" / "app.json").exists()
    assert (vault / "Indicators").is_dir()
    assert any((vault / "Variables").iterdir())


def test_overview_counts_appear(tmp_path: Path, new_snapshot: Snapshot):
    vault = tmp_path / "vault"
    write_vault(new_snapshot, vault)
    text = (vault / OVERVIEW_PATH).read_text(encoding="utf-8")
    assert "# Model overview" in text
    assert f"{len(new_snapshot.variables):,}" in text
    assert "Variables per library" in text


def test_render_overview_has_dataview_queries(new_snapshot: Snapshot):
    text = render_overview(new_snapshot)
    assert text.count("```dataview") == 2


def test_write_vault_refuses_existing_directory(tmp_path: Path, new_snapshot: Snapshot):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "keep.txt").write_text("do not delete me", encoding="utf-8")

    with pytest.raises(VaultError, match="not empty"):
        write_vault(new_snapshot, vault)
    assert (vault / "keep.txt").exists()


def test_write_vault_force_replaces(tmp_path: Path, new_snapshot: Snapshot):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "stale.txt").write_text("old", encoding="utf-8")

    write_vault(new_snapshot, vault, force=True)
    assert not (vault / "stale.txt").exists()
    assert (vault / OVERVIEW_PATH).exists()


def test_prepare_vault_dir_rejects_a_file(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(VaultError):
        prepare_vault_dir(target)


# ------------------------------------------------------------------ update
def test_apply_diff_updates_changed_pages(tmp_path: Path, old_snapshot: Snapshot, new_snapshot: Snapshot):
    vault = tmp_path / "vault"
    write_vault(old_snapshot, vault)
    diff = compare(old_snapshot, new_snapshot)

    counts = apply_diff(diff, vault, new_snapshot, today=date(2026, 3, 1))

    assert counts["added"] == len(diff.added)
    assert counts["deprecated"] == len(diff.deleted)
    assert counts["updated"] >= 1

    added_page = variable_page_path(vault, "NEW_FEATURE_A", "IFRS17")
    assert added_page.exists()
    assert 'change: "NEW"' in added_page.read_text(encoding="utf-8")

    removed_page = next(vault.rglob("FLOW_007.md"))
    text = removed_page.read_text(encoding="utf-8")
    assert "deprecated" in text

    changelog = (vault / CHANGELOG_PATH).read_text(encoding="utf-8")
    assert "2026-03-01" in changelog
    assert changelog.index("2026-03-01") < changelog.index("initial build")


def test_apply_diff_merges_version_history(tmp_path: Path, old_snapshot: Snapshot, new_snapshot: Snapshot):
    vault = tmp_path / "vault"
    write_vault(old_snapshot, vault)
    diff = compare(old_snapshot, new_snapshot)

    apply_diff(diff, vault, new_snapshot, today=date(2026, 3, 1))
    apply_diff(diff, vault, new_snapshot, today=date(2026, 4, 1), backup=False)

    page = variable_page_path(vault, "FLOW_010", "Summary")
    if not page.exists():
        page = next(vault.rglob("FLOW_010.md"))
    history = parse_version_history(page.read_text(encoding="utf-8"))
    dates = [entry["date"] for entry in history]
    assert dates[:2] == ["2026-04-01", "2026-03-01"] or dates[:2] == ["2026-03-01", "2026-04-01"]
    assert len(history) >= 2


def test_apply_diff_makes_a_backup(tmp_path: Path, old_snapshot: Snapshot, new_snapshot: Snapshot):
    vault = tmp_path / "vault"
    write_vault(old_snapshot, vault)
    diff = compare(old_snapshot, new_snapshot)
    apply_diff(diff, vault, new_snapshot)

    backups = [path for path in tmp_path.iterdir() if path.name.startswith("vault.bak.")]
    assert len(backups) == 1
    assert (backups[0] / OVERVIEW_PATH).exists()


def test_apply_diff_without_backup(tmp_path: Path, old_snapshot: Snapshot, new_snapshot: Snapshot):
    vault = tmp_path / "vault"
    write_vault(old_snapshot, vault)
    diff = compare(old_snapshot, new_snapshot)
    apply_diff(diff, vault, new_snapshot, backup=False)
    assert not [path for path in tmp_path.iterdir() if path.name.startswith("vault.bak.")]


def test_apply_diff_requires_existing_vault(tmp_path: Path, new_snapshot: Snapshot):
    with pytest.raises(VaultError, match="vault not found"):
        apply_diff(compare(new_snapshot, new_snapshot), tmp_path / "absent", new_snapshot)


def test_apply_diff_is_idempotent_in_content(tmp_path: Path, old_snapshot: Snapshot, new_snapshot: Snapshot):
    vault = tmp_path / "vault"
    write_vault(old_snapshot, vault)
    diff = compare(old_snapshot, new_snapshot)
    apply_diff(diff, vault, new_snapshot, today=date(2026, 3, 1), backup=False)
    first = variable_page_path(vault, "AGG_004", "Conventional")
    path = first if first.exists() else next(vault.rglob("AGG_004.md"))
    before = path.read_text(encoding="utf-8")
    apply_diff(diff, vault, new_snapshot, today=date(2026, 3, 1), backup=False)
    after = path.read_text(encoding="utf-8")
    # The history entry is re-added, so compare the body only.
    assert before.split("---", 2)[2] == after.split("---", 2)[2]


def test_parse_version_history_on_page_without_frontmatter():
    assert parse_version_history("# Just a heading\n") == []


def test_parse_version_history_roundtrip():
    page = render_variable_page(
        name="X",
        version_history=[{"date": "2026-01-01", "change": "NEW"}],
    )
    entries = parse_version_history(page)
    assert entries == [{"date": "2026-01-01", "change": "NEW"}]


def test_every_wikilink_resolves(tmp_path: Path, new_snapshot: Snapshot):
    """A generated vault must never contain a link to a page that does not exist."""
    import re

    vault = tmp_path / "vault"
    write_vault(new_snapshot, vault)
    page_names = {path.stem for path in vault.rglob("*.md")}

    unresolved: set[str] = set()
    for page in (vault / "Variables").rglob("*.md"):
        text = page.read_text(encoding="utf-8")
        for link in re.findall(r"\[\[([^\]]+)\]\]", text):
            if link not in page_names:
                unresolved.add(link)
    assert unresolved == set()


def test_indicator_links_resolve(tmp_path: Path, new_snapshot: Snapshot):
    """Indicator links are relative, so they must resolve from the page's own folder."""
    import re

    vault = tmp_path / "vault"
    write_vault(new_snapshot, vault)
    checked = 0
    for page in (vault / "Variables").rglob("*.md"):
        text = page.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]*Indicators/[^)]+)\)", text):
            resolved = (page.parent / target).resolve()
            assert resolved.exists(), f"{page.name} -> {target}"
            checked += 1
    assert checked > 0
