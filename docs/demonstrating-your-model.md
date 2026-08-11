# Demonstrating your model on a map

**Level 2 of [three](../README.md#three-ways-to-work-here).** You have a model
that computes something in a notebook ([level 1](getting-started-as-a-modeler.md)),
and now you want to see it — and let other people see it — as an actual map of
DC.

Everything here runs on your own machine. Nothing you do at this level touches
staging or production. The goal is to demonstrate, end to end, **how your model
*would* work if the group adopted it.**

---

## What you are proving

Three things, in order:

1. The full stack runs on your machine — database, tile server, API, frontend.
2. Your model's scores can be loaded into that database.
3. The map can render *your* scores instead of the published ones.

Together those answer the question a reviewer will actually ask, which is not
"is the maths right?" but "what would this look like on the site?"

---

## 1. Run the stack locally

The containers are owned by the
**[ridescoredc-website](https://github.com/civictechdc/ridescoredc-website)**
repository. Follow its **Developer Spinup** guide there.

Follow that repo's guide rather than any copy of it — including this page. If
its compose file changes, its README changes with it, and a duplicated set of
steps here would quietly rot into wrong instructions.

You will end up with four services, reached through NGINX at
`http://localhost:8000`:

| Service | Role |
|---|---|
| `nginx` | the front door, routes `/tiles/` and `/api` |
| `fastapi` | the app and the frontend |
| `martin` | serves vector tiles from PostGIS |
| `db` | PostgreSQL + PostGIS, published on `localhost:5432` |

Confirm the map loads before going further. Debugging your model on top of a
stack that was never working is a bad afternoon.

> The website guide seeds the database from a production dump obtained from an
> org admin. You can instead build the road data yourself from public sources —
> see "Building the base data yourself" below.

---

## 2. Get your scores into the database

The map reads one table: `ridescoredc`. Each row is a road segment with a
geometry and a set of score columns.

Your model needs a column in that table. **Add your own column rather than
overwriting `ridescore_v1`** — keeping the published score alongside yours is
what makes a before-and-after comparison possible, and that comparison is the
most persuasive thing you can show a reviewer.

```sql
-- against your LOCAL database only
ALTER TABLE ridescoredc ADD COLUMN IF NOT EXISTS my_model_score numeric;
```

Then write your notebook's output into it, keyed by segment. From the models
repo, with the website stack running:

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/db
```

How you load is up to you — `GeoDataFrame.to_postgis`, a CSV and `COPY`,
whatever your notebook already produces. This is a demonstration, not the
production path; the production path is [level 3](ongoing-data-pipeline.md).

Sanity-check it before touching the frontend:

```sql
SELECT count(*), min(my_model_score), max(my_model_score) FROM ridescoredc;
```

A row count that does not match the published one means your join dropped
segments — find out which before you conclude anything from the map.

---

## 3. Make the map render it

Tiles are produced by a PostGIS function, not by the frontend. The live one is
`update_score`, and it ships in [`schema/`](../schema/). It takes tile
coordinates plus the user's factor weights, and returns the columns the map
draws.

So there are two edits:

**The tile function** — add your column to the `SELECT` inside the function so
it reaches the tile at all. Apply your modified version to your local database.
`schema/sql/wip-update_score_v2.sql` is a useful reference for what a revised
version of this function looks like.

**The frontend** — in the website repo, `api/static/index.html` is the map UI.
Point it at your column instead of `ridescore_v1`. Because `api/` is mounted
into the `fastapi` container, editing the file and refreshing the browser is
enough; no rebuild.

Tiles are cached aggressively. If the map looks unchanged, hard-refresh, and
check that `MARTIN_CACHE_SIZE=0` is set in the website's compose file.

---

## Building the base data yourself

Optional, and more interesting than restoring a dump: the road and crash data
are public, so you can build the base table from scratch instead of asking an
admin for `dev_backup.sql`.

```bash
uv run ridescore run --run-date 2026-08-10
```

> **Not yet available.** `fetch` and `build` are still being ported from the
> original notebook — see the status table in
> [tools/ridescore-cli/README.md](../tools/ridescore-cli/README.md). Until they
> land, use the production dump as the website guide describes.

---

## What to show the group

When you post in `#ridescore-dc`, the useful things are:

- **A screenshot of your map beside the published one.** Same area, same zoom.
- **The streets where you disagree**, and why you think you are right.
- **What broke or surprised you** while loading the data — that is usually
  where the next real problem is hiding.
- The database change you needed, so people can judge how invasive adoption
  would be.

---

## What you must not do

- **Do not point any of this at staging or production.** Level 2 is local. The
  path to a shared database is level 3, and it goes through group approval
  first.
- **Do not commit a modified `index.html` to the website repo** as part of a
  model proposal. Your frontend edit is a demonstration; if the model is
  adopted, the real change is made deliberately in that repo.
- **Do not commit database dumps or `pg_data/`.** Both are gitignored in the
  website repo for good reason — real data, machine-local.

---

## Next

If the group has traction on your model and wants it maintained rather than
demonstrated once, it needs to run on a schedule from version-controlled
definitions: [level 3 — ongoing data pipeline](ongoing-data-pipeline.md).
