"""
0001_baseline -- load the authoritative database snapshot.

schema/0001_baseline.sql is a full plain-format pg_dump of the source database:
PostGIS extensions, the tiger/topology framework schemas, and the model tables
public.crashes_dc and public.ridescoredc *with their data* + update_score().

A pg_dump is written for psql, so it isn't fully driver-runnable as-is: it has
psql backslash commands (``\restrict``) and ``COPY ... FROM stdin`` data blocks.
Rather than shell out to psql (which would need its own connection + DATABASE_URL),
this migration replays the dump over the connection **yoyo hands us**:

  * plain SQL runs through the cursor (psycopg 3 runs a multi-statement script in
    one execute() when there are no parameters -- the simple query protocol), and
  * each ``COPY ... FROM stdin`` block is streamed via psycopg 3's
    ``cursor.copy()`` -- the dump's COPY payload is already in exactly the text
    format copy() expects.

No psql, no second connection, no DATABASE_URL.
"""

import os
import sys

LIVE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIVE_DIR)

from yoyo import step  # noqa: E402

DUMP_SQL = os.path.join(LIVE_DIR, "schema", "0001_baseline.sql")


def _skip(line):
    """Lines from the dump that are not safe/valid to run over yoyo's session."""
    s = line.lstrip()
    return (
        # psql meta-commands (\restrict / \unrestrict) -- not SQL.
        s.startswith("\\")
        # Would reset THIS session's search_path to '' and break yoyo's own
        # bookkeeping after the step. Every object in the dump is schema-
        # qualified, so dropping this one statement is safe.
        or s.startswith("SELECT pg_catalog.set_config('search_path'")
        # transaction_timeout is a PostgreSQL 17+ setting; skip it so a dump taken
        # from PG 17 still loads on an older server that doesn't recognize it.
        # It's restore boilerplate -- no effect on the schema or data.
        or s.startswith("SET transaction_timeout")
    )


def apply_step(conn):
    cur = conn.cursor()
    sql_buf = []

    def run_buffered():
        script = "".join(sql_buf)
        sql_buf.clear()
        if script.strip():
            cur.execute(script)

    with open(DUMP_SQL, encoding="utf-8") as fh:
        lines = iter(fh)
        for line in lines:
            if _skip(line):
                continue
            head = line.strip()
            upper = head.upper()
            if upper.startswith("COPY ") and "FROM STDIN" in upper:
                run_buffered()  # flush DDL so the table exists before we load it
                copy_sql = head[:-1] if head.endswith(";") else head
                with cur.copy(copy_sql) as cp:
                    for data in lines:  # consume the raw COPY payload until "\."
                        if data.rstrip("\n") == "\\.":
                            break
                        cp.write(data)
                continue
            sql_buf.append(line)
    run_buffered()  # trailing DDL (indexes, constraints, setval, ...)
    cur.close()


def rollback_step(conn):
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS public.ridescoredc, public.crashes_dc CASCADE")
    cur.close()


steps = [step(apply_step, rollback_step)]
