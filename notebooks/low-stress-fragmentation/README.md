# Low-Stress Network Fragmentation Score (`connectivity_lts`)

Existing bike-stress models (LTS, BNA, BLOS, BCI, Bike ISI) rate each street segment using only that segment's own attributes: speed, lanes, bike facility. None of them ask whether a "low-stress" segment can actually be **reached** from the rest of the low-stress network without riding on a stressful street first. A segment can be individually calm and still be an island.

This notebook adds that question. It builds a transparent single-segment stress class from the snapshot, then checks each Low-stress segment for membership in a large, connected, direction-respecting Low-stress network.

**Snapshot date:** 2026-09-29. Segment IDs (`osm_u`, `osm_v`, `osm_key`) are only valid within this snapshot, so `snapshot_date` travels with every row.

## What is in this folder

| File | What it is |
|---|---|
| `low_stress_fragmentation_v2.ipynb` | **The submitted notebook.** Clean, runs top to bottom, writes the two files below. |
| `results.parquet` | One row per snapshot segment (28,978 rows). Columns are described below. |
| `connectivity_lts_map.png` | Map of the four classes. |
| `low_stress_fragmentation.ipynb` | The exploratory notebook the clean one was built from. It keeps the diagnostics (missingness audit, threshold comparison, component size bands, cutoff sensitivity). Not needed to reproduce the results. |

**To run:** from the repo root, `uv sync --group notebooks`, then run `low_stress_fragmentation_v2.ipynb`. It expects the snapshot files `ridescore_dc_basemap_2026-09-29.parquet` and `.geojson` in a `ridescore-data` folder next to the repo (`../../../ridescore-data/` from the notebook).

## What it produces

`connectivity_lts` has four values:

| Value | Meaning |
|---|---|
| `High` | High stress on its own attributes. |
| `Medium` | Medium stress on its own attributes (also where speed or lanes are unknown, see assumptions). |
| `Low-Isolated` | Low stress on its own attributes, but **not** part of a large Low-stress network you can ride out of and back along. |
| `Low-Connected` | Low stress on its own attributes **and** part of a large, connected Low-stress network. |

**Which direction is safer.** Stress rises from Low to Medium to High. Within Low, `Low-Connected` is the more useful for trip planning than `Low-Isolated`. `Low-Isolated` should **not** be read as straightforwardly better than `Medium`: it is calm on its own attributes, but using it may require riding on higher-stress streets to get there or back. This score does not rank `Low-Isolated` against `Medium`.

**Scale (28,978 segments, 2,165 km of street and trail):**

| `connectivity_lts` | Segments | % | km |
|---|---|---|---|
| High | 4,645 | 16.0 | 339 |
| Medium | 5,835 | 20.1 | 445 |
| Low-Isolated | 2,049 | 7.1 | 144 |
| Low-Connected | 16,449 | 56.8 | 1,237 |

**Headline:** of the 18,498 segments that single-segment rules call Low-stress, **2,049 (11.1%) are isolated** and 16,449 (88.9%) are connected, using a 500 m cutoff (see "The isolation cutoff").

### Columns in `results.parquet`

| Column | Type | Meaning |
|---|---|---|
| `osm_u`, `osm_v`, `osm_key` | int | Segment ID (unique within the snapshot). |
| `snapshot_date` | str | Always `"2026-09-29"`. |
| `connectivity_lts` | str | The model column (above). |
| `base_stress_class` | str | Single-segment class before connectivity: `Low`, `Medium`, `High` or `Unknown`. Comparing it with `connectivity_lts` is the finding. |
| `component_size_segments` | Int64 | Number of physical segments in the segment's connected component. |
| `component_size_m` | float | Total length (m) of that component. |
| `is_isolated` | boolean | `True` for cross-edges and for components shorter than 500 m. |
| `is_one_way_bridge` | bool | `True` for a cross-edge whose two end components are both at least 500 m long. |
| `cross_edge_large_ends` | Int64 | For cross-edges only: how many of its two end nodes belong to a component of at least 500 m (0, 1 or 2). |

Component columns, `is_isolated` and `cross_edge_large_ends` are empty (`NaN` / `<NA>`, never 0) for segments that are not Low. For Low segments with no component of their own (cross-edges), size is 1 segment and the segment's own length. `is_one_way_bridge` is `False`, not empty, for everything that is not a bridge.

## Inputs

