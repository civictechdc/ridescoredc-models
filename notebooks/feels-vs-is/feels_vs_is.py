"""Feels vs. Is: a two-axis bike safety model for DC streets.

Stage functions, called in order by feels_vs_is.ipynb. Each takes and returns
plain (Geo)DataFrames so the notebook can show a checkpoint between them.

Feels  = comfort, a Level of Traffic Stress read of the street's design.
Is     = harm, an Empirical Bayes crash rate from five years of bicyclist
         injury crashes, on DDOT blocks and on intersection clusters.
Gap    = where the two disagree.
"""

from __future__ import annotations

import json
import math
import pathlib
import re
import time
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point

HERE = pathlib.Path(__file__).resolve().parent
CACHE = HERE / "cache"
SNAPSHOT = pathlib.Path("~/ridescore-data/ridescore_dc_basemap_2026-09-29.parquet").expanduser()
SNAPSHOT_DATE = "2026-09-29"
METRIC_CRS = "EPSG:26985"
CRASH_START = pd.Timestamp("2021-10-01", tz="UTC")
TEST_START = pd.Timestamp("2025-01-01", tz="UTC")

CYCLEWAY_COLS = ["osm_cycleway", "osm_cycleway_left", "osm_cycleway_right", "osm_cycleway_both"]
BUFFER_COLS = [
    "osm_cycleway_buffer",
    "osm_cycleway_left_buffer",
    "osm_cycleway_right_buffer",
    "osm_cycleway_both_buffer",
]
FACILITY_ORDER = ["separated", "protected", "buffered", "painted", "sharrow", "none"]
FUNC_CLASS = {
    11.0: "Interstate",
    12.0: "Freeway",
    14.0: "Principal Arterial",
    16.0: "Minor Arterial",
    17.0: "Collector",
    18.0: "Collector",
    19.0: "Local",
}
OSM_FUNC_FALLBACK = {
    "motorway": "Interstate",
    "motorway_link": "Interstate",
    "trunk": "Principal Arterial",
    "trunk_link": "Principal Arterial",
    "primary": "Principal Arterial",
    "primary_link": "Principal Arterial",
    "secondary": "Minor Arterial",
    "secondary_link": "Minor Arterial",
    "tertiary": "Collector",
    "tertiary_link": "Collector",
    "cycleway": "Off-street",
    "path": "Off-street",
    "footway": "Off-street",
    "pedestrian": "Off-street",
}
OFF_STREET = {"cycleway", "path", "footway", "pedestrian"}


# ---------------------------------------------------------------- Stage 0: load
def load_snapshot(path: pathlib.Path = SNAPSHOT) -> gpd.GeoDataFrame:
    g = gpd.read_parquet(path)
    g = g.reset_index(drop=True)
    g["seg_id"] = np.arange(len(g))
    return g


def _present(s: pd.Series) -> pd.Series:
    """DDOT facility columns hold IB, OB or BD when the facility exists."""
    return s.notna() & (s.astype(str).str.strip() != "")


def _any_eq(g: pd.DataFrame, cols: list[str], values: set[str]) -> pd.Series:
    out = pd.Series(False, index=g.index)
    for c in cols:
        if c in g:
            out |= g[c].isin(values)
    return out


def street_name(g: pd.DataFrame) -> pd.Series:
    osm = g["osm_name"].where(g["osm_name"].notna() & (g["osm_name"].astype(str) != ""))
    dc = g["dc_ROUTENAME"].astype(str).str.title().str.replace(r"\b(Nw|Ne|Sw|Se)$", lambda m: m.group(1).upper(), regex=True)
    dc = dc.str.replace(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), regex=True)
    dc = dc.where(g["dc_ROUTENAME"].notna())
    return osm.fillna(dc).fillna(g["osm_highway"].astype(str).str.replace("_", " "))


# --------------------------------------------------------------- Stage 1: clean
def _parse_num(s: pd.Series) -> pd.Series:
    """'25 mph' -> 25, '2' -> 2, '2;3' -> 2."""
    txt = s.astype(str).str.extract(r"(\d+(?:\.\d+)?)")[0]
    return pd.to_numeric(txt, errors="coerce")


