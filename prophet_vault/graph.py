"""Render a snapshot's dependency graph as one self-contained HTML page.

Why not Obsidian's graph view
-----------------------------
Obsidian's built-in graph becomes unusable above roughly 10,000 nodes: it lays out
the whole model at once and re-runs the simulation on every pan.  This renderer takes
the opposite approach: it ships the dependency lists, and the browser draws only the
*focus variable plus N hops* (N = 1..3).  A 15,000-variable model renders instantly,
and because the page is a single HTML file it can be attached to a review, a change
ticket or an audit pack.

Data contract
-------------
``NODES`` is a list of objects::

    {
      "n": "VARIABLE_NAME",
      "d": "description",
      "fm": [{"f": "formula text", "ie": "INDICATOR EXPR"}],
      "r": ["upstream", ...],
      "b": ["downstream", ...],
      "deg": 12, "indeg": 5, "outdeg": 7,
      "isLeaf": false, "isRoot": false,
      "lib": "Library name"
    }

``EDGES`` is a list of ``[upstreamIndex, downstreamIndex]`` pairs into ``NODES``.
Both are embedded as JSON; the page needs no server and no build step.

The template lives in ``prophet_vault/templates/dependency_graph.html`` and uses
``__PLACEHOLDER__`` tokens, so the JavaScript can use braces freely.
"""

from __future__ import annotations

import html as html_lib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ._io import write_text
from .config import SHARED_LIBRARY
from .snapshot import Snapshot

TEMPLATE_PATH = Path(__file__).parent / "templates" / "dependency_graph.html"

ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"

#: Fallback palette for libraries beyond the first ten.
PALETTE = [
    "#58a6ff",
    "#3fb950",
    "#d29922",
    "#bc8cff",
    "#39c5cf",
    "#f85149",
    "#db6d28",
    "#a5b4ff",
    "#56d364",
    "#e3b341",
    "#79c0ff",
    "#ffa657",
]


@dataclass
class GraphData:
    """Nodes, edges and the statistics shown in the page header."""

    nodes: list[dict] = field(default_factory=list)
    edges: list[list[int]] = field(default_factory=list)
    libraries: list[str] = field(default_factory=list)
    palette: dict[str, str] = field(default_factory=dict)
    total_variables: int = 0
    label: str = "unknown"
    max_nodes: int = 300

    @property
    def stats(self) -> dict[str, float]:
        degrees = [node["deg"] for node in self.nodes]
        leaves = sum(1 for node in self.nodes if node["isLeaf"])
        roots = sum(1 for node in self.nodes if node["isRoot"])
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "leaves": leaves,
            "roots": roots,
            "maxDegree": max(degrees, default=0),
            "avgDegree": round(sum(degrees) / len(degrees), 1) if degrees else 0.0,
        }


def library_palette(libraries: list[str]) -> dict[str, str]:
    """Assign a stable colour to each library name."""
    return {
        name: PALETTE[index % len(PALETTE)] for index, name in enumerate(sorted(set(libraries)))
    }


