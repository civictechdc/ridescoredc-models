"""Fetching public data, and caching it as dated snapshots.

Sources are registered by name. Nothing fetches "everything" -- a build works
out which sources its model actually needs and fetches only those. Adding a
source for a new model (destinations and census blocks for BNA, say) means
adding an entry here and a layer that consumes it; no existing model changes,
and no existing model starts downloading it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from pathlib import Path

from ridescore.sources.base import Source
from ridescore.sources.opendata_dc import (
    crash_window,
    fetch_boundary,
    fetch_crashes,
    fetch_roads,
)

SOURCES: dict[str, Source] = {
    "roads": Source(
        name="roads",
        filename="roads.geojson",
        fetch=fetch_roads,
        description="DDOT roadway blocks — geometry and street attributes.",
    ),
    "crashes": Source(
        name="crashes",
        filename="crashes.geojson",
        fetch=fetch_crashes,
        description="Bicyclist injury and fatality crashes, five years back from the run date.",
    ),
    "boundary": Source(
        name="boundary",
        filename="boundary.geojson",
        fetch=fetch_boundary,
        description="The DC boundary, used to clip crashes to the city.",
    ),
}

__all__ = ["SOURCES", "Source", "crash_window", "fetch", "path_for"]


def path_for(data_dir: Path, name: str) -> Path:
    try:
        return data_dir / SOURCES[name].filename
    except KeyError as exc:
        raise KeyError(f"unknown source {name!r}. Registered: {', '.join(SOURCES)}") from exc


def fetch(
    data_dir: Path,
    names: Iterable[str],
    run_date: dt.date,
    *,
    force: bool = False,
) -> dict[str, Path]:
    """Fetch exactly the named sources. Returns what is now on disk."""
    data_dir.mkdir(parents=True, exist_ok=True)
    fetched: dict[str, Path] = {}
    for name in dict.fromkeys(names):  # de-duplicate, keep order
        source = SOURCES[name]
        fetched[name] = source.fetch(data_dir / source.filename, run_date, force)
    return fetched
