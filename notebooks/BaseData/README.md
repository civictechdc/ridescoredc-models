# BaseData

**Read this before any other folder.** Every model in the project scores the
same road segments with the same attributes. This folder is where those come
from, and what they mean.

## Sources

| What | Where |
|------|-------|
| Roadway blocks | [Open Data DC — Roadway Block](https://opendata.dc.gov/datasets/DCGIS::roadway-block/about) |
| Crashes | [Open Data DC — Crashes in DC](https://opendata.dc.gov/datasets/crashes-in-dc/about), filtered to bicyclist injuries and fatalities |
| City boundary | Open Data DC — Washington DC Boundary |

The exact URLs are in
[`config.py`](../../tools/ridescore-cli/src/ridescore/config.py), which is the
single place any of these values are defined.

## What a segment carries

Normalised from the raw roadway-block attributes:

| Attribute | Notes |
|---|---|
| `route_id`, `route_name` | identity |
| `function` | Local, Collector, Minor Arterial, Principal/Primary Arterial, Freeway, Interstate, Other |
| `num_lanes` / `num_lanes_raw` | **filled** vs **as recorded**. Missing becomes 1. |
| `speed_limit` / `speed_limit_raw` | **filled** vs **as recorded**. Missing becomes 25 mph. |
| `bike_facility_type` | protected_track, buffered_lane, painted_lane, none |
| `parking_presence`, `road_width`, `pavement_condition` | as recorded |
| `crash_count_5yr` | bicyclist injury/fatality crashes within ~10 m, over five years |

## The thing to understand before you model anything

**Missing data is everywhere, and how it is filled changes your answer.**

The `_raw` columns exist so you can tell a recorded value from an imputed one.
The map displays raw values; the scores use filled ones. If your model treats a
filled-in 25 mph the same as a measured 25 mph, you are asserting something
about thousands of streets that nobody measured.

There is a live example of getting this wrong in the published score: a missing
lane count is treated as **1 lane** by the stress rules (a quiet residential
street) and simultaneously scored **10/100** by the lane-count component (as bad
as an eight-lane road). Both readings of the same blank, in the same model. See
`NUM_LANES_TO_SCORE_DEFAULT` in `config.py`.

Look at how much of each column is actually populated before you trust it.

## Status

The `ridescore fetch` command that will produce these snapshots is still being
ported from
[`../archive/data_processing.ipynb`](../archive/data_processing.ipynb) — see
the status table in
[tools/ridescore-cli/README.md](../../tools/ridescore-cli/README.md). Until it
lands, the archived notebook's cells 2–6 are the working reference for how the
network is built.

**Open question:** whether this folder commits a small extract (a few hundred
segments) so the notebooks run with no network at all, or whether every model
fetches live. Not yet decided — it is easier to judge once `fetch` exists and
we can see how large a useful extract really is.
