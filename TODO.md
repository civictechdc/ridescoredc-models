# Completion plan

**Branch:** `feature/local-model-to-staging`, off the prototype lineage.
**Goal:** one repo where a model is built locally, checked, and synced to a
database by a human running one command — with the 1-2-3 contributor path intact.

Written 2026-08-11. Supersedes the earlier `TODO.md`, preserved at
`docs-for-ai/preserved/TODO.md`.

---

## Where we are

This branch carries the prototype's tree. **What already works, and should not be
rebuilt:**

| | |
|---|---|
| `fetch` / `build` / `run` | dated snapshots with per-file sha256; build reads no network |
| `inspect --against` | diff two runs — the review artifact a release needs |
| `describe` | every dataset checked against its `descriptions/*.yaml` |
| `load` | parquet → PostGIS, one transaction, plus a `ridescore_load` record table |
| `manifest` | `presentation.yaml` + descriptions → `manifest.json`, frontend decoupled |
| `build-bna` | the BNA export wrapped as a dataset |
| `tests/` | 7 modules with a real committed 2026-08-05 snapshot |
| `run_record.py` | `run.json` with git SHA, lockfile hash, derived constants |

**What is on `feature/kestra-setup` and not here** — the reason a second model
cannot yet be deployed on its own:

- `models/base.py` + `resolve()` — the `Model(name, produces, requires)` registry
- `sources/` and `network/` registries — fetch only what a model declares
- `paths.py` — `runs/<model>/{data,outputs}/<date>/`
- generic `cli.py` — `--model` driven, nothing hardcoded
- `models/lts/` — LTS as its own model
- `notebooks/` per-model folders + `model-template.ipynb`; the three guides

Both branches descend from `7a2682a`, so this is a **normal merge** — no
`--allow-unrelated-histories`.

Removed in this pass: `bna/` and `lts/` (empty `.gitkeep` placeholders from the
skeleton).

---

## Decide before Phase 0

1. **Package path.** `src/ridescore/` (here) or `tools/ridescore-cli/src/ridescore/`
   (kestra-setup). **Recommend `src/`**: there is one package, and a uv workspace
   for a single member is overhead. This reverses an earlier call, so it needs
   saying out loud rather than settling by whichever branch merges second.
2. **`live/` or `schema/`.** Same files; `schema/` carries a fix to
   `0001_baseline.py` that `live/` does not. Take `schema/`, then retire it in
   Phase 5.
3. **Kestra.** Not on this branch. Given `db_sync` is human-run, **leave it on
   `feature/kestra-setup` and do not merge it.** Revisit only if the sync ever
   needs to be scheduled.
4. **README.** Take the 1-2-3 version from `docs-for-ai/preserved/README.md`.

---

## Phase 0 — reconcile the branches

- [ ] `git merge feature/kestra-setup` on a throwaway branch first, to see what
      rename detection does with `src/` → `tools/ridescore-cli/src/`
- [ ] Land the four decisions above; delete the losing copy rather than leaving
      two importable packages
- [ ] One `pyproject.toml`, with the prototype's deps (`psycopg`, `pyyaml`)
- [ ] Regenerate `uv.lock`
- [ ] CI: keep both test suites; drop the `flows` job with Kestra

---

## Phase 1 — LTS: agree the rule, then prove the CLI implements it

**This is the honesty check on the whole premise.** The repo claims one
implementation with three runners over it. For LTS that claim is currently false —
three artifacts describe the stress rules and no two agree:

| | no facility → LTS 3 | marked lane → LTS 3 | no-facility local → LTS 2 |
|---|---|---|---|
| README table | — | — | ≤ 25 mph |
| notebook, and the CLI today | ≤30 mph, ≤2 lanes, **Local** | ≤30 mph, ≤**3** lanes | ≤ 20 mph |
| the deployed database | ≤30 mph, ≤2 lanes — **no road-type test** | ≤30 mph, ≤**2** lanes | agrees with the notebook |

