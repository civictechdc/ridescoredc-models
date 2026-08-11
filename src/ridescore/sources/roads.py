"""DDOT roadway blocks: the street network, and every attribute we score on."""

from __future__ import annotations

import json

import geopandas as gpd

from ridescore import config
from ridescore.sources import http
from ridescore.sources.cache import Snapshot

FILENAME = "roadway_block.geojson"


def fetch(snapshot: Snapshot, *, refresh: bool = False) -> None:
    if snapshot.has(FILENAME) and not refresh:
        return
    snapshot.write(FILENAME, url=config.ROADS_URL, content=http.get(config.ROADS_URL))


def load(snapshot: Snapshot) -> gpd.GeoDataFrame:
    """The blocks as fetched. No normalisation -- that is the network build's job."""
    raw = json.loads(snapshot.file(FILENAME).read_text())
    return gpd.GeoDataFrame.from_features(raw["features"], crs=config.CRS)
