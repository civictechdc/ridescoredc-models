"""One run: raw snapshot in, three datasets and a run record out.

The order here is the notebook's, and the two places it looks odd are the two
places it matters:

* Scores are computed over **every** segment, and only then are duplicate,
  short and over-detailed geometries dropped. So the crash normalisation is
  taken over the whole network rather than over what survives rendering.
* Length is measured before any geometry is simplified, so `len` is the length
  of the street rather than of the drawing of it.

Nothing is sorted until everything is computed: "keep the first of these
duplicates" means the first in the source's order, and re-sorting earlier would
quietly change which block survives.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd

from ridescore import config
from ridescore.models.ridescore_v1 import scores as ridescore_v1
from ridescore.models.ridescore_v1 import weights as ridescore_v1_weights
from ridescore.network import crash_join, geometry, normalise
from ridescore.sources import boundary, crashes, roads
from ridescore.sources.cache import Snapshot

ROAD_SEGMENT_COLUMNS = (
    "segment_id",
    "tile_id",
    "route_id",
    "route_name",
    "function",
    "num_lanes",
    "num_lanes_raw",
    "speed_limit",
    "speed_limit_raw",
    "bike_facility_type",
    "parking_presence",
    "road_width",
    "slow_street",
    "pavement_condition",
    "len",
    "crash_count_5yr",
    "serious_injury_count_5yr",
    "fatal_count_5yr",
    "geometry",
)

FILENAMES = {
    "road_segment": "road_segment.parquet",
    "crashes": "crashes.parquet",
    "ridescore_v1_scores": "ridescore_v1_scores.parquet",
}


class BuildError(RuntimeError):
    """The run cannot produce a dataset anyone should trust."""


@dataclass
class Built:
    """What one run produced, in memory."""

    road_segment: gpd.GeoDataFrame
    crashes: gpd.GeoDataFrame
    ridescore_v1_scores: pd.DataFrame
    derived: dict

    def counts(self) -> dict[str, int]:
        return {
            "road_segment": len(self.road_segment),
            "crashes": len(self.crashes),
            "ridescore_v1_scores": len(self.ridescore_v1_scores),
        }


def build(snapshot: Snapshot, run_date: dt.date) -> Built:
    """Everything between a fetched snapshot and the files on disk."""
    segments = normalise.normalise(roads.load(snapshot))
    segments = normalise.add_length(segments)

    published_crashes = crashes.prepare(crashes.load(snapshot), boundary.load(snapshot))
    segments = crash_join.count_crashes_near_segments(segments, published_crashes)

    weights = ridescore_v1_weights.load()
    p95_crashes = ridescore_v1.p95(segments["crash_count_5yr"])
    scored = ridescore_v1.score(segments, weights, p95_crashes=p95_crashes)

    # Geometry is reduced last, and takes the scores with it: a segment dropped
    # here is dropped from every dataset, so no score refers to a street that
    # no longer exists.
    rendered = geometry.prepare_for_render(segments)
    scored = scored.loc[rendered.index]

    rendered, scored = _sort_and_key(rendered, scored)

    return Built(
        road_segment=_road_segment(rendered),
        crashes=published_crashes.reset_index(drop=True),
        ridescore_v1_scores=scored,
        derived={
            "p95_crash_count": p95_crashes,
            "weights": weights.as_dict(),
            "crash_window": [d.isoformat() for d in crashes.window(run_date)],
        },
    )


def _sort_and_key(
    segments: gpd.GeoDataFrame, scored: pd.DataFrame
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Sort once, at the end, and number the rows.

    `tile_id` is the row number after this sort, assigned here rather than by
    the database: a database-assigned row number differs between two loads of
    the same data, which would make two identical runs look different.
    """
    duplicated = segments["segment_id"].duplicated()
    if duplicated.any():
        examples = ", ".join(segments.loc[duplicated, "segment_id"].head(3).astype(str))
        raise BuildError(
            f"{int(duplicated.sum())} segments share a segment_id ({examples}). "
            "Scores are keyed on it, so it has to identify one street."
        )

    order = segments["segment_id"].sort_values(kind="stable").index
    segments = segments.loc[order].reset_index(drop=True)
    scored = scored.loc[order].reset_index(drop=True)

    segments["tile_id"] = range(len(segments))
    scored.insert(0, "segment_id", segments["segment_id"])
    return segments, scored


def _road_segment(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """The street network as published: attributes of the street, and nothing else."""
    out = segments.copy()
    # The deployed table carries this as an integer, and the popup reads it as one.
    out["parking_presence"] = out["parking_presence"].astype(int)
    return out[list(ROAD_SEGMENT_COLUMNS)].set_geometry("geometry")


def write(built: Built, out: Path) -> dict[str, Path]:
    """Write one file per dataset. Geoparquet carries its own CRS and extent.

    Geometry is written as WKB explicitly rather than by relying on geopandas'
    default, because the loader that reads these files does so with pyarrow and
    has no geometry library to fall back on.
    """
    out.mkdir(parents=True, exist_ok=True)
    written = {}

    built.road_segment.to_parquet(
        out / FILENAMES["road_segment"], index=False, geometry_encoding="WKB"
    )
    written["road_segment"] = out / FILENAMES["road_segment"]

    built.crashes.to_parquet(
        out / FILENAMES["crashes"], index=False, geometry_encoding="WKB"
    )
    written["crashes"] = out / FILENAMES["crashes"]

    built.ridescore_v1_scores.to_parquet(out / FILENAMES["ridescore_v1_scores"], index=False)
    written["ridescore_v1_scores"] = out / FILENAMES["ridescore_v1_scores"]

    return written


def read(out: Path, dataset: str) -> pd.DataFrame:
    """Read one dataset back, for `inspect` and for comparing two runs."""
    path = out / FILENAMES[dataset]
    if dataset == "ridescore_v1_scores":
        return pd.read_parquet(path)
    return gpd.read_parquet(path)


__all__ = ["FILENAMES", "BuildError", "Built", "build", "config", "read", "write"]
