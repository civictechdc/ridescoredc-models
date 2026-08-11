# TODO / RESUME

Working state of the RideScore DC models repo. Written to be picked up cold —
by a person or an agent — without reading back through any conversation.

**Last verified:** 2026-08-10. Everything under "Verified working" below was
actually executed, not assumed.

---

## 0. Resume in five minutes

### Option A — uv (the documented path)

```bash
git clone https://github.com/civictechdc/ridescoredc-models
cd ridescoredc-models
uv sync                       # one .venv at the repo root, whole workspace
uv run ridescore models
```

> ⚠️ **`uv.lock` is stale and must be regenerated before this works.** It was
> built when the repo root *was* the package; the root is now a uv *workspace*
> root with `tools/ridescore-cli` as a member. Run `uv lock` at the root and
> commit the result. CI currently omits `--frozen` with a note to restore it,
> and the Kestra flows use `uv run --frozen`, so they stay broken until this
> is done. **This is the single highest-priority chore in the repo.**

### Option B — plain venv + pip (no uv needed)

Verified working on Python 3.11.2 with geopandas 1.1.4 / shapely 2.1.2:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e tools/ridescore-cli   # add --ignore-requires-python on 3.11
pip install pytest                   # only if running tests
ridescore models
```

`pyproject.toml` declares `requires-python = ">=3.12"`. The code runs fine on
3.11 today; the floor exists so nothing accidentally depends on 3.11-only
behaviour. Use `--ignore-requires-python` if 3.11 is what you have.

**No conda, no system GDAL.** geopandas 1.x pulls pyogrio, which ships wheels
with GDAL bundled for Windows, macOS and Linux. This is worth stating loudly in
the beginner docs — it is the single biggest historical blocker for new
contributors.

---

## 1. Verified working

These exact commands were run and produced the output described.

```bash
ridescore models
#   lts            produces lts_level        chain: lts               sources: roads
#   ridescore_v1   produces ridescore_v1     chain: lts -> ridescore_v1
#                                            sources: roads, crashes, boundary

ridescore fetch --model lts --run-date 2026-08-10
#   roads   44.0 MB   runs/lts/data/2026-08-10/roads.geojson       (~4 s)

ridescore build --model lts --run-date 2026-08-10 --area "-77.03,38.93,-77.01,38.95"
#   499 segments  ->  runs/lts/outputs/2026-08-10/lts.geojson       (~7 s)
#                     runs/lts/outputs/2026-08-10/run.json
```

Spot check of the output — these are correct:

| route_name | facility | speed | lanes | lts_level |
|---|---|---|---|---|
| GEORGIA AVE NW | none | 30 | 4 | **4** |
| 3RD ST NW | none | 20 | 2 | **2** |

`pytest` — **23 passed** (`cd tools/ridescore-cli && pytest -q`).

**The generic framework demonstrably works:** `lts` downloads *roads only*. It
does not fetch crash records, because LTS scores physical characteristics and
declares no crash column. `ridescore_v1` declares `crash_count_5yr`, so the
planner pulls in the `crash_counts` layer and its two extra sources. Nothing in
the CLI names a model.

---

## 2. Workstream 1 — finish making `ridescore-cli` generic

**Status: mostly done.** The architecture is proven; the gaps are coverage.

### Done

- `Model` declaration (`models/base.py`) — name, `produces`, `requires`, `score`
- Registry + dependency resolution (`models/__init__.py::resolve`) with cycle detection
- `Source` registry (`sources/`) — fetch only what is asked for
- `Layer` registry (`network/`) — base segments + optional enrichments
- `pipeline.plan()` — walks requires → layers → sources before anything downloads
- `paths.py` — `<root>/<model>/{data,outputs}/<run-date>/`, plus `--data-root`
  to share fetched sources (this is the hook Kestra uses for its Tier 2 mount)
- Generic `cli.py` — `models / fetch / build / run / inspect / load`
- `lts` fully working end to end

### Remaining

- [ ] **Tests for everything added.** The 23 passing tests are all `lts_level`
      boundary tests. There is **zero** coverage of `paths`, `sources`,
      `network.plan`, `network.attributes`, `pipeline.plan`, or
      `models.resolve`. `network.plan` and `models.resolve` are pure and cheap
      to test — do those first.
- [ ] **Port the `ridescore_v1` blend** (notebook cell 24). Currently
      `models/ridescore_v1/__init__.py::_score` raises `NotImplementedError`.
      This is what makes the dependency chain `lts -> ridescore_v1` do
      something real.
- [ ] **Port the factor columns** (`factors.py` has the tables; nothing applies
      them). These feed `update_score` and are needed before any load.
- [ ] **`--area` only accepts a bbox.** Named neighbourhoods raise a clear
      error. Wire up a published neighbourhood boundary dataset, or leave it
      and document bbox-only.
- [ ] **`inspect --against`** — compare two runs. The whole point of dated
      snapshots, and currently just prints `run.json`.
- [ ] **Segment identity.** Nothing produces a stable key. See §3, it blocks
      the load step.

---

## 3. Workstream 2 — Kestra runs the same thing, then loads the warehouse

### The shape

Kestra adds exactly one thing to what a laptop already does:

```
LAPTOP                                    KESTRA
  ridescore fetch  --model lts              same command, --data-root /data/raw
  ridescore build  --model lts              same command
  ─────────────────────────────────         ridescore load --model lts   ← the extra step
  stops at .geojson                         .geojson -> rows in Postgres