def _fill_by_class(value: pd.Series, cls: pd.Series, matched: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Fill gaps with the median of matched rows in the same osm_highway class."""
    med = value[matched & value.notna()].groupby(cls[matched & value.notna()]).median()
    overall = value[matched].median()
    fill = cls.map(med).fillna(overall)
    src = pd.Series(np.where(value.notna(), "data", "class_median"), index=value.index)
    return value.fillna(fill), src


def clean(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """One value per field per segment, with its source."""
    out = g[["seg_id", "osm_u", "osm_v", "osm_key", "osm_highway", "osm_oneway", "dc_blockkey",
             "dc_ROADTYPE", "match_status", "geometry"]].copy()
    out["name"] = street_name(g)
    out["snapshot_date"] = SNAPSHOT_DATE
    matched = g["match_status"] != "none"
    cls = g["osm_highway"].astype(str)
    off_street = g["osm_highway"].isin(OFF_STREET)

    # speed
    dc_speed = pd.to_numeric(g["dc_SPEEDLIMITS_OB"], errors="coerce").where(lambda s: s > 1)
    osm_speed = _parse_num(g["osm_maxspeed"])
    speed = dc_speed.fillna(osm_speed)
    speed_src = pd.Series(np.select([dc_speed.notna(), osm_speed.notna()], ["ddot", "osm"], "class_median"), index=g.index)
    speed, _ = _fill_by_class(speed, cls, matched)
    out["speed_mph"] = speed.round().astype(int)
    out["speed_src"] = speed_src

    # lanes
    dc_lanes = pd.to_numeric(g["dc_TOTALTRAVELLANES"], errors="coerce").where(lambda s: s > 0)
    osm_lanes = _parse_num(g["osm_lanes"])
    lanes = dc_lanes.fillna(osm_lanes)
    lanes_src = pd.Series(np.select([dc_lanes.notna(), osm_lanes.notna()], ["ddot", "osm"], "class_median"), index=g.index)
    lanes, _ = _fill_by_class(lanes, cls, matched)
    out["lanes"] = lanes.round().clip(lower=1).astype(int)
    out["lanes_src"] = lanes_src
    oneway = g["osm_oneway"].fillna(False).astype(bool)
    out["lanes_per_dir"] = np.where(oneway, out["lanes"], np.ceil(out["lanes"] / 2)).astype(int)

    # volume
    aadt = pd.to_numeric(g["dc_AADT"], errors="coerce")
    out["aadt_src"] = np.where(aadt.notna(), "ddot_2020", "class_median")
    aadt, _ = _fill_by_class(aadt, cls, matched)
    out["aadt"] = aadt
    out["aadt_pct"] = aadt.rank(pct=True)

    su = pd.to_numeric(g["dc_AADT_SINGLE_UNIT"], errors="coerce")
    comb = pd.to_numeric(g["dc_AADT_COMBINATION"], errors="coerce")
    raw_aadt = pd.to_numeric(g["dc_AADT"], errors="coerce")
    truck = ((su + comb) / raw_aadt).where(raw_aadt > 0)
    truck, _ = _fill_by_class(truck, cls, matched)
    out["truck_share"] = truck.clip(0, 1)
    out["truck_pct"] = out["truck_share"].rank(pct=True)

    # function
    fc = g["dc_DCFUNCTIONALCLASS"].map(FUNC_CLASS)
    out["func_class"] = fc.fillna(cls.map(OSM_FUNC_FALLBACK)).fillna("Local")

    # facility tiers, most protective wins
    footway_bike = (g["osm_highway"] == "footway") & g["osm_bicycle"].isin(["designated", "yes"])
    separated = g["osm_highway"].isin(["cycleway", "path"]) | footway_bike
    protected = _present(g["dc_BIKELANE_PROTECTED"]) | _present(g["dc_BIKELANE_DUAL_PROTECTED"]) | _any_eq(g, CYCLEWAY_COLS, {"track"})
    has_lane = _any_eq(g, CYCLEWAY_COLS, {"lane", "opposite_lane"})
    buffered = _present(g["dc_BIKELANE_BUFFERED"]) | _present(g["dc_BIKELANE_DUAL_BUFFERED"]) | (has_lane & _any_eq(g, BUFFER_COLS, {"yes"})) | _any_eq(g, CYCLEWAY_COLS, {"buffered_lane"})
    painted = _present(g["dc_BIKELANE_CONVENTIONAL"]) | _present(g["dc_BIKELANE_CONTRAFLOW"]) | has_lane
    sharrow = _any_eq(g, CYCLEWAY_COLS, {"shared_lane", "share_busway"})
    facility = pd.Series(np.select([separated, protected, buffered, painted, sharrow],
                                   ["separated", "protected", "buffered", "painted", "sharrow"], "none"), index=g.index)
    src_dc = _present(g["dc_BIKELANE_PROTECTED"]) | _present(g["dc_BIKELANE_DUAL_PROTECTED"]) | _present(g["dc_BIKELANE_BUFFERED"]) | _present(g["dc_BIKELANE_DUAL_BUFFERED"]) | _present(g["dc_BIKELANE_CONVENTIONAL"]) | _present(g["dc_BIKELANE_CONTRAFLOW"])
    facility_src = pd.Series(np.select([separated, src_dc, facility != "none"], ["osm_highway", "ddot", "osm_tag"], "none"), index=g.index)

    # a street whose bike facility is mapped as its own cycleway row
    parallel_track = (~separated) & _any_eq(g, CYCLEWAY_COLS, {"separate"})
    facility = facility.where(~parallel_track, "none")
    facility_src = facility_src.where(~parallel_track, "parallel_track")
    out["facility"] = facility
    out["facility_src"] = facility_src
    out["parallel_track"] = parallel_track
    out["bus_shared"] = _any_eq(g, CYCLEWAY_COLS, {"share_busway"})
    out["door_zone"] = facility.isin(["painted", "buffered"]) & _present(g["dc_BIKELANE_PARKINGLANE_ADJACENT"])

    nb = pd.to_numeric(g["dc_TOTALBIKELANES"], errors="coerce")
    out["bike_width_ft"] = (pd.to_numeric(g["dc_TOTALBIKELANEWIDTH"], errors="coerce") / nb).where(nb > 0)
    npk = pd.to_numeric(g["dc_TOTALPARKINGLANES"], errors="coerce")
    out["parking_width_ft"] = (pd.to_numeric(g["dc_TOTALPARKINGLANEWIDTH"], errors="coerce") / npk).where(npk > 0)

    out["centerline"] = g["dc_DOUBLEYELLOW_LINE"].astype(str).str.lower().eq("yes")
    out["poor_pavement"] = g["dc_PCI_CONDCATEGORY"].isin(["Poor", "Very Poor"])
    out["calmed"] = g["dc_VERTICAL_DEFLECTION"].astype(str).str.upper().eq("YES")
    out["off_street"] = off_street
    # separated rows copied the adjacent street's traffic attributes; keep them for crossings
    out["street_speed_mph"] = out["speed_mph"]
    out["street_lanes"] = out["lanes"]

    out["length_m"] = out.geometry.to_crs(METRIC_CRS).length
    imputed = (out["speed_src"] == "class_median").astype(int) + (out["lanes_src"] == "class_median").astype(int)
    out["confidence"] = np.select(
        [(g["match_status"] == "good") & (imputed == 0), (g["match_status"] != "none") & (imputed <= 1)],
        ["high", "medium"], "low")
    return out


# -------------------------------------------------------------- Stage 2: feels
def comfort_level(r) -> int:
    """Furth 2012 LTS with Montgomery County amendments. See SPEC.md Stage 2."""
    f, v, lpd = r.facility, r.speed_mph, r.lanes_per_dir
    if f == "separated":
        return 1
    if f == "protected":
        return 1 if v <= 35 else 2
    if f in ("painted", "buffered"):
        if v >= 40:
            return 4
        if r.door_zone:
            reach = (r.bike_width_ft if pd.notna(r.bike_width_ft) else 5.0) + (r.parking_width_ft if pd.notna(r.parking_width_ft) else 8.0)
            if v >= 35 or reach < 14:
                return 3
            if v >= 30 or lpd >= 2 or reach < 15:
                return 2
            return 1
        width = 6.0 if f == "buffered" else (r.bike_width_ft if pd.notna(r.bike_width_ft) else 5.0)
        if v >= 35 or lpd >= 3:
            return 3
        if width < 6 or lpd >= 2:
            return 2
        return 1
    # sharrow or none: mixed traffic on total through lanes
    lanes = r.lanes
    quiet = (not r.centerline) and r.aadt < 3000
    if v >= 35:
        return 4
    if lanes >= 6:
        return 4
    if lanes >= 4:
        return 3 if v <= 25 else 4
    if v <= 25:
        return 1 if quiet else 2
    return 2 if quiet else 3


BANDS = {1: (80, 100), 2: (60, 80), 3: (30, 60), 4: (0, 30)}


def feels(c: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = c.copy()
    out["comfort_lts"] = out.apply(comfort_level, axis=1).astype(int)
    traffic = ~out["facility"].eq("separated")
    p = (0.4 * out["aadt_pct"] * traffic + 0.2 * out["truck_pct"] * traffic + 0.2 * out["door_zone"]
         + 0.2 * out["poor_pavement"] - 0.2 * out["calmed"]).clip(0, 1)
    lo = out["comfort_lts"].map(lambda k: BANDS[k][0])
    hi = out["comfort_lts"].map(lambda k: BANDS[k][1])
    out["comfort_score"] = (hi - p * (hi - lo)).round(1)
    out["kid_ok"] = out["comfort_lts"] == 1
    return out


def lts_v1(g: gpd.GeoDataFrame) -> pd.Series:
    """The repository's LTS v1, on matched rows only."""
    from ridescore.models.ridescore_v1 import lts
    from ridescore.network import normalise

    def one(row):
        t = {k[3:]: v for k, v in row.items() if k.startswith("dc_")}
        return lts.lts_level(
            normalise.classify_facility(t),
            normalise.speed_limit(t.get("SPEEDLIMITS_OB")),
            normalise.num_lanes(t.get("TOTALTRAVELLANES")),
            normalise.name_function(t.get("DCFUNCTIONALCLASS")),
        )

    matched = g["match_status"] != "none"
    vals = pd.Series(np.nan, index=g.index)
    vals[matched] = g[matched].drop(columns="geometry").apply(one, axis=1)
    return vals.astype("Int64")


# ------------------------------------------------- Stage 3: intersections, crashes
def nodes_and_degree(c: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """One row per node with its degree on the undirected simple graph."""
    coords = c.geometry.apply(lambda ln: ln.coords[0])
    coords_v = c.geometry.apply(lambda ln: ln.coords[-1])
    pts = pd.concat([
        pd.DataFrame({"node": c["osm_u"].values, "xy": coords.values}),
        pd.DataFrame({"node": c["osm_v"].values, "xy": coords_v.values}),
    ]).drop_duplicates("node")
    pairs = pd.DataFrame({"a": np.minimum(c["osm_u"], c["osm_v"]), "b": np.maximum(c["osm_u"], c["osm_v"])}).drop_duplicates()
    deg = pd.concat([pairs["a"], pairs["b"]]).value_counts()
    nodes = gpd.GeoDataFrame(
        {"node": pts["node"].values, "degree": pts["node"].map(deg).fillna(0).astype(int).values},
        geometry=[Point(xy) for xy in pts["xy"]], crs=c.crs,
    )
    return nodes


def intersections(c: gpd.GeoDataFrame, eps_m: float = 15.0) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Cluster degree >= 3 nodes within eps_m. Returns (clusters, approaches, node->cluster map)."""
    from sklearn.cluster import DBSCAN

    nodes = nodes_and_degree(c)
    junction = nodes[nodes["degree"] >= 3].to_crs(METRIC_CRS).copy()
    xy = np.c_[junction.geometry.x, junction.geometry.y]
    junction["int_id"] = DBSCAN(eps=eps_m, min_samples=1).fit_predict(xy)
    cent = junction.groupby("int_id").agg(x=("geometry", lambda s: s.x.mean()), y=("geometry", lambda s: s.y.mean()), n_nodes=("node", "size"))
    clusters = gpd.GeoDataFrame(cent[["n_nodes"]], geometry=gpd.points_from_xy(cent.x, cent.y), crs=METRIC_CRS).reset_index()
    node_map = junction[["node", "int_id"]].reset_index(drop=True)
    # approaches: segments touching any node of the cluster
    seg_nodes = pd.concat([
        c[["seg_id", "osm_u"]].rename(columns={"osm_u": "node"}),
        c[["seg_id", "osm_v"]].rename(columns={"osm_v": "node"}),
    ])
    approaches = seg_nodes.merge(node_map, on="node")[["seg_id", "int_id"]].drop_duplicates()
    clusters = clusters.merge(approaches.groupby("int_id").size().rename("n_approaches").reset_index(), on="int_id", how="left")
    clusters["n_approaches"] = clusters["n_approaches"].fillna(0).astype(int)
    return clusters, approaches, node_map


CRASH_URL = "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Public_Safety_WebMercator/MapServer/24/query"
CRASH_WHERE = (
    "REPORTDATE >= DATE '2021-10-01 00:00:00' AND (MAJORINJURIES_BICYCLIST > 0 OR MINORINJURIES_BICYCLIST > 0 "
    "OR UNKNOWNINJURIES_BICYCLIST > 0 OR FATAL_BICYCLIST > 0)"
)
CRASH_FIELDS = (
    "OBJECTID,CRIMEID,REPORTDATE,BLOCKKEY,SUBBLOCKKEY,OFFINTERSECTION,NEARESTINTKEY,LATITUDE,LONGITUDE,"
    "FATAL_BICYCLIST,MAJORINJURIES_BICYCLIST,MINORINJURIES_BICYCLIST,UNKNOWNINJURIES_BICYCLIST,TOTAL_VEHICLES,SPEEDING_INVOLVED"
)


def fetch_crashes(refresh: bool = False) -> gpd.GeoDataFrame:
    """Five years of bicyclist injury crashes from DC GIS, cached in cache/crashes.parquet."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / "crashes.parquet"
    if path.exists() and not refresh:
        df = pd.read_parquet(path)
    else:
        rows, offset = [], 0
        while True:
            r = requests.get(CRASH_URL, params={
                "where": CRASH_WHERE, "outFields": CRASH_FIELDS, "returnGeometry": "false",
                "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": 1000, "f": "json",
            }, timeout=120)
            r.raise_for_status()
            page = [f["attributes"] for f in r.json().get("features", [])]
            rows += page
            if len(page) < 1000:
                break
            offset += 1000
            time.sleep(0.1)
        df = pd.DataFrame(rows)
        df.to_parquet(path, index=False)
    df["date"] = pd.to_datetime(df["REPORTDATE"], unit="ms", utc=True)
    df["ksi"] = (df["FATAL_BICYCLIST"] > 0) | (df["MAJORINJURIES_BICYCLIST"] > 0)
    df["fatal"] = df["FATAL_BICYCLIST"] > 0
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["LONGITUDE"], df["LATITUDE"]), crs="EPSG:4326")


