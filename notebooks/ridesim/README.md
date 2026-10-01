# RideSim DC data prep

Builds the static files behind [RideSim DC](https://ridesimdc.com): a routable street graph with a Level of Traffic Stress (LTS) per edge, residents and destinations on graph nodes, and ranked "missing link" fixes per rider type.

## Run

```bash
uv run ridescore run --run-date 2026-09-30          # pipeline outputs in out/
uv run --group notebooks python notebooks/ridesim/prep.py
```

Inputs (defaults, override with env vars `RIDESIM_SNAPSHOT`, `RIDESIM_OUT`, `RIDESIM_RAW`, `RIDESIM_DEST`):
- `ridescore_dc_basemap_2026-09-29.parquet` (Hugging Face snapshot): the street network (OSM segments with OSM node ids, conflated to DDOT).
- `out/` from `ridescore run`: `ridescore_v1_scores.parquet` (LTS), `road_segment.parquet`, `crashes.parquet`.
- 2020 Census blocks (`tl_2020_11_tabblock20.zip`, field `POP20`).
- DC Open Data points: public and charter schools, libraries, Metro entrances, recreation facilities; ward boundaries.

## Output

| File | One row is | Notes |
|---|---|---|
| `network.json` | node / edge | `[u, v, length_m, lts, lts_source, name, block, coords]`; nodes carry residents and ward |
| `blocks.json` | DDOT block used by the network | facts and scores shown in the "why this score" panel, keyed by `segment_id` |
| `fixes.json` | candidate fix | greedy top 100 per rider (kid LTS ≤ 1, casual ≤ 2, commuter ≤ 3) |
| `pois.json`, `crashes.json`, `wards.geojson`, `meta.json` | | |

## How LTS is assigned (scale 1 calm to 4 hostile)
1. Segments matched to a scored DDOT block take that block's `lts_level` (joined on `dc_blockkey` = pipeline `segment_id`).
2. Separately mapped cycle tracks (`osm_highway = cycleway`) are set to LTS 1. The snapshot copies the neighboring street's attributes onto them, so without this a protected track scores as hostile as the arterial beside it (1,470 such tracks scored 3 or 4).
3. Trails and paths with no DDOT match are LTS 1.
4. Other unmatched roads get an estimate from their OSM road class.

Each edge records which rule applied (`lts_source`).

## What it can't tell you
- **Fixes are a what-if simulation, not scores.** A "fixed" block is treated as calm for every rider; nothing is re-scored by the pipeline.
- **Intersections are not scored.** LTS here is per street segment; crossing a busy street at a signal counts as free.
- **Direction is ignored.** One-way streets are routable both ways.
- **Residents are approximate.** Census block populations are snapped to the nearest street node (median 60 m).
- **Some geometry gaps.** About 1.5% of segments have geometry that does not reach the intersection node; routes still connect but can show a short straight jump.
- **Traffic data is old.** The underlying DDOT traffic volumes are from 2020.
