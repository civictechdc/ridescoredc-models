"""Turn an OSM segment into a street we can score.

The OSM counterpart of `normalise`: the same output columns, so everything
downstream -- the crash join, the geometry steps, the model, `inspect`, the
loader -- cannot tell which source built the network.

The same two-value rule holds. Where OSM says nothing, the scoring value is
filled in from the highway type (`config.OSM_DEFAULT_*`) and the `_raw` value
stays empty, so the map and `inspect` can still tell a measured 25 mph from an
assumed one.
"""

from __future__ import annotations

import math
import re

import geopandas as gpd
import pandas as pd

from ridescore import config

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SIDES = ("", ":left", ":right", ":both")


def _text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    return text or None


def _values(value: object) -> list[str]:
    """A tag's values, split on OSM's `;`."""
    text = _text(value)
    return [part.strip() for part in text.split(";") if part.strip()] if text else []


def highway_type(tags: dict) -> str:
    """The segment's main highway type: the first of OSM's values, link or not."""
    values = _values(tags.get("highway"))
    return values[0] if values else ""


def road_kind(tags: dict) -> str:
    """The key into the default tables: the highway type, `link` or `trail`."""
    highway = highway_type(tags)
    if is_trail(tags):
        return "trail"
    if highway.endswith("_link"):
        return "link"
    return highway


def is_trail(tags: dict) -> bool:
    """Off-street and meant for bikes: a cycleway, or a path or footway bikes may use."""
    highway = highway_type(tags)
    if highway == "cycleway":
        return True
    allowed = config.OSM_TRAIL_BICYCLE.get(highway)
    return bool(allowed) and _text(tags.get("bicycle")) in allowed


def name_function(tags: dict) -> str:
    """The road's job, by name. A `_link` takes its parent's class."""
    highway = highway_type(tags).removesuffix("_link")
    return config.OSM_FUNCTION.get(highway, config.FUNCTION_CLASS_DEFAULT)


def classify_facility(tags: dict) -> str:
    """Protected, buffered, painted, or nothing, across every side tagged.

    Direction is not taken into account, as in the DDOT rules: a lane on one
    side makes the whole segment that kind of street. `shared_lane` (sharrows)
    and `separate` (the lane is drawn as its own way, which is scored on its
    own) count as nothing for this street.
    """
    if is_trail(tags):
        return "protected_track"

    found = set()
    for side in _SIDES:
        for value in _values(tags.get(f"cycleway{side}")):
            if value == "track":
                found.add("protected_track")
            elif value == "lane":
                buffer = _text(tags.get(f"cycleway{side}:buffer")) or _text(
                    tags.get("cycleway:buffer")
                )
                found.add("buffered_lane" if buffer and buffer != "no" else "painted_lane")

    for facility in ("protected_track", "buffered_lane", "painted_lane"):
        if facility in found:
            return facility
    return "none"


def parse_lanes(raw: object) -> float:
    """OSM's `lanes`, or NaN. Of several values (`2;3`), the most."""
    numbers = [float(n) for n in _NUMBER.findall(_text(raw) or "")]
    return max(numbers) if numbers else math.nan


def parse_maxspeed(raw: object) -> float:
    """OSM's `maxspeed` in mph, or NaN.

    A bare number is km/h -- OSM's convention -- and is converted. Of several
    values, the highest, as the street at its fastest. Words such as `signals`
    or `none` give no number and so NaN.
    """
    speeds = []
    for value in _values(raw):
        numbers = _NUMBER.findall(value)
        if not numbers:
            continue
        speed = float(numbers[0])
        speeds.append(speed if "mph" in value else round(speed / config.KMH_PER_MPH))
    return max(speeds) if speeds else math.nan


def _is_oneway(tags: dict) -> bool:
    return _text(tags.get("oneway")) in {"True", "true", "yes", "1", "-1"}


def num_lanes(tags: dict) -> int:
    """Travel lanes, filled in from the highway type when OSM does not say."""
    raw = parse_lanes(tags.get("lanes"))
    if not math.isnan(raw):
        return int(raw)
    kind = road_kind(tags)
    if kind in {"residential", "unclassified"} and _is_oneway(tags):
        return config.OSM_DEFAULT_LANES_ONEWAY_LOCAL
    return config.OSM_DEFAULT_LANES.get(kind, config.OSM_DEFAULT_LANES_FALLBACK)


def speed_limit(tags: dict) -> int:
    """Posted speed in mph, filled in from the highway type when OSM does not say."""
    raw = parse_maxspeed(tags.get("maxspeed"))
    if not math.isnan(raw):
        return int(raw)
    return config.OSM_DEFAULT_SPEED_MPH.get(road_kind(tags), config.OSM_DEFAULT_SPEED_FALLBACK_MPH)


def parking_sides(tags: dict) -> int:
    """How many sides cars park on: 0, 1 or 2."""

    def parks(side: str) -> bool:
        values = _values(tags.get(f"parking:{side}")) + _values(tags.get(f"parking:lane:{side}"))
        return any(value in config.OSM_PARKING_ON_STREET for value in values)

    if parks("both"):
        return 2
    return int(parks("left")) + int(parks("right"))


def pavement_condition(tags: dict) -> str | None:
    """From `smoothness`, the nearest thing OSM has to a condition index."""
    return config.OSM_SMOOTHNESS_TO_PAVEMENT.get(_text(tags.get("smoothness")) or "")


def road_width(tags: dict) -> float:
    """Width in feet: OSM's `width` (metres) if tagged, else an estimate.

    Estimated as lanes times a lane width plus a parking lane per side parked
    on, because an empty width leaves every user-weighted map score empty.
    """
    numbers = _NUMBER.findall(_text(tags.get("width")) or "")
    if numbers:
        return round(float(numbers[0]) * config.FEET_PER_METRE, 1)
    if is_trail(tags):
        return float(config.OSM_TRAIL_WIDTH_FT)
    return float(
        num_lanes(tags) * config.OSM_LANE_WIDTH_FT
        + parking_sides(tags) * config.OSM_PARKING_WIDTH_FT
    )


def segment(tags: dict) -> dict:
    """One OSM segment, normalised. Geometry is not touched here."""
    return {
        "segment_id": tags["segment_id"],
        "route_id": str(tags["osm_id"]),
        "route_name": _text(tags.get("name")),
        "function": name_function(tags),
        "num_lanes": num_lanes(tags),
        "num_lanes_raw": parse_lanes(tags.get("lanes")),
        "speed_limit": speed_limit(tags),
        "speed_limit_raw": parse_maxspeed(tags.get("maxspeed")),
        "bike_facility_type": classify_facility(tags),
        "parking_presence": parking_sides(tags) > 0,
        "road_width": road_width(tags),
        "slow_street": None,
        "pavement_condition": pavement_condition(tags),
    }


def normalise(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Every OSM segment, normalised, in the order given."""
    rows = [
        {**segment(row.to_dict()), "geometry": row.geometry}
        for _, row in segments.reset_index(drop=True).iterrows()
    ]
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=config.CRS)
    for column in ("num_lanes_raw", "speed_limit_raw"):
        out[column] = pd.to_numeric(out[column])
    return out
