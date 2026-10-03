# Feels vs. Is: comfort and harm scores for DC streets

LTS tells you how a street feels. Crashes tell you what happens on it. This model scores both for every segment in the `ridescore_dc_basemap_2026-09-29` snapshot and every intersection, then maps where they disagree.

Map: [bryceob13.github.io/ridescoredc-models](https://bryceob13.github.io/ridescoredc-models/). Notebook: `feels_vs_is.ipynb`. Logic: `feels_vs_is.py`. Design notes: `SPEC.md`.

On the map, search any street or pick a ward for a report: crash trend since 2025, worst blocks and intersections, and what DDOT has changed or planned there. The URL carries the view, so a report can be linked.

## What it produces

`feels_vs_is_results.parquet`, one row per snapshot segment (28,978 rows), keyed by `osm_u`, `osm_v`, `osm_key` and `snapshot_date = "2026-09-29"`.

| Column | Scale and direction |
|---|---|
| `comfort_score` | 0 to 100, higher is more comfortable. Each LTS level owns a band (1: 80 to 100, 2: 60 to 80, 3: 30 to 60, 4: 0 to 30); volume, truck share, door zone, pavement and traffic calming move a segment within its band |
| `comfort_lts` | 1 (calm) to 4 (hostile). Furth 2012 tables with Montgomery County amendments |
| `kid_ok` | `comfort_lts == 1` |
| `harm_score` | 0 to 100, higher is worse. Length-weighted percentile of the segment's Empirical Bayes crash rate, taking the worse of its block and its worst end intersection. 90 means the worst 10 percent of network length |
| `harm_driver` | `block` or `intersection`, whichever set `harm_score` |
| `crashes_5yr`, `ksi_5yr` | Bicyclist injury crashes on the segment's DDOT block since Oct 2021, and how many were fatal or major injury |
| `node_crashes_5yr`, `node_ksi_5yr` | The same at the worse of its two end intersections |
| `death_risk_if_struck` | 0 to 1. A logistic curve fit to the AAA Foundation pedestrian points, evaluated at the posted speed. A pedestrian-derived proxy, not a cyclist measurement |
| `gap_class` | `hidden_danger`, `fix_first`, `scary_but_quiet`, `calm`, `middle` |
| `reasons` | Up to three short phrases, comfort first, then harm |
| `confidence` | `high`, `medium`, `low`, from match quality and how many fields were imputed |
| `speed_mph`, `lanes`, `facility`, `door_zone`, `parallel_track` and their `_src` columns | The cleaned inputs and where each came from |
| `lts_v1` | The pipeline's LTS v1 on matched rows, for comparison. Null on the 1,399 unmatched rows |

| Class | Feels | Is | Network length |
|---|---|---|---|
| `hidden_danger` | LTS 1 or 2 | `harm_score` >= 92 | 4.8% |
| `fix_first` | LTS 3 or 4 | `harm_score` >= 92 | 3.0% |
| `scary_but_quiet` | LTS 4 | `harm_score` <= 40 | 1.4% |
| `calm` | LTS 1 or 2 | `harm_score` <= 40 | 38.4% |
| `middle` | everything else | | 52.4% |

The spec started at a harm threshold of 80. That put 13 percent of the network in `hidden_danger`. 92 keeps it to a short list, 104 km across 890 blocks.

## Inputs

- Snapshot: `~/ridescore-data/ridescore_dc_basemap_2026-09-29.parquet`, 28,978 segments, 135 columns, OSM geometry joined to DDOT blocks.
- Crashes: DC GIS `Public_Safety_WebMercator/MapServer/24`, bicyclist injury crashes from 2021-10-01, fetched at run time and cached in `cache/crashes.parquet`. 2,297 crashes, 202 fatal or major injury, 9 fatal. The count is still climbing: 546 in the first nine months of 2026 against 559 in all of 2025.
- LTS v1 from `src/ridescore/models/ridescore_v1/lts.py`.

Nothing else. Ward, ANC and location stay out of the models so that expectations come from design rather than neighborhood.

## How it works

**Clean.** One value per field with its source. Speed: DDOT `SPEEDLIMITS_OB` (23,137 rows), then OSM `maxspeed` (1,451), then the median of matched rows in the same OSM class (4,390). Lanes: DDOT (26,716), OSM (493), class median (1,769). Volume: DDOT 2020 AADT (11,660), class median for the rest, used as a percentile. Facility, most protective wins: separated (OSM cycleway, path, or bike-designated footway), protected, buffered, painted, sharrow, none, from DDOT bike lane columns and OSM cycleway tags. 1,295 street rows carry `cycleway=separate`, meaning their bike facility is mapped as its own cycleway row; those streets are scored as mixed traffic with `parallel_track` set. 1,628 painted or buffered lanes sit beside parking (`door_zone`).

**Feels.** Furth's LTS by facility, speed, lanes per direction, door-zone reach, centerline and volume. By length: LTS 1 on 1,206 km, LTS 2 on 543, LTS 3 on 257, LTS 4 on 158. LTS v1 on the same network: 76, 998, 243 and 772 km. The difference is mostly residential streets: Furth rates a 20 mph street with no centerline and under 3,000 vehicles a day as LTS 1, while v1 has no LTS 1 without a protected lane.

**Intersections.** Degree 3+ nodes clustered within 15 m (DBSCAN), 7,672 clusters, so a complex junction or a track crossing counts once.

**Crash assignment**, in EPSG:26985. A crash is an intersection crash if it sits within 25 m of a cluster, or within 45 m while DC's own `OFFINTERSECTION` distance is 20 m or less. Otherwise its `BLOCKKEY` finds its DDOT block, otherwise the nearest segment within 40 m, otherwise unmatched. Of 2,297 crashes: 933 intersection (41 percent), 1,146 by block key (50 percent), 153 nearest segment (7 percent), 65 unmatched (3 percent).

**Harm.** A negative binomial model of crash counts on design only. Blocks (15,420 units, offset log length): function class, facility, speed bucket, lanes bucket, volume percentile, parallel track. Intersections (7,672): approaches, highest-class approach, fastest approach, wide approaches, any separated or protected approach. Both fits converged (dispersion 1.07 for blocks, 3.80 for intersections). Empirical Bayes then blends each unit's own record with its design expectation, `w = 1 / (1 + alpha * mu)`, `eb = w * mu + (1 - w) * observed`, so a block with one crash and a quiet design is pulled back toward its peers while 14th St NW with nine stays where it is.

**Gap.** The table above. `reasons` names the facility, lanes and speed, then the crash record, then crossings per km when a block is crossed more than 20 times per km.

## Validation

Train on crashes before 2025 (1,192), test on 2025 to Oct 2026 (1,105 injury crashes, 100 serious). Rank by each method, take the worst 10 percent of block length or the worst 10 percent of intersections, and count the test crashes caught.

| Ranking | Blocks: injury | Blocks: serious | Intersections: injury | Intersections: serious |
|---|---|---|---|---|
| a. LTS v1 (design only) | 13% | 13% | 13% | 2% |
| b. Feels comfort (design only) | 21% | 15% | 18% | 17% |
| c. Harm model expectation (design only) | 37% | 35% | 29% | 35% |
| d. Empirical Bayes with crash history | 44% | 35% | 43% | 39% |

(a) to (c) use only the street's design. (d) also uses the train-period crash record, so it measures persistence: streets that hurt people keep hurting people. Capture curves are in the notebook.

## Top of the list

Hidden danger, one row per block, by harm: the 9th St NW two-way track at Rhode Island Ave (7 injury crashes on one block, 7 more at the intersection), the 14th St NW protected lane north of Columbia Heights (9 crashes, 1 serious), the K St NW track downtown, 14th and U St NW, the 11th St NW track at H St, Irving St NW at 14th, and the 15th St NW track (6 crashes, 2 serious). 35 km of the 104 km of hidden danger is separated track and 4 km is protected lane: the facilities a stress map rates safest.

## Trend and changes on the ground

**Trend.** Each street, ward and block compares its injury crash rate since Jan 2025 with Oct 2021 to Dec 2024. Recorded bicyclist injuries rose about 1.7 times citywide over that split, so the label is relative to the city: `rising` means at least 1.5 times the citywide change with two or more recent crashes, `falling` at most 0.67 times with two or more earlier crashes, tested with a binomial test on the split (p < 0.2 for the firm label, otherwise marked weak). Fewer than three crashes in total is `too few`. By block, 28,119 segments are too few, 243 rising (76 firm), 362 falling (36 firm), 142 flat.

**Changes.** DDOT's ProTrack project lines (`Transportation_Plans_Projects_Study_WebMercator/MapServer/138`) matched to segments by route ID and measure, else by lying within 15 m of the project line. Bike lane, bike marking, speed management, safety, signal and streetscape work types since 2019; routine re-striping is left out. 340 projects touch 4,192 segments (205 km); 1,231 of the 3,216 hidden-danger and fix-first segments have a completed project on them and 297 have one planned or in progress. Each report lists the projects with the injury crash rate before and after completion on the matched blocks and intersections. There is no control group and no exposure, so a rising rate after a new lane can mean more riders. Read it as a check, not a verdict.

**Map.** `web/index.html` renders with Mapbox GL JS when a public token is set in `web/config.js`, otherwise MapLibre GL with OpenFreeMap's dark style. The page is published from the fork's `gh-pages` branch together with the GeoJSON and `reports.json`.

## What it cannot tell you

- **No bicycle exposure.** Low harm can mean few riders. `scary_but_quiet` exists to say so; it is 1.4 percent of the network and almost all arterials and parkways at 35 mph or more.
- **Volumes are 2020 counts** and 60 percent of segments have none, so volume enters as a class-median percentile.
- **Separated tracks inherit the adjacent street's speed, lanes and volume** from the join. They are scored as separated from traffic, with the street's speed kept for `death_risk_if_struck` at crossings.
- **Death risk is a pedestrian curve** (Tefft 2011), evaluated at the posted limit rather than impact speed.
- **Crash reporting gaps.** The layer holds what police recorded as a bicyclist injury. The July 2022 truck death at 21st and I St NW does not appear as a bicyclist fatality in it. About 3 percent of crashes cannot be placed on the network.
- **No signal timing, turn lanes, lighting or construction data.** Intersection expectations come from geometry alone.
- **Trend labels on single blocks rest on a handful of crashes.** Use the street and ward trends; block trends are a pointer, not a finding.
- **Harm at intersections is sparse.** 657 of 7,672 intersections have any crash, so a single crash puts an intersection in the top 8 percent. EB shrinks it, but one event is still one event.

## Next steps

Capital Bikeshare trips as exposure. Signals (`BIKE_PHASE`, `LPI`) at intersections. Low-stress islands from `comfort_lts <= 2`. A second layer in RideScore beside LTS.

## Sources

Furth, [LTS tables](https://bpb-us-e1.wpmucdn.com/sites.northeastern.edu/dist/e/618/files/2014/05/LTS-Tables1.pdf); Montgomery County, [LTS methodology](https://montgomeryplanning.org/wp-content/uploads/2017/11/Appendix-D.pdf); Cicchino et al. 2020 on [protected lane types](https://pubmed.ncbi.nlm.nih.gov/32388015/); Tefft 2011, [impact speed and pedestrian risk](https://aaafoundation.org/research/impact-speed-pedestrians-risk-severe-injury-death/); Highway Safety Manual on [Empirical Bayes](https://www.highwaysafetymanual.org/); DC Vision Zero task force, [Q1 2026 minutes](https://www.open-dc.gov/sites/default/files/documents/mins-Q1_2026_MCRTF.pdf).
