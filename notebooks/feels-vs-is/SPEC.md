# Feels vs. Is: a two-axis bike safety model for DC

Working title. RideScore DC hackathon, Challenge 1, idea 4.2 (Build a new bicycle-safety model). Snapshot `ridescore_dc_basemap_2026-09-29`.

## What it says

LTS tells you how a street feels. Crashes tell you what happens on it. This model scores both for every DC street segment and every intersection, then maps where they disagree:

| Class | Feels | Is | What it means |
|---|---|---|---|
| `hidden_danger` | comfortable (LTS 1-2) | high harm | Looks safe on a stress map, but people keep getting hurt here |
| `fix_first` | stressful (LTS 3-4) | high harm | Bad on both counts |
| `scary_but_quiet` | hostile (LTS 4) | low harm | Few recorded crashes, usually because riders avoid it, not because it is safe |
| `calm` | comfortable | low harm | Fine on both counts |
| `middle` | everything else | | |

Why intersections get their own score: DC's Vision Zero task force reports bicyclist major injuries nearly doubled in 2025 (29 to 56), mostly at intersections ([Q1 2026 minutes](https://www.open-dc.gov/sites/default/files/documents/mins-Q1_2026_MCRTF.pdf)). LTS scores the blocks between them.

Why separated tracks need a second look: an IIHS study of DC, NYC and Portland found elevated injury risk on lightly separated two-way lanes, driven mostly by the 15th St NW track, which streets and alleys cross many times ([Cicchino et al. 2020](https://pubmed.ncbi.nlm.nih.gov/32388015/), [IIHS summary](https://www.iihs.org/news/detail/some-protected-bike-lanes-leave-cyclists-vulnerable-to-injury)). A stress score rates such a track LTS 1.

## Constraints

- Submissions close 4:00 PM, Sat Oct 3, 2026. Demos 4:15 PM, 2 minutes each, from the shared deck.
- Hand-in: a PR to `civictechdc/ridescoredc-models`, base `develop`, adding `notebooks/feels-vs-is/`. Results keyed by `osm_u`, `osm_v`, `osm_key` plus `snapshot_date = "2026-09-29"`, as Parquet. README covering what it produces, scale and direction, inputs, and what it cannot tell you.
- The PR touches only `notebooks/feels-vs-is/`, so CI stays green. Extra packages come in at run time with `uv run --with <pkg>`.
- Raw downloads and large intermediates go in `notebooks/feels-vs-is/cache/` (already gitignored by `notebooks/**/cache/`). The results Parquet and the small map page source are the only data-like files committed.

## Inputs

| Input | Where | Notes |
|---|---|---|
| Snapshot | `~/ridescore-data/ridescore_dc_basemap_2026-09-29.parquet` | GeoParquet, EPSG:4326, 28,978 rows, 135 columns. `geopandas.read_parquet` |
| Bike injury crashes, 5 years | DC GIS `Public_Safety_WebMercator/MapServer/24` | Fetched in Stage 3. Keeps `BLOCKKEY`, which the published `crashes.parquet` drops |
| LTS v1, for comparison | `src/ridescore/models/ridescore_v1/lts.py` | Snippet in AGENTS.md. Matched rows only |

Profiled on the full snapshot (Oct 3):

- `match_status`: good 26,974, weak 605, none 1,399.
- `osm_highway`: residential 13,259, tertiary 3,795, primary 3,462, secondary 3,268, cycleway 3,134, trunk 591, unclassified 588, path 175, footway 117, plus links.
- `dc_SPEEDLIMITS_OB` filled 79.9% (20 mph on 16,461 rows, 25 on 5,053, 30 on 1,245, 35 on 144). `osm_maxspeed` filled 29.1%, text like `"25 mph"`. `dc_SPEEDLIMITS_IB` is empty.
- `dc_TOTALTRAVELLANES` filled 95.2% (0 on 863 rows). `osm_lanes` filled 46.8% (text).
- `dc_AADT` filled 40.2%, median 7,963, all 2020 counts. Truck counts `dc_AADT_SINGLE_UNIT`, `dc_AADT_COMBINATION` filled 23.7%.
- DDOT facility columns hold `IB`, `OB` or `BD` when present: `dc_BIKELANE_CONVENTIONAL` 2,741 rows, `_BUFFERED` 930, `_DUAL_BUFFERED` 166, `_PROTECTED` 686, `_DUAL_PROTECTED` 732, `_CONTRAFLOW` 355, `_PARKINGLANE_ADJACENT` 2,299.
- OSM facility tags: `osm_cycleway`, `osm_cycleway_left`, `osm_cycleway_right`, `osm_cycleway_both` (values include `lane`, `track`, `separate`, `shared_lane`, `share_busway`, `opposite_lane`, `crossing`), plus `*_buffer` = `yes`.
- 3,309 rows are `cycleway` or `path`; 2,226 of them matched a DDOT street (`dc_ROADTYPE == "1"`) and copied that street's speed, lanes and volume.
- 21,523 nodes. Degree 1: 1,099; 2: 9,502 (segment breaks, not intersections); 3: 6,074; 4: 4,640; 5+: 208.
- `dc_PCI_CONDCATEGORY` filled 85.6%. `dc_VERTICAL_DEFLECTION == "YES"` on 3,636 rows. `dc_DOUBLEYELLOW_LINE == "Yes"` on 7,329 rows, empty otherwise. `dc_TOTALRAISEDBUFFERS > 0` on about 5,500 rows, far more than protected lanes, so it is not a bike-separation signal.
- Network about 2,159 km; median segment 50 m. `osm_oneway` is boolean.

## Architecture

Logic lives in `notebooks/feels-vs-is/feels_vs_is.py` as plain functions. `feels_vs_is.ipynb` runs the stages in order and shows a checkpoint after each.

```
snapshot ─► 1 clean ─► 2 Feels (comfort) ──────────────┐
               └─► intersections ─► 3 crashes ─► 4 Is (harm, EB) ─► 5 gap + reasons ─► 6 results, validation, map
```

### Stage 1: Clean

One value per field per segment, with its source, so the README can state precedence.

| Field | Rule |
|---|---|
| `speed_mph`, `speed_src` | `dc_SPEEDLIMITS_OB` when > 1, else parsed `osm_maxspeed`, else the median of matched rows with the same `osm_highway` |
| `lanes`, `lanes_src` | `dc_TOTALTRAVELLANES` when > 0, else `osm_lanes`, else class median. `lanes_per_dir` = lanes if `osm_oneway` else ceil(lanes / 2) |
| `aadt`, `aadt_src` | `dc_AADT` when present, else class median of matched rows. Use its percentile, `aadt_pct`, since the counts are from 2020 |
| `truck_share` | (`dc_AADT_SINGLE_UNIT` + `dc_AADT_COMBINATION`) / `dc_AADT` where all present, else class median. `truck_pct` = its percentile |
| `func_class` | `dc_DCFUNCTIONALCLASS` (floats): 11 Interstate, 12 Freeway, 14 Principal Arterial, 16 Minor Arterial, 17 Collector, 18 treat as Collector, 19 Local. Fall back to `osm_highway` when empty |
| `facility`, `facility_src` | Tier list below, most protective wins, either direction |
| `door_zone` | `facility` in {painted, buffered} and `dc_BIKELANE_PARKINGLANE_ADJACENT` present |
| `parallel_track` | Street row with any `osm_cycleway*` == `separate`: its bike facility is mapped as its own cycleway row. Score the street as mixed traffic |
| `bike_width_ft`, `parking_width_ft` | `dc_TOTALBIKELANEWIDTH / dc_TOTALBIKELANES`, `dc_TOTALPARKINGLANEWIDTH / dc_TOTALPARKINGLANES` (feet, assumed; medians about 5 and 8) |
| `length_m` | Geometry length in EPSG:26985 |
| `confidence` | high: `match_status == "good"` and speed and lanes both from data; medium: weak match or one imputed field; low: no match or two or more imputed fields |

Facility tiers:

1. `separated`: `osm_highway` in {cycleway, path}, or footway with `osm_bicycle` in {designated, yes}. These rows copied the adjacent street's traffic attributes, so they are scored as separated from traffic. Keep the copied values as `street_speed_mph` and `street_lanes` for crossings.
2. `protected`: `dc_BIKELANE_PROTECTED`, `dc_BIKELANE_DUAL_PROTECTED`, or any `osm_cycleway*` == `track`.
3. `buffered`: `dc_BIKELANE_BUFFERED`, `dc_BIKELANE_DUAL_BUFFERED`, or a lane with `osm_cycleway*_buffer` == `yes`.
4. `painted`: `dc_BIKELANE_CONVENTIONAL`, `dc_BIKELANE_CONTRAFLOW`, or `osm_cycleway*` in {lane, opposite_lane}.
5. `sharrow`: `osm_cycleway*` in {shared_lane, share_busway}; set `bus_shared` for share_busway.
6. `none`.

### Stage 2: Feels (comfort)

`comfort_lts` follows Furth's 2012 LTS tables ([PDF](https://bpb-us-e1.wpmucdn.com/sites.northeastern.edu/dist/e/618/files/2014/05/LTS-Tables1.pdf)) with Montgomery County amendments ([Appendix D](https://montgomeryplanning.org/wp-content/uploads/2017/11/Appendix-D.pdf)):

- `separated`: 1.
- `protected`: 1 at 35 mph or less, else 2.
- `painted` or `buffered`, not door zone: 1 if `lanes_per_dir` == 1, speed ≤ 30 and bike width ≥ 6 ft (buffered counts as 6+); 2 if width < 6 ft, or 2 lanes per direction at ≤ 30; 3 at 35 mph or with 3+ lanes per direction; 4 at 40+.
- `painted` or `buffered`, door zone: reach = bike width + parking width. 1 if 1 lane per direction, speed ≤ 25 and reach ≥ 15 ft; 2 if reach 14 to 14.9 ft, speed 30, or 2 lanes per direction; 3 if reach < 14 ft or speed 35; 4 at 40+.
- `sharrow` or `none` (Furth mixed traffic; total through lanes, and 1 lane counts as 2-3):

| Speed | ≤ 3 lanes | 4-5 lanes | 6+ lanes |
|---|---|---|---|
| ≤ 25 | 1 if no centerline and AADT < 3,000, else 2 | 3 | 4 |
| 30 | 2 if no centerline and AADT < 3,000, else 3 | 4 | 4 |
| 35+ | 4 | 4 | 4 |

No centerline means `dc_DOUBLEYELLOW_LINE` is empty. Sharrows score like no facility, per Furth.

`comfort_score` (0 to 100, higher = more comfortable): each level has a band (1: 80 to 100, 2: 60 to 80, 3: 30 to 60, 4: 0 to 30). Position inside the band comes from a penalty `p = clip(0.4·aadt_pct + 0.2·truck_pct + 0.2·door_zone + 0.2·poor_pavement − 0.2·calmed, 0, 1)`, where `poor_pavement` = PCI category Poor or Very Poor and `calmed` = `dc_VERTICAL_DEFLECTION == "YES"`. Separated rows use 0 for the traffic terms. `comfort_score = band_high − p · (band_high − band_low)`.

`kid_ok` = `comfort_lts == 1`.

### Stage 3: Crashes

Fetch with `requests` (paging `resultOffset` by 1,000, stop on a short page) from
`https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Public_Safety_WebMercator/MapServer/24/query` with:

- `where`: `REPORTDATE >= DATE '2021-10-01 00:00:00' AND (MAJORINJURIES_BICYCLIST > 0 OR MINORINJURIES_BICYCLIST > 0 OR UNKNOWNINJURIES_BICYCLIST > 0 OR FATAL_BICYCLIST > 0)` (the pipeline's injury filter, from `src/ridescore/sources/crashes.py`)
- `outFields`: `OBJECTID,CRIMEID,REPORTDATE,BLOCKKEY,SUBBLOCKKEY,OFFINTERSECTION,NEARESTINTKEY,LATITUDE,LONGITUDE,FATAL_BICYCLIST,MAJORINJURIES_BICYCLIST,MINORINJURIES_BICYCLIST,UNKNOWNINJURIES_BICYCLIST,TOTAL_VEHICLES,SPEEDING_INVOLVED`
- `returnGeometry=false`, `orderByFields=OBJECTID`, `resultRecordCount=1000`, `f=json`

Expect roughly 2,000 to 2,500 rows. Cache to `cache/crashes.parquet`. `REPORTDATE` is epoch milliseconds; use it for date windows only, since hour of day in this layer is unreliable. `ksi` = fatal or major injury.

Intersections: cluster degree ≥ 3 nodes within 15 m into one intersection (scikit-learn DBSCAN, eps 15 m, min_samples 1) so complex junctions and track crossings count once. Its approaches are the segments touching the cluster.

Assignment, in EPSG:26985:

1. Within 20 m of an intersection cluster: intersection crash.
2. Else `BLOCKKEY` matches a `dc_blockkey`: midblock crash on that block.
3. Else nearest segment within 25 m: that segment's block, or the segment itself when it has no block key.
4. Else unmatched.

Report the count for each path in the notebook and README.

Time split for validation: train before 2025-01-01, test from 2025-01-01. The final map uses all years.

### Stage 4: Is (harm), with Empirical Bayes

Units: DDOT blocks (`dc_blockkey`) for midblock harm, with length = the block's street rows only (not its parallel cycleway rows); rows without a block key are their own unit. Intersection clusters for intersection harm.

Fit a negative binomial GLM (`statsmodels`) of crash count on design features only. Ward and location stay out, so expectations come from design rather than neighborhood.

- Blocks, offset log(length_km): `func_class`, street facility tier, speed bucket (≤ 20, 25, 30, 35+), lanes bucket (1-2, 3-4, 5+), `aadt_pct`.
- Intersections: number of approaches (3, 4, 5+), max approach `func_class`, max approach speed bucket, approaches with 4+ lanes, any separated or protected approach.

Empirical Bayes ([HSM](https://www.highwaysafetymanual.org/)): `w = 1 / (1 + α·μ)`, `eb = w·μ + (1 − w)·observed`. If the NB fit fails, use Poisson and estimate α by method of moments within design groups.

Per segment: `block_eb_per_km_yr` (every row in a block shares the rate, so a separated track and its street share the corridor's rate) and `node_eb_per_yr` = the worse of its two end intersections. `harm_score = 100 × max(block_pct, node_pct)` using length-weighted percentiles: a segment is as risky as its worst part. `harm_driver` records which one won. Also keep `crashes_5yr`, `ksi_5yr` (block), `node_crashes_5yr`, `node_ksi_5yr`.

`death_risk_if_struck`: a logistic curve fit to the AAA Foundation pedestrian points (10% at 23 mph, 25% at 32, 50% at 42, 75% at 50, 90% at 58; [Tefft 2011](https://aaafoundation.org/research/impact-speed-pedestrians-risk-severe-injury-death/)), evaluated at `speed_mph`, or at `street_speed_mph` for separated rows, labelled as at crossings. Label it a pedestrian-derived proxy.

### Stage 5: Gap and reasons

- `hidden_danger`: `comfort_lts` ≤ 2 and `harm_score` ≥ 80.
- `fix_first`: `comfort_lts` ≥ 3 and `harm_score` ≥ 80.
- `scary_but_quiet`: `comfort_lts` == 4 and `harm_score` ≤ 40.
- `calm`: `comfort_lts` ≤ 2 and `harm_score` ≤ 40.
- `middle`: the rest.

The thresholds are starting points. Tune them so `hidden_danger` is a short, defensible list (about 2 to 5% of network length) and record the final values in the README.

`reasons`: up to three short phrases, comfort first, then harm. Examples: "separated two-way track", "4 lanes at 30 mph, painted lane beside parked cars", "crossed by 9 intersections per km", "11 injury crashes at 15th & L since 2021 (3 serious)". Crossings per km = distinct intersection clusters touching the block's rows / block length.

### Stage 6: Results, validation, map

`notebooks/feels-vs-is/feels_vs_is_results.parquet`, one row per snapshot segment:
`osm_u, osm_v, osm_key, snapshot_date, comfort_score, comfort_lts, kid_ok, harm_score, harm_driver, crashes_5yr, ksi_5yr, node_crashes_5yr, node_ksi_5yr, death_risk_if_struck, gap_class, reasons, confidence, speed_mph, speed_src, lanes, lanes_src, facility, facility_src, door_zone, parallel_track, lts_v1, dc_blockkey`.

Validation (cut first if behind): refit Stage 4 on train crashes. Rank blocks and intersections by (a) LTS v1 (worst approach for intersections), (b) `comfort_lts`/`comfort_score`, (c) design-only expected `μ`, (d) EB with train history. Report the share of test-period injury and KSI crashes that fall in the worst 10% of network length (blocks) and the worst 10% of intersections, with capture curves. Break ties at random with a fixed seed. Say plainly that (d) uses crash history and measures persistence, while (a) to (c) are design-only.

Map, published on GitHub Pages from the fork:

- Export `cache/web/segments.geojson` (5-decimal coordinates, display fields only) and `cache/web/intersections.geojson` (clusters with at least one crash: crashes, ksi, eb).
- `notebooks/feels-vs-is/web/index.html`: one file, MapLibre GL JS from unpkg, basemap style `https://tiles.openfreemap.org/styles/positron` (free, no key).
- Layer switcher: Feels (`comfort_score`, red to green), Is (`harm_score`), Gap (categorical). Intersection dots sized by crashes, ringed by KSI. Click popup: street name, comfort level and reasons, harm and crash counts, death risk if struck, confidence.
- Story buttons that fly to: the top `hidden_danger` corridor (expected near 15th St NW, about 38.914, -77.0345); 21st St and I St NW (about 38.9011, -77.0466, two blocks from the venue, where a construction truck killed a commuter in July 2022); Connecticut Ave NW (about 38.930, -77.055; DDOT dropped its planned protected lanes in April 2024). Keep a story only if the numbers support it.
- A legend, a one-line explanation, and links to the README and PR.
- Publish: put `index.html` and the two GeoJSON files on an orphan `gh-pages` branch (kept out of the PR), push it to `origin`, then enable Pages with `gh api -X POST repos/BryceOB13/ridescoredc-models/pages -f "source[branch]=gh-pages" -f "source[path]=/"`. The site is `https://bryceob13.github.io/ridescoredc-models/`.

## Definition of done

- [ ] Results Parquet: 28,978 rows, unique (`osm_u`, `osm_v`, `osm_key`), no nulls in `comfort_score`, `harm_score`, `gap_class`.
- [ ] Notebook runs top to bottom from a fresh kernel in under 5 minutes with the crash cache present.
- [ ] README, one page: what it produces, scales and directions, inputs, precedence rules, thresholds, crash match rates, and what it cannot tell you (no bicycle exposure, so low harm can mean few riders; 2020 AADT; separated tracks inherit street attributes; pedestrian-derived death-risk curve; crash reporting gaps; no signal timing or turn-lane data).
- [ ] Map live on GitHub Pages and linked from the README.
- [ ] PR open against `develop`, changing only `notebooks/feels-vs-is/`.

## Stretch, in order

1. Traffic signals at intersections: `Transportation_Signs_Signals_Lights_WebMercator/MapServer/170` (`INTERSECTIONKEY`, `BIKE_PHASE`, `LPI`, `NTOR_SIGNAGE`), snapped within 25 m of clusters. Add to the intersection model and popups.
2. Low-stress islands: connected components of `comfort_lts` ≤ 2 (networkx on `osm_u`/`osm_v`), one color per island.
3. Exposure proxy: Capital Bikeshare dock capacity within 400 m (GBFS `station_information`) as a covariate in the block model.
4. Streetlights per 100 m by `BLOCKKEY` (layer 90 of the signals service).
5. AADT refresh from `Transportation_TrafficVolume_WebMercator/MapServer/5` (2024) by `ROUTEID` and measure overlap.

## Sources

- Furth LTS tables: [PDF](https://bpb-us-e1.wpmucdn.com/sites.northeastern.edu/dist/e/618/files/2014/05/LTS-Tables1.pdf)
- Montgomery County LTS methodology: [Appendix D](https://montgomeryplanning.org/wp-content/uploads/2017/11/Appendix-D.pdf)
- Cicchino et al. 2020, protected lane types and injury risk: [PubMed](https://pubmed.ncbi.nlm.nih.gov/32388015/)
- Teschke et al. 2012, route infrastructure and injury risk: [PubMed](https://pubmed.ncbi.nlm.nih.gov/23078480/)
- AAA Foundation, impact speed and pedestrian risk: [Tefft 2011](https://aaafoundation.org/research/impact-speed-pedestrians-risk-severe-injury-death/)
- Crashes in DC: [DC GIS layer 24](https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Public_Safety_WebMercator/MapServer/24)
- Vision Zero task force: [Q1 2026 minutes](https://www.open-dc.gov/sites/default/files/documents/mins-Q1_2026_MCRTF.pdf)
- WABA, 2026 DDOT oversight testimony: [testimony](https://waba.org/document/2026-ddot-performance-oversight-hearing-testimony/)
