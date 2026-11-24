"""End-to-end tests for the command-line interface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prophet_vault.cli import main


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "prophet-vault" in capsys.readouterr().out


def test_missing_command_exits(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0


def test_demo_builds_every_artifact(tmp_path: Path, capsys):
    assert main(["demo", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "snapshots:" in out and "graph:" in out

    assert (tmp_path / "snapshots" / "demo_2026-01" / "variables.csv").exists()
    assert (tmp_path / "snapshots" / "demo_2026-02" / "variables.csv").exists()
    assert (tmp_path / "diffs" / "demo_diff.json").exists()
    assert (tmp_path / "diffs" / "demo_diff_report.md").exists()
    assert (tmp_path / "vault" / "_Index" / "00-Overview.md").exists()
    assert (tmp_path / "dependency-graph.html").exists()

    payload = json.loads((tmp_path / "diffs" / "demo_diff.json").read_text(encoding="utf-8"))
    assert payload["summary"]["added"] == 3
    assert payload["summary"]["deleted"] == 1


def test_demo_can_skip_outputs(tmp_path: Path):
    assert main(["demo", "--out", str(tmp_path), "--no-vault", "--no-graph", "--no-diff"]) == 0
    assert (tmp_path / "snapshots").is_dir()
    assert not (tmp_path / "vault").exists()
    assert not (tmp_path / "dependency-graph.html").exists()


def test_extract_rci(tmp_path: Path, rci_file: Path, capsys):
    assert main(["extract-rci", "--rci", str(rci_file), "--out", str(tmp_path)]) == 0
    output = tmp_path / "variables_phase1.csv"
    assert output.exists()
    assert "AGE_AT_ENTRY" in output.read_text(encoding="utf-8-sig")
    assert "3 variables" in capsys.readouterr().out


def test_extract_rci_rejects_bad_header_without_force(tmp_path: Path, capsys):
    from helpers import build_rci_bytes

    bad = tmp_path / "VAR_LIST.RCI"
    bad.write_bytes(build_rci_bytes([("SOME_VAR", "description")], broken_magic=True))

    assert main(["extract-rci", "--rci", str(bad), "--out", str(tmp_path)]) == 2
    assert "does not look like" in capsys.readouterr().err

    assert main(["extract-rci", "--rci", str(bad), "--out", str(tmp_path), "--force"]) == 0
    assert "SOME_VAR" in (tmp_path / "variables_phase1.csv").read_text(encoding="utf-8-sig")


def test_extract_rci_can_use_the_workspace_folder(tmp_path: Path, rci_file: Path, monkeypatch):
    monkeypatch.setenv("PROPHET_WORKSPACE_DIR", str(rci_file.parent))
    assert main(["extract-rci", "--out", str(tmp_path)]) == 0
    assert "AGE_AT_ENTRY" in (tmp_path / "variables_phase1.csv").read_text(encoding="utf-8-sig")


def test_extract_rci_without_a_path_exits_with_an_error(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("PROPHET_WORKSPACE_DIR", raising=False)
    assert main(["extract-rci", "--out", str(tmp_path)]) == 2
    assert "PROPHET_WORKSPACE_DIR" in capsys.readouterr().err


def test_snapshot_requires_configuration(tmp_path: Path, capsys):
    code = main(["snapshot", "--label", "x", "--prw", str(tmp_path / "absent.PRW")])
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_diff_command(tmp_path: Path, snapshot_dir: Path, old_snapshot):
    old_dir = old_snapshot.save(tmp_path / "old")
    output = tmp_path / "diff.json"
    assert (
        main(["diff", "--old", str(old_dir), "--new", str(snapshot_dir), "--output", str(output)])
        == 0
    )
    assert output.exists()
    assert output.with_name("diff_report.md").exists()


def test_build_vault_command(tmp_path: Path, snapshot_dir: Path):
    vault = tmp_path / "vault"
    assert main(["build-vault", "--snapshot", str(snapshot_dir), "--vault", str(vault)]) == 0
    assert (vault / "_Index" / "00-Overview.md").exists()


def test_build_vault_refuses_non_empty_without_force(tmp_path: Path, snapshot_dir: Path, capsys):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "keep.txt").write_text("x", encoding="utf-8")

    assert main(["build-vault", "--snapshot", str(snapshot_dir), "--vault", str(vault)]) == 2
    assert "not empty" in capsys.readouterr().err
    assert (vault / "keep.txt").exists()

    assert (
        main(["build-vault", "--snapshot", str(snapshot_dir), "--vault", str(vault), "--force"])
        == 0
    )
    assert not (vault / "keep.txt").exists()


def test_update_vault_command(tmp_path: Path, old_snapshot, snapshot_dir: Path, capsys):
    vault = tmp_path / "vault"
    assert (
        main(
            [
                "build-vault",
                "--snapshot",
                str(old_snapshot.save(tmp_path / "old")),
                "--vault",
                str(vault),
            ]
        )
        == 0
    )

    diff_path = tmp_path / "diff.json"
    assert (
        main(
            [
                "diff",
                "--old",
                str(tmp_path / "old"),
                "--new",
                str(snapshot_dir),
                "--output",
                str(diff_path),
            ]
        )
        == 0
    )

    assert (
        main(
            [
                "update-vault",
                "--diff",
                str(diff_path),
                "--vault",
                str(vault),
                "--snapshot",
                str(snapshot_dir),
                "--no-backup",
            ]
        )
        == 0
    )
    assert "vault updated" in capsys.readouterr().out


def test_graph_command(tmp_path: Path, snapshot_dir: Path):
    destination = tmp_path / "graph.html"
    assert main(["graph", "--snapshot", str(snapshot_dir), "-o", str(destination)]) == 0
    assert destination.exists()


def test_graph_command_reports_missing_snapshot(tmp_path: Path, capsys):
    code = main(["graph", "--snapshot", str(tmp_path / "absent"), "-o", str(tmp_path / "g.html")])
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_update_vault_applies_every_change_in_a_large_diff(tmp_path: Path):
    """Regression: a capped diff report silently left pages stale."""
    from prophet_vault.snapshot import Snapshot

    count = 220

    def build(hash_prefix: str, label: str) -> Snapshot:
        variables = [
            {
                "NAME": f"V{index:03d}",
                "DESCRIPTION": "d",
                "DATATYPE": "0",
                "NUMDIMENSIONS": "0",
                "ISARRAY": "0",
                "LIBRARY": "Summary",
            }
            for index in range(count)
        ]
        formulas = [
            {
                "VAR_NAME": f"V{index:03d}",
                "FORMULA": f"X{index}" if hash_prefix == "a" else f"X{index} + 1",
                "INDICATOREXPR": "ALWAYS",
            }
            for index in range(count)
        ]
        hashes = [
            {"VAR_NAME": f"V{index:03d}", "FORMULA_HASH": f"{hash_prefix}{index:03d}"}
            for index in range(count)
        ]
        return Snapshot(
            variables=variables,
            formulas=formulas,
            indicators=[],
            dimensions=[],
            formula_hashes=hashes,
            references=[],
            library_map=[],
            metadata={"label": label, "total_variables": count},
        )

    old_dir = build("a", "old").save(tmp_path / "old")
    new_dir = build("b", "new").save(tmp_path / "new")
    vault = tmp_path / "vault"
    assert main(["build-vault", "--snapshot", str(old_dir), "--vault", str(vault)]) == 0

    diff_path = tmp_path / "diff.json"
    assert (
        main(["diff", "--old", str(old_dir), "--new", str(new_dir), "--output", str(diff_path)])
        == 0
    )
    payload = json.loads(diff_path.read_text(encoding="utf-8"))
    assert len(payload["formula_changed"]) == count

    assert (
        main(
            [
                "update-vault",
                "--diff",
                str(diff_path),
                "--vault",
                str(vault),
                "--snapshot",
                str(new_dir),
                "--no-backup",
            ]
        )
        == 0
    )

    with_history = sum(
        1
        for page in (vault / "Variables").rglob("*.md")
        if "version_history" in page.read_text(encoding="utf-8")
    )
    assert with_history == count


def test_update_vault_warns_when_the_report_is_incomplete(tmp_path: Path, capsys):
    snapshot_dir = _demo_snapshot_dir(tmp_path)
    vault = tmp_path / "vault"
    assert main(["build-vault", "--snapshot", str(snapshot_dir), "--vault", str(vault)]) == 0

    incomplete = {
        "old_label": "old",
        "new_label": "new",
        "summary": {"formula_changed": 5, "unchanged": 100},
        "added": [],
        "deleted": [],
        "desc_changed": [],
        "formula_changed": [{"name": "FLOW_001", "old_formula": "a", "new_formula": "b"}],
        "indicator_changed": [],
        "refs_changed": [],
    }
    diff_path = tmp_path / "incomplete.json"
    diff_path.write_text(json.dumps(incomplete), encoding="utf-8")

    assert (
        main(
            [
                "update-vault",
                "--diff",
                str(diff_path),
                "--vault",
                str(vault),
                "--snapshot",
                str(snapshot_dir),
                "--no-backup",
            ]
        )
        == 0
    )
    assert "4 change(s) will not be applied" in capsys.readouterr().err


def _demo_snapshot_dir(tmp_path: Path) -> Path:
    from prophet_vault.demo import DemoOptions, generate_twin_model
    from prophet_vault.snapshot import Snapshot

    _old, new = generate_twin_model(
        DemoOptions(seed=3, inputs_per_group=2, derived=8, aggregates=4, results=3)
    )
    return Snapshot.build(new, label="demo").save(tmp_path / "snapshot")


def test_build_vault_defaults_to_the_env_vault_dir(tmp_path: Path, snapshot_dir: Path, monkeypatch):
    monkeypatch.setenv("PROPHET_VAULT_DIR", str(tmp_path / "env_vault"))
    assert main(["build-vault", "--snapshot", str(snapshot_dir)]) == 0
    assert (tmp_path / "env_vault" / "_Index" / "00-Overview.md").exists()


def test_graph_uses_the_env_output_dir(tmp_path: Path, snapshot_dir: Path, monkeypatch):
    out = tmp_path / "env_out"
    target = out / "snapshots" / "2026-02_demo"
    target.parent.mkdir(parents=True)
    snapshot_dir.replace(target)

    monkeypatch.setenv("PROPHET_OUTPUT_DIR", str(out))
    assert main(["graph"]) == 0
    assert (out / "dependency-graph.html").exists()


def test_diff_defaults_under_the_output_dir(tmp_path: Path, snapshot_dir: Path, monkeypatch):
    out = tmp_path / "env_out"
    monkeypatch.setenv("PROPHET_OUTPUT_DIR", str(out))
    assert main(["diff", "--old", str(snapshot_dir), "--new", str(snapshot_dir)]) == 0
    assert (out / "diffs" / "latest_diff.json").exists()
