"""Making the output small enough to serve.

Ported from `notebooks/archive/data_processing.ipynb` cell 28, with one fix:
the notebook's coordinate rounding assumed every vertex carried a Z value
(`for x, y, z in ls.coords`) and raised on any 2D geometry. Rounding here goes
through `shapely.ops.transform`, which handles 2D, 3D, and multi-part
geometries alike.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.ops import transform

from ridescore import config


def lean(
    segments: gpd.GeoDataFrame,
    *,
    simplify_m: float = config.SIMPLIFY_TOLERANCE_M,
    decimals: int = config.COORDINATE_DECIMALS,
    min_length_m: float = config.MIN_SEGMENT_LENGTH_M,
) -> gpd.GeoDataFrame:
    """Drop duplicates and slivers, simplify, and round coordinates."""
    out = segments.copy()

    # Duplicate geometries: the source carries the same centreline more than
    # once where a block is described from both directions.
    out = out[~out.geometry.apply(lambda g: g.wkb).duplicated()].copy()

    projected = out.to_crs(config.CRASH_BUFFER_CRS)
    out = out[projected.length >= min_length_m].copy()
    if out.empty:
        return out

    projected = out.to_crs(config.CRASH_BUFFER_CRS)
    projected["geometry"] = projected.geometry.simplify(simplify_m, preserve_topology=True)
    out = projected.to_crs(config.CRS)

    out["geometry"] = out.geometry.apply(lambda g: round_coordinates(g, decimals))
    return out


def round_coordinates(geometry, decimals: int):
    """Round every ordinate. ~1 m at 5 decimal places, and a much smaller file."""
    return transform(lambda *ordinates: tuple(np.round(o, decimals) for o in ordinates), geometry)
