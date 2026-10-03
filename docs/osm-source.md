# The OpenStreetMap road source

A second street network for the pipeline, alongside the DDOT roadway blocks. It
fetches OpenStreetMap, cuts it into segments, and fills in the columns
`ridescore_v1` reads, so the model scores OSM streets without any change.

```
uv sync --extra osm
uv run ridescore run --source osm --run-date 2026-10-03
uv run ridescore inspect --out out-osm
uv run scripts/make_package.py --out out-osm     # dist/ridescoredc-data-osm-preview-0.1
```

## The two sources are kept apart

| | DDOT (default) | OSM (`--source osm`) |
|---|---|---|
| Snapshots | `raw/<date>/` | `raw-osm/<date>/` |
| Artifacts | `out/` | `out-osm/` |
| Package | `ridescoredc-data-preview` | `ridescoredc-data-osm-preview` |
| Needs | the core install | the `osm` extra (`osmnx`) |

Neither source can overwrite the other's output. Neither can have `build` pick
up the other's newer snapshot. The DDOT pipeline never imports `osmnx` and runs
without the extra. Its output is byte-identical to what it was before this
source existed. The one addition is `network_source` in `run.json`, which
`make_package.py` uses to name the package. A `run.json` without it is read as
DDOT.

Nothing built from OSM is comparable with anything built from DDOT blocks,
because segment identity differs. That is why both packages keep the
`-preview` name.

## What was built

| File | Does |
|---|---|
| `sources/osm.py` | `fetch`: one Overpass query for DC, saved as `osm.xml`. The only OSM step that touches the network. |
| `network/osm_segments.py` | Cuts the XML into segments, offline. A port of `fetch_osm()` from `notebooks/BaseData/OSM_BaseData.ipynb`. |
| `network/osm_normalise.py` | Turns each segment into the same columns as the DDOT normaliser. |
| `config.py`, section "network: OSM source" | Filters, tag list, default tables. |
| `scripts/make_osm_fixture.py` | Cuts the committed test extract out of a real snapshot. |
| `tests/test_osm.py` | A synthetic grid plus a committed real extract. No test touches the network. |

### Fetch

The query asks for every way in DC (`config.OSM_DC_AREA_ID`) that the network
keeps, plus the nodes those ways use. The filters are the ones the team settled
in the notebook:

- streets from trunk down to living_street, plus `highway=cycleway`;
- bike trails: paths that allow bikes, and footways where bikes are designated;
- alleys, fetched only so a street is split where an alley meets it.

Two lessons from running it for real:

- Overpass refuses requests' default User-Agent with a **406**. The OSM fetch
  sends its own, and the DDOT fetches are left as they were.
- Overpass answers **200** even when a query runs out of time, with a
  `<remark>` saying where it stopped. `fetch` refuses that answer rather than
  saving a partial city.

## Decisions

### What a segment is

A segment is one stretch between intersections, covering both directions of
travel. It is also cut where an alley meets the street (matching DDOT's
SubBlocks) and wherever any tag in `config.OSM_RAW_TAGS` changes. So a bike lane
that starts mid-block splits the block rather than blurring into `lane;no`.
Alleys are then dropped.

### `segment_id`

`osm:<low node>-<high node>-<n>`:

- the two numbers are the OSM node ids at the ends, smaller first;
- `n` is osmnx's number for telling apart two segments between the same pair of
  nodes.

The id is unique (the build fails if it is not), and it is the same whichever
way the street was drawn. It cannot collide with a DDOT `BLOCKKEY`.

It is **stable across rebuilds** unless someone edits the intersection at one of
its ends, because node ids are permanent in OSM. The trailing number is the weak
part. It depends on the order osmnx meets parallel edges in, and it is almost
always 0.

### Filling in what OSM leaves out

OSM tags win. When a tag is missing, the value is filled in from the highway
type (`config.OSM_DEFAULT_*`), and the `_raw` column stays empty. That way
`ridescore inspect` still reports how much was filled in.

