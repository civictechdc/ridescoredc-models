"""The consolidated bike road network, and its attributes.

A **base** plus **optional layers**. The base turns road geometry into
normalised segments and every model needs it. A layer runs only when some model
asked for a column it produces -- so nothing downloads crash records for a
model that does not score crash history.

The network is also the only part of the pipeline that knows where data came
from. A model receives normalised attributes and could not tell DDOT roadway
blocks from OSM ways.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import geopandas as gpd

from ridescore import config
from ridescore.network.attributes import classify_facility, name_function, normalise
from ridescore.network.base import Layer
from ridescore.network.crashes import LAYER as CRASH_LAYER
from ridescore.network.crashes import (
    clip_to_boundary,
    count_crashes_near_segments,
)
from ridescore.network.geometry import lean, round_coordinates

__all__ = [
    "BASE_COLUMNS",
    "BASE_SOURCES",
    "LAYERS",
    "Layer",
    "build",
    "classify_facility",
    "clip_to_boundary",
    "columns_available",
    "count_crashes_near_segments",
    "lean",
    "name_function",
    "normalise",
    "parse_area",
    "plan",
    "round_coordinates",
]

#: What the base always provides, from road geometry alone.
BASE_SOURCES: tuple[str, ...] = ("roads",)
BASE_COLUMNS: tuple[str, ...] = (
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
    "geometry",
)

#: Optional enrichments, by name. Add a layer here and it becomes available to
#: every model without any model that ignores it paying for it.
LAYERS: dict[str, Layer] = {
    CRASH_LAYER.name: CRASH_LAYER,
}


def columns_available() -> set[str]:
    """Every column the network could provide, base plus all layers."""
    columns = set(BASE_COLUMNS)
    for layer in LAYERS.values():
        columns.update(layer.produces)
    return columns


def plan(needed: Iterable[str]) -> tuple[tuple[Layer, ...], tuple[str, ...]]:
    """Which layers and which sources are required to supply `needed`.

    Returns `(layers, sources)`. Columns the base already provides need no
    layer; columns nothing provides are the caller's problem to report, since
    only the caller knows which model asked.
    """
    wanted = set(needed) - set(BASE_COLUMNS)
    layers = tuple(
        layer for layer in LAYERS.values() if wanted.intersection(layer.produces)
    )
    sources = list(BASE_SOURCES)
    for layer in layers:
        sources.extend(s for s in layer.sources if s not in sources)
    return layers, tuple(sources)


def parse_area(area: str | None) -> tuple[float, float, float, float] | None:
    """A bounding box as `minx,miny,maxx,maxy` in WGS84, or None for all of DC.

    Named neighbourhoods are not supported yet: it needs a published boundary
    dataset we do not fetch. Say so rather than silently scoring the whole city.
    """
    if area is None or not area.strip():
        return None
    parts = area.split(",")
    if len(parts) != 4:
        raise ValueError(
            f"--area must be 'minx,miny,maxx,maxy' in WGS84; got {area!r}. "
            "Named neighbourhoods are not supported yet."
        )
    try:
        minx, miny, maxx, maxy = (float(p) for p in parts)
    except ValueError as exc:
        raise ValueError(f"--area must be four numbers; got {area!r}") from exc
    return minx, miny, maxx, maxy


def build(
    files: dict[str, Path],
    layers: Iterable[Layer] = (),
    *,
    area: str | None = None,
) -> gpd.GeoDataFrame:
    """Read the snapshot and return segments ready to score.

    Reads no network. Every input comes from `files`, so this is safe and fast
    to re-run -- which is the whole reason fetch and build are separate.
    """
    missing = [name for name, path in files.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing fetched sources: {', '.join(sorted(missing))}")

    roads = gpd.read_file(files["roads"]).to_crs(config.CRS)

    bbox = parse_area(area)
    if bbox is not None:
        roads = roads.cx[bbox[0] : bbox[2], bbox[1] : bbox[3]].copy()
        if roads.empty:
            raise ValueError(f"--area {area!r} contains no road segments.")

    segments = normalise(roads)
    for layer in layers:
        segments = layer.apply(segments, {s: files[s] for s in layer.sources})

    return lean(segments)
