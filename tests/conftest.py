"""Shared fixtures: synthetic snapshots, generated without any Prophet install."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import build_rci_bytes

from prophet_vault.demo import DemoOptions, generate_twin_model
from prophet_vault.snapshot import Snapshot


@pytest.fixture(scope="session")
def demo_models():
    """A pair of synthetic models two "months" apart."""
    return generate_twin_model(DemoOptions(seed=11))


@pytest.fixture(scope="session")
def old_snapshot(demo_models) -> Snapshot:
    old, _new = demo_models
    return Snapshot.build(old, label="2026-01_demo")


@pytest.fixture(scope="session")
def new_snapshot(demo_models) -> Snapshot:
    _old, new = demo_models
    return Snapshot.build(new, label="2026-02_demo")


@pytest.fixture()
def snapshot_dir(tmp_path: Path, new_snapshot: Snapshot) -> Path:
    """Persist the current demo snapshot and return its folder."""
    return new_snapshot.save(tmp_path / "snapshots" / "2026-02_demo")


@pytest.fixture()
def rci_file(tmp_path: Path) -> Path:
    blob = build_rci_bytes(
        [
            ("AGE_AT_ENTRY", "Age at entry of the policy"),
            ("SUM_ASSURED", "Sum assured for the base cover"),
            ("PREMIUM_ANNUAL", "Annualised premium"),
        ]
    )
    path = tmp_path / "VAR_LIST.RCI"
    path.write_bytes(blob)
    return path
