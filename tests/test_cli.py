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


def test_extract_rci_warns_on_bad_header(tmp_path: Path, capsys):
    from helpers import build_rci_bytes

    bad = tmp_path / "VAR_LIST.RCI"
    bad.write_bytes(build_rci_bytes([("SOME_VAR", "description")], broken_magic=True))
    assert main(["extract-rci", "--rci", str(bad), "--out", str(tmp_path)]) == 0
    assert "does not look like" in capsys.readouterr().err


def test_snapshot_requires_configuration(tmp_path: Path, capsys):
    code = main(["snapshot", "--label", "x", "--prw", str(tmp_path / "absent.PRW")])
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_diff_command(tmp_path: Path, snapshot_dir: Path, old_snapshot):
    old_dir = old_snapshot.save(tmp_path / "old")
    output = tmp_path / "diff.json"
    assert main(["diff", "--old", str(old_dir), "--new", str(snapshot_dir), "--output", str(output)]) == 0
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

    assert main(["build-vault", "--snapshot", str(snapshot_dir), "--vault", str(vault), "--force"]) == 0
    assert not (vault / "keep.txt").exists()


def test_update_vault_command(tmp_path: Path, old_snapshot, snapshot_dir: Path, capsys):
    vault = tmp_path / "vault"
    assert main(["build-vault", "--snapshot", str(old_snapshot.save(tmp_path / "old")), "--vault", str(vault)]) == 0

    diff_path = tmp_path / "diff.json"
    assert main(
        [
            "diff",
            "--old",
            str(tmp_path / "old"),
            "--new",
            str(snapshot_dir),
            "--output",
            str(diff_path),
        ]
    ) == 0

    assert main(
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
    ) == 0
    assert "vault updated" in capsys.readouterr().out


def test_graph_command(tmp_path: Path, snapshot_dir: Path):
    destination = tmp_path / "graph.html"
    assert main(["graph", "--snapshot", str(snapshot_dir), "-o", str(destination)]) == 0
    assert destination.exists()


def test_graph_command_reports_missing_snapshot(tmp_path: Path, capsys):
    code = main(["graph", "--snapshot", str(tmp_path / "absent"), "-o", str(tmp_path / "g.html")])
    assert code == 2
    assert "error:" in capsys.readouterr().err
