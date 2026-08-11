# schema/ — the database contract

This folder is the **source of truth for the database schema and the tile
functions that reach the shared databases.** Model developers experiment in
[`../notebooks/`](../notebooks/); when a change is ready to ship, it lands here
as a migration and is applied to staging first, then prod.

## Who owns what

The boundary that matters, because crossing it is how user data gets destroyed:

| | Owns | Meaning |
|---|---|---|
| **`schema/`** (here) | **DDL** | tables, columns, indexes, the `update_score` tile function |
| [`../kestra/`](../kestra/) | **DML** | the *rows* of `ridescoredc` and `crashes_dc` |

The pipeline replaces rows. It never creates, alters or drops a table.

The **survey tables** are neither: they hold runtime user data written by
`ridescoredc-website`. Their schema is **not** yet managed by a migration — the
DDL lives here only as the work-in-progress `sql/wip-patch.sql` (moved out of
the website's old boot-time patch), pending being folded into a real migration.
Nothing applies it automatically yet, and nothing in the pipeline may truncate
them.

> **Direction of travel.** yoyo is expected to retire as the Kestra pipeline
> takes over. What must survive that transition is not the tool but the
> properties it provides: an ordered, reviewed, exactly-once record of schema
> changes, and a CI gate that applies them to a throwaway database before they
> reach a real one. Do not delete this folder until those live somewhere else —
> the survey tables and `update_score` would be left with no owner at all.

## Layout

```
schema/
  migrations/            # ordered, ledgered migrations (yoyo-migrations)
    0001_baseline.py       # replays sql/0001_baseline.sql over yoyo's conn
    post-apply.py          # re-applies functions/*.sql after every run
  sql/                   # SQL read by migrations (kept out of migrations/ so
    0001_baseline.sql      #   yoyo doesn't treat it as its own migration).
                           #   0001 is a FULL pg_dump = the authoritative baseline.
    wip-patch.sql          # WIP survey-table DDL (was website api/patch.sql);
                           #   not applied by yoyo yet.
    wip-update_score_v2.sql # WIP Martin tile function (was functions/); not
                           #   applied yet. Live tile fn is update_score (v1),
                           #   which ships inside the 0001 pg_dump.
  functions/             # repeatable objects re-applied by post-apply.py on
                           #   every run (CREATE OR REPLACE); currently empty.
  yoyo.ini.example       # template → copy to yoyo.ini (gitignored) on first setup
  requirements.txt
```

## Writing a migration

Migrations are ordered yoyo files in `migrations/` — a Python `.py` (like the
`0001` baseline) or a plain `.sql`. yoyo records each applied version in
`_yoyo_migration` and runs it exactly once per database.

- **Schema changes** (add a column/index, create a table) are a plain `.sql`
  migration. For renames, follow **expand → migrate → contract** (e.g. add
  `seg_id`, backfill, switch readers, drop `ogc_fid` later) so old and new code
  never break mid-deploy.
- **Repeatable objects** (tile functions) don't get a numbered migration — edit
  the `CREATE OR REPLACE ...` in `functions/*.sql` and `post-apply.py` re-applies
  them after every run.

Open a PR into `develop`; CI applies it to **staging** (verify at
dev.ridescoredc.com), then `develop → main` applies it to **prod**.

## Applying

The database URL is supplied at apply time — never committed.

**First-time setup:** `yoyo.ini` is gitignored (so local/manual tweaks never get
committed), so copy the template once before running anything:

```bash
cp yoyo.ini.example yoyo.ini   # one-time; then edit locally if needed
```

Then:

```bash
pip install -r requirements.txt

# yoyo talks to Postgres through psycopg 3, which it picks from the URL *scheme*.
# DATABASE_URL stays plain (postgresql://) for psql — used by the 0001 baseline —
# and Martin; yoyo gets the same URL rewritten to the postgresql+psycopg:// scheme:
YOYO_DB="postgresql+psycopg://${DATABASE_URL#postgres*://}"

yoyo list     --database "$YOYO_DB"   # what would run
yoyo apply    --database "$YOYO_DB"   # apply pending (ledger: _yoyo_migration)
yoyo rollback --database "$YOYO_DB"   # undo the last migration
```

**Staging → prod** runs from CI on the existing Gitflow: merge to `develop`
applies to the staging DB, merge to `main` applies to prod. Staging is the
canary — never promote to `main` until staging has applied cleanly and the data
looks right. yoyo takes a lock and records applied versions, so each migration
runs exactly once per database and concurrent applies are safe.

## Notes

- `yoyo` / `psycopg` import warnings in an editor just mean the deps aren't in
  that interpreter; they resolve after `pip install -r requirements.txt`. yoyo
  uses **psycopg 3** (`psycopg[binary]`), selected via the `postgresql+psycopg://`
  URL scheme — there is no longer a psycopg2 dependency.
- The `0001` baseline is a full pg_dump (`schema/0001_baseline.sql`, ~4 MB),
  committed as plain text — fine for git at this size. Regenerate it with
  `pg_dump` if the source database changes.
