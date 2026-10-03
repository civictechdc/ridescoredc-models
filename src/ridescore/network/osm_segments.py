"""Cut OSM ways into segments: one per stretch between intersections.

A port of `fetch_osm()` in `notebooks/BaseData/OSM_BaseData.ipynb`, minus the
download, which `sources.osm` does. What a segment is:

* it runs from one intersection to the next, **including where an alley meets
  the street**, matching DDOT's SubBlocks; the alleys are then dropped;
* it is also cut wherever any tag in `config.OSM_RAW_TAGS` changes, so a bike
  lane starting mid-block splits the block rather than blurring into "lane;no";
* it is one row for both directions of travel.

Its key is the two OSM node ids at its ends, smaller first, plus osmnx's key
for telling apart two segments between the same pair of nodes. Node ids are
permanent in OSM, so the key survives a rebuild unless someone edits an
intersection at one of its ends. The parallel-edge number is the weak part: it
depends on the order osmnx meets the edges in.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import osmnx as ox
import pandas as pd

from ridescore import config

SEGMENT_PREFIX = "osm:"


def segment_id(u: int, v: int, key: int) -> str:
    """The same id whichever way round the segment was drawn."""
    low, high = sorted((int(u), int(v)))
    return f"{SEGMENT_PREFIX}{low}-{high}-{int(key)}"


def _is_alley(tags: dict) -> bool:
    return tags.get("highway") == "service" and tags.get("service") == "alley"


def _single(value: object) -> object:
    """One value for a tag that osmnx merged from several ways into a list.

    The ways were only merged because the tag agreed, so the distinct values left
    are OSM's own (a `highway` list across a link, say) and are kept `;`-joined,
    which is OSM's syntax for several values.
    """
    if isinstance(value, list):
        return ";".join(dict.fromkeys(map(str, value)))
    return value


def segments_from_xml(path: Path) -> gpd.GeoDataFrame:
    """Every segment in an OSM XML file, with its way tags, in a stable order."""
    previous_tags = ox.settings.useful_tags_way
    ox.settings.useful_tags_way = sorted(set(previous_tags) | set(config.OSM_RAW_TAGS))
    try:
        graph = ox.graph_from_xml(path, simplify=False, retain_all=True)
    finally:
        ox.settings.useful_tags_way = previous_tags

    present = {key for *_, data in graph.edges(data=True) for key in data}
    graph = ox.simplify_graph(
        graph, edge_attrs_differ=[t for t in config.OSM_RAW_TAGS if t in present]
    )

    alleys = [
        (u, v, k) for u, v, k, data in graph.edges(keys=True, data=True) if _is_alley(data)
    ]
    graph.remove_edges_from(alleys)
    graph = ox.convert.to_undirected(graph)

    if graph.number_of_edges() == 0:
        columns = ["segment_id", "osm_id", *config.OSM_RAW_TAGS, "geometry"]
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs=config.CRS)

    _, edges = ox.graph_to_gdfs(graph)
    edges = edges.reset_index()

    out = pd.DataFrame(
        {
            "segment_id": [
                segment_id(u, v, k)
                for u, v, k in zip(edges["u"], edges["v"], edges["key"], strict=True)
            ],
            # Several ways merged into one segment: take the lowest id, which
            # unlike "the first" does not depend on the order they were merged.
            "osm_id": edges["osmid"].map(lambda v: min(v) if isinstance(v, list) else v),
        }
    )
    for tag in config.OSM_RAW_TAGS:
        out[tag] = edges[tag].map(_single) if tag in edges.columns else None

    segments = gpd.GeoDataFrame(out, geometry=edges.geometry.values, crs=edges.crs)
    segments = segments.to_crs(config.CRS)
    # osmnx's own order follows its internal dicts; the segment key does not.
    return segments.sort_values("segment_id", kind="stable").reset_index(drop=True)
