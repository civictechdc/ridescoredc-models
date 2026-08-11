"""Attaching crash history to segments -- an OPTIONAL layer.

The count of crashes near a street is an *attribute* of the street, like its
speed limit. Turning the count into a score is the model's business, not this
module's.

This is a layer rather than part of the network because most models do not want
it. LTS is physical characteristics only. BNA is about connectivity to
destinations. Only `ridescore_v1` blends crash history in -- so only a build
that includes `ridescore_v1` pays for downloading five years of crash records.

Ported from `notebooks/archive/data_processing.ipynb` cell 22.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from ridescore import config
from ridescore.network.base import Layer


def clip_to_boundary(crashes: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Keep only crashes inside the city.

    Probably unnecessary given the records come from DC's own service, but the
    notebook did it and it costs nothing to keep the guarantee explicit.
    """
    if crashes.empty:
        return crashes
    return gpd.overlay(
        crashes.to_crs(config.CRS),
        boundary.to_crs(config.CRS)[["geometry"]],
        how="intersection",
    )


def count_crashes_near_segments(
    segments: gpd.GeoDataFrame,
    crashes: gpd.GeoDataFrame,
    buffer_m: float = config.CRASH_BUFFER_M,
) -> gpd.GeoDataFrame:
    """Add `crash_count_5yr`: crashes falling within `buffer_m` of each segment.

    DEFECT (ported): the buffer is applied in `config.CRASH_BUFFER_CRS`
    (Web Mercator), where one unit at DC's latitude is about 0.78 of a real
    metre -- so this is roughly 7.8 m on the ground, not 10. It changes which
    crashes attach to which street, so it is left as the notebook had it until
    the port can be diffed.

    A crash near an intersection lands within the buffer of *several* segments
    and is counted for each. That is the notebook's behaviour and is arguably
    right -- the danger belongs to all of them.
    """
    out = segments.copy()
    if crashes.empty or segments.empty:
        out["crash_count_5yr"] = 0
        return out

    projected = segments.to_crs(config.CRASH_BUFFER_CRS)
    buffered = projected.copy()
    buffered["buffered_geometry"] = projected.geometry.buffer(buffer_m)
    buffered = buffered.set_geometry("buffered_geometry", crs=config.CRASH_BUFFER_CRS)

    points = crashes.to_crs(config.CRASH_BUFFER_CRS)

    # The notebook carried a brute-force fallback for a missing spatial index.
    # geopandas 1.x always has one (shapely 2 ships STRtree), so the fallback
    # was unreachable; it is dropped rather than ported as dead code.
    joined = gpd.sjoin(
        points[["geometry"]],
        buffered[["buffered_geometry"]],
        how="inner",
        predicate="within",
    )

    counts = joined.groupby(joined["index_right"]).size()
    out["crash_count_5yr"] = counts.reindex(out.index).fillna(0).astype(int)

    # Present in the published table, never populated by the notebook. Kept so
    # the output schema matches what the database expects.
    out["serious_injury_count_5yr"] = 0
    out["fatal_count_5yr"] = 0
    return out


def _apply(segments: gpd.GeoDataFrame, files: dict[str, Path]) -> gpd.GeoDataFrame:
    crashes = gpd.read_file(files["crashes"])
    if not crashes.empty:
        boundary = gpd.read_file(files["boundary"])
        crashes = clip_to_boundary(crashes.to_crs(config.CRS), boundary)
    return count_crashes_near_segments(segments, crashes)


LAYER = Layer(
    name="crash_counts",
    sources=("crashes", "boundary"),
    produces=("crash_count_5yr", "serious_injury_count_5yr", "fatal_count_5yr"),
    apply=_apply,
    description="Bicyclist injury crashes within ~10 m of each segment, five years back.",
)