| Column | From OSM | When OSM says nothing |
|---|---|---|
| `function` | `highway`; a `_link` takes its parent's class; trails are Local | `Other` |
| `bike_facility_type` | `protected_track`: a cycleway, a trail, or `cycleway[:side]=track`. `buffered_lane`: `=lane` with a buffer. `painted_lane`: `=lane`. Direction ignored, as in the DDOT rules. | `none` |
| `num_lanes` | `lanes` (of `2;3`, the most) | 2 on local streets (1 if one-way), 2 on collectors and minor arterials, 4 on principal arterials and trunks, 0 on trails |
| `speed_limit` | `maxspeed`; a bare number is km/h, OSM's convention | 20 mph on local streets (DC's default since 2021), 25 on arterials, 35 on trunks, 0 on trails |
| `pavement_condition` | `smoothness` (OSM has no condition index) | empty, which the model scores as 50 |
| `road_width` | `width`, metres to feet | 11 ft per lane + 8 ft per side parked on (trails 10 ft) |
| `parking_presence` | `parking:*` / `parking:lane:*` | no parking |

Width is never left empty, because the map's `user_score` multiplies every score
by its weight. One empty score would empty the whole user score.

### Crashes

`network/crash_join.py` runs unchanged on OSM geometry.

## What it does not do

From a full-DC run on 2026-10-03: 28,241 segments, 2,190 km, 44 s to fetch and
build.

- **Most lane, speed and pavement values are guesses.** Speed was filled in on
  70% of segments, lanes on 52%, and pavement on 98%.
- **The lane score is skewed.** `num_lanes_score` scores the *raw* lane count,
  and a missing count scores 10. That is a defect kept on purpose; see
  `config.NUM_LANES_TO_SCORE_DEFAULT`. On OSM, 85% of local streets have no
  `lanes` tag. So half the network scores 10, as bad as a six-lane road, and the
  mean lane score is 36.8 rather than the 75.2 the filled-in lane counts would
  give.
  - This affects only the map's user-weighted score: `ridescore_v1` and the
    stress level use the filled-in count.
  - Fixing it is a change to the model, so it is left for its own PR.
- **The pavement slider barely tells streets apart.** Nearly every OSM segment
  scores 50.
- **The crash score saturates.** OSM segments are shorter than DDOT blocks, so
  the run's 95th-percentile crash count falls to 1 on the full city. One nearby
  crash takes a segment's crash score from 100 to 0.
- **Buffered lanes are rare.** Only 49 segments city-wide come out as
  `buffered_lane`, because few OSM ways carry `cycleway:*:buffer`. DDOT records
  many more.
- **No comparison with DDOT yet.** The two networks are not matched street by
  street. `notebooks/BaseData/OSM_BaseData.ipynb` has a join that could do it.
- **Short segments are dropped.** Segments under 8 m (`MIN_SEGMENT_LENGTH_M`) do
  not reach the output. Cutting at alleys makes more of them than DDOT does.
- **Separately drawn bike lanes.** A cycle track drawn as its own way is scored
  as its own trail segment. The street beside it, tagged `cycleway=separate`,
  counts as having no facility.

## Tests

- **Synthetic grid** (`tests/test_osm.py`): a 3×3 grid written in the test, one
  street per rule. It covers:
  - the alley split, and a split on a tag change;
  - ids not depending on drawing direction;
  - each tag parser;
  - an Overpass answer that was cut short.
- **Committed extract** (`tests/fixtures/osm_snapshot/2026-10-03/`): the real
  OSM around 14th and U St NW, cut by `scripts/make_osm_fixture.py`. It has 156
  segments, all four facility types and 67 crashes. It carries a golden file
  (`tests/fixtures/expected_osm_extract.csv`) and four worked examples whose
  arithmetic is written out by hand.

Without the `osm` extra, `tests/test_osm.py` is skipped and the rest still run.