```

Flows are already scaffolded in `kestra/flows/ridescore/` and validated by CI,
but they call the pre-generic CLI signature.

### Remaining

- [ ] **Update the flows for the generic CLI.** They currently pass
      `--cache` / `--out`; the CLI now takes `--model`, `--root`, `--data-root`.
      Files: `01_fetch_sources.yml`, `02_build_scores.yml`,
      `03_load_database.yml`, `10_refresh_all.yml`.
- [ ] **Implement `ridescore load`.** Currently a stub that validates the
      GeoJSON exists and exits. Needs: read GeoJSON → connect via `PG*` env
      vars → `TRUNCATE` + insert within one transaction → report row deltas.
      `--dry-run` defaults to **true** and must stay that way.
- [ ] **Solve segment identity first — this blocks load.**
      - The live `ridescoredc` table keys on `ogc_fid`, and the tile function
        passes it to the frontend as `promoteId`
        (`schema/sql/wip-update_score_v2.sql:10`).
      - **The survey tables key user submissions to segments.** If identity
        churns between runs, real user data is orphaned.
      - Our pipeline produces `route_id` (DDOT ROUTEID), not `ogc_fid`.
      - **This gets worse with the OSM pivot** (§5): OSM way IDs change
        whenever a mapper splits or merges a way.
      - Decide a stable key scheme before the first load, not after.

### Does the load need a database migration?

**It depends on the model, and the rule is simple: a migration is needed when a
model produces a column the table does not already have.**

| Model | Produces | Column exists in `ridescoredc`? | Migration? |
|---|---|---|---|
| `lts` | `lts_level` | ✅ yes (ships in the 0001 baseline) | **No** |
| `ridescore_v1` | `ridescore_v1` | ✅ yes | **No** |
| factor columns | `speedlimit_score`, `num_lanes_score`, … | ✅ yes | **No** |
| a new model (e.g. `bikeability`) | `bikeability_score` | ❌ no | **Yes** |

So the first load of `lts` needs **no migration** — which makes it a good first
target. Adding a model later means:

1. A migration in `schema/migrations/` adding the column (nullable, so the
   deploy and the first load can be ordered independently).
2. A change to `update_score` in `schema/` if the frontend should re-weight it.
3. Then the load flow writes it.

Ownership stays: **`schema/` owns DDL, `kestra/` owns DML.** The load flow
replaces rows; it creates and alters nothing, and must never touch the survey
tables.

- [ ] **Confirm the live `ridescoredc` column list** against what the pipeline
      produces. Do this by querying the baseline, not by reading the README —
      `psql -c "\d ridescoredc"` after a `smoke-apply`.
- [ ] **Decide the load strategy.** `TRUNCATE` + insert is simplest but takes
      the table out for the duration and breaks any FK from the survey tables.
      Alternatives: load to a staging table then swap, or upsert on the stable
      key. This interacts with segment identity above.

---

## 4. Workstream 3 — beginner docs for the three levels

The three levels are defined in `README.md` and each has a guide. All three
exist; the "getting started" halves need work.

| Level | Guide | State |
|---|---|---|
| 1 — model in a notebook | `docs/getting-started-as-a-modeler.md` | good, needs setup fixes |
| 2 — show it on a map | `docs/demonstrating-your-model.md` | good, blocked on level 1 outputs |
| 3 — ongoing pipeline | `docs/ongoing-data-pipeline.md` | good, needs the new CLI commands |

### Remaining

- [ ] **Setup section must cover both uv AND plain venv/pip.** Right now it
      only shows `uv sync`. Many beginners will not have uv, and some
      institutional machines will not let them install it. Add the venv path
      from §0 Option B, and state explicitly that no conda and no system GDAL
      are required — that is the historical blocker.
- [ ] **Add a real worked example to the level 1 guide** using the commands
      verified in §1. A beginner should be able to copy three commands and see
      499 scored segments in seconds. That is a far better first experience
      than reading about a template.
- [ ] **`notebooks/model-template.ipynb` section 1 is still a TODO stub.** It
      references `../BaseData/segments.parquet`, which does not exist. Point it
      at the real `ridescore build` output now that one exists.
- [ ] **Decide the BaseData question** (§5) — it determines whether level 1 is
      truly clone-and-go or requires a download.
- [ ] **Update level 3 for the generic CLI** — the commands changed.
- [ ] **Level 2 needs the load step or a manual recipe** for getting GeoJSON
      into the local Postgres so the map renders it.
- [ ] **Confirm the Slack channel name.** Docs say `#ridescore-dc` throughout;
      this was assumed, not verified.