def assign_crashes(crashes: gpd.GeoDataFrame, c: gpd.GeoDataFrame, clusters: gpd.GeoDataFrame,
                   int_radius_m: float = 25.0, seg_radius_m: float = 40.0,
                   dc_off_m: float = 20.0, loose_radius_m: float = 45.0) -> gpd.GeoDataFrame:
    """Each crash goes to an intersection cluster, a DDOT block, a segment, or nowhere."""
    cr = crashes.to_crs(METRIC_CRS).copy()
    cr["int_id"] = pd.NA
    cr["unit"] = pd.NA
    cr["path"] = "unmatched"

    near_int = gpd.sjoin_nearest(cr[["geometry"]], clusters[["int_id", "geometry"]], how="left",
                                 max_distance=loose_radius_m, distance_col="d_int")
    near_int = near_int[~near_int.index.duplicated()]
    off = pd.to_numeric(cr["OFFINTERSECTION"], errors="coerce")
    # DC records each crash's distance from the nearest intersection. Trust it when it is
    # small and a cluster is nearby; otherwise require the crash to sit on the cluster.
    hit = near_int["int_id"].notna() & (
        (near_int["d_int"] <= int_radius_m) | ((off > 0) & (off <= dc_off_m))
    )
    cr.loc[hit, "int_id"] = near_int.loc[hit, "int_id"].astype(int).values
    cr.loc[hit, "path"] = "intersection"

    # unit ids: DDOT block key, else the segment itself
    units = c[["seg_id", "dc_blockkey"]].copy()
    units["unit"] = units["dc_blockkey"].fillna("seg:" + units["seg_id"].astype(str))
    block_units = set(units.loc[units["dc_blockkey"].notna(), "dc_blockkey"])
    rest = cr["path"] == "unmatched"
    bk = cr["BLOCKKEY"].where(cr["BLOCKKEY"].isin(block_units))
    cr.loc[rest & bk.notna(), "unit"] = bk[rest & bk.notna()]
    cr.loc[rest & bk.notna(), "path"] = "blockkey"

    rest = cr["path"] == "unmatched"
    segs = c[["seg_id", "geometry"]].to_crs(METRIC_CRS)
    near_seg = gpd.sjoin_nearest(cr.loc[rest, ["geometry"]], segs, how="left", max_distance=seg_radius_m, distance_col="d_seg")
    near_seg = near_seg[~near_seg.index.duplicated()]
    hit = near_seg["seg_id"].notna()
    seg_unit = units.set_index("seg_id")["unit"]
    cr.loc[near_seg.index[hit], "unit"] = near_seg.loc[hit, "seg_id"].astype(int).map(seg_unit).values
    cr.loc[near_seg.index[hit], "path"] = "nearest_segment"
    return cr.to_crs("EPSG:4326")


# ------------------------------------------------------- Stage 4: harm, with EB
def _speed_bucket(v: pd.Series) -> pd.Series:
    return pd.cut(v, [-1, 20, 25, 30, 1000], labels=["le20", "25", "30", "35plus"]).astype(str)


def _lanes_bucket(n: pd.Series) -> pd.Series:
    return pd.cut(n, [0, 2, 4, 1000], labels=["1-2", "3-4", "5plus"]).astype(str)


def period_years(crashes: pd.DataFrame, start=CRASH_START, end=None) -> float:
    end = end or crashes["date"].max()
    return (end - start).days / 365.25


def block_units(f: gpd.GeoDataFrame, approaches: pd.DataFrame) -> pd.DataFrame:
    """Design features per unit: a DDOT block, or a lone segment without one."""
    s = f.copy()
    s["unit"] = s["dc_blockkey"].fillna("seg:" + s["seg_id"].astype(str))
    street = ~s["off_street"]
    s["street_len"] = s["length_m"].where(street, 0.0)
    fac_rank = s["facility"].map({k: i for i, k in enumerate(FACILITY_ORDER)})
    s["fac_rank"] = fac_rank.where(street, len(FACILITY_ORDER))
    n_int = approaches.merge(s[["seg_id", "unit"]], on="seg_id").groupby("unit")["int_id"].nunique()
    u = s.groupby("unit").agg(
        length_m=("street_len", "sum"),
        any_len=("length_m", "sum"),
        fac_rank=("fac_rank", "min"),
        speed_mph=("speed_mph", "max"),
        lanes=("lanes", "max"),
        aadt_pct=("aadt_pct", "mean"),
        parallel_track=("parallel_track", "any"),
        func_rank=("func_class", lambda x: x.map({"Interstate": 0, "Freeway": 1, "Principal Arterial": 2, "Minor Arterial": 3, "Collector": 4, "Local": 5, "Off-street": 6}).min()),
        n_segments=("seg_id", "size"),
        name=("name", lambda x: x.mode().iloc[0] if len(x.mode()) else x.iloc[0]),
    )
    u["length_m"] = u["length_m"].where(u["length_m"] > 0, u["any_len"])
    u["length_km"] = (u["length_m"] / 1000).clip(lower=0.005)
    u["facility"] = u["fac_rank"].map(dict(enumerate(FACILITY_ORDER))).fillna("separated")
    u["func_class"] = u["func_rank"].map({0: "Interstate", 1: "Freeway", 2: "Principal Arterial", 3: "Minor Arterial", 4: "Collector", 5: "Local", 6: "Off-street"})
    u["func_class"] = u["func_class"].replace({"Interstate": "Freeway"})
    u["speed_bucket"] = _speed_bucket(u["speed_mph"])
    u["lanes_bucket"] = _lanes_bucket(u["lanes"])
    u["crossings"] = n_int.reindex(u.index).fillna(0).astype(int)
    u["crossings_per_km"] = u["crossings"] / u["length_km"]
    return u.drop(columns=["fac_rank", "func_rank", "any_len"])


def intersection_units(clusters: gpd.GeoDataFrame, approaches: pd.DataFrame, f: gpd.GeoDataFrame) -> pd.DataFrame:
    a = approaches.merge(f[["seg_id", "func_class", "speed_mph", "lanes", "facility", "name", "comfort_score", "comfort_lts"]], on="seg_id")
    rank = {"Interstate": 0, "Freeway": 1, "Principal Arterial": 2, "Minor Arterial": 3, "Collector": 4, "Local": 5, "Off-street": 6}
    a["func_rank"] = a["func_class"].map(rank)
    a["wide"] = a["lanes"] >= 4
    a["sep"] = a["facility"].isin(["separated", "protected"])
    u = a.groupby("int_id").agg(
        n_approaches=("seg_id", "size"),
        func_rank=("func_rank", "min"),
        speed_mph=("speed_mph", "max"),
        wide_approaches=("wide", "sum"),
        any_separated=("sep", "any"),
        min_comfort=("comfort_score", "min"),
        max_lts=("comfort_lts", "max"),
        names=("name", lambda x: " & ".join(pd.Series(x).dropna().astype(str).drop_duplicates().head(2))),
    )
    u["func_class"] = u["func_rank"].map({v: k for k, v in rank.items()}).replace({"Interstate": "Freeway"})
    u["approach_bucket"] = pd.cut(u["n_approaches"], [0, 3, 4, 1000], labels=["3", "4", "5plus"]).astype(str)
    u["speed_bucket"] = _speed_bucket(u["speed_mph"])
    u["wide_bucket"] = pd.cut(u["wide_approaches"], [-1, 0, 1, 1000], labels=["0", "1", "2plus"]).astype(str)
    return u.join(clusters.set_index("int_id")[["geometry"]]).drop(columns=["func_rank"])


