"""Turn a roadway block into a street we can score.

Each function here takes the source's own field values and returns one
normalised attribute, so every rule can be tested on its own. Two values are
kept for the fields we fill in -- the filled one that scoring uses and the raw
one the map shows -- because a street with an unknown speed limit should not
look on the map as though someone measured 25 mph there.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from ridescore import config


def classify_facility(tags: dict) -> str:
    """Protected, buffered, painted, or nothing.

    Directionality is not taken into account: a lane in one direction makes the
    whole block that kind of street. Sharrows do not appear in the source.
    """
    protected = {tags.get("BIKELANE_PROTECTED"), tags.get("BIKELANE_DUAL_PROTECTED")}
    if protected & config.BIKELANE_PRESENT_CODES:
        return "protected_track"
    if tags.get("BIKELANE_BUFFERED") in config.BIKELANE_PRESENT_CODES:
        return "buffered_lane"
    if tags.get("BIKELANE_CONVENTIONAL") in config.BIKELANE_PRESENT_CODES:
        return "painted_lane"
    return "none"


def name_function(functional_class: object) -> str:
    """The road's job, by name rather than by the source's code."""
    return config.FUNCTION_CLASS_NAMES.get(functional_class, config.FUNCTION_CLASS_DEFAULT)


def num_lanes(raw: object) -> int:
    """Travel lanes, with the source's "unknown" filled in.

    The source uses -1 for unknown. Zero is a real answer and is kept.
    """
    if raw is None or pd.isna(raw):
        return config.DEFAULT_NUM_LANES
    return int(raw) if int(raw) > config.NUM_LANES_MIN_VALID else config.DEFAULT_NUM_LANES


def speed_limit(raw: object) -> int:
    """Posted speed, with the source's "unknown" filled in.

    DEFECT (fix after the port): the test is `> 1`, not `> 0`, so a recorded
    limit of exactly 1 mph is discarded and replaced by the default. See
    `config.SPEED_LIMIT_MIN_VALID`.
    """
    if raw is None or pd.isna(raw):
        return config.DEFAULT_SPEED_LIMIT
    return int(raw) if int(raw) > config.SPEED_LIMIT_MIN_VALID else config.DEFAULT_SPEED_LIMIT


def parking_presence(raw: object) -> bool:
    if raw is None or pd.isna(raw):
        return False
    return float(raw) > 0


def segment(tags: dict) -> dict:
    """One roadway block, normalised. Geometry is not touched here."""
    return {
        "segment_id": tags[config.SEGMENT_ID_FIELD],
        "route_id": tags["ROUTEID"],
        "route_name": tags["ROUTENAME"],
        "function": name_function(tags["DCFUNCTIONALCLASS"]),
        "num_lanes": num_lanes(tags["TOTALTRAVELLANES"]),
        "num_lanes_raw": tags["TOTALTRAVELLANES"],
        "speed_limit": speed_limit(tags[config.SPEED_LIMIT_FIELD]),
        "speed_limit_raw": tags[config.SPEED_LIMIT_FIELD],
        "bike_facility_type": classify_facility(tags),
        "parking_presence": parking_presence(tags["TOTALPARKINGLANES"]),
        "road_width": tags["TOTALCROSSSECTIONWIDTH"],
        "slow_street": tags["SLOWSTREETINFO"],
        "pavement_condition": tags["PCI_CONDCATEGORY"],
    }


def normalise(roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Every block, normalised, in the source's own order."""
    blocks = roads.reset_index(drop=True)
    rows = [
        {**segment(row.to_dict()), "geometry": row.geometry}
        for _, row in blocks.iterrows()
    ]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=config.CRS)


def add_length(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Length in metres, measured in the local UTM zone rather than in degrees."""
    metric = segments.to_crs(segments.estimate_utm_crs())
    out = segments.copy()
    out["len"] = metric.length
    return out
