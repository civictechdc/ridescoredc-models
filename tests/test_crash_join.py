"""Crashes attaching to streets."""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point

from ridescore.network import crash_join

CRS = "EPSG:4326"


def segments(lines: list[LineString]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"segment_id": [str(i) for i in range(len(lines))]}, geometry=lines, crs=CRS
    )


def crashes(points: list[Point], serious: list[int] | None = None,
            fatal: list[int] | None = None) -> gpd.GeoDataFrame:
    n = len(points)
    return gpd.GeoDataFrame(
        {
            "major_injuries_bicyclist": serious or [0] * n,
            "fatal_bicyclist": fatal or [0] * n,
        },
        geometry=points,
        crs=CRS,
    )


def test_a_crash_on_a_street_is_counted():
    street = LineString([(-77.00, 38.90), (-77.00, 38.91)])
    joined = crash_join.count_crashes_near_segments(
        segments([street]), crashes([Point(-77.00, 38.905)])
    )
    assert joined["crash_count_5yr"].tolist() == [1]


def test_a_crash_far_away_is_not():
    street = LineString([(-77.00, 38.90), (-77.00, 38.91)])
    joined = crash_join.count_crashes_near_segments(
        segments([street]), crashes([Point(-76.90, 38.905)])
    )
    assert joined["crash_count_5yr"].tolist() == [0]


def test_a_crash_at_a_corner_counts_for_both_streets():
    """Deliberate: the crash happened at the junction of both."""
    corner = Point(-77.00, 38.90)
    north = LineString([(-77.00, 38.90), (-77.00, 38.91)])
    east = LineString([(-77.00, 38.90), (-76.99, 38.90)])
    joined = crash_join.count_crashes_near_segments(segments([north, east]), crashes([corner]))
    assert joined["crash_count_5yr"].tolist() == [1, 1]


def test_serious_and_fatal_are_counted_separately():
    street = LineString([(-77.00, 38.90), (-77.00, 38.91)])
    three = [Point(-77.00, 38.902), Point(-77.00, 38.905), Point(-77.00, 38.908)]
    joined = crash_join.count_crashes_near_segments(
        segments([street]), crashes(three, serious=[1, 0, 1], fatal=[0, 0, 1])
    )
    assert joined["crash_count_5yr"].tolist() == [3]
    assert joined["serious_injury_count_5yr"].tolist() == [2]
    assert joined["fatal_count_5yr"].tolist() == [1]


def test_no_crashes_at_all_is_zero_not_missing():
    street = LineString([(-77.00, 38.90), (-77.00, 38.91)])
    joined = crash_join.count_crashes_near_segments(segments([street]), crashes([]))
    for column in crash_join.COUNT_COLUMNS:
        assert joined[column].tolist() == [0]