def fit_nb(y: pd.Series, X: pd.DataFrame, offset: pd.Series | None = None) -> tuple[np.ndarray, float, str]:
    """Negative binomial GLM; returns (mu, alpha, method). Poisson + method of moments if NB fails."""
    import statsmodels.api as sm

    Xc = sm.add_constant(X.astype(float), has_constant="add")
    off = None if offset is None else np.asarray(offset, dtype=float)
    try:
        import warnings

        model = sm.NegativeBinomial(y.values.astype(float), Xc.values, offset=off)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            start = model.fit(disp=0, maxiter=3000, method="nm").params
            res = model.fit(start_params=start, disp=0, maxiter=500, method="bfgs")
        alpha = float(res.params[-1])
        mu = res.predict(Xc.values, offset=off)
        if not np.isfinite(alpha) or alpha <= 0 or not np.all(np.isfinite(mu)):
            raise ValueError("bad NB fit")
        return np.asarray(mu), alpha, "negative_binomial"
    except Exception:  # noqa: BLE001
        res = sm.GLM(y.values.astype(float), Xc.values, family=sm.families.Poisson(), offset=off).fit()
        mu = np.asarray(res.predict(Xc.values, offset=off))
        alpha = max(float(((y.values - mu) ** 2 - mu).sum() / (mu**2).sum()), 1e-3)
        return mu, alpha, "poisson_mom"


def _design(u: pd.DataFrame, cols: list[str], numeric: list[str] = ()) -> pd.DataFrame:
    X = pd.get_dummies(u[cols].astype(str), drop_first=True).astype(float)
    for n in numeric:
        X[n] = u[n].astype(float).fillna(u[n].median())
    return X


def harm(f: gpd.GeoDataFrame, clusters: gpd.GeoDataFrame, approaches: pd.DataFrame, crashes: gpd.GeoDataFrame,
         years: float | None = None, history: gpd.GeoDataFrame | None = None) -> dict:
    """Fit the block and intersection models and return EB rates per unit.

    `crashes` fits the design model; `history` (default: the same crashes) is what the EB
    update is allowed to see. For validation the two differ.
    """
    years = years or period_years(crashes)
    history = crashes if history is None else history
    bu = block_units(f, approaches)
    iu = intersection_units(clusters, approaches, f)

    by_unit = crashes[crashes["path"].isin(["blockkey", "nearest_segment"])].groupby("unit")
    bu["crashes_fit"] = by_unit.size().reindex(bu.index).fillna(0).astype(int)
    hist_unit = history[history["path"].isin(["blockkey", "nearest_segment"])].groupby("unit")
    bu["crashes"] = hist_unit.size().reindex(bu.index).fillna(0).astype(int)
    bu["ksi"] = hist_unit["ksi"].sum().reindex(bu.index).fillna(0).astype(int)
    Xb = _design(bu, ["func_class", "facility", "speed_bucket", "lanes_bucket"], ["aadt_pct"])
    Xb["parallel_track"] = bu["parallel_track"].astype(float)
    mu_b, alpha_b, method_b = fit_nb(bu["crashes_fit"], Xb, offset=np.log(bu["length_km"]))
    bu["mu"] = mu_b
    w = 1 / (1 + alpha_b * bu["mu"])
    bu["eb"] = w * bu["mu"] + (1 - w) * bu["crashes"]
    bu["eb_per_km_yr"] = bu["eb"] / (bu["length_km"] * years)
    bu["mu_per_km_yr"] = bu["mu"] / (bu["length_km"] * years)

    by_int = crashes[crashes["path"] == "intersection"].groupby("int_id")
    iu["crashes_fit"] = by_int.size().reindex(iu.index).fillna(0).astype(int)
    hist_int = history[history["path"] == "intersection"].groupby("int_id")
    iu["crashes"] = hist_int.size().reindex(iu.index).fillna(0).astype(int)
    iu["ksi"] = hist_int["ksi"].sum().reindex(iu.index).fillna(0).astype(int)
    Xi = _design(iu, ["approach_bucket", "func_class", "speed_bucket", "wide_bucket"])
    Xi["any_separated"] = iu["any_separated"].astype(float)
    mu_i, alpha_i, method_i = fit_nb(iu["crashes_fit"], Xi)
    iu["mu"] = mu_i
    w = 1 / (1 + alpha_i * iu["mu"])
    iu["eb"] = w * iu["mu"] + (1 - w) * iu["crashes"]
    iu["eb_per_yr"] = iu["eb"] / years
    iu["mu_per_yr"] = iu["mu"] / years
    return {"blocks": bu, "intersections": iu, "years": years,
            "alpha_block": alpha_b, "alpha_int": alpha_i, "method_block": method_b, "method_int": method_i}


def weighted_pct(values: pd.Series, weights: pd.Series) -> pd.Series:
    """Length-weighted percentile rank in [0, 1]. Ties take the middle of their group."""
    order = np.argsort(values.values, kind="mergesort")
    v = values.values[order]
    w = weights.values[order].astype(float)
    cum_hi = np.cumsum(w) / w.sum()
    cum_lo = cum_hi - w / w.sum()
    grp = pd.Series(v)
    hi = pd.Series(cum_hi).groupby(grp).transform("max").values
    lo = pd.Series(cum_lo).groupby(grp).transform("min").values
    out = np.empty(len(values))
    out[order] = (hi + lo) / 2
    return pd.Series(out, index=values.index)


def death_risk_curve() -> tuple[float, float]:
    """Logistic fit to AAA Foundation pedestrian points (Tefft 2011)."""
    v = np.array([23, 32, 42, 50, 58], float)
    p = np.array([0.10, 0.25, 0.50, 0.75, 0.90])
    b, a = np.polyfit(v, np.log(p / (1 - p)), 1)
    return a, b


def death_risk(speed: pd.Series) -> pd.Series:
    a, b = death_risk_curve()
    return (1 / (1 + np.exp(-(a + b * speed.astype(float))))).round(3)


def score_harm(f: gpd.GeoDataFrame, fit: dict, node_map: pd.DataFrame) -> gpd.GeoDataFrame:
    """Per segment: block EB rate, worst end-intersection EB rate, and harm_score 0 to 100."""
    out = f.copy()
    bu, iu = fit["blocks"], fit["intersections"]
    out["unit"] = out["dc_blockkey"].fillna("seg:" + out["seg_id"].astype(str))
    for col in ["eb_per_km_yr", "mu_per_km_yr", "crashes", "ksi", "crossings_per_km"]:
        out["block_" + col] = out["unit"].map(bu[col])
    # worse of the two end intersections
    node_to_int = node_map
    ends = pd.concat([
        out[["seg_id", "osm_u"]].rename(columns={"osm_u": "node"}),
        out[["seg_id", "osm_v"]].rename(columns={"osm_v": "node"}),
    ])
    ends = ends.merge(node_to_int, on="node")
    ends = ends.join(iu[["eb_per_yr", "mu_per_yr", "crashes", "ksi", "names"]], on="int_id")
    ends = ends.sort_values("eb_per_yr", ascending=False).drop_duplicates("seg_id").set_index("seg_id")
    out["node_eb_per_yr"] = out["seg_id"].map(ends["eb_per_yr"]).fillna(0.0)
    out["node_mu_per_yr"] = out["seg_id"].map(ends["mu_per_yr"]).fillna(0.0)
    out["node_crashes_5yr"] = out["seg_id"].map(ends["crashes"]).fillna(0).astype(int)
    out["node_ksi_5yr"] = out["seg_id"].map(ends["ksi"]).fillna(0).astype(int)
    out["node_int_id"] = out["seg_id"].map(ends["int_id"])
    out["node_names"] = out["seg_id"].map(ends["names"])
    out["crashes_5yr"] = out["block_crashes"].fillna(0).astype(int)
    out["ksi_5yr"] = out["block_ksi"].fillna(0).astype(int)

    bp = weighted_pct(out["block_eb_per_km_yr"].fillna(0), out["length_m"])
    npct = weighted_pct(out["node_eb_per_yr"], out["length_m"])
    out["block_pct"] = bp
    out["node_pct"] = npct
    # a segment is as risky as its worst part; re-rank so harm_score 90 means the worst
    # 10 percent of network length
    out["harm_score"] = (100 * weighted_pct(pd.Series(np.maximum(bp, npct), index=out.index), out["length_m"])).round(1)
    out["harm_driver"] = np.where(npct > bp, "intersection", "block")
    out["death_risk_if_struck"] = death_risk(out["street_speed_mph"])
    return out


# ------------------------------------------------------ Stage 5: gap, reasons
THRESHOLDS = {"harm_high": 92.0, "harm_low": 40.0}  # tuned so hidden_danger is about 5% of network length


def gap(h: gpd.GeoDataFrame, harm_high: float | None = None, harm_low: float | None = None) -> gpd.GeoDataFrame:
    hi = THRESHOLDS["harm_high"] if harm_high is None else harm_high
    lo = THRESHOLDS["harm_low"] if harm_low is None else harm_low
    out = h.copy()
    lts, hs = out["comfort_lts"], out["harm_score"]
    out["gap_class"] = np.select(
        [(lts <= 2) & (hs >= hi), (lts >= 3) & (hs >= hi), (lts == 4) & (hs <= lo), (lts <= 2) & (hs <= lo)],
        ["hidden_danger", "fix_first", "scary_but_quiet", "calm"], "middle")
    out["reasons"] = out.apply(_reasons, axis=1)
    return out


