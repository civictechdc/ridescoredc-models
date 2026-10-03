# Low-Stress Network Fragmentation Score (`connectivity_lts`)

**In short:** a street can be calm to ride on and still be useless for getting anywhere, if the only way to reach it is along a stressful street. Existing bike-stress scores rate each street segment on its own and miss this. We rate every segment on its own first, then check whether each calm segment is part of a large connected network of calm streets, or is cut off from it.

Snapshot date: **2026-09-29**. Segment IDs (`osm_u`, `osm_v`, `osm_key`) only hold within one snapshot, so the date is on every row.

## Result

`connectivity_lts` puts every one of the 28,978 street and trail segments (2,165 km) in one of four classes:

| Class | Segments | % | km | Meaning |
|---|---|---|---|---|
| `High` | 4,645 | 16.0 | 339 | High stress on its own attributes. |
| `Medium` | 5,835 | 20.1 | 445 | Medium stress on its own attributes, or speed/lanes unknown (see limitations). |
| `Low-Isolated` | 2,049 | 7.1 | 144 | Calm on its own attributes, but **not** part of a large connected network of calm streets. |
| `Low-Connected` | 16,449 | 56.8 | 1,237 | Calm on its own attributes **and** part of a large connected calm network. |

**Headline:** of the 18,498 segments that single-segment rules call Low-stress, **2,049 (11.1%) are isolated.**

**Which direction is safer:** stress rises from Low to Medium to High. Within Low, `Low-Connected` is the more useful for trip planning. `Low-Isolated` should **not** be read as better than `Medium`: it is calm on its own, but using it may mean riding on higher-stress streets to get there or back. This score does not rank `Low-Isolated` against `Medium`.

## Files and how to run

- `low_stress_fragmentation_v2.ipynb`: the notebook that produces everything below.
- `results.parquet`: one row per snapshot segment (28,978 rows).
- `connectivity_lts_map.png`: map of the four classes.

To run: from the repo root, `uv sync --group notebooks`, then run the notebook. It expects the snapshot files (`ridescore_dc_basemap_2026-09-29.parquet` and `.geojson`) in a `ridescore-data` folder next to the repo.

Some figures quoted below (marked "development check") come from checks run while building the method, outside the submitted notebook.

## How it works

**1. Combine two data sources.** The snapshot joins OpenStreetMap (OSM) streets to DC's DDOT roadway data. For speed and lanes we use DDOT first and fall back to OSM. A bike facility counts as present if either source says so, or if the segment is itself an off-street bike path.

**2. Rate each segment on its own (`base_stress_class`).** First matching rule wins:
1. Off-street bike path or trail: **Low** (no car traffic).
2. **High:** speed 35 mph or more, or 3+ lanes with no bike facility.
3. **Low:** speed 25 mph or less with a bike facility, or speed 20 mph or less with 2 or fewer lanes and no facility.
4. **Unknown:** speed or lanes is missing and the rules above could not decide.
5. **Medium:** everything else.

