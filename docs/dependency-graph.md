# The dependency graph

## The problem with whole-model graphs

A 15,000-variable model has roughly the same number of edges. Rendering all of it at once
fails for structural reasons, not because of a missing GPU:

* Force layouts are O(n log n) per iteration and need hundreds of iterations; at 15k nodes
  the first paint takes minutes.
* Even when it renders, a hairball of 15k nodes answers no question. The user has one
  variable in mind and wants its neighbourhood.
* Every pan re-runs the simulation if the layout is not cached, so the page is unusable
  rather than merely slow.

Obsidian's built-in graph view is exactly this: correct, pretty, and unusable at scale.

## The approach here

Ship the dependency lists, not the layout. The browser draws **one focus variable plus N
hops** (N = 1, 2 or 3), and re-computes on every click. Work is proportional to the
neighbourhood, which is bounded:

| Depth | Typical nodes for a mid-graph variable | Render time |
|---|---|---|
| 1 | 5-30 | instant |
| 2 | 50-300 | instant |
| 3 | 300-2,000 | under a second |

Above 300 nodes the renderer keeps the focus variable plus the highest-degree neighbours,
so a hub with 900 consumers still opens.

## Data contract

`graph.build_graph(snapshot)` produces:

```json
{
  "nodes": [
    {
      "n": "NET_CF",
      "d": "Net cash flow of the period",
      "fm": [{"f": "PREMIUM(t) - CLAIMS(t)", "ie": "ALWAYS"}],
      "r": ["PREMIUM", "CLAIMS"],
      "b": ["PVFP", "BEL"],
      "deg": 4, "indeg": 2, "outdeg": 2,
      "isLeaf": false, "isRoot": false,
      "lib": "Conventional"
    }
  ],
  "edges": [[0, 3], [1, 3]]
}
```

* `r` = the variables this definition reads (upstream), `b` = the variables that read it
  (downstream).
* `fm` = formula blocks, one per indicator. Keeping them attached to the node means the
  page needs no second request to show calculation logic.
* `edges` are `[upstreamIndex, downstreamIndex]` pairs into `nodes`, for consumers that
  want the raw graph (pandas, networkx, another front end). The bundled page rebuilds
  edges from `r`/`b`, which is why it can filter by depth without scanning the edge list.

`isLeaf` / `isRoot` are precomputed because the list panel sorts and tags by them.

## Rendering choices

* **Colour by library.** A variable's library is the one stable grouping in a Prophet
  model, and it lets a reviewer see at a glance that a change crosses from Conventional
  into IFRS17. A hard-coded palette of twelve colours covers typical library counts and
  cycles beyond that.
* **Size by role, not by degree.** Centre 34 px, hub 22 px, ordinary 15 px, leaf 10 px.
  Scaling by degree makes one hub swallow the canvas.
* **Edge colour by direction.** Green into the centre, amber out of it, grey between
  neighbours. This is what makes "what feeds this" versus "what consumes this" readable
  without a legend lookup.
* **Labels only when useful.** The centre and nodes at 15 px or more get labels; showing
  every label at depth 3 is unreadable.
* **Two layouts.** `force` for exploration, `circular` for a hub with many leaves, where a
  force layout stacks leaves on top of each other.
* **Click to navigate, with history.** Clicking any node, chip or list row re-focuses the
  graph and pushes onto a back/forward stack, so exploring a chain of dependencies is one
  gesture rather than a search.
* **Bottom panel is the calculation.** Formula text, per-indicator blocks, and the
  reference/consumer chips. This is the part an actuary actually reads; the graph is the
  map, the panel is the territory.

## Offline use

By default the page loads ECharts from jsDelivr, which keeps the committed file small.

For a page that works with no network - useful for attaching to a change ticket, an audit
pack, or an air-gapped review machine:

```bash
curl -L https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js -o echarts.min.js
python -m prophet_vault graph --snapshot output/snapshots/2026-08 \
    -o graph.html --echarts echarts.min.js
```

The library is inlined into the HTML, so the result is a single file of roughly 1 MB.
ECharts is Apache-2.0 licensed; if you redistribute such a page, keep its licence notice.

## Limits

* No cycle highlighting beyond visual inspection: Prophet formulas do contain cycles via
  period references (`X(t-1)`), and the graph treats every `X` in `X(t-1)` as an edge.
* Edge direction means "reads from", not "evaluated before". Prophet's evaluation order
  also depends on indicators and periods.
* The page is a viewer, not an editor. Nothing is ever written back to the model.
