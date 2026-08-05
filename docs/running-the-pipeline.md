# Running the pipeline

Public DC data in, three datasets out. No database, no server, no credentials.

```
uv sync
uv run ridescore run --run-date 2026-08-05
uv run ridescore inspect
```

That is the whole thing. `run` is `fetch` then `build`; they are separate
commands because they fail for different reasons and only one of them needs the
network.

---

## The commands

| | |
|---|---|
| `ridescore fetch` | download the roadway blocks, the cyclist crashes and the city boundary into `raw/<date>/` |
| `ridescore build` | normalise, score, and write `out/` |
| `ridescore run` | both |
| `ridescore inspect` | what a run produced, and what moved since another one |

### `fetch`

Writes `raw/<run-date>/` and **never deletes an older snapshot**. Comparing a
street against its own past self means re-running the older inputs through
today's model, so a cache that overwrote itself would have destroyed every
comparison point before anyone asked for one.

Fetching twice on the same date reuses what is there. `--refresh` downloads
again.

The ArcGIS download endpoints answer `202` with a placeholder while they
generate the file and only then `200` with the data, so `fetch` waits rather
than saving the placeholder. A 46 MB roadway file takes a minute or so.

### `build`

Reads the newest snapshot on or before `--run-date` and writes:

| File | Produced by | Holds |
|---|---|---|
| `road_segment.parquet` | the network build | geometry and street attributes |
| `crashes.parquet` | the crash source | the reduced crash records |
| `ridescore_v1_scores.parquet` | the model | the component scores and the blend |
| `run.json` | the run | what it used, and what it worked out for itself |

Three files rather than one wide frame: a street's width is a fact about the
street, its RideScore is a claim one model makes about it, and a second model
scoring the same streets should not have to touch the first one's file.

`build` reads no network. Given the same snapshot it produces byte-identical
files, which is what lets a later deployment decide what to reload by comparing
content rather than by trusting a version number.

### `--run-date`

An explicit input, never read from the clock mid-build, because two things
depend on it:

- **the crash window** is five years counted back from it, so it moves with each
  run;
- **the crash score is normalised against each run's own data**, so the same
  street can score differently in two runs over otherwise identical inputs.

Both are recorded in `run.json` — the window, and the 95th-percentile crash
count the run derived — because a score is only interpretable against the run
that produced it.

### `inspect`

Row counts, network length, the spread of every score column, and how much of
the network had to be filled in because the source did not say. `--against
<dir>` compares two runs per column, joined on `segment_id`, so a street that
appeared or disappeared is counted separately rather than shifting every mean
underneath the comparison.

A successful run and a good run are different things; this is how to tell them
apart before a database exists.

---

## What the weights live in

`src/ridescore/models/ridescore_v1/weights.toml`, on their own:

```toml
[weights]
lts = 0.6
crash = 0.3
facility = 0.1
```

They are the definition of what RideScore is, rather than machinery of the
calculation, so changing one is a one-line diff that can be reviewed without
reading any Python. They must sum to 1; `build` fails if they do not, rather
than quietly producing a score on a different scale.

Everything else — thresholds, lookup tables, buffer distances — is in
`config.py`.

---

## The key

`segment_id` is the source's `BLOCKKEY`.

`ROUTEID`, which the notebook carried, names a **route**: Eastern Ave NW is one
`ROUTEID` across forty-odd blocks. It cannot key a per-block score, and nothing
noticed because the notebook never needed a key. `OBJECTID` is unique but is a
serial the publisher reassigns — the same trap as keying feedback to `ogc_fid`.

This is not a claim that a block keeps its `BLOCKKEY` when DDOT republishes.
Segment identity across rebuilds is a separate piece of work. This is the best
the source offers today and it beats a row number.

`tile_id` is the row number after the stable sort, assigned by the build rather
than by the database, because a database-assigned row number differs between two
loads of the same data.

---

## Tests

```
uv run pytest -q
```

No test reaches the network. The end-to-end test runs the whole pipeline over
`tests/fixtures/snapshot/`, a committed extract of 34 real blocks; see
`tests/fixtures/README.md` for what is in it and how the golden file is meant to
be treated.

---

## How it compares with what is deployed

`docs/parity-with-the-deployed-database.md`. The short version: every column
that should match does, and `lts_level` does not — because the deployed database
was built by an earlier version of the stress rules than the notebook now
contains. That needs a decision from a person before this output is deployed.

---

## What this does not do

It writes files. It does not load a database, generate SQL, or know anything
about how a street is drawn. It also does not yet describe its own columns for
someone who has never seen this repository — the files carry names and types,
not meanings.
