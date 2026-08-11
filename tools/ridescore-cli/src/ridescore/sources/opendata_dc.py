"""Fetching the published DC datasets.

Ported from `notebooks/archive/data_processing.ipynb` cells 3, 16 and 17, with
three deliberate changes -- all recorded here because the port is otherwise
faithful:

1. **The boundary is fetched, not geocoded.** The notebook called
   `osmnx.geocode_to_gdf("Washington, DC")`, a live Nominatim lookup that is
   rate-limited, uncacheable and can return a different polygon tomorrow. The
   boundary is a published dataset, so it is fetched like every other input.

2. **A failed fetch raises.** The notebook caught every exception, printed a
   message and implicitly returned `None`, so a network failure did not stop
   the run -- it handed `None` to the next cell, which died later with an
   unrelated `AttributeError`. A fetch that fails now says so, at the point it
   failed.

3. **The crash filter has its missing spaces put back.** See `_crash_where`.

Everything else -- the URLs, the page size, the five-year window, the injury
filter -- is as the notebook had it.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

from ridescore import config

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_S = 2.0


def _get(url: str, *, timeout: int, params: dict | None = None) -> requests.Response:
    """GET with a small retry. Open Data DC is reliable but not always fast."""
    last: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last = exc
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_S * attempt)
    raise RuntimeError(f"giving up on {url} after {RETRY_ATTEMPTS} attempts: {last}") from last


def _crash_where(start: dt.date, end: dt.date) -> str:
    """The bicyclist-injury filter, five years wide.

    DEFECT FIXED (deliberately, and loudly): the notebook built this string
    from adjacent literals without trailing spaces, producing

        ... > 0OR MINORINJURIES_BICYCLIST > 0OR UNKNOWNINJURIES_BICYCLIST ...

    `0OR` is not valid SQL. Whatever the ArcGIS endpoint made of it, it was not
    the filter that was intended, and a silently-wrong WHERE clause changes
    which crashes exist -- which changes `crash_count_5yr`, which changes 30%
    of the published score. Written correctly here; if the crash totals move
    when this is first run, THIS is why.
    """
    return (
        f"REPORTDATE >= DATE '{start.isoformat()} 00:00:00' "
        f"AND REPORTDATE <= DATE '{end.isoformat()} 23:59:59' "
        "AND (MAJORINJURIES_BICYCLIST > 0 "
        "OR MINORINJURIES_BICYCLIST > 0 "
        "OR UNKNOWNINJURIES_BICYCLIST > 0 "
        "OR FATAL_BICYCLIST > 0)"
    )


def crash_window(run_date: dt.date, years_back: int = config.CRASH_YEARS_BACK) -> tuple:
    """The five-year window, counted back from the run date -- never the clock."""
    try:
        start = run_date.replace(year=run_date.year - years_back)
    except ValueError:  # 29 February
        start = run_date.replace(year=run_date.year - years_back, day=28)
    return start, run_date


# Every fetcher takes the same (dest, run_date, force) so the source registry
# can call them without knowing which is which. run_date is unused by sources
# that are not time-bounded, and that is fine -- it costs one parameter to keep
# the registry free of special cases.


def fetch_roads(dest: Path, run_date: dt.date | None = None, force: bool = False) -> Path:
    """DDOT roadway blocks.

    NOTE: this is the one source the OSM segmentation pivot replaces. Nothing
    downstream of the `segments` layer knows where the geometry came from, so
    an OSM source lands beside this one rather than editing it.
    """
    if dest.exists() and not force:
        return dest
    response = _get(config.ROADS_URL, timeout=120)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    return dest


def fetch_boundary(dest: Path, run_date: dt.date | None = None, force: bool = False) -> Path:
    """The DC boundary, used to clip crashes to the city."""
    if dest.exists() and not force:
        return dest
    response = _get(config.BOUNDARY_URL, timeout=60)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    return dest


def fetch_crashes(dest: Path, run_date: dt.date, force: bool = False) -> Path:
    """Bicyclist injury and fatality crashes, paged out of the ArcGIS service.

    The five-year window is derived from `run_date`, never from the clock.
    """
    if dest.exists() and not force:
        return dest

    start, end = crash_window(run_date)
    where = _crash_where(start, end)
    rows: list[dict] = []
    offset = 0

    while True:
        response = _get(
            config.CRASHES_URL,
            timeout=120,
            params={
                "where": where,
                "outFields": "*",
                "outSR": 4326,
                "f": "json",
                "orderByFields": "OBJECTID",
                "resultOffset": offset,
                "resultRecordCount": config.CRASHES_PAGE_SIZE,
            },
        )
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(f"ArcGIS rejected the crash query: {payload['error']}")

        features = payload.get("features", [])
        for feature in features:
            geometry = feature.get("geometry") or {}
            if "x" in geometry and "y" in geometry:
                attributes = dict(feature.get("attributes", {}))
                attributes["geometry"] = Point(geometry["x"], geometry["y"])
                rows.append(attributes)

        if len(features) < config.CRASHES_PAGE_SIZE:
            break
        offset += config.CRASHES_PAGE_SIZE
        time.sleep(0.05)

    crashes = gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs=config.CRS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if crashes.empty:
        # Writing an empty GeoDataFrame loses the schema, so record the shape
        # explicitly rather than producing a file that reads back as garbage.
        dest.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    else:
        crashes.to_file(dest, driver="GeoJSON")
    return dest
