# Ported defects

The port reproduces the notebook, including the parts of it that are wrong. Each
one is marked `DEFECT` in `config.py` beside the value it concerns, and each has
a test asserting the defective behaviour — so fixing one shows up as a failing
test rather than as a score that quietly moved.

They are listed here because a reader of the output deserves to know, and
because each fix is its own change: every one of these moves published numbers
and needs its own review.

---

## In the attributes

**A recorded speed limit of exactly 1 mph is discarded.** The test for "the
source said something" is `> 1` rather than `> 0`, so a 1 mph block is treated as
unknown and filled in with 25. `config.SPEED_LIMIT_MIN_VALID`.

**Only the outbound speed limit is read.** `SPEEDLIMITS_IB` is ignored and the
two can differ. `config.SPEED_LIMIT_FIELD`.

---

## In the crash join

**The buffer is applied in Web Mercator.** A unit at DC's latitude is about 0.78
of a real metre, so `CRASH_BUFFER_M = 10` is roughly 7.8 m on the ground. It
changes which crashes attach to which street. `config.CRASH_BUFFER_CRS`.

---

## In the scores

**A missing lane count scores 10** — as bad as an eight-lane road — while the
stress rules read the same missing value as one lane, a quiet residential
street. The same street is simultaneously assumed calm and scored hostile.
`config.NUM_LANES_TO_SCORE_DEFAULT`.

**The speed score is unbounded.** `100 - 2 × speed` goes negative above 50 mph.
`config.SPEED_LIMIT_SCORE_SLOPE`.

**The width score is unbounded, and a missing width scores best of all.**
`100 - width` goes negative on a wide road, and a street nobody measured comes
out at 100. `config.ROAD_WIDTH_SCORE_INTERCEPT`.

---

## In the geometry

**Detail is destroyed at build time and cannot be recovered.**
`SIMPLIFY_TOLERANCE_M = 4` is about eight pixels at zoom 18, applied once to the
stored geometry rather than chosen per zoom when serving.

**Short blocks are dropped rather than simplified.**
`MIN_SEGMENT_LENGTH_M = 8` removes *features*, so a short block does not exist at
any zoom, on any map, for anyone.

Both are in `config.py` under `network: output geometry`. Neither belongs in a
published dataset: they are decisions about drawing, made where the data is
produced.

---

## Fixed during the port

These could not change any score, which is why they were not left alone:

- **The notebook does not run top to bottom.** Cell 4 used `gdf` two cells before
  it was created.
- **Coordinate rounding assumed a Z on every coordinate** and failed on plain 2D
  geometry. DC's blocks happen to carry one; a source that stopped would have
  stopped the run.
- **`serious_injury_count_5yr` and `fatal_count_5yr` were written as zero and
  never computed**, although the crash records carry both. They are computed now.
- **The DC boundary came from a live Nominatim lookup**, which cannot be cached
  and answers differently over time. It is a published DC dataset and is fetched
  like any other input.
- **The ArcGIS `202` placeholder was treated as a successful download**, because
  `requests`' own `ok` is true for it.

---

## Not a defect, but decided rather than inherited

**The crash window is rolling** — five years counted back from the run date — so
two runs a month apart are over different windows.

**The crash score is normalised against each run's own data**, so the same street
can score differently in two runs over otherwise identical inputs. The derived
95th-percentile count is recorded in `run.json`.

Both are the notebook's behaviour, both are kept, and both are the reason
`--run-date` is an explicit input rather than the clock.

**An unknown pavement condition scores 50**, the middle. Unlike the lane count
above, this one is defensible: an unmeasured surface is assumed average rather
than bad.
