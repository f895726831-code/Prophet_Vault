"""Command-line interface.

Examples
--------
Generate a synthetic model and see every output::

    python -m prophet_vault demo --out examples

Extract from a real Prophet installation::

    python -m prophet_vault snapshot --prw "D:/models/PROPHET.PRW" --label 2026-08
    python -m prophet_vault diff --old output/snapshots/2026-07 --new output/snapshots/2026-08
    python -m prophet_vault build-vault --snapshot output/snapshots/2026-08 --vault vault
    python -m prophet_vault graph --snapshot output/snapshots/2026-08 -o graph.html

Apply a monthly update in place::

    python -m prophet_vault update-vault --diff output/diffs/latest_diff.json \\
        --vault vault --snapshot output/snapshots/2026-08
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import Settings
from .demo import DemoOptions, generate_twin_model
from .diff import compare, load as load_diff, write as write_diff
from .extract import ExtractionError, extract_all, make_runner, merge_rci_descriptions
from .graph import build_graph, write_html
from .isql import IsqlError
from .rci import parse_file, read_header, to_rows
from .snapshot import Snapshot, latest_snapshot, write_rows
from .vault import VaultError, apply_diff, write_vault


def _settings(args: argparse.Namespace) -> Settings:
    return Settings.from_env(
        isql_path=getattr(args, "isql", None),
        prw_path=getattr(args, "prw", None),
        workspace_dir=getattr(args, "workspace", None),
        output_dir=getattr(args, "out", None),
    )


def _progress(message: str) -> None:
    print(f"  {message}", flush=True)


# --------------------------------------------------------------------- commands
def cmd_demo(args: argparse.Namespace) -> int:
    out = Path(args.out)
    options = DemoOptions(seed=args.seed)
    old_model, new_model = generate_twin_model(options)

    old_snap = Snapshot.build(old_model, label="demo_2026-01")
    new_snap = Snapshot.build(new_model, label="demo_2026-02")
    old_dir = old_snap.save(out / "snapshots" / "demo_2026-01")
    new_dir = new_snap.save(out / "snapshots" / "demo_2026-02")
    print(f"snapshots: {old_dir} ({len(old_snap.variables)} variables)")
    print(f"           {new_dir} ({len(new_snap.variables)} variables)")

    if not args.no_diff:
        diff = compare(old_snap, new_snap)
        json_path, report_path = write_diff(diff, out / "diffs" / "demo_diff.json")
        print(f"diff:      {json_path}")
        print(f"           {report_path}  {diff.summary()}")

    if not args.no_vault:
        vault_dir = out / "vault"
        counts = write_vault(new_snap, vault_dir, force=True, progress=_progress)
        print(f"vault:     {vault_dir}  {counts}")

    if not args.no_graph:
        graph = build_graph(new_snap, max_nodes=args.max_nodes)
        graph_path = write_html(
            out / "dependency-graph.html",
            graph,
            title="Prophet demo model - dependency graph",
            echarts_path=args.echarts,
        )
        stats = graph.stats
        print(f"graph:     {graph_path}  {stats['nodes']} nodes / {stats['edges']} edges")
    return 0


def cmd_rci(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if args.rci:
        path = Path(args.rci)
    elif settings.workspace_dir is not None:
        path = settings.rci_path()
    else:
        print(
            "error: pass --rci, or --workspace / PROPHET_WORKSPACE_DIR pointing at the "
            "folder that holds VAR_LIST.RCI",
            file=sys.stderr,
        )
        return 2

    header = read_header(path.read_bytes()[:40])
    if not header.plausible and not args.force:
        print(
            f"error: {path} does not look like VAR_LIST.RCI "
            f"(magic ok: {header.magic_ok}, entries: {header.entry_count}). "
            "Pass --force to parse it anyway.",
            file=sys.stderr,
        )
        return 2

    entries = parse_file(path)
    if not entries:
        print(
            f"error: no variables could be parsed from {path}; the file is not the "
            "expected format or is encrypted",
            file=sys.stderr,
        )
        return 2

    destination = Path(args.out) / "variables_phase1.csv"
    write_rows(
        destination,
        to_rows(entries),
        ["name", "category", "description", "source"],
    )
    categories: dict[str, int] = {}
    for entry in entries:
        categories[entry.category] = categories.get(entry.category, 0) + 1
    print(f"parsed {len(entries)} variables -> {destination}")
    if categories:
        print(
            "categories: "
            + ", ".join(f"{key}={value}" for key, value in sorted(categories.items()))
        )
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    settings = _settings(args)
    runner = make_runner(settings, charset=args.charset)
    for name in runner.table_names():
        print(name)
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    settings = _settings(args)
    runner = make_runner(settings, charset=args.charset)
    print(f"reading {runner.database}")
    model = extract_all(runner, progress=_progress, allow_empty=args.allow_empty)

    rci_path = None
    if args.rci:
        rci_path = Path(args.rci)
    elif settings.workspace_dir is not None:
        candidate = settings.rci_path()
        rci_path = candidate if candidate.exists() else None
    if rci_path is not None:
        if not rci_path.exists():
            print(f"warning: VAR_LIST.RCI not found at {rci_path}", file=sys.stderr)
        else:
            entries = parse_file(rci_path)
            enriched = merge_rci_descriptions(model, entries)
            print(f"descriptions from {rci_path}: {enriched} variable(s) enriched")

    snapshot = Snapshot.build(model, label=args.label, source=str(runner.database))
    directory = snapshot.save(Path(args.out or settings.output_dir) / "snapshots" / args.label)
    print(f"snapshot written: {directory}")
    print(
        f"  variables {len(snapshot.variables):,}, formulas {len(snapshot.formulas):,}, "
        f"indicators {len(snapshot.indicators):,}"
    )
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    settings = _settings(args)
    old = Snapshot.load(args.old)
    new = Snapshot.load(args.new)
    diff = compare(old, new)
    destination = (
        Path(args.output)
        if args.output
        else Path(settings.output_dir) / "diffs" / "latest_diff.json"
    )
    json_path, report_path = write_diff(diff, destination)
    summary = diff.summary()
    print(f"compared {old.label()} -> {new.label()}")
    for key, value in summary.items():
        print(f"  {key:20s} {value}")
    print(f"json:   {json_path}")
    print(f"report: {report_path}")
    return 0


def cmd_build_vault(args: argparse.Namespace) -> int:
    settings = _settings(args)
    snapshot = Snapshot.load(args.snapshot)
    vault_dir = Path(args.vault or settings.vault_dir)
    try:
        counts = write_vault(snapshot, vault_dir, force=args.force, progress=_progress)
    except VaultError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"vault written: {vault_dir}  {counts}")
    return 0


def cmd_update_vault(args: argparse.Namespace) -> int:
    snapshot = Snapshot.load(args.snapshot)
    diff_payload = load_diff(args.diff)

    # Rebuild a Diff object from the JSON report so the updater has one input type.
    from .diff import Diff

    diff = Diff(
        old_label=str(diff_payload.get("old_label", "old")),
        new_label=str(diff_payload.get("new_label", "new")),
        added=list(diff_payload.get("added", [])),
        deleted=list(diff_payload.get("deleted", [])),
        desc_changed=list(diff_payload.get("desc_changed", [])),
        formula_changed=list(diff_payload.get("formula_changed", [])),
        indicator_changed=list(diff_payload.get("indicator_changed", [])),
        refs_changed=list(diff_payload.get("refs_changed", [])),
        unchanged=int(diff_payload.get("summary", {}).get("unchanged", 0)),
    )

    # A report that lists fewer entries than its own summary claims would leave pages
    # stale without any error. Say so loudly instead of updating silently.
    _warn_about_incomplete_report(diff_payload)

    try:
        counts = apply_diff(
            diff, args.vault, snapshot, backup=not args.no_backup, progress=_progress
        )
    except VaultError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"vault updated: {args.vault}  {counts}")
    return 0


def _warn_about_incomplete_report(payload: dict) -> None:
    """Warn when a diff JSON carries fewer entries than its summary reports."""
    summary = payload.get("summary") or {}
    for key in (
        "added",
        "deleted",
        "desc_changed",
        "formula_changed",
        "indicator_changed",
        "refs_changed",
    ):
        listed = len(payload.get(key) or [])
        claimed = summary.get(key, listed)
        if isinstance(claimed, int) and listed < claimed:
            print(
                f"warning: diff report lists {listed} of {claimed} {key}; "
                f"{claimed - listed} change(s) will not be applied. "
                "Regenerate the report with the current version of `prophet-vault diff`.",
                file=sys.stderr,
            )


def cmd_graph(args: argparse.Namespace) -> int:
    settings = _settings(args)
    out_dir = Path(args.out or settings.output_dir)
    snapshot_dir = Path(args.snapshot) if args.snapshot else latest_snapshot(out_dir / "snapshots")
    if snapshot_dir is None:
        print("error: no snapshot found; pass --snapshot", file=sys.stderr)
        return 2
    snapshot = Snapshot.load(snapshot_dir)
    graph = build_graph(snapshot, max_nodes=args.max_nodes)
    destination = Path(args.output) if args.output else out_dir / "dependency-graph.html"
    write_html(
        destination, graph, title=args.title, echarts_path=args.echarts, max_nodes=args.max_nodes
    )
    stats = graph.stats
    print(f"graph written: {destination}")
    print(
        f"  nodes {stats['nodes']:,} / edges {stats['edges']:,} "
        f"/ leaves {stats['leaves']:,} / max degree {stats['maxDegree']}"
    )
    return 0


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prophet-vault",
        description="Turn a Prophet actuarial model into a searchable, diffable knowledge base.",
    )
    parser.add_argument("--version", action="version", version=f"prophet-vault {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--isql", help="path to Firebird isql.exe")
    common.add_argument("--prw", help="path to the Prophet .PRW database")
    common.add_argument(
        "--workspace",
        help="Prophet workspace folder (holds VAR_LIST.RCI); used to enrich descriptions",
    )
    common.add_argument(
        "--charset",
        help="Firebird connection charset passed to isql (e.g. UTF8, WIN1252); "
        "use it when descriptions come back as mojibake",
    )
    common.add_argument(
        "--out",
        default=None,
        help="output folder (default: PROPHET_OUTPUT_DIR or ./output)",
    )

    demo = subparsers.add_parser("demo", help="generate a synthetic model and all outputs")
    demo.add_argument("--out", default="examples", help="output folder (default: examples)")
    demo.add_argument("--seed", type=int, default=7, help="random seed for the demo model")
    demo.add_argument("--max-nodes", type=int, default=300, help="nodes drawn per view")
    demo.add_argument("--echarts", help="local echarts.min.js to inline (offline page)")
    demo.add_argument("--no-vault", action="store_true", help="skip vault generation")
    demo.add_argument("--no-graph", action="store_true", help="skip the HTML graph")
    demo.add_argument("--no-diff", action="store_true", help="skip the diff report")
    demo.set_defaults(func=cmd_demo)

    rci = subparsers.add_parser("extract-rci", help="parse VAR_LIST.RCI into a CSV")
    rci.add_argument("--rci", help="path to VAR_LIST.RCI (default: <workspace>/VAR_LIST.RCI)")
    rci.add_argument("--workspace", help="folder holding VAR_LIST.RCI")
    rci.add_argument("--out", default="output", help="output folder (default: output)")
    rci.add_argument(
        "--force",
        action="store_true",
        help="parse even when the header does not look like VAR_LIST.RCI",
    )
    rci.set_defaults(func=cmd_rci)

    schema = subparsers.add_parser("schema", parents=[common], help="list tables in the PRW")
    schema.set_defaults(func=cmd_schema)

    snapshot = subparsers.add_parser(
        "snapshot", parents=[common], help="extract a snapshot from the PRW"
    )
    snapshot.add_argument("--label", required=True, help="snapshot label, e.g. 2026-08")
    snapshot.add_argument(
        "--rci",
        help="VAR_LIST.RCI to read longer descriptions from "
        "(default: <workspace>/VAR_LIST.RCI when it exists)",
    )
    snapshot.add_argument(
        "--allow-empty",
        action="store_true",
        help="accept a database that returns no variables (writes an empty snapshot)",
    )
    snapshot.set_defaults(func=cmd_snapshot)

    diff = subparsers.add_parser("diff", help="compare two snapshots")
    diff.add_argument("--old", required=True, help="older snapshot folder")
    diff.add_argument("--new", required=True, help="newer snapshot folder")
    diff.add_argument(
        "--output",
        default=None,
        help="diff JSON path (default: <out>/diffs/latest_diff.json)",
    )
    diff.set_defaults(func=cmd_diff)

    build = subparsers.add_parser("build-vault", help="render a snapshot as an Obsidian vault")
    build.add_argument("--snapshot", required=True, help="snapshot folder")
    build.add_argument(
        "--vault",
        default=None,
        help="vault folder to create (default: PROPHET_VAULT_DIR or ./Prophet_Vault)",
    )
    build.add_argument("--force", action="store_true", help="delete an existing non-empty vault")
    build.set_defaults(func=cmd_build_vault)

    update = subparsers.add_parser("update-vault", help="apply a diff to an existing vault")
    update.add_argument("--diff", required=True, help="diff JSON path")
    update.add_argument("--vault", required=True, help="existing vault folder")
    update.add_argument("--snapshot", required=True, help="new snapshot folder")
    update.add_argument("--no-backup", action="store_true", help="do not copy the vault first")
    update.set_defaults(func=cmd_update_vault)

    graph = subparsers.add_parser("graph", help="render the dependency graph as HTML")
    graph.add_argument("--snapshot", help="snapshot folder (default: newest under <out>/snapshots)")
    graph.add_argument(
        "-o",
        "--output",
        default=None,
        help="HTML path (default: <out>/dependency-graph.html)",
    )
    graph.add_argument("--title", default="Prophet model - dependency graph")
    graph.add_argument("--max-nodes", type=int, default=300, help="nodes drawn per view")
    graph.add_argument("--echarts", help="local echarts.min.js to inline (offline page)")
    graph.add_argument(
        "--out",
        default=None,
        help="base folder used to find snapshots (default: PROPHET_OUTPUT_DIR or ./output)",
    )
    graph.set_defaults(func=cmd_graph)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, ValueError, IsqlError, ExtractionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
