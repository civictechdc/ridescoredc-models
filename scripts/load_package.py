# /// script
# requires-python = ">=3.12"
# dependencies = ["pyarrow>=17", "psycopg[binary]>=3.2"]
# ///
"""Load a data package into PostGIS, then apply a deployment bundle.

Provisional. Proposal 0001 Phase 3 gives this to the CLI as `ridescore load`.
Delete this script when that command exists; do not maintain both.

Deliberately depends on pyarrow rather than geopandas: GeoParquet stores
geometry as WKB, so reading it needs no geometry library, and PostGIS parses the
WKB on the way in. That keeps this runnable by someone who wants a local
database without installing the whole pipeline.

    uv run scripts/load_package.py \\
        --package dist/ridescoredc-data-preview-0.1 \\
        --bundle  dist/ridescoredc-bundle-preview-0.1 \\
        --database "postgres://postgres:localdev@localhost:5432/db"

Proposal 0005 divides the database by who writes each part. This creates and
fills `data` (the loader owns it) and applies `serving` (the deployer owns it).
It never touches `app`, which holds user feedback and is the website's.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import psycopg
import pyarrow.parquet as pq

SQL_TYPES = {
    "int8": "smallint", "int16": "smallint", "int32": "integer", "int64": "bigint",
    "uint8": "smallint", "uint16": "integer", "uint32": "bigint", "uint64": "bigint",
    "float": "double precision", "double": "double precision", "halffloat": "real",
    "bool": "boolean", "string": "text", "large_string": "text",
    "binary": "bytea", "large_binary": "bytea", "date32[day]": "date",
}


def sql_type(field) -> str:
    name = str(field.type)
    if name in SQL_TYPES:
        return SQL_TYPES[name]
    if name.startswith("timestamp"):
        return "timestamptz"
    if name.startswith("decimal"):
        return "numeric"
    return "text"


def geometry_columns(schema) -> set[str]:
    """From the GeoParquet metadata, not from guessing at column names."""
    meta = (schema.metadata or {}).get(b"geo")
    if not meta:
        return set()
    return set(json.loads(meta).get("columns", {}))


def load_dataset(conn, dataset: str, path: Path) -> int:
    table = pq.read_table(path)
    geo = geometry_columns(table.schema)
    names = table.schema.names

    columns = ", ".join(f'"{n}" {sql_type(table.schema.field(n))}' for n in names)
    quoted = ", ".join(f'"{n}"' for n in names)

    with conn.cursor() as cur:
        # Scoring data is full-replace: one package is loaded at a time and
        # replaces what was there (Proposal 0001 A.8). CASCADE takes the serving
        # objects with it, which is why the bundle is applied afterwards.
        cur.execute(f'DROP TABLE IF EXISTS data."{dataset}" CASCADE')
        cur.execute(f'CREATE TABLE data."{dataset}" ({columns})')

        with cur.copy(f'COPY data."{dataset}" ({quoted}) FROM STDIN') as copy:
            for batch in table.to_batches(max_chunksize=5000):
                for row in batch.to_pylist():
                    copy.write_row([row[n] for n in names])

        # Geometry arrives as WKB in a bytea column; PostGIS parses it here, so
        # this script needs no geometry library of its own. The package carries
        # no SRID inside the WKB, so it is set from what the pipeline writes.
        #
        # ST_Force2D because the road network is LineStringZ -- an elevation the
        # source carried, through the notebook, into the pipeline. A tile is 2D
        # and nothing draws the Z. Dropping it here rather than in the pipeline
        # is deliberate: Proposal 0001 §6 lists changing the written geometry as
        # a breaking change, and it would move the committed golden fixtures.
        for column in geo:
            cur.execute(
                f'ALTER TABLE data."{dataset}" '
                f'ALTER COLUMN "{column}" TYPE geometry(Geometry, 4326) '
                f'USING ST_Force2D(ST_SetSRID(ST_GeomFromWKB("{column}"), 4326))'
            )
            cur.execute(f'CREATE INDEX ON data."{dataset}" USING gist ("{column}")')

    return table.num_rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--database", required=True)
    args = p.parse_args()

    package = json.loads((args.package / "datapackage.json").read_text())
    bundle = json.loads((args.bundle / "bundle.json").read_text())

    # Proposal 0006 §4.1: a bundle declares which packages it applies to, and
    # apply refuses a pair that does not match rather than half-working.
    wanted = bundle.get("applies_to", {})
    if wanted.get("version") not in (None, package.get("version")):
        raise SystemExit(
            f"bundle {bundle['name']}-{bundle['version']} serves package version "
            f"{wanted.get('version')}, but this package is {package.get('version')}"
        )

    with psycopg.connect(args.database) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS data")
            cur.execute(
                "CREATE TABLE IF NOT EXISTS data.load_record ("
                " dataset text, rows bigint, package text, bundle text,"
                " loaded_at timestamptz)"
            )
            cur.execute("TRUNCATE data.load_record")

        print(f"package {package['name']}-{package['version']}")
        stamp = f"{package['name']}@{package['version']}"
        for resource in package["resources"]:
            rows = load_dataset(conn, resource["name"], args.package / resource["path"])
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO data.load_record VALUES (%s,%s,%s,%s,%s)",
                    (resource["name"], rows, stamp,
                     f"{bundle['name']}@{bundle['version']}", dt.datetime.now(dt.UTC)),
                )
            print(f"  data.{resource['name']:<24} {rows:>8,} rows")

        print(f"bundle {bundle['name']}-{bundle['version']}")
        for name in bundle["serving"]:
            with conn.cursor() as cur:
                cur.execute((args.bundle / "serving" / name).read_text())
            print(f"  applied {name}")

        # Proposal 0005 §4.4: feedback references geometry by value, with no
        # foreign key, because `data` is dropped and rebuilt on every load. The
        # loader reports how many feedback rows now point at nothing.
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('app.survey_contiguous_segments') IS NOT NULL")
            if cur.fetchone()[0]:
                cur.execute(
                    "SELECT count(*) FROM app.survey_contiguous_segments a"
                    " WHERE NOT EXISTS (SELECT 1 FROM data.road_segment g"
                    "                   WHERE g.segment_id = ANY(a.segment_ids))"
                )
                dangling = cur.fetchone()[0]
                print(f"feedback rows pointing at no segment: {dangling:,}")

        conn.commit()

    print(f"\nThis database now holds {stamp}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
