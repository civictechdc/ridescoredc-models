"""BNA census blocks: a second geography, wrapped rather than reimplemented.

PeopleForBikes' Bicycle Network Analysis scores census blocks on what they can
reach without using high-stress streets. It is somebody else's model with its
own run cadence, so the pipeline does not compute it -- it reads the export and
writes the same kind of artifact every other stage writes.

This is the "wrapped at the edge" case: no network, no scoring, just a
projection of an existing export into a dataset with a description.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

FILENAME = "bna_census_block.parquet"

SOURCE_FILE = "neighborhood_census_blocks.geojson"

# What travels with the geometry. The BNA export carries ~60 columns; these are
# the four published scores plus what a popup needs to say which block it is.
COLUMNS = (
    "area_id",
    "tile_id",
    "pop20",
    "overall_score",
    "opportunity_score",
    "core_services_score",
    "recreation_score",
    "retail_score",
    "transit_score",
    "geometry",
)


def build(export_dir: Path) -> gpd.GeoDataFrame:
    """Read the BNA export for one city. Reads no network."""
    source = export_dir / SOURCE_FILE
    if not source.exists():
        raise FileNotFoundError(f"No BNA export at {source}")

    blocks = gpd.read_file(source)

    # `geoid20` is the 2020 census block GEOID -- published, stable across a
    # rebuild, and the reason this geography has no identity problem.
    blocks = blocks.rename(columns={"geoid20": "area_id"})

    # A tile's feature id must be a number, and the GEOID is a string. Selecting
    # a block, or attaching values fetched per selection, needs the numeric one,
    # so the stage that publishes the geography publishes it.
    blocks = blocks.sort_values("area_id").reset_index(drop=True)
    blocks["tile_id"] = blocks.index + 1

    return blocks[list(COLUMNS)].to_crs("EPSG:4326")


def write(blocks: gpd.GeoDataFrame, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / FILENAME
    blocks.to_parquet(path, index=False)
    return path