def _n(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "es" if noun.endswith("sh") else "s")


def _reasons(r) -> str:
    out = []
    f = r.facility
    if f == "separated":
        out.append("separated " + ("one-way" if r.osm_oneway else "two-way") + " path" if r.osm_highway != "cycleway" else "separated " + ("one-way" if r.osm_oneway else "two-way") + " track")
    elif f == "protected":
        out.append(f"protected lane, {_n(int(r.lanes), 'lane')} at {int(r.speed_mph)} mph")
    elif f in ("painted", "buffered"):
        kind = "buffered lane" if f == "buffered" else "painted lane"
        out.append(f"{_n(int(r.lanes), 'lane')} at {int(r.speed_mph)} mph, {kind}" + (" beside parked cars" if r.door_zone else ""))
    elif f == "sharrow":
        out.append(f"sharrows only, {_n(int(r.lanes), 'lane')} at {int(r.speed_mph)} mph")
    else:
        out.append(f"mixed traffic, {_n(int(r.lanes), 'lane')} at {int(r.speed_mph)} mph" + (", beside a separate track" if r.parallel_track else ""))
    if r.harm_driver == "intersection" and r.node_crashes_5yr > 0:
        where = f" at {r.node_names}" if isinstance(r.node_names, str) and r.node_names else ""
        out.append(f"{_n(int(r.node_crashes_5yr), 'injury crash')}{where} since Oct 2021 ({int(r.node_ksi_5yr)} serious)")
    if r.crashes_5yr > 0:
        out.append(f"{_n(int(r.crashes_5yr), 'injury crash')} on this block since Oct 2021 ({int(r.ksi_5yr)} serious)")
    elif r.harm_driver == "block" and r.harm_score >= 60:
        out.append("design matches blocks that see crashes")
    cpk = r.block_crossings_per_km
    if pd.notna(cpk) and cpk >= 20 and len(out) < 3:
        out.append(f"crossed by {int(round(cpk))} intersections per km")
    return "; ".join(out[:3])


# ------------------------------------------- Stage 6: results, validation, map
RESULT_COLS = [
    "osm_u", "osm_v", "osm_key", "snapshot_date", "comfort_score", "comfort_lts", "kid_ok", "harm_score",
    "harm_driver", "crashes_5yr", "ksi_5yr", "node_crashes_5yr", "node_ksi_5yr", "death_risk_if_struck",
    "gap_class", "reasons", "confidence", "speed_mph", "speed_src", "lanes", "lanes_src", "facility",
    "facility_src", "door_zone", "parallel_track", "lts_v1", "dc_blockkey",
]


def results(g: gpd.GeoDataFrame, path: pathlib.Path | None = None) -> pd.DataFrame:
    """The hand-in table, one row per snapshot segment."""
    out = pd.DataFrame(g[RESULT_COLS]).copy()
    out["lts_v1"] = out["lts_v1"].astype("Int64")
    assert len(out) == len(g)
    assert not out.duplicated(["osm_u", "osm_v", "osm_key"]).any()
    assert out[["comfort_score", "harm_score", "gap_class"]].notna().all().all()
    if path:
        out.to_parquet(path, index=False)
    return out


def _capture(rank_key: pd.Series, weight: pd.Series, hits: pd.Series, share: float, seed: int = 0) -> tuple[float, np.ndarray, np.ndarray]:
    """Share of `hits` inside the worst `share` of `weight`, ranking by rank_key descending.

    Ties break at random with a fixed seed. Also returns the full capture curve.
    """
    rng = np.random.default_rng(seed)
    order = np.lexsort((rng.random(len(rank_key)), -rank_key.fillna(-np.inf).values))
    w = np.cumsum(weight.values[order]) / weight.sum()
    h = np.cumsum(hits.values[order]) / max(hits.sum(), 1)
    idx = np.searchsorted(w, share)
    return float(h[min(idx, len(h) - 1)]), w, h


def validate(f: gpd.GeoDataFrame, clusters: gpd.GeoDataFrame, approaches: pd.DataFrame, node_map: pd.DataFrame,
             crashes: gpd.GeoDataFrame, share: float = 0.10) -> tuple[pd.DataFrame, dict]:
    """Train before 2025, test from 2025. Which ranking catches the test crashes?

    (a) LTS v1 and (b) comfort are design-only. (c) is the design-only expectation from the
    crash model. (d) is EB with train history, so it measures persistence, not design.
    """
    train = crashes[crashes["date"] < TEST_START]
    test = crashes[crashes["date"] >= TEST_START]
    fit = harm(f, clusters, approaches, train, years=period_years(train, end=TEST_START))
    bu, iu = fit["blocks"], fit["intersections"]

    seg = f.copy()
    seg["unit"] = seg["dc_blockkey"].fillna("seg:" + seg["seg_id"].astype(str))
    street = seg[~seg["off_street"]] if (~seg["off_street"]).any() else seg
    bu["lts_v1_worst"] = street.groupby("unit")["lts_v1"].max().reindex(bu.index).astype(float)
    bu["lts_v1_worst"] = bu["lts_v1_worst"].fillna(seg.groupby("unit")["lts_v1"].max().reindex(bu.index).astype(float))
    bu["comfort_worst"] = seg.groupby("unit")["comfort_score"].min().reindex(bu.index)
    tb = test[test["path"].isin(["blockkey", "nearest_segment"])].groupby("unit")
    bu["test_crashes"] = tb.size().reindex(bu.index).fillna(0)
    bu["test_ksi"] = tb["ksi"].sum().reindex(bu.index).fillna(0)

    ia = approaches.merge(seg[["seg_id", "lts_v1", "comfort_score"]], on="seg_id").groupby("int_id")
    iu["lts_v1_worst"] = ia["lts_v1"].max().reindex(iu.index).astype(float)
    iu["comfort_worst"] = ia["comfort_score"].min().reindex(iu.index)
    ti = test[test["path"] == "intersection"].groupby("int_id")
    iu["test_crashes"] = ti.size().reindex(iu.index).fillna(0)
    iu["test_ksi"] = ti["ksi"].sum().reindex(iu.index).fillna(0)

    methods = {
        "a. LTS v1 (design only)": lambda u: u["lts_v1_worst"],
        "b. Feels comfort (design only)": lambda u: -u["comfort_worst"],
        "c. Harm model expectation mu (design only)": lambda u: u["mu_per_km_yr"] if "mu_per_km_yr" in u else u["mu_per_yr"],
        "d. Empirical Bayes with train history": lambda u: u["eb_per_km_yr"] if "eb_per_km_yr" in u else u["eb_per_yr"],
    }
    rows, curves = [], {}
    for kind, u, weight in [("blocks", bu, bu["length_km"]), ("intersections", iu, pd.Series(1.0, index=iu.index))]:
        for name, key in methods.items():
            inj, w, h = _capture(key(u), weight, u["test_crashes"], share)
            ksi, _, hk = _capture(key(u), weight, u["test_ksi"], share)
            rows.append({"unit": kind, "method": name, "injury_capture": round(inj, 3), "ksi_capture": round(ksi, 3)})
            curves[(kind, name)] = (w, h, hk)
    board = pd.DataFrame(rows)
    board.attrs["test_crashes"] = int(len(test))
    board.attrs["test_ksi"] = int(test["ksi"].sum())
    board.attrs["train_crashes"] = int(len(train))
    return board, curves


WEB_FIELDS = ["name", "street_key", "ward", "trend", "crashes_before", "crashes_after", "changed", "changed_what", "planned", "comfort_score", "comfort_lts", "kid_ok", "harm_score", "harm_driver", "crashes_5yr", "ksi_5yr",
              "node_crashes_5yr", "node_ksi_5yr", "death_risk_if_struck", "gap_class", "reasons", "confidence",
              "speed_mph", "facility"]


def _round_geojson(gdf: gpd.GeoDataFrame, path: pathlib.Path, places: int = 5) -> None:
    import shapely

    g = gdf.copy()
    g["geometry"] = shapely.transform(g.geometry.values, lambda c: np.round(c, places))
    g.to_file(path, driver="GeoJSON")


