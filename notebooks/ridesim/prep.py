"""RideSim DC data prep.

Builds the static files the RideSim DC page loads: a routable street graph with
Level of Traffic Stress (LTS) per edge, residents and destinations attached to
graph nodes, per-block explanations, crashes, wards, and ranked "missing link"
fixes for each rider type.

Inputs (paths relative to this repo root, override with env vars):
  RIDESIM_SNAPSHOT  OSM + DDOT basemap snapshot (Hugging Face, 2026-09-29), Parquet
  RIDESIM_OUT       ridescore pipeline output folder (road_segment, scores, crashes)
  RIDESIM_RAW       folder with census blocks + DC Open Data downloads
  RIDESIM_DEST      output folder

Run:  uv run --group notebooks python notebooks/ridesim/prep.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = Path(os.environ.get("RIDESIM_SNAPSHOT", ROOT / "../data/raw/basemap_2026-09-29.parquet"))
PIPE_OUT = Path(os.environ.get("RIDESIM_OUT", ROOT / "out"))
RAW = Path(os.environ.get("RIDESIM_RAW", ROOT / "../data/raw"))
DEST = Path(os.environ.get("RIDESIM_DEST", ROOT / "../data/out"))
DEST.mkdir(parents=True, exist_ok=True)

METRIC = "EPSG:26985"  # Maryland State Plane (metres), the usual projection for DC
RIDERS = {"kid": 1, "casual": 2, "commuter": 3}
N_FIXES = 100

# LTS source codes, also used by the page legend
SRC = ["ridescore_v1", "track_rule", "trail_rule", "osm_class_rule", "footway_rule"]
OSM_CLASS_LTS = {
    "living_street": 1, "residential": 2, "unclassified": 2,
    "tertiary": 3, "tertiary_link": 3,
    "secondary": 4, "secondary_link": 4, "primary": 4, "primary_link": 4,
    "trunk": 4, "trunk_link": 4,
}
FACILITY_LABEL = {
    "none": "No bike lane", "painted_lane": "Painted bike lane",
    "buffered_lane": "Buffered bike lane", "protected_track": "Protected bike lane",
}


def load_segments() -> gpd.GeoDataFrame:
    g = gpd.read_parquet(SNAPSHOT)
    n0 = len(g)
    # Drop what a bike may not use at all.
    g = g[~g["osm_access"].isin(["private", "no"]) & (g["osm_bicycle"] != "no")].copy()
    print(f"segments: {n0:,} in snapshot, {len(g):,} after removing private / no-bike ways")

    scores = pd.read_parquet(PIPE_OUT / "ridescore_v1_scores.parquet")[["segment_id", "lts_level", "ridescore_v1"]]
    g = g.merge(scores, left_on="dc_blockkey", right_on="segment_id", how="left")

    hw = g["osm_highway"]
    is_track = hw.eq("cycleway")
    is_trail = hw.eq("path") | (hw.eq("footway") & g["osm_bicycle"].isin(["yes", "designated", "permissive"]))
    is_footway = hw.eq("footway") & ~is_trail
    scored = g["lts_level"].notna()

    lts = pd.Series(np.nan, index=g.index)
    src = pd.Series("", index=g.index)
    lts[scored], src[scored] = g.loc[scored, "lts_level"], "ridescore_v1"
    # Known snapshot caveat: separately drawn cycle tracks copy the street beside them.
    m = is_track & scored
    lts[m], src[m] = 1, "track_rule"
    m = (is_track | is_trail) & ~scored
    lts[m], src[m] = 1, "trail_rule"
    m = is_footway
    lts[m], src[m] = 2, "footway_rule"
    m = lts.isna()
    lts[m] = hw[m].map(OSM_CLASS_LTS).fillna(2)
    src[m] = "osm_class_rule"

    g["lts"] = lts.astype(int)
    g["lts_src"] = src
    print("LTS source:\n" + g["lts_src"].value_counts().to_string())
    print("LTS level:\n" + g["lts"].value_counts().sort_index().to_string())
    return g


def build_graph(g: gpd.GeoDataFrame):
    gm = g.to_crs(METRIC)
    g["len_m"] = gm.length.round(1)
    node_ids = pd.Index(pd.unique(pd.concat([g["osm_u"], g["osm_v"]])))
    g["u"] = node_ids.get_indexer(g["osm_u"])
    g["v"] = node_ids.get_indexer(g["osm_v"])

    # Node coordinates: about half the snapshot's geometries run v -> u, so take, for each node,
    # the endpoint position shared by most of its incident segments; then orient every geometry u -> v.
    from collections import Counter
    votes = [Counter() for _ in range(len(node_ids))]
    for geom, u, v in zip(g.geometry, g["u"], g["v"]):
        c = geom.coords
        a0, a1 = (round(c[0][0], 6), round(c[0][1], 6)), (round(c[-1][0], 6), round(c[-1][1], 6))
        votes[u][a0] += 1; votes[u][a1] += 1
        votes[v][a0] += 1; votes[v][a1] += 1
    lon = np.zeros(len(node_ids)); lat = np.zeros(len(node_ids))
    for n, vt in enumerate(votes):
        (lon[n], lat[n]), _ = vt.most_common(1)[0]
    flipped = 0
    geoms = []
    for geom, u, v in zip(g.geometry, g["u"], g["v"]):
        c = list(geom.coords)
        d_start = (c[0][0] - lon[u]) ** 2 + (c[0][1] - lat[u]) ** 2
        d_end = (c[-1][0] - lon[u]) ** 2 + (c[-1][1] - lat[u]) ** 2
        if d_end < d_start:
            c.reverse(); flipped += 1
        geoms.append(LineString(c))
    g = g.set_geometry(gpd.GeoSeries(geoms, index=g.index, crs=g.crs))
    print(f"oriented geometries: {flipped:,} flipped to run u -> v")
    print(f"graph: {len(node_ids):,} nodes, {len(g):,} edges")
    return g, lon, lat


def nodes_xy(lon, lat):
    pts = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=4326).to_crs(METRIC)
    return np.c_[pts.x, pts.y]


def attach_population(lon, lat, g):
    blocks = gpd.read_file(f"zip://{RAW / 'tabblock20_dc.zip'}")
    blocks = blocks[blocks["POP20"] > 0]
    pts = gpd.GeoSeries(gpd.points_from_xy(blocks["INTPTLON20"].astype(float), blocks["INTPTLAT20"].astype(float)), crs=4326).to_crs(METRIC)
    # Snap to nodes on streets people live on: anything except trails / tracks / footways.
    street_nodes = np.unique(g.loc[~g["lts_src"].isin(["trail_rule", "track_rule", "footway_rule"]), ["u", "v"]].to_numpy())
    tree = cKDTree(nodes_xy(lon, lat)[street_nodes])
    d, i = tree.query(np.c_[pts.x, pts.y])
    pop = np.zeros(len(lon), dtype=np.int64)
    np.add.at(pop, street_nodes[i], blocks["POP20"].to_numpy())
    print(f"population: {pop.sum():,} residents on {np.count_nonzero(pop):,} nodes, median snap {np.median(d):.0f} m, p95 {np.percentile(d, 95):.0f} m")
    return pop


def load_pois(lon, lat):
    specs = [
        ("school", "schools_public.geojson", "NAME"),
        ("school", "schools_charter.geojson", "NAME"),
        ("library", "libraries.geojson", "NAME"),
        ("metro", "metro.geojson", "NAME"),
        ("rec", "rec.geojson", "NAME"),
    ]
    tree = cKDTree(nodes_xy(lon, lat))
    rows = []
    for kind, fname, col in specs:
        f = gpd.read_file(RAW / fname)
        f = f[f.geometry.notna()]
        f["geometry"] = f.geometry.representative_point()
        xy = f.to_crs(METRIC)
        d, i = tree.query(np.c_[xy.geometry.x, xy.geometry.y])
        for (_, r), dd, ii in zip(f.iterrows(), d, i):
            rows.append({"t": kind, "n": str(r[col]).title() if kind != "metro" else str(r[col]),
                         "x": round(r.geometry.x, 5), "y": round(r.geometry.y, 5), "node": int(ii), "d": round(float(dd))})
    df = pd.DataFrame(rows).drop_duplicates(["t", "n", "node"])
    far = df[df["d"] > 150]
    print(f"POIs: {len(df):,} ({df['t'].value_counts().to_dict()}), {len(far)} snap farther than 150 m")
    return df


def node_wards(lon, lat):
    wards = gpd.read_file(RAW / "wards.geojson")[["WARD", "geometry"]]
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lon, lat), crs=4326)
    j = gpd.sjoin(pts, wards.to_crs(4326), how="left", predicate="within")
    j = j[~j.index.duplicated()]
    w = j["WARD"].fillna(0).astype(int).to_numpy()
    return w, wards


class DSU:
    def __init__(self, n, weight):
        self.p = np.arange(n)
        self.w = weight.astype(np.int64).copy()

    def find(self, a):
        p = self.p
        root = a
        while p[root] != root:
            root = p[root]
        while p[a] != root:
            p[a], a = root, p[a]
        return root

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b:
            return
        if self.w[a] < self.w[b]:
            a, b = b, a
        self.p[b] = a
        self.w[a] += self.w[b]


def rank_fixes(g, pop, threshold):
    """Greedy: repeatedly pick the single over-threshold edge that joins the most residents
    (the smaller of the two islands it connects) to a larger island."""
    u, v, lts = g["u"].to_numpy(), g["v"].to_numpy(), g["lts"].to_numpy()
    dsu = DSU(len(pop), pop)
    for a, b in zip(u[lts <= threshold], v[lts <= threshold]):
        dsu.union(a, b)
    total = pop.sum()
    largest0 = max(dsu.w[dsu.find(i)] for i in range(len(pop)))
    cand = np.flatnonzero(lts > threshold)
    fixes = []
    for _ in range(N_FIXES):
        best, best_gain = -1, 0
        for e in cand:
            ra, rb = dsu.find(u[e]), dsu.find(v[e])
            if ra == rb:
                continue
            gain = min(dsu.w[ra], dsu.w[rb])
            if gain > best_gain:
                best, best_gain = e, gain
        if best < 0:
            break
        fixes.append({"e": int(best), "gain": int(best_gain)})
        dsu.union(u[best], v[best])
    print(f"  threshold {threshold}: largest island {largest0 / total:.1%} of residents; top fix +{fixes[0]['gain']:,}" if fixes else "  no fixes")
    return fixes, largest0


def main():
    g = load_segments()
    g, lon, lat = build_graph(g)
    pop = attach_population(lon, lat, g)
    pois = load_pois(lon, lat)
    ward, wards = node_wards(lon, lat)

    # Per-block explanation table (pipeline facts + score components), indexed for the page.
    rs = gpd.read_parquet(PIPE_OUT / "road_segment.parquet").drop(columns="geometry")
    sc = pd.read_parquet(PIPE_OUT / "ridescore_v1_scores.parquet")
    blocks = rs.merge(sc, on="segment_id")
    used = pd.Index(pd.unique(g["segment_id"].dropna()))
    blocks = blocks[blocks["segment_id"].isin(used)].reset_index(drop=True)
    block_idx = pd.Series(np.arange(len(blocks)), index=blocks["segment_id"])
    g["b"] = g["segment_id"].map(block_idx).fillna(-1).astype(int)

    names = pd.Index(pd.unique(g["osm_name"].fillna(g["dc_ROUTENAME"]).fillna("").astype(str)))
    g["nm"] = names.get_indexer(g["osm_name"].fillna(g["dc_ROUTENAME"]).fillna("").astype(str))

    # Edges: [u, v, len_m, lts, src, name, block, flat coords]
    edges = []
    for r in g.itertuples():
        coords = np.round(np.asarray(r.geometry.coords), 5).ravel().tolist()
        edges.append([int(r.u), int(r.v), float(r.len_m), int(r.lts), SRC.index(r.lts_src), int(r.nm), int(r.b), coords])

    network = {
        "nodes": {"lon": np.round(lon, 5).tolist(), "lat": np.round(lat, 5).tolist(),
                  "pop": pop.tolist(), "ward": ward.tolist()},
        "edges": edges, "names": names.tolist(), "src": SRC,
    }
    (DEST / "network.json").write_text(json.dumps(network, separators=(",", ":")))

    keep = ["segment_id", "route_name", "function", "num_lanes", "num_lanes_raw", "speed_limit", "speed_limit_raw",
            "bike_facility_type", "parking_presence", "slow_street", "crash_count_5yr", "serious_injury_count_5yr",
            "fatal_count_5yr", "lts_level", "ridescore_v1"]
    b = blocks[keep].copy()
    b["speed_filled"] = b["speed_limit_raw"].isna()
    b = b.drop(columns=["speed_limit_raw", "num_lanes_raw"])
    b["bike_facility_type"] = b["bike_facility_type"].map(FACILITY_LABEL).fillna("No bike lane")
    b = b.replace({np.nan: None})
    (DEST / "blocks.json").write_text(json.dumps({"cols": list(b.columns), "rows": b.to_numpy().tolist()}, separators=(",", ":"), default=lambda o: o.item() if hasattr(o, "item") else str(o)))

    (DEST / "pois.json").write_text(pois.to_json(orient="records"))

    cr = gpd.read_parquet(PIPE_OUT / "crashes.parquet").to_crs(4326)
    sev = np.where(cr["fatal_bicyclist"].fillna(0) > 0, 2, np.where(cr["major_injuries_bicyclist"].fillna(0) > 0, 1, 0))
    yr = pd.to_datetime(cr["report_date"]).dt.year.fillna(0).astype(int)
    crashes = [[round(p.x, 5), round(p.y, 5), int(s), int(y)] for p, s, y in zip(cr.geometry, sev, yr) if p is not None]
    (DEST / "crashes.json").write_text(json.dumps(crashes, separators=(",", ":")))

    wards.to_crs(4326).assign(geometry=lambda d: d.geometry.simplify(0.0003)).to_file(DEST / "wards.geojson", driver="GeoJSON")

    print("fixes:")
    fixes, largest = {}, {}
    for rider, t in RIDERS.items():
        fixes[rider], largest[rider] = rank_fixes(g, pop, t)
    (DEST / "fixes.json").write_text(json.dumps(fixes, separators=(",", ":")))

    meta = {
        "snapshot": SNAPSHOT.name, "pipeline_run": json.loads((PIPE_OUT / "run.json").read_text()),
        "population_source": "2020 Decennial Census blocks (TIGER/Line tabblock20, POP20)",
        "residents": int(pop.sum()), "edges": len(edges), "nodes": len(lon),
        "riders": RIDERS, "largest_island_share": {k: round(v / pop.sum(), 4) for k, v in largest.items()},
        "lts_source_counts": g["lts_src"].value_counts().to_dict(),
    }
    (DEST / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    for f in sorted(DEST.iterdir()):
        print(f"  {f.name:16s} {f.stat().st_size / 1e6:6.2f} MB")


if __name__ == "__main__":
    main()
