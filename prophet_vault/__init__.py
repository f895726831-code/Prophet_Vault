"""prophet-vault: a knowledge-base toolkit for Prophet actuarial models.

The toolkit reads a Prophet model workspace (a Firebird ``*.PRW`` database plus
optional ``*.RCI`` binary index files), builds a versioned *snapshot* of every
variable, formula and indicator, and renders that snapshot as either an Obsidian
vault or a self-contained dependency-graph HTML page.

Nothing here is Prophet-licensed or Prophet-specific business logic: it only
reads files that already exist on an actuary's machine and writes plain text.

Public entry points are the CLI (``python -m prophet_vault``) and the modules
``rci``, ``isql``, ``extract``, ``snapshot``, ``diff``, ``vault`` and ``graph``.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
