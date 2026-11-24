"""Tests for the dependency-graph payload and the HTML renderer."""

from __future__ import annotations

import json
from pathlib import Path

from prophet_vault.graph import build_graph, library_palette, render_html, write_html
from prophet_vault.snapshot import Snapshot


def test_nodes_cover_every_variable(new_snapshot: Snapshot):
    graph = build_graph(new_snapshot)
    assert len(graph.nodes) == len(set(new_snapshot.variable_names()))
    assert graph.total_variables == len(new_snapshot.variables)


def test_edges_match_indegrees(new_snapshot: Snapshot):
    graph = build_graph(new_snapshot)
    assert len(graph.edges) == sum(node["indeg"] for node in graph.nodes)
    assert all(0 <= source < len(graph.nodes) for source, _target in graph.edges)
    assert all(0 <= target < len(graph.nodes) for _source, target in graph.edges)


def test_node_fields(new_snapshot: Snapshot):
    graph = build_graph(new_snapshot)
    node = next(item for item in graph.nodes if item["n"] == "FLOW_001")
    assert set(node) == {"n", "d", "fm", "r", "b", "deg", "indeg", "outdeg", "isLeaf", "isRoot", "lib"}
    assert node["deg"] == node["indeg"] + node["outdeg"]


def test_leaf_and_root_flags_are_consistent(new_snapshot: Snapshot):
    graph = build_graph(new_snapshot)
    for node in graph.nodes:
        assert node["isLeaf"] == (not node["r"])
        assert node["isRoot"] == (not node["b"])


def test_stats(new_snapshot: Snapshot):
    graph = build_graph(new_snapshot)
    stats = graph.stats
    assert stats["nodes"] == len(graph.nodes)
    assert stats["edges"] == len(graph.edges)
    assert stats["leaves"] >= 1
    assert stats["maxDegree"] >= stats["avgDegree"]


def test_palette_is_stable_and_covers_libraries(new_snapshot: Snapshot):
    graph = build_graph(new_snapshot)
    assert set(graph.palette) == set(graph.libraries)
    assert graph.palette == library_palette(graph.libraries)
    # Distinct colours for a small library set.
    assert len(set(graph.palette.values())) == len(graph.palette)


def test_render_html_has_no_leftover_tokens(new_snapshot: Snapshot):
    html = render_html(build_graph(new_snapshot))
    assert "__NODES__" not in html
    assert "__EDGES__" not in html
    assert "__STAT_VARS__" not in html
    assert "var NODES = [" in html
    assert "FLOW_001" in html


def test_render_html_embeds_stats(new_snapshot: Snapshot):
    graph = build_graph(new_snapshot)
    html = render_html(graph)
    assert f"{len(graph.nodes):,}" in html
    assert "dependency graph" in html


def test_render_html_uses_cdn_by_default(new_snapshot: Snapshot):
    html = render_html(build_graph(new_snapshot))
    assert "cdn.jsdelivr.net/npm/echarts" in html


def test_render_html_can_inline_echarts(tmp_path: Path, new_snapshot: Snapshot):
    echarts = tmp_path / "echarts.min.js"
    echarts.write_text("/* fake echarts */ window.echarts = {};", encoding="utf-8")
    html = render_html(build_graph(new_snapshot), echarts_path=echarts)
    assert "cdn.jsdelivr.net/npm/echarts" not in html
    assert "/* fake echarts */" in html


def test_write_html_creates_parents(tmp_path: Path, new_snapshot: Snapshot):
    destination = tmp_path / "nested" / "graph.html"
    write_html(destination, build_graph(new_snapshot), title="Custom title")
    assert destination.exists()
    assert "Custom title" in destination.read_text(encoding="utf-8")


def test_max_nodes_is_recorded(new_snapshot: Snapshot):
    graph = build_graph(new_snapshot, max_nodes=42)
    assert graph.max_nodes == 42
    assert '"maxNodes":42' in render_html(graph).replace(" ", "")


def test_node_json_is_valid_utf8_json(new_snapshot: Snapshot):
    html = render_html(build_graph(new_snapshot))
    start = html.index("var NODES = ") + len("var NODES = ")
    end = html.index(";\n", start)
    payload = json.loads(html[start:end])
    assert isinstance(payload, list) and payload