---

## 5. Open decisions

### OSM segmentation pivot — biggest open question

All models are pivoting to OSM-modelled segmentation. Current state:

- The pipeline builds segments from **DDOT roadway blocks**, not OSM.
- The archived notebook uses osmnx **once**, for `geocode_to_gdf` on the city
  boundary. `graph_from_*` is never called. There is no OSM anywhere.

**What the pivot does not touch:** any model. `lts_level(facility, speed,
lanes, function)` takes normalised values and has never seen a source field
name. This is the layering paying off.

**What it does touch:**

1. `sources/opendata_dc.py::fetch_roads` — replaced by an OSM source
2. `network/attributes.py` — every field name (`SPEEDLIMITS_OB`,
   `TOTALTRAVELLANES`, `DCFUNCTIONALCLASS`, `BIKELANE_*`) is DDOT
3. `config.py` "network: sources" and "attribute normalisation" sections
4. **Segment identity** (§3) — OSM IDs are not stable
5. **`pavement_condition` has no OSM equivalent.** DDOT's `PCI_CONDCATEGORY`
   is municipally measured; OSM `surface`/`smoothness` are different and
   sparse. But `pavement_condition_score` is one of seven columns
   `update_score` re-weights — dropping it is a frontend contract change.

- [ ] **DECIDE: full replacement, or conflation?** OSM gives routable topology
      (what BNA needs) plus trails and park paths DDOT's roadway-block layer
      lacks. DDOT has authoritative speed limits, lane counts and PCI that OSM
      in DC does not. Most serious bike-safety work conflates: OSM geometry and
      topology, municipal attributes joined on. This changes what `network/`
      is — a fetcher plus a spatial join, not a fetcher.

Note crashes and boundary are **unaffected** by the pivot, so `sources/` is
already two-thirds correct regardless of the answer.

### Others

- [ ] **`BaseData/` committed extract?** Whether `notebooks/BaseData/` ships a
      few hundred segments so level 1 needs no network. Now easier to decide:
      a 499-segment bbox build is small. `tools/ridescore-cli/tests/data/` is
      an empty placeholder waiting on this, and the `slow` pytest marker has
      nothing to run.