def build_graph(snapshot: Snapshot, max_nodes: int = 300) -> GraphData:
    """Build the graph payload from a snapshot.

    Variables without any dependency are still emitted: an actuary searching for a
    table-read input expects to find it, and it simply renders as an isolated node.
    """
    library_by_name = snapshot.library_by_name()
    description_by_name = snapshot.description_by_name()
    references = snapshot.references_by_name()
    reverse = snapshot.referenced_by()
    formulas = snapshot.formulas_by_name()

    names = sorted(set(snapshot.variable_names()) | set(references) | set(reverse))
    index_by_name = {name: index for index, name in enumerate(names)}

    nodes: list[dict] = []
    for name in names:
        blocks = [
            {
                "f": record.get("FORMULA", ""),
                "ie": record.get("INDICATOREXPR", ""),
            }
            for record in formulas.get(name, [])
        ]
        upstream = [ref for ref in references.get(name, []) if ref in index_by_name]
        downstream = [user for user in reverse.get(name, []) if user in index_by_name]
        nodes.append(
            {
                "n": name,
                "d": description_by_name.get(name, ""),
                "fm": blocks,
                "r": upstream,
                "b": downstream,
                "deg": len(upstream) + len(downstream),
                "indeg": len(upstream),
                "outdeg": len(downstream),
                "isLeaf": not upstream,
                "isRoot": not downstream,
                "lib": library_by_name.get(name, SHARED_LIBRARY),
            }
        )

    edges: list[list[int]] = []
    for name, upstream in references.items():
        if name not in index_by_name:
            continue
        target = index_by_name[name]
        for ref in upstream:
            source = index_by_name.get(ref)
            if source is not None:
                edges.append([source, target])

    libraries = sorted({node["lib"] for node in nodes})
    return GraphData(
        nodes=nodes,
        edges=edges,
        libraries=libraries,
        palette=library_palette(libraries),
        total_variables=len(snapshot.variables),
        label=snapshot.label(),
        max_nodes=max_nodes,
    )


def _json_for_script(value: object) -> str:
    """Serialise ``value`` so it can be embedded inside a ``<script>`` block.

    ``json.dumps`` escapes quotes but not ``</script>``. A description or variable name
    containing that sequence would close the element early and blank the page, so the
    three HTML-significant characters are emitted as JSON unicode escapes instead -
    still valid JSON, inert in HTML.
    """
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _echarts_tag(echarts_path: str | Path | None) -> str:
    """Return either a CDN ``<script>`` tag or an inline copy for offline use."""
    if echarts_path is None:
        return f'<script src="{ECHARTS_CDN}"></script>'
    source = Path(echarts_path).read_text(encoding="utf-8")
    return f"<script>\n{source}\n</script>"


def render_html(
    graph: GraphData,
    title: str = "Prophet model - dependency graph",
    echarts_path: str | Path | None = None,
    max_nodes: int | None = None,
) -> str:
    """Render the HTML page.

    Args:
        graph: Output of :func:`build_graph`.
        title: Page and header title.
        echarts_path: Local ``echarts.min.js`` to inline. Without it the page loads
            ECharts from a CDN and shows a hint when offline.
        max_nodes: Cap on nodes drawn per view (default 300).
    """
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    stats = graph.stats
    meta = {
        "label": graph.label,
        "totalVariables": graph.total_variables,
        "maxNodes": max_nodes or getattr(graph, "max_nodes", 300) or 300,
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }

    replacements = {
        # The title lands inside <title> and a <span>, so it is HTML-escaped.
        "__TITLE__": html_lib.escape(title, quote=True),
        "__ECHARTS_TAG__": _echarts_tag(echarts_path),
        "__NODES__": _json_for_script(graph.nodes),
        "__EDGES__": _json_for_script(graph.edges),
        "__META__": _json_for_script(meta),
        "__LIB_COLORS__": _json_for_script(graph.palette),
        "__STAT_VARS__": f"{graph.total_variables:,}",
        "__STAT_NODES__": f"{stats['nodes']:,}",
        "__STAT_EDGES__": f"{stats['edges']:,}",
        "__STAT_LEAVES__": f"{stats['leaves']:,}",
        "__STAT_MAXDEG__": f"{stats['maxDegree']}",
        "__STAT_AVGDEG__": f"{stats['avgDegree']}",
    }
    page = template
    for token, value in replacements.items():
        page = page.replace(token, str(value))
    return page


def write_html(
    path: str | Path,
    graph: GraphData,
    title: str = "Prophet model - dependency graph",
    echarts_path: str | Path | None = None,
    max_nodes: int | None = None,
) -> Path:
    """Render and write the page, creating parent folders. Returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(
        path,
        render_html(graph, title=title, echarts_path=echarts_path, max_nodes=max_nodes),
    )
    return path
