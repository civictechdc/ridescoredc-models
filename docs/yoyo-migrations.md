# Database migrations (yoyo)

The `ridescoredc-models` repo versions the shared PostGIS database — schema, the
model tables' baseline data, and tile functions — with
[yoyo-migrations](https://ollycope.com/software/yoyo/latest/). This page is a
quick reference for running migrations against a database you control (such as
your local dev database).

## Where migrations live

```
ridescoredc-models/live/
  migrations/          # ordered, ledgered migrations yoyo runs
    0001_baseline.py     # loads schema/0001_baseline.sql (the baseline pg_dump)
    post-apply.py        # re-applies functions/*.sql after every run (repeatable)
  schema/              # SQL the migrations read (e.g. the baseline dump)
  functions/           # CREATE OR REPLACE tile functions (repeatable objects)
  requirements.txt
```

yoyo records which migrations have run in a `_yoyo_migration` table in the target
database and takes a lock, so each migration runs exactly once per database and
re-running is safe.

## Running it

```bash
cd ridescoredc-models/live
pip install -r requirements.txt

# yoyo selects its Postgres driver from the URL *scheme*: it uses psycopg 3 via
# the postgresql+psycopg:// scheme. (Other tools — psql, and the Martin tile
# server — use the plain postgresql:// form of the same connection string.)
YOYO_DB="postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME"

yoyo list     --database "$YOYO_DB"   # preview: what would apply
yoyo apply    --database "$YOYO_DB"   # apply all pending migrations ("up")
yoyo rollback --database "$YOYO_DB"   # undo the last migration ("down")
```

Add `--batch` to any command to skip the interactive prompt (useful in scripts).

## The one rule: migrations are append-only

Once a migration has been committed and applied, **never edit or delete it — add
a new one.** yoyo has already recorded older migrations as applied, so edits to
them won't re-run and your change silently never reaches deployed databases. To
change something, add `0002_*`, `0003_*`, and so on.

The exception is the **repeatable** lane: `functions/*.sql`, re-applied on every
run by `post-apply.py` with `CREATE OR REPLACE`. Those are meant to be edited in
place.

## Deploying

Applying migrations to the shared staging/production databases is done by the
maintainers as a separate, manual step for now. This page covers running yoyo
against a database you own.
