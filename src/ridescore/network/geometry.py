"""Preparing geometry for the map.

All four of these destroy detail, and all four happen at build time, which means
the detail is gone from the published data and not only from the tiles. That is
what the notebook did and the port keeps it; `config` marks it.

The order matters and is the notebook's: drop duplicates, drop short segments,
simplify, round. Dropping short segments before simplifying means length is
measured on the real geometry.
"""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

from ridescore import config

METRIC_CRS = "EPSG:3857"


def drop_duplicate_geometries(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Keep the first block of each distinct shape.

    "First" is the source's own order, which is why nothing is sorted until
    everything has been computed.
    """
    keys = segments.geometry.apply(lambda geometry: geometry.wkb)
    return segments[~keys.duplicated()].copy()


def drop_short_segments(
    segments: gpd.GeoDataFrame, *, min_length_m: float = config.MIN_SEGMENT_LENGTH_M
) -> gpd.GeoDataFrame:
    """Drop blocks shorter than the threshold.

    DEFECT (fix after the port): this drops *features*, not detail, so a short
    block does not exist at any zoom. See `config.MIN_SEGMENT_LENGTH_M`.
    """
    metric = segments.to_crs(METRIC_CRS)
    return segments[metric.length >= min_length_m].copy()


def simplify(
    segments: gpd.GeoDataFrame, *, tolerance_m: float = config.SIMPLIFY_TOLERANCE_M
) -> gpd.GeoDataFrame:
    """Simplify in metres, then return to WGS84.

    DEFECT (fix after the port): about eight pixels at zoom 18, applied once and
    irreversibly. See `config.SIMPLIFY_TOLERANCE_M`.
    """
    metric = segments.to_crs(METRIC_CRS)
    metric["geometry"] = metric.geometry.simplify(tolerance_m, preserve_topology=True)
    return metric.to_crs(config.CRS)


def round_linestring(line: LineString, decimals: int = config.COORDINATE_DECIMALS) -> LineString:
    """Round longitude and latitude, leaving any Z alone.

    The notebook unpacked every coordinate as `x, y, z` and so failed on plain
    2D geometry. DC's roadway blocks happen to carry a Z, but a source that
    stops doing so should not stop the run.
    """
    rounded = [
        (round(point[0], decimals), round(point[1], decimals), *point[2:])
        for point in line.coords
    ]
    return LineString(rounded)


def round_coordinates(
    segments: gpd.GeoDataFrame, *, decimals: int = config.COORDINATE_DECIMALS
) -> gpd.GeoDataFrame:
    out = segments.copy()
    out["geometry"] = out.geometry.apply(lambda line: round_linestring(line, decimals))
    return out


def prepare_for_render(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """The four steps, in the notebook's order."""
    prepared = drop_duplicate_geometries(segments)
    prepared = drop_short_segments(prepared)
    prepared = simplify(prepared)
    return round_coordinates(prepared)
