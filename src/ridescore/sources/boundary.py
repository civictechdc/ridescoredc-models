"""The DC boundary, used to clip crashes to the city.

The notebook took this from a live Nominatim lookup through
`osmnx.geocode_to_gdf`, which cannot be cached and answers differently over
time. It is a published DC dataset, so it is fetched like any other input.
"""

from __future__ import annotations

import json

import geopandas as gpd

from ridescore import config
from ridescore.sources import http
from ridescore.sources.cache import Snapshot

FILENAME = "dc_boundary.geojson"


def fetch(snapshot: Snapshot, *, refresh: bool = False) -> None:
    if snapshot.has(FILENAME) and not refresh:
        return
    snapshot.write(FILENAME, url=config.BOUNDARY_URL, content=http.get(config.BOUNDARY_URL))


def load(snapshot: Snapshot) -> gpd.GeoDataFrame:
    raw = json.loads(snapshot.file(FILENAME).read_text())
    return gpd.GeoDataFrame.from_features(raw["features"], crs=config.CRS)[["geometry"]]
