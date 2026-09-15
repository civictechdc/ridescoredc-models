"""How many crashes happened near each street.

A count of crashes near a segment is an attribute of the street, like its speed
limit -- any model may use it. Turning that count into a score is the model's
business and lives elsewhere.

A crash within the buffer of two streets counts for both. That is the notebook's
behaviour and it is the right one for a corner: the crash happened at the
junction of both.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from ridescore import config

COUNT_COLUMNS = ("crash_count_5yr", "serious_injury_count_5yr", "fatal_count_5yr")


def _counts_for(segment_index: pd.Series, keep: pd.Series, index: pd.Index) -> pd.Series:
    """Count matched pairs per segment, restricted to the crashes `keep` selects."""
    selected = segment_index[keep.to_numpy()]
    return selected.value_counts().reindex(index).fillna(0).astype("int64")


def count_crashes_near_segments(
    segments: gpd.GeoDataFrame,
    crashes: gpd.GeoDataFrame,
    *,
    buffer_m: float = config.CRASH_BUFFER_M,
    crs: str = config.CRASH_BUFFER_CRS,
) -> gpd.GeoDataFrame:
    """Attach the three crash counts to every segment.

    DEFECT (fix after the port): the buffer is applied in Web Mercator, where a
    unit at DC's latitude is about 0.78 of a real metre -- so the 10 here is
    roughly 7.8 m on the ground. See `config.CRASH_BUFFER_CRS`.
    """
    out = segments.copy()

    if segments.empty or crashes.empty:
        for column in COUNT_COLUMNS:
            out[column] = pd.Series(0, index=out.index, dtype="int64")
        return out

    buffers = gpd.GeoDataFrame(
        geometry=segments.to_crs(crs).geometry.buffer(buffer_m),
        crs=crs,
    )
    points = crashes.to_crs(crs)[["geometry"]]

    # Indexed by crash, carrying the segment it fell inside. A crash inside no
    # buffer is kept by the left join with no segment, and drops out here.
    joined = gpd.sjoin(points, buffers, how="left", predicate="within")
    matched = joined.dropna(subset=["index_right"])
    segment_index = matched["index_right"].astype("int64")

    everything = pd.Series(True, index=matched.index)
    serious = crashes[config.CRASH_SERIOUS_FIELD].gt(0).reindex(matched.index).fillna(False)
    fatal = crashes[config.CRASH_FATAL_FIELD].gt(0).reindex(matched.index).fillna(False)

    out["crash_count_5yr"] = _counts_for(segment_index, everything, segments.index)
    out["serious_injury_count_5yr"] = _counts_for(segment_index, serious, segments.index)
    out["fatal_count_5yr"] = _counts_for(segment_index, fatal, segments.index)
    return out
