# Fixtures

## `snapshot/2026-08-05/`

An extract of a real `raw/2026-08-05/` snapshot: **34 roadway blocks** and the
**49 crashes** within 100 m of one of them. Same filenames and same shape as a
real snapshot, so `build` reads it without knowing the difference.

The blocks were chosen to cover every combination of bike facility type and road
function the source uses, plus blocks with crashes nearby, blocks with no
recorded speed limit, and blocks with no pavement condition — the cases where a
rule has to decide something rather than read it.

Two deliberate differences from a real snapshot:

- **The boundary is the extract's own bounding box**, not the city's, so the
  fixture does not carry a 490 kB polygon to exercise a clip that removes
  nothing.
- **The crashes are only those near a kept block.** The real file has some two
  thousand.

## `expected_extract.csv`

Every column of `road_segment` and `ridescore_v1_scores` for those 34 blocks,
joined on `segment_id`.

It is a **golden file**: produced by this code and reviewed once. It cannot say
the numbers are right, only that they have not moved. What says they are right
is `TestWorkedExamples` in `tests/test_extract.py`, where the arithmetic is
written out by hand from the notebook.

It is a CSV rather than a parquet so that a changed score appears in a review
diff. Regenerate it only when a change is *meant* to move scores, and say in the
commit message which numbers moved and why.
