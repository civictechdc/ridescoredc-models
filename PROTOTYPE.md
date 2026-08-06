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

You need **Docker** (with Compose) and **uv**. Nothing else, no credentials, and
no data from anyone. About ten minutes, most of it Docker pulling images.

Both branches live on forks, so nothing here touches the `civictechdc`
repositories.

**1. Get the two branches.** Side by side, in one directory:

    git clone -b demo/parquet-to-map https://github.com/fkloosterman/ridescoredc-models.git models
    git clone -b demo/manifest-map   https://github.com/fkloosterman/ridescoredc-website.git website

**2. Get the data package** — 3 MB, the pipeline's output, so you do not have to
fetch several hundred megabytes of source data or hold a local BNA export:

    mkdir -p models/out && curl -sL \
      https://github.com/fkloosterman/ridescoredc-models/releases/download/demo-data-2026-08-06/ridescore-demo-data.tar.gz \
      | tar xz -C models/out

**3. Start the containers.** The website's own stack — Postgres, Martin, Nginx,
FastAPI — on ports 8081 and 5433, so it cannot collide with anything you already
run:

    cd website && cp api/.env.example api/.env && docker compose up -d

**4. Load, and publish the manifest:**

    cd ../models && uv sync
    uv run ridescore describe                       # each dataset against its description
    uv run ridescore load                           # parquet -> PostGIS
    uv run ridescore manifest --to ../website/api/static/manifest.json
    docker compose -f ../website/docker-compose.yml restart martin   # once, so it sees the tables

Then open **http://localhost:8081/demo.html**.

To rebuild the data yourself instead of downloading it, you need the source data
and a BNA export for DC:

    uv run ridescore run                            # fetch + build; several hundred MB
    uv run ridescore build-bna --export-dir <a bikescore export directory>

Martin only needs restarting when a table first appears; reloading data does not
change what it publishes.

`ridescore manifest` rewrites `manifest.json` in place, so a regenerated
manifest is served immediately — reload the page and that is all. An editor that
replaces `demo.html` rather than rewriting it gives the container a stale inode;
`docker compose restart fastapi` clears it.

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

**1. Add a layer without touching the frontend.** Two edits and a reload, about
fifteen seconds. BNA publishes several scores this map does not draw. Add to
`presentation.yaml`:

    - id: bna_recreation
      source: blocks
      value: bna_census_block.recreation_score
      render:
        template: choropleth
        scale: {type: sequential, scheme: viridis}
        opacity: 0.55
      popup: [bna_census_block.area_id, bna_census_block.recreation_score]

Then:

    uv run ridescore manifest --to ../website/api/static/manifest.json   # 0.8s

and reload the page. **Open `demo.html?watch` and it reloads itself** when the
manifest's `generated` changes — the page polls every two seconds, which is
worth it while demonstrating and wrong for a deployed site, hence the flag.

New layer, with its title, legend and popup labels. No
frontend change, no rebuild, no database write, no container restart, no
redeploy. Note it needs no `domain`: the scale takes the attribute's declared
range from the description, so `recreation_score` gets `[0, 1]` and not the
`[0, 100]` of the score above it.

**Where the boundary is**, because it is the whole point: this works without
touching the pipeline because `recreation_score` is already a column in the
table, so it is already in every tile — Martin publishes a table's columns, and
the manifest decides which ones mean something. A layer over an attribute the
pipeline does not yet produce is a different job: build, load, and a Martin
restart so it sees the new shape.

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

## What a click does

Three levels of detail, each answering a different question:

| | Question | Where | What |
|---|---|---|---|
| **Hover** | what is this? | a box at the cursor | one line: the layer's title and the value it is coloured by |
| **Click** | tell me about this | the sidebar | every layer under the cursor, all fields, actions |
| **Selection** | work from this one | the left panel | persists until cleared or replaced |

A click is one question, so it gets one answer: one sidebar, with a section per
layer under the cursor. Sections are ordered **smallest target first** — point,
then line, then polygon — so clicking near a road reads as the road, with the
block it sits on underneath as context. The click is tested against a small box
rather than a point, because a thin line is hard to hit exactly, and several
features from one layer collapse to a `+n more here` note.

It is a sidebar rather than a popup because a popup is the one container that
has to fit near the click while the thing it describes is underneath it. With
four layers it needs a scrollbar over its own subject. The sidebar also has room
for what a query layer will return. On a narrow screen it becomes a bottom
sheet, which is a media query rather than a second implementation.

Hover and selection are separate feature states, so the outline under the cursor
and the outline of what other layers are working from do not look the same.

None of that needs a new manifest field: every geography already declares its
`shape`.

A click can also **select**, which is a different thing from inspecting.
Selection is held per *geography*, not per layer, because several layers can
consume "the block the user picked" and only one block is picked. The selected
feature is highlighted through feature state, which is why a geography needs a
numeric key — BNA blocks now carry `tile_id` beside their string GEOID, assigned
in GEOID order, described as their `tile_key`.

**The available actions come from the manifest.** Any layer declaring a
selection parameter over a geography offers itself as a button on that
geography's section. Publish such a layer and the button appears; nothing in the
page knows what the layer is for.

The "Pin this census block" button is scaffolding — it makes selection visible
while nothing consumes one, and it disappears for any geography that has a real
action, because pinning for its own sake is noise.

## Adding a selection-driven layer

`presentation.yaml` carries a commented `bna_reachable_from` stanza — the
worked example's reachability layer. Uncommenting it publishes a layer that:

- offers "Reachable from selected block" when a block is clicked,
- becomes visible when that action is taken,
- calls `/api/layers/bna_reachable_from?origin=<GEOID>`,
- applies the returned values as feature state keyed by `tile_id`, so it
  restyles instantly with no tile refetch.

All of that works today except the endpoint, which does not exist yet. That is
the only thing standing between the prototype and a working reachability layer,
and it is prototype v2 along with dynamic weighting. The layer's value comes from
the endpoint rather than a dataset, so it is described inline; everything drawn
from a tile is described once, by the stage that writes it.

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
