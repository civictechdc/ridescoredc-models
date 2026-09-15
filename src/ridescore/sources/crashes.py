"""Crashes that hurt a cyclist, from the DC public-safety ArcGIS service.

The window is five years counted back from the run date, so it moves with each
run. That is what the notebook did and it is a deliberate choice rather than an
inherited one: it also means two runs a month apart are over different windows,
which `run.json` records so a score can be interpreted later.
"""

from __future__ import annotations

import datetime as dt
import json
import time

import geopandas as gpd
import pandas as pd
from dateutil.relativedelta import relativedelta
from shapely.geometry import Point

from ridescore import config
from ridescore.sources import http
from ridescore.sources.cache import Snapshot

FILENAME = "crashes.json"


def window(run_date: dt.date, years_back: int = config.CRASH_YEARS_BACK) -> tuple[dt.date, dt.date]:
    """The five-year window, counted back from an explicit run date."""
    return run_date - relativedelta(years=years_back), run_date


def _where(start: dt.date, end: dt.date) -> str:
    """Crashes in the window that hurt at least one cyclist."""
    return (
        f"{config.CRASH_DATE_FIELD} >= DATE '{start.isoformat()} 00:00:00' "
        f"AND {config.CRASH_DATE_FIELD} <= DATE '{end.isoformat()} 23:59:59' "
        "AND (MAJORINJURIES_BICYCLIST > 0 "
        "OR MINORINJURIES_BICYCLIST > 0 "
        "OR UNKNOWNINJURIES_BICYCLIST > 0 "
        "OR FATAL_BICYCLIST > 0)"
    )


def fetch(snapshot: Snapshot, run_date: dt.date, *, refresh: bool = False) -> None:
    """Page through the service and write every matching feature."""
    if snapshot.has(FILENAME) and not refresh:
        return

    start, end = window(run_date)
    features: list[dict] = []
    offset = 0

    while True:
        page = http.get_json(
            config.CRASHES_URL,
            params={
                "where": _where(start, end),
                "outFields": "*",
                "outSR": 4326,
                "f": "json",
                # Ordered, so paging is stable and two fetches agree.
                "orderByFields": "OBJECTID",
                "resultOffset": offset,
                "resultRecordCount": config.CRASHES_PAGE_SIZE,
            },
        )
        batch = page.get("features", [])
        features.extend(batch)
        if len(batch) < config.CRASHES_PAGE_SIZE:
            break
        offset += config.CRASHES_PAGE_SIZE
        time.sleep(0.05)

    body = json.dumps(
        {"window": [start.isoformat(), end.isoformat()], "features": features},
        sort_keys=True,
    ).encode()
    snapshot.write(FILENAME, url=config.CRASHES_URL, content=body)


def load(snapshot: Snapshot) -> gpd.GeoDataFrame:
    """The crashes as fetched, with a point geometry and a local report date."""
    raw = json.loads(snapshot.file(FILENAME).read_text())

    rows = []
    for feature in raw["features"]:
        geometry = feature.get("geometry") or {}
        if "x" not in geometry or "y" not in geometry:
            continue  # a crash with no location cannot be attached to a street
        attributes = dict(feature.get("attributes", {}))
        attributes["geometry"] = Point(geometry["x"], geometry["y"])
        rows.append(attributes)

    frame = gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs=config.CRS)
    frame["REPORTDATE_"] = pd.to_datetime(
        frame[config.CRASH_DATE_FIELD], unit="ms", utc=True
    ).dt.tz_convert(config.CRASH_TIMEZONE)
    return frame


def prepare(crashes: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Clip to the city and keep the columns worth publishing.

    The clip is very nearly a no-op -- these come from the DC service already --
    but a crash recorded just outside the line should not attach to a DC street.
    """
    clipped = gpd.overlay(crashes, boundary[["geometry"]], how="intersection")
    renamed = clipped.rename(columns=config.CRASH_FIELD_NAMES)
    return renamed[[*config.CRASH_KEEP_COLUMNS, "geometry"]].set_geometry("geometry")
