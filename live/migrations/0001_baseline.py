"""
0001_baseline -- load the authoritative database snapshot.

schema/0001_baseline.sql is a full plain-format pg_dump of the source database:
PostGIS extensions, the tiger/topology framework schemas, and the model tables
public.crashes_dc and public.ridescoredc *with their data* + update_score().

A pg_dump is meant to be replayed by psql -- it contains psql meta-commands
(\restrict) and COPY ... FROM stdin data blocks that psycopg's execute() cannot
run. So this migration shells out to psql rather than reading the file itself.
DATABASE_URL is the same connection string yoyo was invoked with
(`yoyo apply --database "$DATABASE_URL"`); CI, the server deploy, and manual runs
all set it.
"""

import os
import subprocess
import sys

# Make live/ importable (kept for consistency with the other migrations).
LIVE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIVE_DIR)

from yoyo import step  # noqa: E402

DUMP_SQL = os.path.join(LIVE_DIR, "schema", "0001_baseline.sql")


def apply_step(conn):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL must be set to load the pg_dump baseline via psql -- "
            "the same URL passed to `yoyo apply --database`."
        )
    # psql speaks plain libpq URLs; strip any yoyo driver qualifier
    # (postgresql+psycopg://) that may be present in the environment.
    dsn = dsn.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgres+psycopg://", "postgres://"
    )
    # --single-transaction: all-or-nothing, so a failed load leaves nothing
    # partial behind and yoyo re-applies cleanly on the next run.
    subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "--single-transaction", "-f", DUMP_SQL],
        check=True,
    )


def rollback_step(conn):
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS public.ridescoredc, public.crashes_dc CASCADE")
    cur.close()


steps = [step(apply_step, rollback_step)]