Only the 2026-09-29 base-data snapshot: OpenStreetMap street segments joined to DDOT roadway sub-block attributes (`osm_*` and `dc_*` columns, plus the segment geometry). The columns used are `osm_maxspeed`, `osm_lanes`, `osm_highway`, `osm_cycleway*`, `osm_oneway`, `osm_oneway_bicycle`, `dc_SPEEDLIMITS_OB`, `dc_TOTALTRAVELLANES`, `dc_BIKELANE_*`, `osm_u`, `osm_v`, `osm_key` and the geometry. **No crash data and no scores from the existing RideScore pipeline are used.** The snapshot contains streets and bike trails only (no alleys, driveways, service roads, sidewalks or motorways).

## Method

### 1. Merging DDOT and OSM attributes

Three clean columns are built before classification:

- **Speed and lanes:** DDOT first, OSM as the fallback when DDOT is empty. OSM's text (`"25 mph"`, `"2"`) is converted to numbers first. A DDOT speed of 0 mph is treated as missing (6 segments). A lane count of 0 is kept.
- **Bike facility:** present if **any** source says so: any `dc_BIKELANE_*` column set, an OSM `cycleway*` value of `lane`, `track`, `buffered_lane` or `opposite_lane`, or the segment is itself an off-street bike path (`cycleway`, `path`, `footway`).

### 2. Scoring rationale (`base_stress_class`)

Rules are applied in this order and the first match wins:

1. **Off-street path** (`cycleway`, `path`, `footway`) is **Low**. There is no car traffic, so speed and lanes do not apply.
2. **High:** speed of 35 mph or more, or 3 or more lanes with no bike facility.
3. **Low:** speed of 25 mph or less **with** a bike facility, **or** speed of 20 mph or less with 2 or fewer lanes and no facility.
4. **Unknown:** speed or lanes is missing and rules 1 to 3 could not decide.
5. **Medium:** everything else.

Result: Low 18,498 (63.8%), Medium 3,180 (11.0%), High 4,645 (16.0%), Unknown 2,655 (9.2%).

Why these rules:

- **Simple and transparent.** Three attributes, plain thresholds, no weights.
- **Why not "facility required for Low".** Only about 3% of residential streets carry a facility, so that rule made 53% of segments Medium and the Low network mostly bike lanes. That is stricter than standard LTS, which treats quiet, narrow, slow streets as low stress.
- **Why not "25 mph or less, 2 lanes or fewer, facility or not".** That made Low 74% of the network and left Medium nearly empty (1%), because DDOT speeds cluster at 20 and 25 mph.
- **The chosen compromise:** a facility earns the 25 mph limit, and a street without one must be 20 mph or slower, which is DDOT's most common posted limit and matches the no-facility rule in the existing RideScore LTS.
- **Missing values never pass silently.** In pandas a comparison with a missing value is `False`, so missing speed or lanes would otherwise fall into Medium by accident. They are labelled `Unknown` and kept visible in `base_stress_class`.

### 3. One-way streets: the finding and the fix

To ask whether a Low-stress street is reachable, we need to know which way bikes may ride. This is where the snapshot needed cleaning.

**The finding.** The snapshot has one row per street. When it was built, the two directions of each street were merged into one row. That preserved the street's drawn **geometry** but lost the original from/to direction, so `osm_u` and `osm_v` are in **arbitrary order for one-way streets**. If we assumed `u -> v` is the legal direction, about half of all one-way segments (4,802 of 10,124) would get the wrong direction and the network would look shattered. Evidence: the geometry starts at `u` for 5,286 one-way segments and at `v` for 4,802.

**What "geometry" means here.** Each row has a `geometry` column: a line made of ordered points, so it has a start (first point) and an end (last point). For a one-way street that line is drawn in the direction of travel. `osm_u` and `osm_v` are only the IDs of the two end nodes; they carry no location.

**The fix, in simple terms.**
1. For every segment, work out which of its two end nodes sits at the **start** of its line. A node's location is the point where its neighboring segments' lines meet, so we match the segment's first and last points to those meeting points.
2. A one-way segment becomes a directed edge from the **start node to the end node**.
3. A two-way segment gets both directions.
4. A one-way segment also gets the reverse direction when a bicycle contraflow exemption applies: `osm_oneway_bicycle = "no"`, a DDOT contraflow lane (`dc_BIKELANE_CONTRAFLOW`), an OSM `opposite_lane` cycleway, or `osm_cycleway_left_oneway = "-1"`. An explicit `osm_oneway_bicycle = "yes"` overrides these. 381 one-way segments have an exemption.

