# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Cut the committed OSM test extract out of a real OSM snapshot.

Reads a `raw-osm/<date>/` written by `ridescore fetch --source osm` and writes
`tests/fixtures/osm_snapshot/<date>/` with the same filenames, so `build` reads
it without knowing the difference. Reads no network.

    uv run scripts/make_osm_fixture.py --snapshot raw-osm/2026-10-03

What it keeps:

* every way with at least one node inside the box, **whole**, and every node
  those ways use -- so a street crossing the edge keeps its full length, but
  the cross streets beyond the edge are gone and the segments there are cut
  differently from a full-city build;
* the crashes inside the box plus a margin -- not along the whole of every
  kept way, which would carry hundreds of crashes for streets mostly outside it;
* the extent itself as the boundary, as the DDOT fixture does, so the clip
  does not depend on a 490 kB polygon.
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

# Around 14th and U St NW: every bike facility type OSM gives us (including one
# of DC's few tagged buffered lanes), four road functions, plenty of crashes, and
# streets with and without lane and speed tags.
DEFAULT_BBOX = (-77.0350, 38.9160, -77.0280, 38.9225)

# Crashes this far outside the kept streets, in degrees (about 100 m), so the
# buffers at the edge still have something to count.
CRASH_MARGIN_DEG = 0.001


def cut_osm(source: Path, bbox: tuple[float, float, float, float]) -> tuple[bytes, tuple]:
    root = ET.parse(source).getroot()
    minx, miny, maxx, maxy = bbox

    nodes = {n.get("id"): n for n in root.iter("node")}

    def inside(node_id: str) -> bool:
        node = nodes.get(node_id)
        if node is None:
            return False
        lon, lat = float(node.get("lon")), float(node.get("lat"))
        return minx <= lon <= maxx and miny <= lat <= maxy

    ways = [w for w in root.iter("way") if any(inside(nd.get("ref")) for nd in w.iter("nd"))]
    used = {nd.get("ref") for w in ways for nd in w.iter("nd")}

    out = ET.Element("osm", root.attrib)
    for child in root:
        if child.tag in {"note", "meta"}:  # ODbL attribution travels with the data
            out.append(child)
    kept_nodes = [nodes[i] for i in sorted(used, key=int) if i in nodes]
    out.extend(kept_nodes)
    out.extend(sorted(ways, key=lambda w: int(w.get("id"))))
    ET.indent(out)

    lons = [float(n.get("lon")) for n in kept_nodes]
    lats = [float(n.get("lat")) for n in kept_nodes]
    extent = (min(lons), min(lats), max(lons), max(lats))
    body = ET.tostring(out, encoding="UTF-8", xml_declaration=True) + b"\n"
    return body, extent


def cut_crashes(source: Path, bbox: tuple) -> bytes:
    raw = json.loads(source.read_text())
    minx, miny, maxx, maxy = bbox
    m = CRASH_MARGIN_DEG

    def near(feature: dict) -> bool:
        g = feature.get("geometry") or {}
        return "x" in g and minx - m <= g["x"] <= maxx + m and miny - m <= g["y"] <= maxy + m

    kept = [f for f in raw["features"] if near(f)]
    return json.dumps({"window": raw["window"], "features": kept}, sort_keys=True).encode()


def boundary(extent: tuple) -> bytes:
    minx, miny, maxx, maxy = extent
    m = CRASH_MARGIN_DEG
    ring = [[minx - m, miny - m], [minx - m, maxy + m], [maxx + m, maxy + m],
            [maxx + m, miny - m], [minx - m, miny - m]]
    feature = {"type": "Feature", "properties": {},
               "geometry": {"type": "Polygon", "coordinates": [ring]}}
    return json.dumps({"type": "FeatureCollection", "features": [feature]}).encode()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", type=Path, required=True, help="a raw-osm/<date>/ directory")
    p.add_argument("--into", type=Path, default=Path("tests/fixtures/osm_snapshot"))
    p.add_argument("--bbox", type=float, nargs=4, default=DEFAULT_BBOX,
                   metavar=("MINX", "MINY", "MAXX", "MAXY"))
    args = p.parse_args()

    target = args.into / args.snapshot.name
    target.mkdir(parents=True, exist_ok=True)

    osm, extent = cut_osm(args.snapshot / "osm.xml", tuple(args.bbox))
    (target / "osm.xml").write_bytes(osm)
    crashes = cut_crashes(args.snapshot / "crashes.json", tuple(args.bbox))
    (target / "crashes.json").write_bytes(crashes)
    (target / "dc_boundary.geojson").write_bytes(boundary(extent))

    print(target)
    for f in sorted(target.iterdir()):
        print(f"  {f.name:<24} {f.stat().st_size:>10,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