Why these rules: they are simple and use only three attributes. Requiring a facility for every Low street would make most residential streets Medium (development check: only about 3% have a facility; Medium would be 53% of the network). Allowing every quiet street up to 25 mph made Low 74% and left Medium nearly empty, because DDOT speeds cluster at 20 and 25 mph. The chosen rule is the middle ground: a facility earns the 25 mph limit, otherwise 20 mph (DDOT's most common posted limit). Result: Low 63.8%, Medium 11.0%, High 16.0%, Unknown 9.2%.

**3. Fix one-way directions.** To know whether a street is reachable we must know which way bikes may ride. The snapshot needed cleaning here:
- *The problem.* Each street is one row, built by merging its two directions. The two end-point IDs, `osm_u` and `osm_v`, are in **arbitrary order for one-way streets**, so treating `u -> v` as the legal direction gives roughly half of one-way segments (4,802 of 10,124) the wrong direction.
- *The fix.* Each row also has a `geometry`: a line drawn as an ordered list of points, so it has a start and an end. For one-way streets the line is drawn in the direction of travel. We find which end-point ID sits at the start of the line (by matching it with the neighboring segments' lines) and use the line's direction. Two-way streets get both directions. One-way streets also get both when a bicycle contraflow exemption applies (OSM `oneway:bicycle=no`, a DDOT contraflow lane, an OSM `opposite_lane`, or a left cycleway tagged `oneway=-1`; 381 segments).
- *Check (a spot check, not a proof).* Along long named one-way streets the line direction is consistent on 30 of 111 streets, versus 0 of 111 using `u -> v`. T Street NE (one-way eastbound per DDOT notice NOI-21-67-TOA): 7 of 8 segments point east. North Capitol Street (a divided road with right-hand traffic, so the NE side runs north and the NW side south): 79 of 79 and 82 of 84 match. **Not resolved:** Daniel French Drive SW. The data says southbound; one unverified source said northbound.

**4. Check connectivity.** We keep only the Low segments and build a directed network where bikes follow one-way rules. We then find groups of streets where you can ride from any street to any other **and back again**. Each group is one "connected network".
- A one-way segment whose two ends fall in different groups (no way back through Low streets) is a **cross-edge**: 1,335 segments (7.2% of Low).
- A Low segment is **isolated** if it is a cross-edge, or its network is shorter than **500 m** (about four city blocks). Everything else is `Low-Connected`.
- One group is large (13,093 segments, 70.8% of Low); the rest are small pieces and cross-edges. Development check: counting isolated segments at cutoffs from 250 m to 5 km gives 9.5% to 15.8%, so the headline is not very sensitive to the cutoff, but the 500 m choice is a judgement call.

Medium, High and Unknown segments are never part of this network. Unknown is shown as `Medium` in the final column, which allows only four values.

## Columns in `results.parquet`

| Column | Meaning |
|---|---|
| `osm_u`, `osm_v`, `osm_key`, `snapshot_date` | Segment ID and snapshot date. |
| `connectivity_lts` | The model column: `High`, `Medium`, `Low-Isolated`, `Low-Connected`. |
| `base_stress_class` | Class before the connectivity check: `Low`, `Medium`, `High`, `Unknown`. Comparing it with `connectivity_lts` is the finding. |
| `component_size_segments`, `component_size_m` | Number of segments and total length (m) of the segment's connected network. A cross-edge counts as its own network of 1 segment. |
| `is_isolated` | `True` for cross-edges and for networks under 500 m. |
| `is_one_way_bridge` | `True` for a cross-edge whose two ends both touch a network of 500 m or more. `False` for everything else. |
| `cross_edge_large_ends` | Cross-edges only: how many of the two ends touch a network of 500 m or more (0, 1 or 2). |

The size columns, `is_isolated` and `cross_edge_large_ends` are empty (never 0) for segments that are not Low.

## Open question: how to read cross-edges

All 1,335 cross-edges are `Low-Isolated`, since none sits on a round trip through Low streets. That label covers different situations, and we have not decided how to interpret them. They may not really be islands: one that touches a large network lets you enter or leave it, just not both ways. Or they may be fragile links: a one-way link that is the only connection between two networks is a single point of failure, which is a statement about the network, not extra stress on the segment. We keep both readings open with two extra columns. In this snapshot, 804 cross-edges touch no large network (short one-way chains), 526 touch one (spurs), and 5 touch two (bridges).

**Future work.** Routing on the same network could answer richer questions: the shortest Low-only round trip back to the main network, how much Low network is reachable within a few kilometers (and with a small allowance for stressful stretches), stress-weighted routes between real origins and destinations, and "missing link" analysis to find which upgrades would join the most calm network together. Validation against crash data, official LTS/BNA and ridership is also open.

## Inputs

Only the 2026-09-29 snapshot (OSM streets joined to DDOT attributes, with geometry): `osm_maxspeed`, `osm_lanes`, `osm_highway`, `osm_cycleway*`, `osm_oneway`, `osm_oneway_bicycle`, `dc_SPEEDLIMITS_OB`, `dc_TOTALTRAVELLANES`, `dc_BIKELANE_*`, the segment ID and geometry. **No crash data and no scores from the existing RideScore pipeline.** The snapshot has streets and bike trails only (no alleys, driveways, service roads, sidewalks or motorways).

## Limitations and assumptions

**Data**
- A segment with no bike-facility information is treated as having **no facility**. About 72% of segments have none in either source (development check); an untagged lane lowers a segment from Low and can fragment the network.
- Which OSM values count as a facility is a choice: `lane`, `track`, `buffered_lane`, `opposite_lane` count; `no`, `shared_lane`, `share_busway`, `separate`, `shoulder`, `sidewalk`, `crossing`, `traffic_island` do not.
- DDOT and OSM often disagree (development check: speed on 38% and lanes on 42% of segments with both). DDOT wins. Part of this is probably different definitions, such as lanes per direction versus total.
- 4.8% of segments have no DDOT match and 2.1% are weak matches; weak matches are used as is. Some DDOT lane counts are 0 on ordinary streets, and 0 is kept as a real value.
- The snapshot covers DC only, so Low networks that continue into Maryland or Virginia are cut at the border and look smaller near it.

**Rating**
- Thresholds are a **first draft chosen by looking at the distribution**, not validated. Posted limits stand in for real speeds. Traffic volume, parking, intersections, signals, surface and hills are not used.
- 2,655 segments (9.2%) are `Unknown` (missing speed or lanes) and appear as `Medium`. This removes them from the Low network, which can **add** fragmentation that is really missing data.
- 918 on-street segments are Low because they have a bike facility, even with 3 or more lanes (development check). This is looser than standard LTS on multi-lane roads.

**One-way handling and network**
- Direction comes from the line-drawing convention described above. It is **inferred and spot-checked on a few streets**, not stored in the data. Three one-way segments where the evidence was a tie are treated as two-way.
- Contraflow is recognized only through the four signals listed. Untagged contraflow lanes are missed, which makes the network look **more** fragmented than it is.
- Reversible or time-restricted roads (for example Rock Creek and Potomac Parkway) cannot be shown in a snapshot and are handled as the data shows them.
- Streets that meet at the same intersection count as connected, with no penalty for crossing a busy street and no turn restrictions. This is the usual convention but **overstates** connectivity.
- Connected means a round trip along Low streets only. A one-way segment that is the sole link between two large networks gets the same `Low-Isolated` label as a dead end. This is deliberate (see the open question).
- The 500 m cutoff is a judgement call (see above).

**Scope:** snapshot only. No crash data, no comparison with official LTS or BNA, and no validation against ridership. OSM is edited continuously, so a different snapshot will give somewhat different results.