The result is 48,167 directed edges from 28,978 segments.

**Validation (a spot check, not a proof).**
- Along long named one-way streets, the geometry heading is consistent (90% or more of segments point the same way) on 30 of 111 streets, versus 0 of 111 when using `u -> v`. Many streets fall short of 90% (for example streets that bend or change direction along their length), so read this as a comparison, not an accuracy.
- T Street NE (one-way eastbound between Lincoln Road and 2nd Street NE per DDOT notice NOI-21-67-TOA, with a westbound contraflow bike lane): 7 of 8 one-way segments point east, and four of them carry the contraflow exemption. The one that does not is a short segment at the western end.
- North Capitol Street NE and NW (a divided road with right-hand traffic: the NE carriageway runs north, the NW carriageway south): 79 of 79 and 82 of 84 segments match.
- **Not resolved:** Daniel French Drive SW. The data says one-way southbound (and the OSM way is tagged one-way in the same direction). One unverified source said northbound. We could not confirm the real direction independently.

### 4. Directed graph, strong connectivity, and the two kinds of Low

1. Keep only the **Low** edges and build a directed graph (16,678 nodes, 32,388 directed edges). Parallel edges collapse into one, which is safe because every edge is already Low.
2. Find the **strongly connected components** (SCCs). An SCC is a set of nodes where you can get from any node to any other **and back again** while obeying one-way directions and contraflow exemptions. This is round-trip reachability, which is why we use strong and not weak connectivity.
3. A Low segment belongs to a component when both of its end nodes are in it. A one-way segment whose two ends fall in **different** components (no way back through Low streets) is a **cross-edge**: 1,335 segments (7.2% of Low). It has no component.
4. Component size is the total length (EPSG:26985, meters) of the Low segments in it. Each row is one physical segment, so a two-way street is never double-counted.
5. A Low segment is **isolated** if it is a cross-edge, or its component is shorter than 500 m. Isolated Low becomes `Low-Isolated`; the rest becomes `Low-Connected`.

Result: one giant component holds 13,093 segments (70.8% of Low). The rest is mostly small pieces and cross-edges. At a 500 m cutoff, 2,049 segments are `Low-Isolated`: 714 in small components and 1,335 cross-edges. For comparison (exploratory notebook), ignoring one-way directions would put 81.7% of Low in the largest component, so respecting one-way streets costs about 11 points of connectivity.

`Medium`, `High` and `Unknown` segments are never part of the graph. `Unknown` is mapped to `Medium` in the final column because it allows only four values.

### 5. The isolation cutoff

The 500 m cutoff (about four city blocks; the median segment is 50 m) is a judgement call. The share of Low segments counted isolated changes only moderately with it: 9.5% at 250 m, 11.1% at 500 m, 12.5% at 1 km, 13.6% at 2 km, 15.8% at 5 km. Cross-edges (1,335) are counted isolated at every cutoff.

## Open question: how to read cross-edges

All 1,335 cross-edges are `Low-Isolated`, because none of them is part of a round-trip Low network. That label mixes different situations, and we have not decided how to interpret them. Two readings pull in opposite directions:

- **They may not really be islands.** A cross-edge that touches a large Low network lets you leave or enter that network along it, even though you cannot return the same way.
- **They may be fragile links.** A one-way link that is the only connection between two networks is a single point of failure, and detours around it may need higher-stress streets. Note that this is about fragility of the network, not extra stress on the segment, which is already Low by its own attributes.

To keep both readings open without changing the primary label, the results carry two extra columns. `cross_edge_large_ends` is 0, 1 or 2 for each cross-edge (how many of its two end nodes sit in a component of at least 500 m), and `is_one_way_bridge` is `True` when it is 2. In this snapshot: 804 cross-edges have 0 large ends (short one-way chains), 526 have 1 (spurs off a large network), and only 5 have 2 (true bridges between two large networks). The columns only look at the two direct end components, not at chains of cross-edges.

### Suggested future work: shortest paths and accessibility

Component membership answers "is it connected at all". Routing on the same directed graph can answer richer questions:

- For each Low segment, how long is the **shortest Low-only round trip** back to the large network, and how long is the detour if a cross-edge is removed?
- How much Low network can be reached from a segment within, say, 1 to 3 km, and how does that change if the route may use a short Medium or High stretch (a limited stress budget)?
- Stress-weighted shortest paths between origins and destinations (schools, transit, jobs), instead of a hard Low-only subgraph.
- **Missing-link analysis:** which Medium or High segments, if upgraded, would join the most Low-network length together? Cross-edges and the 26 mid-sized components between 21 and 100 segments are natural candidates.
- Treat cross-edge chains (not just direct end components) and time-of-day effects explicitly.
- Validate against ground truth: crash data, official LTS and BNA, and survey or ridership data. None of these is used here.

## Known gaps, assumptions and limitations

**Data and merge**
- **No bike-facility information is treated as no facility.** About 72% of segments have no facility tag in either source and count as having none. An untagged lane lowers the segment from Low and can fragment the network.
- **Which OSM values count as a facility** is a choice: `lane`, `track`, `buffered_lane`, `opposite_lane` count; `no`, `shared_lane`, `share_busway`, `separate`, `shoulder`, `sidewalk`, `crossing` and `traffic_island` do not. A `separate` value means the lane is drawn as another way; that way is its own segment and is classified on its own.
- **DDOT wins over OSM for speed and lanes**, but they disagree often where both have a value: speed on 2,679 of 6,968 segments (38%), lanes on 5,572 of 13,255 (42%). Part of this is probably definitions (for example OSM lanes per direction versus DDOT total lanes). Where OSM says `no` facility but DDOT says one exists (321 segments), "present" wins.
- **Join quality:** 1,399 segments (4.8%) have no DDOT match, so their speed and lanes come from OSM alone. 605 (2.1%) are weak matches and their DDOT attributes are used as is.
- **Odd DDOT values:** some streets show 0 lanes (863 segments overall, mostly paths, but also 166 residential and 56 primary segments). Zero is kept as a real value and passes the "2 lanes or fewer" test.
- **Boundary effect:** the snapshot covers DC only. Low networks that continue into Maryland or Virginia are cut at the boundary, so components near the edge look smaller than they are.

**Classification**
- Thresholds (25 / 20 / 35 mph, 2 and 3 lanes) are a **first draft chosen by looking at the distribution**, not validated or calibrated. Posted speed limits stand in for real speeds. Traffic volume, parking, intersections, crossings, signals, surface and grade are not used.
- 2,655 segments (9.2%) are `Unknown` (2,198 missing speed only, 413 missing both, 44 missing lanes only). In the final column they become `Medium`. That removes them from the Low graph and so can **add** fragmentation that is really missing data.
- 918 on-street Low segments have a bike facility **and** 3 or more lanes. The rule lets a facility at 25 mph or less make a street Low regardless of lane count, which is looser than standard LTS on multi-lane roads.

**One-way handling and graph**
- **Direction comes from the geometry convention, which is inferred and spot-checked on a few streets** (see "Validation"). It is not stored in the data. 3 one-way segments where the evidence was a tie are treated as two-way. If the convention were wrong in some area, those streets would be misdirected.
- Contraflow is recognized only through the four signals above. Contraflow lanes that nobody tagged are missed, which makes the network look **more** fragmented than it is. 381 of 10,124 one-way segments have an exemption.
- **Reversible and time-restricted roads** (for example Rock Creek and Potomac Parkway, one-way southbound in the morning and northbound in the afternoon) cannot be represented in a snapshot. They are handled as the data shows them.
- **Free turning and crossing at nodes.** Two Low streets that share a node are connected, even if the node is an intersection with a busy street, and even where a real crossing would be difficult. Turn restrictions are not modelled, and there is no penalty for crossing a Medium or High street at a junction. This overstates connectivity.
- **Strong connectivity means round-trip reachability.** A one-way segment that is the sole link between two large networks gets the same `Low-Isolated` label as a true dead end. This is a deliberate consequence of the definition. See the open question above.
- Connectivity uses **only Low edges**. Medium and High segments are never traversed, even for a short crossing.
- 82 self-loops (cul-de-sacs and loops) and 188 parallel segments (same `u` and `v`, different `osm_key`) are handled by the segment ID and do not create double counting.

**Scope**
- Snapshot-only. No crash data, no comparison with official LTS or BNA, and no validation against ridership. Results depend on the 2026-09-29 OSM and DDOT state; OSM is edited continuously.