2,420 segments differ between the CLI and the live map, and **the version that
produced the deployed scores exists nowhere in version control.**

LTS is the right model to settle first, and not because it is the simplest:

- **Time-invariant.** No crash window, no percentile, no cohort. A diff means a
  rule changed and nothing else. Every other model's numbers move on their own,
  so no other model can serve as a control.
- **Has a committed baseline on both sides.** `tests/fixtures/snapshot/2026-08-05/`
  to build from, and `schema/sql/0001_baseline.sql` with 13,829 deployed segments
  to compare against. The comparison needs no credentials and no network.
- **Boundary-shaped.** Facility × lanes × speed × function is a table, so it can be
  tested exhaustively rather than sampled.
- **Needs no migration and no crash data.** Nothing else has to be right first.

Steps:

- [ ] **Answer the three questions.** Group decision, longest lead time, start now:
  1. Quiet collector, no bike lane — LTS 3 as the map shows, or 4 as the notebook
     says? **2,194 segments**
  2. Painted lane on three lanes — 3 as the notebook says, or 4 as the map shows?
     **135 segments**
  3. No-facility local street — ≤20 mph as the code says, or ≤25 as the README
     says? Invisible in the comparison because the deployed data agrees with the
     notebook here, but it reclassifies every 21–25 mph local street once answered.
- [ ] **Make LTS a model, not a component** — split out of
      `models/ridescore_v1/lts.py` so it can be built, scored and published alone
- [ ] **Exhaustive boundary tests** — every cell of the table, not a sample
- [ ] **Turn the parity comparison into a command.** It exists today as a one-off
      analysis in `docs/parity-with-the-deployed-database.md`. It should build from
      the committed snapshot and report per-column changed-segment counts against a
      baseline, repeatably.
- [ ] **Run it in CI**, so any PR touching a rule states its own blast radius —
      `lts_level: 2,420 segments changed` — in the review, before merge
- [ ] **Fix the README table** to match the code, and delete the "known
      discrepancy" note rather than carrying an admission that the docs lie

Until this passes, "one implementation, three runners" is a slogan. After it, a
scoring change is reviewable the way a frontend change is, and LTS becomes the
first thing worth syncing.

---

## Phase 2 — segment identity, and one dataset per model

The two things that must be right before anything is ever synced.

**Identity.** `ogc_fid` is an `ogr2ogr` row number doing two incompatible jobs.
Split them:

- [ ] `tile_id` — dense integer, assigned at build after a stable sort, for MVT
      feature-state only. Free to change every load.
- [ ] `segment_id` — stable and source-derived (DDOT BLOCKKEY today, OSM later).
      Anything that must survive a rebuild references this.
- [ ] Keep the duplicate-`segment_id` `BuildError` already in `_sort_and_key`

There are **no survey submissions in production yet**, so this is free now and
stops being free the day the survey ships.

**One score dataset per model.** Today `lts_level` ships inside
`ridescore_v1_scores.parquet`, so LTS cannot be published without the
cohort-relative `ridescore_v1` beside it.

- [ ] `road_segment` — geometry and attributes, once
- [ ] `lts_scores` — `segment_id`, `lts_level`, joined on
- [ ] `ridescore_v1_scores` — the blend and its components
- [ ] A description per dataset; `describe` covers each independently
- [ ] Port the `Model` registry so `build --model lts` resolves to roads only and
      never downloads crash data

Deployment granularity should match model granularity. This is the phase that
makes that true.

---

## Phase 3 — BNA as a registered model

- [ ] Register BNA in the model registry; `build --model bna` replaces `build-bna`
- [ ] Give wrapped models a **vintage**: which export, produced when. `road_segment`
      is pinned by date and sha256; BNA currently records nothing, and a map showing
      both compares dated data against undated data
- [ ] Its own description and score dataset, as in Phase 2

Two models, independently buildable and deployable, is the test that the generic
structure actually works. LTS proves the CLI is *correct*; BNA proves it is
*generic*. Both are needed before the first sync means anything.

---

