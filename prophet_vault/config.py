"""Configuration: paths and Firebird credentials, resolved from CLI args or env vars.

Precedence, lowest to highest: module defaults < environment variables < explicit
CLI arguments.  Nothing in this package ever writes to a Prophet installation; the
defaults below only point at the conventional install locations so that a first
run needs no arguments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: Conventional Firebird command-line tool location on a Prophet server install.
DEFAULT_ISQL_PATH = Path("C:/Prophet/ProphetServer/ProphetSuite/Firebird_3_0/isql.exe")

#: Firebird ships with this SYSDBA credential for embedded databases.  Override it
#: with ``PROPHET_ISQL_USER`` / ``PROPHET_ISQL_PASS`` if your install differs.
DEFAULT_ISQL_USER = "sysdba"
DEFAULT_ISQL_PASS = "masterkey"

#: Library name used for variables that exist in more than one Prophet library.
SHARED_LIBRARY = "Summary"

ENV_ISQL_PATH = "PROPHET_ISQL_PATH"
ENV_PRW_PATH = "PROPHET_PRW_PATH"
ENV_WORKSPACE_DIR = "PROPHET_WORKSPACE_DIR"
ENV_ISQL_USER = "PROPHET_ISQL_USER"
ENV_ISQL_PASS = "PROPHET_ISQL_PASS"
ENV_OUTPUT_DIR = "PROPHET_OUTPUT_DIR"
ENV_VAULT_DIR = "PROPHET_VAULT_DIR"


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else None


@dataclass
class Settings:
    """Resolved configuration for one run."""

    isql_path: Path | None = None
    prw_path: Path | None = None
    workspace_dir: Path | None = None
    isql_user: str = DEFAULT_ISQL_USER
    isql_password: str = DEFAULT_ISQL_PASS
    output_dir: Path = field(default_factory=lambda: Path("output"))
    vault_dir: Path = field(default_factory=lambda: Path("Prophet_Vault"))

    @classmethod
    def from_env(cls, **overrides: object) -> "Settings":
        """Build settings from environment variables, then apply ``overrides``.

        ``None`` overrides are ignored so that callers can pass ``argparse``
        results through untouched.
        """
        settings = cls(
            isql_path=_env_path(ENV_ISQL_PATH),
            prw_path=_env_path(ENV_PRW_PATH),
            workspace_dir=_env_path(ENV_WORKSPACE_DIR),
            isql_user=os.environ.get(ENV_ISQL_USER, DEFAULT_ISQL_USER),
            isql_password=os.environ.get(ENV_ISQL_PASS, DEFAULT_ISQL_PASS),
            output_dir=_env_path(ENV_OUTPUT_DIR) or Path("output"),
            vault_dir=_env_path(ENV_VAULT_DIR) or Path("Prophet_Vault"),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(settings, key):
                setattr(settings, key, value)
        return settings

    def require_isql(self) -> Path:
        if self.isql_path is None:
            raise ValueError(
                "No isql.exe path configured. Pass --isql, or set "
                f"{ENV_ISQL_PATH} to the Firebird command-line tool."
            )
        return Path(self.isql_path)

    def require_prw(self) -> Path:
        if self.prw_path is None:
            raise ValueError(
                "No PRW path configured. Pass --prw, or set "
                f"{ENV_PRW_PATH} to the Prophet workspace database."
            )
        return Path(self.prw_path)

    def rci_path(self) -> Path:
        """Path of ``VAR_LIST.RCI`` inside the configured workspace."""
        if self.workspace_dir is None:
            raise ValueError(
                "No workspace directory configured. Pass --workspace, or set "
                f"{ENV_WORKSPACE_DIR} to the folder that holds VAR_LIST.RCI."
            )
        return Path(self.workspace_dir) / "VAR_LIST.RCI"
