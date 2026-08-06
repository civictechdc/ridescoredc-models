# The prototype: parquet → database → map

A demo, not a step. It shows three things and skips everything else:

1. **Parquet files load into PostGIS and reach the map.**
2. **Two geometries** — scored road segments (lines) and BNA census blocks
   (polygons) — with crash points as a third for free.
3. **The frontend is decoupled from the data.** It reads `manifest.json` and
   knows nothing about RideScore, BNA, crashes, tables or columns.

Deliberately not here: dynamic weighting (v2 of the prototype), package
identity and versioning, validation beyond a description check, tests,
migrations, and anything about deployment.

## Running it

Two repositories, in worktrees so nothing touches the real checkouts:

    demo/models     ridescoredc-models   on demo/parquet-to-map
    demo/website    ridescoredc-website  on demo/manifest-map

The containers are the website's own stack, shifted to ports 8081 and 5433 so
they cannot collide with anything already running:

    cd demo/website && docker compose up -d

The pipeline runs on the host — no container needed:

    cd demo/models
    uv sync
    uv run ridescore run                            # fetch + build, if out/ is empty
    uv run ridescore build-bna --export-dir ../../BNA/bikescore-data/washington-district-of-columbia/export
    uv run ridescore describe                       # each dataset against its description
    uv run ridescore load                           # parquet -> PostGIS
    uv run ridescore manifest --to ../website/api/static/manifest.json
    docker compose -f ../website/docker-compose.yml restart martin   # only after new tables

Then open **http://localhost:8081/demo.html**.

Martin only needs restarting when a table first appears; reloading data does not
change what it publishes.

## What is where

| | |
|---|---|
| `descriptions/*.yaml` | what each dataset is: key, geography, shape, and every attribute's type, label, unit and meaning. Authored beside the stage that writes the dataset |
| `presentation.yaml` | what this deployment publishes and how it is drawn. One per deployment, not one per model |
| `src/ridescore/demo/bna.py` | wraps the BNA export as a dataset. No network, no scoring |
| `src/ridescore/demo/load.py` | `COPY` over parquet; the table's shape comes from the data |
| `src/ridescore/demo/manifest.py` | presentation + descriptions + tile endpoints → `manifest.json` |
| `../website/api/static/demo.html` | the whole frontend: a capability table and a boot loop |

## The four things to show

**1. Add a layer without touching the frontend.** BNA publishes several scores
this map does not draw. Add to `presentation.yaml`:

    - id: bna_recreation
      source: blocks
      value: bna_census_block.recreation_score
      render:
        template: choropleth
        scale: {type: sequential, scheme: viridis}
        opacity: 0.55
      popup: [bna_census_block.area_id, bna_census_block.recreation_score]

Re-run `ridescore manifest`, reload the page. New layer, with its title, legend
and popup labels. No frontend change, no rebuild, no database write, no
redeploy. Note it needs no `domain`: the scale takes the attribute's declared
range from the description.

**2. The description is the only place a field is explained.** Change
`recreation_score`'s label in `descriptions/bna_census_block.yaml`, regenerate,
reload — the legend, the layer list and the popup all follow. Today the popup
field list exists three times in the live site and the three disagree.

**3. Publish a layer the page cannot draw.** Set a layer's `render.template` to
`hexbin`. It is dropped with a warning in the console and a note in the panel;
everything else still draws. That is what lets the pipeline publish ahead of the
frontend with no coordinated release.

**4. The description catches the pipeline drifting from its own claims.**
`ridescore describe` compares each parquet against its description. It found
three real mismatches the first time it ran — `parking_presence` described as a
string and written as 0/1, `slow_street` described as a flag and written as free
text, `speed_limit_raw` described as an integer and written as a float with
missing values.

## Layers that cannot be shown together

RideScore and traffic stress draw the same lines from the same source — one
tile request, one copy of the geometry — and both paint `line-color`. Ticking
both would just have the later one cover the earlier, so the panel offers them
as radio buttons with a "none".

The rule is **same source and same visual channel**, not same geometry: crash
points share the map with both and conflict with neither, and two layers over
the BNA blocks would collide on the fill but not if one drew the fill and the
other an outline. Each render template declares the channel it writes, so the
frontend derives the grouping and the manifest needs no new field.

A presentation that genuinely wants two such layers drawn together — different
widths, an offset — sets `group:` on the layer, which overrides the derived
grouping.

## Things worth saying out loud

- **The map will not match production.** Deploying the ported pipeline's output
  changes `lts_level` on 2,420 segments and `ridescore_v1` on 2,789 — see
  `docs/where-we-are.md`. The demo is showing the correct numbers; the live map
  is showing scores from a version of the rules that exists nowhere in version
  control.
- **Road geometry is `LineStringZ`** and the loader drops the Z. A tile is 2D.
- **`road_segment_scored` is a view**, not a table: one geometry table with
  narrow score tables joined onto it, which is the arrangement the manifest
  describes rather than one invented for the frontend.
- **BNA is wrapped, not reimplemented.** Someone else's model, its own cadence,
  read from an export and given a description like anything else.
