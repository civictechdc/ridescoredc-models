"""Raw source fields to normalised segment attributes.

This module is the *only* place that knows a source field name. Everything
downstream -- every model -- sees `speed_limit`, `num_lanes`,
`bike_facility_type` and never `SPEEDLIMITS_OB`. That boundary is what lets the
network move to a different data source without touching a model.

Ported from `notebooks/archive/data_processing.ipynb` cells 5 and 6, unchanged.
"""

from __future__ import annotations

from typing import Any

import geopandas as gpd

from ridescore import config


def classify_facility(tags: dict[str, Any]) -> str:
    """Standardise bike lane type into protected / buffered / painted / none.

    Sharrows are not indicated in the dataset. Direction is not taken into
    account: a lane inbound only still reads as a lane.
    """
    codes = config.BIKELANE_PRESENT_CODES
    if tags.get("BIKELANE_PROTECTED") in codes or tags.get("BIKELANE_DUAL_PROTECTED") in codes:
        return "protected_track"
    if tags.get("BIKELANE_BUFFERED") in codes:
        return "buffered_lane"
    if tags.get("BIKELANE_CONVENTIONAL") in codes:
        return "painted_lane"
    return "none"


def name_function(tags: dict[str, Any]) -> str:
    """DDOT's numeric functional class to a readable name."""
    return config.FUNCTION_CLASS_NAMES.get(
        tags.get("DCFUNCTIONALCLASS"), config.FUNCTION_CLASS_DEFAULT
    )


def normalise(roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """One row per segment, with filled values beside the raw ones.

    Both are kept on purpose. The map displays what was *recorded*; the models
    score what was *filled in*. Anything that cannot tell the two apart is
    asserting something about thousands of streets nobody measured -- see
    `notebooks/BaseData/README.md`.
    """
    rows = []
    for _, record in roads.reset_index(drop=True).iterrows():
        tags = record.to_dict()

        raw_lanes = tags.get("TOTALTRAVELLANES")
        raw_speed = tags.get(config.SPEED_LIMIT_FIELD)

        rows.append(
            {
                "route_id": tags.get("ROUTEID"),
                "route_name": tags.get("ROUTENAME"),
                "function": name_function(tags),
                # A missing lane count becomes 1 -- a quiet residential street.
                "num_lanes": raw_lanes if _present(raw_lanes, 0) else config.DEFAULT_NUM_LANES,
                "num_lanes_raw": raw_lanes,
                # DEFECT (ported): the test is "> 1", not "> 0", so a recorded
                # limit of exactly 1 mph is discarded for the default.
                "speed_limit": (
                    raw_speed
                    if _present(raw_speed, config.SPEED_LIMIT_MIN_VALID)
                    else config.DEFAULT_SPEED_LIMIT
                ),
                "speed_limit_raw": raw_speed,
                "bike_facility_type": classify_facility(tags),
                "parking_presence": bool(_present(tags.get("TOTALPARKINGLANES"), 0)),
                "road_width": tags.get("TOTALCROSSSECTIONWIDTH"),
                "slow_street": tags.get("SLOWSTREETINFO"),
                "pavement_condition": tags.get("PCI_CONDCATEGORY"),
                "geometry": record.geometry,
            }
        )

    return gpd.GeoDataFrame(rows, geometry="geometry", crs=config.CRS)


def _present(value: Any, floor: float) -> bool:
    """True when a value was actually recorded and exceeds `floor`.

    The notebook compared `None > -1` directly, which raises on Python 3. Guard
    the comparison rather than the value, so a missing field and a sentinel
    value both fall through to the default.
    """
    try:
        return value is not None and float(value) > floor
    except (TypeError, ValueError):
        return False