def export_web(g: gpd.GeoDataFrame, fit: dict, out_dir: pathlib.Path = CACHE / "web", ward: pd.Series | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    g = g.copy()
    g["street_key"] = street_key(g["name"])
    g["ward"] = ward.values if ward is not None else ""
    for col in WEB_FIELDS:
        if col not in g:
            g[col] = "too few" if col == "trend" else (0 if col.startswith("crashes_") else None)
    seg = g[[*WEB_FIELDS, "geometry"]].copy()
    seg["geometry"] = seg.geometry.to_crs(METRIC_CRS).simplify(1.0).to_crs("EPSG:4326")
    seg["kid_ok"] = seg["kid_ok"].astype(int)
    seg["death_risk_if_struck"] = seg["death_risk_if_struck"].round(2)
    _round_geojson(seg, out_dir / "segments.geojson")
    iu = fit["intersections"]
    pts = iu[iu["crashes"] > 0][["names", "crashes", "ksi", "mu", "eb", "n_approaches", "geometry"]].copy()
    pts = gpd.GeoDataFrame(pts, geometry="geometry", crs=METRIC_CRS).to_crs("EPSG:4326")
    pts[["mu", "eb"]] = pts[["mu", "eb"]].round(2)
    _round_geojson(pts.reset_index(), out_dir / "intersections.geojson")
    return {"segments": int(len(seg)), "intersections": int(len(pts))}


def stories(g: gpd.GeoDataFrame, fit: dict, crashes: gpd.GeoDataFrame | None = None) -> list[dict]:
    """Fly-to targets for the map, kept only when the numbers support them."""
    out = []
    w = g.to_crs("EPSG:4326")

    def centre(sub):
        c = sub.geometry.union_all().centroid
        return [round(c.x, 5), round(c.y, 5)]

    hd = w[w["gap_class"] == "hidden_danger"]
    if len(hd):
        top_unit = hd.groupby("unit")["crashes_5yr"].max().sort_values(ascending=False).index[0]
        sub = hd[hd["unit"] == top_unit]
        r = sub.sort_values("harm_score", ascending=False).iloc[0]
        out.append({"title": f"{r['name']}: hidden danger", "sub": f"LTS {int(r.comfort_lts)}, comfort {r.comfort_score:.0f}, {int(r.crashes_5yr)} injury crashes on one block since Oct 2021 ({int(r.ksi_5yr)} serious)",
                    "center": centre(sub), "zoom": 16.5, "layer": "gap"})
    iu = fit["intersections"]
    top = iu.sort_values("eb_per_yr", ascending=False).iloc[0]
    pt = gpd.GeoSeries([top.geometry], crs=METRIC_CRS).to_crs("EPSG:4326").iloc[0]
    out.append({"title": f"{top['names']}: worst intersection", "sub": f"{int(top.crashes)} injury crashes since Oct 2021 ({int(top.ksi)} serious), {top.mu:.1f} expected for its design",
                "center": [round(pt.x, 5), round(pt.y, 5)], "zoom": 17, "layer": "is"})
    m = iu["names"].astype(str).str.contains("21st Street Northwest") & iu["names"].astype(str).str.contains("I Street Northwest")
    if m.any() and crashes is not None:
        r = iu[m].sort_values("crashes", ascending=False).iloc[0]
        pt = gpd.GeoSeries([r.geometry], crs=METRIC_CRS).to_crs("EPSG:4326").iloc[0]
        near = crashes.to_crs(METRIC_CRS)
        near = near[near.distance(r.geometry) <= 120]
        if len(near):
            out.append({"title": "21st & I St NW: two blocks from here",
                        "sub": f"{_n(len(near), 'injury crash')} within 120 m since Oct 2021 ({int(near.ksi.sum())} serious). The July 2022 truck death is not recorded as a bicyclist fatality in this layer",
                        "center": [round(pt.x, 5), round(pt.y, 5)], "zoom": 17, "layer": "gap"})
    cy = g.geometry.to_crs(METRIC_CRS).centroid.to_crs("EPSG:4326").y
    ca = w[(w["name"].astype(str).str.contains("Connecticut Avenue")) & (cy.between(38.92, 38.945))]
    if len(ca) and ca["crashes_5yr"].sum() > 0:
        n = ca.drop_duplicates("unit")["crashes_5yr"].sum()
        out.append({"title": "Connecticut Ave NW: the lanes that were dropped", "sub": f"{int(n)} injury crashes on these blocks since Oct 2021; mostly LTS {int(ca.comfort_lts.mode().iloc[0])}. DDOT shelved its protected lanes in April 2024",
                    "center": centre(ca), "zoom": 14.5, "layer": "feels"})
    return out


# ------------------------------------------------------- Street and ward reports
_ABBR = {
    r"\bSt\b": "Street", r"\bAve\b": "Avenue", r"\bRd\b": "Road", r"\bPl\b": "Place", r"\bDr\b": "Drive",
    r"\bBlvd\b": "Boulevard", r"\bPkwy\b": "Parkway", r"\bTer\b": "Terrace", r"\bCt\b": "Court", r"\bLn\b": "Lane",
    r"\bNW\b": "Northwest", r"\bNE\b": "Northeast", r"\bSW\b": "Southwest", r"\bSE\b": "Southeast",
}


def street_key(name: pd.Series) -> pd.Series:
    """Fold '15th St NW', '15th Street Northwest' and '15th Street Northwest Cycle Track' together."""
    s = name.astype(str).str.strip()
    s = s.str.replace(r"\s+(Cycle ?Track|Cycleway|Bike ?Path|Trail Connector)$", "", regex=True, case=False)
    for pat, rep in _ABBR.items():
        s = s.str.replace(pat, rep, regex=True)
    return s.str.replace(r"\s+", " ", regex=True)


def _cross(node_names: object, own: str) -> str:
    if not isinstance(node_names, str) or not node_names:
        return ""
    parts = [p for p in node_names.split(" & ") if street_key(pd.Series([p])).iloc[0] != own]
    return parts[0] if parts else node_names


def _report(sub: gpd.GeoDataFrame, iu: pd.DataFrame, approaches: pd.DataFrame, crashes: gpd.GeoDataFrame,
            years: float, own: str | None, net_rate: float, projects: pd.DataFrame | None = None,
            seg_project: pd.DataFrame | None = None) -> dict:
    w = sub.geometry.to_crs("EPSG:4326")
    km = float(sub["length_m"].sum() / 1000)
    units = sub.drop_duplicates("unit")
    ints = iu.loc[iu.index.isin(approaches[approaches["seg_id"].isin(sub["seg_id"])]["int_id"].unique())]
    c = crashes[crashes["unit"].isin(units["unit"]) | crashes["int_id"].isin(ints.index)]
    by_year = c["date"].dt.year.value_counts().sort_index()
    kmsplit = lambda col: {str(k): round(v / 1000, 2) for k, v in sub.groupby(col)["length_m"].sum().items()}
    blocks = (sub.sort_values("harm_score", ascending=False).drop_duplicates("unit").head(8))
    worst_blocks = []
    for _, r in blocks.iterrows():
        cen = w.loc[r.name].centroid if False else sub.loc[[r.name]].geometry.to_crs(METRIC_CRS).centroid.to_crs("EPSG:4326").iloc[0]
        worst_blocks.append({
            "at": _cross(r["node_names"], own) if own else (r["node_names"] if isinstance(r["node_names"], str) else ""), "name": r["name"], "gap": r["gap_class"],
            "harm": float(r["harm_score"]), "lts": int(r["comfort_lts"]), "comfort": float(r["comfort_score"]),
            "crashes": int(r["crashes_5yr"]), "ksi": int(r["ksi_5yr"]), "node_crashes": int(r["node_crashes_5yr"]),
            "facility": r["facility"], "reasons": r["reasons"], "center": [round(cen.x, 5), round(cen.y, 5)],
        })
    wi = ints[ints["crashes"] > 0].sort_values("eb_per_yr", ascending=False).head(8)
    pts = gpd.GeoSeries(wi["geometry"], crs=METRIC_CRS).to_crs("EPSG:4326") if len(wi) else []
    worst_ints = [{"names": r["names"], "crashes": int(r["crashes"]), "ksi": int(r["ksi"]), "expected": round(float(r["mu"]), 2),
                   "center": [round(p.x, 5), round(p.y, 5)]} for (_, r), p in zip(wi.iterrows(), pts)]
    rate = float(units["crashes_5yr"].sum() / km / years) if km > 0 else 0.0
    t_b, t_a, base = sub.attrs.get("t_before", 3.25), sub.attrs.get("t_after", 1.75), sub.attrs.get("base_ratio", 1.0)
    before, after = int((c["date"] < TEST_START).sum()), int((c["date"] >= TEST_START).sum())
    tlabel, tratio = trend_label(before, after, t_b, t_a, base)
    changes = []
    if projects is not None and seg_project is not None:
        sp = seg_project[seg_project["seg_id"].isin(sub["seg_id"])]
        for oid, grp in sp.groupby("OBJECTID"):
            p = projects.loc[oid]
            segs = sub[sub["seg_id"].isin(grp["seg_id"])]
            if segs["length_m"].sum() < 100 and len(segs) < 3:
                continue  # a crossing sliver of someone else's project
            ints_p = iu.loc[iu.index.isin(approaches[approaches["seg_id"].isin(segs["seg_id"])]["int_id"].unique())]
            item = {"what": p["label"], "bike": bool(p["bike"]), "status": p["status"], "desc": p["desc"],
                    "completed": p["completed"].strftime("%Y-%m") if pd.notna(p["completed"]) else None,
                    "from": str(p["FROMSTREET"] or "").title(), "to": str(p["TOSTREET"] or "").title(),
                    "km": round(float(segs["length_m"].sum() / 1000), 2), "segments": int(len(segs))}
            item.update(project_before_after(segs["unit"].unique(), ints_p.index, p, crashes, item["km"]))
            changes.append(item)
        changes.sort(key=lambda x: (x["status"] != "completed", -(x["km"] or 0)))
    return {
        "trend": tlabel, "trend_ratio": round(tratio, 2) if np.isfinite(tratio) else None, "base_ratio": round(base, 2),
        "before": before, "after": after, "before_per_yr": round(before / t_b, 1), "after_per_yr": round(after / t_a, 1),
        "changes": changes[:12], "changed_km": round(float(sub.loc[sub["changed"].notna(), "length_m"].sum() / 1000), 2) if "changed" in sub else 0,
        "km": round(km, 2), "segments": int(len(sub)), "blocks": int(len(units)),
        "lts_km": kmsplit("comfort_lts"), "gap_km": kmsplit("gap_class"), "facility_km": kmsplit("facility"),
        "harm": round(float(np.average(sub["harm_score"], weights=sub["length_m"])), 1) if km > 0 else None,
        "comfort": round(float(np.average(sub["comfort_score"], weights=sub["length_m"])), 1) if km > 0 else None,
        "crashes": int(len(c)), "ksi": int(c["ksi"].sum()), "fatal": int(c["fatal"].sum()),
        "block_crashes": int(units["crashes_5yr"].sum()), "int_crashes": int(ints["crashes"].sum()),
        "int_ksi": int(ints["ksi"].sum()), "int_expected": round(float(ints["mu"].sum()), 1), "intersections": int(len(ints)),
        "by_year": {int(k): int(v) for k, v in by_year.items()},
        "rate_per_km_yr": round(rate, 2), "rate_vs_network": round(rate / net_rate, 1) if net_rate else None,
        "speeding": int(c["SPEEDING_INVOLVED"].sum()) if "SPEEDING_INVOLVED" in c else 0,
        "worst_blocks": worst_blocks, "worst_intersections": worst_ints,
    }


def json_safe(obj):
    """NaN and numpy scalars are not JSON; fix them before dumping."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if not np.isfinite(obj) else float(obj)
    if obj is pd.NaT:
        return None
    return obj


def street_reports(g: gpd.GeoDataFrame, fit: dict, approaches: pd.DataFrame, crashes: gpd.GeoDataFrame,
                   ward: pd.Series, min_km: float = 0.4, projects: pd.DataFrame | None = None,
                   seg_project: pd.DataFrame | None = None) -> dict:
    """One report per street (folded across OSM and DDOT spellings), per ward, and for the network."""
    iu, years = fit["intersections"], fit["years"]
    s = g.copy()
    s["street_key"] = street_key(s["name"])
    s["ward"] = ward.values
    net_rate = float(s.drop_duplicates("unit")["crashes_5yr"].sum() / (s["length_m"].sum() / 1000) / years)
    rp = dict(projects=projects, seg_project=seg_project)
    out = {"network": _report(s, iu, approaches, crashes, years, None, net_rate, **rp), "streets": {}, "wards": {}}
    km_by = s.groupby("street_key")["length_m"].sum() / 1000
    cr_by = s.drop_duplicates("unit").groupby("street_key")["crashes_5yr"].sum()
    keep = km_by[(km_by >= min_km) | (cr_by.reindex(km_by.index).fillna(0) >= 2)].index
    for key in keep:
        sub = s[s["street_key"] == key]
        if sub["off_street"].all() and key.lower().startswith(("path", "cycleway", "footway")):
            continue
        sub.attrs = s.attrs
        out["streets"][key] = _report(sub, iu, approaches, crashes, years, key, net_rate, **rp)
    for wd, sub in s.groupby("ward"):
        if pd.isna(wd) or str(wd) in ("", "nan"):
            continue
        sub.attrs = s.attrs
        out["wards"][str(int(float(wd)))] = _report(sub, iu, approaches, crashes, years, None, net_rate, **rp)
    return json_safe(out)


# ----------------------------------------------------- Trend, and changes on the ground
WORKTYPE_LABEL = {
    "CPDO-IPMA-BIKLN": "bike lane project", "CPDO-IPMA-BIKTR": "bike trail project", "CPDO-PSA-IBL": "bike and pedestrian improvement",
    "COO-MA-TPMBIKE": "bike markings", "CPDO-IPMA-SAFE": "safety improvement", "CPDO-MM-SAFETY": "safety maintenance",
    "COO-HSIP-IMP": "highway safety improvement", "CPDO-PSA-SSS": "safe streets study", "CPDO-HS-SPMGT": "speed management",
    "CPDO-IPMA-SGI": "signal improvement", "CPDO-IPMA-PP": "pedestrian project", "CPDO-IPMA-PA": "pedestrian project",
    "CPDO-IPMA-STSC": "streetscape", "COO-NSAMS-ST": "neighborhood safety (NSAMS)", "COO-NSAMS-II": "neighborhood safety (NSAMS)",
    "COO-LIVSTDY-IMP": "livability improvement", "CPDO-IPMA-MUT": "multi-use trail",
}  # routine re-striping (COO-MA-INSTTPM, TPMMISC) is left out: it is not a design change
BIKE_WORKTYPES = {"CPDO-IPMA-BIKLN", "CPDO-IPMA-BIKTR", "CPDO-PSA-IBL", "COO-MA-TPMBIKE", "CPDO-IPMA-MUT"}


def load_projects(g: gpd.GeoDataFrame, path: pathlib.Path = CACHE / "protrack_projects.parquet",
                  snapshot: pathlib.Path = SNAPSHOT) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DDOT ProTrack project lines matched to segments by route and measure, else by proximity.

    Returns (projects, seg_project) where seg_project maps seg_id -> project OBJECTID.
    """
    pr = gpd.read_parquet(path)
    pr = pr[pr["WORKTYPE"].isin(WORKTYPE_LABEL)].copy()
    pr["label"] = pr["WORKTYPE"].map(WORKTYPE_LABEL)
    pr["bike"] = pr["WORKTYPE"].isin(BIKE_WORKTYPES)
    pr["completed"] = pr["ACTUALCOMPLETIONDATE"].dt.tz_localize("UTC") if pr["ACTUALCOMPLETIONDATE"].dt.tz is None else pr["ACTUALCOMPLETIONDATE"]
    pr["status"] = np.where(pr["completed"].notna(), "completed", np.where(pr["PERCENTCOMPLETED"].fillna(0) > 0, "in progress", "planned"))
    pr["desc"] = pr["DESCRIPTION"].fillna("").astype(str).str.split("\n").str[0].str.strip().str.slice(0, 140).replace({"None": "", "nan": ""})
    for c in ("FROMSTREET", "TOSTREET"):
        pr[c] = pr[c].fillna("").astype(str).replace({"None": "", "nan": ""})

    meas = pd.read_parquet(snapshot, columns=["dc_ROUTEID", "dc_FROMMEASURE", "dc_TOMEASURE"]).reset_index(drop=True)
    seg = g[["seg_id"]].copy()
    seg["route"] = meas["dc_ROUTEID"].astype(str).values
    seg["m0"] = meas["dc_FROMMEASURE"].values
    seg["m1"] = meas["dc_TOMEASURE"].values
    pm = pr[["OBJECTID", "ROUTEID", "FROMMEASURE", "TOMEASURE"]].dropna()
    pm["ROUTEID"] = pm["ROUTEID"].astype(str)
    j = seg.dropna(subset=["m0", "m1"]).merge(pm, left_on="route", right_on="ROUTEID")
    lo, hi = np.minimum(j["FROMMEASURE"], j["TOMEASURE"]), np.maximum(j["FROMMEASURE"], j["TOMEASURE"])
    overlap = np.minimum(j["m1"], hi) - np.maximum(j["m0"], lo)
    j = j[overlap > 0.3 * (j["m1"] - j["m0"]).clip(lower=1)]
    by_route = j[["seg_id", "OBJECTID"]]

    # off-street rows and unmatched rows: within 15 m of the project line
    rest = g[~g["seg_id"].isin(by_route["seg_id"])][["seg_id", "geometry"]].to_crs(METRIC_CRS)
    prm = pr[["OBJECTID", "geometry"]].to_crs(METRIC_CRS)
    near = gpd.sjoin(rest, gpd.GeoDataFrame(prm.assign(geometry=prm.buffer(15))), how="inner", predicate="intersects")
    near = near[near.geometry.length > 0]
    # require most of the segment inside the buffer, not a crossing
    inside = near.apply(lambda r: prm.loc[prm["OBJECTID"] == r["OBJECTID"], "geometry"].iloc[0].buffer(15).intersection(r.geometry).length / max(r.geometry.length, 1), axis=1) if len(near) else pd.Series(dtype=float)
    near = near[inside.values >= 0.6] if len(near) else near
    by_space = near[["seg_id", "OBJECTID"]]
    seg_project = pd.concat([by_route, by_space]).drop_duplicates()
    return pr.set_index("OBJECTID"), seg_project


def trend_label(before: float, after: float, t_before: float, t_after: float, base_ratio: float = 1.0) -> tuple[str, float]:
    """Compare annualized crash rates since 2025 with before, relative to the citywide change.

    `base_ratio` is the citywide after/before rate ratio, so 'rising' means rising faster than
    the city as a whole, not just riding the citywide tide. Small counts get 'too few'.
    """
    n = before + after
    rb, ra = before / t_before, after / t_after
    raw = (ra / rb) if rb > 0 else (np.inf if ra > 0 else 1.0)
    ratio = raw / base_ratio
    if n < 3:
        return "too few", ratio
    p_after = (t_after * base_ratio) / (t_before + t_after * base_ratio)
    try:
        from scipy.stats import binomtest
        p = binomtest(int(after), int(n), p_after).pvalue
    except Exception:  # noqa: BLE001
        p = 1.0
    if ratio >= 1.5 and after >= 2:
        return ("rising" if p < 0.2 else "rising?"), ratio
    if ratio <= 0.67 and before >= 2:
        return ("falling" if p < 0.2 else "falling?"), ratio
    return "flat", ratio


def base_trend_ratio(crashes: gpd.GeoDataFrame, split=TEST_START) -> float:
    end = crashes["date"].max()
    t_b, t_a = (split - CRASH_START).days / 365.25, (end - split).days / 365.25
    b, a = int((crashes["date"] < split).sum()), int((crashes["date"] >= split).sum())
    return (a / t_a) / (b / t_b)


def trends(g: gpd.GeoDataFrame, crashes: gpd.GeoDataFrame, fit: dict, node_map: pd.DataFrame, split=TEST_START) -> gpd.GeoDataFrame:
    """Per segment: crashes before and since the split, on its block and at its worst intersection, with a label."""
    out = g.copy()
    end = crashes["date"].max()
    t_b, t_a = (split - CRASH_START).days / 365.25, (end - split).days / 365.25
    base = base_trend_ratio(crashes, split)
    out.attrs["t_before"], out.attrs["t_after"], out.attrs["base_ratio"] = t_b, t_a, base
    early, late = crashes[crashes["date"] < split], crashes[crashes["date"] >= split]
    bl = lambda c: c[c["path"].isin(["blockkey", "nearest_segment"])].groupby("unit").size()
    nd = lambda c: c[c["path"] == "intersection"].groupby("int_id").size()
    out["block_before"] = out["unit"].map(bl(early)).fillna(0).astype(int)
    out["block_after"] = out["unit"].map(bl(late)).fillna(0).astype(int)
    nb, na = nd(early), nd(late)
    out["node_before"] = out["node_int_id"].map(nb).fillna(0).astype(int)
    out["node_after"] = out["node_int_id"].map(na).fillna(0).astype(int)
    before = out["block_before"] + out["node_before"]
    after = out["block_after"] + out["node_after"]
    lab = [trend_label(b, a, t_b, t_a, base) for b, a in zip(before, after)]
    out["trend"] = [x[0] for x in lab]
    out["trend_ratio"] = [round(x[1], 2) if np.isfinite(x[1]) else None for x in lab]
    out["crashes_before"] = before
    out["crashes_after"] = after
    return out


def attach_projects(g: gpd.GeoDataFrame, projects: pd.DataFrame, seg_project: pd.DataFrame) -> gpd.GeoDataFrame:
    """Per segment: the latest completed bike/safety project and whether one is planned or in progress."""
    out = g.copy()
    sp = seg_project.join(projects[["completed", "status", "label", "bike", "desc"]], on="OBJECTID")
    done = sp[sp["status"] == "completed"].sort_values("completed").drop_duplicates("seg_id", keep="last").set_index("seg_id")
    out["changed"] = out["seg_id"].map(done["completed"].dt.strftime("%Y-%m"))
    out["changed_what"] = out["seg_id"].map(done["label"])
    out["changed_desc"] = out["seg_id"].map(done["desc"])
    pend = sp[sp["status"] != "completed"].drop_duplicates("seg_id").set_index("seg_id")
    out["planned"] = out["seg_id"].map(pend["label"])
    out["planned_desc"] = out["seg_id"].map(pend["desc"])
    return out


def project_before_after(units: pd.Series, int_ids: pd.Series, project, crashes: gpd.GeoDataFrame, length_km: float) -> dict:
    """Annualized injury crash rate on the matched blocks and intersections before and after completion."""
    c = crashes[crashes["unit"].isin(units) | crashes["int_id"].isin(int_ids)]
    t = project["completed"]
    if pd.isna(t):
        return {}
    end = crashes["date"].max()
    tb, ta = max((t - CRASH_START).days / 365.25, 0), max((end - t).days / 365.25, 0)
    b, a = int((c["date"] < t).sum()), int((c["date"] >= t).sum())
    return {"before": b, "after": a, "years_before": round(tb, 1), "years_after": round(ta, 1),
            "before_per_yr": round(b / tb, 2) if tb >= 0.5 else None, "after_per_yr": round(a / ta, 2) if ta >= 0.5 else None}


# ------------------------------------------------------------- Landmarks for the map
GBFS_STATIONS = "https://gbfs.lyft.com/gbfs/2.3/dca-cabi/en/station_information.json"
OVERPASS_URLS = ["https://overpass.kumi.systems/api/interpreter", "https://lz4.overpass-api.de/api/interpreter", "https://overpass-api.de/api/interpreter"]
TRAILS_URL = "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_Bikes_Trails_WebMercator/MapServer/4/query"
NPS_TRAILS_URL = "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_Bikes_Trails_WebMercator/MapServer/75/query"
DC_BBOX = (38.79, -77.12, 39.0, -76.90)  # south, west, north, east


def landmarks(out_dir: pathlib.Path = CACHE / "web") -> dict:
    """Capital Bikeshare stations, bike shops (OSM) and trails (DC GIS) as GeoJSON for the map."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    feats = []
    try:
        st = requests.get(GBFS_STATIONS, timeout=30).json()["data"]["stations"]
        s, w, n, e = DC_BBOX
        for x in st:
            if s <= x["lat"] <= n and w <= x["lon"] <= e:
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(x["lon"], 5), round(x["lat"], 5)]},
                              "properties": {"kind": "bikeshare", "name": x.get("name", ""), "capacity": int(x.get("capacity", 0))}})
        counts["bikeshare"] = len(feats)
    except Exception as exc:  # noqa: BLE001
        counts["bikeshare_error"] = str(exc)[:80]
    try:
        s, w, n, e = DC_BBOX
        q = f'[out:json][timeout:60];(node["shop"="bicycle"]({s},{w},{n},{e});way["shop"="bicycle"]({s},{w},{n},{e}););out center;'
        r = None
        for url in OVERPASS_URLS:
            try:
                r = requests.post(url, data={"data": q}, timeout=90, headers={"User-Agent": "feels-vs-is/1.0 (ridescore dc hackathon)"}).json()
                break
            except Exception:  # noqa: BLE001
                continue
        if r is None:
            raise RuntimeError("all overpass mirrors failed")
        k = 0
        for el in r.get("elements", []):
            lat, lon = (el.get("lat"), el.get("lon")) if el["type"] == "node" else (el.get("center", {}).get("lat"), el.get("center", {}).get("lon"))
            if lat is None:
                continue
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                          "properties": {"kind": "shop", "name": el.get("tags", {}).get("name", "Bike shop")}})
            k += 1
        counts["shops"] = k
    except Exception as exc:  # noqa: BLE001
        counts["shops_error"] = str(exc)[:80]
    json.dump({"type": "FeatureCollection", "features": feats}, open(out_dir / "landmarks.geojson", "w"), separators=(",", ":"))

    trails = []
    for url, src, name_field in [(TRAILS_URL, "dc", "NAME"), (NPS_TRAILS_URL, "nps", "TRLNAME")]:
        try:
            r = requests.get(url, params={"where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson", "resultRecordCount": 2000}, timeout=90).json()
            for f in r.get("features", []):
                p = f.get("properties", {}) or {}
                nm = next((p[k] for k in (name_field, "NAME", "TRAIL_NAME", "LOCAL_NAME", "FMSS_NAME", "SEGMENT_NA", "UNIT_NAME") if p.get(k)), "")
                if not f.get("geometry"):
                    continue
                g = f["geometry"]
                g["coordinates"] = json.loads(json.dumps(g["coordinates"]), parse_float=lambda v: round(float(v), 5))
                trails.append({"type": "Feature", "geometry": g, "properties": {"name": str(nm).title(), "src": src}})
            counts["trails_" + src] = len(r.get("features", []))
        except Exception as exc:  # noqa: BLE001
            counts["trails_" + src + "_error"] = str(exc)[:80]
    json.dump({"type": "FeatureCollection", "features": trails}, open(out_dir / "trails.geojson", "w"), separators=(",", ":"))
    return counts
