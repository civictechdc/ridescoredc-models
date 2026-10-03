"""OpenStreetMap: the street network, as raw OSM XML from Overpass.

Fetched as XML rather than built into a graph here, so the snapshot holds what
OSM said and `build` turns it into segments offline. The query and its filters
are in `config`.

Overpass has its own version of the ArcGIS 202: a query that runs out of time
or memory still answers **200**, with whatever it had so far and a `<remark>`
saying it stopped. Saving that would make a partial network look like a whole
one, so it fails instead.
"""

from __future__ import annotations

from pathlib import Path

from ridescore import config
from ridescore.sources import http
from ridescore.sources.cache import Snapshot

FILENAME = "osm.xml"


def query(area_id: int = config.OSM_DC_AREA_ID) -> str:
    """The Overpass QL for every way in the network, and the nodes they use."""
    highway = f'["highway"~"^({"|".join(config.OSM_HIGHWAY_TYPES)})$"]'
    filters = (highway, *config.OSM_TRAIL_FILTERS, *config.OSM_SPLIT_ONLY_FILTERS)
    ways = "\n".join(f"  way{f}(area.dc);" for f in filters)
    return (
        f"[out:xml][timeout:{config.OVERPASS_TIMEOUT_S}];\n"
        f"area({area_id})->.dc;\n"
        f"(\n{ways}\n);\n"
        "(._;>;);\n"
        "out body;\n"
    )


def check(content: bytes) -> None:
    """Refuse an Overpass answer that says it is incomplete."""
    head = content[:4096]
    if b"<remark>" in content and b"runtime error" in content:
        start = content.find(b"<remark>")
        remark = content[start : start + 300].decode("utf-8", "replace")
        raise http.FetchError(f"Overpass stopped before finishing: {remark}")
    if b"<osm" not in head:
        raise http.FetchError(f"Overpass did not answer with OSM XML: {head[:200]!r}")


def fetch(snapshot: Snapshot, *, refresh: bool = False) -> None:
    if snapshot.has(FILENAME) and not refresh:
        return
    text = query()
    # Overpass sends nothing until the query is done, which on all of DC can
    # outlast the ordinary read timeout; allow the query's own limit and a margin.
    content = http.get(
        config.OVERPASS_URL,
        params={"data": text},
        headers={"User-Agent": config.OVERPASS_USER_AGENT},
        timeout_s=config.OVERPASS_TIMEOUT_S + 60,
    )
    check(content)
    snapshot.write(FILENAME, url=f"{config.OVERPASS_URL}?data={text}", content=content)


def path(snapshot: Snapshot) -> Path:
    """The fetched XML. Read by `network.osm_segments`, which needs a file."""
    if not snapshot.has(FILENAME):
        raise FileNotFoundError(
            f"{snapshot.file(FILENAME)} is missing. Run `ridescore fetch --source osm` first."
        )
    return snapshot.file(FILENAME)
