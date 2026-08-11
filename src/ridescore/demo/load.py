"""Parquet in, PostGIS out.

The loader decides the table's shape from the parquet's own schema, so the
database's structure follows what was built rather than a migration written by
hand months earlier. That is the property this exists to demonstrate, and it is
the reason it is not `ogr2ogr`: a tool that decides its own DDL gives it away.

Deliberately missing, because Track B is still settling their format: any
validation beyond the description check, package identity, versioning, and any
handling of a failed load other than leaving the previous table alone.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import geopandas as gpd
import pandas as pd
import psycopg
import shapely
from shapely import wkb

from ridescore.demo import descriptions as desc

# pandas dtype kind -> column type. Widest sensible choice each time: this runs
# once over a few tens of thousands of rows, so nothing is gained by being
# clever about integer widths.
SQL_TYPES = {
    "i": "bigint",
    "u": "bigint",
    "f": "double precision",
    "b": "boolean",
    "M": "timestamptz",
    "O": "text",
    "U": "text",
}

GEOMETRY_TYPE = "geometry(Geometry, 4326)"

LOAD_RECORD = "ridescore_load"


def read(path: Path) -> pd.DataFrame:
    """Read a dataset, keeping geometry as geometry if it has any."""
    try:
        return gpd.read_parquet(path)
    except ValueError:
        return pd.read_parquet(path)


def column_type(dtype) -> str:
    if dtype.name == "geometry":
        return GEOMETRY_TYPE
    try:
        return SQL_TYPES[dtype.kind]
    except KeyError:  # pragma: no cover - demo
        return "text"


def ddl(table: str, frame: pd.DataFrame) -> str:
    columns = ",\n    ".join(
        f'"{name}" {column_type(dtype)}' for name, dtype in frame.dtypes.items()
    )
    return f'CREATE TABLE "{table}" (\n    {columns}\n)'


def _missing(value) -> bool:
    """Anything pandas uses for "not recorded", including a float NaN."""
    return (
        value is None
        or value is pd.NaT
        or value is pd.NA
        or (isinstance(value, float) and value != value)
    )


def _rows(frame: pd.DataFrame):
    """Rows as plain Python, geometry as hex WKB, missing values as NULL."""
    geometry_columns = {
        name for name, dtype in frame.dtypes.items() if dtype.name == "geometry"
    }
    names = list(frame.columns)

    for row in frame.itertuples(index=False, name=None):
        out = []
        for name, value in zip(names, row, strict=True):
            if name in geometry_columns:
                # The road network is LineStringZ -- an artifact of the source,
                # carried through the notebook and into the deployed table. A
                # tile is 2D, so the elevation is dropped here rather than
                # given a column that nothing can draw.
                out.append(
                    None
                    if value is None
                    else wkb.dumps(shapely.force_2d(value), hex=True, srid=4326)
                )
            elif _missing(value):
                out.append(None)
            else:
                out.append(value)
        yield out


def load_dataset(
    connection: psycopg.Connection,
    dataset: str,
    frame: pd.DataFrame,
    *,
    source: Path,
) -> int:
    """Replace one table with one dataset. Scoring data is full-replace."""
    columns = ", ".join(f'"{name}"' for name in frame.columns)

    with connection.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS "{dataset}" CASCADE')
        cur.execute(ddl(dataset, frame))

        with cur.copy(f'COPY "{dataset}" ({columns}) FROM STDIN') as copy:
            for row in _rows(frame):
                copy.write_row(row)

        for name, dtype in frame.dtypes.items():
            if dtype.name == "geometry":
                cur.execute(f'CREATE INDEX ON "{dataset}" USING gist ("{name}")')

        cur.execute(
            f'INSERT INTO "{LOAD_RECORD}" (dataset, rows, source, loaded_at)'
            " VALUES (%s, %s, %s, %s)",
            (dataset, len(frame), str(source), dt.datetime.now(dt.UTC)),
        )

    return len(frame)


def ensure_load_record(connection: psycopg.Connection) -> None:
    """What the database is serving, recorded by the thing that served it.

    No orchestrator can answer that question -- only the database that was
    written to.
    """
    with connection.cursor() as cur:
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS "{LOAD_RECORD}" ('
            " dataset text, rows bigint, source text, loaded_at timestamptz)"
        )


def create_join_view(connection: psycopg.Connection, view: str, geometry: str, scores: str,
                     key: str) -> None:
    """One geometry table, narrow score tables joined to it.

    The tile server needs one relation per source, so the join is a serving
    fact rather than something the pipeline bakes into its output.
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = %s AND column_name <> %s ORDER BY ordinal_position",
            (scores, key),
        )
        joined = ", ".join(f's."{name}"' for name, in cur.fetchall())

        cur.execute(f'DROP VIEW IF EXISTS "{view}"')
        cur.execute(
            f'CREATE VIEW "{view}" AS SELECT g.*, {joined} FROM "{geometry}" g'
            f' JOIN "{scores}" s USING ("{key}")'
        )


def load(out: Path, dsn: str, datasets: list[str]) -> dict[str, int]:
    """Load each dataset, checking it against its description first."""
    loaded: dict[str, int] = {}

    with psycopg.connect(dsn) as connection:
        ensure_load_record(connection)

        for dataset in datasets:
            path = out / f"{dataset}.parquet"
            frame = read(path)

            problems = desc.check(desc.load(dataset), frame)
            if problems:
                raise desc.DescriptionError(
                    f"{dataset} does not match its description:\n  "
                    + "\n  ".join(problems)
                )

            loaded[dataset] = load_dataset(connection, dataset, frame, source=path)

        connection.commit()

    return loaded