- [ ] **yoyo retirement.** `schema/` is expected to outlive yoyo but the
      properties must survive: ordered, reviewed, exactly-once schema changes
      plus a CI gate that applies them to a throwaway database first. `live/`
      was renamed to `schema/`; nothing has been deleted.
- [ ] **Survey table DDL has no owner.** `schema/sql/wip-patch.sql` is applied
      by nothing, yet `ridescoredc-website`'s README says this repo manages it.
      A documented cross-repo contract with no implementation.

---

## 6. Known defects, deliberately preserved

`config.py`, `factors.py` and the model configs carry `DEFECT:` markers. They
reproduce the original notebook's bugs **on purpose** — a port that also fixes
things cannot be verified against what it came from. Fix each as its own change
*after* the port diffs clean.

| Defect | Where | Effect |
|---|---|---|
| Speed test is `> 1`, not `> 0` | `config.SPEED_LIMIT_MIN_VALID` | a recorded 1 mph is discarded |
| Only outbound speed read | `config.SPEED_LIMIT_FIELD` | `SPEEDLIMITS_IB` ignored; they can differ |
| Buffer applied in Web Mercator | `config.CRASH_BUFFER_CRS` | ~7.8 m on the ground, not 10 |
| Missing lanes scores 10 | `factors.NUM_LANES_TO_SCORE_DEFAULT` | blank = as bad as 8 lanes, while LTS reads the same blank as 1 lane |
| Speed/width scores unbounded | `factors.SPEED_LIMIT_SCORE_SLOPE`, `ROAD_WIDTH_SCORE_INTERCEPT` | go negative; a *missing* width scores 100 |
| README says 25 mph, code says 20 | `models/lts/config.py` | no-facility local-street rule |

### Already fixed on the way through (not preserved)

- **Crash WHERE clause had missing spaces** — the notebook produced
  `... > 0OR MINORINJURIES_BICYCLIST > 0OR ...`, which is not valid SQL.
  Written correctly in `sources/opendata_dc.py::_crash_where`. **If crash
  totals move when this first runs, this is why.**
- **Fetch swallowed exceptions** and returned `None`, so failures surfaced
  later as unrelated `AttributeError`s. Now raises with retry.
- **Coordinate rounding assumed 3D** (`for x, y, z in ls.coords`) and raised on
  2D geometry. Now goes through `shapely.ops.transform`.
- **Boundary geocode replaced** with a published dataset — a live Nominatim
  lookup is uncacheable and irreproducible.

---

## 7. Repo map

```
notebooks/            LEVEL 1  model-template.ipynb + BaseData/ LTS/ RideScore/ BNA/ Bikeability/
tools/ridescore-cli/  the spine — the only implementation of any model
kestra/               LEVEL 3  flows; authoritative for the pipeline
schema/               DDL, migrations, the update_score tile function
docs/                 the three guides
TODO.md               this file
```

Level 2 has no folder by design — it uses the compose stack in
`ridescoredc-website`, and its guide points there rather than duplicating it.

---

## 8. Gotchas

- **`uv.lock` is stale** (§0). Fix first.
- **CI has 5 jobs**: `lint`, `test`, `flows`, `append-only`, `smoke-apply`. The
  `flows` job validates every Kestra YAML parses and that its namespace matches
  its folder — it has already caught one real bug.
- **Nothing is committed.** All work is staged on `develop`. Branch before
  committing: `git checkout -b feature/...`.
- **Tests never touch the network.** `tests/conftest.py` blocks
  `socket.socket.connect`; a test needing egress must be marked
  `@pytest.mark.network` and say why.
- **`runs/` is gitignored** along with `**/raw/`, `**/out/`, `**/scratch/`.
- **Kestra flows sync from `main` automatically.** A bad flow reaches the
  server on merge. The `flows` CI job is the only gate.
- **The Kestra host URL** (`https://pipeline-ridescore.mocomakers.com`) appears
  in exactly one place, `kestra/README.md`. It is expected to change; keep it
  out of flow YAML.