## Phase 4 — Proposal 0007: the push-based `db_sync` command

**The first deliverable is the proposal, not the code.** The repo has a numbered
proposal series on the wiki (0001 pipeline and data package, 0002 descriptions,
0005 database organization, 0006 deployment — mirrored in
`docs-for-ai/references/ridescoredc-models.wiki/`). A push-based syncer overlaps
0006 directly and has to be read against it, so it belongs in the series.

- [ ] **Write Proposal 0007** — `ridescore db_sync <source> <destination>`: a
      human-run push for moving database values between environments. Source
      material: `docs-for-ai/proposal-db-syncr.md` and the 2026-08-11 meeting.

### It has to answer 0006 head-on

0006 §4.2 states **"Nothing pushes into a server,"** and its alternatives table
says the credential gap under push *"does not close at all."* 0007 is a push
design, so silence on this is not an option. Two honest positions:

| | The claim | What it costs |
|---|---|---|
| **Confine it** *(recommended)* | `db_sync` is the developer loop — `local → local`, `local → dev`. 0006 §4.5 already permits this: contributors build, and dev pulls any current package. Production promotion stays a registry retag. | production is unreachable by `db_sync` until the registry exists |
| **Contest it** | push suits this project's size — no registry to operate, no signing, no server timers, one maintainer with a terminal | keeps a credential pointing into production, which is precisely 0006's objection |

Confining it is buildable now, contradicts nothing in 0006, and leaves its end
state intact.

### Two mechanisms, one property

Both designs solve deploy ordering — code lands before data — by different means:

- **0007, via `/api/check/livemodels`** — the destination declares what it needs,
  at sync time. Requires a live website to answer.
- **0006, via the bundle contract** — the package pins the shape and description
  revision it applies to, and a server refuses a mismatch. Checkable in CI,
  offline, before deploy.

0006's is the stronger mechanism. 0007 should adopt it wherever it can, and keep
the endpoint only for what a build-time contract cannot know — chiefly which
environment the destination believes it is.

### Then the implementation

- [ ] **Environments config** — `local` / `staging` / `production` → API base URL;
      credentials from `PG*` env vars, never an argument
- [ ] **`/api/check/livemodels`** in the website repo: the destination declares what
      it needs — relation, kind, columns, params, `promote_id`, and its own
      `environment`. *Cross-repo; needs the website team's agreement before anything
      here can call it.*
- [ ] **Coverage lint at the source, before the sync executes** — every required
      model built, every required column present, `describe` clean. Half of this is
      `describe` already.
- [ ] **Diff against what the destination is serving**, from `ridescore_load`. This
      is what the human approves.
- [ ] **Direction guard** — refuse when the destination self-reports `production`
      and the source is a laptop, before a human is even asked
- [ ] **Postgres schema split**: `models.*` (syncer writes, may drop and recreate),
      `submissions.*` (**no access**), `tiger.*` ignored. Enforce with a grant, not
      a convention

The ordering property this buys: the destination cannot ask for a model until its
code is deployed, so **code lands before data, by construction.**

---

## Phase 5 — restore the 1-2-3 contributor path

Design intent is preserved in `docs-for-ai/preserved/the-three-levels.md`; the
files themselves in `docs-for-ai/preserved/`.

| | Restore | Now different |
|---|---|---|
| **1** Model in a notebook | `notebooks/` per-model folders, `model-template.ipynb`, `getting-started-as-a-modeler.md` | template section 1 can point at real `build` output; `tests/fixtures/snapshot/` can seed `BaseData/` so level 1 is clone-and-go |
| **2** Show it on a map | `demonstrating-your-model.md` | **has a real load step now** — `load` + `manifest`, and adding a layer is a YAML edit rather than an `index.html` edit |
| **3** Ongoing pipeline | `ongoing-data-pipeline.md` | rewritten around `db_sync`, not Kestra |

- [ ] Keep the rule the layout serves: **one implementation, three runners**
      (notebook, laptop, sync). A model that lives only in a notebook drifts from
      what the map serves.
- [ ] Confirm the Slack channel name — `#ridescore-dc` was assumed throughout, never
      verified.

---

## Phase 6 — retire `live/` and yoyo

Sort by nature, not by tool:

- **`models.*`** — fully derived, nothing irreplaceable. The loader owns the table
  shape, so **a new model column never needs a migration.**
- **`submissions.*`** — stateful and irreplaceable. Ordered, reviewed DDL. The only
  place migrations earn their keep.
- **Tile functions** (`update_score*`) — stateless. `CREATE OR REPLACE` is
  idempotent, so they belong in files reapplied on every deploy, diffed in a PR,
  like frontend code. `schema/functions/` exists and is empty.

- [ ] Re-scope the `append-only` CI job to `submissions` migrations only — function
      files are meant to be edited in place
- [ ] Reconcile `wip-update_score_v2.sql`. It is applied by nothing, and
      `update_score_v2` is **not formally in production**, so `schema/` is ahead of
      the deployed database rather than behind it
- [ ] Decide which schema the tile functions live in — moving `ridescoredc` to
      `models.road_segment` likely touches Martin's config and the frontend's
      `/tiles/<name>/` URL

---

## Group decisions, not work

These block deployment regardless of how good the tooling gets.

1. **Which LTS rule is correct** — the three questions in **Phase 1**. Longest lead
   time of anything here, gates the first sync, and needs people rather than code.
   Start it before Phase 0.
2. **`ridescore_v1` is not comparable between runs.** `s_crash` is normalised
   against each run's own 95th percentile — its own description says so. A segment's
   score moves when *other* segments change, so a user comparing today's score to
   last month's sees a change that means nothing. Freezing the percentile per
   released model version is the fix, and it is a decision about what the published
   number means, not a bug to patch.
3. **OSM segmentation.** Full replacement, or conflation with DDOT attributes.
   Touches `sources/roads`, every field name in normalisation, and `segment_id`.
   Note it does not touch any model: `lts_level(facility, speed, lanes, function)`
   has never seen a source field name.

---

## Context preserved outside git

`docs-for-ai/` is gitignored, so it survives branch switches:

- `preserved/README.md`, `preserved/TODO.md`, `preserved/notebooks/` — the
  pre-merge state
- `preserved/the-three-levels.md` — why the 1-2-3 structure exists
- `proposal-db-syncr.md` — the syncer design, with meeting quotes marked. Becomes
  **Proposal 0007** (Phase 4)
- `merging-the-prototype-branch.md` — full file inventory of both branches
  *(its "unrelated histories" claim is wrong; they share `7a2682a`)*
- `references/ridescoredc-models.wiki/` — the numbered proposal series

## The proposal series

| | Status | Subject | Bearing on this plan |
|---|---|---|---|
| 0001 | Draft | pipeline, stages, the **data package** | versioned `shape.values` packages — the piece missing from this plan entirely, and what makes rollback and promotion mean anything |
| 0002 | Draft | dataset descriptions | already implemented on this branch; adds `describe --validate` and declared ranges |
| 0003 | Not started | presentation and manifest | `presentation.yaml` exists here without a proposal behind it |
| 0004 | Not started | user-adjustable parameters | the `update_score` weights the frontend re-weights |
| 0005 | Draft | database organization | **supersedes Phase 6** — three schemas (`data`/`app`/`serving`), and migrations move to `ridescoredc-website` |
| 0006 | Unfinished | deploying packages, pull-based | **Phase 4 must answer it** |
| 0007 | To write | push-based `db_sync` | Phase 4 |

Two defects spotted while reading, worth raising with the author:

- **0005 §4.2** opens *"Both the `data` and `serving` … do need migrations"*, which
  contradicts its own heading and the rest of the section. Reads like a dropped
  "not", and it inverts the meaning.
- **0001 §6** gates the visible map change on *"§8's stress-rule questions"*, but
  §8 holds only the Data Package standard question. Those questions are written
  down nowhere — which is what **Phase 1** exists to fix.
